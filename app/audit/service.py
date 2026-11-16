"""Audit service: writes the audit trail.

The service is deliberately tiny - it owns no business logic, it only
records what happened, who did it and from where.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models.audit_log import AuditLog

logger = structlog.get_logger(__name__)

#: Maximum length of the free-form details payload.
MAX_DETAILS_LENGTH = 2000


class AuditService:
    """Records auditable actions."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        request_id: str | None = None,
        source_ip: str | None = None,
    ) -> None:
        self._session = session
        self._request_id = request_id
        self._source_ip = source_ip

    async def record(
        self,
        action: str,
        *,
        actor_type: str,
        actor_id: str | None = None,
        tenant_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        """Persist one audit entry (no-op when the audit log is disabled)."""
        if not get_settings().audit_log_enabled:
            return None

        entry = AuditLog(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=_truncate(details),
            request_id=self._request_id,
            source_ip=self._source_ip,
        )
        try:
            self._session.add(entry)
            await self._session.commit()
        except SQLAlchemyError:
            # A failing audit write must not break the business operation,
            # but it has to be visible.
            await self._session.rollback()
            logger.error("audit_write_failed", action=action, exc_info=True)
            return None
        return entry


def _truncate(details: dict[str, Any] | None) -> dict[str, Any]:
    """Bound the size of the details payload."""
    if not details:
        return {}
    rendered = repr(details)
    if len(rendered) <= MAX_DETAILS_LENGTH:
        return details
    return {"truncated": True, "preview": rendered[:MAX_DETAILS_LENGTH]}
