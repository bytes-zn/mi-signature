"""MIME mail processing: parse, modify, rebuild.

The processor reads a raw MIME message, extracts everything the delivery
layer needs (sender, recipients, bodies, attachments) and appends the
rendered signature to both the HTML and the plain-text body. Attachments,
inline images and all headers are preserved without loss.

Design note: the delivery happens via Graph ``sendMail`` which takes a
JSON message representation - so the processor's job is a faithful
MIME -> JSON mapping with the signature injected, not MIME reserialization.
"""

import base64
import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from typing import Any


@dataclass
class Attachment:
    """A MIME attachment (regular or inline image)."""

    filename: str
    content_type: str
    content_bytes: bytes
    content_id: str | None = None

    @property
    def is_inline(self) -> bool:
        return self.content_id is not None


@dataclass
class ProcessedMail:
    """The delivery-ready representation of a parsed message."""

    from_upn: str
    subject: str
    to: list[str]
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    html_body: str | None = None
    text_body: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    message_id: str | None = None
    reply_to: list[str] = field(default_factory=list)


def _collect_addresses(header_value: str | None) -> list[str]:
    if not header_value:
        return []
    return [addr for _, addr in getaddresses([header_value]) if addr]


# Markers that indicate the beginning of quoted reply/forward content in
# HTML bodies. The signature must be inserted before the earliest marker so
# it sits directly below the sender's fresh text instead of at the bottom of
# the whole thread.
_HTML_QUOTE_MARKERS = (
    'id="mail-editor-reference-message-container"',  # new Outlook / OWA
    "id='mail-editor-reference-message-container'",
    'id="divRplyFwdMsg"',  # classic OWA
    "id='divRplyFwdMsg'",
    'class="gmail_quote"',  # Gmail
    "class='gmail_quote'",
    'class="moz-cite-prefix"',  # Thunderbird
    "class='moz-cite-prefix'",
    "<blockquote",  # Apple Mail and most other clients
    "border-top:solid",  # Outlook desktop (Word HTML) divider
)

_TEXT_QUOTE_DELIMITERS = (
    "-----original message-----",
    "-----ursprüngliche nachricht-----",
    "-----urspruengliche nachricht-----",
)
_TEXT_REPLY_HEADER = re.compile(r"^(am|on)\s.+(schrieb|wrote)\s*:\s*$", flags=re.IGNORECASE)

# OWA/Outlook place a divider (``<hr ...>``, optionally wrapped in a bare
# ``<div>``) between the fresh text and the quoted container. That divider
# belongs to the quote section, so the signature goes before it as well.
_HR_DIVIDER_BEFORE_QUOTE = re.compile(
    r"(?:<div\b[^>]*>\s*)?<hr\b[^>]*>(?:\s*</div>)?\s*$",
    flags=re.IGNORECASE,
)


def _find_quote_start_html(html_body: str) -> int | None:
    """Offset of the enclosing tag of the earliest quote marker, if any."""
    lowered = html_body.lower()
    starts: list[int] = []
    for marker in _HTML_QUOTE_MARKERS:
        idx = lowered.find(marker.lower())
        if idx == -1:
            continue
        tag_start = lowered.rfind("<", 0, idx)
        starts.append(tag_start if tag_start != -1 else idx)
    if not starts:
        return None
    start = min(starts)
    divider = _HR_DIVIDER_BEFORE_QUOTE.search(html_body[:start])
    if divider:
        start = divider.start()
    return start


def _find_quote_start_text(text_body: str) -> int | None:
    """Character offset of the first quoted line in a plain-text body."""
    offset = 0
    for line in text_body.splitlines(keepends=True):
        stripped = line.strip()
        lowered = stripped.lower()
        if (
            stripped.startswith(">")
            or lowered.startswith(_TEXT_QUOTE_DELIMITERS)
            or _TEXT_REPLY_HEADER.match(stripped)
        ):
            return offset
        offset += len(line)
    return None


