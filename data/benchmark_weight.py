"""Benchmark weight (Wb) auto-calculation from TWSE dual API.

Combines two TWSE APIs:
  - t187ap03_L: company list with industry codes + shares outstanding
  - STOCK_DAY_ALL: all stock closing prices

Calculation:
  market_cap(stock) = shares_outstanding × closing_price
  Wb(industry) = Σ market_cap(industry) / Σ market_cap(all)

Cache: benchmark_weight table in SQLite, TTL = 24h.
"""

import logging
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests
import urllib3

from config.settings import TWSE_RATE_LIMIT_DELAY

# Suppress TWSE SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# TWSE API endpoints
COMPANY_LIST_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
STOCK_PRICE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

# Cache TTL
CACHE_TTL_HOURS = 24

# TWSE industry code → standard industry name mapping
INDUSTRY_CODE_MAP = {
    "01": "水泥",
    "02": "食品",
    "03": "塑膠",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "07": "化學",      # includes 化學生技醫療
    "08": "生技醫療",
    "09": "玻璃陶瓷",
    "10": "造紙",
    "11": "鋼鐵",
    "12": "橡膠",
    "13": "汽車",
    "14": "半導體",
    "15": "電腦及週邊設備",
    "16": "光電",
    "17": "通信網路",
    "18": "電子零組件",
    "19": "電子通路",
    "20": "資訊服務",
    "21": "其他電子",
    "22": "建材營造",
    "23": "航運",
    "24": "觀光餐旅",   # was 觀光事業
    "25": "金融保險",
    "26": "貿易百貨",
    "27": "油電燃氣",
    "28": "其他",
    "29": "電子工業",   # composite, not a standard category
    "31": "綠能環保",
    "32": "數位雲端",
    "33": "運動休閒",
    "34": "居家生活",
}

# Rate limiter state
_last_request_time: float = 0.0


def compute_industry_weights(
    conn: Optional[sqlite3.Connection] = None,
    target_date: Optional[str] = None,
) -> pd.DataFrame:
    """Compute industry benchmark weights (Wb) from TWSE data.

    Args:
        conn: SQLite connection for caching.
        target_date: YYYYMMDD format. Default = today.

    Returns:
        DataFrame: [industry, Wb, market_cap]
        - industry: standard industry name (TSE 28)
        - Wb: float, market-cap weight (sum ≈ 1.0)
        - market_cap: int, total industry market cap (TWD)

    Raises:
        ValueError: If TWSE data unavailable.
    """
    if target_date is None:
        target_date = date.today().strftime("%Y%m%d")

    # Check cache
    if conn is not None:
        cached = _get_cached_weights(conn, target_date)
        if cached is not None:
            return cached

    # Fetch from TWSE
    companies = _fetch_company_list()
    prices = _fetch_stock_prices()

    if companies.empty or prices.empty:
        # Try cache regardless of TTL
        if conn is not None:
            fallback = _get_cached_weights(conn, target_date, ignore_ttl=True)
            if fallback is not None:
                logger.info("Using expired cache for Wb on %s", target_date)
                return fallback
        raise ValueError("TWSE data unavailable for Wb calculation")

    # Compute
    result = _compute_weights(companies, prices)

    # Cache
    if conn is not None and len(result) > 0:
        _cache_weights(conn, result, target_date)

    return result


def _rate_limit():
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < TWSE_RATE_LIMIT_DELAY:
        time.sleep(TWSE_RATE_LIMIT_DELAY - elapsed)
    _last_request_time = time.monotonic()


