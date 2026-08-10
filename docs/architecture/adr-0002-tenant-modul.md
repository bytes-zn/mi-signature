# ADR-0002: Tenant-Modul und API-Key-Authentifizierung

Status: akzeptiert
Datum: 2026-07-28

## Kontext

Phase 2 liefert das Tenant-Modul: vollständiges Tenant-Datenmodell, CRUD-API,
API-Key-Authentifizierung und Mandantenisolation. Damit existiert der erste
Fach-Baustein, an dem sich alle späteren Module ausrichten.

## Entscheidungen

### 1. Zwei Rollen: Operator und Tenant

- **Operator** (Plattformbetreiber / White-Label-Kunde): authentifiziert sich
  über den statischen `OPERATOR_API_KEY` aus der Umgebung. Darf Tenants
  anlegen, auflisten und löschen.
- **Tenant**: authentifiziert sich über individuelle API-Keys
  (`bss_...`, in der DB als SHA-256-Hash). Darf ausschließlich den eigenen
  Tenant lesen/ändern und eigene API-Keys verwalten.

Begründung: Tenant-Verwaltung ist eine Betreiberfunktion; ein statischer
Operator-Key (später ergänzt um ein Operator-Backend) vermeidet ein
Henne-Ei-Problem bei der Tenant-Erstellung. JWT/OAuth2 bleibt vorbereitet,
ist aber für die serverseitige Nutzung (API-zu-API) nicht nötig.

### 2. API-Keys: nur Hash speichern, Klartext einmalig

Keys folgen dem Format `bss_<urlsafe-token>` (43 Zeichen Entropie-Anteil).
Gespeichert werden SHA-256-Hash (Lookup) und ein nicht-geheimes 12-Zeichen-Präfix
(Identifikation/Support). Der Klartext wird exakt einmal bei Erstellung
zurückgegeben. Widerruf ist ein Status-Flag (`revoked`), kein Löschen —
damit bleibt die Audit-Historie erhalten.

### 3. Isolation über eine Caller-Abstraktion

`app/auth/api_key.py` liefert die Dependency `get_caller`, die beide Rollen zu
einem `Caller`-Objekt auflöst. Fach-Endpoints rufen
`caller.ensure_tenant_access(tenant_id)` — die Isolationsregel existiert also
genau einmal und liegt nicht verstreut in den Routern. Spätere tenant-scoped
Module (Templates, Rules, ...) nutzen denselben Mechanismus.

### 4. ORM-Modelle zentral in `app/models/`

Tenant und ApiKey liegen zentral statt im Modulverzeichnis. Begründung:
Querschnitts-Relationen (Users, Templates, Rules referenzieren alle
`tenants.id`) erzeugen sonst zirkuläre Importe; Alembic und die
Naming-Conventions profitieren von einer einzigen Import-Anlaufstelle
(`app/models/__init__.py`). Die Module kapseln weiterhin Schemas (DTOs),
Repository, Service und Router.

### 5. Secrets-Felder: Secret ist schreibgeschützt

`entra_client_secret` ist im `TenantRead`-DTO nicht enthalten (write-only).
Verschlüsselung at-rest (z. B. via pgcrypto oder KMS-Hülle) ist als eigene
Härtungsmaßnahme vor Produktivbetrieb vorgesehen und hier bewusst noch nicht
implementiert (YAGNI für die Dev-Phase).

### 6. Service besitzt Transaktionsgrenzen

Der `TenantService` orchestriert die Repositories und committet selbst
(Unit-of-Work-light über die Request-Session). Repositories enthalten
ausschließlich Datenzugriff, Router ausschließlich HTTP-Belange.

## Konsequenzen

- Neue geschützte Endpoints müssen `get_caller` / `get_current_tenant` /
  `require_operator` verwenden — kein eigener Auth-Code in Routern.
- `OPERATOR_API_KEY` muss in echten Umgebungen gesetzt sein; der Default
  `dev-operator-key` ist ausschließlich für Entwicklung.
- Tenant-Löschen kaskadiert auf API-Keys (DB-`ON DELETE CASCADE`).
- Die 90-%-Coverage-Vorgabe gilt ab jetzt für die Businesslogik; der
  TenantService liegt bei 94 % (ohne Integrationstests).
