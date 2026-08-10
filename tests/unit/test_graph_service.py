"""Unit tests for the GraphSyncService with fake client, repo and cache."""

import uuid
from typing import Any

import pytest

from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.graph.service import GraphSyncService
from app.models.tenant import Tenant
from app.models.user import SyncedUser


class FakeGraphClient:
    """Returns canned Graph payloads."""

    def __init__(self, users: list[dict[str, Any]], groups: dict[str, list[str]] | None = None):
        self._users = users
        self._groups = groups or {}

    async def list_users(self) -> list[dict[str, Any]]:
        return self._users

    async def get_user_groups(self, user_id: str) -> list[str]:
        return self._groups.get(user_id, [])


class FakeSession:
    async def commit(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)


class FakeSyncedUserRepository:
    def __init__(self) -> None:
        self.store: dict[str, SyncedUser] = {}

    async def get_by_entra_id(self, tenant_id: uuid.UUID, entra_user_id: str) -> SyncedUser | None:
        return self.store.get(entra_user_id)

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 500
    ) -> list[SyncedUser]:
        return list(self.store.values())[offset : offset + limit]

    async def delete_stale(self, tenant_id: uuid.UUID, current_entra_ids: set[str]) -> int:
        stale = [k for k in self.store if k not in current_entra_ids]
        for key in stale:
            del self.store[key]
        return len(stale)

    def add(self, user: SyncedUser) -> None:
        self.store[user.entra_user_id] = user


TENANT_ID = uuid.uuid4()


def _tenant(with_creds: bool = True) -> Tenant:
    return Tenant(
        id=TENANT_ID,
        name="acme",
        status="active",
        microsoft_tenant_id="t-1" if with_creds else None,
        entra_client_id="c-1" if with_creds else None,
        entra_client_secret="s-1" if with_creds else None,
        branding={},
        settings={},
    )


def _graph_user(entra_id: str, name: str, department: str) -> dict[str, Any]:
    return {
        "id": entra_id,
        "givenName": name.split()[0],
        "surname": name.split()[-1],
        "displayName": name,
        "department": department,
        "mail": f"{name.replace(' ', '.')}@example.com".lower(),
        "manager": {"displayName": "Nico Zeier"},
    }


@pytest.fixture
def service(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[GraphSyncService, FakeRedis, FakeSyncedUserRepository]:
    repo = FakeSyncedUserRepository()
    redis = FakeRedis()
    monkeypatch.setattr("app.graph.service.SyncedUserRepository", lambda session: repo)
    svc = GraphSyncService(FakeSession(), redis, Settings(_env_file=None))  # type: ignore[arg-type]
    return svc, redis, repo


async def test_sync_creates_users_and_writes_cache(
    service: tuple[GraphSyncService, FakeRedis, FakeSyncedUserRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, redis, repo = service
    fake = FakeGraphClient(
        [_graph_user("u1", "Max Mustermann", "Sales")],
        groups={"u1": ["Sales-Team"]},
    )
    monkeypatch.setattr(GraphSyncService, "_build_client", lambda self, tenant: fake)

    result = await svc.sync_tenant(_tenant())

    assert result.synced == 1
    assert result.removed == 0
    stored = repo.store["u1"]
    assert stored.display_name == "Max Mustermann"
    assert stored.data["department"] == "Sales"
    assert stored.data["groups"] == ["Sales-Team"]
    assert stored.data["manager"] == "Nico Zeier"

    cached = await svc.read_cache(TENANT_ID)
    assert cached is not None
    assert cached[0]["display_name"] == "Max Mustermann"


async def test_sync_updates_and_removes(
    service: tuple[GraphSyncService, FakeRedis, FakeSyncedUserRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, _, repo = service
    repo.store["old"] = SyncedUser(
        tenant_id=TENANT_ID, entra_user_id="old", email="o@x.de", display_name="Old", data={}
    )
    repo.store["u1"] = SyncedUser(
        tenant_id=TENANT_ID,
        entra_user_id="u1",
        email="m@x.de",
        display_name="Max",
        data={"department": "Alt"},
    )
    fake = FakeGraphClient([_graph_user("u1", "Max Mustermann", "Sales")])
    monkeypatch.setattr(GraphSyncService, "_build_client", lambda self, tenant: fake)

    result = await svc.sync_tenant(_tenant())

    assert result.synced == 1
    assert result.removed == 1
    assert "old" not in repo.store
    assert repo.store["u1"].data["department"] == "Sales"


async def test_sync_without_credentials_fails(
    service: tuple[GraphSyncService, FakeRedis, FakeSyncedUserRepository],
) -> None:
    svc, _, _ = service
    with pytest.raises(ValidationError) as exc_info:
        await svc.sync_tenant(_tenant(with_creds=False))
    assert exc_info.value.code == "entra_credentials_missing"
