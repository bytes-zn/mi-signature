"""Unit tests for the RuleService with in-memory fake repositories."""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.user_context import UserContext
from app.models.rule import Rule
from app.models.template import Template
from app.rules.schemas import RuleCreate, RuleUpdate
from app.rules.service import RuleService

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
TEMPLATE_A = uuid.uuid4()


class FakeSession:
    async def commit(self) -> None:
        return None

    async def delete(self, obj: object) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class FakeRuleRepository:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Rule] = {}

    async def get_by_id(self, rule_id: uuid.UUID) -> Rule | None:
        return self.store.get(rule_id)

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Rule | None:
        return next(
            (r for r in self.store.values() if r.tenant_id == tenant_id and r.name == name), None
        )

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[Rule]:
        items = sorted(
            (r for r in self.store.values() if r.tenant_id == tenant_id),
            key=lambda r: -r.priority,
        )
        return items[offset : offset + limit]

    async def list_active_for_tenant(self, tenant_id: uuid.UUID) -> list[Rule]:
        return sorted(
            (r for r in self.store.values() if r.tenant_id == tenant_id and r.status == "active"),
            key=lambda r: -r.priority,
        )

    def add(self, rule: Rule) -> None:
        if rule.id is None:
            rule.id = uuid.uuid4()
        rule.status = rule.status or "active"
        now = datetime.now(UTC)
        rule.created_at = rule.created_at or now
        rule.updated_at = rule.updated_at or now
        self.store[rule.id] = rule

    async def delete(self, rule: Rule) -> None:
        self.store.pop(rule.id, None)


class FakeTemplateRepository:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Template] = {
            TEMPLATE_A: Template(id=TEMPLATE_A, tenant_id=TENANT_A, name="sig")
        }

    async def get_by_id(self, template_id: uuid.UUID) -> Template | None:
        return self.store.get(template_id)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> RuleService:
    rules = FakeRuleRepository()
    templates = FakeTemplateRepository()
    monkeypatch.setattr("app.rules.service.RuleRepository", lambda session: rules)
    monkeypatch.setattr("app.rules.service.TemplateRepository", lambda session: templates)
    return RuleService(session=FakeSession())  # type: ignore[arg-type]


def _payload(
    name: str = "sales-rule",
    priority: int = 0,
    template_id: uuid.UUID = TEMPLATE_A,
    **kwargs: object,
) -> RuleCreate:
    return RuleCreate(
        name=name,
        template_id=template_id,
        priority=priority,
        conditions={
            "type": "leaf",
            "field": "department",
            "operator": "equals",
            "value": "Sales",
        },
        **kwargs,  # type: ignore[arg-type]
    )


async def test_create_rule(service: RuleService) -> None:
    rule = await service.create_rule(TENANT_A, _payload())
    assert rule.name == "sales-rule"
    assert rule.conditions["field"] == "department"


async def test_create_rule_rejects_foreign_template(service: RuleService) -> None:
    with pytest.raises(ValidationError) as exc_info:
        await service.create_rule(TENANT_A, _payload(template_id=uuid.uuid4()))
    assert exc_info.value.code == "template_not_in_tenant"


async def test_create_rule_duplicate_name(service: RuleService) -> None:
    await service.create_rule(TENANT_A, _payload())
    with pytest.raises(ConflictError):
        await service.create_rule(TENANT_A, _payload())


async def test_get_tenant_rule_enforces_ownership(service: RuleService) -> None:
    rule = await service.create_rule(TENANT_A, _payload())
    with pytest.raises(NotFoundError):
        await service.get_tenant_rule(TENANT_B, rule.id)


async def test_update_rule(service: RuleService) -> None:
    rule = await service.create_rule(TENANT_A, _payload())
    updated = await service.update_rule(
        TENANT_A,
        rule.id,
        RuleUpdate(
            priority=50,
            conditions={"type": "leaf", "field": "country", "operator": "in", "value": ["DE"]},
        ),
    )
    assert updated.priority == 50
    assert updated.conditions["field"] == "country"


async def test_delete_rule(service: RuleService) -> None:
    rule = await service.create_rule(TENANT_A, _payload())
    await service.delete_rule(TENANT_A, rule.id)
    with pytest.raises(NotFoundError):
        await service.get_rule(rule.id)


async def test_evaluate_returns_highest_priority_match(service: RuleService) -> None:
    low = await service.create_rule(TENANT_A, _payload(name="low", priority=10))
    high = await service.create_rule(TENANT_A, _payload(name="high", priority=90))
    await service.create_rule(TENANT_A, _payload(name="inactive", priority=100, status="inactive"))

    match = await service.evaluate_for_user(TENANT_A, UserContext(department="sales"))
    assert match is not None
    assert match.id == high.id
    assert match.id != low.id


async def test_evaluate_no_match_returns_none(service: RuleService) -> None:
    await service.create_rule(TENANT_A, _payload())
    assert await service.evaluate_for_user(TENANT_A, UserContext(department="IT")) is None
