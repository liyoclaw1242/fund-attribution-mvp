"""Attribution orchestration service.

Resolves holdings → fetches benchmark → calls Brinson engine → returns result.
"""

import logging

import pandas as pd

from service.services.fund_service import get_fund_by_identifier, get_benchmark_data

logger = logging.getLogger(__name__)


def run_attribution(
    holdings_input: list[dict],
    mode: str = "BF2",
    benchmark: str = "auto",
) -> dict:
    """Orchestrate Brinson attribution.

    Args:
        holdings_input: List of {"identifier": "0050", "shares": 100}.
        mode: "BF2" or "BF3".
        benchmark: "auto" or specific benchmark name.

    Returns:
        Attribution result dict.
    """
    from engine.brinson import compute_attribution

    # 1. Resolve fund holdings
    all_industries = {}
    for h in holdings_input:
        fund = get_fund_by_identifier(h["identifier"])
        if not fund:
            logger.warning("Fund not found: %s — skipping", h["identifier"])
            continue

        for holding in fund.get("holdings", []):
            industry = holding["stock_name"]
            weight = holding["weight"]
            if industry in all_industries:
                all_industries[industry]["Wp"] += weight
            else:
                all_industries[industry] = {
                    "industry": industry,
                    "Wp": weight,
                    "Rp": 0.0,  # Return from fund
                }

    if not all_industries:
        raise ValueError("No holdings could be resolved from the provided identifiers")

    # 2. Fetch benchmark
    benchmark_data = get_benchmark_data()
    bench_by_industry = {b["industry"]: b for b in benchmark_data}

    # 3. Merge into attribution DataFrame
    rows = []
    for industry, data in all_industries.items():
        bench = bench_by_industry.get(industry, {})
        rows.append({
            "industry": industry,
            "Wp": data["Wp"],
            "Wb": bench.get("weight", 0.0),
            "Rp": data.get("Rp", 0.0),
            "Rb": bench.get("return_rate", 0.0),
        })

    # Add benchmark-only industries
    for industry, bench in bench_by_industry.items():
        if industry not in all_industries:
            rows.append({
                "industry": industry,
                "Wp": 0.0,
                "Wb": bench["weight"],
                "Rp": 0.0,
                "Rb": bench.get("return_rate", 0.0),
            })

    df = pd.DataFrame(rows)

    # 4. Compute attribution
    result = compute_attribution(df, mode=mode)

    # 5. Format response
    detail = []
    if isinstance(result["detail"], pd.DataFrame) and not result["detail"].empty:
        for _, row in result["detail"].iterrows():
            detail.append({
                "industry": row.get("industry", ""),
                "Wp": float(row.get("Wp", 0)),
                "Wb": float(row.get("Wb", 0)),
                "Rp": float(row.get("Rp", 0)),
                "Rb": float(row.get("Rb", 0)),
                "alloc_effect": float(row.get("alloc_effect", 0)),
                "select_effect": float(row.get("select_effect", 0)),
                "interaction_effect": float(row.get("interaction_effect", 0)) if "interaction_effect" in row else None,
                "total_contrib": float(row.get("total_contrib", 0)),
            })

    top = []
    if isinstance(result.get("top_contributors"), pd.DataFrame):
        for _, row in result["top_contributors"].iterrows():
            top.append({
                "industry": row.get("industry", ""),
                "Wp": float(row.get("Wp", 0)),
                "Wb": float(row.get("Wb", 0)),
                "Rp": float(row.get("Rp", 0)),
                "Rb": float(row.get("Rb", 0)),
                "alloc_effect": float(row.get("alloc_effect", 0)),
                "select_effect": float(row.get("select_effect", 0)),
                "interaction_effect": float(row.get("interaction_effect", 0)) if "interaction_effect" in row else None,
                "total_contrib": float(row.get("total_contrib", 0)),
            })

    bottom = []
    if isinstance(result.get("bottom_contributors"), pd.DataFrame):
        for _, row in result["bottom_contributors"].iterrows():
            bottom.append({
                "industry": row.get("industry", ""),
                "Wp": float(row.get("Wp", 0)),
                "Wb": float(row.get("Wb", 0)),
                "Rp": float(row.get("Rp", 0)),
                "Rb": float(row.get("Rb", 0)),
                "alloc_effect": float(row.get("alloc_effect", 0)),
                "select_effect": float(row.get("select_effect", 0)),
                "interaction_effect": float(row.get("interaction_effect", 0)) if "interaction_effect" in row else None,
                "total_contrib": float(row.get("total_contrib", 0)),
            })

    return {
        "fund_return": float(result["fund_return"]),
        "bench_return": float(result["bench_return"]),
        "excess_return": float(result["excess_return"]),
        "allocation_total": float(result["allocation_total"]),
        "selection_total": float(result["selection_total"]),
        "interaction_total": float(result.get("interaction_total") or 0),
        "brinson_mode": result["brinson_mode"],
        "detail": detail,
        "top_contributors": top,
        "bottom_contributors": bottom,
        "unmapped_weight": float(result.get("unmapped_weight", 0)),
    }
