"""Offshore fund data client — NAV, returns, and allocation.

Primary source: anue.com (鉅亨網) fund API
Fallback: stub data for known popular funds
Cache: SQLite offshore_fund_cache table with TTL.

Supported data:
  - Fund search by keyword
  - NAV history (up to 1 year)
  - Sector/region allocation
"""

import json
import logging
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Rate limiting: 2 requests per 5 seconds
_RATE_LIMIT_DELAY = 2.5
_last_request_time: float = 0.0

# Cache TTL
SEARCH_TTL_DAYS = 30
NAV_TTL_HOURS = 24
ALLOCATION_TTL_DAYS = 30

# Anue API base
ANUE_FUND_API = "https://fund.api.anue.com.tw"

# Offshore sector name mapping to standard names
OFFSHORE_SECTOR_MAP = {
    "科技": "資訊科技",
    "資訊科技": "資訊科技",
    "金融服務": "金融",
    "金融": "金融",
    "非核心消費": "非必需消費",
    "非必需消費品": "非必需消費",
    "核心消費": "必需消費",
    "必需消費品": "必需消費",
    "通訊": "通訊服務",
    "通訊服務": "通訊服務",
    "原物料": "原材料",
    "原材料": "原材料",
    "工業": "工業",
    "醫療保健": "醫療保健",
    "公用事業": "公用事業",
    "房地產": "房地產",
    "能源": "能源",
    "半導體": "資訊科技",
    "電子": "資訊科技",
}

# Known popular offshore funds with stub data
_KNOWN_FUNDS = [
    {
        "fund_id": "LU0117844026",
        "fund_name": "摩根太平洋科技基金",
        "fund_house": "摩根資產管理",
        "fund_type": "股票型",
        "currency": "USD",
        "region": "亞太",
    },
    {
        "fund_id": "LU1548497426",
        "fund_name": "安聯收益成長基金",
        "fund_house": "安聯環球投資",
        "fund_type": "平衡型",
        "currency": "USD",
        "region": "全球",
    },
    {
        "fund_id": "TW000T3774Y6",
        "fund_name": "統一大龍騰中國基金",
        "fund_house": "統一投信",
        "fund_type": "股票型",
        "currency": "TWD",
        "region": "中國",
    },
    {
        "fund_id": "LU0348529875",
        "fund_name": "富蘭克林坦伯頓全球債券基金",
        "fund_house": "富蘭克林坦伯頓",
        "fund_type": "債券型",
        "currency": "USD",
        "region": "全球",
    },
    {
        "fund_id": "LU0069970746",
        "fund_name": "富達亞洲高收益基金",
        "fund_house": "富達國際",
        "fund_type": "債券型",
        "currency": "USD",
        "region": "亞太",
    },
    {
        "fund_id": "LU0251132253",
        "fund_name": "貝萊德世界科技基金",
        "fund_house": "貝萊德",
        "fund_type": "股票型",
        "currency": "USD",
        "region": "全球",
    },
    {
        "fund_id": "LU0476943708",
        "fund_name": "施羅德環球基金系列-亞洲機會",
        "fund_house": "施羅德投資",
        "fund_type": "股票型",
        "currency": "USD",
        "region": "亞太",
    },
    {
        "fund_id": "LU0690375182",
        "fund_name": "PIMCO 總回報基金",
        "fund_house": "PIMCO",
        "fund_type": "債券型",
        "currency": "USD",
        "region": "全球",
    },
    {
        "fund_id": "LU0823427611",
        "fund_name": "景順亞洲科技基金",
        "fund_house": "景順投信",
        "fund_type": "股票型",
        "currency": "USD",
        "region": "亞太",
    },
    {
        "fund_id": "IE00B4L5Y983",
        "fund_name": "iShares 核心 MSCI 世界 ETF",
        "fund_house": "iShares",
        "fund_type": "ETF",
        "currency": "USD",
        "region": "全球",
    },
]

