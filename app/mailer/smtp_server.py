"""SMTP inbound server: receives mail from the M365 outbound connector.

Microsoft 365 routes outbound messages matching the transport rule to this
server (smart host). The server validates the connecting host, resolves the
tenant from the envelope sender domain, runs the signature/campaign pipeline
and hands the result to :mod:`app.mailer.smtp_client` for delivery back to
Exchange Online via the tenant's inbound connector.
"""

from __future__ import annotations

import ipaddress
import re
import signal
import ssl
import threading
from email import policy as email_policy
from email.parser import BytesParser

import structlog
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP as SMTPServer
from aiosmtpd.smtp import Envelope
from aiosmtpd.smtp import Session as SMTPSession
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config.settings import Settings, get_settings
from app.core.exceptions import AppError, ForbiddenError
from app.database.session import build_engine, build_session_factory
from app.logging.setup import configure_logging
from app.mailer.service import MailProcessingService, SkipMessage
from app.mailer.smtp_client import (
    DeliveryDeferred,
    DeliveryRejected,
    DeliveryUncertain,
    send_processed_mail,
    send_raw_message,
)
from app.models.tenant import Tenant
from app.tenants.repository import TenantRepository

logger = structlog.get_logger(__name__)

MAX_MESSAGE_SIZE = 50 * 1024 * 1024

_AUTH_PARAM = re.compile(r"\s+AUTH=\S*", flags=re.IGNORECASE)


def strip_auth_param(arg: str) -> str:
    """Remove the RFC 4954 ``AUTH`` parameter from a ``MAIL FROM`` argument.

    Exchange Online appends ``AUTH=<>`` on anonymously received messages.
    aiosmtpd only supports AUTH in the submission sense and would reject the
    command with ``555 MAIL FROM parameters not recognized or not
    implemented`` - so the parameter is dropped before parsing.
    """
    return _AUTH_PARAM.sub("", arg)


def has_processed_header(raw: bytes, header_name: str) -> bool:
    """True when the top-level headers of the message carry the marker.

    Only the headers are inspected. A byte search over the whole message
    would also match a quoted or forwarded mail in the body and would drop
    that message silently.
    """
    try:
        message = BytesParser(policy=email_policy.default).parsebytes(raw)
    except Exception:  # noqa: BLE001 - broken message, do not drop it
        logger.warning("smtp message could not be parsed, skipping loop check")
        return False
    return any(name.lower() == header_name.lower() for name in message.keys())


class TolerantSMTP(SMTPServer):
    """SMTP protocol that tolerates Exchange Online's ``AUTH=<>`` parameter."""

    async def smtp_MAIL(self, arg: str | None) -> None:
        if arg is not None:
            arg = strip_auth_param(arg)
        await super().smtp_MAIL(arg)


class SignatureController(Controller):
    """Controller that instantiates :class:`TolerantSMTP` per connection."""

    def factory(self) -> TolerantSMTP:
        return TolerantSMTP(self.handler, **self.SMTP_kwargs)


