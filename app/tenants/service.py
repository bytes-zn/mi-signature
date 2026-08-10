"""Tenant service: business logic for tenant and API key management.

The service orchestrates repositories and owns transaction boundaries
(commit/rollback). Routers stay free of business logic.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.keys import generate_api_key, hash_api_key, key_prefix
from app.core.exceptions import ConflictError, NotFoundError
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.tenants.repository import ApiKeyRepository, TenantRepository
from app.tenants.schemas import ApiKeyCreate, TenantCreate, TenantUpdate


class TenantService:
    """Use cases around tenants and their API keys."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenants = TenantRepository(session)
        self._keys = ApiKeyRepository(session)

    async def create_tenant(self, data: TenantCreate) -> tuple[Tenant, str]:
        """Create a tenant together with its initial API key.

        Returns the tenant and the plaintext API key (shown exactly once).
        """
        if await self._tenants.get_by_name(data.name) is not None:
            raise ConflictError(f"Tenant with name '{data.name}' already exists.")

        tenant = Tenant(
            name=data.name,
            microsoft_tenant_id=data.microsoft_tenant_id,
            entra_client_id=data.entra_client_id,
            entra_client_secret=data.entra_client_secret,
            license_plan=data.license_plan,
            license_seats=data.license_seats,
            license_valid_until=data.license_valid_until,
            branding=data.branding.model_dump(exclude_none=True) if data.branding else {},
            settings=data.settings,
        )
        self._tenants.add(tenant)
        await self._session.flush()

        _, plaintext_key = self._build_key(tenant.id, ApiKeyCreate(name="initial"))
        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant, plaintext_key

    async def get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = await self._tenants.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant '{tenant_id}' not found.")
        return tenant

    async def list_tenants(self, *, offset: int = 0, limit: int = 100) -> Sequence[Tenant]:
        return await self._tenants.list(offset=offset, limit=limit)

    async def update_tenant(self, tenant_id: uuid.UUID, data: TenantUpdate) -> Tenant:
        tenant = await self.get_tenant(tenant_id)

        if data.name is not None and data.name != tenant.name:
            if await self._tenants.get_by_name(data.name) is not None:
                raise ConflictError(f"Tenant with name '{data.name}' already exists.")
            tenant.name = data.name

        for field in (
            "status",
            "microsoft_tenant_id",
            "entra_client_id",
            "entra_client_secret",
            "license_plan",
            "license_seats",
            "license_valid_until",
        ):
            value = getattr(data, field)
            if value is not None:
                setattr(tenant, field, value)

        if data.branding is not None:
            tenant.branding = {**tenant.branding, **data.branding.model_dump(exclude_none=True)}
        if data.settings is not None:
            tenant.settings = {**tenant.settings, **data.settings}

        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant

    async def delete_tenant(self, tenant_id: uuid.UUID) -> None:
        tenant = await self.get_tenant(tenant_id)
        await self._tenants.delete(tenant)
        await self._session.commit()

    async def create_api_key(self, tenant_id: uuid.UUID, data: ApiKeyCreate) -> tuple[ApiKey, str]:
        """Create an additional API key for a tenant."""
        await self.get_tenant(tenant_id)
        api_key, plaintext_key = self._build_key(tenant_id, data)
        await self._session.flush()
        await self._session.commit()
        await self._session.refresh(api_key)
        return api_key, plaintext_key

    async def list_api_keys(self, tenant_id: uuid.UUID) -> Sequence[ApiKey]:
        await self.get_tenant(tenant_id)
        return await self._keys.list_for_tenant(tenant_id)

    async def revoke_api_key(self, tenant_id: uuid.UUID, key_id: uuid.UUID) -> None:
        await self.get_tenant(tenant_id)
        api_key = await self._keys.get_by_id(key_id)
        if api_key is None or api_key.tenant_id != tenant_id:
            raise NotFoundError(f"API key '{key_id}' not found for this tenant.")
        api_key.status = "revoked"
        await self._session.commit()

    def _build_key(self, tenant_id: uuid.UUID, data: ApiKeyCreate) -> tuple[ApiKey, str]:
        plaintext = generate_api_key()
        api_key = ApiKey(
            tenant_id=tenant_id,
            name=data.name,
            key_prefix=key_prefix(plaintext),
            key_hash=hash_api_key(plaintext),
            expires_at=data.expires_at,
        )
        self._keys.add(api_key)
        return api_key, plaintext

    async def set_outbound_mode(self, tenant_id: uuid.UUID, mode: str) -> Tenant | None:
        tenant = await self._tenants.get_by_id(tenant_id)
        if tenant is None:
            return None
        tenant.mailflow_outbound = mode
        await self._session.commit()
        await self._session.refresh(tenant)
        return tenant

    async def set_resend_domain(self, tenant_id: uuid.UUID, domain_id: str) -> Tenant | None:
        return await self._tenants.set_resend_domain(tenant_id, domain_id)

    async def set_resend_verified(self, tenant_id: uuid.UUID, verified: bool) -> Tenant | None:
        return await self._tenants.set_resend_verified(tenant_id, verified)

    async def clear_resend_domain(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self._tenants.clear_resend_domain(tenant_id)
