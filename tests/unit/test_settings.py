"""Tests for application settings loading."""

import pytest

from app.config.settings import Settings, get_settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "Bytes Signature Service"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.log_format == "json"


def test_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.log_level == "DEBUG"
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/x"


def test_celery_urls_default_to_redis() -> None:
    settings = Settings(redis_url="redis://example:6379/0")
    assert settings.resolved_celery_broker_url == "redis://example:6379/0"
    assert settings.resolved_celery_result_backend == "redis://example:6379/0"


def test_celery_urls_explicit() -> None:
    settings = Settings(
        redis_url="redis://example:6379/0",
        celery_broker_url="redis://example:6379/1",
        celery_result_backend="redis://example:6379/2",
    )
    assert settings.resolved_celery_broker_url == "redis://example:6379/1"
    assert settings.resolved_celery_result_backend == "redis://example:6379/2"
