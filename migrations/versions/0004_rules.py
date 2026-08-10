"""rules table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_rules_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name=op.f("fk_rules_template_id_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_rules_tenant_name"),
    )
    op.create_index(op.f("ix_rules_tenant_id"), "rules", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_rules_template_id"), "rules", ["template_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rules_template_id"), table_name="rules")
    op.drop_index(op.f("ix_rules_tenant_id"), table_name="rules")
    op.drop_table("rules")
