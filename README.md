# MI Signature (Bytes Signature Service)

Open-source, self-hosted platform for **server-side email signatures in
Microsoft 365** — an alternative to CodeTwo & Co., without client plugins and
without Outlook rules. The mail flows through the **Exchange Online connectors**
to your own server, where the signature and an optional campaign banner are
appended, and then it is delivered back to M365.

Pure REST API (no frontend), multi-tenant, clean architecture.

**Status:** Production-ready. End-to-end tested:
Outlook → M365 → Signature Server → M365 → external recipient, including
reply-safe signature placement.

## How It Works

```
┌─────────┐   1. Mail to external recipient
│ Outlook │
└────┬────┘
     ▼
┌─────────────────────────────────────────────────────────┐
│ Microsoft 365 (Exchange Online)                         │
│  Transport rule "Signature"  ──2──►  Outbound Connector │
└──────────────────────────────────────┬──────────────────┘
                                       ▼  SMTP + STARTTLS, Port 25
┌─────────────────────────────────────────────────────────┐
│ MI Signature (this server)                              │
│  3. Recognize tenant by sender domain                   │
│  4. Resolve user from directory (Graph sync)            │
│  5. Rule → select template, check campaign              │
│  6. Insert signature directly under the new text        │
│     (before the quoted history)                         │
└──────────────────────────────────────┬──────────────────┘
                                       ▼  SMTP + STARTTLS, Port 25
┌─────────────────────────────────────────────────────────┐
│ Microsoft 365 — Inbound Connector (Partner Organization)│
│  7. Delivery to the recipient                           │
└─────────────────────────────────────────────────────────┘
```

Key properties of the mail flow:

- **Fail-safe:** If a mail cannot be signed (unknown sender, no rule,
  processing error), it is **forwarded unchanged** — the mail flow is never
  interrupted.
- **Loop protection:** Signed mails carry the header
  `X-Bytes-Signature-Processed: yes`. The transport rule has an
  exception for this header; the server additionally discards duplicate
  incoming mails itself.
- **Reply-safe:** The signature is inserted before the quote block
  (recognized markers: new Outlook/OWA, classic OWA including `<hr>` separator,
  Outlook Desktop/Word-HTML, Gmail, Apple Mail, Thunderbird) — for new
  mails, as before, at the end.
- **Envelope-faithful:** SMTP recipients (RCPT TO) are taken over 1:1,
  BCC and redirects remain intact.

## Features

- **Multi-tenant:** Tenants with their own API keys, domains, templates,
  rules, campaigns, and M365 credentials
- **Template engine:** Jinja2 (sandboxed), HTML + text, validation against
  the canonical `UserContext` contract, filters `initials` and `tel`
- **Rule engine:** Condition trees (`and`/`or`/`not`), operators `equals`,
  `contains`, `starts_with`, `ends_with`, `regex`, `in`, `not_in`,
  prioritization, dry-run endpoint
- **Campaigns:** Time-controlled banners (`start_at`/`end_at`), targeting
  like rules, priority, phases (`scheduled`/`running`/`expired`)
- **Graph sync:** Users + groups from Microsoft Entra ID (MSAL client
  credentials, Microsoft Graph SDK), Redis cache, optionally scheduled via
  Celery Beat
- **Operations:** JSON logging with request IDs, Prometheus metrics
  (`/metrics`), health checks (`/health`)

## Technology Stack

