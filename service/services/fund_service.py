"""Fund lookup and search service.

Reads from SQLite cache.db (fund_holdings, benchmark_index) and
PostgreSQL pipeline tables (fund_info, fund_holding) when available.
"""

import logging
import re
import sqlite3

from config.settings import DB_PATH

logger = logging.getLogger(__name__)

_DB_PATH = DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def detect_identifier_type(identifier: str) -> str:
    """Auto-detect fund identifier type.

    Returns: 'tw_etf', 'us_stock', 'offshore_fund', or 'unknown'.
    """
    identifier = identifier.strip()

    # ISIN pattern: 2 letters + 10 alphanumeric
    if re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", identifier):
        return "offshore_fund"

    # Taiwan stock/ETF: 4-6 digits
    if re.match(r"^\d{4,6}$", identifier):
        return "tw_etf"

    # US stock: letters, possibly with hyphen
    if re.match(r"^[A-Z]{1,5}(-[A-Z])?$", identifier.upper()):
        return "us_stock"

    return "unknown"


def get_fund_by_identifier(identifier: str) -> dict | None:
    """Look up a fund by any identifier type.

    Checks SQLite fund_holdings first, then pipeline fund_info.
    """
    id_type = detect_identifier_type(identifier)

    conn = _get_conn()
    try:
        # Check if it's a known fund code in SQLite
        row = conn.execute(
            "SELECT DISTINCT fund_code FROM fund_holdings WHERE fund_code = ?",
            (identifier,),
        ).fetchone()

        if row:
            holdings = conn.execute(
                """
                SELECT industry, weight, return_rate
                FROM fund_holdings
                WHERE fund_code = ?
                ORDER BY weight DESC
                """,
                (identifier,),
            ).fetchall()

            return {
                "fund_id": identifier,
                "fund_name": identifier,
                "fund_type": id_type,
                "market": "tw" if id_type == "tw_etf" else "unknown",
                "source": "sitca",
                "holdings": [
                    {
                        "stock_name": h["industry"],
                        "weight": h["weight"],
                        "sector": h["industry"],
                    }
                    for h in holdings
                ],
                "as_of_date": "",
            }

        # Try ISIN lookup from registry
        if id_type == "offshore_fund":
            from pipeline.fetchers.fund_isin_registry import lookup_name
            name = lookup_name(identifier)
            if name:
                return {
                    "fund_id": identifier,
                    "fund_name": name,
                    "fund_type": "offshore_fund",
                    "market": "offshore",
                    "source": "finnhub",
                    "holdings": [],
                    "as_of_date": "",
                }

        return None
    finally:
        conn.close()


def search_funds(query: str, limit: int = 20) -> list[dict]:
    """Search funds by name or code.

    Searches SQLite fund_holdings + ISIN registry.
    """
    results = []
    query_lower = query.lower()

    conn = _get_conn()
    try:
        # Search in SQLite fund_holdings
        rows = conn.execute(
            "SELECT DISTINCT fund_code FROM fund_holdings WHERE fund_code LIKE ?",
            (f"%{query}%",),
        ).fetchall()

        for row in rows:
            results.append({
                "fund_id": row["fund_code"],
                "fund_name": row["fund_code"],
                "fund_type": detect_identifier_type(row["fund_code"]),
                "market": "tw",
                "source": "sitca",
            })
    finally:
        conn.close()

    # Search ISIN registry
    try:
        from pipeline.fetchers.fund_isin_registry import FUND_ISIN_MAP
        for name, isin in FUND_ISIN_MAP.items():
            if query_lower in name.lower() or query_lower in isin.lower():
                results.append({
                    "fund_id": isin,
                    "fund_name": name,
                    "fund_type": "offshore_fund",
                    "market": "offshore",
                    "source": "finnhub",
                })
    except ImportError:
        pass

    return results[:limit]


def get_benchmark_data(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Get latest benchmark index data from SQLite."""
    if conn is None:
        conn = _get_conn()
        should_close = True
    else:
        should_close = False

    try:
        rows = conn.execute(
            """
            SELECT industry, weight, return_rate
            FROM benchmark_index
            WHERE index_name = 'MI_INDEX'
            ORDER BY industry
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if should_close:
            conn.close()
