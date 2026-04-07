"""Fund comparison engine — side-by-side analysis of 2-4 funds.

Computes comparative metrics (return, Sharpe ratio, max drawdown,
sector allocation deltas) and runs Brinson attribution on each fund.
Optionally generates a Traditional Chinese AI explanation.

Technical notes (from spec):
  - MoneyDJ NAV data is HIGH risk (HTML scraping) — marked TODO for post-MVP.
  - Sharpe/MaxDD: simplified from available period returns.
    Full time-series calculation is post-MVP.
"""

import logging
from typing import List, Dict, Optional

import pandas as pd

from interfaces import FundMetrics, FundComparison
from engine.brinson import compute_attribution

logger = logging.getLogger(__name__)

MIN_FUNDS = 2
MAX_FUNDS = 4

# Risk-free rate assumption for Sharpe ratio (Taiwan 1Y T-bill approx)
RISK_FREE_RATE = 0.01


def compare_funds(
    fund_codes: List[str],
    holdings_map: Dict[str, pd.DataFrame],
    period: str = "",
    mode: str = "BF2",
    generate_ai: bool = True,
    api_key: Optional[str] = None,
) -> FundComparison:
    """Compare 2-4 funds side-by-side.

    Args:
        fund_codes: List of fund codes to compare (2-4).
        holdings_map: {fund_code: DataFrame} with columns
            [industry, Wp, Wb, Rp, Rb] for each fund.
        period: Period string (e.g. "2026-03") for labelling.
        mode: Brinson mode ("BF2" or "BF3").
        generate_ai: Whether to generate AI comparison explanation.
        api_key: Anthropic API key (optional, uses env default).

    Returns:
        FundComparison with metrics, attribution results, diffs,
        and AI explanation.

    Raises:
        ValueError: If fund_codes count is not 2-4.
    """
    if len(fund_codes) < MIN_FUNDS or len(fund_codes) > MAX_FUNDS:
        raise ValueError(
            f"Fund count must be {MIN_FUNDS}-{MAX_FUNDS}, got {len(fund_codes)}"
        )

    fund_metrics: List[FundMetrics] = []
    attribution_results: Dict[str, dict] = {}
    skipped: List[str] = []

    for code in fund_codes:
        if code not in holdings_map:
            logger.warning("Fund %s: no holdings data — skipping", code)
            skipped.append(code)
            continue

        holdings = holdings_map[code]

        # Compute Brinson attribution
        try:
            result = compute_attribution(holdings, mode=mode)
        except (ValueError, AssertionError) as e:
            logger.warning("Fund %s: attribution failed — %s — skipping", code, e)
            skipped.append(code)
            continue

        attribution_results[code] = result

        # Extract sector weights from holdings
        sector_weights = dict(zip(
            holdings["industry"].tolist(),
            holdings["Wp"].astype(float).tolist(),
        ))

        total_return = result["fund_return"]

        # Simplified Sharpe ratio from single-period excess return
        # Full time-series Sharpe is post-MVP (TODO(#37): MoneyDJ NAV integration)
        sharpe = _compute_simple_sharpe(total_return)

        # Simplified max drawdown placeholder — single period has no drawdown
        # TODO(#37): compute from NAV time series when MoneyDJ data is available
        max_drawdown = None

        fund_metrics.append(FundMetrics(
            fund_code=code,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_drawdown,
            sector_weights=sector_weights,
        ))

    # Need at least 2 funds with valid data to compare
    if len(fund_metrics) < MIN_FUNDS:
        raise ValueError(
            f"Need at least {MIN_FUNDS} funds with valid data, "
            f"got {len(fund_metrics)} (skipped: {skipped})"
        )

    # Compute pairwise attribution diffs
    attribution_diffs = _compute_attribution_diffs(attribution_results)

    # Generate AI explanation
    ai_explanation = ""
    if generate_ai and len(fund_metrics) >= MIN_FUNDS:
        ai_explanation = _generate_comparison_explanation(
            fund_metrics, attribution_results, api_key=api_key
        )

    return FundComparison(
        funds=fund_metrics,
        attribution_results=attribution_results,
        attribution_diffs=attribution_diffs,
        ai_explanation=ai_explanation,
    )


def _compute_simple_sharpe(total_return: float) -> float:
    """Simplified Sharpe ratio from single-period return.

    Uses (return - risk_free) as numerator. Without time-series data,
    we cannot compute volatility, so we use excess return directly
    as a relative ranking metric.
    """
    return total_return - RISK_FREE_RATE


