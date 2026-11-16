"""encrypt existing tenant secrets at rest

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16

The Entra ID client secret was historically stored in plain text. This
migration converts the existing values to ciphertext using the master key
from ``SECRET_ENCRYPTION_KEY``.

The migration is idempotent: values that already carry the ``enc:v1:``
prefix are left untouched. Running it without a configured master key uses
the insecure development key - the value must therefore be migrated again
after ``SECRET_ENCRYPTION_KEY`` has been set in the target environment.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.crypto import get_cipher, is_encrypted

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    cipher = get_cipher()
    rows = connection.execute(
        sa.text("SELECT id, entra_client_secret FROM tenants WHERE entra_client_secret IS NOT NULL")
    ).fetchall()
    for row in rows:
        value = row.entra_client_secret
        if not isinstance(value, str) or is_encrypted(value):
            continue
        connection.execute(
            sa.text("UPDATE tenants SET entra_client_secret = :value WHERE id = :id"),
            {"value": cipher.encrypt(value), "id": row.id},
        )


def downgrade() -> None:
    connection = op.get_bind()
    cipher = get_cipher()
    rows = connection.execute(
        sa.text("SELECT id, entra_client_secret FROM tenants WHERE entra_client_secret IS NOT NULL")
    ).fetchall()
    for row in rows:
        value = row.entra_client_secret
        if not isinstance(value, str) or not is_encrypted(value):
            continue
        connection.execute(
            sa.text("UPDATE tenants SET entra_client_secret = :value WHERE id = :id"),
            {"value": cipher.decrypt(value), "id": row.id},
        )
