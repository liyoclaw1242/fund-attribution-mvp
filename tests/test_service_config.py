"""Tests for service.config — ServiceConfig from env vars."""

import os
from unittest.mock import patch

from service.config import ServiceConfig


class TestServiceConfig:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = ServiceConfig.from_env()
        assert "postgresql" in cfg.postgres_url
        assert "asyncpg" in cfg.postgres_url
        assert cfg.cors_origins == ["http://localhost:8501"]
        assert cfg.anthropic_api_key == ""
        assert cfg.debug is False

    def test_from_env(self):
        env = {
            "POSTGRES_URL": "postgresql+asyncpg://test@db/test_db",
            "CORS_ORIGINS": "http://localhost:3000, http://example.com",
            "ANTHROPIC_API_KEY": "sk-test",
            "DEBUG": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = ServiceConfig.from_env()
        assert cfg.postgres_url == env["POSTGRES_URL"]
        assert cfg.cors_origins == ["http://localhost:3000", "http://example.com"]
        assert cfg.anthropic_api_key == "sk-test"
        assert cfg.debug is True

    def test_frozen(self):
        cfg = ServiceConfig.from_env()
        try:
            cfg.postgres_url = "changed"
            assert False, "Should raise"
        except AttributeError:
            pass
