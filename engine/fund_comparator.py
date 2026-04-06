"""Fund comparison engine — side-by-side analysis of 2-4 funds.

Computes comparative metrics: returns, Sharpe ratio, max drawdown,
sector allocation diffs, and Brinson attribution differences.
Generates AI explanation of "why choose A over B."
"""

import logging
import math
from typing import Optional

import pandas as pd

from interfaces import FundMetrics, FundComparison

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.01  # Annual risk-free rate (approx Taiwan 1Y deposit)


def compare_funds(
    holdings_map: dict[str, pd.DataFrame],
    period: str = "",
    ai_api_key: Optional[str] = None,
) -> FundComparison:
    """Compare 2-4 funds side-by-side.

    Args:
        holdings_map: {fund_code: holdings_df} where holdings_df has
            columns [industry, Wp, Wb, Rp, Rb].
        period: Analysis period string.
        ai_api_key: Optional API key for AI explanation.

    Returns:
        FundComparison with metrics, diffs, and AI explanation.

    Raises:
        ValueError: If fewer than 2 or more than 4 funds provided.
    """
    if len(holdings_map) < 2:
        raise ValueError("At least 2 funds required for comparison")
    if len(holdings_map) > 4:
        raise ValueError("Maximum 4 funds for comparison")

    # Compute metrics for each fund
    fund_metrics = []
    for fund_code, holdings in holdings_map.items():
        try:
            metrics = _compute_fund_metrics(fund_code, holdings)
            fund_metrics.append(metrics)
        except Exception as e:
            logger.warning("Skipping fund %s: %s", fund_code, e)
            fund_metrics.append(FundMetrics(
                fund_code=fund_code,
                total_return=0.0,
            ))

    # Compute attribution diffs (pairwise against first fund)
    attribution_diffs = _compute_attribution_diffs(fund_metrics)

    # Generate AI explanation
    ai_explanation = _generate_comparison_explanation(fund_metrics, ai_api_key)

    return FundComparison(
        funds=fund_metrics,
        attribution_diffs=attribution_diffs,
        ai_explanation=ai_explanation,
    )


def _compute_fund_metrics(fund_code: str, holdings: pd.DataFrame) -> FundMetrics:
    """Compute metrics for a single fund."""
    from engine.brinson import compute_attribution

    # Run Brinson attribution
    result = compute_attribution(holdings, mode="BF2")

    total_return = result["fund_return"]
    sector_weights = dict(zip(holdings["industry"], holdings["Wp"]))

    # Simplified Sharpe ratio (single-period)
    # Sharpe = (Rp - Rf) / volatility
    # For single period, use excess return magnitude as proxy
    excess = result["excess_return"]
    # Simple volatility proxy: std of industry contributions
    detail = result["detail"]
    if len(detail) > 1:
        vol = detail["total_contrib"].std()
        sharpe = (total_return - RISK_FREE_RATE / 12) / vol if vol > 0 else None
    else:
        sharpe = None

    # Simplified max drawdown (single-period: just the return if negative)
    max_dd = min(total_return, 0.0)

    return FundMetrics(
        fund_code=fund_code,
        total_return=total_return,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        sector_weights=sector_weights,
        attribution=result,
    )


def _compute_attribution_diffs(fund_metrics: list[FundMetrics]) -> dict:
    """Compute per-industry attribution differences vs first fund."""
    if len(fund_metrics) < 2:
        return {}

    base = fund_metrics[0]
    if base.attribution is None:
        return {}

    base_detail = base.attribution.get("detail")
    if base_detail is None:
        return {}

    diffs = {}
    base_by_industry = {
        row["industry"]: row for _, row in base_detail.iterrows()
    }

    for other in fund_metrics[1:]:
        if other.attribution is None:
            continue
        other_detail = other.attribution.get("detail")
        if other_detail is None:
            continue

        pair_key = f"{base.fund_code}_vs_{other.fund_code}"
        pair_diffs = []

        other_by_industry = {
            row["industry"]: row for _, row in other_detail.iterrows()
        }

        all_industries = set(base_by_industry.keys()) | set(other_by_industry.keys())
        for ind in sorted(all_industries):
            base_alloc = base_by_industry.get(ind, {}).get("alloc_effect", 0)
            other_alloc = other_by_industry.get(ind, {}).get("alloc_effect", 0)
            base_select = base_by_industry.get(ind, {}).get("select_effect", 0)
            other_select = other_by_industry.get(ind, {}).get("select_effect", 0)

            pair_diffs.append({
                "industry": ind,
                "alloc_diff": base_alloc - other_alloc,
                "select_diff": base_select - other_select,
                "total_diff": (base_alloc + base_select) - (other_alloc + other_select),
            })

        diffs[pair_key] = pair_diffs

    return diffs


def _generate_comparison_explanation(
    fund_metrics: list[FundMetrics],
    api_key: Optional[str] = None,
) -> str:
    """Generate AI comparison explanation in Traditional Chinese."""
    # Build metrics summary for prompt
    lines = []
    for fm in fund_metrics:
        sharpe_str = f"{fm.sharpe_ratio:.2f}" if fm.sharpe_ratio is not None else "N/A"
        dd_str = f"{fm.max_drawdown * 100:.2f}%" if fm.max_drawdown is not None else "N/A"
        lines.append(
            f"- {fm.fund_code}: 報酬 {fm.total_return * 100:.2f}%, "
            f"Sharpe {sharpe_str}, MaxDD {dd_str}"
        )

    metrics_text = "\n".join(lines)

    # Try AI if key available
    if api_key:
        try:
            return _call_ai_comparison(metrics_text, api_key)
        except Exception as e:
            logger.warning("AI comparison failed: %s — using template", e)

    # Fallback: template-based
    return _template_comparison(fund_metrics)


def _template_comparison(fund_metrics: list[FundMetrics]) -> str:
    """Generate template-based comparison in Traditional Chinese."""
    sorted_by_return = sorted(fund_metrics, key=lambda f: f.total_return, reverse=True)
    best = sorted_by_return[0]
    worst = sorted_by_return[-1]

    diff = (best.total_return - worst.total_return) * 100

    explanation = (
        f"比較結果：{best.fund_code} 報酬率 {best.total_return * 100:.2f}% "
        f"表現最佳，領先 {worst.fund_code}（{worst.total_return * 100:.2f}%）"
        f"約 {diff:.2f} 個百分點。"
    )

    if best.attribution:
        alloc = best.attribution.get("allocation_total", 0)
        select = best.attribution.get("selection_total", 0)
        if abs(alloc) > abs(select):
            explanation += "主要優勢來自產業配置策略。"
        else:
            explanation += "主要優勢來自選股能力。"

    return explanation


def _call_ai_comparison(metrics_text: str, api_key: str) -> str:
    """Call Claude API for comparison explanation."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""你是資深投資研究總監。請用100字以內的繁體中文，比較以下基金的表現差異，
說明哪檔基金較適合不同風險偏好的投資人。

{metrics_text}

請直接回覆分析文字，不需要 JSON 格式。"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        timeout=10,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
