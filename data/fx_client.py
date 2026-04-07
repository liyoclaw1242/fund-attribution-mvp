"""FX rate client — Taiwan Bank (台銀) exchange rate integration.

Primary source: rate.bot.com.tw (台銀牌告匯率)
Fallback: hardcoded recent rates (for offline/test scenarios)
Cache: SQLite fx_rate_cache table with TTL.

Supported currencies: USD, EUR, JPY, CNY, HKD, GBP, TWD.
"""

import logging
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = ["USD", "EUR", "JPY", "CNY", "HKD", "GBP", "TWD"]

# Taiwan Bank rate URL — returns HTML with exchange rates
BOT_RATE_URL = "https://rate.bot.com.tw/xrt/flcsv/0/day"

# Cache TTL
INTRADAY_TTL_HOURS = 4      # today's rate refreshes during trading hours
HISTORICAL_TTL_HOURS = 8760  # historical rates: 1 year (effectively permanent)

# Fallback rates (approximate, for when API is unavailable)
_FALLBACK_RATES = {
    "USDTWD": 32.5,
    "EURTWD": 35.0,
    "JPYTWD": 0.22,
    "CNYTWD": 4.5,
    "HKDTWD": 4.15,
    "GBPTWD": 41.0,
}


def get_exchange_rate(
    from_currency: str,
    to_currency: str,
    rate_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> float:
    """Get exchange rate (mid-price).

    Args:
        from_currency: Source currency code (e.g. "USD").
        to_currency: Target currency code (e.g. "TWD").
        rate_date: Date string YYYYMMDD. Default = today.
        conn: SQLite connection for caching.

    Returns:
        Exchange rate as float (e.g. 32.5 means 1 USD = 32.5 TWD).

    Raises:
        ValueError: If currency not supported or rate unavailable.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    _validate_currency(from_currency)
    _validate_currency(to_currency)

    if from_currency == to_currency:
        return 1.0

    if rate_date is None:
        rate_date = date.today().strftime("%Y%m%d")

    # TWD is always one side of the pair
    if to_currency == "TWD":
        pair = f"{from_currency}TWD"
        return _get_rate(pair, rate_date, conn)
    elif from_currency == "TWD":
        pair = f"{to_currency}TWD"
        rate = _get_rate(pair, rate_date, conn)
        return 1.0 / rate
    else:
        # Cross rate: FROM → TWD → TO
        from_twd = _get_rate(f"{from_currency}TWD", rate_date, conn)
        to_twd = _get_rate(f"{to_currency}TWD", rate_date, conn)
        return from_twd / to_twd


def convert_amount(
    amount: float,
    from_currency: str,
    to_currency: str,
    rate_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> float:
    """Convert amount between currencies.

    Args:
        amount: Amount in source currency.
        from_currency: Source currency code.
        to_currency: Target currency code.
        rate_date: Date string YYYYMMDD.
        conn: SQLite connection for caching.

    Returns:
        Converted amount in target currency.
    """
    rate = get_exchange_rate(from_currency, to_currency, rate_date, conn)
    return amount * rate


def get_fx_history(
    pair: str,
    period: str = "1y",
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Get exchange rate history.

    Args:
        pair: Currency pair (e.g. "USDTWD").
        period: Lookback period ("1m", "3m", "6m", "1y").
        conn: SQLite connection for caching.

    Returns:
        DataFrame with columns: [date, rate, change_pct].
    """
    pair = pair.upper()
    if len(pair) != 6:
        raise ValueError(f"Invalid pair format: {pair}. Expected 6 chars, e.g. 'USDTWD'")

    days = _period_to_days(period)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Try cache first
    rows = []
    if conn is not None:
        rows = _get_cached_history(conn, pair, start_date, end_date)

    if not rows:
        # Fetch from API for each business day
        rows = _fetch_history_range(pair, start_date, end_date, conn)

    if not rows:
        raise ValueError(f"No FX history available for {pair}")

    df = pd.DataFrame(rows, columns=["date", "rate"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.sort_values("date").reset_index(drop=True)
    df["change_pct"] = df["rate"].pct_change()
    return df


def adjust_returns_for_fx(
    returns_df: pd.DataFrame,
    from_currency: str,
    to_currency: str = "TWD",
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Adjust foreign currency returns to TWD.

    Uses the precise formula:
        TWD_return = (1 + R_foreign) * (1 + R_fx) - 1

    Where R_fx is the FX rate change for the period.

    Args:
        returns_df: DataFrame with columns [date, return_rate].
        from_currency: Currency of the returns.
        to_currency: Target currency (default TWD).
        conn: SQLite connection for caching.

    Returns:
        DataFrame with columns:
        [date, return_rate_foreign, fx_rate, return_rate_twd, fx_contribution]
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        result = returns_df.copy()
        result["return_rate_foreign"] = result["return_rate"]
        result["fx_rate"] = 1.0
        result["return_rate_twd"] = result["return_rate"]
        result["fx_contribution"] = 0.0
        return result

    pair = f"{from_currency}{to_currency}"

    result_rows = []
    prev_rate = None

    for _, row in returns_df.iterrows():
        dt = row["date"]
        if isinstance(dt, str):
            date_str = dt.replace("-", "")
        else:
            date_str = dt.strftime("%Y%m%d")

        try:
            fx_rate = get_exchange_rate(
                from_currency, to_currency, date_str, conn
            )
        except (ValueError, Exception):
            fx_rate = prev_rate or _FALLBACK_RATES.get(pair, 1.0)

        r_foreign = row["return_rate"]

        if prev_rate is not None and prev_rate > 0:
            r_fx = (fx_rate - prev_rate) / prev_rate
        else:
            r_fx = 0.0

        # Precise formula
        r_twd = (1 + r_foreign) * (1 + r_fx) - 1
        fx_contribution = r_twd - r_foreign

        result_rows.append({
            "date": row["date"],
            "return_rate_foreign": r_foreign,
            "fx_rate": fx_rate,
            "return_rate_twd": r_twd,
            "fx_contribution": fx_contribution,
        })

        prev_rate = fx_rate

    return pd.DataFrame(result_rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_currency(code: str) -> None:
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError(
            f"Unsupported currency: {code}. "
            f"Supported: {', '.join(SUPPORTED_CURRENCIES)}"
        )


def _get_rate(
    pair: str, rate_date: str, conn: Optional[sqlite3.Connection]
) -> float:
    """Get rate for a specific pair+date, with cache."""
    # 1. Check cache
    if conn is not None:
        cached = _get_cached_rate(conn, pair, rate_date)
        if cached is not None:
            return cached

    # 2. Fetch from Taiwan Bank
    try:
        rate = _fetch_bot_rate(pair, rate_date)
        if conn is not None:
            _cache_rate(conn, pair, rate_date, rate)
        return rate
    except Exception as e:
        logger.warning("BOT rate fetch failed for %s@%s: %s", pair, rate_date, e)

    # 3. Fallback
    fallback = _FALLBACK_RATES.get(pair)
    if fallback is not None:
        logger.info("Using fallback rate for %s: %s", pair, fallback)
        return fallback

    raise ValueError(f"No exchange rate available for {pair} on {rate_date}")


def _fetch_bot_rate(pair: str, rate_date: str) -> float:
    """Fetch exchange rate from Taiwan Bank CSV endpoint.

    The BOT CSV has columns:
    幣別, 匯率, 現金買入, 現金賣出, 即期買入, 即期賣出
    """
    currency = pair[:3]

    # Map currency codes to BOT currency names
    bot_names = {
        "USD": "美金",
        "EUR": "歐元",
        "JPY": "日圓",
        "CNY": "人民幣",
        "HKD": "港幣",
        "GBP": "英鎊",
    }

    bot_name = bot_names.get(currency)
    if bot_name is None:
        raise ValueError(f"Currency {currency} not available from BOT")

    url = BOT_RATE_URL
    if rate_date != date.today().strftime("%Y%m%d"):
        # Historical: use date-specific URL
        formatted = f"{rate_date[:4]}-{rate_date[4:6]}-{rate_date[6:8]}"
        url = f"https://rate.bot.com.tw/xrt/flcsv/0/{formatted}"

    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    # Parse CSV response
    lines = resp.text.strip().split("\n")
    for line in lines[1:]:  # skip header
        cols = line.split(",")
        if len(cols) >= 6:
            name = cols[0].strip().strip('"')
            if bot_name in name:
                # Use spot mid-price: avg of spot buy and spot sell
                try:
                    spot_buy = float(cols[4].strip().strip('"'))
                    spot_sell = float(cols[5].strip().strip('"'))
                    return (spot_buy + spot_sell) / 2.0
                except (ValueError, IndexError):
                    continue

    raise ValueError(f"Rate for {currency} not found in BOT response")


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

def _get_cached_rate(
    conn: sqlite3.Connection, pair: str, rate_date: str
) -> Optional[float]:
    """Check cache for a rate."""
    try:
        cursor = conn.execute(
            "SELECT rate, fetched_at FROM fx_rate_cache "
            "WHERE pair = ? AND date = ?",
            (pair, rate_date),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        # Handle both tuple and Row access
        if isinstance(row, tuple):
            rate, fetched_at_str = row[0], row[1]
        else:
            rate, fetched_at_str = row["rate"], row["fetched_at"]

        # Check TTL
        is_today = rate_date == date.today().strftime("%Y%m%d")
        ttl_hours = INTRADAY_TTL_HOURS if is_today else HISTORICAL_TTL_HOURS

        if fetched_at_str:
            try:
                fetched_at = datetime.fromisoformat(str(fetched_at_str))
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                age_hours = (now_utc - fetched_at).total_seconds() / 3600
                if age_hours > ttl_hours:
                    logger.debug("Cache expired for %s@%s (age=%.1fh)", pair, rate_date, age_hours)
                    return None
            except (ValueError, TypeError):
                pass  # Can't parse date, treat as valid

        return float(rate)
    except Exception as e:
        logger.warning("Cache read error for %s@%s: %s", pair, rate_date, e)
        return None


def _cache_rate(
    conn: sqlite3.Connection, pair: str, rate_date: str, rate: float
) -> None:
    """Store rate in cache."""
    try:
        conn.execute(
            "INSERT OR REPLACE INTO fx_rate_cache (pair, date, rate) "
            "VALUES (?, ?, ?)",
            (pair, rate_date, rate),
        )
        conn.commit()
    except Exception as e:
        logger.warning("Failed to cache FX rate: %s", e)


def _get_cached_history(
    conn: sqlite3.Connection, pair: str, start: date, end: date
) -> list:
    """Get cached historical rates for a date range."""
    try:
        rows = conn.execute(
            "SELECT date, rate FROM fx_rate_cache "
            "WHERE pair = ? AND date >= ? AND date <= ? "
            "ORDER BY date",
            (pair, start.strftime("%Y%m%d"), end.strftime("%Y%m%d")),
        ).fetchall()
        return [(r[0], r[1]) for r in rows] if rows else []
    except Exception:
        return []


def _fetch_history_range(
    pair: str, start: date, end: date,
    conn: Optional[sqlite3.Connection],
) -> list:
    """Fetch historical rates by trying cached + API for business days."""
    rows = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # business days only
            date_str = current.strftime("%Y%m%d")
            try:
                rate = _get_rate(pair, date_str, conn)
                rows.append((date_str, rate))
            except (ValueError, Exception):
                pass
        current += timedelta(days=1)
    return rows


def _period_to_days(period: str) -> int:
    """Convert period string to number of days."""
    mapping = {
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
    }
    return mapping.get(period, 365)
