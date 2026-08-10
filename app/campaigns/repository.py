"""Repository for the campaigns module: pure data access."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign


class CampaignRepository:
    """Data access for campaigns (always tenant-scoped)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, campaign_id: uuid.UUID) -> Campaign | None:
        result = await self._session.execute(select(Campaign).where(Campaign.id == campaign_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Campaign | None:
        result = await self._session.execute(
            select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.name == name)
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> Sequence[Campaign]:
        result = await self._session.execute(
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id)
            .order_by(Campaign.priority.desc(), Campaign.created_at)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def list_active_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[Campaign]:
        """Active campaigns ordered by priority (highest first)."""
        result = await self._session.execute(
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id, Campaign.status == "active")
            .order_by(Campaign.priority.desc(), Campaign.created_at)
        )
        return result.scalars().all()

    def add(self, campaign: Campaign) -> None:
        self._session.add(campaign)

    async def delete(self, campaign: Campaign) -> None:
        await self._session.delete(campaign)
