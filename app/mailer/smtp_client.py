"""SMTP delivery of processed mail back to Microsoft 365.

After the signature engine has transformed a message, it is sent back to
Exchange Online over the tenant's inbound connector (typically
``<domain>.mail.protection.outlook.com``). The original envelope sender and
recipients are preserved so replies, bounces and threading keep working.
"""

from __future__ import annotations

import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import aiosmtplib

from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.mailer.processor import ProcessedMail
from app.models.tenant import Tenant


def build_message(mail: ProcessedMail, settings: Settings) -> EmailMessage:
    """Build a standards-compliant MIME message from a processed mail."""
    msg = EmailMessage()
    msg["From"] = mail.from_upn
    if mail.to:
        msg["To"] = ", ".join(mail.to)
    if mail.cc:
        msg["Cc"] = ", ".join(mail.cc)
    msg["Subject"] = mail.subject or ""
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = mail.message_id or make_msgid()
    if mail.reply_to:
        msg["Reply-To"] = ", ".join(mail.reply_to)
    msg["MIME-Version"] = "1.0"
    msg[settings.smtp_processed_header] = "yes"

    if mail.text_body is not None:
        msg.set_content(mail.text_body)
        if mail.html_body is not None:
            msg.add_alternative(mail.html_body, subtype="html")
    elif mail.html_body is not None:
        msg.add_alternative(mail.html_body, subtype="html")
    else:
        msg.set_content("")

    for attachment in mail.attachments:
        maintype, _, subtype = attachment.content_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        kwargs: dict[str, str] = {"maintype": maintype, "subtype": subtype}
        if attachment.content_id:
            kwargs["disposition"] = "inline"
        else:
            kwargs["filename"] = attachment.filename
        msg.add_attachment(attachment.content_bytes, **kwargs)
        if attachment.content_id:
            # ``add_attachment`` does not expose Content-ID directly; set it
            # on the last appended MIME part.
            payload = msg.get_payload()
            if isinstance(payload, list) and payload:
                last = payload[-1]
                last["Content-ID"] = f"<{attachment.content_id}>"

    return msg


async def _deliver(
    settings: Settings,
    host: str,
    sender: str,
    recipients: list[str],
    message: EmailMessage | bytes,
) -> None:
    """Low-level SMTP delivery to the M365 inbound connector."""
    tls_context: ssl.SSLContext | None = None
    if not settings.smtp_outbound_tls_verify:
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.CERT_NONE

    await aiosmtplib.send(
        message,
        hostname=host,
        port=settings.smtp_outbound_port,
        sender=sender,
        recipients=recipients,
        start_tls=settings.smtp_outbound_starttls,
        username=settings.smtp_outbound_username,
        password=settings.smtp_outbound_password,
        validate_certs=settings.smtp_outbound_tls_verify,
        tls_context=tls_context,
        timeout=30,
    )


def _outbound_host(tenant: Tenant | None, settings: Settings) -> str:
    host = (
        tenant.settings.get("inbound_connector_host")
        if tenant is not None
        else None
    ) or settings.smtp_outbound_default_host
    if not host:
        raise ValidationError(
            "No inbound connector host configured (tenant setting or SMTP_OUTBOUND_DEFAULT_HOST).",
            code="inbound_connector_missing",
        )
    return str(host)


async def send_processed_mail(
    tenant: Tenant,
    mail: ProcessedMail,
    settings: Settings,
    recipients: list[str] | None = None,
) -> None:
    """Send a processed message back to Exchange Online via SMTP.

    The target host is taken from ``tenant.settings["inbound_connector_host"]``
    with ``SMTP_OUTBOUND_DEFAULT_HOST`` as platform fallback.

    ``recipients`` must be the original SMTP envelope recipients (RCPT TO);
    they can differ from the To/Cc headers (BCC, redirects). Only when no
    envelope is available (e.g. the polling mail flow) are the header
    addresses used as a fallback.
    """
    host = _outbound_host(tenant, settings)
    message = build_message(mail, settings)
    if recipients is None:
        recipients = mail.to + mail.cc + mail.bcc
    await _deliver(settings, host, mail.from_upn, recipients, message)


async def send_raw_message(
    settings: Settings,
    *,
    sender: str,
    recipients: list[str],
    raw: bytes,
    tenant: Tenant | None = None,
) -> None:
    """Relay an unmodified message to Exchange Online (fail-safe pass-through).

    Used whenever the signature pipeline cannot or must not touch a message
    (unknown sender, no matching rule, processing error) so the mail flow
    is never interrupted by the signature hop.
    """
    host = _outbound_host(tenant, settings)
    await _deliver(settings, host, sender, recipients, raw)
