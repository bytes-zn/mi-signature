"""Async SQLAlchemy engine and session factory construction."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine for the configured database URL."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)
