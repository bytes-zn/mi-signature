# MI Signature (Bytes Signature Service)

Open-Source, self-hosted Plattform für **serverseitige E-Mail-Signaturen in
Microsoft 365** — eine Alternative zu CodeTwo & Co., ohne Client-Plugins und
ohne Outlook-Regeln. Die Mail läuft über normale **Exchange-Online-Connectoren**
durch den eigenen Server, bekommt dort Signatur und optional ein
Kampagnen-Banner angehängt und wird an M365 zurückgeliefert.

Reine REST-API (kein Frontend), mandantenfähig, Clean Architecture.

**Status:** Produktiv lauffähig. Ende-zu-Ende getestet:
Outlook → M365 → Signatur-Server → M365 → externer Empfänger, inkl.
reply-sicherer Signaturplatzierung.

## Wie es funktioniert

```
┌─────────┐   1. Mail an externen Empfänger
│ Outlook │
└────┬────┘
     ▼
┌─────────────────────────────────────────────────────────┐
│ Microsoft 365 (Exchange Online)                         │
│  Transportregel „Signature"  ──2──►  Outbound-Connector │
└──────────────────────────────────────┬──────────────────┘
                                        ▼  SMTP + STARTTLS, Port 25
┌─────────────────────────────────────────────────────────┐
│ MI Signature (dieser Server)                            │
│  3. Tenant an Absender-Domain erkennen                  │
│  4. Benutzer aus Verzeichnis (Graph-Sync) auflösen      │
│  5. Regel → Template wählen, Kampagne prüfen            │
│  6. Signatur direkt unter den neuen Text einfügen       │
│     (vor dem zitierten Verlauf)                         │
└──────────────────────────────────────┬──────────────────┘
                                        ▼  SMTP + STARTTLS, Port 25
┌─────────────────────────────────────────────────────────┐
│ Microsoft 365 — Inbound-Connector (Partnerorganisation) │
│  7. Zustellung an den Empfänger                         │
└─────────────────────────────────────────────────────────┘
```

Zentrale Eigenschaften des Mailflows:

- **Fail-safe:** Kann eine Mail nicht signiert werden (unbekannter Absender,
  keine Regel, Verarbeitungsfehler), wird sie **unverändert weitergeleitet** —
  der Mailfluss wird nie unterbrochen.
- **Loop-Schutz:** Signierte Mails tragen den Header
  `X-Bytes-Signature-Processed: yes`. Die Transportregel bekommt eine
  Ausnahme auf diesen Header; der Server verwirft doppelt eintreffende Mails
  zusätzlich selbst.
- **Reply-sicher:** Die Signatur wird vor dem Zitatblock eingefügt
  (erkannte Marker: neues Outlook/OWA, klassisches OWA inkl. `<hr>`-Trenner,
  Outlook Desktop/Word-HTML, Gmail, Apple Mail, Thunderbird) — bei neuen
  Mails wie bisher ans Ende.
- **Envelope-treu:** SMTP-Empfänger (RCPT TO) werden 1:1 übernommen,
  BCC und Redirects bleiben erhalten.

## Features

- **Mandantenfähig:** Tenants mit eigenen API-Keys, Domains, Templates,
  Regeln, Kampagnen und M365-Credentials
- **Template-Engine:** Jinja2 (sandboxed), HTML + Text, Validierung gegen
  den kanonischen `UserContext`-Vertrag, Filter `initials` und `tel`
- **Rule Engine:** Bedingungsbäume (`and`/`or`/`not`), Operatoren `equals`,
  `contains`, `starts_with`, `ends_with`, `regex`, `in`, `not_in`,
  Priorisierung, Dry-Run-Endpoint
- **Kampagnen:** Zeitgesteuerte Banner (`start_at`/`end_at`), Targeting wie
  bei Regeln, Priorität, Phasen (`scheduled`/`running`/`expired`)
- **Graph-Sync:** Benutzer + Gruppen aus Microsoft Entra ID (MSAL Client
  Credentials, Microsoft Graph SDK), Redis-Cache, optional per Celery Beat
  geplant
- **Betrieb:** JSON-Logging mit Request-IDs, Prometheus-Metriken
  (`/metrics`), Health-Checks (`/health`)

## Technologie-Stack

