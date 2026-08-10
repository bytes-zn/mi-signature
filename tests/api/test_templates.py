"""API tests for template endpoints and the preview endpoint."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.auth.api_key import Caller, get_caller
from app.core.exceptions import NotFoundError
from app.core.user_context import UserContext
from app.models.template import Template
from app.models.tenant import Tenant
from app.templates.router import get_template_service
from app.templates.schemas import TemplateCreate, TemplateUpdate

TEMPLATES_URL = "/api/v1/templates"
PREVIEW_URL = "/api/v1/preview"
OPERATOR_KEY = "dev-operator-key"

TENANT_A_ID = uuid.uuid4()
TENANT_B_ID = uuid.uuid4()


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


def _make_template(tenant_id: uuid.UUID, name: str = "default") -> Template:
    now = datetime.now(UTC)
    return Template(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        description=None,
        html_body="<b>{{ first_name }}</b>",
        text_body="{{ first_name }}",
        status="draft",
        created_at=now,
        updated_at=now,
    )


class FakeTemplateService:
    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Template] = {}

    async def create_template(self, tenant_id: uuid.UUID, data: TemplateCreate) -> Template:
        template = _make_template(tenant_id, data.name)
        self.store[template.id] = template
        return template

    async def get_template(self, template_id: uuid.UUID) -> Template:
        if template_id not in self.store:
            raise NotFoundError("not found")
        return self.store[template_id]

    async def list_templates(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[Template]:
        return [t for t in self.store.values() if t.tenant_id == tenant_id]

    async def update_template(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID, data: TemplateUpdate
    ) -> Template:
        template = await self.get_template(template_id)
        if data.name is not None:
            template.name = data.name
        return template

    async def delete_template(self, tenant_id: uuid.UUID, template_id: uuid.UUID) -> None:
        self.store.pop(template_id, None)

    def render_preview(self, template: Template, user: UserContext) -> tuple[str, str | None]:
        return f"rendered:{template.name}:{user.first_name}", None

    def render_inline(
        self, html_body: str | None, text_body: str | None, user: UserContext
    ) -> tuple[str | None, str | None]:
        return (f"inline:{user.first_name}" if html_body else None), None


@pytest.fixture
def fake_service(app: FastAPI) -> Any:
    service = FakeTemplateService()
    app.dependency_overrides[get_template_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


def _as_tenant(app: FastAPI, tenant_id: uuid.UUID) -> None:
    app.dependency_overrides[get_caller] = lambda: Caller(
        tenant=_tenant(tenant_id), is_operator=False
    )


async def test_create_as_tenant_scoped_to_own_tenant(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    _as_tenant(app, TENANT_A_ID)

    response = await client.post(
        TEMPLATES_URL, json={"name": "sig", "html_body": "<b>x</b>"}, headers={"X-API-Key": "k"}
    )

    assert response.status_code == 201
    assert response.json()["tenant_id"] == str(TENANT_A_ID)


async def test_create_as_operator_requires_tenant_id(
    client: AsyncClient, fake_service: Any
) -> None:
    response = await client.post(
        TEMPLATES_URL,
        json={"name": "sig", "html_body": "<b>x</b>"},
        headers={"X-API-Key": OPERATOR_KEY},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tenant_required"


async def test_create_as_operator_with_tenant_id(client: AsyncClient, fake_service: Any) -> None:
    response = await client.post(
        TEMPLATES_URL,
        json={"name": "sig", "html_body": "<b>x</b>", "tenant_id": str(TENANT_A_ID)},
        headers={"X-API-Key": OPERATOR_KEY},
    )
    assert response.status_code == 201


async def test_get_template_of_other_tenant_forbidden(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    template = _make_template(TENANT_B_ID)
    fake_service.store[template.id] = template
    _as_tenant(app, TENANT_A_ID)

    response = await client.get(f"{TEMPLATES_URL}/{template.id}", headers={"X-API-Key": "k"})
    assert response.status_code == 403


async def test_update_and_delete_template(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    template = _make_template(TENANT_A_ID)
    fake_service.store[template.id] = template
    _as_tenant(app, TENANT_A_ID)

    response = await client.put(
        f"{TEMPLATES_URL}/{template.id}", json={"name": "new"}, headers={"X-API-Key": "k"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "new"

    response = await client.delete(f"{TEMPLATES_URL}/{template.id}", headers={"X-API-Key": "k"})
    assert response.status_code == 204


async def test_preview_with_template_id(
    app: FastAPI, client: AsyncClient, fake_service: Any
) -> None:
    template = _make_template(TENANT_A_ID)
    fake_service.store[template.id] = template
    _as_tenant(app, TENANT_A_ID)

    response = await client.post(
        PREVIEW_URL,
        json={"template_id": str(template.id), "user": {"first_name": "Max"}},
        headers={"X-API-Key": "k"},
    )
    assert response.status_code == 200
    assert response.json()["html"] == "rendered:default:Max"


async def test_preview_inline(client: AsyncClient, fake_service: Any) -> None:
    response = await client.post(
        PREVIEW_URL,
        json={"html_body": "<b>{{ first_name }}</b>", "user": {"first_name": "Erika"}},
        headers={"X-API-Key": OPERATOR_KEY},
    )
    assert response.status_code == 200
    assert response.json()["html"] == "inline:Erika"


async def test_preview_requires_source(client: AsyncClient, fake_service: Any) -> None:
    response = await client.post(
        PREVIEW_URL, json={"user": {}}, headers={"X-API-Key": OPERATOR_KEY}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "preview_source_required"
