"""Service configuration — loaded from environment variables."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceConfig:
    """Environment-based configuration for the FastAPI service."""

    postgres_url: str
    cors_origins: list[str]
    anthropic_api_key: str
    debug: bool

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        """Create config from environment variables with sensible defaults."""
        cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:8501")
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]

        return cls(
            postgres_url=os.environ.get(
                "POSTGRES_URL",
                "postgresql+asyncpg://pipeline:pipeline@localhost:5432/fund_data",
            ),
            cors_origins=cors_origins,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            debug=os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
        )
