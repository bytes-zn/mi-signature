"""Resend integration: domain provisioning and outbound delivery.

Resend is the relay used to bypass the M365 outbounds-only pool reputation
problem - its infrastructure has well-established IPs that are accepted by
the recipient mail servers. Tenants provision their own sender domain via
the Resend Domains API; the platform returns the DNS records that must be
added at the tenant's DNS provider, then verifies and sends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import resend
from resend.domains._domains import Domains as _Domains
from resend.emails._emails import Emails as _Emails


@dataclass
class DnsRecord:
    """A DNS record that the tenant must add at their DNS provider."""

    type: str  # MX, TXT, CNAME, ...
    host: str
    value: str
    ttl: int | None = None
    priority: int | None = None


@dataclass
class DomainProvision:
    """Result of creating a domain in Resend."""

    id: str
    name: str
    status: str
    region: str
    records: list[DnsRecord] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Result of a domain verification request."""

    id: str
    name: str
    status: str  # verified | pending | failed
    dns_records: list[DnsRecord] = field(default_factory=list)


def _to_records(payload: Any) -> list[dict[str, Any]]:
    """Normalize a Resend records payload to a list of plain dicts."""
    if payload is None:
        return []
    return [dict(r) for r in payload]


class ResendClient:
    """Thin wrapper around the Resend API for our multi-tenant onboarding."""

    def __init__(self, api_key: str) -> None:
        resend.api_key = api_key

    # ---------------------------------------------------------- domain

    def create_domain(self, name: str, region: str = "us-east-1") -> DomainProvision:
        params: _Domains.CreateParams = {"name": name, "region": region}
        result = _Domains.create(params)
        return DomainProvision(
            id=str(result["id"]),
            name=str(result["name"]),
            status=str(result["status"]),
            region=region,
            records=[self._record_from(r) for r in _to_records(result.get("records"))],
        )

    def get_domain(self, domain_id: str) -> DomainProvision:
        result = resend.Domains.get(domain_id)
        return DomainProvision(
            id=str(result["id"]),
            name=str(result["name"]),
            status=str(result["status"]),
            region=str(result.get("region", "us-east-1")),
            records=[self._record_from(r) for r in _to_records(result.get("records"))],
        )

    def verify_domain(self, domain_id: str) -> VerificationResult:
        result = resend.Domains.verify(domain_id)
        return VerificationResult(
            id=str(result["id"]),
            name=str(result["name"]),
            status=str(result["status"]),
            dns_records=[self._record_from(r) for r in _to_records(result.get("records"))],
        )

    def delete_domain(self, domain_id: str) -> None:
        resend.Domains.remove(domain_id)

    # ---------------------------------------------------------- send

    def send_email(
        self,
        *,
        sender: str,
        to: list[str],
        subject: str,
        html: str | None = None,
        text: str | None = None,
        reply_to: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        params: dict[str, Any] = {
            "from": sender,
            "to": to,
            "subject": subject,
        }
        if html is not None:
            params["html"] = html
        if text is not None:
            params["text"] = text
        if reply_to:
            params["reply_to"] = reply_to[0] if len(reply_to) == 1 else reply_to
        if attachments:
            params["attachments"] = [
                {
                    "filename": att["filename"],
                    "content": att["content_bytes"],
                    "content_id": att.get("content_id"),
                }
                for att in attachments
            ]
        result = _Emails.send(params)  # type: ignore[arg-type]
        return str(result["id"])

    # ---------------------------------------------------------- helpers

    @staticmethod
    def _record_from(record: dict[str, Any]) -> DnsRecord:
        return DnsRecord(
            type=record.get("type", "") or record.get("record", ""),
            host=(record.get("name", "") or record.get("host", "") or record.get("record", "")),
            value=record.get("value", "") or record.get("data", ""),
            ttl=record.get("ttl"),
            priority=record.get("priority"),
        )
