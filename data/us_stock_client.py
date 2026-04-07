"""US stock data client — yfinance integration.

Fetches US stock prices, fundamentals, and GICS sector classification.
Provides S&P 500 sector weights as benchmark (Wb).

Rate limiting: 2s delay between requests to avoid being blocked.
Cache: SQLite us_stock_cache table with TTL.
"""

import logging
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Rate limiting
_RATE_LIMIT_DELAY = 2.0
_last_request_time: float = 0.0

# GICS sector English → Chinese mapping
GICS_SECTORS = {
    "Technology": "資訊科技",
    "Health Care": "醫療保健",
    "Financials": "金融",
    "Consumer Discretionary": "非必需消費",
    "Consumer Staples": "必需消費",
    "Energy": "能源",
    "Industrials": "工業",
    "Materials": "原材料",
    "Utilities": "公用事業",
    "Real Estate": "不動產",
    "Communication Services": "通訊服務",
}

# S&P 500 approximate sector weights (as of 2026-Q1)
# Source: approximation from public data
_SP500_SECTOR_WEIGHTS = {
    "資訊科技": 0.32,
    "醫療保健": 0.12,
    "金融": 0.13,
    "非必需消費": 0.10,
    "通訊服務": 0.09,
    "工業": 0.08,
    "必需消費": 0.06,
    "能源": 0.04,
    "公用事業": 0.02,
    "不動產": 0.02,
    "原材料": 0.02,
}


def fetch_stock_info(ticker: str) -> dict:
    """Fetch basic info for a US stock.

    Args:
        ticker: US stock ticker symbol (e.g. "AAPL").

    Returns:
        Dict with keys: ticker, name, sector, industry, currency, market_cap.

    Raises:
        ValueError: If ticker not found or data unavailable.
    """
    ticker = ticker.upper().strip()
    try:
        import yfinance as yf
        _rate_limit()

        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get("regularMarketPrice") is None:
            raise ValueError(f"No data found for ticker {ticker}")

        sector_en = info.get("sector", "")
        sector_zh = GICS_SECTORS.get(sector_en, sector_en)

        return {
            "ticker": ticker,
            "name": info.get("longName", info.get("shortName", ticker)),
            "sector": sector_zh,
            "sector_en": sector_en,
            "industry": info.get("industry", ""),
            "currency": info.get("currency", "USD"),
            "market_cap": info.get("marketCap", 0),
        }

    except ImportError:
        raise ValueError("yfinance not installed. Run: pip install yfinance")
    except Exception as e:
        if "No data found" in str(e) or "not found" in str(e).lower():
            raise ValueError(f"Ticker {ticker} not found") from e
        raise ValueError(f"Failed to fetch info for {ticker}: {e}") from e


