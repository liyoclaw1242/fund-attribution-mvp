"""Fund code → full Brinson holdings pipeline.

End-to-end: fund_code → [industry, Wp, Wb, Rp, Rb] DataFrame
ready for engine.brinson.compute_attribution().

Integrates:
  - DS-06: benchmark_weight.py (Wb)
  - DS-07: sitca_scraper.py (Wp, Rp)
  - MI_INDEX: twse_client.py (Rb)
  - industry_mapper.py (name alignment)
"""

import logging
import sqlite3
from typing import Optional

import pandas as pd

from data.fund_registry import get_fund_info

logger = logging.getLogger(__name__)


def lookup_fund(
    fund_code: str,
    period: Optional[str] = None,
    benchmark: str = "MI_INDEX",
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Look up fund by code and return complete Brinson holdings.

    Args:
        fund_code: Fund code (e.g. "0050", "00878").
        period: YYYYMM format. None = latest.
        benchmark: Benchmark name for Wb/Rb. Default "MI_INDEX".
        conn: SQLite connection for caching.

    Returns:
        DataFrame: [industry, Wp, Wb, Rp, Rb]
        Ready for compute_attribution().

    Raises:
        ValueError: If fund not found or data unavailable.
    """
    # 1. Look up fund info
    fund_info = get_fund_info(fund_code)
    if fund_info is None:
        raise ValueError(
            f"基金代碼 {fund_code} 查無資料。\n"
            f"目前支援的基金請見基金列表，或改用「上傳 CSV/Excel」模式。"
        )

    logger.info(
        "Looking up %s: %s (%s)",
        fund_code, fund_info["fund_name"], fund_info["company_name"],
    )

    company_code = fund_info["company_code"]
    fund_type = fund_info["fund_type"]

    # 2. Get Wp from SITCA scraper
    wp_df = _fetch_wp(company_code, fund_type, period, conn)

    # 3. Get Rp from SITCA returns
    rp_df = _fetch_rp(company_code, period, conn)

    # 4. Get Wb from benchmark weight
    wb_df = _fetch_wb(conn)

    # 5. Get Rb from MI_INDEX
    rb_df = _fetch_rb(conn)

    # 6. Merge all into [industry, Wp, Wb, Rp, Rb]
    result = _merge_holdings(wp_df, rp_df, wb_df, rb_df, fund_info["fund_name"])

    if result.empty:
        raise ValueError(
            f"基金 {fund_code} ({fund_info['fund_name']}) 資料不完整。\n"
            f"可能原因：SITCA 資料尚未更新，或網路連線問題。"
        )

    logger.info("Lookup complete: %d industries, Wp sum=%.2f", len(result), result["Wp"].sum())
    return result


def _fetch_wp(
    company_code: str,
    fund_type: str,
    period: Optional[str],
    conn: Optional[sqlite3.Connection],
) -> pd.DataFrame:
    """Fetch fund weights (Wp) from SITCA scraper."""
    try:
        from data.sitca_scraper import fetch_fund_holdings
        df = fetch_fund_holdings(company_code, fund_type, period, conn)

        if df.empty:
            logger.warning("No Wp data from SITCA for %s", company_code)
            return pd.DataFrame(columns=["industry", "Wp"])

        # Normalize: use industry_mapper
        df = _map_industries(df, "industry")

        # Aggregate by mapped industry (in case of duplicates)
        result = df.groupby("industry")["weight"].sum().reset_index()
        result.columns = ["industry", "Wp"]

        return result

    except Exception as e:
        logger.warning("Wp fetch failed: %s", e)
        return pd.DataFrame(columns=["industry", "Wp"])


def _fetch_rp(
    company_code: str,
    period: Optional[str],
    conn: Optional[sqlite3.Connection],
) -> pd.DataFrame:
    """Fetch fund returns (Rp) from SITCA.

    Note: SITCA returns are fund-level, not sector-level.
    For Brinson, we need sector-level Rp. If unavailable,
    we use the fund-level return as a uniform estimate.
    """
    try:
        from data.sitca_scraper import fetch_fund_returns
        df = fetch_fund_returns(company_code, period, conn)

        if df.empty or "return_1m" not in df.columns:
            return pd.DataFrame(columns=["fund_name", "Rp"])

        # Use 1-month return as the period return
        result = df[["fund_name"]].copy()
        result["Rp"] = df["return_1m"].fillna(0)
        return result

    except Exception as e:
        logger.warning("Rp fetch failed: %s", e)
        return pd.DataFrame(columns=["fund_name", "Rp"])


def _fetch_wb(conn: Optional[sqlite3.Connection]) -> pd.DataFrame:
    """Fetch benchmark weights (Wb) from TWSE."""
    try:
        from data.benchmark_weight import compute_industry_weights
        df = compute_industry_weights(conn=conn)

        if df.empty:
            return pd.DataFrame(columns=["industry", "Wb"])

        return df[["industry", "Wb"]]

    except Exception as e:
        logger.warning("Wb fetch failed: %s", e)
        return pd.DataFrame(columns=["industry", "Wb"])


def _fetch_rb(conn: Optional[sqlite3.Connection]) -> pd.DataFrame:
    """Fetch benchmark returns (Rb) from MI_INDEX."""
    try:
        from data.twse_client import get_industry_indices
        indices = get_industry_indices(conn=conn)

        if not indices:
            return pd.DataFrame(columns=["industry", "Rb"])

        rows = []
        for idx in indices:
            industry = idx.get("industry", "")
            return_rate = idx.get("return_rate", 0)
            if industry:
                rows.append({"industry": industry, "Rb": return_rate})

        return pd.DataFrame(rows)

    except Exception as e:
        logger.warning("Rb fetch failed: %s", e)
        return pd.DataFrame(columns=["industry", "Rb"])


def _map_industries(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Apply industry_mapper to normalize industry names."""
    try:
        from data.industry_mapper import map_industry, load_mapping
        mapping = load_mapping()
        df = df.copy()
        df[col] = df[col].apply(lambda x: map_industry(x, mapping))
    except Exception as e:
        logger.warning("Industry mapping failed: %s — using raw names", e)
    return df


def _merge_holdings(
    wp_df: pd.DataFrame,
    rp_df: pd.DataFrame,
    wb_df: pd.DataFrame,
    rb_df: pd.DataFrame,
    fund_name: str,
) -> pd.DataFrame:
    """Merge Wp, Wb, Rp, Rb into a unified DataFrame."""
    if wp_df.empty:
        return pd.DataFrame(columns=["industry", "Wp", "Wb", "Rp", "Rb"])

    # Start with Wp
    result = wp_df.copy()

    # LEFT JOIN Wb
    if not wb_df.empty:
        result = result.merge(wb_df, on="industry", how="left")
    else:
        result["Wb"] = 0.0

    # LEFT JOIN Rb
    if not rb_df.empty:
        result = result.merge(rb_df, on="industry", how="left")
    else:
        result["Rb"] = 0.0

    # Add Rp — fund-level return applied uniformly if sector-level unavailable
    if not rp_df.empty:
        # Find matching fund return
        fund_rp = rp_df[rp_df["fund_name"].str.contains(fund_name[:4], na=False)]
        if not fund_rp.empty:
            result["Rp"] = fund_rp["Rp"].iloc[0]
        else:
            result["Rp"] = rp_df["Rp"].iloc[0] if len(rp_df) > 0 else 0.0
    else:
        result["Rp"] = 0.0

    # Fill NaN
    result["Wb"] = result["Wb"].fillna(0)
    result["Rb"] = result["Rb"].fillna(0)
    result["Rp"] = result["Rp"].fillna(0)

    return result[["industry", "Wp", "Wb", "Rp", "Rb"]]
