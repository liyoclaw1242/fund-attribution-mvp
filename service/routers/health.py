"""Health check endpoint — verifies DB connectivity."""

import logging

from fastapi import APIRouter
from sqlalchemy import text

from service.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Return service health status including DB connectivity.

    Returns:
        {"status": "ok"|"degraded", "db": "connected"|"disconnected", "version": "..."}
    """
    from service.main import __version__

    db_status = "disconnected"
    engine = get_engine()

    if engine is not None:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_status = "connected"
        except Exception:
            logger.exception("Health check DB query failed")

    status = "ok" if db_status == "connected" else "degraded"

    return {
        "status": status,
        "db": db_status,
        "version": __version__,
    }