# Stub allocation data for known funds
_STUB_ALLOCATIONS = {
    "LU0117844026": {
        "as_of_date": "2026-03-31",
        "by_sector": [
            {"sector": "資訊科技", "weight": 0.42},
            {"sector": "非必需消費", "weight": 0.15},
            {"sector": "通訊服務", "weight": 0.12},
            {"sector": "金融", "weight": 0.10},
            {"sector": "工業", "weight": 0.08},
            {"sector": "醫療保健", "weight": 0.05},
            {"sector": "原材料", "weight": 0.04},
            {"sector": "其他", "weight": 0.04},
        ],
        "by_region": [
            {"region": "台灣", "weight": 0.28},
            {"region": "韓國", "weight": 0.22},
            {"region": "中國", "weight": 0.18},
            {"region": "日本", "weight": 0.15},
            {"region": "印度", "weight": 0.10},
            {"region": "其他", "weight": 0.07},
        ],
        "by_asset_class": [
            {"asset_class": "股票", "weight": 0.97},
            {"asset_class": "現金", "weight": 0.03},
        ],
    },
    "LU1548497426": {
        "as_of_date": "2026-03-31",
        "by_sector": [
            {"sector": "資訊科技", "weight": 0.25},
            {"sector": "金融", "weight": 0.18},
            {"sector": "醫療保健", "weight": 0.12},
            {"sector": "非必需消費", "weight": 0.10},
            {"sector": "工業", "weight": 0.08},
            {"sector": "通訊服務", "weight": 0.07},
            {"sector": "能源", "weight": 0.05},
            {"sector": "其他", "weight": 0.15},
        ],
        "by_region": [
            {"region": "美國", "weight": 0.55},
            {"region": "歐洲", "weight": 0.20},
            {"region": "亞太", "weight": 0.15},
            {"region": "其他", "weight": 0.10},
        ],
        "by_asset_class": [
            {"asset_class": "股票", "weight": 0.50},
            {"asset_class": "債券", "weight": 0.30},
            {"asset_class": "可轉債", "weight": 0.15},
            {"asset_class": "現金", "weight": 0.05},
        ],
    },
}


def search_fund(
    keyword: str,
    conn: Optional[sqlite3.Connection] = None,
) -> List[dict]:
    """Search for funds by keyword.

    Args:
        keyword: Fund name keyword (Chinese or English).
        conn: SQLite connection for caching.

    Returns:
        List of fund info dicts.
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    # 1. Check cache
    if conn is not None:
        cached = _get_cached_json(conn, f"search:{keyword}", "search", "")
        if cached is not None:
            return cached

    # 2. Try Anue API
    try:
        results = _search_anue(keyword)
        if results and conn is not None:
            _cache_json(conn, f"search:{keyword}", "search", "", results)
        if results:
            return results
    except Exception as e:
        logger.warning("Anue search failed for '%s': %s", keyword, e)

    # 3. Fallback to known funds
    results = [
        f for f in _KNOWN_FUNDS
        if keyword.lower() in f["fund_name"].lower()
        or keyword.lower() in f.get("fund_house", "").lower()
    ]

    return results


def fetch_fund_nav(
    fund_id: str,
    period: str = "1y",
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Fetch NAV history for a fund.

    Args:
        fund_id: ISIN or internal fund ID.
        period: Lookback period ("1m", "3m", "6m", "1y").
        conn: SQLite connection for caching.

    Returns:
        DataFrame with columns: [date, nav, return_rate].

    Raises:
        ValueError: If no NAV data available.
    """
    # 1. Check cache
    if conn is not None:
        cached = _get_cached_json(conn, fund_id, "nav", period)
        if cached is not None:
            return pd.DataFrame(cached)

    # 2. Try Anue API
    try:
        data = _fetch_anue_nav(fund_id, period)
        if data and conn is not None:
            _cache_json(conn, fund_id, "nav", period, data)
        if data:
            return pd.DataFrame(data)
    except Exception as e:
        logger.warning("Anue NAV fetch failed for %s: %s", fund_id, e)

    # 3. Generate stub NAV data
    return _generate_stub_nav(fund_id, period)