def _fetch_company_list() -> pd.DataFrame:
    """Fetch t187ap03_L: company list with industry + shares."""
    _rate_limit()
    try:
        resp = requests.get(COMPANY_LIST_URL, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or len(data) == 0:
            return pd.DataFrame()

        records = []
        for item in data:
            code = item.get("公司代號", "").strip()
            ind_code = item.get("產業別", "").strip()
            shares_str = item.get("已發行股份總數(股)", "0").replace(",", "").strip()

            try:
                shares = int(float(shares_str))
            except (ValueError, TypeError):
                shares = 0

            if code and shares > 0:
                records.append({
                    "stock_code": code,
                    "industry_code": ind_code,
                    "shares": shares,
                })

        return pd.DataFrame(records)

    except Exception as e:
        logger.warning("Failed to fetch company list: %s", e)
        return pd.DataFrame()


def _fetch_stock_prices() -> pd.DataFrame:
    """Fetch STOCK_DAY_ALL: all stock closing prices."""
    _rate_limit()
    try:
        resp = requests.get(STOCK_PRICE_URL, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or len(data) == 0:
            return pd.DataFrame()

        records = []
        for item in data:
            code = item.get("Code", "").strip()
            price_str = item.get("ClosingPrice", "0").replace(",", "").strip()

            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = 0

            if code and price > 0:
                records.append({
                    "stock_code": code,
                    "closing_price": price,
                })

        return pd.DataFrame(records)

    except Exception as e:
        logger.warning("Failed to fetch stock prices: %s", e)
        return pd.DataFrame()


def _compute_weights(
    companies: pd.DataFrame, prices: pd.DataFrame
) -> pd.DataFrame:
    """Join companies + prices and compute industry weights."""
    if companies.empty or prices.empty:
        return pd.DataFrame(columns=["industry", "Wb", "market_cap"])

    # Merge
    merged = companies.merge(prices, on="stock_code", how="inner")

    if merged.empty:
        return pd.DataFrame(columns=["industry", "Wb", "market_cap"])

    # Market cap = shares × price
    merged["market_cap"] = merged["shares"] * merged["closing_price"]

    # Map industry codes to names
    merged["industry"] = merged["industry_code"].map(INDUSTRY_CODE_MAP)
    merged = merged.dropna(subset=["industry"])

    # Filter out composite categories
    merged = merged[merged["industry_code"] != "29"]  # exclude "電子工業" composite

    # Group by industry
    grouped = merged.groupby("industry")["market_cap"].sum().reset_index()
    total_market_cap = grouped["market_cap"].sum()

    if total_market_cap == 0:
        return pd.DataFrame(columns=["industry", "Wb", "market_cap"])

    grouped["Wb"] = grouped["market_cap"] / total_market_cap
    grouped = grouped.sort_values("Wb", ascending=False).reset_index(drop=True)

    return grouped[["industry", "Wb", "market_cap"]]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _get_cached_weights(
    conn: sqlite3.Connection, target_date: str, ignore_ttl: bool = False
) -> Optional[pd.DataFrame]:
    """Check benchmark_weight cache."""
    try:
        rows = conn.execute(
            "SELECT industry, weight, market_cap FROM benchmark_weight "
            "WHERE date = ?",
            (target_date,),
        ).fetchall()

        if not rows:
            return None

        if not ignore_ttl:
            fresh_row = conn.execute(
                "SELECT fetched_at FROM benchmark_weight "
                "WHERE date = ? ORDER BY fetched_at DESC LIMIT 1",
                (target_date,),
            ).fetchone()

            if fresh_row:
                try:
                    fetched_at = datetime.fromisoformat(str(fresh_row[0]))
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                    age_hours = (now_utc - fetched_at).total_seconds() / 3600
                    if age_hours > CACHE_TTL_HOURS:
                        return None
                except (ValueError, TypeError):
                    pass

        df = pd.DataFrame(rows, columns=["industry", "Wb", "market_cap"])
        return df

    except Exception as e:
        logger.warning("Cache read error: %s", e)
        return None


def _cache_weights(
    conn: sqlite3.Connection, df: pd.DataFrame, target_date: str
) -> None:
    """Store computed weights in cache."""
    try:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO benchmark_weight "
                "(industry, date, weight, market_cap) VALUES (?, ?, ?, ?)",
                (row["industry"], target_date, float(row["Wb"]), int(row["market_cap"])),
            )
        conn.commit()
    except Exception as e:
        logger.warning("Cache write error: %s", e)
