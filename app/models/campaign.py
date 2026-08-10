"""Campaign ORM model.

A campaign injects a time-boxed banner (e.g. event promotion, legal
notice) into signatures. Targeting reuses the rule engine's condition
tree; when several campaigns match, the highest priority wins.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Campaign(Base):
    """A tenant-scoped, time-boxed banner campaign."""

    __tablename__ = "campaigns"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_campaigns_tenant_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    banner_html: Mapped[str] = mapped_column(Text, nullable=False)
    banner_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
