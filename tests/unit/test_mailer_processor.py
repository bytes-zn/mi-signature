"""Tests for the MIME processor."""

import base64

from app.mailer.processor import (
    append_signature_html,
    append_signature_text,
    build_sendmail_body,
    process_mime,
)

SIMPLE_MIME = b"""From: Nico Zeier <zeier@androidhell.de>
To: Empfaenger <ziel@example.com>, zweiter@example.com
Cc: kopie@example.com
Subject: Testbetreff
Message-ID: <abc123@androidhell.de>
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><body><p>Hallo Welt</p></body></html>
"""

MULTIPART_MIME = (
    b"From: Max <max@example.com>\r\n"
    b"To: ziel@example.com\r\n"
    b"Subject: Multipart\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: multipart/alternative; boundary=ALT\r\n"
    b"\r\n"
    b"--ALT\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Plain Version\r\n"
    b"--ALT\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"<html><body><b>HTML Version</b></body></html>\r\n"
    b"--ALT--\r\n"
)

ATTACHMENT_MIME = (
    b"From: Max <max@example.com>\r\n"
    b"To: ziel@example.com\r\n"
    b"Subject: Mit Anhang\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: multipart/mixed; boundary=MIX\r\n"
    b"\r\n"
    b"--MIX\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"<html><body>Siehe Anhang</body></html>\r\n"
    b"--MIX\r\n"
    b"Content-Type: application/pdf; name=report.pdf\r\n"
    b"Content-Disposition: attachment; filename=report.pdf\r\n"
    b"Content-Transfer-Encoding: base64\r\n"
    b"\r\n" + base64.b64encode(b"%PDF-fake-content") + b"\r\n"
    b"--MIX--\r\n"
)


def test_simple_html_message() -> None:
    result = process_mime(SIMPLE_MIME, "<hr><b>SIGNATUR</b>", "-- SIG")

    assert result.from_upn == "zeier@androidhell.de"
    assert result.subject == "Testbetreff"
    assert result.to == ["ziel@example.com", "zweiter@example.com"]
    assert result.cc == ["kopie@example.com"]
    assert result.message_id == "<abc123@androidhell.de>"
    assert "<p>Hallo Welt</p><hr><b>SIGNATUR</b></body>" in result.html_body
    assert result.attachments == []


def test_multipart_alternative_both_bodies_signed() -> None:
    result = process_mime(MULTIPART_MIME, "<hr>HTMLSIG", "TEXTSIG")

    assert result.html_body is not None and "HTML Version</b><hr>HTMLSIG" in result.html_body
    assert result.text_body is not None and result.text_body.endswith("TEXTSIG")
    assert "Plain Version" in result.text_body


def test_attachment_preserved() -> None:
    result = process_mime(ATTACHMENT_MIME, "<hr>SIG", "SIG")

    assert len(result.attachments) == 1
    attachment = result.attachments[0]
    assert attachment.filename == "report.pdf"
    assert attachment.content_type == "application/pdf"
    assert attachment.content_bytes == b"%PDF-fake-content"
    assert not attachment.is_inline


def test_sendmail_body_structure() -> None:
    result = process_mime(SIMPLE_MIME, "<hr>SIG", "SIG")
    body = build_sendmail_body(result)

    message = body["message"]
    assert message["subject"] == "Testbetreff"
    assert message["toRecipients"][0]["emailAddress"]["address"] == "ziel@example.com"
    assert message["body"]["contentType"] == "HTML"
    assert "SIG" in message["body"]["content"]


def test_missing_from_raises() -> None:
    raw = b"To: x@example.com\r\nSubject: kein Absender\r\n\r\nHallo"
    try:
        process_mime(raw, "x", "x")
        raise AssertionError("should have raised")
    except ValueError:
        pass


def test_append_signature_variants() -> None:
    assert append_signature_html("<p>x</p>", "<b>sig</b>") == "<p>x</p><b>sig</b>"
    assert (
        append_signature_html("<html><body>x</BODY></html>", "SIG")
        == "<html><body>xSIG</BODY></html>"
    )
    assert append_signature_text("Hallo", "SIG") == "Hallo\n\nSIG"
    assert append_signature_text("Hallo\n", "SIG") == "Hallo\n\nSIG"


def test_append_signature_html_before_blockquote() -> None:
    body = "<html><body><p>Neue Nachricht</p><blockquote><p>Alt</p></blockquote></body></html>"
    result = append_signature_html(body, "SIG")
    assert result.index("Neue Nachricht") < result.index("SIG") < result.index("<blockquote")


def test_append_signature_html_before_outlook_reference_container() -> None:
    body = (
        '<html><body><div>Neu</div>'
        '<div id="mail-editor-reference-message-container"><div>Verlauf</div></div>'
        "</body></html>"
    )
    result = append_signature_html(body, "SIG")
    assert result.index("SIG") < result.index('id="mail-editor-reference-message-container"')


def test_append_signature_html_before_gmail_quote_and_outlook_divider() -> None:
    gmail = '<div>Neu</div><div class="gmail_quote">Zitat</div>'
    assert append_signature_html(gmail, "SIG").index("SIG") < gmail.index("gmail_quote")
    divider = '<div>Neu</div><div style="border:none;border-top:solid #E1E1E1 1.0pt">Alt</div>'
    result = append_signature_html(divider, "SIG")
    assert result.index("SIG") < result.index("border-top:solid")


def test_append_signature_text_before_quoted_lines() -> None:
    body = "Meine Antwort\n\n> Alter Text\n> Noch älter\n"
    result = append_signature_text(body, "SIG")
    assert result == "Meine Antwort\n\nSIG\n\n> Alter Text\n> Noch älter\n"


def test_append_signature_text_before_original_message_delimiter() -> None:
    body = "Meine Antwort\n\n-----Ursprüngliche Nachricht-----\nVon: x@y.de\n"
    result = append_signature_text(body, "SIG")
    assert result.index("SIG") < result.index("-----Ursprüngliche Nachricht-----")


def test_append_signature_text_before_reply_header() -> None:
    body = "Meine Antwort\n\nOn Mon, 10 Aug 2026 10:33 Nico Zeier wrote:\n> Alt\n"
    result = append_signature_text(body, "SIG")
    assert result.index("SIG") < result.index("On Mon")


def test_append_signature_html_before_owa_hr_divider() -> None:
    body = (
        "<html><body><div>Neu</div>"
        '<hr style="display:inline-block;width:98%" tabindex="-1">'
        '<div id="divRplyFwdMsg"><p>Alt</p></div></body></html>'
    )
    result = append_signature_html(body, "SIG")
    assert result.index("Neu") < result.index("SIG") < result.index("<hr")
    assert result.index("<hr") < result.index('id="divRplyFwdMsg"')


def test_append_signature_html_before_div_wrapped_hr_divider() -> None:
    body = (
        "<div>Neu</div><div><hr></div>"
        '<div id="mail-editor-reference-message-container"><p>Alt</p></div>'
    )
    result = append_signature_html(body, "SIG")
    assert result.index("SIG") < result.index("<hr")
