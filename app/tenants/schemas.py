"""Pydantic DTOs for the tenant module (API boundary, never ORM objects)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TenantStatus = Literal["active", "suspended"]


class TenantBranding(BaseModel):
    """White-label branding options for a tenant."""

    company_name: str | None = None
    logo_url: str | None = None
    primary_color: str | None = None
    support_email: str | None = None


class TenantCreate(BaseModel):
    """Payload for creating a tenant."""

    name: str = Field(min_length=1, max_length=255)
    microsoft_tenant_id: str | None = Field(default=None, max_length=64)
    entra_client_id: str | None = Field(default=None, max_length=64)
    entra_client_secret: str | None = Field(default=None, max_length=512)
    license_plan: str | None = Field(default=None, max_length=100)
    license_seats: int | None = Field(default=None, ge=0)
    license_valid_until: datetime | None = None
    branding: TenantBranding | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    """Payload for updating a tenant (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: TenantStatus | None = None
    microsoft_tenant_id: str | None = Field(default=None, max_length=64)
    entra_client_id: str | None = Field(default=None, max_length=64)
    entra_client_secret: str | None = Field(default=None, max_length=512)
    license_plan: str | None = Field(default=None, max_length=100)
    license_seats: int | None = Field(default=None, ge=0)
    license_valid_until: datetime | None = None
    branding: TenantBranding | None = None
    settings: dict[str, Any] | None = None


class TenantRead(BaseModel):
    """Tenant representation returned by the API.

    ``entra_client_secret`` is write-only and never exposed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    microsoft_tenant_id: str | None
    entra_client_id: str | None
    license_plan: str | None
    license_seats: int | None
    license_valid_until: datetime | None
    branding: dict[str, Any]
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TenantCreated(BaseModel):
    """Response for tenant creation: tenant plus the initial API key.

    The plaintext API key is returned exactly once and cannot be recovered.
    """

    tenant: TenantRead
    api_key: str


class ApiKeyCreate(BaseModel):
    """Payload for creating an additional API key."""

    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None


class ApiKeyRead(BaseModel):
    """API key metadata (never contains the key itself)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    status: str
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreated(BaseModel):
    """Response for API key creation including the plaintext key (once)."""

    api_key: ApiKeyRead
    key: str
