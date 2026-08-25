"""User-supplied execution environment variables.

Pins validation, credential references, and dispatch-time resolution for the
environment-variable bundle supported by every edition.
"""
import pytest

from nodes.agent.user_env import (
    RESERVED_NAMES,
    describe_user_env,
    is_reserved,
    sanitize_user_env,
)


# ── validation ───────────────────────────────────────────────────────────────


def test_accepts_ordinary_bundle():
    env = {"STRIPE_KEY": "sk_live_1", "API_BASE": "https://api.example.com", "_X": "1"}
    assert sanitize_user_env(env) == env


def test_empty_bundles_are_noops():
    assert sanitize_user_env(None) == {}
    assert sanitize_user_env({}) == {}


@pytest.mark.parametrize("name", ["1LEADING_DIGIT", "HAS-DASH", "HAS SPACE", "a;b", "PATH=x"])
def test_rejects_malformed_names(name):
    with pytest.raises(ValueError, match="Invalid environment variable name"):
        sanitize_user_env({name: "v"})


@pytest.mark.parametrize("name", ["PATH", "HOME", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH"])
def test_rejects_bootstrap_vars(name):
    """These are the ones merge order canNOT protect: no harness sets them, so a
    user value would apply and could break process startup."""
    with pytest.raises(ValueError, match="reserved"):
        sanitize_user_env({name: "/tmp/evil"})


@pytest.mark.parametrize("name", ["NC_INTERNAL_TOKEN", "NC_INTERNAL_URL", "NC_MODEL", "NC_ANYTHING"])
def test_rejects_runtime_control_names(name):
    """NoClick reserves NC_* for runtime-managed settings."""
    with pytest.raises(ValueError, match="reserved"):
        sanitize_user_env({name: "x"})


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_ACCESS_TOKEN"])
def test_rejects_provider_auth(name):
    """Provider keys belong on the separately configured model credential."""
    with pytest.raises(ValueError, match="reserved"):
        sanitize_user_env({name: "x"})


def test_rejects_non_string_value():
    with pytest.raises(ValueError, match="must be a string"):
        sanitize_user_env({"PORT": 8080})


def test_rejects_oversized_value():
    with pytest.raises(ValueError, match="exceeds"):
        sanitize_user_env({"BLOB": "x" * 40_000})


def test_reject_is_loud_not_silent():
    """A rejected var must fail the run, never be dropped: an agent silently
    missing the key it was told to use is far harder to debug than a config error."""
    with pytest.raises(ValueError):
        sanitize_user_env({"GOOD": "1", "PATH": "/evil"})


def test_is_reserved_covers_prefix_and_set():
    assert is_reserved("NC_WHATEVER")
    assert all(is_reserved(n) for n in RESERVED_NAMES)
    assert not is_reserved("STRIPE_KEY")


# ── model-facing description ─────────────────────────────────────────────────


def test_describe_lists_names_never_values():
    note = describe_user_env({"STRIPE_KEY": "sk_live_SECRET", "API_BASE": "https://x"})
    assert "$STRIPE_KEY" in note and "$API_BASE" in note
    assert "sk_live_SECRET" not in note
    assert describe_user_env({}) == ""
    assert describe_user_env(None) == ""


# ── credentialIds is the reference location ──────────────────────────────────


def test_env_credential_is_never_the_primary():
    """agent_env rides the credentialIds map so the delete-impact scan and
    authorize_credentials_for_workflow can see it — but it must never be picked as
    the node's own credential, or insertion order decides whether an agent resolves
    its model key or its env bundle."""
    from utils.credentials import pick_credential_id

    assert pick_credential_id({"agent_env": "B", "agent_anthropic": "A"}) == "A"
    assert pick_credential_id({"agent_anthropic": "A", "agent_env": "B"}) == "A"
    # env vars but no model credential (e.g. openrouter on platform credits)
    assert pick_credential_id({"agent_env": "B"}) is None


def test_env_credential_does_not_satisfy_the_builders_credential_check():
    """node_has_credential gates the builder's "connect an account" request. An
    agent carrying only sandbox env vars still needs its MODEL key, so a
    non-primary credential must not make it look credentialed — otherwise the
    builder silently stops asking and the run fails later on missing credentials.
    """
    from coder.workflow.workflow_ops import node_has_credential

    assert node_has_credential({"credentialIds": {"agent_env": "B"}}) is False
    assert node_has_credential({"credentialIds": {"agent_anthropic": "A"}}) is True
    assert node_has_credential({"credentialIds": {"agent_env": "B", "agent_anthropic": "A"}}) is True


def test_builder_can_reference_the_env_credential_type():
    """`agent_env` must be a KNOWN credential type, or the builder's
    <set_credentials> gate rejects it as invented."""
    from coder.workflow.operation_catalog import known_credential_types

    assert "agent_env" in known_credential_types()


def test_env_credential_is_visible_to_workflow_authorization():
    """The fail-closed owner-fallback gate reads this collector; a reference it
    can't see means collaborator runs fail to resolve the credential."""
    from utils.credentials import collect_node_credential_uuids

    env_id = "22222222-2222-2222-2222-222222222222"
    blob = {"nodes": [{"data": {"credentialIds": {
        "agent_anthropic": "11111111-1111-1111-1111-111111111111",
        "agent_env": env_id,
    }}}]}
    assert env_id in {str(u) for u in collect_node_credential_uuids(blob)}


@pytest.mark.parametrize(
    "node_data,expected",
    [
        ({"credentialIds": {"agent_env": "cred-B"}}, "cred-B"),
        ({"credentialIds": {"agent_anthropic": "cred-A"}}, None),
        ({}, None),
        # unresolved template refs and blanks are not ids
        ({"credentialIds": {"agent_env": "{{vars.X}}"}}, None),
        ({"credentialIds": {"agent_env": "  "}}, None),
    ],
)
def test_env_credential_id_reads_the_map(node_data, expected):
    from nodes import agent_node as an

    node = an.AgentNode.__new__(an.AgentNode)
    node.node_data = node_data
    assert an.AgentNode._env_credential_id(node) == expected


# ── credential blob shapes ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blob,expected",
    [
        ({"credential_type": "agent_env", "env": {"A": "1"}}, {"A": "1"}),
        # Empty bundle: the `env` key's PRESENCE wins, so the wrapper's own keys are
        # never reinterpreted as variables (which would raise on credential_type).
        ({"credential_type": "agent_env", "env": {}}, {}),
        ({"credential_type": "agent_env", "env": None}, {}),
        # Legacy/flat shape, mirroring AgentCredentials.wrap_flat_credentials.
        ({"credential_type": "agent_env", "A": "1"}, {"A": "1"}),
    ],
)
async def test_resolve_user_env_accepts_both_blob_shapes(monkeypatch, blob, expected):
    from nodes import agent_node as an

    node = an.AgentNode.__new__(an.AgentNode)
    node.user_id = "u1"
    node.organization_id = None
    node.workflow_id = "wf1"

    async def _fake_resolve(cred_id, user_id, pool, **kw):
        return blob

    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", _fake_resolve)
    assert await an.AgentNode._resolve_user_env(node, "cred-1", "u1") == expected


@pytest.mark.asyncio
async def test_resolve_user_env_skips_when_unset():
    """No credential configured must not touch the DB at all."""
    from nodes import agent_node as an

    node = an.AgentNode.__new__(an.AgentNode)
    assert await an.AgentNode._resolve_user_env(node, None, "u1") == {}
