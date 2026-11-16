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
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_validator

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

#: Maximum length of a regular expression used in a condition.
MAX_REGEX_LENGTH = 200

#: Nested quantifiers ("(a+)+") are the classic source of catastrophic
#: backtracking. The rule engine runs synchronously in the mail path, so
#: such a pattern would block the worker for every incoming message.
_NESTED_QUANTIFIER = re.compile(r"\([^)]*[+*][^)]*\)\s*[+*]")


def validate_regex_pattern(pattern: str) -> str:
    """Validate a condition regex and return it unchanged.

    Raises:
        ValueError: if the pattern is invalid, too long or prone to
            catastrophic backtracking.
    """
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(
            f"Regular expression must not be longer than {MAX_REGEX_LENGTH} characters."
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}") from exc
    if _NESTED_QUANTIFIER.search(pattern):
        raise ValueError(
            "Regular expression with nested quantifiers is not allowed "
            "(risk of catastrophic backtracking)."
        )
    return pattern


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

_condition_adapter: TypeAdapter[Condition] = TypeAdapter(Condition)


def validate_condition_tree(condition: Condition) -> Condition:
    """Validate the regular expressions of a condition tree.

    Called when a rule or a campaign is saved. Stored conditions are not
    re-validated on read, so a legacy pattern stays usable (and simply
    never matches) instead of breaking the whole rule set.
    """
    if isinstance(condition, ConditionLeaf):
        if condition.operator == "regex":
            if not isinstance(condition.value, str):
                raise ValueError("A regex condition requires a string value.")
            validate_regex_pattern(condition.value)
    elif isinstance(condition, ConditionGroup):
        for child in condition.children:
            validate_condition_tree(child)
    elif isinstance(condition, ConditionNot):
        validate_condition_tree(condition.child)
    return condition


@lru_cache(maxsize=1024)
def parse_conditions(raw: str) -> Condition:
    """Parse and validate a serialized condition tree.

    The result is cached: the rule engine evaluates the conditions of a
    tenant for every incoming mail, and re-validating the same tree over
    and over again would dominate the processing time.
    """
    return _condition_adapter.validate_json(raw)
