"""Pydantic DTOs for the graph module."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SyncedUserRead(BaseModel):
    """A synced directory user as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entra_user_id: str
    email: str
    display_name: str
    data: dict[str, Any]
    synced_at: datetime


class SyncResult(BaseModel):
    """Outcome of a sync run."""

    tenant_id: uuid.UUID
    synced: int
    removed: int
    duration_ms: int