- Python 3.13+, FastAPI, Uvicorn
- PostgreSQL 16, SQLAlchemy 2.x (async, asyncpg), Alembic
- Redis 7 (cache + Celery broker), Celery 5
- aiosmtpd (SMTP inbound), aiosmtplib (SMTP outbound)
- MSAL + Microsoft Graph SDK, Jinja2, structlog, prometheus-client
- Package manager: [uv](https://docs.astral.sh/uv/)

## Project Structure

```
app/
├── api/            # Router + dependency injection (no business logic)
│   ├── ops.py      #   /health, /metrics (unversioned)
│   └── v1/         #   versioned business endpoints (/api/v1)
├── auth/           # API key auth (operator + tenant keys, SHA-256 hashes)
├── cache/          # Redis client
├── campaigns/      # Time-controlled banner campaigns
├── config/         # pydantic-settings (environment-based)
├── core/           # Exceptions, middleware, UserContext contract
├── database/       # Engine/session factory, declarative base
├── graph/          # Entra ID sync (client, mapper, service)
├── jobs/           # Celery app + tasks
├── logging/        # structlog setup
├── mailer/         # Mail flow: MIME processing, SMTP server/client,
│                   #   Graph and Resend sending (alternative)
├── models/         # SQLAlchemy ORM models
├── rules/          # Condition trees + engine
├── templates/      # Jinja2 engine, validation, preview
└── tenants/        # Tenant CRUD, API keys, Resend onboarding
migrations/         # Alembic migrations
tests/              # unit / api / integration
docs/architecture/  # ADRs (architecture decision records)
```

## Production Setup (VPS + Microsoft 365)

### 1. Prerequisites

- VPS with public IPv4, DNS hostname for the relay, e.g.
  `relay.example.com` → VPS IP
- TLS certificate for this hostname (Let's Encrypt):
  `certbot certonly --standalone -d relay.example.com`
- M365 tenant with manageable Exchange Admin Center
- Entra app registration with application permissions `User.Read.All`,
  `GroupMember.Read.All`, `Directory.Read.All` (admin consent)

### 2. Server

Either Docker Compose (`docker compose up -d`, includes db, redis,
migrate, api, worker, scheduler, smtp) or native: install PostgreSQL + Redis,
`alembic upgrade head`, API and SMTP server as services
(systemd examples: see `docs/` or below under "Operations").

Important environment variables (`.env`):

```dotenv
# SMTP inbound (M365 outbound connector → this server)
SMTP_RELAY_HOSTNAME=relay.example.com
SMTP_INBOUND_PORT=25
SMTP_INBOUND_TLS_CERTFILE=/path/to/fullchain.pem
SMTP_INBOUND_TLS_KEYFILE=/path/to/privkey.pem
SMTP_INBOUND_REQUIRE_TLS=true
# Exchange Online outbound IPs (security! empty = open, for testing only)
SMTP_ALLOWED_HOSTS=40.92.0.0/15,40.107.0.0/16,52.100.0.0/14,52.238.78.88/32,104.47.0.0/17,2a01:111:f400::/48,2a01:111:f403::/48

# SMTP outbound (this server → M365 inbound connector)
SMTP_OUTBOUND_DEFAULT_HOST=<domain>.mail.protection.outlook.com
SMTP_OUTBOUND_PORT=25
SMTP_OUTBOUND_STARTTLS=true
```

Notes:

- If the server runs behind NAT/container without root, it listens on a
  high port (e.g. 2525) and is exposed to port 25 via port mapping.
- Sending to M365 should **force IPv4** (connectors only match IPv4
  sender IPs) — on Linux: activate `precedence ::ffff:0:0/96 100` in
  `/etc/gai.conf`.
- Ubuntu 26.04+ removed the legacy root "DigiCert Global Root CA" that
  M365 still uses — in case of `CERTIFICATE_VERIFY_FAILED`, install the root CA
  from https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem to
  `/usr/local/share/ca-certificates/` and run `update-ca-certificates`
  (verify fingerprint!).

### 3. M365 Configuration

1. **Outbound connector** (Mail flow → Connectors → New:
   Office 365 → Partner organization): Smarthost `relay.example.com`,
   port 25, TLS with certificate name `relay.example.com`. Validation address:
   `validation@relay.example.com` (accepted by the server and discarded).
2. **Transport rule:** "Sender is inside the organization" (+ optionally
   "Recipient is outside") → "Use connector". **Important — exception:**
   message header `X-Bytes-Signature-Processed` contains `yes`
   (loop protection!). Optional additional exception: "Sender IP =
   <VPS-IP>/32".
3. **Inbound connector** (Partner organization → Office 365):
   Identification by sender IP = VPS **IPv4**, TLS required.
4. **SPF** of the sender domain: extend with `ip4:<VPS-IP>` (recommended).

### 4. Create Tenant & Synchronize

```bash
# Tenant (operator key from .env)
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "X-API-Key: $OPERATOR_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "name": "acme",
    "microsoft_tenant_id": "<Tenant-ID>",
    "entra_client_id": "<Client-ID>",
    "entra_client_secret": "<Secret>",
    "settings": {
      "accepted_domains": ["example.com"],
      "inbound_connector_host": "example-com.mail.protection.outlook.com"
    }
  }'
# Response contains the tenant API key (bss_..., visible only once!)

# Synchronize users, create template + rule
curl -X POST http://localhost:8000/api/v1/graph/sync -H "X-API-Key: bss_..."
curl -X POST http://localhost:8000/api/v1/templates -H "X-API-Key: bss_..." ...
curl -X POST http://localhost:8000/api/v1/rules     -H "X-API-Key: bss_..." ...
```

After that, send a test mail from Outlook to an external recipient — it
arrives signed. Logs: `logs/smtp.log` (`smtp message processed and delivered`).

## Operations (native, systemd)

```ini
# /etc/systemd/system/bytes-signature-smtp.service
[Service]
WorkingDirectory=/opt/BytesSignatureService
ExecStart=/opt/BytesSignatureService/.venv/bin/python -m app.mailer.smtp_server
Restart=always

# /etc/systemd/system/bytes-signature-api.service
[Service]
WorkingDirectory=/opt/BytesSignatureService
ExecStart=/opt/BytesSignatureService/.venv/bin/uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
Restart=always
```

## Quick Start (Docker, Development)

```bash
cp .env.example .env
make up          # db, redis, migrate, api, worker, scheduler, smtp
```

- API: http://localhost:8000 — OpenAPI: `/docs`, Health: `/health`, Metrics: `/metrics`

## API Overview (v1)

Authentication via `X-API-Key` (operator key from `OPERATOR_API_KEY` or
tenant key `bss_...`; tenant isolation is enforced).

```
POST/GET/GET/PUT/DELETE  /api/v1/tenants[/{id}]          Tenant management
POST/GET/DELETE          /api/v1/tenants/{id}/api-keys   API keys
POST/GET/GET/PUT/DELETE  /api/v1/templates[/{id}]        Signature templates
POST                     /api/v1/preview                 Render preview
POST/GET/GET/PUT/DELETE  /api/v1/rules[/{id}]            Rules
POST                     /api/v1/rules/evaluate          Rule dry-run
POST/GET/GET/PUT/DELETE  /api/v1/campaigns[/{id}]        Campaigns
POST                     /api/v1/campaigns/evaluate      Campaign dry-run
POST                     /api/v1/graph/sync              Entra ID sync
GET                      /api/v1/graph/users             Synchronized users
POST                     /api/v1/mail/process            MIME dry-run (append signature)
POST                     /api/v1/mail/poll               Interception mailbox (legacy flow)
```

## Templates & User Attributes

Available variables (validated on save against `UserContext`):

```
first_name  last_name  display_name  title       department  company
office      city       country       phone       mobile      email
manager     groups (list)           custom_attributes (dict)
```

Filters: `initials` ("Max Mustermann" → "MM"), `tel` (for `tel:` links).
Conditional sections via Jinja (`{% if title %}...{% endif %}`) — empty
fields do not produce blank lines.

## Rule Engine (Example)

```json
{
  "type": "group", "op": "and",
  "children": [
    {"type": "leaf", "field": "department", "operator": "equals", "value": "Sales"},
    {"type": "leaf", "field": "country", "operator": "in", "value": ["DE", "AT", "CH"]},
    {"type": "not", "child":
      {"type": "leaf", "field": "groups", "operator": "contains", "value": "Extern"}}
  ]
}
```

## Security

- SMTP inbound: TLS enforced, source IP allowlist (Exchange Online ranges),
  no open relay; mails to the relay hostname itself are discarded
  (connector validation)
- Tenant API keys stored as SHA-256 hashes, plaintext visible only once
- Jinja2 sandbox, no HTML escaping needed (signature HTML is admin input)
- Secrets exclusively via environment variables

## Tests & Code Quality

```bash
make test              # Unit + API tests
make coverage          # With coverage report
make test-integration  # Requires running DB/Redis (RUN_INTEGRATION_TESTS=1)
make lint              # ruff + black --check + isort --check + mypy (strict)
make format            # ruff --fix + black + isort
```

## Roadmap

- DKIM signing on the return path
- Automatic Graph sync via Celery Beat (service setup)
- CID logos, QR codes, disclaimer blocks, banner rotation
- Management UI
- Multi-tenant scaling: queueing with persistent retries

## License

See `LICENSE` or `pyproject.toml`.
