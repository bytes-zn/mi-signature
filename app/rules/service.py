"""Rule service: business logic for tenant-scoped signature rules."""

import json
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.user_context import UserContext
from app.models.rule import Rule
from app.rules.conditions import Condition, parse_conditions
from app.rules.engine import evaluate
from app.rules.repository import RuleRepository
from app.rules.schemas import RuleCreate, RuleUpdate
from app.templates.repository import TemplateRepository

_condition_adapter: TypeAdapter[Condition] = TypeAdapter(Condition)


class RuleService:
    """Use cases around rules and rule evaluation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rules = RuleRepository(session)
        self._templates = TemplateRepository(session)

    async def create_rule(self, tenant_id: uuid.UUID, data: RuleCreate) -> Rule:
        await self._ensure_template_belongs_to_tenant(tenant_id, data.template_id)

        if await self._rules.get_by_name(tenant_id, data.name) is not None:
            raise ConflictError(f"Rule with name '{data.name}' already exists for this tenant.")

        rule = Rule(
            tenant_id=tenant_id,
            template_id=data.template_id,
            name=data.name,
            description=data.description,
            status=data.status,
            priority=data.priority,
            conditions=self._serialize_conditions(data.conditions),
        )
        self._rules.add(rule)
        await self._session.commit()
        await self._session.refresh(rule)
        return rule

    async def get_rule(self, rule_id: uuid.UUID) -> Rule:
        rule = await self._rules.get_by_id(rule_id)
        if rule is None:
            raise NotFoundError(f"Rule '{rule_id}' not found.")
        return rule

    async def get_tenant_rule(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> Rule:
        rule = await self.get_rule(rule_id)
        if rule.tenant_id != tenant_id:
            raise NotFoundError(f"Rule '{rule_id}' not found.")
        return rule

    async def list_rules(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> Sequence[Rule]:
        return await self._rules.list_for_tenant(tenant_id, offset=offset, limit=limit)

    async def update_rule(self, tenant_id: uuid.UUID, rule_id: uuid.UUID, data: RuleUpdate) -> Rule:
        rule = await self.get_tenant_rule(tenant_id, rule_id)

        if data.template_id is not None:
            await self._ensure_template_belongs_to_tenant(tenant_id, data.template_id)
            rule.template_id = data.template_id

        if data.name is not None and data.name != rule.name:
            if await self._rules.get_by_name(tenant_id, data.name) is not None:
                raise ConflictError(f"Rule with name '{data.name}' already exists for this tenant.")
            rule.name = data.name

        if data.description is not None:
            rule.description = data.description
        if data.status is not None:
            rule.status = data.status
        if data.priority is not None:
            rule.priority = data.priority
        if data.conditions is not None:
            rule.conditions = self._serialize_conditions(data.conditions)

        await self._session.commit()
        await self._session.refresh(rule)
        return rule

    async def delete_rule(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> None:
        rule = await self.get_tenant_rule(tenant_id, rule_id)
        await self._rules.delete(rule)
        await self._session.commit()

    async def evaluate_for_user(self, tenant_id: uuid.UUID, user: UserContext) -> Rule | None:
        """Return the highest-priority active rule matching the user, if any."""
        rules = await self._rules.list_active_for_tenant(tenant_id)
        for rule in rules:
            condition = parse_conditions(json.dumps(rule.conditions, sort_keys=True))
            if evaluate(condition, user):
                return rule
        return None

    async def _ensure_template_belongs_to_tenant(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> None:
        template = await self._templates.get_by_id(template_id)
        if template is None or template.tenant_id != tenant_id:
            raise ValidationError(
                f"Template '{template_id}' does not exist for this tenant.",
                code="template_not_in_tenant",
            )

    @staticmethod
    def _serialize_conditions(conditions: Condition) -> dict[str, Any]:
        return conditions.model_dump(mode="json")
