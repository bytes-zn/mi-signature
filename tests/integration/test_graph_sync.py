"""Integration test: real sync against the development Entra tenant.

Requires RUN_GRAPH_TESTS=1 and ENTRA_TENANT_ID / ENTRA_CLIENT_ID /
ENTRA_CLIENT_SECRET in the environment (see .env). Creates a throwaway
tenant record without own credentials so the environment fallback kicks in.
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database.session import build_engine, build_session_factory
from app.graph.service import GraphSyncService
from app.tenants.schemas import TenantCreate
from app.tenants.service import TenantService
from tests.conftest import FakeRedis

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_GRAPH_TESTS") != "1",
    reason="graph integration tests require RUN_GRAPH_TESTS=1 and Entra credentials",
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = build_engine(get_settings())
    factory = build_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_sync_against_real_tenant(session: AsyncSession) -> None:
    tenant_service = TenantService(session)
    tenant, _ = await tenant_service.create_tenant(
        TenantCreate(name=f"graph-it-{uuid.uuid4().hex[:8]}")
    )
    try:
        service = GraphSyncService(session, FakeRedis(), get_settings())  # type: ignore[arg-type]
        result = await service.sync_tenant(tenant)

        assert result.synced >= 4

        users = await service.list_users(tenant.id)
        by_name = {u.display_name: u for u in users}

        maxm = by_name["Max Mustermann"]
        assert maxm.data["department"] == "Sales"
        assert maxm.data["title"] == "Senior Account Manager"
        assert maxm.data["manager"] == "Nico Zeier"
        assert "Sales-Team" in maxm.data["groups"]
        assert maxm.data["phone"] == "+49 89 1234-56"

        assert "Erika Musterfrau" in by_name
        assert "John Doe" in by_name
    finally:
        await tenant_service.delete_tenant(tenant.id)
