"""API tests for the graph endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.auth.api_key import Caller, get_caller
from app.graph.router import get_graph_service, get_tenant_service
from app.graph.schemas import SyncResult
from app.models.tenant import Tenant
from app.models.user import SyncedUser

GRAPH_URL = "/api/v1/graph"
OPERATOR_KEY = "dev-operator-key"

TENANT_A_ID = uuid.uuid4()


def _tenant() -> Tenant:
    now = datetime.now(UTC)
    return Tenant(
        id=TENANT_A_ID,
        name="acme",
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


def _synced_user(email: str) -> SyncedUser:
    return SyncedUser(
        id=uuid.uuid4(),
        tenant_id=TENANT_A_ID,
        entra_user_id="entra-1",
        email=email,
        display_name="Max Mustermann",
        data={"first_name": "Max"},
        synced_at=datetime.now(UTC),
    )


class FakeGraphService:
    async def sync_tenant(self, tenant: Tenant) -> SyncResult:
        return SyncResult(tenant_id=tenant.id, synced=4, removed=0, duration_ms=123)

    async def list_users(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 500
    ) -> list[SyncedUser]:
        return [_synced_user("max@example.com")]


class FakeTenantService:
    async def get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        return _tenant()


@pytest.fixture
def fakes(app: FastAPI) -> None:
    app.dependency_overrides[get_graph_service] = lambda: FakeGraphService()
    app.dependency_overrides[get_tenant_service] = lambda: FakeTenantService()
    app.dependency_overrides[get_caller] = lambda: Caller(tenant=_tenant(), is_operator=False)
    yield
    app.dependency_overrides.clear()


async def test_trigger_sync_as_tenant(app: FastAPI, client: AsyncClient, fakes: Any) -> None:
    response = await client.post(f"{GRAPH_URL}/sync", json={}, headers={"X-API-Key": "k"})
    assert response.status_code == 200
    body = response.json()
    assert body["synced"] == 4
    assert body["tenant_id"] == str(TENANT_A_ID)


async def test_list_users(app: FastAPI, client: AsyncClient, fakes: Any) -> None:
    response = await client.get(f"{GRAPH_URL}/users", headers={"X-API-Key": "k"})
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["email"] == "max@example.com"


async def test_operator_requires_tenant_id(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_graph_service] = lambda: FakeGraphService()
    app.dependency_overrides[get_tenant_service] = lambda: FakeTenantService()
    response = await client.post(f"{GRAPH_URL}/sync", json={}, headers={"X-API-Key": OPERATOR_KEY})
    assert response.status_code == 422
