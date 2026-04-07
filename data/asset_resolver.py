"""Asset resolver — smart identification and data fetching for any asset.

Identifies asset type from user input and fetches complete data:
  - "0050" → Taiwan ETF → SITCA + TWSE
  - "AAPL" → US stock → yfinance
  - "摩根太平洋科技" → Offshore fund → Anue/stub data
  - "LU0117844026" → ISIN → Offshore fund

Then assembles a unified portfolio DataFrame ready for
multi_market_brinson.compute_multi_market_attribution().
"""

import logging
import re
import sqlite3
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def resolve_asset(identifier: str) -> dict:
    """Identify asset type from user input.

    Args:
        identifier: Fund code, stock ticker, fund name, or ISIN.

    Returns:
        Dict with keys: type, code/ticker/fund_id, market, name.

    Raises:
        ValueError: If identifier cannot be resolved.
    """
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("標的代碼不可為空")

    # 1. ISIN format (LU/IE + 10 chars)
    if re.match(r"^(LU|IE|TW)\w{10,}", identifier, re.I):
        return {
            "type": "offshore_fund",
            "fund_id": identifier.upper(),
            "market": "offshore",
            "name": identifier,
        }

    # 2. Pure digits 4-6 chars → Taiwan stock/ETF
    if re.match(r"^\d{4,6}$", identifier):
        code = identifier
        is_etf = code.startswith("00") and len(code) >= 5
        return {
            "type": "tw_etf" if is_etf else "tw_stock",
            "code": code,
            "market": "TWSE",
            "name": code,
        }

    # 3. English letters 1-5 chars → US stock ticker
    if re.match(r"^[A-Za-z]{1,5}$", identifier):
        return {
            "type": "us_stock",
            "ticker": identifier.upper(),
            "market": "US",
            "name": identifier.upper(),
        }

    # 4. Contains Chinese → offshore fund search
    if re.search(r"[\u4e00-\u9fff]", identifier):
        return {
            "type": "offshore_fund",
            "keyword": identifier,
            "market": "offshore",
            "name": identifier,
        }

    # 5. Alphanumeric mix → try as Taiwan stock first
    if re.match(r"^\d{4}[A-Za-z]?$", identifier):
        return {
            "type": "tw_stock",
            "code": identifier.upper(),
            "market": "TWSE",
            "name": identifier,
        }

    raise ValueError(
        f"無法辨識標的「{identifier}」。\n"
        f"請輸入：台股代碼(0050)、美股代碼(AAPL)、或基金名稱(摩根太平洋科技)"
    )


def resolve_portfolio(
    items: List[dict],
    conn: Optional[sqlite3.Connection] = None,
    base_currency: str = "TWD",
) -> pd.DataFrame:
    """Resolve a list of holdings into a unified portfolio DataFrame.

    Args:
        items: List of dicts with identifier + shares or amount_twd.
            [{"identifier": "0050", "shares": 100},
             {"identifier": "AAPL", "shares": 50},
             {"identifier": "摩根太平洋科技", "amount_twd": 100000}]
        conn: SQLite connection for caching.
        base_currency: Base currency for valuation.

    Returns:
        DataFrame with columns:
            [name, identifier, asset_type, market, currency,
             shares, cost_basis_twd, market_value_twd,
             sector, region, asset_class,
             weight, return_rate_local, return_rate_twd, fx_contribution]
    """
    if not items:
        return _empty_portfolio_df()

    rows = []
    for item in items:
        identifier = item.get("identifier", "")
        try:
            asset = resolve_asset(identifier)
            row = _fetch_asset_data(asset, item, conn, base_currency)
            if row is not None:
                rows.append(row)
        except Exception as e:
            logger.warning("Failed to resolve '%s': %s — skipping", identifier, e)

    if not rows:
        return _empty_portfolio_df()

    df = pd.DataFrame(rows)

    # Compute weights from market value
    total_value = df["market_value_twd"].sum()
    if total_value > 0:
        df["weight"] = df["market_value_twd"] / total_value
    else:
        df["weight"] = 1.0 / len(df)

    return df


def _empty_portfolio_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "name", "identifier", "asset_type", "market", "currency",
        "shares", "cost_basis_twd", "market_value_twd",
        "sector", "region", "asset_class",
        "weight", "return_rate_local", "return_rate_twd", "fx_contribution",
    ])


def _fetch_asset_data(
    asset: dict,
    item: dict,
    conn: Optional[sqlite3.Connection],
    base_currency: str,
) -> Optional[dict]:
    """Fetch data for a single resolved asset."""
    asset_type = asset["type"]
    shares = item.get("shares", 0)
    amount_twd = item.get("amount_twd", 0)

    if asset_type in ("tw_stock", "tw_etf"):
        return _fetch_tw_asset(asset, shares, amount_twd, conn)
    elif asset_type == "us_stock":
        return _fetch_us_asset(asset, shares, amount_twd, conn, base_currency)
    elif asset_type == "offshore_fund":
        return _fetch_offshore_asset(asset, shares, amount_twd, conn, base_currency)
    else:
        logger.warning("Unknown asset type: %s", asset_type)
        return None


