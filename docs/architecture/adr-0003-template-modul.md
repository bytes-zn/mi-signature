# ADR-0003: Template-Modul und kanonischer Attribut-Vertrag

Status: akzeptiert
Datum: 2026-07-28

## Kontext

Phase 3 liefert das Template-Modul: Jinja2-basierte Signatur-Templates mit
tenant-isoliertem CRUD und einem Preview-Endpoint. Die zentrale fachliche
Anforderung: Templates referenzieren Benutzer-Attribute (`{{ first_name }}`,
`{{ phone }}`, ...), die später aus Entra ID via Microsoft Graph synchronisiert
werden. Templates dürfen niemals Variablen enthalten, die der Graph Sync gar
nicht liefern kann.

## Entscheidungen

### 1. Kanonischer Attribut-Vertrag (`UserContext`)

`app/core/user_context.py` definiert das Pydantic-Modell `UserContext` als
**einzige Quelle der Wahrheit** für alle benutzerbezogenen Attribute
(`first_name`, `last_name`, `display_name`, `title`, `department`, `company`,
`office`, `city`, `country`, `phone`, `mobile`, `email`, `manager`, `groups`,
`custom_attributes`).

Drei Module binden an diesen Vertrag:

- Die **Template Engine** validiert jede Template-Variable strikt dagegen
  (unbekannte Variablen → HTTP 422 beim Anlegen/Ändern).
- Die **Signature Engine** rendert später mit `UserContext`-Instanzen.
- Der **Graph Sync** mappt Entra-ID-Attribute in exakt dieses Schema — die
  Ende-zu-Ende-Validierung ist damit von Anfang an eingebaut.

Feldnamen orientieren sich am Graph-User-Resource-Modell (z. B. wird
`givenName` zu `first_name` gemappt). `custom_attributes` (Dict) und `groups`
(Liste) decken Erweiterungsattribute bzw. Gruppenmitgliedschaften ab.

### 2. Validierung zur Speicherzeit, nicht zur Renderzeit

Template-Quelltexte (HTML- und Text-Body) werden beim `POST`/`PUT` geparst
(Jinja2-AST, `meta.find_undeclared_variables`) und gegen den Vertrag geprüft.
Vorteil: Fehler treten beim Erstellen auf, nicht erst beim ersten ausgehenden
E-Mail — es existiert zu keinem Zeitpunkt ein ungültiges Template in der
Datenbank.

### 3. Jinja2-Sandbox als Sicherheitsgrenze

Rendering erfolgt in `SandboxedEnvironment`: Zugriffe auf unsichere
Python-Interna (`__class__`, `__mro__`, ...) werden blockiert und als
`ValidationError` (422, `unsafe_template`) gemeldet. Da Templates von
Mandanten gepflegt werden, ist dies eine echte Angriffsfläche
(Server-Side Template Injection), nicht nur ein theoretisches Risiko.
`autoescape` ist bewusst deaktiviert: Signatur-Templates erzeugen
bewusst HTML; Escaping obliegt dem Template-Autor (später prüft die
Signature Engine das Ergebnis zusätzlich auf Outlook-Kompatibilität).

### 4. Eigene Filter minimal halten

Nur zwei Domänen-Filter: `initials` (Avatar-Platzhalter) und `tel`
(Normalisierung für `tel:`-Links). Alles andere deckt Jinja2 eingebaut ab
(YAGNI). QR-Codes/Banner gehören in die Signature Engine, nicht in die
Template-Sprache.

### 5. Preview als generischer Render-Endpoint

`POST /api/v1/preview` rendert wahlweise ein gespeichertes Template
(`template_id`, mit Tenant-Zugriffsprüfung) oder ad-hoc-Quelltext
(`html_body`/`text_body`) gegen Beispiel-Benutzerdaten. Damit kann ein
späteres Frontend Templates ohne Speichern testen; der Signature Engine
dient derselbe Codepfad (`TemplateService.render_inline` / `render_preview`).

### 6. Tenant-Scoping in der API-Schicht

Tenant-Caller werden immer auf den eigenen Tenant fixiert (clientseitige
`tenant_id`-Angaben werden ignoriert); Operator-Calls müssen den Tenant
explizit nennen (sonst 422 `tenant_required`). Der Service erzwingt die
Zugehörigkeit zusätzlich auf Datenebene (`get_tenant_template` liefert 404
statt 403 bei fremden Templates auf Service-Ebene — Existenz wird nicht
preisgegeben).

## Konsequenzen

- Neue Benutzer-Attribute werden ausschließlich über `UserContext`
  eingeführt (Model + Graph-Mapping in derselben Änderung).
- Der Graph Sync muss `UserContext`-Instanzen erzeugen können; seine Tests
  validieren das Mapping gegen dieses Schema.
- Templates sind pro Tenant eindeutig benannt (`uq_templates_tenant_name`)
  und werden mit dem Tenant kaskadiert gelöscht.
