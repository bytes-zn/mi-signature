"""Microsoft Graph data access.

Uses the official Graph SDK for transport/auth (token acquisition via
MSAL, see ``app.graph.auth``). Typed SDK responses are serialized back
to plain Graph-shaped dicts — the mapper consumes exactly what the
Graph API returns, keeping the mapping layer free of SDK model coupling.
"""

from typing import Any

from kiota_abstractions.authentication import BaseBearerTokenAuthenticationProvider
from kiota_serialization_json.json_serialization_writer import JsonSerializationWriter
from msgraph.graph_request_adapter import GraphRequestAdapter
from msgraph.graph_service_client import GraphServiceClient

from app.graph.auth import MsalAccessTokenProvider

USER_SELECT = [
    "id",
    "givenName",
    "surname",
    "displayName",
    "jobTitle",
    "department",
    "companyName",
    "officeLocation",
    "city",
    "country",
    "businessPhones",
    "mobilePhone",
    "mail",
    "userPrincipalName",
    "onPremisesExtensionAttributes",
]


def _to_dict(parsable: Any) -> dict[str, Any]:
    """Serialize a typed SDK model back to its Graph JSON shape."""
    writer = JsonSerializationWriter()
    writer.write_object_value(None, parsable)
    raw = writer.get_serialized_content()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    import json

    return json.loads(text)  # type: ignore[no-any-return]


class GraphClient:
    """Thin async wrapper around the Graph SDK for one tenant."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self._provider = MsalAccessTokenProvider(tenant_id, client_id, client_secret)
        auth = BaseBearerTokenAuthenticationProvider(self._provider)
        adapter = GraphRequestAdapter(auth)
        self._client = GraphServiceClient(request_adapter=adapter)

    async def get_json(self, url: str) -> dict[str, Any]:
        """GET an arbitrary Graph URL with the tenant's token."""
        import httpx

        token = await self._provider.get_authorization_token(url)
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_bytes(self, url: str) -> bytes:
        """GET an arbitrary Graph URL returning raw bytes (e.g. MIME content)."""
        import httpx

        token = await self._provider.get_authorization_token(url)
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            return response.content

    async def post_json(self, url: str, payload: dict[str, Any]) -> None:
        """POST a JSON body to an arbitrary Graph URL."""
        import httpx

        token = await self._provider.get_authorization_token(url)
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    async def delete(self, url: str) -> None:
        """DELETE an arbitrary Graph URL."""
        import httpx

        token = await self._provider.get_authorization_token(url)
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.delete(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()

    async def patch_json(self, url: str, payload: dict[str, Any]) -> None:
        """PATCH a JSON body to an arbitrary Graph URL."""
        import httpx

        token = await self._provider.get_authorization_token(url)
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.patch(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    async def list_users(self) -> list[dict[str, Any]]:
        """All users with signature-relevant attributes and their manager."""
        from msgraph.generated.users.users_request_builder import UsersRequestBuilder

        config = UsersRequestBuilder.UsersRequestBuilderGetRequestConfiguration(
            query_parameters=UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                select=USER_SELECT,
                expand=["manager($select=displayName)"],
                top=999,
            )
        )
        users: list[dict[str, Any]] = []
        response = await self._client.users.get(request_configuration=config)
        while response is not None:
            users.extend(_to_dict(u) for u in response.value or [])
            next_link = response.odata_next_link
            if not next_link:
                break
            response = await self._client.users.with_url(next_link).get()
        return users

    async def get_user_groups(self, user_id: str) -> list[str]:
        """Display names of the groups a user belongs to."""
        try:
            response = await self._client.users.by_user_id(user_id).member_of.graph_group.get()
        except Exception:
            return []
        if response is None:
            return []
        names: list[str] = []
        for obj in response.value or []:
            data = _to_dict(obj)
            if data.get("displayName"):
                names.append(data["displayName"])
        return names
