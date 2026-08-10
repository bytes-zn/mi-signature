"""Repository for the rules module: pure data access."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import Rule


class RuleRepository:
    """Data access for rules (always tenant-scoped)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, rule_id: uuid.UUID) -> Rule | None:
        result = await self._session.execute(select(Rule).where(Rule.id == rule_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Rule | None:
        result = await self._session.execute(
            select(Rule).where(Rule.tenant_id == tenant_id, Rule.name == name)
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> Sequence[Rule]:
        result = await self._session.execute(
            select(Rule)
            .where(Rule.tenant_id == tenant_id)
            .order_by(Rule.priority.desc(), Rule.created_at)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def list_active_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[Rule]:
        """Active rules ordered by priority (highest first)."""
        result = await self._session.execute(
            select(Rule)
            .where(Rule.tenant_id == tenant_id, Rule.status == "active")
            .order_by(Rule.priority.desc(), Rule.created_at)
        )
        return result.scalars().all()

    def add(self, rule: Rule) -> None:
        self._session.add(rule)

    async def delete(self, rule: Rule) -> None:
        await self._session.delete(rule)
