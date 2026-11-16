"""FastAPI security dependencies: tenant API keys and the operator key.

Two caller roles exist:

- **Operator** (platform owner): authenticated via the ``OPERATOR_API_KEY``
  environment variable; may manage all tenants.
- **Tenant**: authenticated via a tenant API key (``X-API-Key`` header);
  may access only its own tenant resource (strict tenant isolation).
"""

import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_session
from app.auth.keys import hash_api_key
from app.config.settings import Settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.models.api_key import ApiKey
from app.models.tenant import Tenant

API_KEY_HEADER = "X-API-Key"

#: ``last_used_at`` is only written when it is older than this interval -
#: otherwise every single API request would cause a database write.
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)

api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


@dataclass(frozen=True)
class Caller:
    """The authenticated caller: either the operator or a tenant."""

    tenant: Tenant | None
    is_operator: bool

    def ensure_tenant_access(self, tenant_id: uuid.UUID) -> None:
        """Allow operator access to any tenant, tenants only to themselves."""
        if self.is_operator:
            return
        if self.tenant is None or self.tenant.id != tenant_id:
            raise ForbiddenError("Access to this tenant is not allowed.", code="tenant_mismatch")

    @property
    def actor_type(self) -> str:
        """Audit actor type of this caller."""
        return "operator" if self.is_operator else "tenant"

    @property
    def actor_id(self) -> str | None:
        """Audit actor id of this caller (``None`` for the operator)."""
        if self.is_operator or self.tenant is None:
            return None
        return str(self.tenant.id)


async def _resolve_tenant(session: AsyncSession, api_key: str) -> Tenant:
    """Resolve the tenant for a tenant API key or raise 401/403."""
    key_hash = hash_api_key(api_key)
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    key = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if key is None or key.status != "active":
        raise UnauthorizedError("Invalid API key.", code="invalid_api_key")
    if key.expires_at is not None and key.expires_at <= now:
        raise UnauthorizedError("API key expired.", code="api_key_expired")

    tenant = key.tenant
    if tenant.status != "active":
        raise ForbiddenError("Tenant is not active.", code="tenant_inactive")

    if key.last_used_at is None or now - key.last_used_at > LAST_USED_WRITE_INTERVAL:
        key.last_used_at = now
        await session.commit()
    return tenant


async def get_caller(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
) -> Caller:
    """Authenticate either as operator or as tenant."""
    if not api_key:
        raise UnauthorizedError("Missing API key.", code="missing_api_key")
    if hmac.compare_digest(api_key, settings.operator_api_key):
        return Caller(tenant=None, is_operator=True)
    return Caller(tenant=await _resolve_tenant(session, api_key), is_operator=False)


async def get_current_tenant(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[str | None, Security(api_key_header)],
) -> Tenant:
    """Require a valid tenant API key (operator key is not accepted)."""
    if not api_key:
        raise UnauthorizedError("Missing API key.", code="missing_api_key")
    return await _resolve_tenant(session, api_key)


def require_operator(
    settings: Annotated[Settings, Depends(get_app_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
) -> None:
    """Require the platform operator key (from the environment)."""
    if not api_key:
        raise UnauthorizedError("Missing API key.", code="missing_api_key")
    if not hmac.compare_digest(api_key, settings.operator_api_key):
        raise ForbiddenError("Operator privileges required.", code="operator_required")
