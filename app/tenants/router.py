"""Tenant API: CRUD for tenants and their API keys.

No business logic here - every endpoint delegates to the TenantService.
Access rules:
- Create/list/delete tenants: operator only.
- Read/update a tenant, manage its API keys: operator or the tenant itself.

Every mutating action is written to the audit trail.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.audit.dependencies import AuditDep
from app.auth.api_key import Caller, get_caller, require_operator
from app.tenants.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    TenantCreate,
    TenantCreated,
    TenantRead,
    TenantUpdate,
)
from app.tenants.service import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


def get_tenant_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantService:
    return TenantService(session)


ServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]


@router.post(
    "",
    response_model=TenantCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operator)],
)
async def create_tenant(
    data: TenantCreate,
    service: ServiceDep,
    caller: CallerDep,
    audit: AuditDep,
) -> TenantCreated:
    """Create a tenant (operator only). Returns the initial API key once."""
    tenant, plaintext_key = await service.create_tenant(data)
    await audit.record(
        "tenant.created",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=tenant.id,
        target_type="tenant",
        target_id=str(tenant.id),
        details={"name": tenant.name},
    )
    return TenantCreated(tenant=TenantRead.model_validate(tenant), api_key=plaintext_key)


@router.get("", response_model=list[TenantRead], dependencies=[Depends(require_operator)])
async def list_tenants(
    service: ServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TenantRead]:
    """List all tenants (operator only)."""
    tenants = await service.list_tenants(offset=offset, limit=limit)
    return [TenantRead.model_validate(tenant) for tenant in tenants]


@router.get("/{tenant_id}", response_model=TenantRead)
async def get_tenant(tenant_id: uuid.UUID, caller: CallerDep, service: ServiceDep) -> TenantRead:
    """Read a tenant (operator or the tenant itself)."""
    caller.ensure_tenant_access(tenant_id)
    tenant = await service.get_tenant(tenant_id)
    return TenantRead.model_validate(tenant)


@router.put("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    caller: CallerDep,
    service: ServiceDep,
    audit: AuditDep,
) -> TenantRead:
    """Update a tenant (operator or the tenant itself)."""
    caller.ensure_tenant_access(tenant_id)
    tenant = await service.update_tenant(tenant_id, data)
    await audit.record(
        "tenant.updated",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=str(tenant_id),
        details={"fields": sorted(data.model_dump(exclude_none=True).keys())},
    )
    return TenantRead.model_validate(tenant)


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_operator)],
)
async def delete_tenant(
    tenant_id: uuid.UUID,
    service: ServiceDep,
    caller: CallerDep,
    audit: AuditDep,
) -> Response:
    """Delete a tenant including its API keys (operator only)."""
    await service.delete_tenant(tenant_id)
    await audit.record(
        "tenant.deleted",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=str(tenant_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{tenant_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    tenant_id: uuid.UUID,
    data: ApiKeyCreate,
    caller: CallerDep,
    service: ServiceDep,
    audit: AuditDep,
) -> ApiKeyCreated:
    """Create an additional API key. The plaintext key is returned once."""
    caller.ensure_tenant_access(tenant_id)
    api_key, plaintext_key = await service.create_api_key(tenant_id, data)
    await audit.record(
        "api_key.created",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=tenant_id,
        target_type="api_key",
        target_id=str(api_key.id),
        details={"name": data.name},
    )
    return ApiKeyCreated(api_key=ApiKeyRead.model_validate(api_key), key=plaintext_key)


@router.get("/{tenant_id}/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(
    tenant_id: uuid.UUID, caller: CallerDep, service: ServiceDep
) -> list[ApiKeyRead]:
    """List API key metadata (keys themselves are never exposed)."""
    caller.ensure_tenant_access(tenant_id)
    keys = await service.list_api_keys(tenant_id)
    return [ApiKeyRead.model_validate(key) for key in keys]


@router.delete("/{tenant_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    caller: CallerDep,
    service: ServiceDep,
    audit: AuditDep,
) -> Response:
    """Revoke an API key."""
    caller.ensure_tenant_access(tenant_id)
    await service.revoke_api_key(tenant_id, key_id)
    await audit.record(
        "api_key.revoked",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=tenant_id,
        target_type="api_key",
        target_id=str(key_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
