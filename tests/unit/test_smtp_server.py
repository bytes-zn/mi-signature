"""Unit tests for the SMTP inbound server's security helpers."""

import pytest
from aiosmtpd.smtp import Envelope

from app.config.settings import Settings
from app.core.exceptions import ForbiddenError
from app.mailer.smtp_server import SignatureSMTPHandler, strip_auth_param


def test_allowed_host_accepts_configured_ip_and_network() -> None:
    handler = SignatureSMTPHandler(Settings(smtp_allowed_hosts="10.0.0.0/8, 192.168.1.10"))
    handler._check_allowed_host("10.20.30.40")
    handler._check_allowed_host("192.168.1.10")


def test_allowed_host_rejects_unknown_ip() -> None:
    handler = SignatureSMTPHandler(Settings(smtp_allowed_hosts="10.0.0.0/8"))
    with pytest.raises(ForbiddenError):
        handler._check_allowed_host("192.168.1.10")


def test_allowed_host_empty_list_allows_everything() -> None:
    handler = SignatureSMTPHandler(Settings(smtp_allowed_hosts=None))
    handler._check_allowed_host("203.0.113.7")


def test_local_delivery_detects_relay_hostname_recipient() -> None:
    handler = SignatureSMTPHandler(Settings(smtp_relay_hostname="relay.example.com"))
    envelope = Envelope()
    envelope.rcpt_tos.append("validation@relay.example.com")
    assert handler._is_local_delivery(envelope) is True


def test_local_delivery_ignores_other_domains_and_unset_hostname() -> None:
    envelope = Envelope()
    envelope.rcpt_tos.append("user@example.org")
    handler = SignatureSMTPHandler(Settings(smtp_relay_hostname="relay.example.com"))
    assert handler._is_local_delivery(envelope) is False
    handler = SignatureSMTPHandler(Settings(smtp_relay_hostname=None))
    assert handler._is_local_delivery(envelope) is False


def test_strip_auth_param_removes_exchange_auth_parameter() -> None:
    arg = "FROM:<zeier@androidhell.de> SIZE=41106 AUTH=<>"
    assert strip_auth_param(arg) == "FROM:<zeier@androidhell.de> SIZE=41106"


def test_strip_auth_param_keeps_plain_arguments_untouched() -> None:
    arg = "FROM:<zeier@androidhell.de> SIZE=100 BODY=8BITMIME"
    assert strip_auth_param(arg) == arg
