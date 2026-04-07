"""0050 ETF benchmark mirror — compare client portfolio vs "just buying 0050."

Flow:
  1. Fetch 0050 return (TWSE MI_INDEX weighted return as proxy for MVP)
  2. Calculate client's total weighted portfolio return
  3. Compare: winning → congratulate; losing → Brinson explains why + AI rebalance

Data source for 0050 proxy:
  - MI_INDEX from TWSE API via data/twse_client.py
  - The weighted average of all industry index returns approximates
    the market-cap-weighted 0050 return.
"""

import logging
import sqlite3
from typing import List, Optional

import pandas as pd

from interfaces import ETFMirrorResult

logger = logging.getLogger(__name__)


def compare_vs_0050(
    client_id: str,
    conn: sqlite3.Connection,
    period: str = "latest",
    mode: str = "BF2",
    generate_ai: bool = True,
    api_key: Optional[str] = None,
) -> ETFMirrorResult:
    """Compare client portfolio return vs 0050 ETF benchmark.

    Args:
        client_id: Client ID to look up holdings for.
        conn: SQLite connection with client_portfolios and fund_holdings tables.
        period: Period to compare (default "latest").
        mode: Brinson mode for gap explanation ("BF2" or "BF3").
        generate_ai: Whether to generate AI rebalance suggestion.
        api_key: Anthropic API key (optional).

    Returns:
        ETFMirrorResult with comparison and explanation.

    Raises:
        ValueError: If client has no holdings or no return data available.
    """
    # 1. Get client portfolio return
    client_return = _get_client_portfolio_return(conn, client_id, period)

    # 2. Get 0050 proxy return
    etf_return = _get_etf_return(conn, period)

    # 3. Compare
    diff = client_return - etf_return
    is_winning = diff >= 0

    # 4. If losing, explain why via Brinson + suggest rebalancing
    brinson_explanation = ""
    rebalance_suggestion = ""

    if not is_winning:
        brinson_explanation = _explain_gap(
            conn, client_id, period, mode, client_return, etf_return
        )
        if generate_ai:
            rebalance_suggestion = _generate_rebalance_suggestion(
                client_return, etf_return, diff,
                brinson_explanation, api_key=api_key,
            )

    return ETFMirrorResult(
        client_return=client_return,
        etf_return=etf_return,
        diff=diff,
        is_winning=is_winning,
        brinson_explanation=brinson_explanation,
        rebalance_suggestion=rebalance_suggestion,
    )


def compare_vs_0050_direct(
    client_holdings: List[dict],
    benchmark_indices: List[dict],
    mode: str = "BF2",
    generate_ai: bool = True,
    api_key: Optional[str] = None,
) -> ETFMirrorResult:
    """Compare client portfolio vs 0050 without DB.

    Args:
        client_holdings: List of dicts with fund_code, weight, return_rate.
        benchmark_indices: List of dicts with industry, weight, return_rate
            (MI_INDEX data as 0050 proxy).
        mode: Brinson mode.
        generate_ai: Whether to generate AI suggestion.
        api_key: Anthropic API key.

    Returns:
        ETFMirrorResult.
    """
    # Client return: weighted average
    client_return = sum(
        h.get("weight", 0) * h.get("return_rate", 0)
        for h in client_holdings
    )

    # ETF return: weighted average of benchmark indices
    total_bench_weight = sum(b.get("weight", 0) for b in benchmark_indices)
    if total_bench_weight > 0:
        etf_return = sum(
            b.get("weight", 0) * b.get("return_rate", 0)
            for b in benchmark_indices
        ) / total_bench_weight
    else:
        # Equal-weighted fallback
        etf_return = (
            sum(b.get("return_rate", 0) for b in benchmark_indices)
            / len(benchmark_indices)
        ) if benchmark_indices else 0.0

    diff = client_return - etf_return
    is_winning = diff >= 0

    brinson_explanation = ""
    rebalance_suggestion = ""

    if not is_winning:
        brinson_explanation = _explain_gap_from_data(
            client_holdings, benchmark_indices, mode,
            client_return, etf_return,
        )
        if generate_ai:
            rebalance_suggestion = _generate_rebalance_suggestion(
                client_return, etf_return, diff,
                brinson_explanation, api_key=api_key,
            )

    return ETFMirrorResult(
        client_return=client_return,
        etf_return=etf_return,
        diff=diff,
        is_winning=is_winning,
        brinson_explanation=brinson_explanation,
        rebalance_suggestion=rebalance_suggestion,
    )


