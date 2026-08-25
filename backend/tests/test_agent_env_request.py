"""Builder-declared sandbox env-var requests.

The builder can DECLARE (demand-driven) that an agent needs sandbox env vars via
the canvas-only `agent_env_requested` key, surface the need to the brain, and
collect values from the user — interactively or through a shareable bridge link —
which become an `agent_env` credential (values never touch the graph). Pins the
declaration validation, the brain hint gating, the <ask field="env"> parser, and
the bridge mint/submit path.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── declaration normalization ────────────────────────────────────────────────


def test_normalize_requested_env_vars_shapes():
    from nodes.agent.user_env import normalize_requested_env_vars as n

    assert n('["STRIPE_KEY"]') == ([{"name": "STRIPE_KEY"}], None)
    assert n("STRIPE_KEY") == ([{"name": "STRIPE_KEY"}], None)
    assert n([{"name": "A", "description": "d"}, "A"]) == ([{"name": "A", "description": "d"}], None)
    assert n(None) == ([], None)
    assert n([]) == ([], None)


@pytest.mark.parametrize("bad", [["PATH"], ["NC_X"], ["OPENAI_API_KEY"], ["1BAD"], ["has space"]])
def test_normalize_rejects_reserved_and_malformed(bad):
    from nodes.agent.user_env import normalize_requested_env_vars

    normalized, err = normalize_requested_env_vars(bad)
    assert normalized is None and err


def test_declaration_validated_at_both_ai_chokepoints():
    """A declared name that's reserved/malformed must be rejected in BOTH the MCP
    server and the agentic builder — the two AI write paths."""
    # Agentic builder (execute_field_ops → normalize_requested_env_vars).
    from nodes.agent.user_env import normalize_requested_env_vars

    _, err = normalize_requested_env_vars(["PATH"])
    assert err  # the value both chokepoints raise on

    # Both chokepoints register agent_env_requested as canvas-only (bypasses Pydantic).
    from mcp_server import NoClickMCPServer
    from coder.workflow.agentic.commands import SAME_TURN_FIELD_ALLOWLIST

    assert "agent_env_requested" in NoClickMCPServer._CANVAS_ONLY_CONFIG_KEYS
    assert "agent_env_requested" in SAME_TURN_FIELD_ALLOWLIST


# ── brain hint gating ─────────────────────────────────────────────────────────


def test_env_hint_only_when_declared_and_unfulfilled():
    from coder.workflow.operation_catalog import credential_status_line as c

    # No declaration → no env line (the common case — "not ask in most cases").
    assert "env vars" not in (c("agent", "default", {"model": "openrouter/x"}, "a1") or "")
    # Declared, unfulfilled → needed.
    line = c("agent", "default", {"model": "openrouter/x", "agent_env_requested": ["STRIPE_KEY"]}, "a1")
    assert "[env vars needed: STRIPE_KEY]" in line
    # Fulfilled (agent_env credential attached) → satisfied.
    line2 = c("agent", "default", {
        "model": "openrouter/x",
        "agent_env_requested": ["STRIPE_KEY"],
        "credentialIds": {"agent_env": "cred-1"},
    }, "a1")
    assert "[env vars: STRIPE_KEY ✓]" in line2


def test_env_hint_independent_of_model_credential():
    """A BYOK harness shows BOTH the model-credential need AND the env need."""
    from coder.workflow.operation_catalog import credential_status_line as c

    line = c("agent", "default", {"model": "codex", "agent_env_requested": ["STRIPE_KEY"]}, "a1")
    assert "[credentials needed:" in line and "[env vars needed: STRIPE_KEY]" in line


# ── <ask field="env"> parser ─────────────────────────────────────────────────


def _agent_node(config):
    return SimpleNamespace(id="agent_1", type="agent", operation="default", config=config)


class _GraphState:
    def __init__(self, node):
        self._node = node

    def get_node(self, ref):
        return self._node if ref == self._node.id else None


def _xml_op(**attrs):
    return SimpleNamespace(tag="ask", attrs=attrs, body="")


def test_ask_env_uses_declared_names():
    from coder.workflow.agentic.commands import extract_ask_requests

    gs = _GraphState(_agent_node({"agent_env_requested": [{"name": "STRIPE_KEY", "description": "key"}]}))
    reqs, rej = extract_ask_requests([_xml_op(node="agent_1", field="env")], gs)
    assert not rej
    assert len(reqs) == 1
    r = reqs[0]
    assert r["type"] == "env" and r["fieldKey"] == "env"
    assert r["envKeys"] == [{"name": "STRIPE_KEY", "description": "key"}]
    assert "STRIPE_KEY" in r["label"]


def test_ask_env_rejected_without_declaration():
    """An env ask with nothing declared is rejected — the brain must declare first,
    so the request can't surface an empty form."""
    from coder.workflow.agentic.commands import extract_ask_requests

    gs = _GraphState(_agent_node({}))
    reqs, rej = extract_ask_requests([_xml_op(node="agent_1", field="env")], gs)
    assert not reqs and rej and "agent_env_requested" in rej[0]


