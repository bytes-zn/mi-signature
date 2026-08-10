# ADR-0006: Graph Sync (Microsoft Entra ID)

Status: akzeptiert
Datum: 2026-07-28

## Kontext

Phase 6 synchronisiert Benutzer-Attribute aus Microsoft Entra ID in die
Plattform. Damit fließen echte Verzeichnisdaten in Templates, Rules und
Kampagnen — und der bis hier geforderte „Graph-Vertrag" wird
geschlossen.

## Entscheidungen

### 1. Token-Erwerb: MSAL Confidential Client (Client Credentials)

Pro Tenant werden die App-Registration-Credentials im Tenant-Record
gehalten (oder global in `.env` als Fallback für Dev). Der `MsalAccessTokenProvider`
implementiert das kiota-`AccessTokenProvider`-Protokoll, sodass der
Microsoft Graph SDK weiterhin für Transport und Auth verwendet werden
kann — wie die Spec es verlangt, ohne ein zweites Credential-System
(`azure-identity`) einzuziehen.

### 2. Mapping als Vertrags-Tor

`app/graph/mapper.py` ist die einzige Stelle, an der Graph-Payloads in
`UserContext` überführt werden. Vierzehn Felder plus Gruppen und
`customAttributes` (extensionAttribute1–15) werden befüllt; fehlende
Werte werden zu leeren Strings bzw. leeren Listen — damit die
`UserContext`-Validierungen in Template- und Rule-Engine nie
überrascht werden. Das Mapping ist die Garantie, die ADR-0003
versprochen hat.

### 3. SDK-Antworten werden zu Graph-Dicts re-serialisiert

Die vom SDK gelieferten Typed Models werden über
`JsonSerializationWriter` wieder in die Graph-JSON-Shape serialisiert —
das Mapping sieht immer aus, was die Graph-API liefert, und bleibt
damit unabhängig von SDK-Modell-Änderungen. Preis: ein kleiner
Round-Trip-Overhead pro Modell, akzeptabel für moderate
Verzeichnisgrößen.

### 4. Speicherung: `users`-Tabelle + Redis-Cache

Das `users`-Schema speichert pro Tenant das vollständige `UserContext`-
Payload als JSONB (`data`) plus denormalisierte Suchfelder
(`email`, `display_name`). Ein Redis-Cache (`graph:users:{tenant_id}`,
TTL aus `GRAPH_CACHE_TTL_SECONDS`) liegt daneben, damit häufige
Abfragen nicht jedes Mal Graph anrufen.

### 5. Sync ist deterministisch

Pro Sync-Lauf wird die vollständige Liste geholt, gemappt, im Ziel
upserted (anhand `tenant_id + entra_user_id`) und Datensätze, die im
Verzeichnis nicht mehr existieren, hart gelöscht. Damit ist die
`users`-Tabelle immer konsistent mit dem Verzeichnis und es gibt keine
„verwaisten" Einträge.

### 6. Geplanter Sync via Celery Beat

`app.jobs.tasks.sync_all_tenants` iteriert über alle aktiven Tenants
mit konfigurierbaren Entra-Credentials und führt den Sync aus.
Aktivierung erfolgt durch `GRAPH_SYNC_INTERVAL_MINUTES` (`> 0`); 0 =
off. Damit ist Scheduling konfigurierbar, statt einen Scheduler zu
erzwingen.

### 7. Mail-Test: Apps + Postfächer

Der echte End-to-End-Versand (Testmail an `zeier@bytes-commerce.de`)
erfordert zusätzlich die App-Permission `Mail.Send` plus lizenzierte
Postfächer (in der Dev-Umgebung: `O365_BUSINESS_PREMIUM`, 25 Plätze
verfügbar). Beides wurde im Tenant eingerichtet; der Dev-Skript
`scripts/send_test_mail.py` rendert eine Signatur über
`app.templates.engine` und sendet via `/users/{sender}/sendMail` mit
Client-Credentials. Die produktive Mail-Flow-Integration ist
Gegenstand von Phase 8.

## Konsequenzen

- Templates, Rules und Kampagnen müssen nie „auf fehlende Attribute
  reagieren" — das Mapping normalisiert auf leere Strings.
- `display_name` und `email` werden in `user_principal_name` und `mail`
  bevorzugt; die `UserContext.email` landet im Mapper via Fallback
  immer auf einem gültigen Wert.
- `manager` wird unter `mailboxSettings` aufgelöst — aktuell nur
  Display-Name. Wer echte Manager-E-Mails braucht, ergänzt das Mapping
  später.
- Bei großen Verzeichnissen (> 999 Benutzer) paginiert der SDK
  automatisch; unser `$select/$top=999` ist nur ein Schleifen-Startwert.
