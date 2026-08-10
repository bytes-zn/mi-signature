"""Repository for the template module: pure data access."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import Template


class TemplateRepository:
    """Data access for templates (always tenant-scoped)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, template_id: uuid.UUID) -> Template | None:
        result = await self._session.execute(select(Template).where(Template.id == template_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Template | None:
        result = await self._session.execute(
            select(Template).where(Template.tenant_id == tenant_id, Template.name == name)
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> Sequence[Template]:
        result = await self._session.execute(
            select(Template)
            .where(Template.tenant_id == tenant_id)
            .order_by(Template.created_at)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    def add(self, template: Template) -> None:
        self._session.add(template)

    async def delete(self, template: Template) -> None:
        await self._session.delete(template)
