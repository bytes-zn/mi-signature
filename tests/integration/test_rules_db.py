"""Integration tests for the rules module against a real PostgreSQL."""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.user_context import UserContext
from app.database.session import build_engine, build_session_factory
from app.rules.schemas import RuleCreate, RuleUpdate
from app.rules.service import RuleService
from app.templates.schemas import TemplateCreate
from app.templates.service import TemplateService
from app.tenants.schemas import TenantCreate
from app.tenants.service import TenantService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="integration tests require RUN_INTEGRATION_TESTS=1 and live services",
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = build_engine(get_settings())
    factory = build_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def tenant_setup(session: AsyncSession) -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    tenant_service = TenantService(session)
    tenant, _ = await tenant_service.create_tenant(TenantCreate(name=f"it-{uuid.uuid4().hex[:12]}"))
    template_service = TemplateService(session)
    template = await template_service.create_template(
        tenant.id, TemplateCreate(name="sig", html_body="{{ first_name }}")
    )
    yield tenant.id, template.id
    await tenant_service.delete_tenant(tenant.id)


async def test_rule_roundtrip_and_evaluation(
    session: AsyncSession, tenant_setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_id, template_id = tenant_setup
    service = RuleService(session)

    rule = await service.create_rule(
        tenant_id,
        RuleCreate(
            name="dach-sales",
            template_id=template_id,
            priority=10,
            conditions={
                "type": "group",
                "op": "and",
                "children": [
                    {"type": "leaf", "field": "department", "operator": "equals", "value": "Sales"},
                    {"type": "leaf", "field": "country", "operator": "in", "value": ["DE", "AT"]},
                ],
            },
        ),
    )
    assert rule.id is not None

    match = await service.evaluate_for_user(
        tenant_id, UserContext(department="Sales", country="DE")
    )
    assert match is not None
    assert match.id == rule.id

    assert (
        await service.evaluate_for_user(tenant_id, UserContext(department="IT", country="DE"))
        is None
    )

    updated = await service.update_rule(tenant_id, rule.id, RuleUpdate(priority=99))
    assert updated.priority == 99

    await service.delete_rule(tenant_id, rule.id)
    assert await service.list_rules(tenant_id) == []


async def test_rules_deleted_with_template(
    session: AsyncSession, tenant_setup: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_id, template_id = tenant_setup
    rule_service = RuleService(session)
    template_service = TemplateService(session)

    rule = await rule_service.create_rule(
        tenant_id,
        RuleCreate(
            name="cascade",
            template_id=template_id,
            conditions={"type": "leaf", "field": "department", "operator": "equals", "value": "X"},
        ),
    )
    await template_service.delete_template(tenant_id, template_id)

    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await rule_service.get_rule(rule.id)
