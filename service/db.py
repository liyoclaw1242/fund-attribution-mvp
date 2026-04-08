"""Async database engine and session factory for the FastAPI service.

Uses SQLAlchemy async engine with asyncpg. Read-only pool — the service
never writes to pipeline tables.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory = None


def init_engine(postgres_url: str) -> None:
    """Initialize the async engine and session factory.

    Called once during app lifespan startup.
    """
    global _engine, _session_factory
    _engine = create_async_engine(
        postgres_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False,
    )


async def close_engine() -> None:
    """Dispose of the engine and connection pool.

    Called during app lifespan shutdown.
    """
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db():
    """FastAPI dependency — yields an AsyncSession.

    Usage in routes:
        async def my_route(db: AsyncSession = Depends(get_db)):
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_engine() first")

    async with _session_factory() as session:
        yield session


def get_engine():
    """Return the current engine (for health checks, etc.)."""
    return _engine
