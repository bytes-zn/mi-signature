"""Unit tests for the CampaignService, especially time-window evaluation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.campaigns.schemas import CampaignCreate, CampaignUpdate
from app.campaigns.service import CampaignService, campaign_phase
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.user_context import UserContext
from app.models.campaign import Campaign

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()

NOW = datetime.now(UTC)
PAST = NOW - timedelta(days=10)
FUTURE = NOW + timedelta(days=10)
FAR_FUTURE = NOW + timedelta(days=20)


class FakeSession:
    async def commit(self) -> None:
        return None

    async def delete(self, obj: object) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class FakeCampaignRepository:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Campaign] = {}

    async def get_by_id(self, campaign_id: uuid.UUID) -> Campaign | None:
        return self.store.get(campaign_id)

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Campaign | None:
        return next(
            (c for c in self.store.values() if c.tenant_id == tenant_id and c.name == name),
            None,
        )

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[Campaign]:
        items = sorted(
            (c for c in self.store.values() if c.tenant_id == tenant_id),
            key=lambda c: -c.priority,
        )
        return items[offset : offset + limit]

    async def list_active_for_tenant(self, tenant_id: uuid.UUID) -> list[Campaign]:
        return sorted(
            (c for c in self.store.values() if c.tenant_id == tenant_id and c.status == "active"),
            key=lambda c: -c.priority,
        )

    def add(self, campaign: Campaign) -> None:
        if campaign.id is None:
            campaign.id = uuid.uuid4()
        campaign.status = campaign.status or "active"
        now = datetime.now(UTC)
        campaign.created_at = campaign.created_at or now
        campaign.updated_at = campaign.updated_at or now
        self.store[campaign.id] = campaign

    async def delete(self, campaign: Campaign) -> None:
        self.store.pop(campaign.id, None)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> CampaignService:
    repo = FakeCampaignRepository()
    monkeypatch.setattr("app.campaigns.service.CampaignRepository", lambda session: repo)
    return CampaignService(session=FakeSession())  # type: ignore[arg-type]


def _payload(
    name: str = "launch",
    start_at: datetime = PAST,
    end_at: datetime = FUTURE,
    **kwargs: object,
) -> CampaignCreate:
    return CampaignCreate(
        name=name,
        start_at=start_at,
        end_at=end_at,
        banner_html='<a href="https://example.com"><img src="cid:banner"/></a>',
        **kwargs,  # type: ignore[arg-type]
    )


def test_phase_lifecycle() -> None:
    campaign = Campaign(status="active", start_at=PAST, end_at=FUTURE)
    assert campaign_phase(campaign, NOW) == "running"
    assert campaign_phase(campaign, PAST - timedelta(seconds=1)) == "scheduled"
    assert campaign_phase(campaign, FUTURE + timedelta(seconds=1)) == "expired"

    campaign.status = "inactive"
    assert campaign_phase(campaign, NOW) == "inactive"


def test_create_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="end_at must be after start_at"):
        CampaignCreate(name="x", start_at=FUTURE, end_at=PAST, banner_html="<b>x</b>")


def test_create_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CampaignCreate(
            name="x",
            start_at=datetime(2026, 1, 1),
            end_at=datetime(2026, 2, 1),
            banner_html="<b>x</b>",
        )


async def test_create_campaign(service: CampaignService) -> None:
    campaign = await service.create_campaign(TENANT_A, _payload())
    assert campaign.name == "launch"
    assert campaign.conditions is None


async def test_create_campaign_duplicate_name(service: CampaignService) -> None:
    await service.create_campaign(TENANT_A, _payload())
    with pytest.raises(ConflictError):
        await service.create_campaign(TENANT_A, _payload())


async def test_get_tenant_campaign_enforces_ownership(service: CampaignService) -> None:
    campaign = await service.create_campaign(TENANT_A, _payload())
    with pytest.raises(NotFoundError):
        await service.get_tenant_campaign(TENANT_B, campaign.id)


async def test_update_campaign(service: CampaignService) -> None:
    campaign = await service.create_campaign(TENANT_A, _payload())
    updated = await service.update_campaign(
        TENANT_A, campaign.id, CampaignUpdate(priority=50, banner_text="Alt-Text")
    )
    assert updated.priority == 50
    assert updated.banner_text == "Alt-Text"


async def test_update_rejects_invalid_window(service: CampaignService) -> None:
    campaign = await service.create_campaign(TENANT_A, _payload())
    with pytest.raises(ValidationError) as exc_info:
        await service.update_campaign(
            TENANT_A, campaign.id, CampaignUpdate(end_at=PAST - timedelta(days=1))
        )
    assert exc_info.value.code == "invalid_time_window"


async def test_delete_campaign(service: CampaignService) -> None:
    campaign = await service.create_campaign(TENANT_A, _payload())
    await service.delete_campaign(TENANT_A, campaign.id)
    with pytest.raises(NotFoundError):
        await service.get_campaign(campaign.id)


async def test_evaluate_matches_running_campaign_without_conditions(
    service: CampaignService,
) -> None:
    campaign = await service.create_campaign(TENANT_A, _payload())
    match = await service.evaluate_for_user(TENANT_A, UserContext())
    assert match is not None
    assert match.id == campaign.id


async def test_evaluate_skips_outside_time_window(service: CampaignService) -> None:
    await service.create_campaign(
        TENANT_A, _payload(name="future", start_at=FUTURE, end_at=FAR_FUTURE)
    )
    assert await service.evaluate_for_user(TENANT_A, UserContext()) is None

    # Dry-run with a future timestamp finds it.
    match = await service.evaluate_for_user(TENANT_A, UserContext(), at=FUTURE + timedelta(days=1))
    assert match is not None
    assert match.name == "future"


async def test_evaluate_respects_conditions(service: CampaignService) -> None:
    await service.create_campaign(
        TENANT_A,
        _payload(
            conditions={
                "type": "leaf",
                "field": "department",
                "operator": "equals",
                "value": "Sales",
            }
        ),
    )
    assert await service.evaluate_for_user(TENANT_A, UserContext(department="Sales")) is not None
    assert await service.evaluate_for_user(TENANT_A, UserContext(department="IT")) is None


async def test_evaluate_highest_priority_wins(service: CampaignService) -> None:
    low = await service.create_campaign(TENANT_A, _payload(name="low", priority=1))
    high = await service.create_campaign(TENANT_A, _payload(name="high", priority=99))
    await service.create_campaign(TENANT_A, _payload(name="off", priority=100, status="inactive"))

    match = await service.evaluate_for_user(TENANT_A, UserContext())
    assert match is not None
    assert match.id == high.id
    assert match.id != low.id