def _compute_attribution_diffs(
    results: Dict[str, dict],
) -> Dict[str, dict]:
    """Compute pairwise diffs between fund attribution results.

    Returns dict keyed by "A_vs_B" with allocation/selection/excess deltas.
    """
    codes = list(results.keys())
    diffs: Dict[str, dict] = {}

    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            a, b = codes[i], codes[j]
            ra, rb = results[a], results[b]

            key = f"{a}_vs_{b}"
            diffs[key] = {
                "fund_a": a,
                "fund_b": b,
                "excess_return_diff": ra["excess_return"] - rb["excess_return"],
                "allocation_diff": ra["allocation_total"] - rb["allocation_total"],
                "selection_diff": ra["selection_total"] - rb["selection_total"],
                "sector_diffs": _compute_sector_diffs(ra, rb),
            }

    return diffs


def _compute_sector_diffs(result_a: dict, result_b: dict) -> Dict[str, dict]:
    """Compute per-sector allocation and contribution diffs between two funds."""
    detail_a = result_a["detail"].set_index("industry")
    detail_b = result_b["detail"].set_index("industry")

    all_sectors = set(detail_a.index) | set(detail_b.index)
    sector_diffs: Dict[str, dict] = {}

    for sector in all_sectors:
        wp_a = detail_a.loc[sector, "Wp"] if sector in detail_a.index else 0.0
        wp_b = detail_b.loc[sector, "Wp"] if sector in detail_b.index else 0.0
        contrib_a = detail_a.loc[sector, "total_contrib"] if sector in detail_a.index else 0.0
        contrib_b = detail_b.loc[sector, "total_contrib"] if sector in detail_b.index else 0.0

        sector_diffs[sector] = {
            "weight_diff": float(wp_a - wp_b),
            "contribution_diff": float(contrib_a - contrib_b),
        }

    return sector_diffs


def _generate_comparison_explanation(
    funds: List[FundMetrics],
    attribution_results: Dict[str, dict],
    api_key: Optional[str] = None,
) -> str:
    """Generate Traditional Chinese AI comparison explanation.

    Falls back to a rule-based template if Claude API is unavailable.
    """
    try:
        from ai.claude_client import generate_summary as _generate_summary
    except ImportError:
        logger.warning("AI module not available — using template explanation")
        return _template_explanation(funds, attribution_results)

    # Build comparison-specific prompt
    prompt_data = _build_comparison_prompt_data(funds, attribution_results)

    try:
        import anthropic
        from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS

        key = api_key or ANTHROPIC_API_KEY
        if not key:
            return _template_explanation(funds, attribution_results)

        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            timeout=AI_TIMEOUT_SECONDS,
            messages=[{"role": "user", "content": prompt_data}],
        )
        return message.content[0].text

    except Exception as e:
        logger.warning("AI comparison failed: %s — using template", e)
        return _template_explanation(funds, attribution_results)


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _build_comparison_prompt_data(
    funds: List[FundMetrics],
    attribution_results: Dict[str, dict],
) -> str:
    """Build a comparison prompt for Claude API."""
    fund_lines = []
    for fm in funds:
        r = attribution_results.get(fm.fund_code, {})
        fund_lines.append(
            f"- {fm.fund_code}: 報酬率 {_fmt_pct(fm.total_return)}, "
            f"超額 {_fmt_pct(r.get('excess_return', 0))}, "
            f"配置效果 {_fmt_pct(r.get('allocation_total', 0))}, "
            f"選股效果 {_fmt_pct(r.get('selection_total', 0))}"
        )

    return f"""你是一位資深投資研究總監，正在為台灣理財顧問比較以下基金：

{chr(10).join(fund_lines)}

## 規則
1. 禁止使用: Brinson, attribution, allocation effect, selection effect
2. 改用: 市場佈局、選股能力、產業配置
3. 僅使用上方提供的精確數字

## 任務
用 200-300 字繁體中文說明「為何選 A 不選 B」，比較各基金的優劣勢。
語氣專業但易懂，適合理財顧問向客戶解釋。"""


def _template_explanation(
    funds: List[FundMetrics],
    attribution_results: Dict[str, dict],
) -> str:
    """Rule-based fallback comparison explanation."""
    sorted_funds = sorted(funds, key=lambda f: f.total_return, reverse=True)
    best = sorted_funds[0]
    rest = sorted_funds[1:]

    lines = [f"基金比較摘要（共 {len(funds)} 檔基金）：\n"]

    best_result = attribution_results.get(best.fund_code, {})
    lines.append(
        f"表現最佳：{best.fund_code}，報酬率 {_fmt_pct(best.total_return)}，"
        f"超額報酬 {_fmt_pct(best_result.get('excess_return', 0))}。"
    )

    for fm in rest:
        r = attribution_results.get(fm.fund_code, {})
        diff = best.total_return - fm.total_return
        lines.append(
            f"{fm.fund_code}：報酬率 {_fmt_pct(fm.total_return)}，"
            f"落後 {_fmt_pct(diff)}。"
            f"配置效果 {_fmt_pct(r.get('allocation_total', 0))}，"
            f"選股效果 {_fmt_pct(r.get('selection_total', 0))}。"
        )

    return "\n".join(lines)
