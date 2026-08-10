"""tenant resend fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("resend_domain_id", sa.String(length=64), nullable=True))
    op.add_column(
        "tenants",
        sa.Column(
            "resend_domain_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "mailflow_outbound",
            sa.String(length=20),
            server_default=sa.text("'graph'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "mailflow_outbound")
    op.drop_column("tenants", "resend_domain_verified")
    op.drop_column("tenants", "resend_domain_id")
