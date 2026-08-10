"""Canonical user attribute schema: the single source of truth for
which user attributes exist in the platform.

This contract connects three modules:

- The **template engine** validates template variables (``{{ first_name }}``,
  ``{{ phone }}``, ...) strictly against it - unknown variables are rejected
  when a template is created or updated.
- The **signature engine** renders templates with a ``UserContext`` instance.
- The **Microsoft Graph sync** (later phase) maps Entra ID user attributes
  into exactly this schema, so templates are guaranteed to match the data
  that Graph delivers.

Field names are aligned with the Entra ID / Microsoft Graph user resource
where sensible (e.g. ``given_name`` is exposed as ``first_name``).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserContext(BaseModel):
    """All user attributes available to templates and the signature engine."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = ""
    last_name: str = ""
    display_name: str = ""
    title: str = ""  # job title / position
    department: str = ""
    company: str = ""
    office: str = ""  # office location
    city: str = ""
    country: str = ""
    phone: str = ""  # business phone
    mobile: str = ""
    email: str = ""
    manager: str = ""  # manager display name

    # Microsoft 365 group display names the user belongs to.
    groups: list[str] = Field(default_factory=list)

    # Entra ID extension / custom attributes (free-form keys), e.g.
    # {"extensionAttribute1": "..."}.
    custom_attributes: dict[str, Any] = Field(default_factory=dict)


# Variables that may be used in templates, derived from the contract.
KNOWN_USER_VARIABLES: frozenset[str] = frozenset(UserContext.model_fields)
