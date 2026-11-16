"""Tests for the production baseline: the app must not start insecure."""

import pytest
from pydantic import ValidationError

from app.config.settings import Settings

_STRONG_OPERATOR_KEY = "operator-key-with-at-least-32-characters"
_STRONG_ENCRYPTION_KEY = "c2VjcmV0LWVuY3J5cHRpb24ta2V5LWZvci10ZXN0cy1vbmx5IQ=="


def _production_settings(**overrides: object) -> Settings:
    """Return a production configuration that passes the baseline."""
    base: dict[str, object] = {
        "environment": "production",
        "operator_api_key": _STRONG_OPERATOR_KEY,
        "secret_encryption_key": _STRONG_ENCRYPTION_KEY,
        "smtp_allowed_hosts": "40.92.0.0/15",
        "smtp_inbound_require_tls": True,
        "debug": False,
        "smtp_outbound_tls_verify": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_valid_production_configuration_starts() -> None:
    settings = _production_settings()
    assert settings.production_problems() == []


def test_default_operator_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="OPERATOR_API_KEY"):
        _production_settings(operator_api_key="dev-operator-key")


def test_short_operator_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="OPERATOR_API_KEY"):
        _production_settings(operator_api_key="too-short")


def test_missing_encryption_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SECRET_ENCRYPTION_KEY"):
        _production_settings(secret_encryption_key=None)


def test_empty_smtp_allow_list_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SMTP_ALLOWED_HOSTS"):
        _production_settings(smtp_allowed_hosts=None)


def test_disabled_tls_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SMTP_INBOUND_REQUIRE_TLS"):
        _production_settings(smtp_inbound_require_tls=False)


def test_debug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="DEBUG"):
        _production_settings(debug=True)


def test_disabled_outbound_certificate_check_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SMTP_OUTBOUND_TLS_VERIFY"):
        _production_settings(smtp_outbound_tls_verify=False)


def test_smtp_server_without_certificate_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SMTP_INBOUND_TLS_CERTFILE"):
        _production_settings(smtp_inbound_enabled=True)


def test_missing_relay_hostname_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SMTP_RELAY_HOSTNAME"):
        _production_settings(smtp_inbound_enabled=True, smtp_relay_hostname=None)


def test_development_configuration_starts_with_defaults() -> None:
    settings = Settings(environment="development", operator_api_key="dev-operator-key")
    assert settings.environment == "development"


def test_trusted_host_list_is_parsed() -> None:
    settings = Settings(trusted_hosts="api.example.com, mail.example.com ,")
    assert settings.trusted_host_list == ["api.example.com", "mail.example.com"]
