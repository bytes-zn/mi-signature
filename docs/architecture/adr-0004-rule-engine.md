# ADR-0004: Rule Engine

Status: akzeptiert
Datum: 2026-07-28

## Kontext

Phase 4 liefert die Rule Engine: Regeln entscheiden anhand von
Benutzer-Attributen, welches Template für eine Signatur greift. Dieselbe
Bedingungslogik wird später von Kampagnen (Targeting) wiederverwendet.

## Entscheidungen

### 1. Bedingungsbaum als JSONB, validiert über Pydantic-Unions

Bedingungen sind rekursive Bäume: `ConditionLeaf` (Feld/Operator/Wert),
`ConditionGroup` (`and`/`or` mit Kindern), `ConditionNot` (Negation).
Gespeichert als JSONB; die Validierung erfolgt über eine
diskriminierte Pydantic-Union (`type`-Discriminator) — ungültige Strukturen
scheitern bereits an der API-Grenze mit HTTP 422. Gegenüber einer
flachen Liste von Regelzeilen erlaubt der Baum beliebige AND/OR/NOT-
Kombinationen ohne Spezialfall-Logik.

### 2. Felder referenzieren den kanonischen Vertrag

Condition-Felder werden gegen `KNOWN_USER_VARIABLES` (UserContext)
validiert; Custom Attributes folgen dem Muster `custom_attributes.<key>`.
Damit gilt dieselbe Garantie wie bei Templates: Eine Regel kann nie auf
Daten prüfen, die der Graph Sync nicht liefert.

### 3. Case-insensitive String-Vergleiche

`equals`, `contains`, `starts_with`, `ends_with`, `in`, `not_in` vergleichen
case-insensitiv — Verzeichnisdaten sind uneinheitlich gepflegt („Sales" vs.
„sales"), und das Erwartungsverhalten von Administratoren ist
Groß-/Kleinschreibungs-ignorant. `regex` bleibt unverändert (Flags gehören
ins Pattern, z. B. `(?i)`).

### 4. Listenfeld-Semantik für `groups`

Auf `groups` bedeutet `contains` Mitgliedschaft einer Gruppe, `in`/`not_in`
prüfen Schnittmenge. Andere Operatoren liefern auf Listen `false`.
Fehlende Custom Attributes (`None`) sind nur bei `not_in` wahr — ein
Attribut, das nicht existiert, kann keinen Ausschluss auslösen.

### 5. Höchste Priorität gewinnt, Evaluation ist rein

`evaluate()` ist eine reine Funktion ohne I/O (vollständig unit-testbar).
Der Service lädt aktive Regeln absteigend nach `priority` (Tiebreak:
Erstellungsdatum) und liefert die erste passende. Kein Treffer → `None`;
ob ein Fallback-Template greift, entscheidet später die Signature Engine.

### 6. Evaluate-Endpoint als Dry-Run

`POST /api/v1/rules/evaluate` persistiert nichts und dient dem Testen von
Regelwerken (späteres Frontend, Debugging) sowie der Kampagnen-Vorschau.

## Konsequenzen

- Regeln referenzieren Templates tenant-intern (`template_not_in_tenant`
  bei fremden IDs); Löschen eines Templates kaskadiert auf seine Regeln.
- Die Kampagnen-Engine importiert `conditions` + `engine` aus `app/rules`
  — keine zweite Bedingungsimplementierung.
- Ungültige Regex-Muster ergeben `false` statt eines Fehlers zur Laufzeit;
  eine Pattern-Validierung beim Speichern ist als spätere Härtung notiert.
