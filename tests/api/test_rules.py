"""API tests for the rules endpoints including evaluation."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.auth.api_key import Caller, get_caller
from app.core.exceptions import NotFoundError
from app.core.user_context import UserContext
from app.models.rule import Rule
from app.models.tenant import Tenant
from app.rules.router import get_rule_service
from app.rules.schemas import RuleCreate, RuleUpdate

RULES_URL = "/api/v1/rules"
OPERATOR_KEY = "dev-operator-key"

TENANT_A_ID = uuid.uuid4()
TENANT_B_ID = uuid.uuid4()
TEMPLATE_ID = uuid.uuid4()


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


def _make_rule(tenant_id: uuid.UUID, name: str = "sales-rule", priority: int = 0) -> Rule:
    now = datetime.now(UTC)
    return Rule(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        template_id=TEMPLATE_ID,
        name=name,
        description=None,
        status="active",
        priority=priority,
        conditions={"type": "leaf", "field": "department", "operator": "equals", "value": "Sales"},
        created_at=now,
        updated_at=now,
    )


class FakeRuleService:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Rule] = {}

    async def create_rule(self, tenant_id: uuid.UUID, data: RuleCreate) -> Rule:
        rule = _make_rule(tenant_id, data.name, data.priority)
        self.store[rule.id] = rule
        return rule

    async def get_rule(self, rule_id: uuid.UUID) -> Rule:
        if rule_id not in self.store:
            raise NotFoundError("not found")
        return self.store[rule_id]

    async def list_rules(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[Rule]:
        return sorted(
            (r for r in self.store.values() if r.tenant_id == tenant_id),
            key=lambda r: -r.priority,
        )

    async def update_rule(self, tenant_id: uuid.UUID, rule_id: uuid.UUID, data: RuleUpdate) -> Rule:
        rule = await self.get_rule(rule_id)
        if data.priority is not None:
            rule.priority = data.priority
        return rule

    async def delete_rule(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> None:
        self.store.pop(rule_id, None)

    async def evaluate_for_user(self, tenant_id: uuid.UUID, user: UserContext) -> Rule | None:
        if user.department.lower() == "sales":
            return next((r for r in self.store.values() if r.tenant_id == tenant_id), None)
        return None


@pytest.fixture
def fake_service(app: FastAPI) -> Any:
    service = FakeRuleService()
    app.dependency_overrides[get_rule_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


def _as_tenant(app: FastAPI, tenant_id: uuid.UUID) -> None:
    app.dependency_overrides[get_caller] = lambda: Caller(
        tenant=_tenant(tenant_id), is_operator=False
    )


def _conditions() -> dict[str, Any]:
    return {"type": "leaf", "field": "department", "operator": "equals", "value": "Sales"}


async def test_create_rule_as_tenant(app: FastAPI, client: AsyncClient, fake_service: Any) -> None:
    _as_tenant(app, TENANT_A_ID)
    response = await client.post(
        RULES_URL,
        json={"name": "r1", "template_id": str(TEMPLATE_ID), "conditions": _conditions()},
        headers={"X-API-Key": "k"},
    )
    assert response.status_code == 201
    assert response.json()["tenant_id"] == str(TENANT_A_ID)


async def test_create_rule_invalid_field_rejected(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    _as_tenant(app, TENANT_A_ID)
    response = await client.post(
        RULES_URL,
        json={
            "name": "r1",
            "template_id": str(TEMPLATE_ID),
            "conditions": {
                "type": "leaf",
                "field": "nickname",
                "operator": "equals",
                "value": "x",
            },
        },
        headers={"X-API-Key": "k"},
    )
    assert response.status_code == 422


async def test_create_rule_as_operator_requires_tenant_id(
    client: AsyncClient, fake_service: Any
) -> None:
    response = await client.post(
        RULES_URL,
        json={"name": "r1", "template_id": str(TEMPLATE_ID), "conditions": _conditions()},
        headers={"X-API-Key": OPERATOR_KEY},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tenant_required"


async def test_get_rule_of_other_tenant_forbidden(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    rule = _make_rule(TENANT_B_ID)
    fake_service.store[rule.id] = rule
    _as_tenant(app, TENANT_A_ID)

    response = await client.get(f"{RULES_URL}/{rule.id}", headers={"X-API-Key": "k"})
    assert response.status_code == 403


async def test_update_and_delete_rule(app: FastAPI, client: AsyncClient, fake_service: Any) -> None:
    rule = _make_rule(TENANT_A_ID)
    fake_service.store[rule.id] = rule
    _as_tenant(app, TENANT_A_ID)

    response = await client.put(
        f"{RULES_URL}/{rule.id}", json={"priority": 42}, headers={"X-API-Key": "k"}
    )
    assert response.status_code == 200
    assert response.json()["priority"] == 42

    response = await client.delete(f"{RULES_URL}/{rule.id}", headers={"X-API-Key": "k"})
    assert response.status_code == 204


async def test_evaluate_match(app: FastAPI, client: AsyncClient, fake_service: Any) -> None:
    rule = _make_rule(TENANT_A_ID)
    fake_service.store[rule.id] = rule
    _as_tenant(app, TENANT_A_ID)

    response = await client.post(
        f"{RULES_URL}/evaluate",
        json={"user": {"department": "Sales"}},
        headers={"X-API-Key": "k"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["rule"]["id"] == str(rule.id)


async def test_evaluate_no_match(app: FastAPI, client: AsyncClient, fake_service: Any) -> None:
    _as_tenant(app, TENANT_A_ID)
    response = await client.post(
        f"{RULES_URL}/evaluate",
        json={"user": {"department": "IT"}},
        headers={"X-API-Key": "k"},
    )
    assert response.status_code == 200
    assert response.json() == {"matched": False, "rule": None}
