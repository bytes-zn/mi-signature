"""Tests for the condition validation (regex safety).

The regular expressions of a rule are validated when the rule is **saved**,
not when it is read: a legacy pattern that is already stored must stay
usable (it simply never matches) instead of breaking the whole rule set.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.rules.conditions import (
    ConditionLeaf,
    parse_conditions,
    validate_condition_tree,
    validate_regex_pattern,
)
from app.rules.schemas import RuleCreate, RuleUpdate

_LEAF = {
    "type": "leaf",
    "field": "department",
    "operator": "regex",
    "value": "^Sales.*$",
}


def _rule(conditions: dict[str, object]) -> RuleCreate:
    return RuleCreate(name="sales-rule", template_id=uuid.uuid4(), conditions=conditions)  # type: ignore[arg-type]


def test_valid_regex_is_accepted() -> None:
    rule = _rule(_LEAF)
    assert isinstance(rule.conditions, ConditionLeaf)


def test_invalid_regex_is_rejected_on_save() -> None:
    with pytest.raises(ValidationError):
        _rule({**_LEAF, "value": "(unclosed"})


def test_regex_with_nested_quantifier_is_rejected_on_save() -> None:
    with pytest.raises(ValidationError):
        _rule({**_LEAF, "value": "(a+)+$"})


def test_regex_that_is_too_long_is_rejected_on_save() -> None:
    with pytest.raises(ValidationError):
        _rule({**_LEAF, "value": "a" * 500})


def test_regex_value_must_be_a_string() -> None:
    with pytest.raises(ValidationError):
        _rule({**_LEAF, "value": ["not", "a", "string"]})


def test_non_regex_operator_is_not_affected() -> None:
    rule = _rule(
        {
            "type": "leaf",
            "field": "department",
            "operator": "contains",
            "value": "(a+)+",
        }
    )
    assert isinstance(rule.conditions, ConditionLeaf)


def test_nested_condition_tree_is_validated() -> None:
    with pytest.raises(ValidationError):
        _rule(
            {
                "type": "group",
                "op": "and",
                "children": [
                    {"type": "leaf", "field": "country", "operator": "equals", "value": "DE"},
                    {**_LEAF, "value": "(a+)+"},
                ],
            }
        )


def test_update_payload_is_validated_too() -> None:
    with pytest.raises(ValidationError):
        RuleUpdate(conditions={**_LEAF, "value": "(a+)+"})  # type: ignore[arg-type]


def test_validate_regex_pattern_returns_the_pattern() -> None:
    assert validate_regex_pattern("^abc$") == "^abc$"


def test_validate_condition_tree_returns_the_condition() -> None:
    condition = ConditionLeaf(field="department", operator="regex", value="^abc$")
    assert validate_condition_tree(condition) is condition


def test_parse_conditions_reads_stored_trees() -> None:
    condition = parse_conditions(
        '{"type": "leaf", "field": "department", "operator": "equals", "value": "Sales"}'
    )
    assert isinstance(condition, ConditionLeaf)
    assert condition.field == "department"


def test_parse_conditions_tolerates_a_legacy_invalid_regex() -> None:
    """Stored conditions must stay readable - they are only checked on save."""
    condition = parse_conditions(
        '{"type": "leaf", "field": "department", "operator": "regex", "value": "(unclosed"}'
    )
    assert isinstance(condition, ConditionLeaf)
