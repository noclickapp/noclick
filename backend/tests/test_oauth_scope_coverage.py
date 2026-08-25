"""OAuth scope coverage: the requested scopes must cover what operations need.

The bug this pins: ``x-oauth-scopes`` (what the app asks for at connect) was
hand-written and disconnected from the scopes an operation actually needs. The
Slack node shipped 131 operations — 61% of its surface — that could only ever
return ``missing_scope``, plus a trigger whose event scope was never requested.

Three layers, weakest to strongest:

1. **Ratchet** — every node declaring ``x-oauth-scopes`` either has a
   ``scope_registry`` or sits on ``_UNVERIFIED``. That list may only shrink;
   adding a NEW OAuth node without a registry fails here.
2. **Coverage** — for nodes with a registry, the scopes their operations
   require must be a subset of what they request (``Enforcement.SUBSET``), or
   exactly equal for tables verified against provider docs (``STRICT``).
3. **Call-site** — for nodes whose registry keys on API endpoints, every
   endpoint reachable from a dispatched operation must have an entry, derived
   from the AST so a new unscoped operation cannot slip through.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from nodes.core.oauth_scopes import Enforcement, ScopeRegistry
from nodes.core.registry import NODE_REGISTRY

BACKEND = Path(__file__).resolve().parents[1]
NODES_DIR = BACKEND / "nodes"


# Nodes that declare OAuth scopes but have no requirement table yet. Their
# scopes stay hand-written and unverified, which is the status quo — this list
# exists so the gap is COUNTED rather than invisible.
#
# This list may only shrink. Adding an entry means shipping a node whose
# requested scopes nothing checks; migrate it instead.
_UNVERIFIED: frozenset[str] = frozenset()


def _oauth_node_classes() -> dict[str, type]:
    """Registered node classes whose credential model requests OAuth scopes."""
    found = {}
    for node_type, node_cls in NODE_REGISTRY.items():
        try:
            schema = node_cls.get_config_schema()
        except Exception:  # pragma: no cover - a broken schema fails elsewhere
            continue
        if _find_key(schema, "x-oauth-scopes") is not None:
            found[node_type] = node_cls
    return found


def _find_key(obj, key):
    """First value for `key` anywhere in a nested schema, else None."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def _find_all_values(obj, key):
    """Union of EVERY list value for `key` anywhere in a nested schema. A node
    that offers more than one OAuth credential type (e.g. Instagram, which
    supports both Facebook Login and Instagram Login) requests the union of
    those credentials' scopes, so coverage must be judged against the union."""
    out = []
    if isinstance(obj, dict):
        if isinstance(obj.get(key), (list, tuple)):
            out.extend(obj[key])
        for value in obj.values():
            out.extend(_find_all_values(value, key))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(_find_all_values(value, key))
    return out


# ---------------------------------------------------------------------------
# Layer 1 — the ratchet
# ---------------------------------------------------------------------------


def test_every_oauth_node_declares_scope_requirements():
    """A node requesting OAuth scopes must declare what its operations need."""
    oauth_nodes = _oauth_node_classes()
    assert oauth_nodes, "expected to find OAuth nodes in NODE_REGISTRY"

    missing = sorted(
        node_type
        for node_type, node_cls in oauth_nodes.items()
        if node_cls.scope_registry is None and node_type not in _UNVERIFIED
    )
    assert not missing, (
        "These nodes request OAuth scopes with no requirement table, so nothing "
        "verifies the requested scopes cover what their operations call:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd a table under nodes/scopes/ and set `scope_registry` on the "
        "node. See nodes/scopes/slack.py."
    )


def test_scope_registry_attributes_are_registries():
    """`scope_registry` must be a ScopeRegistry, not a bare list of scopes.

    Assigning a list is an easy mistake — the attribute name reads like it
    holds scopes — and it surfaces as an unhelpful AttributeError deep in an
    unrelated test. Fail here with the node named instead.
    """
    wrong = sorted(
        f"{node_type}: {type(node_cls.scope_registry).__name__}"
        for node_type, node_cls in _oauth_node_classes().items()
        if node_cls.scope_registry is not None
        and not isinstance(node_cls.scope_registry, ScopeRegistry)
    )
    assert not wrong, (
        "These nodes set `scope_registry` to something that is not a "
        "ScopeRegistry:\n  " + "\n  ".join(wrong)
    )


def test_unverified_allowlist_only_shrinks():
    """Every allowlisted node must still exist and still lack a registry.

    A stale entry silently re-opens the hole for a node that has since been
    migrated, so the allowlist has to stay honest.
    """
    oauth_nodes = _oauth_node_classes()
    stale = sorted(
        node_type
        for node_type in _UNVERIFIED
        if node_type not in oauth_nodes
        or oauth_nodes[node_type].scope_registry is not None
    )
    assert not stale, (
        "These nodes are on the unverified allowlist but no longer need to be. "
        "Remove them from _UNVERIFIED:\n  " + "\n  ".join(stale)
    )


