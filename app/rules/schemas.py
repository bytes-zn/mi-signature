"""Pydantic DTOs for the rules module."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.rules.conditions import Condition

RuleStatus = Literal["active", "inactive"]


class RuleCreate(BaseModel):
    """Payload for creating a rule.

    ``tenant_id`` is only meaningful for operator calls; tenant callers
    are always bound to their own tenant.
    """

    tenant_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    template_id: uuid.UUID
    status: RuleStatus = "active"
    priority: int = 0
    conditions: Condition


class RuleUpdate(BaseModel):
    """Payload for updating a rule (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    template_id: uuid.UUID | None = None
    status: RuleStatus | None = None
    priority: int | None = None
    conditions: Condition | None = None


class RuleRead(BaseModel):
    """Rule representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    template_id: uuid.UUID
    name: str
    description: str | None
    status: str
    priority: int
    conditions: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RuleEvaluationResult(BaseModel):
    """Result of evaluating all active rules of a tenant for a user."""

    matched: bool
    rule: RuleRead | None