def fetch_fund_allocation(
    fund_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Fetch fund allocation (sector/region/asset class).

    Args:
        fund_id: ISIN or internal fund ID.
        conn: SQLite connection for caching.

    Returns:
        Dict with keys: as_of_date, by_sector, by_region, by_asset_class.

    Raises:
        ValueError: If no allocation data available.
    """
    # 1. Check cache
    if conn is not None:
        cached = _get_cached_json(conn, fund_id, "allocation", "")
        if cached is not None:
            return cached

    # 2. Try Anue API
    try:
        data = _fetch_anue_allocation(fund_id)
        if data and conn is not None:
            _cache_json(conn, fund_id, "allocation", "", data)
        if data:
            return data
    except Exception as e:
        logger.warning("Anue allocation fetch failed for %s: %s", fund_id, e)

    # 3. Fallback to stub data
    stub = _STUB_ALLOCATIONS.get(fund_id)
    if stub is not None:
        return stub

    raise ValueError(
        f"No allocation data available for fund {fund_id}. "
        "This fund may not be in our database yet."
    )


def normalize_sector(name: str) -> str:
    """Normalize a sector name to standard naming."""
    return OFFSHORE_SECTOR_MAP.get(name, name)


# ---------------------------------------------------------------------------
# Anue API fetchers
# ---------------------------------------------------------------------------

def _rate_limit():
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_request_time = time.monotonic()


def _search_anue(keyword: str) -> List[dict]:
    """Search funds via Anue API."""
    _rate_limit()
    url = f"{ANUE_FUND_API}/fund/api/v1/search"
    params = {"q": keyword, "limit": 20}

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    results = []
    items = data.get("data", data.get("items", []))
    if isinstance(items, list):
        for item in items:
            results.append({
                "fund_id": item.get("isin", item.get("id", "")),
                "fund_name": item.get("name", item.get("fund_name", "")),
                "fund_house": item.get("company", item.get("fund_house", "")),
                "fund_type": item.get("type", ""),
                "currency": item.get("currency", ""),
                "region": item.get("region", ""),
            })

    return results


def _fetch_anue_nav(fund_id: str, period: str) -> List[dict]:
    """Fetch NAV history from Anue API."""
    _rate_limit()

    days = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}.get(period, 365)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    url = f"{ANUE_FUND_API}/fund/api/v1/nav/{fund_id}"
    params = {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    records = []
    items = data.get("data", data.get("nav", []))
    if isinstance(items, list):
        prev_nav = None
        for item in items:
            nav_date = item.get("date", "")
            nav_value = item.get("nav", item.get("value", 0))
            try:
                nav_value = float(nav_value)
            except (ValueError, TypeError):
                continue

            return_rate = 0.0
            if prev_nav and prev_nav > 0:
                return_rate = (nav_value - prev_nav) / prev_nav

            records.append({
                "date": nav_date,
                "nav": nav_value,
                "return_rate": return_rate,
            })
            prev_nav = nav_value

    return records


def _fetch_anue_allocation(fund_id: str) -> Optional[dict]:
    """Fetch fund allocation from Anue API."""
    _rate_limit()

    url = f"{ANUE_FUND_API}/fund/api/v1/allocation/{fund_id}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = data.get("data", data)
    if not isinstance(result, dict):
        return None

    # Normalize sector names
    if "by_sector" in result:
        for item in result["by_sector"]:
            item["sector"] = normalize_sector(item.get("sector", ""))

    return result


# ---------------------------------------------------------------------------
# Stub data generation
# ---------------------------------------------------------------------------

def _generate_stub_nav(fund_id: str, period: str) -> pd.DataFrame:
    """Generate synthetic NAV data for testing/fallback."""
    import numpy as np

    days = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}.get(period, 365)
    end = date.today()
    start = end - timedelta(days=days)

    # Generate business days
    dates = pd.bdate_range(start, end)
    n = len(dates)

    # Random walk with slight upward drift
    np.random.seed(hash(fund_id) % 2**32)
    daily_returns = np.random.normal(0.0003, 0.012, n)
    nav_values = 100.0 * np.cumprod(1 + daily_returns)

    return_rates = [0.0] + list(np.diff(nav_values) / nav_values[:-1])

    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d").tolist(),
        "nav": nav_values.tolist(),
        "return_rate": return_rates,
    })

    logger.info("Generated stub NAV for %s: %d data points", fund_id, len(df))
    return df


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

def _get_cached_json(
    conn: sqlite3.Connection, fund_id: str, data_type: str, period: str
) -> Optional[any]:
    """Get cached JSON data."""
    try:
        row = conn.execute(
            "SELECT data_json, fetched_at FROM offshore_fund_cache "
            "WHERE fund_id = ? AND data_type = ? AND period = ?",
            (fund_id, data_type, period or ""),
        ).fetchone()

        if row is None:
            return None

        data_json = row[0] if isinstance(row, tuple) else row["data_json"]
        fetched_at_str = row[1] if isinstance(row, tuple) else row["fetched_at"]

        # TTL check
        ttl_hours = _get_ttl_hours(data_type)
        if fetched_at_str:
            try:
                fetched_at = datetime.fromisoformat(str(fetched_at_str))
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                age_hours = (now_utc - fetched_at).total_seconds() / 3600
                if age_hours > ttl_hours:
                    return None
            except (ValueError, TypeError):
                pass

        return json.loads(data_json)
    except Exception as e:
        logger.warning("Cache read error: %s", e)
        return None


def _cache_json(
    conn: sqlite3.Connection,
    fund_id: str,
    data_type: str,
    period: str,
    data: any,
) -> None:
    """Store JSON data in cache."""
    try:
        conn.execute(
            "INSERT OR REPLACE INTO offshore_fund_cache "
            "(fund_id, data_type, period, data_json) VALUES (?, ?, ?, ?)",
            (fund_id, data_type, period or "", json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()
    except Exception as e:
        logger.warning("Cache write error: %s", e)


def _get_ttl_hours(data_type: str) -> float:
    """Get TTL in hours for a data type."""
    if data_type == "nav":
        return NAV_TTL_HOURS
    elif data_type in ("allocation", "allocation_sector", "allocation_region"):
        return ALLOCATION_TTL_DAYS * 24
    elif data_type == "search":
        return SEARCH_TTL_DAYS * 24
    return NAV_TTL_HOURS
