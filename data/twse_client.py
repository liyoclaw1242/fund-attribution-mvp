"""Fetch industry index data from TWSE OpenAPI.

Endpoints:
  - Industry Index: GET https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX
  - TWT49U: DEPRECATED (returns 404 as of 2026-04-06)

Rate limit: 3 req / 5s, 2s delay between requests.
Cache: 24h TTL in SQLite benchmark_index table.
Fallback: manual CSV if API fails.
"""

import csv
import logging
import time
from pathlib import Path
from typing import Optional

import requests
import urllib3

from config.settings import TWSE_RATE_LIMIT_DELAY

# TWSE SSL cert missing Subject Key Identifier — suppress warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

TWSE_BASE = "https://openapi.twse.com.tw/v1/exchangeReport"
MI_INDEX_URL = f"{TWSE_BASE}/MI_INDEX"

# Industry-level indices we care about for Brinson benchmark
# (filter out composite/themed indices from MI_INDEX response)
TSE_INDUSTRY_INDICES = {
    "水泥類指數", "食品類指數", "塑膠類指數", "紡織纖維類指數",
    "電機機械類指數", "電器電纜類指數", "化學類指數", "生技醫療類指數",
    "玻璃陶瓷類指數", "造紙類指數", "鋼鐵類指數", "橡膠類指數",
    "汽車類指數", "電子工業類指數", "半導體類指數", "電腦及週邊設備類指數",
    "光電類指數", "通信網路類指數", "電子零組件類指數", "電子通路類指數",
    "資訊服務類指數", "其他電子類指數", "建材營造類指數", "航運類指數",
    "觀光餐旅類指數", "金融保險類指數", "貿易百貨類指數", "油電燃氣類指數",
    "綠能環保類指數", "數位雲端類指數", "運動休閒類指數", "居家生活類指數",
    "其他類指數",
}


class RateLimiter:
    """Simple rate limiter: enforces minimum delay between requests."""

    def __init__(self, min_delay: float = TWSE_RATE_LIMIT_DELAY):
        self._min_delay = min_delay
        self._last_request: float = 0.0

    def wait(self) -> None:
        """Block until enough time has elapsed since last request."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed)
        self._last_request = time.monotonic()


# Module-level rate limiter shared across all calls
_rate_limiter = RateLimiter()


def fetch_mi_index(rate_limiter: Optional[RateLimiter] = None) -> list[dict]:
    """Fetch MI_INDEX data from TWSE OpenAPI.

    Returns list of dicts with keys: 日期, 指數, 收盤指數, 漲跌, 漲跌點數, 漲跌百分比.

    Raises:
        requests.RequestException: On network/HTTP errors.
        ValueError: If response is not valid JSON.
    """
    limiter = rate_limiter or _rate_limiter
    limiter.wait()

    resp = requests.get(MI_INDEX_URL, timeout=10, verify=False)
    resp.raise_for_status()

    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"MI_INDEX returned unexpected type: {type(data)}")

    return data


def get_industry_indices(
    conn=None,
    rate_limiter: Optional[RateLimiter] = None,
    fallback_csv: Optional[str | Path] = None,
) -> list[dict]:
    """Get TSE industry index data, with cache and fallback.

    Flow:
    1. Check SQLite cache (benchmark_index, 24h TTL)
    2. If miss → fetch from TWSE API
    3. If API fails → load from fallback CSV
    4. Store fresh data in cache

    Args:
        conn: SQLite connection for caching. If None, no caching.
        rate_limiter: Optional rate limiter override (for testing).
        fallback_csv: Path to fallback CSV file.

    Returns:
        List of dicts: [{index_name, closing_price, change_pct}, ...]
    """
    # 1. Check cache
    if conn is not None:
        from data.cache import get_benchmark_index
        cached = get_benchmark_index(conn, "MI_INDEX", "latest")
        if cached is not None:
            logger.info("MI_INDEX cache hit — %d records", len(cached))
            return cached

    # 2. Fetch from API
    try:
        raw = fetch_mi_index(rate_limiter)
        records = _parse_mi_index(raw)
        logger.info("MI_INDEX fetched — %d industry records", len(records))
    except Exception as e:
        logger.warning("TWSE API failed: %s — trying fallback", e)
        # 3. Fallback to CSV
        if fallback_csv is not None:
            records = _load_fallback_csv(fallback_csv)
            logger.info("Loaded %d records from fallback CSV", len(records))
        else:
            raise

    # 4. Store in cache
    if conn is not None and records:
        from data.cache import upsert_benchmark_index
        upsert_benchmark_index(conn, "MI_INDEX", "latest", records, ttl_hours=24)
        logger.info("MI_INDEX cached — %d records", len(records))

    return records


def _parse_mi_index(raw: list[dict]) -> list[dict]:
    """Filter and normalize MI_INDEX response to industry-level indices."""
    records = []
    for item in raw:
        index_name = item.get("指數", "")
        if index_name not in TSE_INDUSTRY_INDICES:
            continue

        # Strip "類指數" suffix to get industry name
        industry = index_name.replace("類指數", "").replace("指數", "")

        try:
            closing = float(item["收盤指數"].replace(",", ""))
        except (ValueError, KeyError):
            continue

        try:
            change_pct = float(item["漲跌百分比"].replace(",", ""))
        except (ValueError, KeyError):
            change_pct = 0.0

        records.append({
            "industry": industry,
            "weight": 0.0,  # weight computed later by industry_mapper
            "return_rate": change_pct / 100.0,  # convert percentage to decimal
            "index_name": index_name,
            "closing_price": closing,
        })

    return records


def _load_fallback_csv(csv_path: str | Path) -> list[dict]:
    """Load industry index data from a manually prepared CSV.

    Expected columns: industry, weight, return_rate
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Fallback CSV not found: {csv_path}")

    records = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "industry": row["industry"],
                "weight": float(row.get("weight", 0.0)),
                "return_rate": float(row.get("return_rate", 0.0)),
            })

    if not records:
        raise ValueError(f"Fallback CSV is empty: {csv_path}")

    return records
