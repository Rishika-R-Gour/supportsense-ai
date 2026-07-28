from __future__ import annotations

import pytest

from supportsense.config import Settings


def test_production_fails_fast_without_database_or_auth(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORTSENSE_ENV", "production")
    for name in [
        "DATABASE_URL",
        "SUPPORTSENSE_API_KEYS",
        "SUPPORTSENSE_JWT_SECRET",
        "SUPPORTSENSE_JWT_PUBLIC_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Settings.from_env()


def test_production_defaults_to_offline_rollout(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORTSENSE_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example")
    monkeypatch.setenv("REDIS_URL", "rediss://redis.example:6379/0")
    monkeypatch.setenv("SUPPORTSENSE_JWT_PUBLIC_KEY", "test-public-key")
    monkeypatch.delenv("SUPPORTSENSE_ROLLOUT_STAGE", raising=False)

    assert Settings.from_env().rollout_stage == "offline"


def test_production_rejects_non_postgres_database(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORTSENSE_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unsafe.db")
    monkeypatch.setenv("REDIS_URL", "rediss://redis.example:6379/0")
    monkeypatch.setenv("SUPPORTSENSE_JWT_PUBLIC_KEY", "test-public-key")

    with pytest.raises(RuntimeError, match="must use PostgreSQL"):
        Settings.from_env()


def test_production_http_tool_gateway_requires_https(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORTSENSE_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example")
    monkeypatch.setenv("REDIS_URL", "rediss://redis.example:6379/0")
    monkeypatch.setenv("SUPPORTSENSE_JWT_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("SUPPORTSENSE_TOOL_BACKEND", "http")
    monkeypatch.setenv("SUPPORTSENSE_TOOL_API_URL", "http://tools.example")
    monkeypatch.setenv("SUPPORTSENSE_TOOL_API_TOKEN", "not-a-real-token")

    with pytest.raises(RuntimeError, match="must use HTTPS"):
        Settings.from_env()
