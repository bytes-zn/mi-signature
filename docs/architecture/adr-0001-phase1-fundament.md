# ADR-0001: Phase-1-Fundament

Status: akzeptiert
Datum: 2026-07-28

## Kontext

Greenfield-Projekt: White-Label-Backend-Plattform für serverseitige E-Mail-Signaturen
in Microsoft 365. Phase 1 liefert ausschließlich die Infrastruktur-Basis, auf der alle
Fachmodule aufsetzen. Dieses Dokument begründet die getroffenen Grundsatzentscheidungen.

## Entscheidungen

### 1. Paketmanager: uv

`uv` mit `pyproject.toml` + `uv.lock`. Deutlich schnellere Builds (lokal und in Docker),
reproduzierbare Lockfiles, First-class-Support für Dependency-Groups (dev-Abhängigkeiten
ohne separates requirements-File).

### 2. Async SQLAlchemy 2.x (asyncpg)

FastAPI ist nativ async; der DB-Zugriff über `AsyncSession` + `asyncpg` vermeidet
Thread-Pool-Umwege und skaliert bei vielen parallelen Requests (später: Mail Processing,
Graph Sync) besser. Alembic läuft mit einer async `env.py` über denselben Engine-Typ.

### 3. App-Factory statt Modul-Singleton

`app.main:create_app()` erzeugt die FastAPI-Instanz. Shared Resources (Engine,
Session-Factory, Redis) werden im Lifespan erzeugt und in `app.state` abgelegt;
Endpoints erhalten sie über Dependency-Provider (`app/api/deps.py`). Das hält die
App testbar (Fakes via `app.state` austauschbar) und vermeidet Import-Time-Seiteneffekte.

### 4. Unversionierte Ops-Endpoints, versionierte Fach-API

`/health` und `/metrics` liegen bewusst **außerhalb** von `/api/v1`: sie werden von
Loadbalancern, Kubernetes-Probes und Prometheus konsumiert und sollen bei
API-Versionssprüngen stabil bleiben. Alle Fach-Endpoints kommen unter `/api/v1`
(Router `app/api/v1/router.py`, in Phase 1 noch leer).

### 5. Health-Design: Liveness + Readiness kombiniert

`GET /health` prüft PostgreSQL (`SELECT 1`) und Redis (`PING`) und antwortet mit
HTTP 200 (`{"status": "ok"}`) bzw. HTTP 503 (`{"status": "degraded"}`) plus
Per-Komponenten-Status. Einzelne Komponentenfehler ziehen den Gesamtstatus auf 503,
ohne dass der Prozess selbst als tot gilt — passend für K8s-Readiness.

### 6. Logging: structlog mit Request-ID-Korrelation

JSON-Renderer in `staging`/`production`, Console-Renderer in `development`
(`LOG_FORMAT`). Eine Middleware bindet die `X-Request-ID` (übernommen oder generiert)
an den structlog-Context und loggt Methode, Pfad, Status und Dauer jedes Requests.
Audit-Logging der Fachmodule baut später auf derselben Infrastruktur auf.

### 7. Celery in Phase 1 nur als Gerüst

Worker- und Beat-Container sind in `docker-compose.yml` enthalten und starten mit,
enthalten aber nur den `ping`-Task als Konnektivitätsnachweis. Begründung: Die
Docker-/CI-Verkabelung (Broker, Result-Backend, Image) soll früh bewiesen werden;
fachliche Jobs (Graph-Sync, Kampagnen) folgen mit ihren Modulen.

### 8. Minimale `tenants`-Tabelle als Migrations-Anker

Die erste Migration erstellt eine kleine `tenants`-Tabelle (id, name, status,
Timestamps). Damit ist die Alembic-Pipeline (async env, Naming-Conventions,
Autogenerate-Basis) Ende-zu-Ende bewiesen, ohne dem Tenant-Modul (Phase 2)
Feldentscheidungen vorwegzunehmen.

### 9. Teststrategie: Fakes statt externer Dienste für Unit/API-Tests

API-Tests ersetzen `app.state.session_factory` und `app.state.redis` durch Fakes —
keine DB/Redis nötig, schnell und CI-tauglich. Echte Konnektivität decken
Integrationstests ab, die nur mit `RUN_INTEGRATION_TESTS=1` laufen (Compose/CI).
Die 90-%-Coverage-Vorgabe gilt für die Businesslogik der Fachmodule ab Phase 2;
Phase 1 richtet die Coverage-Infrastruktur (`pytest-cov`) ein.

### 10. Constraint-Naming-Conventions

Die Declarative Base setzt PostgreSQL-Naming-Conventions für alle Constraints/Indizes.
Damit sind Migrationen deterministisch und spätere `ALTER`-Operationen referenzierbar.

## Konsequenzen

- Docker-Compose umfasst 5 Services (api, db, redis, worker, scheduler) + Migrations-Job.
- mypy läuft im `strict`-Modus auf `app/`; neue Module müssen vollständig typisiert sein.
- Keine Businesslogik in `app/api/` — Router dürfen nur Dependencies injizieren und
  Services aufrufen (wird ab Phase 2 durchgesetzt).
