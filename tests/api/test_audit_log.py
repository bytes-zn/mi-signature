"""API test: mutating endpoints write an audit entry."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.exceptions import NotFoundError
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.tenants.router import get_tenant_service
from app.tenants.schemas import ApiKeyCreate, TenantCreate, TenantUpdate

OPERATOR_KEY = "dev-operator-key"
TENANTS_URL = "/api/v1/tenants"


def _make_tenant(tenant_id: uuid.UUID, name: str) -> Tenant:
    now = datetime.now(UTC)
    return Tenant(
        id=tenant_id,
        name=name,
        status="active",
        branding={},
        settings={},
        created_at=now,
        updated_at=now,
    )


class FakeTenantService:
    """In-memory stand-in for the TenantService."""

    def __init__(self) -> None:
        self.tenants: dict[uuid.UUID, Tenant] = {}
        self.keys: dict[uuid.UUID, ApiKey] = {}

    async def create_tenant(self, data: TenantCreate) -> tuple[Tenant, str]:
        tenant = _make_tenant(uuid.uuid4(), data.name)
        self.tenants[tenant.id] = tenant
        return tenant, "bss_plaintext-once"

    async def get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError("not found")
        return tenant

    async def list_tenants(self, *, offset: int = 0, limit: int = 100) -> list[Tenant]:
        return list(self.tenants.values())[offset : offset + limit]

    async def update_tenant(self, tenant_id: uuid.UUID, data: TenantUpdate) -> Tenant:
        tenant = await self.get_tenant(tenant_id)
        if data.name is not None:
            tenant.name = data.name
        return tenant

    async def delete_tenant(self, tenant_id: uuid.UUID) -> None:
        self.tenants.pop(tenant_id, None)

    async def create_api_key(self, tenant_id: uuid.UUID, data: ApiKeyCreate) -> tuple[ApiKey, str]:
        key = ApiKey(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=data.name,
            key_prefix="bss_test",
            key_hash="x" * 64,
            status="active",
            created_at=datetime.now(UTC),
        )
        self.keys[key.id] = key
        return key, "bss_new-plaintext"


@pytest.fixture
def fake_service(app: FastAPI) -> FakeTenantService:
    service = FakeTenantService()
    app.dependency_overrides[get_tenant_service] = lambda: service
    yield service  # type: ignore[misc]
    app.dependency_overrides.pop(get_tenant_service, None)


async def test_create_tenant_is_audited(
    client: AsyncClient, fake_audit: Any, fake_service: FakeTenantService
) -> None:
    response = await client.post(
        TENANTS_URL, json={"name": "acme"}, headers={"X-API-Key": OPERATOR_KEY}
    )
    assert response.status_code == 201

    actions = [entry["action"] for entry in fake_audit.entries]
    assert "tenant.created" in actions

    entry = next(e for e in fake_audit.entries if e["action"] == "tenant.created")
    assert entry["actor_type"] == "operator"
    assert str(entry["tenant_id"]) == response.json()["tenant"]["id"]


async def test_update_tenant_is_audited(
    client: AsyncClient, fake_audit: Any, fake_service: FakeTenantService
) -> None:
    created = (
        await client.post(TENANTS_URL, json={"name": "acme"}, headers={"X-API-Key": OPERATOR_KEY})
    ).json()
    tenant_id = created["tenant"]["id"]

    await client.put(
        f"{TENANTS_URL}/{tenant_id}",
        json={"name": "acme-new"},
        headers={"X-API-Key": OPERATOR_KEY},
    )

    actions = [entry["action"] for entry in fake_audit.entries]
    assert "tenant.updated" in actions


async def test_api_key_creation_is_audited(
    client: AsyncClient, fake_audit: Any, fake_service: FakeTenantService
) -> None:
    created = (
        await client.post(TENANTS_URL, json={"name": "acme"}, headers={"X-API-Key": OPERATOR_KEY})
    ).json()
    tenant_id = created["tenant"]["id"]

    await client.post(
        f"{TENANTS_URL}/{tenant_id}/api-keys",
        json={"name": "ci"},
        headers={"X-API-Key": OPERATOR_KEY},
    )

    actions = [entry["action"] for entry in fake_audit.entries]
    assert "api_key.created" in actions


async def test_read_only_requests_are_not_audited(
    client: AsyncClient, fake_audit: Any, fake_service: FakeTenantService
) -> None:
    await client.get(TENANTS_URL, headers={"X-API-Key": OPERATOR_KEY})

    assert fake_audit.entries == []
