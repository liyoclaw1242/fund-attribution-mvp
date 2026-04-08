"""TWSE OpenAPI fetchers — industry index, daily stock prices, company info.

Three sub-fetchers, each extending BaseFetcher:
- TwseMiIndexFetcher: MI_INDEX (產業指數)
- TwseStockDayAllFetcher: STOCK_DAY_ALL (每日股價)
- TwseCompanyInfoFetcher: t187ap03_L (公司基本資料)

Respects TWSE_RATE_LIMIT_DELAY. Uses verify=False for TWSE's SSL cert.
"""

import asyncio
import logging
from datetime import date

import aiohttp
import pandas as pd

from pipeline.config import PipelineConfig
from pipeline.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

TWSE_BASE = "https://openapi.twse.com.tw/v1"

# Industry indices we care about (filter composites)
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


async def _twse_get(session: aiohttp.ClientSession, url: str, delay: float) -> list[dict]:
    """GET from TWSE with rate limiting and SSL bypass."""
    await asyncio.sleep(delay)
    async with session.get(url, ssl=False, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        data = await resp.json()
    if not isinstance(data, list):
        raise ValueError(f"TWSE returned unexpected type: {type(data)}")
    return data


class TwseMiIndexFetcher(BaseFetcher):
    """Fetch TWSE MI_INDEX (產業指數) every 30min during market hours."""

    source_name = "twse_mi_index"
    default_schedule = "*/30 9-14 * * 1-5"
    target_table = "industry_index"

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()
        self.delay = self.config.twse_rate_limit_delay

    async def fetch(self, params: dict) -> list[dict]:
        url = f"{TWSE_BASE}/exchangeReport/MI_INDEX"
        async with aiohttp.ClientSession() as session:
            raw = await _twse_get(session, url, self.delay)
        return raw

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        records = []
        today = date.today().isoformat()

        for item in raw:
            index_name = item.get("指數", "")
            if index_name not in TSE_INDUSTRY_INDICES:
                continue

            industry = index_name.replace("類指數", "").replace("指數", "")

            try:
                close_index = float(str(item.get("收盤指數", "0")).replace(",", ""))
            except (ValueError, TypeError):
                continue

            try:
                change_pct = float(str(item.get("漲跌百分比", "0")).replace(",", ""))
            except (ValueError, TypeError):
                change_pct = 0.0

            records.append({
                "industry": industry,
                "date": today,
                "close_index": close_index,
                "change_pct": change_pct,
                "source": "twse",
            })

        return pd.DataFrame(records) if records else pd.DataFrame()


class TwseStockDayAllFetcher(BaseFetcher):
    """Fetch TWSE STOCK_DAY_ALL (每日收盤) daily after market close."""

    source_name = "twse_stock_day_all"
    default_schedule = "0 16 * * 1-5"
    target_table = "stock_price"

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()
        self.delay = self.config.twse_rate_limit_delay

    async def fetch(self, params: dict) -> list[dict]:
        url = f"{TWSE_BASE}/exchangeReport/STOCK_DAY_ALL"
        async with aiohttp.ClientSession() as session:
            raw = await _twse_get(session, url, self.delay)
        return raw

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        records = []
        today = date.today().isoformat()

        for item in raw:
            stock_id = item.get("Code", "").strip()
            if not stock_id:
                continue

            try:
                close_price = float(str(item.get("ClosingPrice", "0")).replace(",", ""))
            except (ValueError, TypeError):
                continue

            try:
                change_pct = float(str(item.get("Change", "0")).replace(",", ""))
            except (ValueError, TypeError):
                change_pct = 0.0

            try:
                volume = int(str(item.get("TradeVolume", "0")).replace(",", ""))
            except (ValueError, TypeError):
                volume = 0

            records.append({
                "stock_id": stock_id,
                "date": today,
                "close_price": close_price,
                "change_pct": change_pct,
                "volume": volume,
                "market_cap": None,
                "source": "twse",
            })

        return pd.DataFrame(records) if records else pd.DataFrame()


class TwseCompanyInfoFetcher(BaseFetcher):
    """Fetch TWSE t187ap03_L (公司基本資料) weekly."""

    source_name = "twse_company_info"
    default_schedule = "0 1 * * 1"
    target_table = "stock_info"

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()
        self.delay = self.config.twse_rate_limit_delay

    async def fetch(self, params: dict) -> list[dict]:
        url = f"{TWSE_BASE}/opendata/t187ap03_L"
        async with aiohttp.ClientSession() as session:
            raw = await _twse_get(session, url, self.delay)
        return raw

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        records = []
        for item in raw:
            stock_id = item.get("公司代號", "").strip()
            if not stock_id:
                continue

            records.append({
                "stock_id": stock_id,
                "stock_name": item.get("公司簡稱", item.get("公司名稱", "")),
                "market": "twse",
                "industry": item.get("產業類別", ""),
                "industry_source": "tse28",
                "shares_outstanding": None,
            })

        return pd.DataFrame(records) if records else pd.DataFrame()
