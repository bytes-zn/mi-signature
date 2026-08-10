"""Graph sync service: pulls Entra ID users into the platform.

For each user the service resolves manager display name and group
memberships, maps the payload through the canonical ``UserContext``
contract, upserts the ``users`` table and refreshes the Redis cache.
Credentials come from the tenant record, falling back to the
environment-level dev credentials.
"""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.graph.client import GraphClient
from app.graph.mapper import map_user
from app.graph.repository import SyncedUserRepository
from app.graph.schemas import SyncResult
from app.models.tenant import Tenant
from app.models.user import SyncedUser


class GraphSyncService:
    """Use cases around directory synchronization."""

    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:  # type: ignore[type-arg]
        self._session = session
        self._redis = redis
        self._settings = settings
        self._users = SyncedUserRepository(session)

    async def sync_tenant(self, tenant: Tenant) -> SyncResult:
        """Run a full sync for one tenant. Returns counters."""
        started = time.perf_counter()
        client = self._build_client(tenant)

        graph_users = await client.list_users()

        now = datetime.now(UTC)
        seen: set[str] = set()
        synced = 0
        for graph_user in graph_users:
            entra_id = graph_user["id"]
            seen.add(entra_id)

            manager_name = (graph_user.get("manager") or {}).get("displayName") or ""
            groups = await client.get_user_groups(entra_id)
            context = map_user(graph_user, manager_name, groups)

            existing = await self._users.get_by_entra_id(tenant.id, entra_id)
            if existing is None:
                self._users.add(
                    SyncedUser(
                        tenant_id=tenant.id,
                        entra_user_id=entra_id,
                        email=context.email,
                        display_name=context.display_name,
                        data=context.model_dump(mode="json"),
                        synced_at=now,
                    )
                )
            else:
                existing.email = context.email
                existing.display_name = context.display_name
                existing.data = context.model_dump(mode="json")
                existing.synced_at = now
            synced += 1

        removed = await self._users.delete_stale(tenant.id, seen)
        await self._session.commit()

        await self._write_cache(tenant.id)

        return SyncResult(
            tenant_id=tenant.id,
            synced=synced,
            removed=removed,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    async def list_users(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 500
    ) -> list[SyncedUser]:
        return list(await self._users.list_for_tenant(tenant_id, offset=offset, limit=limit))

    async def _write_cache(self, tenant_id: uuid.UUID) -> None:
        users = await self._users.list_for_tenant(tenant_id, limit=10000)
        payload = json.dumps([u.data for u in users])
        await self._redis.set(
            self._cache_key(tenant_id), payload, ex=self._settings.graph_cache_ttl_seconds
        )

    async def read_cache(self, tenant_id: uuid.UUID) -> list[dict[str, Any]] | None:
        raw = await self._redis.get(self._cache_key(tenant_id))
        return json.loads(raw) if raw else None

    @staticmethod
    def _cache_key(tenant_id: uuid.UUID) -> str:
        return f"graph:users:{tenant_id}"

    def _build_client(self, tenant: Tenant) -> GraphClient:
        tenant_id = tenant.microsoft_tenant_id or self._settings.entra_tenant_id
        client_id = tenant.entra_client_id or self._settings.entra_client_id
        client_secret = tenant.entra_client_secret or self._settings.entra_client_secret
        if not (tenant_id and client_id and client_secret):
            raise ValidationError(
                "Tenant has no Entra credentials and no fallback is configured.",
                code="entra_credentials_missing",
            )
        return GraphClient(tenant_id, client_id, client_secret)
