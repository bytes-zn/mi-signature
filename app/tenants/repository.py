"""Repositories for the tenant module: pure data access, no business logic."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.tenant import Tenant


class TenantRepository:
    """Data access for tenants."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Tenant | None:
        result = await self._session.execute(select(Tenant).where(Tenant.name == name))
        return result.scalar_one_or_none()

    async def list(self, *, offset: int = 0, limit: int = 100) -> Sequence[Tenant]:
        result = await self._session.execute(
            select(Tenant).order_by(Tenant.created_at).offset(offset).limit(limit)
        )
        return result.scalars().all()

    async def list_active(self) -> Sequence[Tenant]:
        """All active tenants (for domain-based lookups)."""
        result = await self._session.execute(select(Tenant).where(Tenant.status == "active"))
        return result.scalars().all()

    async def find_active_by_domain(self, domain: str) -> Tenant | None:
        """Resolve an active tenant by one of its accepted sender domains.

        Accepted domains are stored in ``tenant.settings["accepted_domains"]``
        (or the legacy ``mailflow_accepted_domains`` key) as a list of
        lowercase domain names.
        """
        domain = domain.lower()
        for tenant in await self.list_active():
            raw = tenant.settings.get("accepted_domains")
            if raw is None:
                raw = tenant.settings.get("mailflow_accepted_domains")
            if not isinstance(raw, list):
                continue
            domains = [str(d).lower() for d in raw]
            if domain in domains:
                return tenant
        return None

    async def set_resend_domain(self, tenant_id: uuid.UUID, domain_id: str) -> Tenant | None:
        tenant = await self.get_by_id(tenant_id)
        if tenant is None:
            return None
        tenant.resend_domain_id = domain_id
        tenant.resend_domain_verified = False
        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant

    async def set_resend_verified(self, tenant_id: uuid.UUID, verified: bool) -> Tenant | None:
        tenant = await self.get_by_id(tenant_id)
        if tenant is None:
            return None
        tenant.resend_domain_verified = verified
        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant

    async def clear_resend_domain(self, tenant_id: uuid.UUID) -> Tenant | None:
        tenant = await self.get_by_id(tenant_id)
        if tenant is None:
            return None
        tenant.resend_domain_id = None
        tenant.resend_domain_verified = False
        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant

    def add(self, tenant: Tenant) -> None:
        self._session.add(tenant)

    async def delete(self, tenant: Tenant) -> None:
        await self._session.delete(tenant)


class ApiKeyRepository:
    """Data access for API keys."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, key_id: uuid.UUID) -> ApiKey | None:
        result = await self._session.execute(select(ApiKey).where(ApiKey.id == key_id))
        return result.scalar_one_or_none()

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[ApiKey]:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at)
        )
        return result.scalars().all()

    def add(self, api_key: ApiKey) -> None:
        self._session.add(api_key)