- Python 3.13+, FastAPI, Uvicorn
- PostgreSQL 16, SQLAlchemy 2.x (async, asyncpg), Alembic
- Redis 7 (Cache + Celery Broker), Celery 5
- aiosmtpd (SMTP-Eingang), aiosmtplib (SMTP-Ausgang)
- MSAL + Microsoft Graph SDK, Jinja2, structlog, prometheus-client
- Paketmanager: [uv](https://docs.astral.sh/uv/)

## Projektstruktur

```
app/
├── api/            # Router + Dependency Injection (keine Businesslogik)
│   ├── ops.py      #   /health, /metrics (unversioniert)
│   └── v1/         #   versionierte Fach-Endpoints (/api/v1)
├── auth/           # API-Key-Auth (Operator + Tenant-Keys, SHA-256-Hashes)
├── cache/          # Redis-Client
├── campaigns/      # Zeitgesteuerte Banner-Kampagnen
├── config/         # pydantic-settings (Environment-basiert)
├── core/           # Exceptions, Middleware, UserContext-Vertrag
├── database/       # Engine/Session-Factory, Declarative Base
├── graph/          # Entra-ID-Sync (Client, Mapper, Service)
├── jobs/           # Celery App + Tasks
├── logging/        # structlog-Setup
├── mailer/         # Mailflow: MIME-Verarbeitung, SMTP-Server/-Client,
│                   #   Graph- und Resend-Versand (alternativ)
├── models/         # SQLAlchemy ORM-Modelle
├── rules/          # Bedingungsbäume + Engine
├── templates/      # Jinja2-Engine, Validierung, Preview
└── tenants/        # Tenant-CRUD, API-Keys, Resend-Onboarding
migrations/         # Alembic-Migrationen
tests/              # unit / api / integration
docs/architecture/  # ADRs (Architekturentscheidungen)
```

## Produktiv-Setup (VPS + Microsoft 365)

### 1. Voraussetzungen

- VPS mit öffentlicher IPv4, DNS-Hostname für den Relay, z. B.
  `relay.example.com` → VPS-IP
- TLS-Zertifikat für diesen Hostnamen (Let's Encrypt):
  `certbot certonly --standalone -d relay.example.com`
- M365-Tenant mit administrierbarem Exchange Admin Center
- Entra-App-Registration mit Application Permissions `User.Read.All`,
  `GroupMember.Read.All`, `Directory.Read.All` (Admin Consent)

### 2. Server

Entweder Docker Compose (`docker compose up -d`, enthält db, redis,
migrate, api, worker, scheduler, smtp) oder nativ: PostgreSQL + Redis
installieren, `alembic upgrade head`, API und SMTP-Server als Dienste
(systemd-Beispiele: siehe `docs/` bzw. unten „Betrieb").

Wichtige Umgebungsvariablen (`.env`):

```dotenv
# SMTP-Eingang (M365 Outbound-Connector → dieser Server)
SMTP_RELAY_HOSTNAME=relay.example.com
SMTP_INBOUND_PORT=25
SMTP_INBOUND_TLS_CERTFILE=/pfad/zu/fullchain.pem
SMTP_INBOUND_TLS_KEYFILE=/pfad/zu/privkey.pem
SMTP_INBOUND_REQUIRE_TLS=true
# Exchange-Online-Ausgangs-IPs (Sicherheit! leer = offen, nur zum Testen)
SMTP_ALLOWED_HOSTS=40.92.0.0/15,40.107.0.0/16,52.100.0.0/14,52.238.78.88/32,104.47.0.0/17,2a01:111:f400::/48,2a01:111:f403::/48

# SMTP-Ausgang (dieser Server → M365 Inbound-Connector)
SMTP_OUTBOUND_DEFAULT_HOST=<domain>.mail.protection.outlook.com
SMTP_OUTBOUND_PORT=25
SMTP_OUTBOUND_STARTTLS=true
```

Hinweise:

- Läuft der Server hinter NAT/Container ohne Root, lauscht er auf einem
  High-Port (z. B. 2525) und wird per Port-Mapping auf 25 exponiert.
- Der Versand an M365 sollte **IPv4** erzwingen (Connectoren matchen nur
  IPv4-Absender-IPs) — unter Linux: `precedence ::ffff:0:0/96 100` in
  `/etc/gai.conf` aktivieren.
- Ubuntu 26.04+ entfernte die Legacy-Root „DigiCert Global Root CA“, die
  M365 noch verwendet — bei `CERTIFICATE_VERIFY_FAILED` die Root-CA von
  https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem nach
  `/usr/local/share/ca-certificates/` installieren und
  `update-ca-certificates` ausführen (Fingerprint prüfen!).

### 3. M365 einrichten

1. **Outbound-Connector** (Nachrichtenfluss → Connectors → Neu:
   Office 365 → Partnerorganisation): Smarthost `relay.example.com`,
   Port 25, TLS mit Zertifikatsname `relay.example.com`. Validierungsadresse:
   `validation@relay.example.com` (wird vom Server angenommen und verworfen).
2. **Transportregel:** „Absender innerhalb der Organisation“ (+ optional
   „Empfänger außerhalb“) → „Connector verwenden“. **Wichtig — Ausnahme:**
   Nachrichtenkopf `X-Bytes-Signature-Processed` enthält `yes`
   (Loop-Schutz!). Optional zusätzlich: Ausnahme „Absender-IP =
   <VPS-IP>/32“.
3. **Inbound-Connector** (Partnerorganisation → Office 365):
   Identifizierung per Absender-IP = VPS-**IPv4**, TLS erforderlich.
4. **SPF** der Absender-Domain um `ip4:<VPS-IP>` erweitern (empfohlen).

### 4. Tenant anlegen & synchronisieren

```bash
# Tenant (Operator-Key aus .env)
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
# Antwort enthält den Tenant-API-Key (bss_..., nur einmal sichtbar!)

# Benutzer synchronisieren, Template + Regel anlegen
curl -X POST http://localhost:8000/api/v1/graph/sync -H "X-API-Key: bss_..."
curl -X POST http://localhost:8000/api/v1/templates -H "X-API-Key: bss_..." ...
curl -X POST http://localhost:8000/api/v1/rules     -H "X-API-Key: bss_..." ...
```

Danach eine Testmail aus Outlook an einen externen Empfänger — sie kommt
signiert an. Logs: `logs/smtp.log` (`smtp message processed and delivered`).

## Betrieb (nativ, systemd)

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

## Schnellstart (Docker, Entwicklung)

```bash
cp .env.example .env
make up          # db, redis, migrate, api, worker, scheduler, smtp
```

- API: http://localhost:8000 — OpenAPI: `/docs`, Health: `/health`, Metrics: `/metrics`

## API-Überblick (v1)

Authentifizierung per `X-API-Key` (Operator-Key aus `OPERATOR_API_KEY` oder
Tenant-Key `bss_...`; Tenant-Isolation wird erzwungen).

```
POST/GET/GET/PUT/DELETE  /api/v1/tenants[/{id}]          Tenant-Verwaltung
POST/GET/DELETE          /api/v1/tenants/{id}/api-keys   API-Keys
POST/GET/GET/PUT/DELETE  /api/v1/templates[/{id}]        Signatur-Templates
POST                     /api/v1/preview                 Render-Vorschau
POST/GET/GET/PUT/DELETE  /api/v1/rules[/{id}]            Regeln
POST                     /api/v1/rules/evaluate          Regel-Dry-Run
POST/GET/GET/PUT/DELETE  /api/v1/campaigns[/{id}]        Kampagnen
POST                     /api/v1/campaigns/evaluate      Kampagnen-Dry-Run
POST                     /api/v1/graph/sync              Entra-ID-Sync
GET                      /api/v1/graph/users             Synchronisierte Benutzer
POST                     /api/v1/mail/process            MIME-Dry-Run (Signatur anhängen)
POST                     /api/v1/mail/poll               Interception-Mailbox (Legacy-Flow)
```

## Templates & Benutzer-Attribute

Verfügbare Variablen (Validierung beim Speichern gegen `UserContext`):

```
first_name  last_name  display_name  title       department  company
office      city       country       phone       mobile      email
manager     groups (Liste)           custom_attributes (Dict)
```

Filter: `initials` („Max Mustermann" → „MM"), `tel` (für `tel:`-Links).
Bedingte Abschnitte per Jinja (`{% if title %}...{% endif %}`) — leere
Felder erzeugen keine Leerzeilen.

## Rule Engine (Beispiel)

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

## Sicherheit

- SMTP-Eingang: TLS erzwungen, Quell-IP-Allowlist (Exchange-Online-Bereiche),
  kein Open Relay; Mails an den Relay-Hostnamen selbst werden verworfen
  (Connector-Validierung)
- Tenant-API-Keys als SHA-256-Hash gespeichert, Klartext nur einmal sichtbar
- Jinja2-Sandbox, kein HTML-Escaping nötig (Signatur-HTML ist Admin-Input)
- Secrets ausschließlich über Environment-Variablen

## Tests & Codequalität

```bash
make test              # Unit- + API-Tests
make coverage          # mit Coverage-Report
make test-integration  # benötigt laufende DB/Redis (RUN_INTEGRATION_TESTS=1)
make lint              # ruff + black --check + isort --check + mypy (strict)
make format            # ruff --fix + black + isort
```

## Roadmap

- DKIM-Signierung auf dem Rückweg
- Automatischer Graph-Sync per Celery Beat (Service-Setup)
- CID-Logos, QR-Codes, Disclaimer-Blöcke, Banner-Rotation
- Verwaltungs-UI
- Mehrmandanten-Skalierung: Queueing mit persistenten Retries

## Lizenz

Siehe `LICENSE` bzw. `pyproject.toml`.