def append_signature_html(html_body: str, signature_html: str) -> str:
    """Insert the signature after the fresh text of an HTML body.

    In replies/forwards the quoted thread (blockquote, Outlook reference
    container, ...) is detected and the signature goes before it; otherwise
    it is appended (before ``</body>`` if present).
    """
    quote_start = _find_quote_start_html(html_body)
    if quote_start is not None:
        return html_body[:quote_start] + signature_html + html_body[quote_start:]
    match = re.search(r"</body\s*>", html_body, flags=re.IGNORECASE)
    if match:
        return html_body[: match.start()] + signature_html + html_body[match.start() :]
    return html_body + signature_html


def append_signature_text(text_body: str, signature_text: str) -> str:
    """Insert the signature after the fresh text of a plain-text body."""
    quote_start = _find_quote_start_text(text_body)
    if quote_start is not None:
        head, tail = text_body[:quote_start], text_body[quote_start:]
        if head.endswith("\n\n"):
            separator = ""
        elif head.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
        return head + separator + signature_text + "\n\n" + tail
    separator = "\n\n" if not text_body.endswith("\n") else "\n"
    return text_body + separator + signature_text


def process_mime(raw: bytes, signature_html: str, signature_text: str) -> ProcessedMail:
    """Parse a raw MIME message and append the signature to its bodies.

    Raises:
        ValueError: if the message has no From header.
    """
    message = BytesParser(policy=policy.default).parsebytes(raw)

    from_upn = parseaddr(message.get("From", ""))[1]
    if not from_upn:
        raise ValueError("Message has no usable From header.")

    result = ProcessedMail(
        from_upn=from_upn.lower(),
        subject=str(message.get("Subject", "")),
        to=[a.lower() for a in _collect_addresses(message.get("To"))],
        cc=[a.lower() for a in _collect_addresses(message.get("Cc"))],
        bcc=[a.lower() for a in _collect_addresses(message.get("Bcc"))],
        message_id=message.get("Message-ID"),
        reply_to=[a.lower() for a in _collect_addresses(message.get("Reply-To"))],
    )

    for part in message.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()

        if content_type == "text/html" and disposition != "attachment":
            charset = part.get_content_charset() or "utf-8"
            result.html_body = append_signature_html(
                part.get_payload(decode=True).decode(charset, errors="replace"),  # type: ignore[union-attr]
                signature_html,
            )
        elif content_type == "text/plain" and disposition != "attachment":
            charset = part.get_content_charset() or "utf-8"
            result.text_body = append_signature_text(
                part.get_payload(decode=True).decode(charset, errors="replace"),  # type: ignore[union-attr]
                signature_text,
            )
        else:
            payload = part.get_payload(decode=True)
            if payload is None or not isinstance(payload, bytes):
                continue
            content_id = part.get("Content-ID")
            if content_id:
                content_id = content_id.strip("<>")
            filename = part.get_filename() or content_id or "attachment"
            result.attachments.append(
                Attachment(
                    filename=filename,
                    content_type=content_type,
                    content_bytes=payload,
                    content_id=content_id,
                )
            )

    return result


def build_sendmail_body(mail: ProcessedMail) -> dict[str, Any]:
    """Build the Graph ``sendMail`` JSON payload for a processed message."""

    def recipients(addresses: list[str]) -> list[dict[str, Any]]:
        return [{"emailAddress": {"address": a}} for a in addresses]

    message: dict[str, Any] = {
        "subject": mail.subject,
        "toRecipients": recipients(mail.to),
        "ccRecipients": recipients(mail.cc),
        "bccRecipients": recipients(mail.bcc),
    }
    if mail.html_body is not None:
        message["body"] = {"contentType": "HTML", "content": mail.html_body}
    elif mail.text_body is not None:
        message["body"] = {"contentType": "Text", "content": mail.text_body}

    attachments = []
    for attachment in mail.attachments:
        entry: dict[str, Any] = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": attachment.filename,
            "contentType": attachment.content_type,
            "contentBytes": base64.b64encode(attachment.content_bytes).decode(),
        }
        if attachment.content_id:
            entry["contentId"] = attachment.content_id
            entry["isInline"] = True
        attachments.append(entry)
    if attachments:
        message["attachments"] = attachments

    return {"message": message, "saveToSentItems": True}
