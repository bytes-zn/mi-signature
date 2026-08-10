"""Dependency-injection providers for FastAPI endpoints.

Resources (engine, session factory, Redis client) are created once during
the application lifespan and stored on ``app.state``; these providers hand
them to endpoints in a request-scoped, overridable way (tests can swap
them via ``app.dependency_overrides`` or by replacing ``app.state``).
"""

from collections.abc import AsyncIterator

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped database session."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_redis(request: Request) -> Redis:  # type: ignore[type-arg]
    """Return the shared Redis client."""
    return request.app.state.redis  # type: ignore[no-any-return]


def get_app_settings(request: Request) -> Settings:
    """Return the application settings."""
    return request.app.state.settings  # type: ignore[no-any-return]
