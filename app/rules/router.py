"""Rules API: CRUD and evaluation.

Tenant isolation mirrors the templates module: tenant callers are bound
to their own tenant, operators must name the tenant explicitly.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.auth.api_key import Caller, get_caller
from app.core.exceptions import ValidationError
from app.core.user_context import UserContext
from app.rules.schemas import RuleCreate, RuleEvaluationResult, RuleRead, RuleUpdate
from app.rules.service import RuleService

router = APIRouter(prefix="/rules", tags=["rules"])


def get_rule_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RuleService:
    return RuleService(session)


ServiceDep = Annotated[RuleService, Depends(get_rule_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]


def _scope(caller: Caller, tenant_id: uuid.UUID | None) -> uuid.UUID:
    if not caller.is_operator:
        assert caller.tenant is not None
        return caller.tenant.id
    if tenant_id is None:
        raise ValidationError("Operator calls must provide a tenant_id.", code="tenant_required")
    return tenant_id


@router.post("", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(data: RuleCreate, caller: CallerDep, service: ServiceDep) -> RuleRead:
    """Create a rule. Conditions are validated against the user contract."""
    tenant_id = _scope(caller, data.tenant_id)
    rule = await service.create_rule(tenant_id, data)
    return RuleRead.model_validate(rule)


@router.get("", response_model=list[RuleRead])
async def list_rules(
    caller: CallerDep,
    service: ServiceDep,
    tenant_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RuleRead]:
    """List rules of a tenant (ordered by priority, highest first)."""
    scope = _scope(caller, tenant_id)
    rules = await service.list_rules(scope, offset=offset, limit=limit)
    return [RuleRead.model_validate(r) for r in rules]


class RuleEvaluateRequest(BaseModel):
    """Evaluate the active rules of a tenant for the given user."""

    tenant_id: uuid.UUID | None = None
    user: UserContext = Field(default_factory=UserContext)


@router.post("/evaluate", response_model=RuleEvaluationResult)
async def evaluate_rules(
    data: RuleEvaluateRequest, caller: CallerDep, service: ServiceDep
) -> RuleEvaluationResult:
    """Return the winning rule for a user (dry-run, nothing persisted)."""
    scope = _scope(caller, data.tenant_id)
    rule = await service.evaluate_for_user(scope, data.user)
    return RuleEvaluationResult(
        matched=rule is not None,
        rule=RuleRead.model_validate(rule) if rule else None,
    )


@router.get("/{rule_id}", response_model=RuleRead)
async def get_rule(rule_id: uuid.UUID, caller: CallerDep, service: ServiceDep) -> RuleRead:
    rule = await service.get_rule(rule_id)
    caller.ensure_tenant_access(rule.tenant_id)
    return RuleRead.model_validate(rule)


@router.put("/{rule_id}", response_model=RuleRead)
async def update_rule(
    rule_id: uuid.UUID, data: RuleUpdate, caller: CallerDep, service: ServiceDep
) -> RuleRead:
    rule = await service.get_rule(rule_id)
    caller.ensure_tenant_access(rule.tenant_id)
    updated = await service.update_rule(rule.tenant_id, rule_id, data)
    return RuleRead.model_validate(updated)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, caller: CallerDep, service: ServiceDep) -> Response:
    rule = await service.get_rule(rule_id)
    caller.ensure_tenant_access(rule.tenant_id)
    await service.delete_rule(rule.tenant_id, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
