"""SITCA fund holdings scraper — ASP.NET Postback automation.

Scrapes SITCA IN2629 (industry allocation) and IN2211 (fund returns)
pages by simulating ASP.NET __doPostBack form submissions.

Primary source: sitca.org.tw
Fallback: manual Excel files via sitca_parser.py
Cache: fund_holdings table in SQLite (TTL = 30 days)

Rate limiting: 3s delay between requests.
"""

import io
import logging
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# SITCA URLs
SITCA_BASE = "https://www.sitca.org.tw/ROC/Industry"
HOLDINGS_URL = f"{SITCA_BASE}/IN2629.aspx"
RETURNS_URL = f"{SITCA_BASE}/IN2211.aspx"

# Rate limiting: 3 seconds between requests
_RATE_LIMIT_DELAY = 3.0
_last_request_time: float = 0.0

# Cache TTL: 30 days (SITCA data is monthly)
CACHE_TTL_HOURS = 720

# Known investment trust company codes
COMPANY_CODES = {
    "A0001": "兆豐投信",
    "A0005": "元大投信",
    "A0010": "富邦投信",
    "A0015": "國泰投信",
    "A0020": "中國信託投信",
    "A0025": "群益投信",
    "A0030": "統一投信",
    "A0035": "復華投信",
    "A0040": "日盛投信",
    "A0045": "凱基投信",
    "A0050": "野村投信",
    "A0055": "安聯投信",
    "A0060": "新光投信",
    "A0065": "第一金投信",
    "A0070": "台新投信",
    "A0075": "永豐投信",
}

# Fund type codes
FUND_TYPES = {
    "AA1": "國內股票型",
    "AA2": "國內平衡型",
    "AC12": "固定收益型",
    "AD1": "ETF-股票型",
    "AD2": "ETF-債券型",
}


