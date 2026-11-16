"""Tests for the API hardening middleware (body limit, rate limit)."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.core.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    TokenBucketLimiter,
    client_identifier,
)


def _build_app(max_bytes: int = 1024, limiter: TokenBucketLimiter | None = None) -> Starlette:
    """Build a tiny app that echoes the request body."""

    async def echo(request: Request) -> Response:
        body = await request.body()
        return Response(content=body, media_type="text/plain")

    app = Starlette(routes=[Route("/echo", echo, methods=["POST"])])
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    if limiter is not None:
        app.add_middleware(RateLimitMiddleware, limiter=limiter)
    return app


async def test_body_below_limit_is_accepted() -> None:
    app = _build_app(max_bytes=1024)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", content=b"hello")

    assert response.status_code == 200
    assert response.content == b"hello"


async def test_body_above_limit_is_rejected() -> None:
    app = _build_app(max_bytes=16)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", content=b"x" * 1024)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_rate_limit_rejects_after_budget_is_exhausted() -> None:
    limiter = TokenBucketLimiter(rate_per_minute=60, capacity=2)
    app = _build_app(max_bytes=1024, limiter=limiter)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/echo", content=b"a")
        second = await client.post("/echo", content=b"a")
        third = await client.post("/echo", content=b"a")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"


def test_token_bucket_refills_over_time() -> None:
    limiter = TokenBucketLimiter(rate_per_minute=60, capacity=1)

    assert limiter.allow("client", now=0.0) is True
    assert limiter.allow("client", now=0.0) is False
    # 60 requests per minute = one token per second.
    assert limiter.allow("client", now=1.5) is True


def test_token_bucket_is_per_client() -> None:
    limiter = TokenBucketLimiter(rate_per_minute=60, capacity=1)

    assert limiter.allow("a", now=0.0) is True
    assert limiter.allow("b", now=0.0) is True
    assert limiter.allow("a", now=0.0) is False


def test_rate_limiter_requires_positive_rate() -> None:
    with pytest.raises(ValueError):
        TokenBucketLimiter(rate_per_minute=0)


async def test_client_identifier_hashes_the_api_key() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-api-key", b"bss_secret_value")],
        "client": ("10.0.0.5", 1234),
    }
    request = Request(scope)

    identifier = client_identifier(request)

    assert identifier.startswith("key:")
    assert "bss_secret_value" not in identifier


async def test_client_identifier_falls_back_to_ip() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("10.0.0.5", 1234),
    }
    request = Request(scope)

    assert client_identifier(request) == "ip:10.0.0.5"
