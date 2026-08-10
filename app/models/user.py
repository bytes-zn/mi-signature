"""Synced user ORM model.

Users are synchronized from Microsoft Entra ID via the Graph sync. The
canonical attribute payload lives in ``data`` (a serialized
``UserContext``); key fields are denormalized for querying.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class SyncedUser(Base):
    """A user synchronized from a tenant's Entra ID directory."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "entra_user_id", name="uq_users_tenant_entra"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entra_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
