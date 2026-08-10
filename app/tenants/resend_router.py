"""Tenant Resend onboarding: provision a sender domain, return DNS records,
trigger verification, and delete. The platform uses Resend to skip the
high-risk M365 outbound IP pool.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_session
from app.auth.api_key import Caller, get_caller
from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.mailer.resend_client import ResendClient
from app.tenants.service import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants-resend"])


def get_tenant_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantService:
    return TenantService(session)


ServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


class ResendOnboardingRequest(BaseModel):
    domain: str


class DnsRecordOut(BaseModel):
    type: str
    host: str
    value: str
    ttl: int | None = None
    priority: int | None = None


class ResendDomainResponse(BaseModel):
    tenant_id: uuid.UUID
    domain: str
    resend_domain_id: str
    status: str
    records: list[DnsRecordOut]


def _api_key(call: Caller, settings: Settings) -> str:
    if call.is_operator:
        return settings.resend_api_key or ""
    raise ValidationError(
        "Resend is operated by the platform operator. "
        "Tenants must use the platform-shared Resend configuration.",
        code="resend_operator_only",
    )


def _build_client(call: Caller, settings: Settings) -> ResendClient:
    key: str = _api_key(call, settings)
    if not key:
        raise ValidationError(
            "RESEND_API_KEY is not configured on the platform.",
            code="resend_key_missing",
        )
    return ResendClient(api_key=key)


def _tenant_id_or_error(call: Caller) -> uuid.UUID:
    if call.is_operator or call.tenant is None:
        raise ValidationError(
            "Tenant context required for Resend management.",
            code="tenant_required",
        )
    return call.tenant.id


def _build_response(
    tenant_id: uuid.UUID, provision: Any, records: list[DnsRecordOut]
) -> ResendDomainResponse:
    return ResendDomainResponse(
        tenant_id=tenant_id,
        domain=str(provision.name),
        resend_domain_id=str(provision.id),
        status=str(provision.status),
        records=records,
    )


def _records_out(items: Any) -> list[DnsRecordOut]:
    return [
        DnsRecordOut(type=r.type, host=r.host, value=r.value, ttl=r.ttl, priority=r.priority)
        for r in items
    ]


@router.post(
    "/resend/domain",
    response_model=ResendDomainResponse,
    status_code=status.HTTP_201_CREATED,
)
async def provision_domain(
    data: ResendOnboardingRequest,
    caller: CallerDep,
    settings: SettingsDep,
    service: ServiceDep,
) -> ResendDomainResponse:
    """Create the sender domain in Resend and return the DNS records.

    The tenant then adds these records at their DNS provider (e.g. Hetzner)
    and triggers the verification endpoint below.
    """
    if not data.domain or "." not in data.domain:
        raise ValidationError("A domain like 'example.com' is required.")

    client = _build_client(caller, settings)
    provision = client.create_domain(data.domain)
    tenant_id = _tenant_id_or_error(caller)
    tenant = await service.set_resend_domain(tenant_id, provision.id)
    if tenant is None:
        raise ValidationError("Tenant not found.", code="not_found")

    return _build_response(tenant_id, provision, _records_out(provision.records))


@router.get("/resend/domain", response_model=ResendDomainResponse)
async def get_domain(
    caller: CallerDep,
    settings: SettingsDep,
    service: ServiceDep,
) -> ResendDomainResponse:
    """Return the current Resend domain status (request records for re-add)."""
    tenant_id = _tenant_id_or_error(caller)
    tenant = await service.get_tenant(tenant_id)
    if tenant.resend_domain_id is None:
        raise ValidationError(
            "No Resend domain configured for this tenant.",
            code="resend_not_provisioned",
        )
    client = _build_client(caller, settings)
    provision = client.get_domain(tenant.resend_domain_id)
    return _build_response(tenant_id, provision, _records_out(provision.records))


@router.post("/resend/verify", response_model=ResendDomainResponse)
async def verify_domain(
    caller: CallerDep,
    settings: SettingsDep,
    service: ServiceDep,
) -> ResendDomainResponse:
    """Trigger Resend to re-check the DNS records (after the tenant has added them)."""
    tenant_id = _tenant_id_or_error(caller)
    tenant = await service.get_tenant(tenant_id)
    if tenant.resend_domain_id is None:
        raise ValidationError(
            "No Resend domain to verify.",
            code="resend_not_provisioned",
        )
    client = _build_client(caller, settings)
    result = client.verify_domain(tenant.resend_domain_id)
    verified = result.status == "verified"
    await service.set_resend_verified(tenant_id, verified)
    return _build_response(tenant_id, result, _records_out(result.dns_records))


@router.delete("/resend/domain", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    caller: CallerDep,
    settings: SettingsDep,
    service: ServiceDep,
) -> None:
    """Remove the Resend domain and clear the tenant's settings."""
    tenant_id = _tenant_id_or_error(caller)
    tenant = await service.get_tenant(tenant_id)
    if tenant.resend_domain_id is None:
        return
    client = _build_client(caller, settings)
    try:
        client.delete_domain(tenant.resend_domain_id)
    finally:
        await service.clear_resend_domain(tenant_id)


class OutboundRequest(BaseModel):
    mode: str  # "graph" | "resend"


@router.put("/resend/outbound")
async def set_outbound_mode(
    data: OutboundRequest,
    caller: CallerDep,
    service: ServiceDep,
) -> dict[str, str]:
    """Switch the tenant's mailflow outbound mode between ``graph`` and ``resend``."""
    if data.mode not in ("graph", "resend"):
        raise ValidationError("mode must be 'graph' or 'resend'.")
    tenant_id = _tenant_id_or_error(caller)
    tenant = await service.get_tenant(tenant_id)
    if data.mode == "resend" and (
        tenant.resend_domain_id is None or not tenant.resend_domain_verified
    ):
        raise ValidationError(
            "Resend requires a verified domain. Provision + verify one first.",
            code="resend_not_verified",
        )
    await service.set_outbound_mode(tenant_id, data.mode)
    return {"tenant_id": str(tenant_id), "mailflow_outbound": data.mode}
