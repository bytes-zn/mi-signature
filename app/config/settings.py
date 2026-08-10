"""Central application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the application.

    All values can be overridden via environment variables (case-insensitive)
    or a local ``.env`` file. Secrets must never be hardcoded here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Bytes Signature Service"
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://signature:signature@localhost:5432/signature"
    redis_url: str = "redis://localhost:6379/0"

    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Platform operator key for tenant management endpoints.
    # MUST be overridden via environment in non-development environments.
    operator_api_key: str = "dev-operator-key"

    # Microsoft Entra ID fallback credentials (used when a tenant record
    # carries no own credentials; mainly for development).
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    entra_client_secret: str | None = None

    # Graph sync: cache TTL and optional scheduled-sync interval (0 = off).
    graph_cache_ttl_seconds: int = 3600
    graph_sync_interval_minutes: int = 0

    # Mail flow: interception mailbox (UPN) and poll interval (0 = off).
    interception_mailbox_upn: str | None = None
    mail_poll_interval_seconds: int = 0

    # Resend (relay) outbound - platform default API key (tenants can override).
    resend_api_key: str | None = None

    # SMTP inbound server: receives mail from the M365 outbound connector.
    smtp_inbound_enabled: bool = False
    smtp_inbound_host: str = "0.0.0.0"
    smtp_inbound_port: int = 25
    smtp_inbound_tls_certfile: str | None = None
    smtp_inbound_tls_keyfile: str | None = None
    smtp_inbound_require_tls: bool = True
    # Public hostname of this relay (e.g. "relay.example.com"). Mail addressed
    # to any mailbox at this hostname is accepted and discarded - used for the
    # Microsoft connector validation e-mail.
    smtp_relay_hostname: str | None = None
    # Comma-separated source IPs/CIDRs allowed to talk to the inbound SMTP
    # server (typically the Exchange Online egress ranges of the tenant).
    # None = allow all (only for local testing, never in production).
    smtp_allowed_hosts: str | None = None

    # SMTP outbound client: sends processed mail to the M365 inbound connector.
    # Tenant-specific hosts can be stored in tenant.settings["inbound_connector_host"].
    smtp_outbound_default_host: str | None = None
    smtp_outbound_port: int = 25
    smtp_outbound_starttls: bool = True
    smtp_outbound_username: str | None = None
    smtp_outbound_password: str | None = None
    smtp_outbound_tls_verify: bool = True
    # Header written by the platform after processing; used to avoid loops.
    smtp_processed_header: str = "X-Bytes-Signature-Processed"

    @property
    def resolved_celery_broker_url(self) -> str:
        """Celery broker URL, derived from Redis when not set explicitly."""
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        """Celery result backend, derived from Redis when not set explicitly."""
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""
    return Settings()
