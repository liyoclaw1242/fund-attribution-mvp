"""Multi-market Brinson-Fachler attribution engine.

Extends single-market brinson.py to support:
  - Multiple asset classes (equity, fixed income, cash)
  - Multiple regions (Taiwan, US, China, Asia-Pacific, Europe)
  - Unified sector classification (GICS-based 11 sectors)
  - Currency attribution (FX contribution isolation)

Each dimension runs a standard Brinson BF2/BF3 decomposition.
Currency overlay is computed separately.
"""

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from engine.brinson import compute_attribution
from interfaces import AttributionResult

logger = logging.getLogger(__name__)

# Unified sector mapping: detailed → GICS 11
UNIFIED_SECTORS = {
    "資訊科技": [
        "半導體", "電腦及週邊設備", "光電", "通信網路", "電子零組件",
        "電子通路", "資訊服務", "其他電子", "電子工業",
        "Technology", "Information Technology",
    ],
    "金融": ["金融保險", "金融", "Financials"],
    "醫療保健": ["生技醫療", "Health Care", "Healthcare"],
    "工業": ["電機機械", "電器電纜", "Industrials"],
    "原材料": [
        "水泥", "塑膠", "化學", "鋼鐵", "橡膠", "玻璃陶瓷", "造紙",
        "Materials",
    ],
    "非必需消費": [
        "汽車", "觀光餐旅", "貿易百貨", "紡織纖維",
        "Consumer Discretionary",
    ],
    "必需消費": ["食品", "Consumer Staples"],
    "能源": ["油電燃氣", "Energy"],
    "公用事業": ["Utilities"],
    "不動產": ["建材營造", "Real Estate"],
    "通訊服務": ["數位雲端", "航運", "Communication Services"],
}

# Reverse lookup: detailed name → unified sector
_SECTOR_REVERSE_MAP = {}
for unified, details in UNIFIED_SECTORS.items():
    for detail in details:
        _SECTOR_REVERSE_MAP[detail] = unified
    _SECTOR_REVERSE_MAP[unified] = unified  # self-mapping


def map_to_unified_sector(sector_name: str) -> str:
    """Map any sector name to unified GICS-based classification."""
    return _SECTOR_REVERSE_MAP.get(sector_name, "其他")


def compute_multi_market_attribution(
    portfolio: pd.DataFrame,
    benchmark: pd.DataFrame,
    mode: str = "BF2",
    dimensions: Optional[List[str]] = None,
    base_currency: str = "TWD",
) -> dict:
    """Multi-market Brinson attribution across multiple dimensions.

    Args:
        portfolio: DataFrame with columns:
            [name, asset_class, region, sector, weight, return_rate,
             currency, fx_contribution]
        benchmark: Same structure as portfolio.
        mode: "BF2" or "BF3".
        dimensions: List of dimensions to analyze. Default all.
            Options: "asset_class", "region", "sector"
        base_currency: Base currency for all calculations.

    Returns:
        Dict with keys:
            portfolio_return, benchmark_return, excess_return, fx_contribution,
            by_asset_class, by_region, by_sector, currency_attribution, detail
    """
    if dimensions is None:
        dimensions = ["asset_class", "region", "sector"]

    # Validate inputs
    _validate_inputs(portfolio, benchmark)

    # Calculate total returns (in base currency)
    portfolio_return = (portfolio["weight"] * portfolio["return_rate"]).sum()
    benchmark_return = (benchmark["weight"] * benchmark["return_rate"]).sum()
    excess_return = portfolio_return - benchmark_return
    fx_total = (portfolio["weight"] * portfolio.get("fx_contribution", 0)).sum()

    result = {
        "portfolio_return": portfolio_return,
        "benchmark_return": benchmark_return,
        "excess_return": excess_return,
        "fx_contribution": fx_total,
    }

    # Run Brinson for each requested dimension
    for dim in dimensions:
        if dim in portfolio.columns and dim in benchmark.columns:
            attribution = _run_dimension_attribution(
                portfolio, benchmark, dim, mode
            )
            result[f"by_{dim}"] = attribution
        else:
            logger.warning("Dimension '%s' not found in data — skipping", dim)

    # Currency attribution
    result["currency_attribution"] = _compute_currency_attribution(
        portfolio, benchmark
    )

    # Full detail
    result["detail"] = _build_detail(portfolio, benchmark, mode)

    return result


