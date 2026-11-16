"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.ops import router as ops_router
from app.api.v1.router import router as v1_router
from app.cache.redis import build_redis
from app.config.settings import get_settings
from app.core.exceptions import AppError
from app.core.middleware import (
    BodySizeLimitMiddleware,
    PrometheusMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    TokenBucketLimiter,
)
from app.database.session import build_engine, build_session_factory
from app.logging.setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create shared resources on startup and release them on shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    engine = build_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.redis = build_redis(settings)

    yield

    await app.state.redis.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="White-label backend platform for server-side email signatures.",
        lifespan=lifespan,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )

    # The middleware stack is built from the inside out: the middleware
    # added last is executed first. The body limit therefore runs before
    # anything else can read the request body.
    app.add_middleware(PrometheusMiddleware)
    if settings.trusted_host_list:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
    if settings.https_redirect:
        app.add_middleware(HTTPSRedirectMiddleware)
    if settings.api_rate_limit_per_minute > 0:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=TokenBucketLimiter(settings.api_rate_limit_per_minute),
        )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)

    app.include_router(ops_router)
    app.include_router(v1_router, prefix=settings.api_v1_prefix)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app
