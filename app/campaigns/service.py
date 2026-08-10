"""Campaign service: business logic for time-boxed banner campaigns.

Targeting reuses the rule engine's condition tree and evaluator - there
is deliberately no second condition implementation here.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.repository import CampaignRepository
from app.campaigns.schemas import CampaignCreate, CampaignUpdate
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.user_context import UserContext
from app.models.campaign import Campaign
from app.rules.conditions import Condition
from app.rules.engine import evaluate

_condition_adapter: TypeAdapter[Condition] = TypeAdapter(Condition)


def campaign_phase(campaign: Campaign, at: datetime) -> str:
    """Derive the lifecycle phase of a campaign at a point in time."""
    if campaign.status != "active":
        return "inactive"
    if at < campaign.start_at:
        return "scheduled"
    if at > campaign.end_at:
        return "expired"
    return "running"


class CampaignService:
    """Use cases around campaigns and campaign evaluation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._campaigns = CampaignRepository(session)

    async def create_campaign(self, tenant_id: uuid.UUID, data: CampaignCreate) -> Campaign:
        if await self._campaigns.get_by_name(tenant_id, data.name) is not None:
            raise ConflictError(f"Campaign with name '{data.name}' already exists for this tenant.")

        campaign = Campaign(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            status=data.status,
            start_at=data.start_at,
            end_at=data.end_at,
            priority=data.priority,
            banner_html=data.banner_html,
            banner_text=data.banner_text,
            link_url=data.link_url,
            conditions=self._serialize(data.conditions),
        )
        self._campaigns.add(campaign)
        await self._session.commit()
        await self._session.refresh(campaign)
        return campaign

    async def get_campaign(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self._campaigns.get_by_id(campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign '{campaign_id}' not found.")
        return campaign

    async def get_tenant_campaign(self, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        if campaign.tenant_id != tenant_id:
            raise NotFoundError(f"Campaign '{campaign_id}' not found.")
        return campaign

    async def list_campaigns(
        self, tenant_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> Sequence[Campaign]:
        return await self._campaigns.list_for_tenant(tenant_id, offset=offset, limit=limit)

    async def update_campaign(
        self, tenant_id: uuid.UUID, campaign_id: uuid.UUID, data: CampaignUpdate
    ) -> Campaign:
        campaign = await self.get_tenant_campaign(tenant_id, campaign_id)

        new_start = data.start_at if data.start_at is not None else campaign.start_at
        new_end = data.end_at if data.end_at is not None else campaign.end_at
        if new_end <= new_start:
            raise ValidationError("end_at must be after start_at.", code="invalid_time_window")

        if data.name is not None and data.name != campaign.name:
            if await self._campaigns.get_by_name(tenant_id, data.name) is not None:
                raise ConflictError(
                    f"Campaign with name '{data.name}' already exists for this tenant."
                )
            campaign.name = data.name

        if data.description is not None:
            campaign.description = data.description
        if data.status is not None:
            campaign.status = data.status
        if data.start_at is not None:
            campaign.start_at = data.start_at
        if data.end_at is not None:
            campaign.end_at = data.end_at
        if data.priority is not None:
            campaign.priority = data.priority
        if data.banner_html is not None:
            campaign.banner_html = data.banner_html
        if data.banner_text is not None:
            campaign.banner_text = data.banner_text
        if data.link_url is not None:
            campaign.link_url = data.link_url
        if data.conditions is not None:
            campaign.conditions = self._serialize(data.conditions)

        await self._session.commit()
        await self._session.refresh(campaign)
        return campaign

    async def delete_campaign(self, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> None:
        campaign = await self.get_tenant_campaign(tenant_id, campaign_id)
        await self._campaigns.delete(campaign)
        await self._session.commit()

    async def evaluate_for_user(
        self, tenant_id: uuid.UUID, user: UserContext, at: datetime | None = None
    ) -> Campaign | None:
        """Return the highest-priority running campaign matching the user.

        ``at`` defaults to now (UTC); pass a timestamp to test future or
        past windows (dry-run).
        """
        moment = at or datetime.now(UTC)
        campaigns = await self._campaigns.list_active_for_tenant(tenant_id)
        for campaign in campaigns:
            if not (campaign.start_at <= moment <= campaign.end_at):
                continue
            if campaign.conditions is None:
                return campaign
            condition = _condition_adapter.validate_python(campaign.conditions)
            if evaluate(condition, user):
                return campaign
        return None

    @staticmethod
    def _serialize(conditions: Condition | None) -> dict[str, Any] | None:
        if conditions is None:
            return None
        return conditions.model_dump(mode="json")