# ---------------------------------------------------------------------------
# Layer 2 — requested scopes cover required scopes
# ---------------------------------------------------------------------------


def _registry_nodes():
    return [
        (node_type, node_cls)
        for node_type, node_cls in _oauth_node_classes().items()
        if isinstance(node_cls.scope_registry, ScopeRegistry)
    ]


@pytest.mark.parametrize(
    "node_type,node_cls",
    _registry_nodes(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_requested_scopes_cover_requirements(node_type, node_cls):
    registry: ScopeRegistry = node_cls.scope_registry
    schema = node_cls.get_config_schema()

    for variant in sorted(registry.variants()):
        key = "x-oauth-scopes" if variant != "user" else "x-oauth-user-scopes"
        requested = set(_find_all_values(schema, key))
        derived = set(registry.declared_scopes(variant=variant))

        missing = derived - requested
        assert not missing, (
            f"{node_type} ({variant} token): operations require scopes the node "
            f"never requests, so they fail at runtime: {sorted(missing)}"
        )

        if registry.enforcement is Enforcement.STRICT:
            extra = requested - derived
            assert not extra, (
                f"{node_type} ({variant} token): requests scopes no operation "
                f"needs: {sorted(extra)}. Either drop them or, if a live "
                f"credential depends on them, add them to the table's retained "
                f"set with a reason."
            )


@pytest.mark.parametrize(
    "node_type,node_cls",
    _registry_nodes(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_elevated_scopes_are_never_requested_at_connect(node_type, node_cls):
    """Non-standard-tier scopes must stay out of the connect request.

    Slack refuses to install an app requesting `admin.*` scopes outside
    Enterprise Grid, so leaking one into `x-oauth-scopes` breaks OAuth connect
    for every ordinary user of that node.
    """
    registry: ScopeRegistry = node_cls.scope_registry
    schema = node_cls.get_config_schema()
    elevated_tiers = registry.tiers() - {"standard"}

    for variant in sorted(registry.variants()):
        key = "x-oauth-scopes" if variant != "user" else "x-oauth-user-scopes"
        requested = set(_find_all_values(schema, key))
        for tier in sorted(elevated_tiers):
            leaked = requested & set(
                registry.declared_scopes(variant=variant, tier=tier)
            )
            assert not leaked, (
                f"{node_type}: '{tier}' scopes {sorted(leaked)} are in the "
                f"connect request. Elevated scopes must be satisfied by a "
                f"user-supplied credential, not requested for everyone."
            )


# ---------------------------------------------------------------------------
# Layer 3 — Slack call sites (endpoint-keyed registry)
# ---------------------------------------------------------------------------


def _slack_ast():
    source = (NODES_DIR / "slack_node.py").read_text()
    return source, ast.parse(source)


def _endpoints_by_handler(tree) -> dict[str, set[str]]:
    handlers: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        endpoints = {
            call.args[1].value
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "_make_request"
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Constant)
        }
        if endpoints:
            handlers[node.name] = endpoints
    return handlers


def _operation_by_config_class(source, tree) -> dict[str, str]:
    operations = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.AnnAssign)
                and getattr(stmt.target, "id", "") == "operation"
            ):
                literal = ast.get_source_segment(source, stmt.annotation) or ""
                match = re.search(r'"([a-zA-Z0-9_]+)"', literal)
                if match:
                    operations[node.name] = match.group(1)
    return operations


def test_slack_every_called_endpoint_has_a_requirement():
    """No Slack API call may reach a provider without a declared scope."""
    from nodes.scopes.slack import SLACK_SCOPES

    _, tree = _slack_ast()
    called = set().union(*_endpoints_by_handler(tree).values())

    undeclared = sorted(called - SLACK_SCOPES.keys_declared)
    assert not undeclared, (
        "Slack endpoints called with no scope requirement declared — this is "
        "exactly how unusable operations ship:\n  " + "\n  ".join(undeclared)
    )


def test_slack_elevated_operation_sets_match_handlers():
    """The materialized per-tier operation sets must match the handlers.

    The sets exist so `get_config_schema` can mark the picker without
    instantiating a node; this re-derives each tier's set from the handlers so
    the copies cannot rot.
    """
    from nodes.scopes.slack import (
        CONNECT_ADMIN_OPERATIONS,
        CONNECT_ADMIN_TIER,
        GRID_ADMIN_OPERATIONS,
        GRID_ADMIN_TIER,
        SLACK_SCOPES,
    )

    source, tree = _slack_ast()
    handlers = _endpoints_by_handler(tree)
    operations = _operation_by_config_class(source, tree)
    tier_by_endpoint = {
        key: req.tier for key, req in SLACK_SCOPES.elevated().items()
    }
    elevated = set(tier_by_endpoint)

    derived: dict = {}
    straddling = []
    for config_class, handler in re.findall(r"(\w+Config):\s*self\.(_\w+)", source):
        operation = operations.get(config_class)
        endpoints = handlers.get(handler, set())
        if not operation or not endpoints:
            continue
        hits = endpoints & elevated
        if not hits:
            continue
        if len(hits) != len(endpoints) or len({tier_by_endpoint[e] for e in hits}) > 1:
            straddling.append(operation)
            continue
        derived.setdefault(tier_by_endpoint[next(iter(hits))], set()).add(operation)

    assert not straddling, (
        "These operations mix elevated-tier and ordinary (or cross-tier) "
        f"endpoints, so a single credential gate would half-break them: "
        f"{sorted(straddling)}"
    )
    for tier, materialized in (
        (GRID_ADMIN_TIER, set(GRID_ADMIN_OPERATIONS)),
        (CONNECT_ADMIN_TIER, set(CONNECT_ADMIN_OPERATIONS)),
    ):
        got = derived.get(tier, set())
        assert got == materialized, (
            f"The materialized set for tier {tier!r} is out of sync with the "
            "handlers.\n"
            f"  missing from the set: {sorted(got - materialized)}\n"
            f"  stale in the set:     {sorted(materialized - got)}"
        )


def test_slack_elevated_operations_are_marked_in_the_picker():
    """A user must see the tier requirement before wiring the operation up."""
    from nodes.scopes.slack import (
        CONNECT_ADMIN_OPERATIONS,
        CONNECT_ADMIN_TIER,
        GRID_ADMIN_OPERATIONS,
        GRID_ADMIN_TIER,
    )
    from nodes.slack_node import SlackNode

    schema = SlackNode.get_config_schema()
    marked: dict = {}
    for definition in (schema.get("$defs") or {}).values():
        if not isinstance(definition, dict):
            continue
        operation = (definition.get("properties") or {}).get("operation")
        if not isinstance(operation, dict) or "const" not in operation:
            continue
        # The marker must sit on the config class definition, not the nested
        # operation property — that is where NodeConfig.getOptionTierLabel
        # reads it after resolving the $ref. Stamping it on the nested
        # property renders nothing.
        tier = definition.get("x-requires-tier")
        if tier:
            marked.setdefault(tier, set()).add(operation["const"])
            assert definition.get("x-tier-label"), (
                f"{operation['const']}: x-requires-tier without an "
                f"x-tier-label renders no marker in the picker"
            )
    assert marked.get(GRID_ADMIN_TIER, set()) == set(GRID_ADMIN_OPERATIONS)
    assert marked.get(CONNECT_ADMIN_TIER, set()) == set(CONNECT_ADMIN_OPERATIONS)


def test_slack_undeclared_endpoint_raises():
    """The choke point fails loudly rather than returning missing_scope."""
    from nodes.core.oauth_scopes import UndeclaredScopeError
    from nodes.scopes.slack import SLACK_SCOPES

    with pytest.raises(UndeclaredScopeError, match="chat.newMethod"):
        SLACK_SCOPES.require("chat.newMethod")


def test_slack_grid_operation_rejects_oauth_credential():
    """OAuth credentials cannot run Grid-admin methods; the gate says why."""
    from nodes.core.oauth_scopes import CredentialTypeError
    from nodes.scopes.slack import SLACK_SCOPES

    with pytest.raises(CredentialTypeError, match="slack_bot_token"):
        SLACK_SCOPES.enforce_credential_type(
            "admin.users.invite", "slack_oauth"
        )

    # A bot token from the user's own Grid app is accepted.
    requirement = SLACK_SCOPES.enforce_credential_type(
        "admin.users.invite", "slack_bot_token"
    )
    assert requirement.scopes == ("admin.users:write",)


def test_slack_event_scopes_are_requested():
    """Trigger events need scopes no endpoint implies.

    `app_mentions:read` was missing entirely, so `on_app_mention` could never
    fire; the history scopes are needed for `message.*` delivery and an
    endpoint-only derivation would drop them.
    """
    from nodes.slack_node import SlackNode

    schema = SlackNode.get_config_schema()
    requested = set(_find_all_values(schema, "x-oauth-scopes"))
    required = {
        "app_mentions:read",
        "channels:history",
        "groups:history",
        "im:history",
        "mpim:history",
        "reactions:read",
    }
    assert required <= requested, sorted(required - requested)
