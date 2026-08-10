"""Repository for synced users: pure data access."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import SyncedUser


class SyncedUserRepository:
    """Data access for synced users (always tenant-scoped)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_entra_id(self, tenant_id: uuid.UUID, entra_user_id: str) -> SyncedUser | None:
        result = await self._session.execute(
            select(SyncedUser).where(
                SyncedUser.tenant_id == tenant_id,
                SyncedUser.entra_user_id == entra_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, tenant_id: uuid.UUID, email: str) -> SyncedUser | None:
        result = await self._session.execute(
            select(SyncedUser).where(
                SyncedUser.tenant_id == tenant_id,
                SyncedUser.email == email.lower(),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 500
    ) -> Sequence[SyncedUser]:
        result = await self._session.execute(
            select(SyncedUser)
            .where(SyncedUser.tenant_id == tenant_id)
            .order_by(SyncedUser.display_name)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def delete_stale(self, tenant_id: uuid.UUID, current_entra_ids: set[str]) -> int:
        """Remove users no longer present in the directory. Returns count."""
        stmt = delete(SyncedUser).where(SyncedUser.tenant_id == tenant_id)
        if current_entra_ids:
            stmt = stmt.where(SyncedUser.entra_user_id.not_in(current_entra_ids))
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0))

    def add(self, user: SyncedUser) -> None:
        self._session.add(user)
