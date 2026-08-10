"""Integration tests for the campaigns module against a real PostgreSQL."""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.schemas import CampaignCreate, CampaignUpdate
from app.campaigns.service import CampaignService
from app.config.settings import get_settings
from app.core.user_context import UserContext
from app.database.session import build_engine, build_session_factory
from app.tenants.schemas import TenantCreate
from app.tenants.service import TenantService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="integration tests require RUN_INTEGRATION_TESTS=1 and live services",
)

NOW = datetime.now(UTC)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = build_engine(get_settings())
    factory = build_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def tenant_id(session: AsyncSession) -> AsyncIterator[uuid.UUID]:
    tenant_service = TenantService(session)
    tenant, _ = await tenant_service.create_tenant(TenantCreate(name=f"it-{uuid.uuid4().hex[:12]}"))
    yield tenant.id
    await tenant_service.delete_tenant(tenant.id)


async def test_campaign_roundtrip_and_evaluation(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    service = CampaignService(session)

    campaign = await service.create_campaign(
        tenant_id,
        CampaignCreate(
            name="kickoff",
            start_at=NOW - timedelta(days=1),
            end_at=NOW + timedelta(days=30),
            priority=5,
            banner_html='<a href="https://example.com"><img src="cid:banner"/></a>',
            link_url="https://example.com",
            conditions={
                "type": "leaf",
                "field": "country",
                "operator": "in",
                "value": ["DE", "AT"],
            },
        ),
    )
    assert campaign.id is not None

    match = await service.evaluate_for_user(tenant_id, UserContext(country="DE"))
    assert match is not None
    assert match.id == campaign.id

    assert await service.evaluate_for_user(tenant_id, UserContext(country="US")) is None

    updated = await service.update_campaign(tenant_id, campaign.id, CampaignUpdate(priority=99))
    assert updated.priority == 99

    await service.delete_campaign(tenant_id, campaign.id)
    assert await service.list_campaigns(tenant_id) == []


async def test_campaigns_deleted_with_tenant(session: AsyncSession) -> None:
    tenant_service = TenantService(session)
    tenant, _ = await tenant_service.create_tenant(TenantCreate(name=f"it-{uuid.uuid4().hex[:12]}"))
    service = CampaignService(session)

    campaign = await service.create_campaign(
        tenant.id,
        CampaignCreate(
            name="cascade",
            start_at=NOW - timedelta(days=1),
            end_at=NOW + timedelta(days=1),
            banner_html="<b>x</b>",
        ),
    )
    await tenant_service.delete_tenant(tenant.id)

    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await service.get_campaign(campaign.id)
