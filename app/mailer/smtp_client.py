"""SMTP delivery of processed mail back to Microsoft 365.

After the signature engine has transformed a message, it is sent back to
Exchange Online over the tenant's inbound connector (typically
``<domain>.mail.protection.outlook.com``). The original envelope sender and
recipients are preserved so that replies, bounces and threading keep working.

Delivery failures are classified so that the caller can decide whether a
fallback delivery is safe:

* :class:`DeliveryRejected` - the server definitively refused the message
  (5xx). The message was not accepted; a smaller original copy may still
  work, so the caller may fall back.
* :class:`DeliveryDeferred` - the server asked to try again later (4xx) or
  the connection could not be established. Nothing was accepted.
* :class:`DeliveryUncertain` - the connection broke while the message was
  in flight. The outcome is unknown, so the caller must **not** send a
  second copy; it has to ask the sender to retry instead.
"""

from __future__ import annotations

import ssl
from email.message import EmailMessage, Message
from email.utils import formatdate, make_msgid

import aiosmtplib

from app.config.settings import Settings
from app.core.exceptions import ValidationError
from app.mailer.processor import ProcessedMail
from app.models.tenant import Tenant


class DeliveryError(Exception):
    """Base class for classified delivery failures."""


class DeliveryRejected(DeliveryError):
    """The receiving server refused the message (permanent, 5xx)."""


class DeliveryDeferred(DeliveryError):
    """The receiving server asked for a retry (temporary, 4xx)."""


class DeliveryUncertain(DeliveryError):
    """The delivery outcome is unknown - the message may have been accepted."""


def _sanitize_header_value(value: str) -> str:
    """Strip line breaks from a header value.

    Header values are attacker controlled (they come from the incoming
    message). A stray CR/LF would allow additional headers to be injected
    into the rebuilt message.
    """
    return value.replace("\r", " ").replace("\n", " ")


def build_message(mail: ProcessedMail, settings: Settings) -> EmailMessage:
    """Build a standards-compliant MIME message from a processed mail."""
    msg = EmailMessage()

    # Headers of the original message that are not rebuilt (threading
    # headers such as In-Reply-To/References and custom X-* headers).
    for name, value in mail.headers:
        if name.lower() == settings.smtp_processed_header.lower():
            continue
        try:
            msg[name] = _sanitize_header_value(value)
        except (ValueError, TypeError):
            # Header name or value not accepted by the policy - skip it
            # instead of losing the whole signature.
            continue

    msg["From"] = _sanitize_header_value(mail.from_upn)
    if mail.to:
        msg["To"] = _sanitize_header_value(", ".join(mail.to))
    if mail.cc:
        msg["Cc"] = _sanitize_header_value(", ".join(mail.cc))
    msg["Subject"] = _sanitize_header_value(mail.subject or "")
    msg["Date"] = mail.date or formatdate(localtime=False)
    msg["Message-ID"] = _sanitize_header_value(mail.message_id or make_msgid())
    if mail.reply_to:
        msg["Reply-To"] = _sanitize_header_value(", ".join(mail.reply_to))
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
        if attachment.content_id:
            msg.add_attachment(
                attachment.content_bytes,
                maintype=maintype,
                subtype=subtype,
                disposition="inline",
            )
            # ``add_attachment`` does not expose Content-ID directly; set it
            # on the last appended MIME part.
            payload = msg.get_payload()
            if isinstance(payload, list) and payload:
                last = payload[-1]
                if isinstance(last, Message):
                    last["Content-ID"] = f"<{attachment.content_id}>"
        else:
            msg.add_attachment(
                attachment.content_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )

    return msg


async def _deliver(
    settings: Settings,
    host: str,
    sender: str,
    recipients: list[str],
    message: EmailMessage | bytes,
) -> None:
    """Low-level SMTP delivery to the M365 inbound connector.

    Raises:
        DeliveryRejected: the server refused the message (5xx).
        DeliveryDeferred: the server asked for a retry (4xx) or the
            connection could not be established.
        DeliveryUncertain: the connection broke in flight; the outcome of
            the delivery is unknown.
    """
    tls_context: ssl.SSLContext | None = None
    if not settings.smtp_outbound_tls_verify:
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.CERT_NONE

    try:
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
    except aiosmtplib.SMTPResponseException as exc:
        if exc.code >= 500:
            raise DeliveryRejected(f"{host} rejected the message: {exc}") from exc
        raise DeliveryDeferred(f"{host} asked for a retry: {exc}") from exc
    except aiosmtplib.SMTPConnectError as exc:
        raise DeliveryDeferred(f"Cannot connect to {host}: {exc}") from exc
    except (aiosmtplib.SMTPTimeoutError, aiosmtplib.SMTPServerDisconnected, OSError) as exc:
        raise DeliveryUncertain(f"Delivery to {host} was interrupted: {exc}") from exc


def _outbound_host(tenant: Tenant | None, settings: Settings) -> str:
    host = (
        tenant.settings.get("inbound_connector_host") if tenant is not None else None
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
