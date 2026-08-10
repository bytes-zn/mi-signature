"""Shared pytest fixtures.

The app lifespan runs with real (but lazily connecting) resources; tests
replace ``app.state.session_factory`` / ``app.state.redis`` with fakes so
no external services are needed for unit/API tests.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config.settings import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a deterministic test configuration for every test."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_FORMAT", "json")
    get_settings.cache_clear()


class FakeSession:
    """Minimal stand-in for an AsyncSession used by the health check."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        if self._fail:
            raise ConnectionError("database unreachable")
        return None


class FakeSessionFactory:
    """Mimics ``async_sessionmaker``: callable returning an async CM."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    def __call__(self) -> "FakeSessionFactory":
        return self

    async def __aenter__(self) -> FakeSession:
        return FakeSession(fail=self._fail)

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class FakeRedis:
    """Minimal stand-in for a Redis client used by the health check."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self._store: dict[str, str] = {}

    async def ping(self) -> bool:
        if self._fail:
            raise ConnectionError("redis unreachable")
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def aclose(self) -> None:
        """Called by the app lifespan on shutdown."""
        return None


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    """Create the application and run its lifespan (resources stay lazy)."""
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the app via ASGI transport (no real server)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
