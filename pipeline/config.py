"""Pipeline configuration — loaded from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineConfig:
    """Environment-based configuration for the data pipeline."""

    postgres_url: str
    finnhub_api_key: str
    finmind_api_token: str
    twse_rate_limit_delay: float
    scheduler_timezone: str

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        """Create config from environment variables with sensible defaults."""
        return cls(
            postgres_url=os.environ.get(
                "POSTGRES_URL",
                "postgresql://pipeline:pipeline@localhost:5432/fund_data",
            ),
            finnhub_api_key=os.environ.get("FINNHUB_API_KEY", ""),
            finmind_api_token=os.environ.get("FINMIND_API_TOKEN", ""),
            twse_rate_limit_delay=float(
                os.environ.get("TWSE_RATE_LIMIT_DELAY", "2.0")
            ),
            scheduler_timezone=os.environ.get(
                "SCHEDULER_TIMEZONE", "Asia/Taipei"
            ),
        )
