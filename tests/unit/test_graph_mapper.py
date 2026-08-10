"""Tests for the Graph -> UserContext mapping (the Entra contract gate)."""

from app.core.user_context import UserContext
from app.graph.mapper import map_user


def _graph_user(**overrides: object) -> dict:
    base = {
        "id": "abc-123",
        "givenName": "Max",
        "surname": "Mustermann",
        "displayName": "Max Mustermann",
        "jobTitle": "Senior Account Manager",
        "department": "Sales",
        "companyName": "Bytes Commerce UG",
        "officeLocation": "München HQ",
        "city": "München",
        "country": "Deutschland",
        "businessPhones": ["+49 89 1234-56"],
        "mobilePhone": "+49 171 2345678",
        "mail": "max@example.com",
        "userPrincipalName": "max@example.com",
        "onPremisesExtensionAttributes": {
            "extensionAttribute1": "Bavaria",
            "extensionAttribute2": None,
        },
    }
    base.update(overrides)
    return base


def test_full_mapping() -> None:
    ctx = map_user(_graph_user(), "Nico Zeier", ["Sales-Team"])

    assert isinstance(ctx, UserContext)
    assert ctx.first_name == "Max"
    assert ctx.last_name == "Mustermann"
    assert ctx.display_name == "Max Mustermann"
    assert ctx.title == "Senior Account Manager"
    assert ctx.department == "Sales"
    assert ctx.company == "Bytes Commerce UG"
    assert ctx.office == "München HQ"
    assert ctx.city == "München"
    assert ctx.country == "Deutschland"
    assert ctx.phone == "+49 89 1234-56"
    assert ctx.mobile == "+49 171 2345678"
    assert ctx.email == "max@example.com"
    assert ctx.manager == "Nico Zeier"
    assert ctx.groups == ["Sales-Team"]
    assert ctx.custom_attributes == {"extensionAttribute1": "Bavaria"}


def test_empty_attributes_become_empty_strings() -> None:
    ctx = map_user(
        _graph_user(
            givenName=None,
            department=None,
            businessPhones=[],
            mobilePhone=None,
            onPremisesExtensionAttributes=None,
        ),
        "",
        [],
    )
    assert ctx.first_name == ""
    assert ctx.department == ""
    assert ctx.phone == ""
    assert ctx.mobile == ""
    assert ctx.custom_attributes == {}


def test_email_falls_back_to_upn() -> None:
    ctx = map_user(_graph_user(mail=None), "", [])
    assert ctx.email == "max@example.com"


def test_context_serializes_for_storage() -> None:
    ctx = map_user(_graph_user(), "Nico Zeier", ["Sales-Team"])
    data = ctx.model_dump(mode="json")
    assert data["first_name"] == "Max"
    assert data["groups"] == ["Sales-Team"]
