"""templates table

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
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
            name=op.f("fk_templates_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_templates")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_templates_tenant_name"),
    )
    op.create_index(op.f("ix_templates_tenant_id"), "templates", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_templates_tenant_id"), table_name="templates")
    op.drop_table("templates")
