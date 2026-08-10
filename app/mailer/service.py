"""Mail processing service: the signature mail-flow engine.

Pipeline (per message in the interception mailbox):

1. Fetch raw MIME from the mailbox (Graph ``$value``).
2. Parse it (``app.mailer.processor``) - sender, recipients, bodies,
   attachments are all preserved.
3. Resolve the sender's ``UserContext`` from the synced directory.
4. Evaluate rules (template selection) and campaigns (banner).
5. Render the signature and append it to both bodies.
6. Re-send via the configured outbound channel:
   - ``graph`` (default): M365 Graph ``sendMail`` from a privileged app.
   - ``resend``: tenant's Resend (relay) - bypasses the M365 high-risk
     outbound pool.
7. Delete the original message from the interception mailbox.

The transport rule redirects originals here; recipients only ever see
the re-sent, signed copy.
"""

import base64
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.service import CampaignService
from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.core.user_context import UserContext
from app.graph.client import GraphClient
from app.graph.repository import SyncedUserRepository
from app.mailer.processor import ProcessedMail, build_sendmail_body, process_mime
from app.mailer.resend_client import ResendClient
from app.models.tenant import Tenant
from app.rules.service import RuleService
from app.templates.service import TemplateService

GRAPH_V1 = "https://graph.microsoft.com/v1.0"


@dataclass
class ProcessingReport:
    """Outcome of processing one intercepted message."""

    graph_message_id: str
    from_upn: str | None = None
    subject: str | None = None
    status: str = "pending"  # sent | skipped | error
    detail: str = ""


@dataclass
class PollReport:
    """Outcome of one polling run."""

    mailbox: str
    processed: int = 0
    sent: int = 0
    skipped: int = 0
    errors: int = 0
    reports: list[ProcessingReport] = field(default_factory=list)


