"""Fund lookup and search service (Postgres-backed).

Reads from the pipeline-populated Postgres tables (`fund_info`,
`fund_holding`, `industry_weight`, `industry_index`) via the async
SQLAlchemy engine owned by `service.db`. The legacy SQLite `cache.db`
path has been removed — the service runs in a container that does not
ship `cache.db`.
"""

import logging
import re

from sqlalchemy import text

from service.db import get_engine

logger = logging.getLogger(__name__)


_ID_TYPE_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
_ID_TYPE_TW = re.compile(r"^\d{4,6}$")
_ID_TYPE_US = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")


def detect_identifier_type(identifier: str) -> str:
    """Return 'tw_etf' | 'us_stock' | 'offshore_fund' | 'unknown'."""
    identifier = identifier.strip()
    if _ID_TYPE_ISIN.match(identifier):
        return "offshore_fund"
    if _ID_TYPE_TW.match(identifier):
        return "tw_etf"
    if _ID_TYPE_US.match(identifier.upper()):
        return "us_stock"
    return "unknown"


def _market_for(id_type: str) -> str:
    if id_type == "tw_etf":
        return "tw"
    if id_type == "us_stock":
        return "us"
    if id_type == "offshore_fund":
        return "offshore"
    return "unknown"


async def get_fund_by_identifier(identifier: str) -> dict | None:
    """Look up a fund by any identifier type.

    Reads `fund_info` for metadata and `fund_holding` for the latest
    snapshot, grouped by `sector` so the response matches the
    industry-level shape the Brinson engine expects.

    Returns None when no fund with that id exists.
    """
    engine = get_engine()
    if engine is None:
        logger.error("get_fund_by_identifier called before init_engine()")
        return None

    id_type = detect_identifier_type(identifier)

    async with engine.connect() as conn:
        info_row = (
            await conn.execute(
                text(
                    """
                    SELECT fund_id, fund_name, fund_type, currency, market, source
                    FROM fund_info
                    WHERE fund_id = :fid
                    """
                ),
                {"fid": identifier},
            )
        ).first()

        if info_row is None:
            # Fall back to ISIN registry (offshore funds indexed by pipeline
            # fetchers — the registry is a pure-Python dict, no DB required).
            if id_type == "offshore_fund":
                try:
                    from pipeline.fetchers.fund_isin_registry import lookup_name
                    name = lookup_name(identifier)
                except ImportError:
                    name = None
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

        holdings_rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        COALESCE(NULLIF(sector, ''), stock_name) AS industry,
                        SUM(weight) AS weight,
                        MAX(as_of_date) AS as_of_date
                    FROM fund_holding
                    WHERE fund_id = :fid
                      AND as_of_date = (
                          SELECT MAX(as_of_date)
                          FROM fund_holding
                          WHERE fund_id = :fid
                      )
                    GROUP BY COALESCE(NULLIF(sector, ''), stock_name)
                    ORDER BY SUM(weight) DESC
                    """
                ),
                {"fid": identifier},
            )
        ).all()

    holdings = [
        {
            "stock_name": row[0],
            "weight": float(row[1] or 0),
            "sector": row[0],
        }
        for row in holdings_rows
    ]

    as_of_date = ""
    if holdings_rows and holdings_rows[0][2] is not None:
        as_of_date = holdings_rows[0][2].isoformat() if hasattr(holdings_rows[0][2], "isoformat") else str(holdings_rows[0][2])

    return {
        "fund_id": info_row[0],
        "fund_name": info_row[1],
        "fund_type": info_row[2] or id_type,
        "market": info_row[4] or _market_for(id_type),
        "source": info_row[5] or "",
        "holdings": holdings,
        "as_of_date": as_of_date,
    }


async def search_funds(query: str, limit: int = 20) -> list[dict]:
    """Search funds by fund_id, fund_name, or the offshore ISIN registry."""
    engine = get_engine()
    results: list[dict] = []
    seen_ids: set[str] = set()

    if engine is not None:
        like = f"%{query}%"
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT fund_id, fund_name, fund_type, currency, market, source
                        FROM fund_info
                        WHERE fund_id ILIKE :q OR fund_name ILIKE :q
                        ORDER BY fund_id
                        LIMIT :lim
                        """
                    ),
                    {"q": like, "lim": limit},
                )
            ).all()

        for row in rows:
            if row[0] in seen_ids:
                continue
            seen_ids.add(row[0])
            results.append(
                {
                    "fund_id": row[0],
                    "fund_name": row[1] or row[0],
                    "fund_type": row[2] or detect_identifier_type(row[0]),
                    "market": row[4] or "",
                    "source": row[5] or "",
                }
            )

    # Also scan the ISIN registry — covers offshore funds not yet in fund_info.
    try:
        from pipeline.fetchers.fund_isin_registry import FUND_ISIN_MAP
        query_lower = query.lower()
        for name, isin in FUND_ISIN_MAP.items():
            if isin in seen_ids:
                continue
            if query_lower in name.lower() or query_lower in isin.lower():
                seen_ids.add(isin)
                results.append(
                    {
                        "fund_id": isin,
                        "fund_name": name,
                        "fund_type": "offshore_fund",
                        "market": "offshore",
                        "source": "finnhub",
                    }
                )
                if len(results) >= limit:
                    break
    except ImportError:
        pass

    return results[:limit]


async def get_benchmark_data() -> list[dict]:
    """Return the latest industry-level benchmark snapshot.

    Joins the most recent `industry_weight` rows (TWSE universe) with the
    most recent `industry_index.change_pct` per industry to yield the
    {industry, weight, return_rate} shape the Brinson engine expects.
    """
    engine = get_engine()
    if engine is None:
        return []

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    WITH latest_weight AS (
                        SELECT industry, weight
                        FROM industry_weight
                        WHERE market = 'twse'
                          AND date = (
                              SELECT MAX(date) FROM industry_weight WHERE market = 'twse'
                          )
                    ),
                    latest_return AS (
                        SELECT DISTINCT ON (industry) industry, change_pct
                        FROM industry_index
                        ORDER BY industry, date DESC
                    )
                    SELECT lw.industry, lw.weight, COALESCE(lr.change_pct, 0) AS return_rate
                    FROM latest_weight lw
                    LEFT JOIN latest_return lr USING (industry)
                    ORDER BY lw.industry
                    """
                )
            )
        ).all()

    return [
        {
            "industry": row[0],
            "weight": float(row[1] or 0),
            "return_rate": float(row[2] or 0),
        }
        for row in rows
    ]
