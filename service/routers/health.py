"""Health check endpoint — verifies DB connectivity and data freshness."""

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import text

from service.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Per-table maximum age before data is considered stale.
# Tuned to absorb weekends/holidays for daily price feeds and the monthly
# SITCA cadence for fund holdings.
FRESHNESS_WINDOW_DAYS: dict[str, int] = {
    "stock_price": 3,
    "industry_index": 3,
    "fx_rate": 3,
    "fund_holding": 35,
}

FRESHNESS_DATE_COLUMNS: dict[str, str] = {
    "stock_price": "date",
    "industry_index": "date",
    "fx_rate": "date",
    "fund_holding": "as_of_date",
}


def _is_fresh(table: str, latest: date | None, today: date | None = None) -> bool:
    """Return True when `latest` is within the table's freshness window."""
    if latest is None:
        return False
    if today is None:
        today = datetime.now(timezone.utc).date()
    window = FRESHNESS_WINDOW_DAYS.get(table)
    if window is None:
        return True
    return (today - latest).days <= window


async def _check_db(conn) -> str:
    try:
        await conn.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        logger.exception("Health check DB query failed")
        return "disconnected"


async def _get_last_pipeline_run(conn) -> str | None:
    """Return ISO timestamp of the most recent finished pipeline_run, or None."""
    try:
        result = await conn.execute(
            text("SELECT MAX(finished_at) FROM pipeline_run WHERE finished_at IS NOT NULL")
        )
        row = result.first()
        if row and row[0]:
            return row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])
    except Exception:
        logger.exception("Failed to read last pipeline_run")
    return None


async def _get_latest_date(conn, table: str) -> date | None:
    """Return the most recent date column value from the given table, or None."""
    column = FRESHNESS_DATE_COLUMNS.get(table)
    if column is None:
        return None
    try:
        result = await conn.execute(text(f"SELECT MAX({column}) FROM {table}"))
        row = result.first()
        if row and row[0]:
            value = row[0]
            return value if isinstance(value, date) else date.fromisoformat(str(value))
    except Exception:
        logger.exception("Failed to read latest date for %s", table)
    return None


@router.get("/health")
async def health_check():
    """Return service health status, DB connectivity, and data freshness.

    Returns:
        {
            "status": "healthy" | "degraded",
            "db": "connected" | "disconnected",
            "version": "...",
            "checks": {
                "db": "connected" | "disconnected",
                "pipeline_last_run": "<iso-ts>" | None,
                "data_freshness": {
                    "stock_price":    {"latest": "<iso-date>" | None, "fresh": bool},
                    "fund_holding":   ...,
                    "industry_index": ...,
                    "fx_rate":        ...,
                },
            },
        }

    Always returns HTTP 200; the `status` field signals degradation so
    upstream load balancers / monitors can decide how to react.
    """
    from service.main import __version__

    db_status = "disconnected"
    pipeline_last_run: str | None = None
    freshness: dict[str, dict] = {
        table: {"latest": None, "fresh": False}
        for table in FRESHNESS_DATE_COLUMNS
    }

    engine = get_engine()
    if engine is not None:
        try:
            async with engine.connect() as conn:
                db_status = await _check_db(conn)
                if db_status == "connected":
                    pipeline_last_run = await _get_last_pipeline_run(conn)
                    today = datetime.now(timezone.utc).date()
                    for table in FRESHNESS_DATE_COLUMNS:
                        latest = await _get_latest_date(conn, table)
                        freshness[table] = {
                            "latest": latest.isoformat() if latest else None,
                            "fresh": _is_fresh(table, latest, today),
                        }
        except Exception:
            logger.exception("Health check connection failed")

    all_fresh = db_status == "connected" and all(
        entry["fresh"] for entry in freshness.values()
    )
    status = "healthy" if all_fresh else "degraded"

    return {
        "status": status,
        "db": db_status,
        "version": __version__,
        "checks": {
            "db": db_status,
            "pipeline_last_run": pipeline_last_run,
            "data_freshness": freshness,
        },
    }
