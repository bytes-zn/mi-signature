"""Template service: business logic for tenant-scoped signature templates."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.user_context import UserContext
from app.models.template import Template
from app.templates.engine import get_template_engine
from app.templates.repository import TemplateRepository
from app.templates.schemas import TemplateCreate, TemplateUpdate


class TemplateService:
    """Use cases around signature templates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._templates = TemplateRepository(session)
        self._engine = get_template_engine()

    async def create_template(self, tenant_id: uuid.UUID, data: TemplateCreate) -> Template:
        """Create a template after validating both bodies."""
        self._validate_bodies(data.html_body, data.text_body)

        if await self._templates.get_by_name(tenant_id, data.name) is not None:
            raise ConflictError(f"Template with name '{data.name}' already exists for this tenant.")

        template = Template(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            html_body=data.html_body,
            text_body=data.text_body,
            status=data.status,
        )
        self._templates.add(template)
        await self._session.commit()
        await self._session.refresh(template)
        return template

    async def get_template(self, template_id: uuid.UUID) -> Template:
        template = await self._templates.get_by_id(template_id)
        if template is None:
            raise NotFoundError(f"Template '{template_id}' not found.")
        return template

    async def get_tenant_template(self, tenant_id: uuid.UUID, template_id: uuid.UUID) -> Template:
        """Load a template and enforce that it belongs to the tenant."""
        template = await self.get_template(template_id)
        if template.tenant_id != tenant_id:
            raise NotFoundError(f"Template '{template_id}' not found.")
        return template

    async def list_templates(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> Sequence[Template]:
        return await self._templates.list_for_tenant(tenant_id, offset=offset, limit=limit)

    async def update_template(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID, data: TemplateUpdate
    ) -> Template:
        template = await self.get_tenant_template(tenant_id, template_id)

        new_html = data.html_body if data.html_body is not None else template.html_body
        new_text = data.text_body if data.text_body is not None else template.text_body
        self._validate_bodies(new_html, new_text)

        if data.name is not None and data.name != template.name:
            if await self._templates.get_by_name(tenant_id, data.name) is not None:
                raise ConflictError(
                    f"Template with name '{data.name}' already exists for this tenant."
                )
            template.name = data.name

        if data.description is not None:
            template.description = data.description
        if data.html_body is not None:
            template.html_body = data.html_body
        if data.text_body is not None:
            template.text_body = data.text_body
        if data.status is not None:
            template.status = data.status

        await self._session.commit()
        await self._session.refresh(template)
        return template

    async def delete_template(self, tenant_id: uuid.UUID, template_id: uuid.UUID) -> None:
        template = await self.get_tenant_template(tenant_id, template_id)
        await self._templates.delete(template)
        await self._session.commit()

    def render_preview(self, template: Template, user: UserContext) -> tuple[str, str | None]:
        """Render a template with sample user data (for the preview endpoint)."""
        html = self._engine.render(template.html_body, user)
        text = self._engine.render(template.text_body, user) if template.text_body else None
        return html, text

    def render_inline(
        self, html_body: str | None, text_body: str | None, user: UserContext
    ) -> tuple[str | None, str | None]:
        """Render ad-hoc template sources without persisting them."""
        html = self._engine.render(html_body, user) if html_body is not None else None
        text = self._engine.render(text_body, user) if text_body is not None else None
        return html, text

    def _validate_bodies(self, html_body: str, text_body: str | None) -> None:
        self._engine.validate(html_body)
        if text_body is not None:
            self._engine.validate(text_body)