# ── bridge: public projection + submit ───────────────────────────────────────


def test_bridge_sanitize_exposes_names_only():
    from utils.builder_bridge import _sanitize_input

    out = _sanitize_input({
        "id": "ask_0", "label": "Provide env", "type": "env",
        "envKeys": [{"name": "STRIPE_KEY", "description": "key"}],
        "nodeId": "agent_1", "fieldKey": "env",
    })
    assert out["type"] == "env"
    assert out["env_keys"] == [{"name": "STRIPE_KEY", "description": "key"}]
    # Server-side fields never leak into the public projection.
    assert "nodeId" not in out and "fieldKey" not in out


def _link_row(inputs):
    now = datetime.now(timezone.utc)
    return {
        "id": "link-1", "user_id": uuid.uuid4(), "workflow_id": uuid.uuid4(),
        "builder_conversation_id": "conv-1", "ask_id": "ask-1",
        "agent_conversation_id": "ck:x", "agent_node_id": "agent_1",
        "inputs": inputs, "workflow_name": "Stripe Agent",
        "created_at": now, "expires_at": now + timedelta(days=7),
    }


@pytest.mark.asyncio
async def test_bridge_submit_env_creates_credential_and_resumes(monkeypatch):
    from utils import builder_bridge_routes as routes
    from utils.builder_bridge_routes import BridgeSubmitBody

    owner = uuid.uuid4()
    new_cred = str(uuid.uuid4())
    link = _link_row([
        {"id": "ask_0", "label": "Provide env", "type": "env", "fieldKey": "env",
         "nodeId": "agent_1", "env_keys": [{"name": "STRIPE_KEY"}], "required": True},
    ])
    link["user_id"] = owner
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.load_pending", AsyncMock(return_value=link)
    )
    monkeypatch.setattr(
        "repositories.builder_bridge.BuilderBridgeRepo.mark_answered", AsyncMock(return_value=True)
    )
    monkeypatch.setattr("utils.builder_bridge_routes.get_native_pool", lambda: MagicMock())
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: MagicMock())

    # The visitor's raw {NAME: value} becomes an agent_env credential (owner-owned);
    # only its id flows onward — values never reach the resume payload.
    seen = {}

    async def _fake_create(raw, *, owner_id, workflow_name):
        seen.update({"raw": raw, "owner_id": owner_id})
        return new_cred

    monkeypatch.setattr(routes, "_create_env_credential", _fake_create)

    resumed = {}

    class FakeHandler:
        def __init__(self, sio):
            pass

        async def handle_input_response(self, sid, data, caller_user_id=None):
            resumed.update({"data": data, "caller_user_id": caller_user_id})

    monkeypatch.setattr(
        "wss.handlers.workflow_builder_handler.WorkflowBuilderHandler", FakeHandler
    )
    spawned = []
    monkeypatch.setattr("utils.async_helpers.spawn", lambda coro, name=None: spawned.append(coro))

    resp = await routes.submit_bridge_answers(
        "link-1", BridgeSubmitBody(values={"ask_0": {"STRIPE_KEY": "sk_live_1"}})
    )
    assert resp == {"success": True}
    assert seen["raw"] == {"STRIPE_KEY": "sk_live_1"} and seen["owner_id"] == str(owner)
    await spawned[0]
    # The resume carries the credential id, NOT the raw secret.
    assert resumed["data"]["values"] == {"ask_0": new_cred}
    assert resumed["caller_user_id"] == str(owner)


# ── resume rendering ──────────────────────────────────────────────────────────


def test_resume_renders_env_as_set_credentials():
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    pending = {"inputs": [
        {"id": "ask_0", "type": "env", "fieldKey": "env", "nodeId": "agent_1", "label": "env"},
    ]}
    out = WorkflowBuilderHandler._format_input_response_content({"ask_0": "cred-99"}, pending)
    assert '<set_credentials node="agent_1" id="cred-99" />' in out
    assert "agent_env" in out  # labeled so the brain knows it's the env bundle
