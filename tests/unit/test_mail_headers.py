"""Tests for the MIME header handling of the mail pipeline.

Two properties matter for production:

* threading headers (``In-Reply-To``, ``References``) must survive the
  rebuild, otherwise replies no longer appear in the conversation,
* the loop protection must only look at the headers - a quoted mail in the
  body must never cause a message to be dropped.
"""

from app.config.settings import Settings
from app.mailer.processor import process_mime
from app.mailer.smtp_client import build_message
from app.mailer.smtp_server import has_processed_header

RAW_REPLY = b"""From: sender@example.com
To: recipient@example.org
Subject: Re: Hello
Message-ID: <child@example.com>
In-Reply-To: <parent@example.com>
References: <root@example.com> <parent@example.com>
Date: Mon, 01 Jan 2024 10:00:00 +0000
X-Custom-Trace: abc-123

Body text
"""


def test_process_mime_collects_threading_headers() -> None:
    mail = process_mime(RAW_REPLY, "<p>Signature</p>", "Signature")

    headers = dict(mail.headers)
    assert headers["In-Reply-To"] == "<parent@example.com>"
    assert headers["References"] == "<root@example.com> <parent@example.com>"
    assert headers["X-Custom-Trace"] == "abc-123"


def test_process_mime_drops_rebuilt_headers() -> None:
    mail = process_mime(RAW_REPLY, "<p>Signature</p>", "Signature")

    names = {name.lower() for name, _ in mail.headers}
    assert "from" not in names
    assert "to" not in names
    assert "subject" not in names
    assert "date" not in names
    assert "message-id" not in names


def test_build_message_preserves_threading_headers() -> None:
    mail = process_mime(RAW_REPLY, "<p>Signature</p>", "Signature")
    msg = build_message(mail, Settings())

    assert msg["In-Reply-To"] == "<parent@example.com>"
    assert msg["References"] == "<root@example.com> <parent@example.com>"
    assert msg["X-Custom-Trace"] == "abc-123"
    assert msg["Date"] == "Mon, 01 Jan 2024 10:00:00 +0000"


def test_build_message_neutralizes_header_injection() -> None:
    mail = process_mime(RAW_REPLY, "<p>Signature</p>", "Signature")
    mail.headers.append(("X-Evil", "value\r\nBcc: attacker@evil.test"))

    msg = build_message(mail, Settings())

    assert "\n" not in msg["X-Evil"]
    assert "\r" not in msg["X-Evil"]


def test_build_message_does_not_forward_the_bcc_header() -> None:
    raw = b"From: sender@example.com\nBcc: hidden@example.org\n\nbody"
    mail = process_mime(raw, "<p>Signature</p>", "Signature")

    msg = build_message(mail, Settings())

    assert msg.get_all("Bcc") is None


def test_processed_header_in_headers_triggers_loop_protection() -> None:
    raw = b"From: a@example.com\nX-Bytes-Signature-Processed: yes\n\nbody"

    assert has_processed_header(raw, "X-Bytes-Signature-Processed") is True


def test_processed_header_in_body_does_not_trigger_loop_protection() -> None:
    raw = (
        b"From: a@example.com\nSubject: Re: Hello\n\n"
        b"> X-Bytes-Signature-Processed: yes\n> some quoted mail\n"
    )

    assert has_processed_header(raw, "X-Bytes-Signature-Processed") is False


def test_processed_header_check_is_case_insensitive() -> None:
    raw = b"From: a@example.com\nx-bytes-signature-processed: yes\n\nbody"

    assert has_processed_header(raw, "X-Bytes-Signature-Processed") is True


def test_custom_marker_header_is_honoured() -> None:
    raw = b"From: a@example.com\nX-Custom-Processed: yes\n\nbody"

    assert has_processed_header(raw, "X-Custom-Processed") is True
    assert has_processed_header(raw, "X-Bytes-Signature-Processed") is False
