"""HTTP middleware: request-ID correlation, request logging, Prometheus metrics."""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

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
