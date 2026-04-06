"""Rule-based fallback template when AI verification fails.

Produces natural Chinese text using exact numbers from AttributionResult.
Used when Claude output contains hallucinated numbers or API is unavailable.
"""


def _fmt_pct(value: float) -> str:
    """Format a decimal as percentage string (e.g., 0.085 -> '8.50%')."""
    return f"{value * 100:.2f}%"


def _sign_emoji(value: float) -> str:
    """Return emoji for positive/negative value."""
    if value > 0:
        return "📈"
    elif value < 0:
        return "📉"
    return "➡️"


def generate_line_message(result: dict) -> str:
    """Generate LINE message (<100 chars Chinese with emoji).

    Args:
        result: AttributionResult dict.

    Returns:
        Short Chinese summary with emoji prefix.
    """
    excess = result["excess_return"]
    emoji = _sign_emoji(excess)
    fund_ret = _fmt_pct(result["fund_return"])
    bench_ret = _fmt_pct(result["bench_return"])
    excess_ret = _fmt_pct(abs(excess))

    if excess > 0:
        return f"{emoji} 基金報酬{fund_ret}，超越基準{bench_ret}，超額報酬{excess_ret}，市場佈局與選股皆有貢獻"
    elif excess < 0:
        return f"{emoji} 基金報酬{fund_ret}，落後基準{bench_ret}，差距{excess_ret}，需檢視產業配置策略"
    else:
        return f"{emoji} 基金報酬{fund_ret}，與基準{bench_ret}持平，配置與選股效果互相抵消"


def generate_pdf_summary(result: dict) -> str:
    """Generate PDF summary (150-200 chars professional Chinese).

    Args:
        result: AttributionResult dict.

    Returns:
        Professional Chinese summary paragraph.
    """
    fund_ret = _fmt_pct(result["fund_return"])
    bench_ret = _fmt_pct(result["bench_return"])
    excess_ret = _fmt_pct(result["excess_return"])
    alloc = _fmt_pct(result["allocation_total"])
    select = _fmt_pct(result["selection_total"])

    mode = result.get("brinson_mode", "BF2")

    top = result.get("top_contributors")
    top_str = ""
    if top is not None and len(top) > 0:
        top_name = top.iloc[0]["industry"]
        top_contrib = _fmt_pct(top.iloc[0]["total_contrib"])
        top_str = f"其中{top_name}貢獻最大（{top_contrib}）。"

    if mode == "BF3" and result.get("interaction_total") is not None:
        interact = _fmt_pct(result["interaction_total"])
        return (
            f"本期基金報酬率為{fund_ret}，基準指數報酬率為{bench_ret}，"
            f"超額報酬為{excess_ret}。"
            f"產業配置效果為{alloc}，選股能力效果為{select}，"
            f"交互效果為{interact}。{top_str}"
        )

    return (
        f"本期基金報酬率為{fund_ret}，基準指數報酬率為{bench_ret}，"
        f"超額報酬為{excess_ret}。"
        f"產業配置效果為{alloc}，選股能力效果為{select}。{top_str}"
    )


def generate_advisor_note(result: dict) -> str:
    """Generate advisor note (<50 chars metrics only).

    Args:
        result: AttributionResult dict.

    Returns:
        Compact metrics string for advisor reference.
    """
    fund_ret = _fmt_pct(result["fund_return"])
    excess_ret = _fmt_pct(result["excess_return"])
    alloc = _fmt_pct(result["allocation_total"])
    select = _fmt_pct(result["selection_total"])

    return f"基金{fund_ret} 超額{excess_ret} 配置{alloc} 選股{select}"


def generate_fallback(result: dict) -> dict:
    """Generate all 3 summary variants using templates.

    Args:
        result: AttributionResult dict.

    Returns:
        Dict with keys: line_message, pdf_summary, advisor_note.
    """
    return {
        "line_message": generate_line_message(result),
        "pdf_summary": generate_pdf_summary(result),
        "advisor_note": generate_advisor_note(result),
    }