def _get_client_portfolio_return(
    conn: sqlite3.Connection, client_id: str, period: str
) -> float:
    """Calculate client's weighted portfolio return from fund_holdings."""
    conn.row_factory = sqlite3.Row

    # Get client's fund codes
    portfolio_rows = conn.execute(
        "SELECT fund_code, cost_basis FROM client_portfolios WHERE client_id = ?",
        (client_id,),
    ).fetchall()

    if not portfolio_rows:
        raise ValueError(f"No portfolio found for client {client_id}")

    total_value = sum(r["cost_basis"] for r in portfolio_rows)
    if total_value == 0:
        raise ValueError(f"Client {client_id} has zero portfolio value")

    weighted_return = 0.0
    funds_with_data = 0

    for row in portfolio_rows:
        fund_code = row["fund_code"]
        weight = row["cost_basis"] / total_value

        # Look up fund's return from fund_holdings
        holdings = conn.execute(
            "SELECT weight AS w, return_rate FROM fund_holdings "
            "WHERE fund_code = ? AND period = ?",
            (fund_code, period),
        ).fetchall()

        if holdings:
            # Fund return = sum of (sector_weight * sector_return)
            fund_return = sum(
                h["w"] * (h["return_rate"] or 0) for h in holdings
            )
            weighted_return += weight * fund_return
            funds_with_data += 1
        else:
            logger.warning("Fund %s: no holdings data for period %s", fund_code, period)

    if funds_with_data == 0:
        raise ValueError(
            f"No return data found for any fund in client {client_id}'s portfolio"
        )

    return weighted_return


