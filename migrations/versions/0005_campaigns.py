"""campaigns table

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("banner_html", sa.Text(), nullable=False),
        sa.Column("banner_text", sa.Text(), nullable=True),
        sa.Column("link_url", sa.String(length=2048), nullable=True),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_campaigns_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_campaigns_tenant_name"),
    )
    op.create_index(op.f("ix_campaigns_tenant_id"), "campaigns", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_campaigns_tenant_id"), table_name="campaigns")
    op.drop_table("campaigns")