def fetch_stock_history(
    ticker: str,
    period: str = "1y",
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Fetch historical stock prices.

    Args:
        ticker: Stock ticker symbol.
        period: Lookback period ("1mo", "3mo", "6mo", "1y", "5y").
        conn: SQLite connection for caching.

    Returns:
        DataFrame with columns: [date, open, high, low, close, volume, return_rate].

    Raises:
        ValueError: If no history data available.
    """
    ticker = ticker.upper().strip()

    # Check cache
    if conn is not None:
        cached = _get_cached_history(conn, ticker, period)
        if cached is not None and len(cached) > 0:
            return cached

    try:
        import yfinance as yf
        _rate_limit()

        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)

        if hist.empty:
            raise ValueError(f"No history data for {ticker}")

        df = pd.DataFrame({
            "date": hist.index.strftime("%Y-%m-%d").tolist(),
            "open": hist["Open"].values,
            "high": hist["High"].values,
            "low": hist["Low"].values,
            "close": hist["Close"].values,
            "volume": hist["Volume"].values,
        })

        # Calculate daily returns
        df["return_rate"] = df["close"].pct_change().fillna(0)

        # Cache results
        if conn is not None:
            _cache_history(conn, ticker, df)

        return df

    except ImportError:
        raise ValueError("yfinance not installed")
    except Exception as e:
        raise ValueError(f"Failed to fetch history for {ticker}: {e}") from e


def fetch_portfolio_us(
    holdings: List[dict],
    period: str = "1mo",
) -> pd.DataFrame:
    """Batch-fetch US stock portfolio data.

    Args:
        holdings: List of dicts with ticker, shares, cost_basis_usd.
        period: Period for return calculation.

    Returns:
        DataFrame: [ticker, name, sector, weight, return_rate, market_value_usd].
    """
    if not holdings:
        return pd.DataFrame(
            columns=["ticker", "name", "sector", "weight", "return_rate", "market_value_usd"]
        )

    results = []
    total_value = 0

    for h in holdings:
        ticker = h["ticker"].upper()
        shares = h.get("shares", 0)
        cost = h.get("cost_basis_usd", 0)

        try:
            info = fetch_stock_info(ticker)
            hist = fetch_stock_history(ticker, period)

            if len(hist) >= 2:
                period_return = (hist["close"].iloc[-1] / hist["close"].iloc[0]) - 1
            else:
                period_return = 0.0

            # Use latest close price for current market value
            current_price = hist["close"].iloc[-1] if len(hist) > 0 else 0
            market_value = shares * current_price if shares > 0 else cost

            results.append({
                "ticker": ticker,
                "name": info["name"],
                "sector": info["sector"],
                "weight": 0,  # calculated after total_value known
                "return_rate": period_return,
                "market_value_usd": market_value,
            })
            total_value += market_value

        except Exception as e:
            logger.warning("Failed to fetch %s: %s — skipping", ticker, e)

    # Calculate weights
    if total_value > 0:
        for r in results:
            r["weight"] = r["market_value_usd"] / total_value

    return pd.DataFrame(results)


def get_sp500_sector_weights() -> pd.DataFrame:
    """Get S&P 500 sector weights as US stock benchmark.

    Returns:
        DataFrame with columns: [sector, Wb, Rb].
        Rb is set to 0 (placeholder — live benchmark returns require
        separate ETF data feed).
    """
    rows = []
    for sector, weight in _SP500_SECTOR_WEIGHTS.items():
        rows.append({
            "sector": sector,
            "Wb": weight,
            "Rb": 0.0,  # placeholder
        })
    return pd.DataFrame(rows)


def translate_sector(sector_en: str) -> str:
    """Translate GICS sector name from English to Chinese."""
    return GICS_SECTORS.get(sector_en, sector_en)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def _rate_limit():
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_request_time = time.monotonic()


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

def _get_cached_history(
    conn: sqlite3.Connection, ticker: str, period: str
) -> Optional[pd.DataFrame]:
    """Get cached stock history."""
    try:
        days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "5y": 1825}.get(period, 365)
        cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

        rows = conn.execute(
            "SELECT date, close_price, return_rate FROM us_stock_cache "
            "WHERE ticker = ? AND date >= ? ORDER BY date",
            (ticker, cutoff),
        ).fetchall()

        if not rows or len(rows) < 5:  # need minimum data
            return None

        # Check freshness
        latest_row = conn.execute(
            "SELECT fetched_at FROM us_stock_cache "
            "WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
        ).fetchone()

        if latest_row:
            fetched_at_str = latest_row[0]
            try:
                fetched_at = datetime.fromisoformat(str(fetched_at_str))
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                age_hours = (now_utc - fetched_at).total_seconds() / 3600
                if age_hours > 24:
                    return None
            except (ValueError, TypeError):
                pass

        df = pd.DataFrame(rows, columns=["date", "close", "return_rate"])
        df["open"] = df["close"]  # approximate
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["volume"] = 0
        return df[["date", "open", "high", "low", "close", "volume", "return_rate"]]

    except Exception as e:
        logger.warning("Cache read error for %s: %s", ticker, e)
        return None


def _cache_history(
    conn: sqlite3.Connection, ticker: str, df: pd.DataFrame
) -> None:
    """Cache stock history data."""
    try:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO us_stock_cache "
                "(ticker, date, close_price, return_rate) VALUES (?, ?, ?, ?)",
                (ticker, row["date"], float(row["close"]), float(row["return_rate"])),
            )
        conn.commit()
    except Exception as e:
        logger.warning("Cache write error for %s: %s", ticker, e)
