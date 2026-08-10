"""Condition tree schema for the rule engine.

A rule's conditions form a tree stored as JSONB:

- **Leaf**: compares a user attribute (``field``) with a ``value`` using
  an ``operator``.
- **Group**: combines child conditions with ``and`` / ``or``.
- **Not**: negates a single child condition.

Example::

    {"type": "group", "op": "and", "children": [
        {"type": "leaf", "field": "department", "operator": "equals", "value": "Sales"},
        {"type": "not", "child":
            {"type": "leaf", "field": "groups", "operator": "contains", "value": "Extern"}},
    ]}

Fields reference the canonical user contract (``UserContext``); custom
attributes are addressed as ``custom_attributes.<key>``.
"""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.user_context import KNOWN_USER_VARIABLES

Operator = Literal[
    "equals",
    "contains",
    "starts_with",
    "ends_with",
    "regex",
    "in",
    "not_in",
]

_CUSTOM_FIELD_PATTERN = re.compile(r"^custom_attributes\.[A-Za-z0-9_]+$")


def validate_field_name(field: str) -> str:
    """Ensure a condition field references the user contract."""
    if field in KNOWN_USER_VARIABLES:
        return field
    if _CUSTOM_FIELD_PATTERN.match(field):
        return field
    known = ", ".join(sorted(KNOWN_USER_VARIABLES))
    raise ValueError(
        f"Unknown condition field: '{field}'. Known fields: {known}, " "or custom_attributes.<key>."
    )


class ConditionLeaf(BaseModel):
    """A single comparison: ``<field> <operator> <value>``."""

    type: Literal["leaf"] = "leaf"
    field: str
    operator: Operator
    value: Any

    @field_validator("field")
    @classmethod
    def _field_known(cls, value: str) -> str:
        return validate_field_name(value)


class ConditionGroup(BaseModel):
    """Combines child conditions with logical AND/OR."""

    type: Literal["group"] = "group"
    op: Literal["and", "or"]
    children: list["Condition"] = Field(min_length=1)


class ConditionNot(BaseModel):
    """Negates a child condition."""

    type: Literal["not"] = "not"
    child: "Condition"


Condition = Annotated[
    ConditionLeaf | ConditionGroup | ConditionNot,
    Field(discriminator="type"),
]

# Resolve forward references for the recursive model.
ConditionGroup.model_rebuild()
ConditionNot.model_rebuild()
