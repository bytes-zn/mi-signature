"""Central application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Well-known development key. Production start-up validation rejects it.
DEFAULT_OPERATOR_API_KEY = "dev-operator-key"

#: Minimum length accepted for the operator key in production.
MIN_OPERATOR_KEY_LENGTH = 32


class Settings(BaseSettings):
    """Runtime configuration for the application.

    All values can be overridden via environment variables (case-insensitive)
    or a local ``.env`` file. Secrets must never be hardcoded here.

    In ``ENVIRONMENT=production`` the constructor validates the security
    relevant options and refuses to start with an insecure configuration
    (default operator key, open SMTP relay, missing encryption key, ...).
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
    celery_task_time_limit: int = 900
    celery_result_expires: int = 3600

    # Platform operator key for tenant management endpoints.
    # MUST be overridden via environment in non-development environments.
    operator_api_key: str = DEFAULT_OPERATOR_API_KEY

    # Master key for encrypting tenant secrets at rest (base64, 32 bytes).
    # Required in production; a stable development key is used otherwise.
    secret_encryption_key: str | None = None

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

    # API hardening.
    # Shared token required to read /metrics (empty = endpoint stays open).
    metrics_token: str | None = None
    # Comma-separated list of allowed Host headers (empty = allow all).
    trusted_hosts: str | None = None
    # Redirect plain HTTP to HTTPS (enable when a TLS terminator runs).
    https_redirect: bool = False
    # Serve the OpenAPI documentation (/docs, /openapi.json).
    api_docs_enabled: bool = True
    # Maximum accepted HTTP request body size in bytes.
    max_request_body_bytes: int = 10 * 1024 * 1024
    # Token-bucket rate limit per client (0 = disabled).
    api_rate_limit_per_minute: int = 120
    # Persist an audit trail for tenant and configuration changes.
    audit_log_enabled: bool = True

    @property
    def resolved_celery_broker_url(self) -> str:
        """Celery broker URL, derived from Redis when not set explicitly."""
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        """Celery result backend, derived from Redis when not set explicitly."""
        return self.celery_result_backend or self.redis_url

    @property
    def trusted_host_list(self) -> list[str]:
        """Parsed list of allowed Host headers."""
        if not self.trusted_hosts:
            return []
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    def production_problems(self) -> list[str]:
        """Return the list of security problems that block a production start.

        An empty list means the configuration is considered safe to run.
        """
        problems: list[str] = []

        if self.operator_api_key == DEFAULT_OPERATOR_API_KEY:
            problems.append(
                "OPERATOR_API_KEY still uses the well-known development value; "
                "generate a unique key (see 'make secrets')."
            )
        elif len(self.operator_api_key) < MIN_OPERATOR_KEY_LENGTH:
            problems.append(
                f"OPERATOR_API_KEY must be at least {MIN_OPERATOR_KEY_LENGTH} characters long."
            )

        if not self.secret_encryption_key:
            problems.append(
                "SECRET_ENCRYPTION_KEY is required to encrypt tenant secrets at rest "
                "(see 'make secrets')."
            )

        if not self.smtp_allowed_hosts:
            problems.append(
                "SMTP_ALLOWED_HOSTS must list the Exchange Online egress ranges; "
                "an empty value turns the relay into an open relay."
            )

        if not self.smtp_inbound_require_tls:
            problems.append("SMTP_INBOUND_REQUIRE_TLS must be true.")

        if self.debug:
            problems.append("DEBUG must be false in production.")

        if self.smtp_inbound_enabled:
            if not (self.smtp_inbound_tls_certfile and self.smtp_inbound_tls_keyfile):
                problems.append(
                    "SMTP_INBOUND_TLS_CERTFILE and SMTP_INBOUND_TLS_KEYFILE are required "
                    "when the SMTP inbound server is enabled."
                )
            if not self.smtp_relay_hostname:
                problems.append(
                    "SMTP_RELAY_HOSTNAME is required so that connector validation mails "
                    "can be discarded."
                )

        if self.smtp_outbound_tls_verify is False:
            problems.append("SMTP_OUTBOUND_TLS_VERIFY must be true.")

        return problems

    @model_validator(mode="after")
    def _enforce_production_baseline(self) -> "Settings":
        """Fail fast when a production deployment is misconfigured."""
        if self.environment != "production":
            return self
        problems = self.production_problems()
        if problems:
            joined = "\n  - ".join(problems)
            raise ValueError(f"Insecure production configuration:\n  - {joined}")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""
    return Settings()
