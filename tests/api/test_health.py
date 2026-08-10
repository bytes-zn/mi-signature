"""Tests for the operational endpoints (/health, /metrics)."""

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import FakeRedis, FakeSessionFactory


async def test_health_ok(app: FastAPI, client: AsyncClient) -> None:
    app.state.session_factory = FakeSessionFactory()
    app.state.redis = FakeRedis()

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }


async def test_health_degraded_when_database_down(app: FastAPI, client: AsyncClient) -> None:
    app.state.session_factory = FakeSessionFactory(fail=True)
    app.state.redis = FakeRedis()

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "error"
    assert body["checks"]["redis"] == "ok"


async def test_health_degraded_when_redis_down(app: FastAPI, client: AsyncClient) -> None:
    app.state.session_factory = FakeSessionFactory()
    app.state.redis = FakeRedis(fail=True)

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "error"


async def test_health_returns_request_id_header(app: FastAPI, client: AsyncClient) -> None:
    app.state.session_factory = FakeSessionFactory()
    app.state.redis = FakeRedis()

    response = await client.get("/health")

    assert "x-request-id" in response.headers


async def test_metrics_endpoint(client: AsyncClient) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