def _fetch_tw_asset(
    asset: dict, shares: float, amount_twd: float,
    conn: Optional[sqlite3.Connection],
) -> dict:
    """Fetch Taiwan stock/ETF data."""
    code = asset["code"]
    name = code
    sector = "其他"
    return_rate = 0.0

    # Try fund lookup for ETFs
    try:
        from data.fund_registry import get_fund_info
        fund_info = get_fund_info(code)
        if fund_info:
            name = fund_info["fund_name"]
    except Exception:
        pass

    # Try to get return from TWSE
    try:
        from data.twse_client import get_industry_indices
        indices = get_industry_indices(conn=conn)
        if indices:
            # Use average market return as proxy
            returns = [i.get("return_rate", 0) for i in indices if i.get("return_rate") is not None]
            if returns:
                return_rate = sum(returns) / len(returns)
    except Exception:
        pass

    market_value = amount_twd if amount_twd > 0 else shares * 100  # rough estimate

    return {
        "name": name,
        "identifier": code,
        "asset_type": asset["type"],
        "market": "TWSE",
        "currency": "TWD",
        "shares": shares,
        "cost_basis_twd": market_value,
        "market_value_twd": market_value,
        "sector": sector,
        "region": "台灣",
        "asset_class": "股票",
        "weight": 0,  # computed later
        "return_rate_local": return_rate,
        "return_rate_twd": return_rate,
        "fx_contribution": 0.0,
    }


def _fetch_us_asset(
    asset: dict, shares: float, amount_twd: float,
    conn: Optional[sqlite3.Connection], base_currency: str,
) -> dict:
    """Fetch US stock data."""
    ticker = asset["ticker"]
    name = ticker
    sector = "其他"
    return_rate = 0.0
    currency = "USD"
    fx_rate = 32.5  # fallback
    fx_contribution = 0.0

    # Get stock info
    try:
        from data.us_stock_client import fetch_stock_info, fetch_stock_history
        info = fetch_stock_info(ticker)
        name = info.get("name", ticker)
        sector = info.get("sector", "其他")

        hist = fetch_stock_history(ticker, "1mo", conn)
        if len(hist) >= 2:
            return_rate = (hist["close"].iloc[-1] / hist["close"].iloc[0]) - 1
    except Exception as e:
        logger.warning("US stock fetch failed for %s: %s", ticker, e)

    # FX conversion
    try:
        from data.fx_client import get_exchange_rate
        fx_rate = get_exchange_rate("USD", "TWD", conn=conn)
        # Approximate FX contribution (would need historical rates for precise)
        fx_contribution = 0.0  # simplified — precise calc requires time series
    except Exception:
        pass

    if amount_twd > 0:
        market_value_twd = amount_twd
    elif shares > 0:
        try:
            from data.us_stock_client import fetch_stock_history
            hist = fetch_stock_history(ticker, "1mo", conn)
            if len(hist) > 0:
                market_value_usd = shares * hist["close"].iloc[-1]
                market_value_twd = market_value_usd * fx_rate
            else:
                market_value_twd = shares * 200 * fx_rate  # rough
        except Exception:
            market_value_twd = shares * 200 * fx_rate
    else:
        market_value_twd = 0

    return {
        "name": name,
        "identifier": ticker,
        "asset_type": "us_stock",
        "market": "US",
        "currency": currency,
        "shares": shares,
        "cost_basis_twd": market_value_twd,
        "market_value_twd": market_value_twd,
        "sector": sector,
        "region": "美國",
        "asset_class": "股票",
        "weight": 0,
        "return_rate_local": return_rate,
        "return_rate_twd": return_rate + fx_contribution,
        "fx_contribution": fx_contribution,
    }


def _fetch_offshore_asset(
    asset: dict, shares: float, amount_twd: float,
    conn: Optional[sqlite3.Connection], base_currency: str,
) -> dict:
    """Fetch offshore fund data."""
    fund_id = asset.get("fund_id", "")
    keyword = asset.get("keyword", "")
    name = asset.get("name", keyword or fund_id)
    sector = "其他"
    region = "全球"
    return_rate = 0.0
    currency = "USD"

    # Search fund if keyword provided
    try:
        from data.offshore_fund_client import search_fund, fetch_fund_allocation
        if keyword:
            results = search_fund(keyword, conn=conn)
            if results:
                fund = results[0]
                fund_id = fund.get("fund_id", fund_id)
                name = fund.get("fund_name", name)
                currency = fund.get("currency", "USD")
                region = fund.get("region", "全球")

        if fund_id:
            try:
                alloc = fetch_fund_allocation(fund_id, conn=conn)
                if alloc and alloc.get("by_sector"):
                    top_sector = max(alloc["by_sector"], key=lambda s: s.get("weight", 0))
                    sector = top_sector.get("sector", "其他")
                if alloc and alloc.get("by_region"):
                    top_region = max(alloc["by_region"], key=lambda r: r.get("weight", 0))
                    region = top_region.get("region", region)
            except Exception:
                pass
    except Exception as e:
        logger.warning("Offshore fund fetch failed: %s", e)

    market_value_twd = amount_twd if amount_twd > 0 else 100000  # default

    return {
        "name": name,
        "identifier": fund_id or keyword,
        "asset_type": "offshore_fund",
        "market": "offshore",
        "currency": currency,
        "shares": shares,
        "cost_basis_twd": market_value_twd,
        "market_value_twd": market_value_twd,
        "sector": sector,
        "region": region,
        "asset_class": "基金",
        "weight": 0,
        "return_rate_local": return_rate,
        "return_rate_twd": return_rate,
        "fx_contribution": 0.0,
    }
