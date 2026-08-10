"""Integration tests for real PostgreSQL and Redis connectivity.

These tests are skipped unless ``RUN_INTEGRATION_TESTS=1`` is set and the
service URLs point to reachable instances (e.g. inside docker-compose).
"""

import os

import pytest
from sqlalchemy import text

from app.cache.redis import build_redis
from app.config.settings import get_settings
from app.database.session import build_engine, build_session_factory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="integration tests require RUN_INTEGRATION_TESTS=1 and live services",
)


async def test_database_connection() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    try:
        session_factory = build_session_factory(engine)
        async with session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await engine.dispose()


async def test_redis_connection() -> None:
    settings = get_settings()
    redis = build_redis(settings)
    try:
        assert await redis.ping() is True
    finally:
        await redis.aclose()
