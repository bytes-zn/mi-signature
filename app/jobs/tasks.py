"""Celery tasks.

``ping`` verifies worker connectivity. ``sync_all_tenants`` runs the
Graph sync for every tenant that has Entra credentials configured (own
record or environment fallback); it is scheduled via Celery Beat when
``GRAPH_SYNC_INTERVAL_MINUTES`` > 0.
"""

import asyncio

from app.jobs.celery_app import celery_app


@celery_app.task(name="app.jobs.tasks.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    """Return ``pong``; used as a worker health check."""
    return "pong"


@celery_app.task(name="app.jobs.tasks.sync_all_tenants")  # type: ignore[untyped-decorator]
def sync_all_tenants() -> dict[str, int]:
    """Sync Entra ID users for all tenants with configured credentials."""
    return asyncio.run(_sync_all())


async def _sync_all() -> dict[str, int]:
    from sqlalchemy import select

    from app.cache.redis import build_redis
    from app.config.settings import get_settings
    from app.database.session import build_engine, build_session_factory
    from app.graph.service import GraphSyncService
    from app.models.tenant import Tenant

    settings = get_settings()
    engine = build_engine(settings)
    redis = build_redis(settings)
    try:
        async with build_session_factory(engine)() as session:
            service = GraphSyncService(session, redis, settings)
            result = await session.execute(select(Tenant).where(Tenant.status == "active"))
            tenants = result.scalars().all()

            stats = {"tenants": 0, "synced": 0, "removed": 0, "skipped": 0}
            for tenant in tenants:
                has_credentials = (tenant.microsoft_tenant_id and tenant.entra_client_id) or (
                    settings.entra_tenant_id and settings.entra_client_id
                )
                if not has_credentials:
                    stats["skipped"] += 1
                    continue
                outcome = await service.sync_tenant(tenant)
                stats["tenants"] += 1
                stats["synced"] += outcome.synced
                stats["removed"] += outcome.removed
            return stats
    finally:
        await redis.aclose()  # type: ignore[attr-defined]
        await engine.dispose()
