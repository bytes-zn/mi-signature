"""Integration tests for the tenant module against a real PostgreSQL.

Skipped unless ``RUN_INTEGRATION_TESTS=1`` is set and DATABASE_URL points
to a reachable, migrated database (e.g. the docker-compose stack).
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import _resolve_tenant
from app.config.settings import get_settings
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.database.session import build_engine, build_session_factory
from app.tenants.schemas import ApiKeyCreate, TenantCreate, TenantUpdate
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


def _unique_name() -> str:
    return f"it-{uuid.uuid4().hex[:12]}"


async def test_tenant_crud_roundtrip(session: AsyncSession) -> None:
    service = TenantService(session)
    name = _unique_name()

    tenant, plaintext = await service.create_tenant(
        TenantCreate(name=name, license_plan="pro", license_seats=50)
    )
    assert tenant.id is not None
    assert plaintext.startswith("bss_")

    fetched = await service.get_tenant(tenant.id)
    assert fetched.name == name
    assert fetched.license_plan == "pro"

    updated = await service.update_tenant(tenant.id, TenantUpdate(license_seats=99))
    assert updated.license_seats == 99

    key, _ = await service.create_api_key(tenant.id, ApiKeyCreate(name="ci"))
    assert len(await service.list_api_keys(tenant.id)) == 2

    await service.revoke_api_key(tenant.id, key.id)

    await service.delete_tenant(tenant.id)
    with pytest.raises(NotFoundError):
        await service.get_tenant(tenant.id)


async def test_duplicate_name_conflicts(session: AsyncSession) -> None:
    service = TenantService(session)
    name = _unique_name()

    tenant, _ = await service.create_tenant(TenantCreate(name=name))
    with pytest.raises(ConflictError):
        await service.create_tenant(TenantCreate(name=name))

    await service.delete_tenant(tenant.id)


async def test_resolve_tenant_by_api_key(session: AsyncSession) -> None:
    service = TenantService(session)
    tenant, plaintext = await service.create_tenant(TenantCreate(name=_unique_name()))

    resolved = await _resolve_tenant(session, plaintext)
    assert resolved.id == tenant.id

    with pytest.raises(UnauthorizedError):
        await _resolve_tenant(session, "bss_invalid")

    await service.delete_tenant(tenant.id)
