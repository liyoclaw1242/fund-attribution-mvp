"""Tests for pipeline.config — PipelineConfig from env vars."""

import os
from unittest.mock import patch

from pipeline.config import PipelineConfig


class TestPipelineConfig:
    def test_defaults(self):
        """Config loads sensible defaults when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = PipelineConfig.from_env()
        assert "postgresql://" in cfg.postgres_url
        assert cfg.finnhub_api_key == ""
        assert cfg.finmind_api_token == ""
        assert cfg.twse_rate_limit_delay == 2.0
        assert cfg.scheduler_timezone == "Asia/Taipei"

    def test_from_env(self):
        """Config reads from environment variables."""
        env = {
            "POSTGRES_URL": "postgresql://test:test@db:5432/test_db",
            "FINNHUB_API_KEY": "fh_key_123",
            "FINMIND_API_TOKEN": "fm_token_456",
            "TWSE_RATE_LIMIT_DELAY": "3.5",
            "SCHEDULER_TIMEZONE": "UTC",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = PipelineConfig.from_env()
        assert cfg.postgres_url == env["POSTGRES_URL"]
        assert cfg.finnhub_api_key == "fh_key_123"
        assert cfg.finmind_api_token == "fm_token_456"
        assert cfg.twse_rate_limit_delay == 3.5
        assert cfg.scheduler_timezone == "UTC"

    def test_frozen(self):
        """Config is immutable after creation."""
        cfg = PipelineConfig.from_env()
        try:
            cfg.postgres_url = "changed"
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass
