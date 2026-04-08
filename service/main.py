"""FastAPI service entry point.

Usage:
    uvicorn service.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from service.config import ServiceConfig
from service.db import close_engine, init_engine
from service.routers import attribution, fund, health

logger = logging.getLogger("service")

__version__ = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan — initialize DB pool on startup, close on shutdown."""
    config = ServiceConfig.from_env()
    logger.info("Initializing DB pool: %s", config.postgres_url.split("@")[-1])
    init_engine(config.postgres_url)
    logger.info("Service ready (v%s)", __version__)
    yield
    await close_engine()
    logger.info("Service shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = ServiceConfig.from_env()

    app = FastAPI(
        title="Fund Attribution API",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS — allow Streamlit and configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router, prefix="/api")
    app.include_router(fund.router)
    app.include_router(attribution.router)

    return app


app = create_app()
