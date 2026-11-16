"""API tests for the hardening layers (body limit, rate limit, metrics token)."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config.settings import get_settings
from app.main import create_app


async def _client(app: FastAPI) -> AsyncClient:
    """Return an HTTP client bound to the app (no real server)."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_oversized_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "128")
    get_settings.cache_clear()

    application = create_app()
    async with application.router.lifespan_context(application):
        async with await _client(application) as client:
            response = await client.post(
                "/api/v1/mail/process",
                content=b"x" * 4096,
                headers={"X-API-Key": "dev-operator-key"},
            )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_rate_limit_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()

    application = create_app()
    async with application.router.lifespan_context(application):
        async with await _client(application) as client:
            # The schema endpoint needs no database access - only the
            # rate limiter is under test here.
            first = await client.get("/openapi.json")
            second = await client.get("/openapi.json")
            third = await client.get("/openapi.json")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"


async def test_health_endpoint_is_not_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "1")
    get_settings.cache_clear()

    application = create_app()
    async with application.router.lifespan_context(application):
        async with await _client(application) as client:
            for _ in range(3):
                response = await client.get("/health")

    assert response.status_code in (200, 503)


async def test_metrics_require_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "s3cret-metrics-token")
    get_settings.cache_clear()

    application = create_app()
    async with application.router.lifespan_context(application):
        async with await _client(application) as client:
            unauthorized = await client.get("/metrics")
            authorized = await client.get(
                "/metrics", headers={"X-Metrics-Token": "s3cret-metrics-token"}
            )
            bearer = await client.get(
                "/metrics", headers={"Authorization": "Bearer s3cret-metrics-token"}
            )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert bearer.status_code == 200


async def test_metrics_are_open_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    get_settings.cache_clear()

    application = create_app()
    async with application.router.lifespan_context(application):
        async with await _client(application) as client:
            response = await client.get("/metrics")

    assert response.status_code == 200


async def test_openapi_docs_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_DOCS_ENABLED", "false")
    get_settings.cache_clear()

    application = create_app()
    async with application.router.lifespan_context(application):
        async with await _client(application) as client:
            response = await client.get("/docs")

    assert response.status_code == 404


def test_app_uses_the_configured_settings(app: FastAPI) -> None:
    settings: Any = app.state.settings
    assert settings.max_request_body_bytes > 0
