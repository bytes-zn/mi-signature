"""Tests for the Jinja2 template engine (validation, rendering, sandbox)."""

import pytest

from app.core.exceptions import ValidationError
from app.core.user_context import KNOWN_USER_VARIABLES, UserContext
from app.templates.engine import TemplateEngine


@pytest.fixture
def engine() -> TemplateEngine:
    return TemplateEngine()


@pytest.fixture
def user() -> UserContext:
    return UserContext(
        first_name="Max",
        last_name="Mustermann",
        display_name="Max Mustermann",
        department="Sales",
        phone="+49 89 1234-56",
        email="max@example.com",
        groups=["Sales-DE", "Management"],
        custom_attributes={"extensionAttribute1": "Munich"},
    )


def test_contract_contains_expected_variables() -> None:
    expected = {
        "first_name",
        "last_name",
        "display_name",
        "department",
        "company",
        "phone",
        "mobile",
        "email",
        "city",
        "country",
        "manager",
        "title",
        "groups",
        "custom_attributes",
    }
    assert expected <= KNOWN_USER_VARIABLES


def test_render_variables(engine: TemplateEngine, user: UserContext) -> None:
    html = engine.render("{{ first_name }} {{ last_name }} - {{ phone }}", user)
    assert html == "Max Mustermann - +49 89 1234-56"


def test_render_condition(engine: TemplateEngine, user: UserContext) -> None:
    source = "{% if department == 'Sales' %}SALES{% else %}OTHER{% endif %}"
    assert engine.render(source, user) == "SALES"
    assert engine.render(source, UserContext(department="IT")) == "OTHER"


def test_render_loop_over_groups(engine: TemplateEngine, user: UserContext) -> None:
    source = "{% for g in groups %}[{{ g }}]{% endfor %}"
    assert engine.render(source, user) == "[Sales-DE][Management]"


def test_render_macro(engine: TemplateEngine, user: UserContext) -> None:
    source = "{% macro line(v) %}<b>{{ v }}</b>{% endmacro %}{{ line(first_name) }}"
    assert engine.render(source, user) == "<b>Max</b>"


def test_custom_filter_initials(engine: TemplateEngine, user: UserContext) -> None:
    assert engine.render("{{ display_name | initials }}", user) == "MM"
    assert engine.render("{{ '' | initials }}", user) == ""


def test_custom_filter_tel(engine: TemplateEngine, user: UserContext) -> None:
    assert engine.render("{{ phone | tel }}", user) == "+4989123456"


def test_custom_attributes(engine: TemplateEngine, user: UserContext) -> None:
    source = "{{ custom_attributes.extensionAttribute1 }}"
    assert engine.render(source, user) == "Munich"


def test_unknown_variable_rejected(engine: TemplateEngine, user: UserContext) -> None:
    with pytest.raises(ValidationError) as exc_info:
        engine.render("{{ nickname }}", user)
    assert exc_info.value.code == "unknown_template_variables"
    assert "nickname" in exc_info.value.message


def test_syntax_error_rejected(engine: TemplateEngine) -> None:
    with pytest.raises(ValidationError):
        engine.validate("{% if %}broken")


def test_sandbox_blocks_unsafe_access(engine: TemplateEngine, user: UserContext) -> None:
    with pytest.raises(ValidationError) as exc_info:
        engine.render("{{ ''.__class__.__mro__ }}", user)
    assert exc_info.value.code == "unsafe_template"


def test_builtin_filters_work(engine: TemplateEngine, user: UserContext) -> None:
    assert engine.render("{{ first_name | upper }}", user) == "MAX"
