"""Shared fixtures for the API tests.

The audit trail is replaced by an in-memory fake so that the API tests do
not need a database.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI

from app.audit.dependencies import get_audit_service


class FakeAuditService:
    """Records audit entries in memory."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def record(self, action: str, **kwargs: Any) -> None:
        self.entries.append({"action": action, **kwargs})


@pytest.fixture(autouse=True)
def fake_audit(app: FastAPI) -> Iterator[FakeAuditService]:
    """Replace the audit service with the in-memory fake."""
    service = FakeAuditService()
    app.dependency_overrides[get_audit_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_audit_service, None)