def fetch_fund_holdings(
    company_code: str,
    fund_type: Optional[str] = None,
    period: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Fetch fund industry allocation from SITCA IN2629.

    Args:
        company_code: Investment trust company code (e.g. "A0005").
        fund_type: Fund category code (e.g. "AA1"). None = all.
        period: YYYYMM format. None = latest available.
        conn: SQLite connection for caching.

    Returns:
        DataFrame: [fund_name, industry, weight]
        weight is a float 0-1.

    Raises:
        ValueError: If no data available.
    """
    if period is None:
        # Default to last month
        today = date.today()
        first = today.replace(day=1)
        last_month = first - timedelta(days=1)
        period = last_month.strftime("%Y%m")

    # Check cache
    if conn is not None:
        cached = _get_cached_holdings(conn, company_code, period)
        if cached is not None and len(cached) > 0:
            return cached

    # Try scraping
    try:
        df = _scrape_holdings(company_code, fund_type, period)
        if conn is not None and len(df) > 0:
            _cache_holdings(conn, df, company_code, period)
        return df
    except Exception as e:
        logger.warning(
            "SITCA scrape failed for %s/%s: %s — trying fallback",
            company_code, period, e,
        )

    # Fallback to manual Excel
    return _fallback_holdings(company_code, period)


def fetch_fund_returns(
    company_code: str,
    period: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """Fetch fund returns from SITCA IN2211.

    Args:
        company_code: Company code.
        period: YYYYMM format.
        conn: SQLite connection for caching.

    Returns:
        DataFrame: [fund_name, return_1m, return_3m, return_6m, return_1y]
    """
    if period is None:
        today = date.today()
        first = today.replace(day=1)
        last_month = first - timedelta(days=1)
        period = last_month.strftime("%Y%m")

    try:
        return _scrape_returns(company_code, period)
    except Exception as e:
        logger.warning("SITCA returns scrape failed: %s", e)
        return pd.DataFrame(
            columns=["fund_name", "return_1m", "return_3m", "return_6m", "return_1y"]
        )


def list_companies() -> dict:
    """Return known company codes and names."""
    return dict(COMPANY_CODES)


def list_fund_types() -> dict:
    """Return known fund type codes and names."""
    return dict(FUND_TYPES)


# ---------------------------------------------------------------------------
# ASP.NET scraping
# ---------------------------------------------------------------------------

def _rate_limit():
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_request_time = time.monotonic()


def _get_viewstate(session: requests.Session, url: str) -> dict:
    """GET the page and extract ASP.NET hidden fields."""
    _rate_limit()
    resp = session.get(url, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        tag = soup.find("input", {"name": name})
        if tag:
            fields[name] = tag.get("value", "")

    return fields


def _scrape_holdings(
    company_code: str, fund_type: Optional[str], period: str
) -> pd.DataFrame:
    """Scrape IN2629 page for fund holdings."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })

    # 1. GET page to obtain ViewState
    fields = _get_viewstate(session, HOLDINGS_URL)
    if not fields:
        raise ValueError("Failed to obtain SITCA ViewState")

    # 2. POST with company code and period
    year = period[:4]
    month = period[4:6]

    form_data = {
        **fields,
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnQuery",
        "__EVENTARGUMENT": "",
        "ctl00$ContentPlaceHolder1$ddlCompany": company_code,
        "ctl00$ContentPlaceHolder1$ddlYear": year,
        "ctl00$ContentPlaceHolder1$ddlMonth": month,
    }
    if fund_type:
        form_data["ctl00$ContentPlaceHolder1$ddlFundType"] = fund_type

    _rate_limit()
    resp = session.post(HOLDINGS_URL, data=form_data, timeout=30)
    resp.raise_for_status()

    # 3. Parse HTML table
    return _parse_holdings_html(resp.text)


def _parse_holdings_html(html: str) -> pd.DataFrame:
    """Parse fund holdings from SITCA HTML response."""
    soup = BeautifulSoup(html, "html.parser")

    # Find the main data table
    tables = soup.find_all("table", class_=re.compile("grid|data|table", re.I))
    if not tables:
        # Try pandas.read_html as fallback parser
        try:
            dfs = pd.read_html(io.StringIO(html))
            if dfs:
                return _normalize_holdings_df(dfs[0])
        except Exception:
            pass
        raise ValueError("No data table found in SITCA response")

    # Parse the first matching table
    rows = []
    for table in tables:
        trs = table.find_all("tr")
        for tr in trs:
            tds = tr.find_all(["td", "th"])
            if len(tds) >= 2:
                cells = [td.get_text(strip=True) for td in tds]
                rows.append(cells)

    if len(rows) < 2:
        raise ValueError("SITCA table has no data rows")

    df = pd.DataFrame(rows[1:], columns=rows[0] if rows[0] else None)
    return _normalize_holdings_df(df)


def _normalize_holdings_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize parsed DataFrame to standard format."""
    # Find relevant columns
    fund_col = _find_col(df, ["基金名稱", "基金", "fund_name", "Fund"])
    ind_col = _find_col(df, ["產業", "產業類別", "行業", "industry", "Industry"])
    weight_col = _find_col(df, ["比重", "比重(%)", "權重", "weight", "Weight"])

    if ind_col is None or weight_col is None:
        # Try to use first few columns as fallback
        cols = df.columns.tolist()
        if len(cols) >= 2:
            return pd.DataFrame({
                "fund_name": df.iloc[:, 0] if len(cols) >= 3 else "",
                "industry": df.iloc[:, -2] if len(cols) >= 3 else df.iloc[:, 0],
                "weight": pd.to_numeric(
                    df.iloc[:, -1].astype(str).str.replace("%", "").str.strip(),
                    errors="coerce",
                ).fillna(0) / 100,
            })
        raise ValueError("Cannot identify industry/weight columns")

    result = pd.DataFrame()
    result["fund_name"] = df[fund_col] if fund_col else ""
    result["industry"] = df[ind_col]
    # Convert percentage to decimal
    weight_values = df[weight_col].astype(str).str.replace("%", "").str.strip()
    result["weight"] = pd.to_numeric(weight_values, errors="coerce").fillna(0) / 100

    return result[result["weight"] > 0].reset_index(drop=True)


def _scrape_returns(company_code: str, period: str) -> pd.DataFrame:
    """Scrape IN2211 page for fund returns."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })

    fields = _get_viewstate(session, RETURNS_URL)
    if not fields:
        raise ValueError("Failed to obtain SITCA ViewState for returns page")

    year = period[:4]
    month = period[4:6]

    form_data = {
        **fields,
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnQuery",
        "__EVENTARGUMENT": "",
        "ctl00$ContentPlaceHolder1$ddlCompany": company_code,
        "ctl00$ContentPlaceHolder1$ddlYear": year,
        "ctl00$ContentPlaceHolder1$ddlMonth": month,
    }

    _rate_limit()
    resp = session.post(RETURNS_URL, data=form_data, timeout=30)
    resp.raise_for_status()

    return _parse_returns_html(resp.text)


def _parse_returns_html(html: str) -> pd.DataFrame:
    """Parse fund returns from SITCA HTML response."""
    try:
        dfs = pd.read_html(io.StringIO(html))
        if dfs:
            df = dfs[0]
            result = pd.DataFrame()

            fund_col = _find_col(df, ["基金名稱", "基金", "Fund"])
            result["fund_name"] = df[fund_col] if fund_col else df.iloc[:, 0]

            for period_name, candidates in [
                ("return_1m", ["一個月", "1M", "1月"]),
                ("return_3m", ["三個月", "3M", "3月"]),
                ("return_6m", ["六個月", "6M", "6月"]),
                ("return_1y", ["一年", "1Y", "12月"]),
            ]:
                col = _find_col(df, candidates)
                if col:
                    result[period_name] = pd.to_numeric(
                        df[col].astype(str).str.replace("%", ""),
                        errors="coerce",
                    ) / 100
                else:
                    result[period_name] = None

            return result
    except Exception as e:
        logger.warning("Failed to parse returns HTML: %s", e)

    return pd.DataFrame(
        columns=["fund_name", "return_1m", "return_3m", "return_6m", "return_1y"]
    )


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find first matching column name."""
    for col_name in df.columns:
        col_str = str(col_name)
        for candidate in candidates:
            if candidate in col_str:
                return col_name
    return None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _get_cached_holdings(
    conn: sqlite3.Connection, company_code: str, period: str
) -> Optional[pd.DataFrame]:
    """Check fund_holdings cache for SITCA data."""
    try:
        rows = conn.execute(
            "SELECT industry, weight FROM fund_holdings "
            "WHERE fund_code = ? AND period = ? AND source = 'sitca_scraper'",
            (company_code, period),
        ).fetchall()

        if not rows:
            return None

        # Check freshness
        fresh_row = conn.execute(
            "SELECT fetched_at FROM fund_holdings "
            "WHERE fund_code = ? AND period = ? AND source = 'sitca_scraper' "
            "ORDER BY fetched_at DESC LIMIT 1",
            (company_code, period),
        ).fetchone()

        if fresh_row:
            fetched_at_str = fresh_row[0]
            try:
                fetched_at = datetime.fromisoformat(str(fetched_at_str))
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                age_hours = (now_utc - fetched_at).total_seconds() / 3600
                if age_hours > CACHE_TTL_HOURS:
                    return None
            except (ValueError, TypeError):
                pass

        return pd.DataFrame(rows, columns=["industry", "weight"])

    except Exception as e:
        logger.warning("Cache read error: %s", e)
        return None


def _cache_holdings(
    conn: sqlite3.Connection, df: pd.DataFrame,
    company_code: str, period: str,
) -> None:
    """Store holdings in fund_holdings table."""
    try:
        # Calculate TTL expiry
        expires = (datetime.now(timezone.utc) + timedelta(hours=CACHE_TTL_HOURS)).isoformat()

        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO fund_holdings "
                "(fund_code, period, industry, weight, return_rate, source, expires_at) "
                "VALUES (?, ?, ?, ?, NULL, 'sitca_scraper', ?)",
                (company_code, period, row["industry"], float(row["weight"]), expires),
            )
        conn.commit()
    except Exception as e:
        logger.warning("Cache write error: %s", e)


def _fallback_holdings(company_code: str, period: str) -> pd.DataFrame:
    """Try loading from manual Excel as fallback."""
    from pathlib import Path
    from config.settings import SITCA_DATA_DIR

    data_dir = Path(SITCA_DATA_DIR)
    if not data_dir.exists():
        logger.info("No SITCA data directory at %s", data_dir)
        return pd.DataFrame(columns=["fund_name", "industry", "weight"])

    # Look for any matching Excel file
    patterns = [f"*{company_code}*{period}*", f"*{period}*", "*.xlsx", "*.xls"]
    for pattern in patterns:
        files = list(data_dir.glob(pattern))
        if files:
            try:
                from data.sitca_parser import parse_sitca_excel
                df = parse_sitca_excel(files[0])
                df["fund_name"] = files[0].stem
                return df[["fund_name", "industry", "weight"]]
            except Exception as e:
                logger.warning("Fallback Excel parse failed: %s", e)

    return pd.DataFrame(columns=["fund_name", "industry", "weight"])
