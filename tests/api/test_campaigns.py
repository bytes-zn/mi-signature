"""API tests for the campaigns endpoints."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.auth.api_key import Caller, get_caller
from app.campaigns.router import get_campaign_service
from app.campaigns.schemas import CampaignCreate, CampaignUpdate
from app.core.exceptions import NotFoundError
from app.core.user_context import UserContext
from app.models.campaign import Campaign
from app.models.tenant import Tenant

CAMPAIGNS_URL = "/api/v1/campaigns"
OPERATOR_KEY = "dev-operator-key"

TENANT_A_ID = uuid.uuid4()
TENANT_B_ID = uuid.uuid4()

NOW = datetime.now(UTC)
PAST = NOW - timedelta(days=5)
FUTURE = NOW + timedelta(days=5)


def _tenant(tenant_id: uuid.UUID) -> Tenant:
    now = datetime.now(UTC)
    return Tenant(
        id=tenant_id,
        name=f"tenant-{tenant_id.hex[:6]}",
        status="active",
        microsoft_tenant_id=None,
        entra_client_id=None,
        entra_client_secret=None,
        license_plan=None,
        license_seats=None,
        license_valid_until=None,
        branding={},
        settings={},
        created_at=now,
        updated_at=now,
    )


def _make_campaign(tenant_id: uuid.UUID, name: str = "launch", priority: int = 0) -> Campaign:
    now = datetime.now(UTC)
    return Campaign(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        description=None,
        status="active",
        start_at=PAST,
        end_at=FUTURE,
        priority=priority,
        banner_html="<b>Banner</b>",
        banner_text=None,
        link_url=None,
        conditions=None,
        created_at=now,
        updated_at=now,
    )


class FakeCampaignService:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Campaign] = {}

    async def create_campaign(self, tenant_id: uuid.UUID, data: CampaignCreate) -> Campaign:
        campaign = _make_campaign(tenant_id, data.name, data.priority)
        self.store[campaign.id] = campaign
        return campaign

    async def get_campaign(self, campaign_id: uuid.UUID) -> Campaign:
        if campaign_id not in self.store:
            raise NotFoundError("not found")
        return self.store[campaign_id]

    async def list_campaigns(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[Campaign]:
        return [c for c in self.store.values() if c.tenant_id == tenant_id]

    async def update_campaign(
        self, tenant_id: uuid.UUID, campaign_id: uuid.UUID, data: CampaignUpdate
    ) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        if data.priority is not None:
            campaign.priority = data.priority
        return campaign

    async def delete_campaign(self, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> None:
        self.store.pop(campaign_id, None)

    async def evaluate_for_user(
        self, tenant_id: uuid.UUID, user: UserContext, at: datetime | None = None
    ) -> Campaign | None:
        if user.department.lower() == "sales":
            return next((c for c in self.store.values() if c.tenant_id == tenant_id), None)
        return None


@pytest.fixture
def fake_service(app: FastAPI) -> Any:
    service = FakeCampaignService()
    app.dependency_overrides[get_campaign_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


def _as_tenant(app: FastAPI, tenant_id: uuid.UUID) -> None:
    app.dependency_overrides[get_caller] = lambda: Caller(
        tenant=_tenant(tenant_id), is_operator=False
    )


def _body(**kwargs: Any) -> dict[str, Any]:
    return {
        "name": "launch",
        "start_at": PAST.isoformat(),
        "end_at": FUTURE.isoformat(),
        "banner_html": "<b>Banner</b>",
        **kwargs,
    }


async def test_create_campaign_as_tenant(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    _as_tenant(app, TENANT_A_ID)
    response = await client.post(CAMPAIGNS_URL, json=_body(), headers={"X-API-Key": "k"})
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(TENANT_A_ID)
    assert body["phase"] == "running"


async def test_create_campaign_invalid_window(client: AsyncClient, fake_service: Any) -> None:
    response = await client.post(
        CAMPAIGNS_URL,
        json=_body(start_at=FUTURE.isoformat(), end_at=PAST.isoformat()),
        headers={"X-API-Key": OPERATOR_KEY},
    )
    assert response.status_code == 422


async def test_create_campaign_as_operator_requires_tenant_id(
    client: AsyncClient, fake_service: Any
) -> None:
    response = await client.post(CAMPAIGNS_URL, json=_body(), headers={"X-API-Key": OPERATOR_KEY})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tenant_required"


async def test_get_campaign_of_other_tenant_forbidden(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    campaign = _make_campaign(TENANT_B_ID)
    fake_service.store[campaign.id] = campaign
    _as_tenant(app, TENANT_A_ID)

    response = await client.get(f"{CAMPAIGNS_URL}/{campaign.id}", headers={"X-API-Key": "k"})
    assert response.status_code == 403


async def test_update_and_delete_campaign(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    campaign = _make_campaign(TENANT_A_ID)
    fake_service.store[campaign.id] = campaign
    _as_tenant(app, TENANT_A_ID)

    response = await client.put(
        f"{CAMPAIGNS_URL}/{campaign.id}", json={"priority": 7}, headers={"X-API-Key": "k"}
    )
    assert response.status_code == 200
    assert response.json()["priority"] == 7

    response = await client.delete(f"{CAMPAIGNS_URL}/{campaign.id}", headers={"X-API-Key": "k"})
    assert response.status_code == 204


async def test_evaluate_campaign(app: FastAPI, client: AsyncClient, fake_service: Any) -> None:
    campaign = _make_campaign(TENANT_A_ID)
    fake_service.store[campaign.id] = campaign
    _as_tenant(app, TENANT_A_ID)

    response = await client.post(
        f"{CAMPAIGNS_URL}/evaluate",
        json={"user": {"department": "Sales"}},
        headers={"X-API-Key": "k"},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["campaign"]["id"] == str(campaign.id)

    response = await client.post(
        f"{CAMPAIGNS_URL}/evaluate",
        json={"user": {"department": "IT"}},
        headers={"X-API-Key": "k"},
    )
    assert response.json() == {"matched": False, "campaign": None}
