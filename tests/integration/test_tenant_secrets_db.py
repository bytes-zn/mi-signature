"""Integration tests for the encryption of tenant secrets at rest.

Skipped unless ``RUN_INTEGRATION_TESTS=1`` is set and DATABASE_URL points
to a reachable, migrated database (e.g. the docker-compose stack).
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.crypto import is_encrypted
from app.database.session import build_engine, build_session_factory
from app.tenants.schemas import TenantCreate
from app.tenants.service import TenantService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="integration tests require RUN_INTEGRATION_TESTS=1 and live services",
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = build_engine(get_settings())
    factory = build_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_tenant_secret_is_encrypted_in_the_database(session: AsyncSession) -> None:
    service = TenantService(session)
    secret = "super-secret-client-value"

    tenant, _ = await service.create_tenant(
        TenantCreate(name=f"it-{uuid.uuid4().hex[:12]}", entra_client_secret=secret)
    )

    # The ORM hands out the decrypted value ...
    assert tenant.entra_client_secret == secret

    # ... but the database only contains ciphertext.
    row = (
        await session.execute(
            text("SELECT entra_client_secret FROM tenants WHERE id = :id"),
            {"id": tenant.id},
        )
    ).scalar_one()
    assert row != secret
    assert is_encrypted(str(row))

    # Reading it back decrypts it again.
    fetched = await service.get_tenant(tenant.id)
    assert fetched.entra_client_secret == secret
