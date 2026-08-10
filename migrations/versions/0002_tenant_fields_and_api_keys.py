"""tenant fields and api_keys table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("microsoft_tenant_id", sa.String(length=64), nullable=True))
    op.add_column("tenants", sa.Column("entra_client_id", sa.String(length=64), nullable=True))
    op.add_column("tenants", sa.Column("entra_client_secret", sa.String(length=512), nullable=True))
    op.add_column("tenants", sa.Column("license_plan", sa.String(length=100), nullable=True))
    op.add_column("tenants", sa.Column("license_seats", sa.Integer(), nullable=True))
    op.add_column(
        "tenants", sa.Column("license_valid_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tenants",
        sa.Column(
            "branding", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_api_keys_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_index(op.f("ix_api_keys_tenant_id"), "api_keys", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_api_keys_key_prefix"), "api_keys", ["key_prefix"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_tenant_id"), table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_column("tenants", "settings")
    op.drop_column("tenants", "branding")
    op.drop_column("tenants", "license_valid_until")
    op.drop_column("tenants", "license_seats")
    op.drop_column("tenants", "license_plan")
    op.drop_column("tenants", "entra_client_secret")
    op.drop_column("tenants", "entra_client_id")
    op.drop_column("tenants", "microsoft_tenant_id")