def build_blended_benchmark(
    allocations: List[dict],
    tw_benchmark: Optional[pd.DataFrame] = None,
    us_benchmark: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build a blended benchmark from multiple indices.

    Args:
        allocations: List of {"index": "TAIEX"|"SP500", "weight": 0.5}.
        tw_benchmark: Taiwan benchmark data (MI_INDEX format).
        us_benchmark: US benchmark data (S&P 500 sector weights).

    Returns:
        DataFrame with [name, asset_class, region, sector, weight, return_rate, currency].
    """
    rows = []

    for alloc in allocations:
        index = alloc["index"]
        alloc_weight = alloc["weight"]

        if index == "TAIEX" and tw_benchmark is not None:
            for _, row in tw_benchmark.iterrows():
                sector = map_to_unified_sector(row.get("industry", ""))
                rows.append({
                    "name": f"TAIEX:{row.get('industry', '')}",
                    "asset_class": "股票",
                    "region": "台灣",
                    "sector": sector,
                    "weight": alloc_weight * row.get("Wb", row.get("weight", 0)),
                    "return_rate": row.get("Rb", row.get("return_rate", 0)),
                    "currency": "TWD",
                    "fx_contribution": 0.0,
                })
        elif index == "SP500" and us_benchmark is not None:
            for _, row in us_benchmark.iterrows():
                rows.append({
                    "name": f"SP500:{row.get('sector', '')}",
                    "asset_class": "股票",
                    "region": "美國",
                    "sector": row.get("sector", ""),
                    "weight": alloc_weight * row.get("Wb", 0),
                    "return_rate": row.get("Rb", 0),
                    "currency": "USD",
                    "fx_contribution": 0.0,
                })

    if not rows:
        return pd.DataFrame(columns=[
            "name", "asset_class", "region", "sector",
            "weight", "return_rate", "currency", "fx_contribution",
        ])

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _validate_inputs(portfolio: pd.DataFrame, benchmark: pd.DataFrame) -> None:
    """Validate required columns."""
    required = ["weight", "return_rate"]
    for col in required:
        if col not in portfolio.columns:
            raise ValueError(f"Portfolio missing column: {col}")
        if col not in benchmark.columns:
            raise ValueError(f"Benchmark missing column: {col}")


def _run_dimension_attribution(
    portfolio: pd.DataFrame,
    benchmark: pd.DataFrame,
    dimension: str,
    mode: str,
) -> AttributionResult:
    """Run Brinson attribution along a single dimension."""
    # Aggregate by dimension
    p_grouped = portfolio.groupby(dimension).agg({
        "weight": "sum",
        "return_rate": lambda x: np.average(x, weights=portfolio.loc[x.index, "weight"])
        if portfolio.loc[x.index, "weight"].sum() > 0 else 0,
    }).reset_index()

    b_grouped = benchmark.groupby(dimension).agg({
        "weight": "sum",
        "return_rate": lambda x: np.average(x, weights=benchmark.loc[x.index, "weight"])
        if benchmark.loc[x.index, "weight"].sum() > 0 else 0,
    }).reset_index()

    # Merge into Brinson format
    all_categories = set(p_grouped[dimension]) | set(b_grouped[dimension])
    holdings_rows = []
    for cat in all_categories:
        p_row = p_grouped[p_grouped[dimension] == cat]
        b_row = b_grouped[b_grouped[dimension] == cat]

        holdings_rows.append({
            "industry": cat,
            "Wp": p_row["weight"].iloc[0] if len(p_row) > 0 else 0,
            "Wb": b_row["weight"].iloc[0] if len(b_row) > 0 else 0,
            "Rp": p_row["return_rate"].iloc[0] if len(p_row) > 0 else 0,
            "Rb": b_row["return_rate"].iloc[0] if len(b_row) > 0 else 0,
        })

    holdings_df = pd.DataFrame(holdings_rows)
    return compute_attribution(holdings_df, mode=mode)


def _compute_currency_attribution(
    portfolio: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    """Compute currency overlay attribution."""
    if "currency" not in portfolio.columns:
        return pd.DataFrame(columns=["currency", "weight", "fx_return", "contribution"])

    fx_col = "fx_contribution" if "fx_contribution" in portfolio.columns else None

    if fx_col is None:
        return pd.DataFrame(columns=["currency", "weight", "fx_return", "contribution"])

    grouped = portfolio.groupby("currency").agg({
        "weight": "sum",
        fx_col: lambda x: np.average(x, weights=portfolio.loc[x.index, "weight"])
        if portfolio.loc[x.index, "weight"].sum() > 0 else 0,
    }).reset_index()

    grouped.columns = ["currency", "weight", "fx_return"]
    grouped["contribution"] = grouped["weight"] * grouped["fx_return"]

    return grouped


def _build_detail(
    portfolio: pd.DataFrame,
    benchmark: pd.DataFrame,
    mode: str,
) -> pd.DataFrame:
    """Build detailed attribution for each holding."""
    detail = portfolio.copy()
    detail["excess_vs_benchmark"] = detail["return_rate"] - (
        benchmark["return_rate"].mean() if len(benchmark) > 0 else 0
    )
    return detail
