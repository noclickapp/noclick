"""Unit tests for the ScopeRegistry mechanism itself.

test_oauth_scope_coverage.py checks that real nodes use this correctly; these
pin the semantics that check depends on.
"""

from __future__ import annotations

import pytest

from nodes.core.oauth_scopes import (
    ANY_VARIANT,
    CredentialTypeError,
    Enforcement,
    ScopeRegistry,
    ScopeRequirement,
    UndeclaredScopeError,
)


def _registry(**kwargs) -> ScopeRegistry:
    requirements = kwargs.pop(
        "requirements",
        {
            "read_thing": ScopeRequirement(scopes=("thing:read",)),
            "write_thing": ScopeRequirement(scopes=("thing:write",)),
        },
    )
    return ScopeRegistry(provider="test", requirements=requirements, **kwargs)


def test_declared_scopes_is_the_union_sorted():
    registry = _registry()
    assert registry.declared_scopes() == ["thing:read", "thing:write"]


def test_scalar_scope_is_accepted_as_a_single_scope():
    """A bare string must not be exploded into one scope per character."""
    requirement = ScopeRequirement(scopes="thing:read")
    assert requirement.scopes == ("thing:read",)


def test_any_variant_folds_into_every_concrete_variant():
    registry = _registry(
        requirements={
            "post": ScopeRequirement(scopes=("chat:write",), variant=ANY_VARIANT),
            "read_bot": ScopeRequirement(scopes=("bot:read",), variant="bot"),
            "read_user": ScopeRequirement(scopes=("user:read",), variant="user"),
        }
    )
    assert registry.declared_scopes(variant="bot") == ["bot:read", "chat:write"]
    assert registry.declared_scopes(variant="user") == ["chat:write", "user:read"]
    # ANY is a marker, not a token the provider mints.
    assert registry.variants() == frozenset({"bot", "user"})


def test_elevated_tier_is_excluded_from_the_standard_request():
    """The whole point of tiers: an admin scope must not reach the consent
    screen of an ordinary user, because providers refuse the install."""
    registry = _registry(
        requirements={
            "read_thing": ScopeRequirement(scopes=("thing:read",)),
            "nuke_org": ScopeRequirement(scopes=("admin:write",), tier="org_admin"),
        }
    )
    assert registry.declared_scopes() == ["thing:read"]
    assert registry.declared_scopes(tier="org_admin") == ["admin:write"]
    assert set(registry.elevated()) == {"nuke_org"}


def test_extra_scopes_are_added_only_to_the_standard_tier():
    """Event-subscription scopes are required but implied by no endpoint."""
    registry = _registry(extra_scopes={"default": ("events:read",)})
    assert "events:read" in registry.declared_scopes()
    assert "events:read" not in registry.declared_scopes(tier="org_admin")


def test_require_raises_for_an_undeclared_key():
    registry = _registry()
    with pytest.raises(UndeclaredScopeError, match="delete_thing"):
        registry.require("delete_thing")


def test_credential_type_gate_allows_when_unrestricted():
    registry = _registry()
    assert registry.enforce_credential_type("read_thing", "anything") is not None
    assert registry.enforce_credential_type("read_thing", None) is not None


def test_credential_type_gate_rejects_and_names_what_is_needed():
    registry = _registry(
        requirements={
            "nuke_org": ScopeRequirement(
                scopes=("admin:write",),
                tier="org_admin",
                credential_types=("admin_token",),
                note="Bring your own admin token.",
            )
        }
    )
    with pytest.raises(CredentialTypeError) as excinfo:
        registry.enforce_credential_type("nuke_org", "oauth")
    message = str(excinfo.value)
    assert "admin_token" in message
    assert "Bring your own admin token." in message

    assert registry.enforce_credential_type("nuke_org", "admin_token").scopes == (
        "admin:write",
    )


def test_enforcement_defaults_to_subset():
    """Unverified tables must not be able to delete a live credential's scope."""
    assert _registry().enforcement is Enforcement.SUBSET
