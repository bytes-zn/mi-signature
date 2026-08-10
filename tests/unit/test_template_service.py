"""Unit tests for the TemplateService with an in-memory fake repository."""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.user_context import UserContext
from app.models.template import Template
from app.templates.schemas import TemplateCreate, TemplateUpdate
from app.templates.service import TemplateService

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


class FakeSession:
    async def commit(self) -> None:
        return None

    async def delete(self, obj: object) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class FakeTemplateRepository:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Template] = {}

    async def get_by_id(self, template_id: uuid.UUID) -> Template | None:
        return self.store.get(template_id)

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Template | None:
        return next(
            (t for t in self.store.values() if t.tenant_id == tenant_id and t.name == name),
            None,
        )

    async def list_for_tenant(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[Template]:
        items = [t for t in self.store.values() if t.tenant_id == tenant_id]
        return items[offset : offset + limit]

    def add(self, template: Template) -> None:
        if template.id is None:
            template.id = uuid.uuid4()
        template.status = template.status or "draft"
        now = datetime.now(UTC)
        template.created_at = template.created_at or now
        template.updated_at = template.updated_at or now
        self.store[template.id] = template

    async def delete(self, template: Template) -> None:
        self.store.pop(template.id, None)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> TemplateService:
    repo = FakeTemplateRepository()
    monkeypatch.setattr("app.templates.service.TemplateRepository", lambda session: repo)
    return TemplateService(session=FakeSession())  # type: ignore[arg-type]


def _create_payload(name: str = "default", html: str = "<b>{{ first_name }}</b>") -> TemplateCreate:
    return TemplateCreate(name=name, html_body=html, text_body="{{ first_name }}")


async def test_create_template(service: TemplateService) -> None:
    template = await service.create_template(TENANT_A, _create_payload())
    assert template.name == "default"
    assert template.tenant_id == TENANT_A


async def test_create_template_validates_body(service: TemplateService) -> None:
    with pytest.raises(ValidationError):
        await service.create_template(TENANT_A, _create_payload(html="{{ unknown_var }}"))


async def test_create_template_duplicate_name(service: TemplateService) -> None:
    await service.create_template(TENANT_A, _create_payload())
    with pytest.raises(ConflictError):
        await service.create_template(TENANT_A, _create_payload())


async def test_same_name_allowed_for_different_tenants(service: TemplateService) -> None:
    await service.create_template(TENANT_A, _create_payload())
    template = await service.create_template(TENANT_B, _create_payload())
    assert template.tenant_id == TENANT_B


async def test_get_tenant_template_enforces_ownership(service: TemplateService) -> None:
    template = await service.create_template(TENANT_A, _create_payload())

    with pytest.raises(NotFoundError):
        await service.get_tenant_template(TENANT_B, template.id)


async def test_update_template(service: TemplateService) -> None:
    template = await service.create_template(TENANT_A, _create_payload())

    updated = await service.update_template(
        TENANT_A,
        template.id,
        TemplateUpdate(html_body="<i>{{ last_name }}</i>", status="active"),
    )
    assert updated.html_body == "<i>{{ last_name }}</i>"
    assert updated.status == "active"


async def test_update_template_validates_new_body(service: TemplateService) -> None:
    template = await service.create_template(TENANT_A, _create_payload())

    with pytest.raises(ValidationError):
        await service.update_template(TENANT_A, template.id, TemplateUpdate(html_body="{{ nope }}"))


async def test_update_template_rename_conflict(service: TemplateService) -> None:
    await service.create_template(TENANT_A, _create_payload(name="one"))
    second = await service.create_template(TENANT_A, _create_payload(name="two"))

    with pytest.raises(ConflictError):
        await service.update_template(TENANT_A, second.id, TemplateUpdate(name="one"))


async def test_delete_template(service: TemplateService) -> None:
    template = await service.create_template(TENANT_A, _create_payload())
    await service.delete_template(TENANT_A, template.id)

    with pytest.raises(NotFoundError):
        await service.get_template(template.id)


async def test_delete_template_of_other_tenant_fails(service: TemplateService) -> None:
    template = await service.create_template(TENANT_A, _create_payload())

    with pytest.raises(NotFoundError):
        await service.delete_template(TENANT_B, template.id)


async def test_render_preview(service: TemplateService) -> None:
    template = await service.create_template(TENANT_A, _create_payload())
    html, text = service.render_preview(template, UserContext(first_name="Max"))

    assert html == "<b>Max</b>"
    assert text == "Max"


async def test_render_inline(service: TemplateService) -> None:
    html, text = service.render_inline("{{ first_name }}", None, UserContext(first_name="Erika"))
    assert html == "Erika"
    assert text is None
