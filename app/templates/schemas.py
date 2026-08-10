"""Pydantic DTOs for the template module."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TemplateStatus = Literal["active", "draft", "archived"]


class TemplateCreate(BaseModel):
    """Payload for creating a template.

    ``tenant_id`` is only meaningful for operator calls; tenant callers
    are always bound to their own tenant.
    """

    tenant_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    html_body: str = Field(min_length=1)
    text_body: str | None = None
    status: TemplateStatus = "draft"


class TemplateUpdate(BaseModel):
    """Payload for updating a template (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    html_body: str | None = Field(default=None, min_length=1)
    text_body: str | None = None
    status: TemplateStatus | None = None


class TemplateRead(BaseModel):
    """Template representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    html_body: str
    text_body: str | None
    status: str
    created_at: datetime
    updated_at: datetime
