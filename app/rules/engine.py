"""Rule engine: evaluates condition trees against a UserContext.

Pure functions, no I/O - the engine is fully unit-testable. String
comparisons are case-insensitive by default (matching user expectations
for directory data); ``regex`` uses the pattern's own flags.

Semantics on the list field ``groups``: ``contains`` tests membership,
``in``/``not_in`` test whether any group is in the value list.
"""

import re
from typing import Any

from app.core.user_context import UserContext
from app.rules.conditions import Condition, ConditionGroup, ConditionLeaf, ConditionNot


def resolve_field(user: UserContext, field: str) -> Any:
    """Resolve a condition field to the user's attribute value."""
    if field.startswith("custom_attributes."):
        key = field.removeprefix("custom_attributes.")
        return user.custom_attributes.get(key)
    return getattr(user, field)


def evaluate_leaf(leaf: ConditionLeaf, user: UserContext) -> bool:
    """Evaluate a single comparison against the user."""
    attr = resolve_field(user, leaf.field)
    value = leaf.value

    # List-valued attribute (groups): membership semantics.
    if isinstance(attr, list):
        lowered = {str(item).lower() for item in attr}
        if leaf.operator == "contains":
            return str(value).lower() in lowered
        if leaf.operator == "in":
            return bool(lowered & {str(v).lower() for v in _as_list(value)})
        if leaf.operator == "not_in":
            return not lowered & {str(v).lower() for v in _as_list(value)}
        return False

    # Missing custom attribute: only not_in is meaningfully true.
    if attr is None:
        return leaf.operator == "not_in"

    text = str(attr)
    if leaf.operator == "equals":
        return text.lower() == str(value).lower()
    if leaf.operator == "contains":
        return str(value).lower() in text.lower()
    if leaf.operator == "starts_with":
        return text.lower().startswith(str(value).lower())
    if leaf.operator == "ends_with":
        return text.lower().endswith(str(value).lower())
    if leaf.operator == "regex":
        try:
            return re.search(str(value), text) is not None
        except re.error:
            return False
    if leaf.operator == "in":
        return text.lower() in {str(v).lower() for v in _as_list(value)}
    if leaf.operator == "not_in":
        return text.lower() not in {str(v).lower() for v in _as_list(value)}
    return False


def evaluate(condition: Condition, user: UserContext) -> bool:
    """Evaluate a condition tree against the user."""
    if isinstance(condition, ConditionLeaf):
        return evaluate_leaf(condition, user)
    if isinstance(condition, ConditionGroup):
        results = (evaluate(child, user) for child in condition.children)
        return all(results) if condition.op == "and" else any(results)
    if isinstance(condition, ConditionNot):
        return not evaluate(condition.child, user)
    raise TypeError(f"Unknown condition type: {type(condition)!r}")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]
