# ADR-0005: Kampagnen-Modul

Status: akzeptiert
Datum: 2026-07-28

## Kontext

Phase 5 liefert zeitgesteuerte Banner-Kampagnen: Start-/Enddatum, Priorität,
Targeting, mehrere parallele Kampagnen pro Tenant. Kampagnen werden später
von der Signature Engine in die gerenderte Signatur eingeblendet.

## Entscheidungen

### 1. Targeting nutzt die Rule Engine (kein zweites Bedingungssystem)

Kampagnen-Bedingungen sind exakt derselbe Condition-Baum wie bei Regeln
(`app/rules/conditions`, `app/rules/engine`). Vorteile: eine Implementierung,
eine Validierung gegen den UserContext-Vertrag, ein konsistentes Verhalten
für „Regel wählt Template" und „Kampagne wählt Banner". Kampagnen ohne
`conditions` (`NULL` in der DB) gelten für alle Benutzer des Tenants.

### 2. Zeitfenster strikt validiert, Auswertung zeitpunktbezogen

`start_at`/`end_at` sind Pflicht und müssen timezone-aware sein
(`end_at > start_at`), sowohl beim Anlegen als auch beim Aktualisieren
(kombinierte Prüfung). Die Evaluation vergleicht gegen einen übergebenen
Zeitpunkt (`at`, Default: jetzt UTC) — so ist die Zeitlogik rein und
deterministisch testbar, und der Evaluate-Endpoint kann beliebige
Zeitpunkte als Dry-Run prüfen.

### 3. Abgeleitete `phase` statt gespeichertem Status

Neben dem manuellen `status` (active/inactive) liefert die API ein
berechnetes Feld `phase`: `inactive` / `scheduled` / `running` / `expired`.
Es wird nie persistiert, sondern pro Request bestimmt — keine Hintergrund-
Jobs nötig, keine veralteten Zustände. Celery-basierte Aktivierung entfällt
damit bewusst (YAGNI): „running" ist eine Funktion der Zeit, nicht eines
Schedulers.

### 4. Höchste Priorität gewinnt — analog zu Regeln

Parallele Kampagnen sind erlaubt; bei mehreren Treffern (Zeitfenster +
Bedingungen) gewinnt die höchste `priority` (Tiebreak: Erstellungsdatum).
Dieselbe Semantik wie bei Regeln, damit Administratoren nur ein
Prioritätsmodell lernen müssen. Ob künftig mehrere Banner gleichzeitig
angezeigt werden, entscheidet die Signature Engine — das Modell
(`list_active_for_tenant`) gibt das bereits her.

### 5. Banner ist HTML-Snippet, kein Template

`banner_html` ist ein fertiges HTML-Fragment (typisch verlinktes Bild via
CID oder Remote-URL), optional ergänzt um `banner_text` (Plain-Text-Mails)
und `link_url`. Banner werden bewusst **nicht** durch die Jinja2-Engine
gejagt: Sie sind tenantweit identisch, nicht benutzerbezogen. Das Einfügen
in die Signatur (Outlook-kompatibel, mit Bild-Einbettung) ist Aufgabe der
Signature Engine.

## Konsequenzen

- Regel- und Kampagnen-Targeting bleiben dauerhaft synchron, weil beide
  `app/rules` importieren — Änderungen am Bedingungssystem gelten für beide.
- Der Evaluate-Endpoint (`POST /api/v1/campaigns/evaluate`) persistiert
  nichts und eignet sich für Frontend-Vorschau und Debugging.
- Kampagnen werden mit dem Tenant kaskadiert gelöscht.
