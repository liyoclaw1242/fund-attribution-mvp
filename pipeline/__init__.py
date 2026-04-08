"""Data Pipeline — async fetchers, PostgreSQL storage, and scheduling."""

from pipeline.config import PipelineConfig
from pipeline.db import close_pool, create_pool, execute_schema, log_pipeline_run
from pipeline.fetchers.base import BaseFetcher

__all__ = [
    "PipelineConfig",
    "create_pool",
    "close_pool",
    "execute_schema",
    "log_pipeline_run",
    "BaseFetcher",
]
