"""MSAL-based authentication provider for the Microsoft Graph SDK.

Implements the kiota ``AccessTokenProvider`` protocol so the Graph SDK
can use tokens acquired via MSAL (client credentials flow) — per-tenant
app registrations, no global credentials.
"""

from typing import Any

import msal
from kiota_abstractions.authentication import (
    AccessTokenProvider,
    AllowedHostsValidator,
)

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_HOSTS = ["graph.microsoft.com"]


class MsalAccessTokenProvider(AccessTokenProvider):
    """Supplies Graph SDK requests with MSAL client-credentials tokens."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self._app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        self._validator = AllowedHostsValidator(GRAPH_HOSTS)

    async def get_authorization_token(
        self,
        uri: str,
        additional_authentication_context: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> str:
        result = self._app.acquire_token_silent(GRAPH_SCOPE, account=None)
        if not result:
            result = self._app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise ConnectionError(
                f"MS Graph token acquisition failed: {result.get('error_description', result)}"
            )
        return str(result["access_token"])

    def get_allowed_hosts_validator(self) -> AllowedHostsValidator:
        return self._validator
