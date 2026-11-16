"""HTTP middleware: request-ID correlation, request logging, Prometheus metrics.

The module also contains the hardening layers that protect the API in a
production deployment: a request body limit, a per-client rate limit and
the helpers used to identify a client.
"""

import hashlib
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

#: Paths that are never rate limited (orchestrator probes, scraping).
RATE_LIMIT_EXEMPT_PATHS = frozenset({"/health", "/metrics", "/healthz", "/readyz"})

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests.",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)
RATE_LIMITED = Counter(
    "http_rate_limited_total",
    "Number of requests rejected by the rate limiter.",
    ["path"],
)
REJECTED_BODY = Counter(
    "http_rejected_body_total",
    "Number of requests rejected because the body was too large.",
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request ID to the log context and log every request.

    The request ID is taken from the ``X-Request-ID`` header when present,
    otherwise a new UUID4 is generated. It is echoed back in the response.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        logger = structlog.get_logger("http.request")
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_finished",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record request count and latency for the ``/metrics`` endpoint."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        path = request.url.path
        REQUEST_LATENCY.labels(method=request.method, path=path).observe(elapsed)
        REQUEST_COUNT.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).inc()
        return response


class BodySizeLimitMiddleware:
    """Reject request bodies that exceed the configured limit.

    Implemented as a pure ASGI middleware: the body is buffered while it is
    counted, and an oversized body is answered with ``413`` before it ever
    reaches an endpoint. Without this limit a single request could exhaust
    the memory of the API process.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            body.extend(message.get("body", b""))
            more_body = bool(message.get("more_body", False))
            if len(body) > self._max_bytes:
                REJECTED_BODY.inc()
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "payload_too_large",
                            "message": (
                                "Request body exceeds the maximum size of "
                                f"{self._max_bytes} bytes."
                            ),
                        }
                    },
                )
                await response(scope, receive, send)
                return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._app(scope, replay_receive, send)


class TokenBucketLimiter:
    """In-memory token bucket rate limiter.

    One bucket per client. The bucket refills continuously; a request
    consumes one token. The limiter is intentionally process-local - it
    protects a single API instance against abuse, it is not a distributed
    quota system.
    """

    def __init__(self, rate_per_minute: int, capacity: int | None = None) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self._rate_per_second = rate_per_minute / 60.0
        self._capacity = float(capacity if capacity is not None else rate_per_minute)
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        """Consume one token for ``key``; False when the limit is reached."""
        timestamp = time.monotonic() if now is None else now
        tokens, last_seen = self._buckets.get(key, (self._capacity, timestamp))

        elapsed = max(0.0, timestamp - last_seen)
        tokens = min(self._capacity, tokens + elapsed * self._rate_per_second)

        if tokens < 1.0:
            self._buckets[key] = (tokens, timestamp)
            return False

        self._buckets[key] = (tokens - 1.0, timestamp)
        self._prune(timestamp)
        return True

    def _prune(self, now: float) -> None:
        """Drop buckets of clients that are no longer active."""
        if len(self._buckets) < 10_000:
            return
        idle_after = self._capacity / self._rate_per_second
        self._buckets = {
            key: bucket for key, bucket in self._buckets.items() if now - bucket[1] < idle_after
        }


def client_identifier(request: Request) -> str:
    """Return a stable, non-secret identifier for the calling client.

    The API key is hashed before it is used as a key so that no secret is
    kept in memory. Requests without an API key are identified by their
    IP address.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return "key:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:32]
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limit the number of requests a client may send per minute."""

    def __init__(self, app: Any, limiter: TokenBucketLimiter) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in RATE_LIMIT_EXEMPT_PATHS:
            return await call_next(request)

        if not self._limiter.allow(client_identifier(request)):
            RATE_LIMITED.labels(path=request.url.path).inc()
            logger = structlog.get_logger("http.ratelimit")
            logger.warning("rate limit exceeded", path=request.url.path)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Please retry later.",
                    }
                },
                headers={"Retry-After": "60"},
            )
        return await call_next(request)