class SignatureSMTPHandler:
    """aiosmtpd handler that plugs into the signature mail-flow pipeline."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        """Lazy engine/session factory (bound to the SMTP worker thread's loop)."""
        if self._session_factory is None:
            self._engine = build_engine(self._settings)
            self._session_factory = build_session_factory(self._engine)
        return self._session_factory

    async def handle_MAIL(
        self,
        server: SMTPServer,
        session: SMTPSession,
        envelope: Envelope,
        address: str,
        mail_options: list[str],
    ) -> str:
        envelope.mail_from = address.lower()
        envelope.mail_options.extend(mail_options)
        return "250 OK"

    async def handle_RCPT(
        self,
        server: SMTPServer,
        session: SMTPSession,
        envelope: Envelope,
        address: str,
        rcpt_options: list[str],
    ) -> str:
        if not address or "@" not in address:
            return "550 Invalid recipient address"
        envelope.rcpt_tos.append(address.lower())
        return "250 OK"

    async def handle_DATA(
        self,
        server: SMTPServer,
        session: SMTPSession,
        envelope: Envelope,
    ) -> str:
        peer = self._peer_host(session)
        mail_from = (envelope.mail_from or "").lower()
        try:
            self._check_allowed_host(peer)
            if self._is_local_delivery(envelope):
                # Validation/system mail addressed at the relay hostname
                # itself (e.g. the Microsoft connector validation e-mail):
                # accept and discard.
                logger.info(
                    "smtp local delivery accepted",
                    peer=peer,
                    sender=mail_from,
                    recipients=envelope.rcpt_tos,
                )
                return "250 OK"

            content = envelope.content
            if not isinstance(content, bytes):
                # The server runs with decode_data=False, so the content is
                # always raw bytes. Anything else cannot be relayed.
                logger.error("smtp message content is not raw data", peer=peer, sender=mail_from)
                return "451 Temporary local problem, please try later"
            raw = content
            if has_processed_header(raw, self._settings.smtp_processed_header):
                # Loop protection: an already-signed message must never be
                # processed again. Dropping breaks the loop.
                logger.info("smtp message already processed, dropping", peer=peer, sender=mail_from)
                return "250 OK"

            domain = mail_from.split("@", 1)[1] if "@" in mail_from else ""
            tenant = await self._resolve_tenant(domain)

            if tenant is not None:
                try:
                    async with self._sessions()() as db_session:
                        service = MailProcessingService(db_session, self._settings)
                        processed = await service.process_bytes(tenant, raw)
                        await send_processed_mail(
                            tenant,
                            processed,
                            self._settings,
                            recipients=list(envelope.rcpt_tos),
                        )
                    logger.info(
                        "smtp message processed and delivered",
                        peer=peer,
                        sender=mail_from,
                        tenant_id=str(tenant.id),
                        recipients=len(envelope.rcpt_tos),
                    )
                    return "250 Message accepted for delivery"
                except SkipMessage as exc:
                    logger.info(
                        "smtp no signature applied, relaying unchanged",
                        peer=peer,
                        sender=mail_from,
                        reason=str(exc),
                    )
                except DeliveryUncertain as exc:
                    # The message may already have been accepted by Exchange.
                    # Relaying the original as well would deliver it twice.
                    logger.warning(
                        "smtp delivery outcome uncertain, requesting retry",
                        peer=peer,
                        sender=mail_from,
                        error=str(exc),
                    )
                    return "451 Temporary local problem, please try later"
                except DeliveryDeferred as exc:
                    logger.warning(
                        "smtp delivery deferred, requesting retry",
                        peer=peer,
                        sender=mail_from,
                        error=str(exc),
                    )
                    return "451 Temporary local problem, please try later"
                except DeliveryRejected as exc:
                    # The signed copy was refused (e.g. too large). The
                    # original may still be accepted.
                    logger.warning(
                        "smtp signed mail rejected, relaying original",
                        peer=peer,
                        sender=mail_from,
                        error=str(exc),
                    )
                except Exception:
                    logger.exception(
                        "smtp processing failed, relaying unchanged",
                        peer=peer,
                        sender=mail_from,
                    )
            else:
                logger.warning(
                    "smtp sender domain not configured, relaying unchanged",
                    peer=peer,
                    sender=mail_from,
                )

            # Fail-safe pass-through: the signature hop must never interrupt
            # the mail flow, so anything we could not sign is relayed as-is.
            await send_raw_message(
                self._settings,
                sender=mail_from,
                recipients=list(envelope.rcpt_tos),
                raw=raw,
                tenant=tenant,
            )
            return "250 Message accepted for delivery"
        except ForbiddenError as exc:
            logger.warning("smtp host rejected", peer=peer, sender=mail_from, reason=exc.message)
            return "550 Relay access denied"
        except AppError as exc:
            logger.warning(
                "smtp processing error",
                peer=peer,
                sender=mail_from,
                code=exc.code,
                error=exc.message,
            )
            return f"550 {exc.message}"
        except DeliveryUncertain as exc:
            logger.warning(
                "smtp delivery outcome uncertain, requesting retry",
                peer=peer,
                sender=mail_from,
                error=str(exc),
            )
            return "451 Temporary local problem, please try later"
        except DeliveryDeferred as exc:
            logger.warning(
                "smtp delivery deferred, requesting retry",
                peer=peer,
                sender=mail_from,
                error=str(exc),
            )
            return "451 Temporary local problem, please try later"
        except DeliveryRejected as exc:
            logger.warning(
                "smtp message rejected by the receiving server",
                peer=peer,
                sender=mail_from,
                error=str(exc),
            )
            return "550 Message rejected by the receiving server"
        except Exception:
            logger.exception("smtp unexpected processing error", peer=peer, sender=mail_from)
            return "451 Temporary local problem, please try later"

    async def _resolve_tenant(self, domain: str) -> Tenant | None:
        if not domain:
            return None
        async with self._sessions()() as db_session:
            repo = TenantRepository(db_session)
            return await repo.find_active_by_domain(domain)

    def _is_local_delivery(self, envelope: Envelope) -> bool:
        """True when any recipient lives at the relay hostname itself."""
        relay = self._settings.smtp_relay_hostname
        if not relay:
            return False
        relay = relay.lower()
        return any("@" in rcpt and rcpt.split("@", 1)[1] == relay for rcpt in envelope.rcpt_tos)

    def _check_allowed_host(self, peer: str) -> None:
        configured = self._settings.smtp_allowed_hosts
        if not configured:
            return
        try:
            ip = ipaddress.ip_address(peer)
        except ValueError as exc:
            raise ForbiddenError("Invalid peer address") from exc

        for entry in configured.split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                if "/" in entry:
                    if ip in ipaddress.ip_network(entry, strict=False):
                        return
                elif ip == ipaddress.ip_address(entry):
                    return
            except ValueError:
                continue
        raise ForbiddenError(f"Host {peer} is not in the allow-list")

    @staticmethod
    def _peer_host(session: SMTPSession) -> str:
        peer = session.peer
        if isinstance(peer, tuple) and peer:
            return str(peer[0])
        return "unknown"


def build_tls_context(settings: Settings) -> ssl.SSLContext | None:
    """Build the STARTTLS context when certificate and key are configured."""
    if not settings.smtp_inbound_tls_certfile or not settings.smtp_inbound_tls_keyfile:
        return None
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(settings.smtp_inbound_tls_certfile, settings.smtp_inbound_tls_keyfile)
    return context


def create_controller(settings: Settings) -> Controller:
    """Create the aiosmtpd controller for the inbound SMTP server."""
    tls_context = build_tls_context(settings)
    if settings.smtp_inbound_require_tls and tls_context is None:
        raise RuntimeError(
            "SMTP_INBOUND_REQUIRE_TLS=true requires SMTP_INBOUND_TLS_CERTFILE and "
            "SMTP_INBOUND_TLS_KEYFILE to be configured."
        )
    handler = SignatureSMTPHandler(settings)
    return SignatureController(
        handler,
        hostname=settings.smtp_inbound_host,
        port=settings.smtp_inbound_port,
        tls_context=tls_context,
        require_starttls=settings.smtp_inbound_require_tls,
        decode_data=False,
        data_size_limit=MAX_MESSAGE_SIZE,
    )


def main() -> None:
    """Entry point: configure logging and run the SMTP server."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    controller = create_controller(settings)
    controller.start()
    logger.info(
        "smtp inbound server started",
        host=settings.smtp_inbound_host,
        port=settings.smtp_inbound_port,
        tls=settings.smtp_inbound_require_tls,
        allowed_hosts=bool(settings.smtp_allowed_hosts),
    )

    # The controller runs its own event loop in a worker thread; the main
    # thread only needs to stay alive until interrupted. SIGTERM is handled
    # explicitly so that a container stop closes the listener gracefully
    # instead of killing the process mid-transaction.
    stop_event = threading.Event()

    def _request_stop(signum: int, frame: object) -> None:  # noqa: ANN001, ARG001
        logger.info("smtp shutdown requested", signal=signum)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _request_stop)
        except (ValueError, OSError):
            # Not the main thread (e.g. under a test runner) - ignore.
            pass

    try:
        while not stop_event.wait(timeout=1.0):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        logger.info("smtp inbound server stopped")


if __name__ == "__main__":
    main()
