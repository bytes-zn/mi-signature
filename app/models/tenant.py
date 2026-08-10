"""Tenant ORM model.

A tenant is a customer of the platform. All tenant-scoped data in other
modules references this table; tenants must remain strictly isolated.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.api_key import ApiKey


class Tenant(Base):
    """A customer tenant of the platform."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )

    # Microsoft 365 / Entra ID connection
    microsoft_tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entra_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entra_client_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # License information
    license_plan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    license_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license_valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # White-label branding and free-form tenant settings
    branding: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Resend (relay) outbound: domain ID + verification status
    resend_domain_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resend_domain_verified: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    # Mail flow outbound: "graph" (default, M365) or "resend" (relay)
    mailflow_outbound: Mapped[str] = mapped_column(
        String(20), nullable=False, default="graph", server_default="graph"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="raise"
    )
