"""Pydantic DTOs for the campaigns module."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.rules.conditions import Condition, validate_condition_tree

CampaignStatus = Literal["active", "inactive"]


def _require_tz(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware (include an offset, e.g. Z or +02:00).")
    return value


class _TimeWindow(BaseModel):
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def _window_valid(self) -> "_TimeWindow":
        _require_tz(self.start_at, "start_at")
        _require_tz(self.end_at, "end_at")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at.")
        return self


class CampaignCreate(_TimeWindow):
    """Payload for creating a campaign.

    ``tenant_id`` is only meaningful for operator calls; tenant callers
    are always bound to their own tenant. ``conditions`` may be omitted
    to target all users of the tenant.
    """

    tenant_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    status: CampaignStatus = "active"
    priority: int = 0
    banner_html: str = Field(min_length=1)
    banner_text: str | None = None
    link_url: str | None = Field(default=None, max_length=2048)
    conditions: Condition | None = None

    @field_validator("conditions")
    @classmethod
    def _check_conditions(cls, value: Condition | None) -> Condition | None:
        """Reject unsafe regular expressions when the campaign is saved."""
        if value is None:
            return None
        return validate_condition_tree(value)


class CampaignUpdate(BaseModel):
    """Payload for updating a campaign (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    status: CampaignStatus | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    priority: int | None = None
    banner_html: str | None = Field(default=None, min_length=1)
    banner_text: str | None = None
    link_url: str | None = Field(default=None, max_length=2048)
    conditions: Condition | None = None

    @field_validator("conditions")
    @classmethod
    def _check_conditions(cls, value: Condition | None) -> Condition | None:
        """Reject unsafe regular expressions when the campaign is saved."""
        if value is None:
            return None
        return validate_condition_tree(value)


class CampaignRead(BaseModel):
    """Campaign representation returned by the API.

    ``phase`` is derived: inactive / scheduled / running / expired.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    status: str
    start_at: datetime
    end_at: datetime
    priority: int
    banner_html: str
    banner_text: str | None
    link_url: str | None
    conditions: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    phase: str = "unknown"


class CampaignEvaluationResult(BaseModel):
    """Result of evaluating the campaigns of a tenant for a user."""

    matched: bool
    campaign: CampaignRead | None
