"""Unit tests for the TenantService with in-memory fake repositories."""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.keys import hash_api_key
from app.core.exceptions import ConflictError, NotFoundError
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.tenants.schemas import ApiKeyCreate, TenantCreate, TenantUpdate
from app.tenants.service import TenantService


class FakeSession:
    """No-op stand-in for AsyncSession transaction methods."""

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def delete(self, obj: object) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class FakeTenantRepository:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Tenant] = {}

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        return self.store.get(tenant_id)

    async def get_by_name(self, name: str) -> Tenant | None:
        return next((t for t in self.store.values() if t.name == name), None)

    async def list(self, *, offset: int = 0, limit: int = 100) -> list[Tenant]:
        return list(self.store.values())[offset : offset + limit]

    def add(self, tenant: Tenant) -> None:
        if tenant.id is None:
            tenant.id = uuid.uuid4()
        tenant.status = tenant.status or "active"
        now = datetime.now(UTC)
        tenant.created_at = tenant.created_at or now
        tenant.updated_at = tenant.updated_at or now
        self.store[tenant.id] = tenant

    async def delete(self, tenant: Tenant) -> None:
        self.store.pop(tenant.id, None)


class FakeApiKeyRepository:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, ApiKey] = {}

    async def get_by_id(self, key_id: uuid.UUID) -> ApiKey | None:
        return self.store.get(key_id)

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[ApiKey]:
        return [k for k in self.store.values() if k.tenant_id == tenant_id]

    def add(self, api_key: ApiKey) -> None:
        if api_key.id is None:
            api_key.id = uuid.uuid4()
        api_key.created_at = api_key.created_at or datetime.now(UTC)
        self.store[api_key.id] = api_key


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeTenantRepository, FakeApiKeyRepository]:
    tenant_repo = FakeTenantRepository()
    key_repo = FakeApiKeyRepository()
    monkeypatch.setattr("app.tenants.service.TenantRepository", lambda session: tenant_repo)
    monkeypatch.setattr("app.tenants.service.ApiKeyRepository", lambda session: key_repo)
    return tenant_repo, key_repo


@pytest.fixture
def service(repos: tuple[FakeTenantRepository, FakeApiKeyRepository]) -> TenantService:
    return TenantService(session=FakeSession())  # type: ignore[arg-type]


async def test_create_tenant_returns_initial_key(service: TenantService) -> None:
    tenant, plaintext = await service.create_tenant(TenantCreate(name="acme"))

    assert tenant.name == "acme"
    assert tenant.status == "active"
    assert plaintext.startswith("bss_")

    keys = await service.list_api_keys(tenant.id)
    assert len(keys) == 1
    assert keys[0].key_hash == hash_api_key(plaintext)


async def test_create_tenant_duplicate_name_raises(service: TenantService) -> None:
    await service.create_tenant(TenantCreate(name="acme"))
    with pytest.raises(ConflictError):
        await service.create_tenant(TenantCreate(name="acme"))


async def test_get_tenant_not_found(service: TenantService) -> None:
    with pytest.raises(NotFoundError):
        await service.get_tenant(uuid.uuid4())


async def test_list_tenants_pagination(service: TenantService) -> None:
    for i in range(5):
        await service.create_tenant(TenantCreate(name=f"tenant-{i}"))

    assert len(await service.list_tenants()) == 5
    assert len(await service.list_tenants(offset=2, limit=2)) == 2


async def test_update_tenant_merges_fields(service: TenantService) -> None:
    tenant, _ = await service.create_tenant(
        TenantCreate(name="acme", settings={"a": 1}, branding={"company_name": "ACME"})
    )

    updated = await service.update_tenant(
        tenant.id,
        TenantUpdate(license_plan="pro", settings={"b": 2}),
    )

    assert updated.license_plan == "pro"
    assert updated.settings == {"a": 1, "b": 2}
    assert updated.branding == {"company_name": "ACME"}


async def test_update_tenant_rename_conflict(service: TenantService) -> None:
    tenant_a, _ = await service.create_tenant(TenantCreate(name="a"))
    await service.create_tenant(TenantCreate(name="b"))

    with pytest.raises(ConflictError):
        await service.update_tenant(tenant_a.id, TenantUpdate(name="b"))


async def test_delete_tenant(service: TenantService) -> None:
    tenant, _ = await service.create_tenant(TenantCreate(name="acme"))
    await service.delete_tenant(tenant.id)

    with pytest.raises(NotFoundError):
        await service.get_tenant(tenant.id)


async def test_create_and_revoke_api_key(service: TenantService) -> None:
    tenant, _ = await service.create_tenant(TenantCreate(name="acme"))

    api_key, plaintext = await service.create_api_key(tenant.id, ApiKeyCreate(name="ci"))
    assert plaintext.startswith("bss_")
    assert api_key.name == "ci"
    assert len(await service.list_api_keys(tenant.id)) == 2

    await service.revoke_api_key(tenant.id, api_key.id)
    keys = {k.id: k for k in await service.list_api_keys(tenant.id)}
    assert keys[api_key.id].status == "revoked"


async def test_revoke_api_key_of_other_tenant_fails(service: TenantService) -> None:
    tenant_a, _ = await service.create_tenant(TenantCreate(name="a"))
    tenant_b, _ = await service.create_tenant(TenantCreate(name="b"))
    key_b = (await service.list_api_keys(tenant_b.id))[0]

    with pytest.raises(NotFoundError):
        await service.revoke_api_key(tenant_a.id, key_b.id)
