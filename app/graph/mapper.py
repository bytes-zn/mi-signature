"""Mapping from Microsoft Graph user data to the canonical UserContext.

This is the validation gate the platform promised in ADR-0003: every
attribute the Graph sync delivers is mapped into exactly the fields the
template and rule engines validate against. Graph payloads are passed as
plain dicts (serialized SDK models) to keep this function pure and
trivially testable.
"""

from typing import Any

from app.core.user_context import UserContext

# Entra extension attributes exposed to templates as custom_attributes.
EXTENSION_ATTRIBUTES = [f"extensionAttribute{i}" for i in range(1, 16)]


def map_user(graph_user: dict[str, Any], manager_name: str, groups: list[str]) -> UserContext:
    """Map one Graph user (plus resolved manager name and group names)."""
    on_prem = graph_user.get("onPremisesExtensionAttributes") or {}
    custom = {
        key: on_prem[key] for key in EXTENSION_ATTRIBUTES if on_prem.get(key) not in (None, "")
    }

    business_phones = graph_user.get("businessPhones") or []

    return UserContext(
        first_name=graph_user.get("givenName") or "",
        last_name=graph_user.get("surname") or "",
        display_name=graph_user.get("displayName") or "",
        title=graph_user.get("jobTitle") or "",
        department=graph_user.get("department") or "",
        company=graph_user.get("companyName") or "",
        office=graph_user.get("officeLocation") or "",
        city=graph_user.get("city") or "",
        country=graph_user.get("country") or "",
        phone=business_phones[0] if business_phones else "",
        mobile=graph_user.get("mobilePhone") or "",
        email=graph_user.get("mail") or graph_user.get("userPrincipalName") or "",
        manager=manager_name,
        groups=groups,
        custom_attributes=custom,
    )
