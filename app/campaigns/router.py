"""Campaigns API: CRUD and evaluation.

Tenant isolation mirrors the other modules. Targeting conditions reuse
the rule engine's condition schema.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.audit.dependencies import AuditDep
from app.auth.api_key import Caller, get_caller
from app.campaigns.schemas import (
    CampaignCreate,
    CampaignEvaluationResult,
    CampaignRead,
    CampaignUpdate,
)
from app.campaigns.service import CampaignService, campaign_phase
from app.core.exceptions import ValidationError
from app.core.user_context import UserContext
from app.models.campaign import Campaign

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def get_campaign_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CampaignService:
    return CampaignService(session)


ServiceDep = Annotated[CampaignService, Depends(get_campaign_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]


def _scope(caller: Caller, tenant_id: uuid.UUID | None) -> uuid.UUID:
    if not caller.is_operator:
        assert caller.tenant is not None
        return caller.tenant.id
    if tenant_id is None:
        raise ValidationError("Operator calls must provide a tenant_id.", code="tenant_required")
    return tenant_id


def _to_read(campaign: Campaign) -> CampaignRead:
    read = CampaignRead.model_validate(campaign)
    read.phase = campaign_phase(campaign, datetime.now(UTC))
    return read


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    data: CampaignCreate, caller: CallerDep, service: ServiceDep, audit: AuditDep
) -> CampaignRead:
    """Create a time-boxed banner campaign."""
    tenant_id = _scope(caller, data.tenant_id)
    campaign = await service.create_campaign(tenant_id, data)
    await audit.record(
        "campaign.created",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=tenant_id,
        target_type="campaign",
        target_id=str(campaign.id),
        details={"name": campaign.name},
    )
    return _to_read(campaign)


@router.get("", response_model=list[CampaignRead])
async def list_campaigns(
    caller: CallerDep,
    service: ServiceDep,
    tenant_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CampaignRead]:
    """List campaigns of a tenant (ordered by priority, highest first)."""
    scope = _scope(caller, tenant_id)
    campaigns = await service.list_campaigns(scope, offset=offset, limit=limit)
    return [_to_read(c) for c in campaigns]


class CampaignEvaluateRequest(BaseModel):
    """Evaluate the campaigns of a tenant for the given user.

    ``at`` defaults to now; pass a timestamp to test other windows.
    """

    tenant_id: uuid.UUID | None = None
    user: UserContext = Field(default_factory=UserContext)
    at: datetime | None = None

    @field_validator("at")
    @classmethod
    def _at_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("at must be timezone-aware.")
        return value


@router.post("/evaluate", response_model=CampaignEvaluationResult)
async def evaluate_campaigns(
    data: CampaignEvaluateRequest, caller: CallerDep, service: ServiceDep
) -> CampaignEvaluationResult:
    """Return the winning campaign for a user at a point in time (dry-run)."""
    scope = _scope(caller, data.tenant_id)
    campaign = await service.evaluate_for_user(scope, data.user, at=data.at)
    return CampaignEvaluationResult(
        matched=campaign is not None,
        campaign=_to_read(campaign) if campaign else None,
    )


@router.get("/{campaign_id}", response_model=CampaignRead)
async def get_campaign(
    campaign_id: uuid.UUID, caller: CallerDep, service: ServiceDep
) -> CampaignRead:
    campaign = await service.get_campaign(campaign_id)
    caller.ensure_tenant_access(campaign.tenant_id)
    return _to_read(campaign)


@router.put("/{campaign_id}", response_model=CampaignRead)
async def update_campaign(
    campaign_id: uuid.UUID,
    data: CampaignUpdate,
    caller: CallerDep,
    service: ServiceDep,
    audit: AuditDep,
) -> CampaignRead:
    campaign = await service.get_campaign(campaign_id)
    caller.ensure_tenant_access(campaign.tenant_id)
    updated = await service.update_campaign(campaign.tenant_id, campaign_id, data)
    await audit.record(
        "campaign.updated",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=campaign.tenant_id,
        target_type="campaign",
        target_id=str(campaign_id),
        details={"fields": sorted(data.model_dump(exclude_none=True).keys())},
    )
    return _to_read(updated)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID, caller: CallerDep, service: ServiceDep, audit: AuditDep
) -> Response:
    campaign = await service.get_campaign(campaign_id)
    caller.ensure_tenant_access(campaign.tenant_id)
    await service.delete_campaign(campaign.tenant_id, campaign_id)
    await audit.record(
        "campaign.deleted",
        actor_type=caller.actor_type,
        actor_id=caller.actor_id,
        tenant_id=campaign.tenant_id,
        target_type="campaign",
        target_id=str(campaign_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
