"""Unit tests for the SMTP outbound message builder."""

from app.config.settings import Settings
from app.mailer.processor import Attachment, ProcessedMail
from app.mailer.smtp_client import build_message


def _mail() -> ProcessedMail:
    return ProcessedMail(
        from_upn="user@example.com",
        subject="Hello",
        to=["recipient@example.org"],
        cc=["cc@example.org"],
        html_body="<p>Hi</p><p>Signature</p>",
        text_body="Hi\n\nSignature",
        attachments=[
            Attachment(
                filename="logo.png",
                content_type="image/png",
                content_bytes=b"png-bytes",
                content_id="logo1",
            ),
            Attachment(
                filename="report.pdf",
                content_type="application/pdf",
                content_bytes=b"pdf-bytes",
            ),
        ],
        message_id="<abc@example.com>",
        reply_to=["reply@example.com"],
    )


def test_build_message_sets_headers_and_processed_marker() -> None:
    settings = Settings(smtp_processed_header="X-Test-Processed")
    msg = build_message(_mail(), settings)

    assert msg["From"] == "user@example.com"
    assert msg["To"] == "recipient@example.org"
    assert msg["Cc"] == "cc@example.org"
    assert msg["Subject"] == "Hello"
    assert msg["Message-ID"] == "<abc@example.com>"
    assert msg["Reply-To"] == "reply@example.com"
    assert msg["X-Test-Processed"] == "yes"


def test_build_message_contains_both_bodies_and_attachments() -> None:
    settings = Settings()
    msg = build_message(_mail(), settings)
    payload = msg.get_payload()
    assert isinstance(payload, list)

    alternative = payload[0]
    assert alternative.get_content_type() == "multipart/alternative"
    parts = alternative.get_payload()
    assert isinstance(parts, list)
    assert parts[0].get_content_type() == "text/plain"
    assert parts[1].get_content_type() == "text/html"

    attachment_parts = payload[1:]
    assert len(attachment_parts) == 2
    assert attachment_parts[0].get_content_disposition() == "inline"
    assert attachment_parts[0]["Content-ID"] == "<logo1>"
    assert attachment_parts[1].get_filename() == "report.pdf"
