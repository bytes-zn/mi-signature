"""Mail API: MIME transformation and interception polling."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_session
from app.auth.api_key import Caller, get_caller
from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.mailer.processor import process_mime
from app.mailer.service import MailProcessingService, PollReport
from app.tenants.service import TenantService

router = APIRouter(prefix="/mail", tags=["mail"])


def get_mail_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> MailProcessingService:
    return MailProcessingService(session, settings)


def get_tenant_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantService:
    return TenantService(session)


ServiceDep = Annotated[MailProcessingService, Depends(get_mail_service)]
TenantServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]


class ProcessResponse(BaseModel):
    """Result of the MIME transformation (no delivery involved)."""

    from_upn: str
    subject: str
    to: list[str]
    html_body: str | None
    text_body: str | None
    attachments: int


@router.post("/process", response_model=ProcessResponse)
async def process(
    request: Request,
    caller: CallerDep,
    signature_html: str = "<hr><b>Signatur</b>",
    signature_text: str = "-- Signatur",
) -> ProcessResponse:
    """Append a signature to a raw MIME message (dry-run, no delivery).

    Expects the raw RFC822 message in the request body
    (``Content-Type: message/rfc822``). Any authenticated caller may use
    this endpoint; it touches no tenant data.
    """
    raw = await request.body()
    if not raw:
        raise ValidationError("Request body must contain the raw MIME message.")
    processed = process_mime(raw, signature_html, signature_text)
    return ProcessResponse(
        from_upn=processed.from_upn,
        subject=processed.subject,
        to=processed.to,
        html_body=processed.html_body,
        text_body=processed.text_body,
        attachments=len(processed.attachments),
    )


class PollRequest(BaseModel):
    tenant_id: uuid.UUID | None = None


@router.post("/poll", response_model=PollReport)
async def poll(
    data: PollRequest,
    caller: CallerDep,
    service: ServiceDep,
    tenants: TenantServiceDep,
) -> PollReport:
    """Run one interception polling pass for the tenant's mailbox."""
    if not caller.is_operator:
        assert caller.tenant is not None
        tenant = await tenants.get_tenant(caller.tenant.id)
    else:
        if data.tenant_id is None:
            raise ValidationError(
                "Operator calls must provide a tenant_id.", code="tenant_required"
            )
        tenant = await tenants.get_tenant(data.tenant_id)
    return await service.poll_mailbox(tenant)
