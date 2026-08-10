"""API tests for the tenant endpoints (routing, auth, serialization).

The service layer is replaced by an in-memory fake via dependency
overrides; no database is required.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.auth.api_key import Caller, get_caller
from app.core.exceptions import NotFoundError
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.tenants.router import get_tenant_service
from app.tenants.schemas import ApiKeyCreate, TenantCreate, TenantUpdate

OPERATOR_KEY = "dev-operator-key"
TENANTS_URL = "/api/v1/tenants"


def _make_tenant(tenant_id: uuid.UUID, name: str = "acme") -> Tenant:
    now = datetime.now(UTC)
    return Tenant(
        id=tenant_id,
        name=name,
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


def _make_api_key(tenant_id: uuid.UUID, name: str = "initial") -> ApiKey:
    return ApiKey(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        key_prefix="bss_test",
        key_hash="x" * 64,
        status="active",
        last_used_at=None,
        expires_at=None,
        created_at=datetime.now(UTC),
    )


class FakeTenantService:
    """In-memory stand-in for TenantService."""

    def __init__(self) -> None:
        self.tenants: dict[uuid.UUID, Tenant] = {}
        self.keys: dict[uuid.UUID, ApiKey] = {}

    async def create_tenant(self, data: TenantCreate) -> tuple[Tenant, str]:
        tenant = _make_tenant(uuid.uuid4(), data.name)
        self.tenants[tenant.id] = tenant
        key = _make_api_key(tenant.id)
        self.keys[key.id] = key
        return tenant, "bss_plaintext-once"

    async def get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        if tenant_id not in self.tenants:
            raise NotFoundError("not found")
        return self.tenants[tenant_id]

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
        key = _make_api_key(tenant_id, data.name)
        self.keys[key.id] = key
        return key, "bss_new-plaintext"

    async def list_api_keys(self, tenant_id: uuid.UUID) -> list[ApiKey]:
        return [k for k in self.keys.values() if k.tenant_id == tenant_id]

    async def revoke_api_key(self, tenant_id: uuid.UUID, key_id: uuid.UUID) -> None:
        if key_id in self.keys:
            self.keys[key_id].status = "revoked"


@pytest.fixture
def fake_service(app: FastAPI) -> FakeTenantService:
    service = FakeTenantService()
    app.dependency_overrides[get_tenant_service] = lambda: service
    yield service  # type: ignore[misc]
    app.dependency_overrides.clear()


def _operator_headers() -> dict[str, str]:
    return {"X-API-Key": OPERATOR_KEY}


async def test_create_tenant_requires_key(client: AsyncClient, fake_service: Any) -> None:
    response = await client.post(TENANTS_URL, json={"name": "acme"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


async def test_create_tenant_rejects_wrong_key(client: AsyncClient, fake_service: Any) -> None:
    response = await client.post(TENANTS_URL, json={"name": "acme"}, headers={"X-API-Key": "nope"})
    assert response.status_code == 403


async def test_create_tenant_as_operator(client: AsyncClient, fake_service: Any) -> None:
    response = await client.post(TENANTS_URL, json={"name": "acme"}, headers=_operator_headers())

    assert response.status_code == 201
    body = response.json()
    assert body["tenant"]["name"] == "acme"
    assert body["api_key"] == "bss_plaintext-once"
    assert "entra_client_secret" not in body["tenant"]


async def test_list_tenants_as_operator(client: AsyncClient, fake_service: Any) -> None:
    await client.post(TENANTS_URL, json={"name": "acme"}, headers=_operator_headers())

    response = await client.get(TENANTS_URL, headers=_operator_headers())
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_get_tenant_as_operator(client: AsyncClient, fake_service: Any) -> None:
    created = (
        await client.post(TENANTS_URL, json={"name": "acme"}, headers=_operator_headers())
    ).json()
    tenant_id = created["tenant"]["id"]

    response = await client.get(f"{TENANTS_URL}/{tenant_id}", headers=_operator_headers())
    assert response.status_code == 200
    assert response.json()["id"] == tenant_id


async def test_get_tenant_not_found(client: AsyncClient, fake_service: Any) -> None:
    response = await client.get(f"{TENANTS_URL}/{uuid.uuid4()}", headers=_operator_headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_tenant_can_read_itself_but_not_others(
    app: FastAPI, client: AsyncClient, fake_service: FakeTenantService
) -> None:
    own = _make_tenant(uuid.uuid4(), "own")
    other_id = uuid.uuid4()
    fake_service.tenants[own.id] = own
    fake_service.tenants[other_id] = _make_tenant(other_id, "other")

    app.dependency_overrides[get_caller] = lambda: Caller(tenant=own, is_operator=False)

    response = await client.get(f"{TENANTS_URL}/{own.id}", headers={"X-API-Key": "tenant-key"})
    assert response.status_code == 200

    response = await client.get(f"{TENANTS_URL}/{other_id}", headers={"X-API-Key": "tenant-key"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_mismatch"


async def test_update_tenant(client: AsyncClient, fake_service: Any) -> None:
    created = (
        await client.post(TENANTS_URL, json={"name": "acme"}, headers=_operator_headers())
    ).json()
    tenant_id = created["tenant"]["id"]

    response = await client.put(
        f"{TENANTS_URL}/{tenant_id}", json={"name": "acme-new"}, headers=_operator_headers()
    )
    assert response.status_code == 200
    assert response.json()["name"] == "acme-new"


async def test_delete_tenant(client: AsyncClient, fake_service: Any) -> None:
    created = (
        await client.post(TENANTS_URL, json={"name": "acme"}, headers=_operator_headers())
    ).json()
    tenant_id = created["tenant"]["id"]

    response = await client.delete(f"{TENANTS_URL}/{tenant_id}", headers=_operator_headers())
    assert response.status_code == 204


async def test_api_key_lifecycle(client: AsyncClient, fake_service: Any) -> None:
    created = (
        await client.post(TENANTS_URL, json={"name": "acme"}, headers=_operator_headers())
    ).json()
    tenant_id = created["tenant"]["id"]

    response = await client.post(
        f"{TENANTS_URL}/{tenant_id}/api-keys",
        json={"name": "ci"},
        headers=_operator_headers(),
    )
    assert response.status_code == 201
    key_id = response.json()["api_key"]["id"]
    assert response.json()["key"] == "bss_new-plaintext"

    response = await client.get(f"{TENANTS_URL}/{tenant_id}/api-keys", headers=_operator_headers())
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert all("key_hash" not in k for k in response.json())

    response = await client.delete(
        f"{TENANTS_URL}/{tenant_id}/api-keys/{key_id}", headers=_operator_headers()
    )
    assert response.status_code == 204
