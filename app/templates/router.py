"""Template API and preview endpoint.

Tenant isolation: tenant callers are always bound to their own tenant;
operators must identify the tenant explicitly (``tenant_id`` in the
payload or query). No business logic lives here - everything delegates
to the TemplateService.
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
from app.templates.schemas import TemplateCreate, TemplateRead, TemplateUpdate
from app.templates.service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])
preview_router = APIRouter(prefix="/preview", tags=["preview"])


def get_template_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TemplateService:
    return TemplateService(session)


ServiceDep = Annotated[TemplateService, Depends(get_template_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]


def _scope_for_write(caller: Caller, tenant_id: uuid.UUID | None) -> uuid.UUID:
    """Determine the tenant scope for create operations."""
    if not caller.is_operator:
        assert caller.tenant is not None
        return caller.tenant.id
    if tenant_id is None:
        raise ValidationError("Operator calls must provide a tenant_id.", code="tenant_required")
    return tenant_id


@router.post("", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TemplateCreate, caller: CallerDep, service: ServiceDep
) -> TemplateRead:
    """Create a template. Bodies are validated against the user contract."""
    tenant_id = _scope_for_write(caller, data.tenant_id)
    template = await service.create_template(tenant_id, data)
    return TemplateRead.model_validate(template)


@router.get("", response_model=list[TemplateRead])
async def list_templates(
    caller: CallerDep,
    service: ServiceDep,
    tenant_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TemplateRead]:
    """List templates of a tenant."""
    scope = _scope_for_write(caller, tenant_id)
    templates = await service.list_templates(scope, offset=offset, limit=limit)
    return [TemplateRead.model_validate(t) for t in templates]


@router.get("/{template_id}", response_model=TemplateRead)
async def get_template(
    template_id: uuid.UUID, caller: CallerDep, service: ServiceDep
) -> TemplateRead:
    template = await service.get_template(template_id)
    caller.ensure_tenant_access(template.tenant_id)
    return TemplateRead.model_validate(template)


@router.put("/{template_id}", response_model=TemplateRead)
async def update_template(
    template_id: uuid.UUID, data: TemplateUpdate, caller: CallerDep, service: ServiceDep
) -> TemplateRead:
    template = await service.get_template(template_id)
    caller.ensure_tenant_access(template.tenant_id)
    updated = await service.update_template(template.tenant_id, template_id, data)
    return TemplateRead.model_validate(updated)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID, caller: CallerDep, service: ServiceDep
) -> Response:
    template = await service.get_template(template_id)
    caller.ensure_tenant_access(template.tenant_id)
    await service.delete_template(template.tenant_id, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PreviewRequest(BaseModel):
    """Render a stored template or inline bodies with sample user data."""

    template_id: uuid.UUID | None = None
    html_body: str | None = None
    text_body: str | None = None
    user: UserContext = Field(default_factory=UserContext)


class PreviewResponse(BaseModel):
    html: str | None
    text: str | None


@preview_router.post("", response_model=PreviewResponse)
async def preview(data: PreviewRequest, caller: CallerDep, service: ServiceDep) -> PreviewResponse:
    """Render a signature preview for the given user attributes.

    Either ``template_id`` (stored template, tenant access enforced) or
    inline ``html_body``/``text_body`` must be provided.
    """
    if data.template_id is not None:
        template = await service.get_template(data.template_id)
        caller.ensure_tenant_access(template.tenant_id)
        html, text = service.render_preview(template, data.user)
        return PreviewResponse(html=html, text=text)

    if data.html_body is None and data.text_body is None:
        raise ValidationError(
            "Provide either template_id or inline html_body/text_body.",
            code="preview_source_required",
        )

    rendered_html, rendered_text = service.render_inline(data.html_body, data.text_body, data.user)
    return PreviewResponse(html=rendered_html, text=rendered_text)