class MailProcessingService:
    """Use cases around signature injection into intercepted mail."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = SyncedUserRepository(session)
        self._templates = TemplateService(session)
        self._rules = RuleService(session)
        self._campaigns = CampaignService(session)

    async def poll_mailbox(self, tenant: Tenant) -> PollReport:
        """Process all unread messages of the interception mailbox."""
        mailbox = tenant.settings.get("interception_mailbox") or self._mailbox_from_env()
        if not mailbox:
            raise ValidationError(
                "No interception mailbox configured (tenant setting or INTERCEPTION_MAILBOX_UPN).",
                code="interception_mailbox_missing",
            )

        client = self._build_client(tenant)
        report = PollReport(mailbox=mailbox)

        listing = await client.get_json(
            f"{GRAPH_V1}/users/{mailbox}/mailFolders/inbox/messages"
            "?$filter=isRead eq false&$select=id,subject&$top=50"
        )
        messages = listing.get("value", [])

        for message in messages:
            item = await self._process_one(client, tenant, mailbox, message["id"])
            report.reports.append(item)
            report.processed += 1
            if item.status == "sent":
                report.sent += 1
            elif item.status == "skipped":
                report.skipped += 1
            else:
                report.errors += 1

        return report

    async def _process_one(
        self, client: GraphClient, tenant: Tenant, mailbox: str, message_id: str
    ) -> ProcessingReport:
        report = ProcessingReport(graph_message_id=message_id)
        try:
            raw = await client.get_bytes(f"{GRAPH_V1}/users/{mailbox}/messages/{message_id}/$value")
            processed = await self.process_bytes(tenant, raw)
            report.from_upn = processed.from_upn
            report.subject = processed.subject

            await self._send(tenant, processed)
            await client.delete(f"{GRAPH_V1}/users/{mailbox}/messages/{message_id}")
            report.status = "sent"
        except SkipMessage as exc:
            report.status = "skipped"
            report.detail = str(exc)
            await self._mark_read(client, mailbox, message_id)
        except Exception as exc:  # noqa: BLE001 - report and continue with next message
            report.status = "error"
            report.detail = str(exc)[:300]
        return report

    async def _send(self, tenant: Tenant, processed: ProcessedMail) -> None:
        """Route the signed message to the tenant's configured outbound channel."""
        if tenant.mailflow_outbound == "resend":
            await self._send_via_resend(tenant, processed)
        else:
            await self._send_via_graph(tenant, processed)

    async def _send_via_graph(self, tenant: Tenant, processed: ProcessedMail) -> None:
        client = self._build_client(tenant)
        body = build_sendmail_body(processed)
        await client.post_json(f"{GRAPH_V1}/users/{processed.from_upn}/sendMail", body)

    async def _send_via_resend(self, tenant: Tenant, processed: ProcessedMail) -> None:
        if not self._settings.resend_api_key:
            raise ValidationError(
                "RESEND_API_KEY is not configured on the platform.",
                code="resend_key_missing",
            )
        if not tenant.resend_domain_id or not tenant.resend_domain_verified:
            raise ValidationError(
                "Resend domain is not fully provisioned + verified for this tenant.",
                code="resend_not_verified",
            )

        sender = processed.from_upn
        attachments = [
            {
                "filename": att.filename,
                "content_bytes": base64.b64encode(att.content_bytes).decode(),
                "content_id": att.content_id,
            }
            for att in processed.attachments
        ]
        client = ResendClient(api_key=self._settings.resend_api_key)
        client.send_email(
            sender=sender,
            to=processed.to,
            subject=processed.subject,
            html=processed.html_body,
            text=processed.text_body,
            reply_to=processed.reply_to or None,
            attachments=attachments or None,
        )

    async def process_bytes(self, tenant: Tenant, raw: bytes) -> ProcessedMail:
        """Transform raw MIME into a signed, delivery-ready message."""
        from email import policy as email_policy
        from email.parser import BytesParser

        sender = BytesParser(policy=email_policy.default).parsebytes(raw).get("From", "")
        from email.utils import parseaddr

        from_upn = parseaddr(sender)[1].lower()
        if not from_upn:
            raise SkipMessage("no usable From header")

        synced = await self._users.get_by_email(tenant.id, from_upn)
        if synced is None:
            raise SkipMessage(f"sender '{from_upn}' is not a synced user of this tenant")

        user = UserContext.model_validate(synced.data)

        rule = await self._rules.evaluate_for_user(tenant.id, user)
        if rule is None:
            raise SkipMessage(f"no rule matches sender '{from_upn}'")

        template = await self._templates.get_tenant_template(tenant.id, rule.template_id)
        signature_html, signature_text = self._templates.render_preview(template, user)

        campaign = await self._campaigns.evaluate_for_user(tenant.id, user)
        if campaign is not None:
            signature_html += campaign.banner_html
            if campaign.banner_text and signature_text is not None:
                signature_text += "\n\n" + campaign.banner_text

        return process_mime(raw, signature_html, signature_text or "")

    async def _mark_read(self, client: GraphClient, mailbox: str, message_id: str) -> None:
        await client.patch_json(
            f"{GRAPH_V1}/users/{mailbox}/messages/{message_id}",
            {"isRead": True},
        )

    def _build_client(self, tenant: Tenant) -> GraphClient:
        tenant_id = tenant.microsoft_tenant_id or self._settings.entra_tenant_id
        client_id = tenant.entra_client_id or self._settings.entra_client_id
        client_secret = tenant.entra_client_secret or self._settings.entra_client_secret
        if not (tenant_id and client_id and client_secret):
            raise ValidationError(
                "Tenant has no Entra credentials and no fallback is configured.",
                code="entra_credentials_missing",
            )
        return GraphClient(tenant_id, client_id, client_secret)

    def _mailbox_from_env(self) -> str | None:
        return getattr(self._settings, "interception_mailbox_upn", None)


class SkipMessage(Exception):
    """A message that must not be signed (unknown sender, no matching rule)."""
