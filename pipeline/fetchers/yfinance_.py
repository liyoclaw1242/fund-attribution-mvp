"""yfinance fetcher — US stock prices and sector info.

Batch downloads S&P 500 daily prices and maps GICS sectors.
"""

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from pipeline.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

# Top S&P 500 tickers for MVP (expand via config later)
DEFAULT_TICKERS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "BRK-B", "TSLA",
    "UNH", "XOM", "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK",
    "ABBV", "LLY", "PEP", "KO", "COST", "AVGO", "WMT", "MCD", "CSCO",
    "ACN", "TMO", "ABT", "DHR", "NEE", "LIN", "PM", "TXN", "CRM",
]

# GICS sector mapping for unified taxonomy
GICS_TO_UNIFIED = {
    "Technology": "資訊科技",
    "Healthcare": "醫療保健",
    "Financial Services": "金融",
    "Consumer Cyclical": "非必需消費",
    "Communication Services": "通訊服務",
    "Industrials": "工業",
    "Consumer Defensive": "必需消費",
    "Energy": "能源",
    "Utilities": "公用事業",
    "Real Estate": "不動產",
    "Basic Materials": "原材料",
}


class YfinanceFetcher(BaseFetcher):
    """Fetch US stock prices via yfinance."""

    source_name = "yfinance"
    default_schedule = "0 6 * * 1-5"
    target_table = "stock_price"

    def __init__(self, tickers: list[str] | None = None):
        self.tickers = tickers or DEFAULT_TICKERS

    async def fetch(self, params: dict) -> list[dict]:
        """Download daily prices for configured tickers.

        Args:
            params: {"period": "5d"} or {"start": "2026-01-01", "end": "2026-04-01"}.
        """
        period = params.get("period", "5d")
        start = params.get("start")
        end = params.get("end")

        tickers_str = " ".join(self.tickers)
        logger.info("Fetching %d US tickers (%s)", len(self.tickers), period)

        try:
            if start and end:
                df = yf.download(tickers_str, start=start, end=end, group_by="ticker", auto_adjust=True)
            else:
                df = yf.download(tickers_str, period=period, group_by="ticker", auto_adjust=True)
        except Exception:
            logger.exception("yfinance download failed")
            return []

        if df.empty:
            return []

        records = []
        for ticker in self.tickers:
            try:
                if len(self.tickers) == 1:
                    ticker_df = df
                else:
                    ticker_df = df[ticker] if ticker in df.columns.get_level_values(0) else None

                if ticker_df is None or ticker_df.empty:
                    continue

                for dt, row in ticker_df.iterrows():
                    close = row.get("Close")
                    if pd.isna(close):
                        continue
                    records.append({
                        "stock_id": f"US_{ticker}",
                        "date": dt.date() if hasattr(dt, "date") else dt,
                        "close_price": float(close),
                        "change_pct": float(row["Close"] / row["Open"] - 1) if row.get("Open") and not pd.isna(row.get("Open")) and row["Open"] != 0 else None,
                        "volume": int(row["Volume"]) if not pd.isna(row.get("Volume", float("nan"))) else None,
                        "market_cap": None,
                        "source": "yfinance",
                    })
            except Exception:
                logger.exception("Failed to process ticker %s", ticker)

        return records

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Normalize to stock_price schema."""
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        return df[["stock_id", "date", "close_price", "change_pct",
                    "volume", "market_cap", "source"]]


class YfinanceInfoFetcher(BaseFetcher):
    """Fetch US stock info (sector, market cap) via yfinance — run weekly."""

    source_name = "yfinance_info"
    default_schedule = "0 7 * * 6"
    target_table = "stock_info"

    def __init__(self, tickers: list[str] | None = None):
        self.tickers = tickers or DEFAULT_TICKERS

    async def fetch(self, params: dict) -> list[dict]:
        records = []
        for ticker in self.tickers:
            try:
                info = yf.Ticker(ticker).info
                sector = info.get("sector", "")
                records.append({
                    "stock_id": f"US_{ticker}",
                    "stock_name": info.get("shortName", ticker),
                    "market": "us",
                    "industry": GICS_TO_UNIFIED.get(sector, sector),
                    "industry_source": "gics",
                    "shares_outstanding": info.get("sharesOutstanding"),
                })
            except Exception:
                logger.exception("Failed to fetch info for %s", ticker)
        return records

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        return df[["stock_id", "stock_name", "market", "industry",
                    "industry_source", "shares_outstanding"]]
