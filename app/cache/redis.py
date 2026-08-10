"""Redis client construction.

The client is created during application startup (lifespan) and stored on
``app.state``. Connections are established lazily on first use.
"""

from redis.asyncio import Redis, from_url

from app.config.settings import Settings


def build_redis(settings: Settings) -> Redis:  # type: ignore[type-arg]
    """Create a Redis client for the configured URL (lazy connection).

    Note: ``Redis`` is generic only in the type stubs, not at runtime,
    so the parameterless form is used for runtime safety.
    """
    return from_url(settings.redis_url, decode_responses=True)
