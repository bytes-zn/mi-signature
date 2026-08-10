"""Graph API: trigger syncs and list synced users."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_redis, get_session
from app.auth.api_key import Caller, get_caller
from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.graph.schemas import SyncedUserRead, SyncResult
from app.graph.service import GraphSyncService
from app.tenants.service import TenantService

router = APIRouter(prefix="/graph", tags=["graph"])


def get_graph_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],  # type: ignore[type-arg]
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> GraphSyncService:
    return GraphSyncService(session, redis, settings)


def get_tenant_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantService:
    return TenantService(session)


ServiceDep = Annotated[GraphSyncService, Depends(get_graph_service)]
TenantServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]


def _scope(caller: Caller, tenant_id: uuid.UUID | None) -> uuid.UUID:
    if not caller.is_operator:
        assert caller.tenant is not None
        return caller.tenant.id
    if tenant_id is None:
        raise ValidationError("Operator calls must provide a tenant_id.", code="tenant_required")
    return tenant_id


class SyncRequest(BaseModel):
    tenant_id: uuid.UUID | None = None


@router.post("/sync", response_model=SyncResult)
async def trigger_sync(
    data: SyncRequest,
    caller: CallerDep,
    service: ServiceDep,
    tenants: TenantServiceDep,
) -> SyncResult:
    """Synchronize the tenant's Entra ID users into the platform."""
    scope = _scope(caller, data.tenant_id)
    tenant = await tenants.get_tenant(scope)
    return await service.sync_tenant(tenant)


@router.get("/users", response_model=list[SyncedUserRead])
async def list_users(
    caller: CallerDep,
    service: ServiceDep,
    tenant_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> list[SyncedUserRead]:
    """List the tenant's synced users."""
    scope = _scope(caller, tenant_id)
    users = await service.list_users(scope, offset=offset, limit=limit)
    return [SyncedUserRead.model_validate(u) for u in users]
