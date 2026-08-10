"""Send a test signature email.

Uses the application's Entra credentials (client credentials) to
authenticate, renders a signature template against Max Mustermann's
synced UserContext, and sends the mail as Max to the configured
recipient via the Graph ``sendMail`` endpoint.
"""

import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from sqlalchemy import select

from app.cache.redis import build_redis
from app.config.settings import get_settings
from app.core.user_context import UserContext
from app.database.session import build_engine, build_session_factory
from app.graph.client import GraphClient
from app.graph.mapper import map_user
from app.models.tenant import Tenant


def get_token() -> str:
    """Acquire a Graph token via client credentials (Mail.Send falls back too)."""
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{os.environ['ENTRA_TENANT_ID']}/oauth2/v2.0/token",
        data=urllib.parse.urlencode(
            {
                "client_id": os.environ["ENTRA_CLIENT_ID"],
                "client_secret": os.environ["ENTRA_CLIENT_SECRET"],
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }
        ).encode(),
    )
    return json.load(urllib.request.urlopen(req))["access_token"]


def send_mail(token: str, sender_upn: str, recipient: str, subject: str, html: str) -> None:
    body = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        },
        "saveToSentItems": False,
    }
    req = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0/users/{sender_upn}/sendMail",
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        print(f"sendMail für {sender_upn} -> {recipient}: {r.status}")


async def render_signature_for_sender(client: GraphClient, sender_upn: str) -> str:
    """Fetch the sender's attributes from Graph and render the signature."""
    users = await client.list_users()
    user = next(u for u in users if u.get("userPrincipalName") == sender_upn)
    groups = await client.get_user_groups(user["id"])
    context = map_user(user, (user.get("manager") or {}).get("displayName", ""), groups)

    template = """\
<table cellpadding="0" cellspacing="0" border="0" style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
  <tr>
    <td>
      <strong style="color: #1a73e8;">{{ display_name }}</strong><br>
      {% if title %}<em>{{ title }}</em><br>{% endif %}
      {% if department %}<span>{{ department }}</span>{% if company %} | {{ company }}{% endif %}<br>{% endif %}
      <hr style="border: 0; border-top: 1px solid #ddd; margin: 6px 0;">
      {% if phone %}<span>Tel: {{ phone }}</span>{% endif %}
      {% if mobile %} | <span>Mobil: {{ mobile }}</span>{% endif %}<br>
      {% if email %}<a href="mailto:{{ email }}" style="color: #1a73e8;">{{ email }}</a>{% endif %}
      {% if manager %}<br><small style="color: #777;">Manager: {{ manager }}</small>{% endif %}
      {% if groups %}<br><small style="color: #777;">Gruppen: {{ groups | join(', ') }}</small>{% endif %}
    </td>
  </tr>
</table>"""

    from app.templates.engine import get_template_engine

    return get_template_engine().render(template, context)


async def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: send_test_mail.py <sender_upn> <recipient>")
        sys.exit(2)

    sender_upn = sys.argv[1]
    recipient = sys.argv[2]
    subject = "Bytes Signature Service: Test-Signatur"

    client = GraphClient(
        os.environ["ENTRA_TENANT_ID"],
        os.environ["ENTRA_CLIENT_ID"],
        os.environ["ENTRA_CLIENT_SECRET"],
    )
    signature = await render_signature_for_sender(client, sender_upn)

    body = (
        "<!DOCTYPE html>"
        '<html><body style="font-family: Arial, sans-serif; color: #333;">'
        "<p>Hallo,</p>"
        "<p>die Signatur unten wurde serverseitig aus dem Microsoft-Graph-Profil "
        "und einem Jinja2-Template gerendert (Zeilen werden per <code>{% if %}</code> "
        "nur ausgegeben, wenn das Attribut gefuellt ist).</p>"
        '<hr style="border: 0; border-top: 1px solid #ddd; margin: 18px 0;">'
        + signature
        + "</body></html>"
    )

    token = get_token()
    send_mail(token, sender_upn, recipient, subject, body)


if __name__ == "__main__":
    asyncio.run(main())
