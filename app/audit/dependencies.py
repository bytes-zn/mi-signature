"""FastAPI dependency that provides the audit service."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.audit.service import AuditService


async def get_audit_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> AuditService:
    """Return an audit service bound to the current request."""
    client = request.client
    return AuditService(
        session,
        request_id=request.headers.get("X-Request-ID"),
        source_ip=client.host if client else None,
    )


AuditDep = Annotated[AuditService, Depends(get_audit_service)]
