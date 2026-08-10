"""Tests for the rule engine: operators, logic combinators, field resolution."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.user_context import UserContext
from app.rules.conditions import (
    ConditionGroup,
    ConditionLeaf,
    ConditionNot,
    validate_field_name,
)
from app.rules.engine import evaluate, resolve_field


@pytest.fixture
def user() -> UserContext:
    return UserContext(
        first_name="Max",
        last_name="Mustermann",
        department="Sales",
        office="Munich",
        city="Munich",
        country="DE",
        title="Senior Account Manager",
        manager="Erika Chef",
        email="max@example.com",
        groups=["Sales-DE", "Management"],
        custom_attributes={"extensionAttribute1": "Bavaria"},
    )


def leaf(field: str, operator: str, value: object) -> ConditionLeaf:
    return ConditionLeaf(field=field, operator=operator, value=value)  # type: ignore[arg-type]


# --- Operators on string fields ---


def test_equals_case_insensitive(user: UserContext) -> None:
    assert evaluate(leaf("department", "equals", "sales"), user)
    assert not evaluate(leaf("department", "equals", "IT"), user)


def test_contains(user: UserContext) -> None:
    assert evaluate(leaf("title", "contains", "account"), user)
    assert not evaluate(leaf("title", "contains", "director"), user)


def test_starts_with_ends_with(user: UserContext) -> None:
    assert evaluate(leaf("email", "starts_with", "max@"), user)
    assert evaluate(leaf("email", "ends_with", "EXAMPLE.COM"), user)
    assert not evaluate(leaf("email", "starts_with", "erika"), user)


def test_regex(user: UserContext) -> None:
    assert evaluate(leaf("email", "regex", r"^[\w.]+@example\.com$"), user)
    assert not evaluate(leaf("email", "regex", r"@other\.de$"), user)


def test_invalid_regex_is_false(user: UserContext) -> None:
    assert not evaluate(leaf("email", "regex", r"(unclosed"), user)


def test_in_and_not_in(user: UserContext) -> None:
    assert evaluate(leaf("country", "in", ["DE", "AT", "CH"]), user)
    assert not evaluate(leaf("country", "in", ["US", "GB"]), user)
    assert evaluate(leaf("country", "not_in", ["US", "GB"]), user)
    assert not evaluate(leaf("country", "not_in", ["DE", "AT"]), user)


# --- Groups (list field) ---


def test_groups_contains(user: UserContext) -> None:
    assert evaluate(leaf("groups", "contains", "sales-de"), user)
    assert not evaluate(leaf("groups", "contains", "Extern"), user)


def test_groups_in_not_in(user: UserContext) -> None:
    assert evaluate(leaf("groups", "in", ["Extern", "Management"]), user)
    assert evaluate(leaf("groups", "not_in", ["Extern"]), user)
    assert not evaluate(leaf("groups", "not_in", ["Management"]), user)


def test_groups_unsupported_operator_is_false(user: UserContext) -> None:
    assert not evaluate(leaf("groups", "equals", "Sales-DE"), user)


# --- Custom attributes ---


def test_custom_attribute(user: UserContext) -> None:
    assert evaluate(leaf("custom_attributes.extensionAttribute1", "equals", "bavaria"), user)


def test_missing_custom_attribute(user: UserContext) -> None:
    assert not evaluate(leaf("custom_attributes.missing", "equals", "x"), user)
    assert evaluate(leaf("custom_attributes.missing", "not_in", ["x"]), user)


def test_resolve_field(user: UserContext) -> None:
    assert resolve_field(user, "department") == "Sales"
    assert resolve_field(user, "custom_attributes.extensionAttribute1") == "Bavaria"
    assert resolve_field(user, "custom_attributes.nope") is None


# --- Logic combinators ---


def test_and_group(user: UserContext) -> None:
    cond = ConditionGroup(
        op="and",
        children=[
            leaf("department", "equals", "Sales"),
            leaf("country", "equals", "DE"),
        ],
    )
    assert evaluate(cond, user)

    cond.children.append(leaf("title", "contains", "Director"))
    assert not evaluate(cond, user)


def test_or_group(user: UserContext) -> None:
    cond = ConditionGroup(
        op="or",
        children=[
            leaf("department", "equals", "IT"),
            leaf("department", "equals", "Sales"),
        ],
    )
    assert evaluate(cond, user)


def test_not(user: UserContext) -> None:
    cond = ConditionNot(child=leaf("groups", "contains", "Extern"))
    assert evaluate(cond, user)

    cond = ConditionNot(child=leaf("groups", "contains", "Management"))
    assert not evaluate(cond, user)


def test_nested_tree(user: UserContext) -> None:
    """department == Sales AND (country in DACH OR title contains Manager) AND NOT Extern."""
    cond = ConditionGroup(
        op="and",
        children=[
            leaf("department", "equals", "Sales"),
            ConditionGroup(
                op="or",
                children=[
                    leaf("country", "in", ["DE", "AT", "CH"]),
                    leaf("title", "contains", "Manager"),
                ],
            ),
            ConditionNot(child=leaf("groups", "contains", "Extern")),
        ],
    )
    assert evaluate(cond, user)


# --- Field validation ---


def test_validate_field_name_accepts_contract_and_custom() -> None:
    assert validate_field_name("department") == "department"
    assert validate_field_name("custom_attributes.extensionAttribute1").startswith("custom")


def test_validate_field_name_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown condition field"):
        validate_field_name("nickname")


def test_condition_leaf_rejects_unknown_field() -> None:
    with pytest.raises(PydanticValidationError):
        ConditionLeaf(field="nickname", operator="equals", value="x")