def _get_etf_return(conn: sqlite3.Connection, period: str) -> float:
    """Get 0050 proxy return from MI_INDEX benchmark data.

    Uses equal-weighted average of all industry index returns as
    a proxy for 0050's market-cap-weighted return.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT industry, return_rate FROM benchmark_index "
        "WHERE index_name = ? AND period = ?",
        ("MI_INDEX", period),
    ).fetchall()

    if not rows:
        raise ValueError(
            f"No MI_INDEX benchmark data for period {period}. "
            "Run TWSE data fetch first."
        )

    # Equal-weighted average as 0050 proxy
    returns = [r["return_rate"] for r in rows if r["return_rate"] is not None]
    if not returns:
        raise ValueError("MI_INDEX has no valid return data")

    return sum(returns) / len(returns)


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _explain_gap(
    conn: sqlite3.Connection,
    client_id: str,
    period: str,
    mode: str,
    client_return: float,
    etf_return: float,
) -> str:
    """Use Brinson engine to explain why client is underperforming 0050."""
    try:
        from engine.brinson import compute_attribution

        # Build a combined holdings DataFrame for Brinson
        # Wp = client sector weights, Wb = benchmark sector weights
        # Rp = client sector returns, Rb = benchmark sector returns
        holdings_df = _build_comparison_holdings(conn, client_id, period)

        if holdings_df is None or holdings_df.empty:
            return _template_explanation(client_return, etf_return)

        result = compute_attribution(holdings_df, mode=mode)
        return _format_brinson_explanation(result, client_return, etf_return)

    except Exception as e:
        logger.warning("Brinson explanation failed: %s — using template", e)
        return _template_explanation(client_return, etf_return)


def _explain_gap_from_data(
    client_holdings: List[dict],
    benchmark_indices: List[dict],
    mode: str,
    client_return: float,
    etf_return: float,
) -> str:
    """Explain gap using direct data (no DB)."""
    try:
        from engine.brinson import compute_attribution

        holdings_df = _build_comparison_holdings_from_data(
            client_holdings, benchmark_indices
        )

        if holdings_df is None or holdings_df.empty:
            return _template_explanation(client_return, etf_return)

        result = compute_attribution(holdings_df, mode=mode)
        return _format_brinson_explanation(result, client_return, etf_return)

    except Exception as e:
        logger.warning("Brinson explanation failed: %s — using template", e)
        return _template_explanation(client_return, etf_return)


def _build_comparison_holdings(
    conn: sqlite3.Connection, client_id: str, period: str
) -> Optional[pd.DataFrame]:
    """Build Brinson-compatible DataFrame from DB data."""
    conn.row_factory = sqlite3.Row

    # Client's aggregated sector weights/returns
    portfolio_rows = conn.execute(
        "SELECT fund_code, cost_basis FROM client_portfolios WHERE client_id = ?",
        (client_id,),
    ).fetchall()

    total_value = sum(r["cost_basis"] for r in portfolio_rows)
    if total_value == 0:
        return None

    # Aggregate client sector exposure across all funds
    client_sectors: dict = {}
    for row in portfolio_rows:
        fund_weight = row["cost_basis"] / total_value
        holdings = conn.execute(
            "SELECT industry, weight, return_rate FROM fund_holdings "
            "WHERE fund_code = ? AND period = ?",
            (row["fund_code"], period),
        ).fetchall()
        for h in holdings:
            ind = h["industry"]
            w = h["weight"] * fund_weight
            r = h["return_rate"] or 0
            if ind in client_sectors:
                client_sectors[ind]["Wp"] += w
                # Weighted average return
                old_w = client_sectors[ind]["Wp"] - w
                if client_sectors[ind]["Wp"] > 0:
                    client_sectors[ind]["Rp"] = (
                        old_w * client_sectors[ind]["Rp"] + w * r
                    ) / client_sectors[ind]["Wp"]
            else:
                client_sectors[ind] = {"Wp": w, "Rp": r}

    # Benchmark sector data
    bench_rows = conn.execute(
        "SELECT industry, weight, return_rate FROM benchmark_index "
        "WHERE index_name = ? AND period = ?",
        ("MI_INDEX", period),
    ).fetchall()

    bench_sectors = {r["industry"]: {"Wb": r["weight"], "Rb": r["return_rate"]} for r in bench_rows}

    # Merge into Brinson format
    all_sectors = set(client_sectors.keys()) | set(bench_sectors.keys())
    rows = []
    for sector in all_sectors:
        cs = client_sectors.get(sector, {"Wp": 0, "Rp": 0})
        bs = bench_sectors.get(sector, {"Wb": 0, "Rb": 0})
        rows.append({
            "industry": sector,
            "Wp": cs["Wp"],
            "Wb": bs["Wb"],
            "Rp": cs["Rp"],
            "Rb": bs["Rb"],
        })

    if not rows:
        return None

    return pd.DataFrame(rows)


def _build_comparison_holdings_from_data(
    client_holdings: List[dict],
    benchmark_indices: List[dict],
) -> Optional[pd.DataFrame]:
    """Build Brinson-compatible DataFrame from direct data."""
    client_sectors = {}
    for h in client_holdings:
        ind = h.get("industry", h.get("fund_code", "unknown"))
        client_sectors[ind] = {
            "Wp": h.get("weight", 0),
            "Rp": h.get("return_rate", 0),
        }

    bench_sectors = {}
    total_bench_weight = sum(b.get("weight", 0) for b in benchmark_indices)
    for b in benchmark_indices:
        ind = b["industry"]
        w = b.get("weight", 0)
        if total_bench_weight > 0:
            w = w / total_bench_weight
        bench_sectors[ind] = {
            "Wb": w,
            "Rb": b.get("return_rate", 0),
        }

    all_sectors = set(client_sectors.keys()) | set(bench_sectors.keys())
    rows = []
    for sector in all_sectors:
        cs = client_sectors.get(sector, {"Wp": 0, "Rp": 0})
        bs = bench_sectors.get(sector, {"Wb": 0, "Rb": 0})
        rows.append({
            "industry": sector,
            "Wp": cs["Wp"],
            "Wb": bs["Wb"],
            "Rp": cs["Rp"],
            "Rb": bs["Rb"],
        })

    return pd.DataFrame(rows) if rows else None


def _format_brinson_explanation(
    result: dict, client_return: float, etf_return: float
) -> str:
    """Format Brinson attribution into a readable explanation."""
    lines = [
        f"您的投資組合報酬率 {_fmt_pct(client_return)}，"
        f"低於 0050 的 {_fmt_pct(etf_return)}，"
        f"落後 {_fmt_pct(abs(client_return - etf_return))}。",
        "",
        "主要原因分析：",
        f"  產業配置效果：{_fmt_pct(result['allocation_total'])}",
        f"  選股效果：{_fmt_pct(result['selection_total'])}",
    ]

    if result.get("interaction_total") is not None:
        lines.append(f"  交互效果：{_fmt_pct(result['interaction_total'])}")

    # Top detractors
    bottom = result.get("bottom_contributors")
    if bottom is not None and len(bottom) > 0:
        lines.append("")
        lines.append("拖累最大的產業：")
        for _, row in bottom.head(3).iterrows():
            lines.append(
                f"  - {row['industry']}：貢獻 {_fmt_pct(row['total_contrib'])}"
            )

    return "\n".join(lines)


def _template_explanation(client_return: float, etf_return: float) -> str:
    """Fallback template when Brinson analysis is not available."""
    diff = abs(client_return - etf_return)
    return (
        f"您的投資組合報酬率 {_fmt_pct(client_return)}，"
        f"低於 0050 的 {_fmt_pct(etf_return)}，"
        f"落後 {_fmt_pct(diff)}。"
        f"建議檢視產業配置與個別基金表現。"
    )


def _generate_rebalance_suggestion(
    client_return: float,
    etf_return: float,
    diff: float,
    brinson_explanation: str,
    api_key: Optional[str] = None,
) -> str:
    """Generate AI rebalance suggestion via Claude API."""
    try:
        import anthropic
        from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS

        key = api_key or ANTHROPIC_API_KEY
        if not key:
            return _template_rebalance(client_return, etf_return)

        prompt = (
            "你是一位資深投資研究總監，正在為台灣理財顧問提供再平衡建議。\n\n"
            f"客戶投資組合報酬率：{_fmt_pct(client_return)}\n"
            f"0050 ETF 報酬率：{_fmt_pct(etf_return)}\n"
            f"落後幅度：{_fmt_pct(abs(diff))}\n\n"
            f"歸因分析：\n{brinson_explanation}\n\n"
            "## 規則\n"
            "1. 禁止使用: Brinson, attribution, allocation effect, selection effect\n"
            "2. 改用: 市場佈局、選股能力、產業配置\n"
            "3. 僅使用上方提供的精確數字\n\n"
            "## 任務\n"
            "用 100-150 字繁體中文提供具體的再平衡建議。"
            "語氣專業但易懂，適合理財顧問向客戶解釋。"
        )

        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            timeout=AI_TIMEOUT_SECONDS,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        logger.warning("AI rebalance suggestion failed: %s — using template", e)
        return _template_rebalance(client_return, etf_return)


def _template_rebalance(client_return: float, etf_return: float) -> str:
    """Fallback rebalance suggestion template."""
    return (
        f"建議考慮將部分持倉轉換至低成本指數型 ETF（如 0050），"
        f"以降低費用率並貼近市場報酬。"
        f"目前落後 {_fmt_pct(abs(client_return - etf_return))}，"
        f"可透過調整產業配置比重來縮小差距。"
    )
