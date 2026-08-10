"""Integration tests for the template module against a real PostgreSQL."""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.user_context import UserContext
from app.database.session import build_engine, build_session_factory
from app.templates.schemas import TemplateCreate, TemplateUpdate
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
async def tenant_id(session: AsyncSession) -> AsyncIterator[uuid.UUID]:
    tenant_service = TenantService(session)
    tenant, _ = await tenant_service.create_tenant(TenantCreate(name=f"it-{uuid.uuid4().hex[:12]}"))
    yield tenant.id
    await tenant_service.delete_tenant(tenant.id)


async def test_template_roundtrip(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    service = TemplateService(session)

    template = await service.create_template(
        tenant_id,
        TemplateCreate(
            name="default",
            html_body="<b>{{ first_name }} {{ last_name }}</b>",
            text_body="{{ first_name }} {{ last_name }}",
            status="active",
        ),
    )
    assert template.id is not None

    fetched = await service.get_tenant_template(tenant_id, template.id)
    assert fetched.name == "default"

    updated = await service.update_template(
        tenant_id, template.id, TemplateUpdate(description="Standard-Signatur")
    )
    assert updated.description == "Standard-Signatur"

    html, text = service.render_preview(
        updated, UserContext(first_name="Max", last_name="Mustermann")
    )
    assert html == "<b>Max Mustermann</b>"
    assert text == "Max Mustermann"

    await service.delete_template(tenant_id, template.id)
    assert await service.list_templates(tenant_id) == []


async def test_unknown_variable_rejected(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    service = TemplateService(session)
    with pytest.raises(ValidationError):
        await service.create_template(
            tenant_id, TemplateCreate(name="broken", html_body="{{ manager_name }}")
        )


async def test_templates_deleted_with_tenant(session: AsyncSession) -> None:
    tenant_service = TenantService(session)
    tenant, _ = await tenant_service.create_tenant(TenantCreate(name=f"it-{uuid.uuid4().hex[:12]}"))
    service = TemplateService(session)

    template = await service.create_template(
        tenant.id, TemplateCreate(name="cascade", html_body="{{ first_name }}")
    )
    await tenant_service.delete_tenant(tenant.id)

    with pytest.raises(NotFoundError):
        await service.get_template(template.id)
