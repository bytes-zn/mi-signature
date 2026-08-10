# ADR-0006b: Graph-Versandpfad und Empfänger-Reputation

Status: akzeptiert
Datum: 2026-08-09

## Kontext

Der Mail-Flow (Interception → Signatur → Re-Send) funktioniert Ende-zu-Ende auf der Plattform. Die zugestellten Testmails landen in Nicos `Sent Items`, der Plattform-SendMail-Aufruf gibt 202 zurück. Trotzdem kommen ausgehende Mails bei **externen Empfängern nicht an**, wenn der Tenant neu ist: SMTP-Diagnose liefert `550 5.7.708 Service unavailable. Access denied, traffic not accepted from this IP`.

## Entscheidungen

### 1. Zwei verschiedene Outbound-Pools für M365

- **Interaktiv (Outlook / OWA / Apple Mail)**: Versand geht über den **normalen Outbound-Pool** des Mandanten. Bekannte Empfänger akzeptieren; auch externe Server ohne harte IP-Blockregeln.
- **App-Only (Graph `sendMail` mit Client Credentials, SMTP AUTH XOAUTH2, etc.)**: Versand geht über den **High-Risk-Outbound-Pool** für Anwendungen / Background-Dienste. Dessen IP-Bereich ist eine Teilmenge, die bei vielen Empfänger-Servern (z. B. Spamhaus-Blocklist, Rspamd-Blocklist, Hornetsecurity, Mailcow) als schlechte Reputation auftaucht.

Der `5.7.708`-Bounce stammt damit **nicht** vom Code, sondern von der Reputation des App-Only-Pools. Inhalts‑Signaturen (DKIM/DMARC) oder gute SPF-Deklarationen ändern daran nichts, weil der Empfänger-Server den Traffic der IP-Bereich gar nicht inhaltlich prüft — er lehnt ihn auf Transportebene ab.

### 2. Lösung: eine von zwei Pfaden

**Pfad A — Delegated Mail.Send** (empfohlen für App-Architektur):
- Im Entra-Portal der App-Registration zusätzlich „Delegated Mail.Send" hinzufügen (UI-Pfad: API-Berechtigungen → Microsoft Graph → Delegierte Berechtigungen → Mail.Send auswählen → Administratorzustimmung erteilen).
- Token via OAuth-Code-Flow oder Device-Login mit `Mail.Send` Scope anfordern.
- Plattform re-sendet die Mail via Graph `sendMail` mit dem **delegated** Token des Benutzers: Graph reicht die Mail als „der angemeldete Benutzer" ein → normaler Outbound-Pool → identisches Verhalten wie ein Outlook-Klick.
- Diese App nutzt `scope=Mail.Send` delegated; der Token enthält `scp: Mail.Send`, der Graph-SendMail-Aufruf geht als eingeloggter Benutzer raus.

**Pfad B — Relay/Smarthost** (empfohlen wenn Pfad A nicht aufhört):
- Eigener SMTP-Server als Smarthost: Mails gehen vom Signatur-Server direkt zu Bytes-Commerce.de. Funktionsfähige Server-IP ist etabliert, nicht Teil eines Reputation-Pools.
- Kostenlose Dienste: SendGrid Free (100/Tag), Brevo Free (300/Tag), Mailgun Free (Fritzbox).
- Konfiguration: im M365-Admin-Center einen Outbound-Connector auf den Smarthost setzen, der Transportrule-Refit erfolgt darauf.

### 3. Pfad-C-Wahl im Code

`app.mailer.processor` baut die Graph-`sendMail`-JSON; der Aufrufer (Service oder Relayer) bestimmt, mit welchem Token der HTTP-Call abgesetzt wird:

- `client_credentials` → App-Only-Pool → **blockiert** bei reputations-basierten Empfängern.
- `delegated + Mail.Send` → User-Pool → **verhält sich wie ein manueller Outlook-Versand**.
- `relay + SMTP-Auth` → Smarthost → **Empfänger sieht nur die Smarthost-IP**.

Die Auswahl ist implementierungsseitig der Token, der an `app.mailer.processor.build_sendmail_body` gereicht wird. Default: delegated Service Principal Token (Pfad A). Für Hochvolumen/Tenant-übergreifend: configurable per Tenant.

## Konsequenzen

- Mails, die über den App-Only‑Pool gehen, können den Empfänger nicht erreichen, solange der Mandantenruf im jeweiligen Empfänger-IP-Range auf einer Blocklist steht. SPF/DKIM/DMARC ändern daran nichts.
- Pfad A (delegated Mail.Send) ist der Königsweg: er emuliert das, was ein Klick im Outlook tut.
- Pfad B (Smarthost) skaliert besser und macht sich unabhängig von M365-EOP‑Reputation, sofern ein Smarthost‑Provider konfiguriert wird.
- Ein einziger Mandantenruf kann beide Pfade gleichzeitig erlauben: API-Endpunkt toggelt anhand des Tenants (z. B. per Tenant-Flag `mailflow.relay: `…``).

## Reproducibility

Auf einem neuen M365-Tenant dauert es typischerweise einige Stunden bis Tage, bis der Tenant die initiale Outbound-Reputation aufgebaut hat. In dieser Phase ist der High-Risk-Pool für externe Empfänger meistens blockiert, danach normalisiert sich die Sache. Einen zwingenden Hard-Cutoff gibt Microsoft nicht.
