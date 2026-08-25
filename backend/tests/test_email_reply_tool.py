"""
The agent's locked ``email__reply`` tool (inbound-email trigger reply path).

Containment contract under test:
- the reply token minted at receipt (utils/email_routes.py) is the ONLY thing
  that authorizes a reply — fabricated/stale payloads can't anchor the tool;
- the recipient is locked server-side to the original sender (the model never
  chooses recipients, so the tool can't be repurposed for cold email);
- loop guards (trigger-domain recipients, auto-submitted/bulk senders);
- every send is credit-gated BEFORE the send and charged a flat 0.01 credits
  (billing.pricing.EMAIL_SEND_PRICE) after it.
"""

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from billing.markup import dollars_to_credits
from billing.pricing import EMAIL_SEND_PRICE
from nodes.agent.email_reply import (
    EMAIL_REPLY_TOOL_NAME,
    MAX_REPLIES_PER_RUN,
    build_email_reply_tool,
    execute_email_reply,
)
from nodes.agent_node import AgentNode
from nodes.inbound_email_trigger_node import InboundEmailTriggerNode
from utils import email_reply
from utils.email_reply import (
    build_reply_context,
    build_reply_subject,
    mint_reply_token,
    reply_refusal,
    verify_reply_token,
)


@pytest.fixture(autouse=True)
def relay_secret(monkeypatch):
    monkeypatch.setenv("EMAIL_RELAY_SECRET", "test-secret")


def _trigger_output(**overrides):
    ts = overrides.pop("timestamp", time.time())
    out = {
        "type": "email-trigger",
        "from": "alice@example.com",
        "to": "invoices@noclick.app",
        "subject": "Order #42",
        "text": "Where is my order?",
        "headers": {"message-id": "<abc@mail.example.com>"},
        "timestamp": ts,
    }
    out.update(overrides)
    out.setdefault(
        "reply_token",
        mint_reply_token(
            to_addr=out["to"],
            sender=out["from"],
            message_id=(out.get("headers") or {}).get("message-id"),
            timestamp=ts,
        ),
    )
    return out


# ---------------------------------------------------------------------------
# Reply token
# ---------------------------------------------------------------------------

class TestReplyToken:
    def test_roundtrip(self):
        ts = time.time()
        token = mint_reply_token(
            to_addr="Invoices@noclick.app", sender="alice@example.com",
            message_id="<abc>", timestamp=ts,
        )
        # Case-insensitive on addresses (mint lowercases internally).
        assert verify_reply_token(
            token, to_addr="invoices@noclick.app", sender="ALICE@example.com",
            message_id="<abc>", timestamp=ts,
        )

    @pytest.mark.parametrize("field,value", [
        ("sender", "victim@example.com"),   # retarget = forged recipient
        ("to_addr", "other@noclick.app"),
        ("message_id", "<different>"),
    ])
    def test_tampered_field_fails(self, field, value):
        ts = time.time()
        kwargs = {"to_addr": "invoices@noclick.app", "sender": "alice@example.com",
                  "message_id": "<abc>", "timestamp": ts}
        token = mint_reply_token(**kwargs)
        kwargs[field] = value
        assert not verify_reply_token(token, **kwargs)

    def test_expired_fails(self):
        ts = time.time() - email_reply.REPLY_TOKEN_TTL_SECONDS - 10
        token = mint_reply_token(
            to_addr="invoices@noclick.app", sender="alice@example.com",
            message_id="<abc>", timestamp=ts,
        )
        assert not verify_reply_token(
            token, to_addr="invoices@noclick.app", sender="alice@example.com",
            message_id="<abc>", timestamp=ts,
        )

    def test_missing_token_or_timestamp_fails(self):
        assert not verify_reply_token(
            None, to_addr="a@b", sender="c@d", message_id=None, timestamp=time.time()
        )
        assert not verify_reply_token(
            "x", to_addr="a@b", sender="c@d", message_id=None, timestamp=None
        )

    def test_no_secret_raises(self, monkeypatch):
        monkeypatch.delenv("EMAIL_RELAY_SECRET")
        with pytest.raises(RuntimeError, match="EMAIL_RELAY_SECRET"):
            mint_reply_token(to_addr="a@b", sender="c@d", message_id=None, timestamp=1.0)


# ---------------------------------------------------------------------------
# Reply context + refusal guards
# ---------------------------------------------------------------------------

class TestReplyContext:
    def test_builds_locked_context(self):
        ctx = build_reply_context(_trigger_output())
        assert ctx["to"] == "alice@example.com"
        assert ctx["from_addr"] == "invoices@noclick.app"
        assert ctx["message_id"] == "<abc@mail.example.com>"
        assert reply_refusal(ctx) is None

    @pytest.mark.parametrize("missing", ["from", "to", "reply_token", "timestamp"])
    def test_missing_anchor_field_yields_none(self, missing):
        out = _trigger_output()
        out[missing] = None
        assert build_reply_context(out) is None

    def test_fabricated_payload_is_refused(self):
        """A _triggerPayload hand-written into a saved config has no valid token."""
        out = _trigger_output(reply_token="not-a-real-token")
        refusal = reply_refusal(build_reply_context(out))
        assert refusal and "reply authorization" in refusal

    def test_retargeted_sender_is_refused(self):
        """Replaying a genuine token with a swapped sender must fail."""
        genuine = _trigger_output()
        forged = dict(genuine, **{"from": "victim@example.com"})
        refusal = reply_refusal(build_reply_context(forged))
        assert refusal and "reply authorization" in refusal

    def test_trigger_domain_recipient_is_refused(self):
        out = _trigger_output(**{"from": "other-flow@inbound.example.test"})
        out["reply_token"] = mint_reply_token(
            to_addr=out["to"], sender=out["from"],
            message_id="<abc@mail.example.com>", timestamp=out["timestamp"],
        )
        refusal = reply_refusal(build_reply_context(out))
        assert refusal and "loop" in refusal

    def test_auto_submitted_sender_is_refused(self):
        out = _trigger_output(
            headers={"message-id": "<abc@mail.example.com>", "auto-submitted": "auto-generated"}
        )
        refusal = reply_refusal(build_reply_context(out))
        assert refusal and "auto-submitted" in refusal

    def test_bulk_precedence_is_refused(self):
        out = _trigger_output(
            headers={"message-id": "<abc@mail.example.com>", "precedence": "bulk"}
        )
        refusal = reply_refusal(build_reply_context(out))
        assert refusal and "bulk" in refusal


class TestReplySubject:
    def test_prefixes_re(self):
        assert build_reply_subject("Order #42", None) == "Re: Order #42"

    def test_no_double_re(self):
        assert build_reply_subject("RE: Order #42", None) == "RE: Order #42"

    def test_override_wins(self):
        assert build_reply_subject("Order #42", "Shipped!") == "Shipped!"

    def test_empty_original(self):
        assert build_reply_subject(None, None) == "Re: your email"


# ---------------------------------------------------------------------------
# Tool build
# ---------------------------------------------------------------------------

class TestBuildTool:
    def test_locked_config_and_opaque_params(self):
        pair = build_email_reply_tool("trig1", _trigger_output())
        assert pair is not None
        tool_param, tool_config = pair
        assert tool_param["function"]["name"] == EMAIL_REPLY_TOOL_NAME
        # The model only chooses content — no recipient surface.
        props = tool_param["function"]["parameters"]["properties"]
        assert set(props) == {"body", "subject", "attachment_resource_ids"}
        assert not {"to", "recipient", "recipients"} & set(props)
        assert tool_param["function"]["parameters"]["required"] == ["body"]
        assert tool_config["tool_type"] == "email_reply"
        assert tool_config["node_id"] == "trig1"
        assert tool_config["reply_context"]["to"] == "alice@example.com"
        # CLI harness advertisement mirrors the LLM-facing schema.
        assert tool_config["_parameters"] == tool_param["function"]["parameters"]

    def test_no_token_no_tool(self):
        out = _trigger_output()
        del out["reply_token"]
        out["reply_token"] = None
        assert build_email_reply_tool("trig1", out) is None


# ---------------------------------------------------------------------------
# Agent-side injection (fired trigger wired directly into the agent)
# ---------------------------------------------------------------------------

def _make_agent() -> AgentNode:
    return AgentNode(
        node_id="agent_1", node_type="agent", node_data={}, config=None,
        sio=None, sid=None, workflow_id="test_wf",
    )


def _wire(agent, nodes, edges):
    agent._workflow_nodes = nodes
    agent._workflow_edges = edges


class TestAgentInjection:
    def test_fired_email_trigger_injects_tool(self):
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {"id": "em1", "type": "trigger-email", "config": {"_triggerPayload": {"x": 1}}},
                {"id": "agent_1", "type": "agent", "config": {}},
            ],
            edges=[{"source": "em1", "target": "agent_1"}],
        )
        tool_params, tool_configs, _ = agent._collect_tool_definitions(
            {"em1": _trigger_output()}
        )
        assert EMAIL_REPLY_TOOL_NAME in tool_configs
        assert [t["function"]["name"] for t in tool_params] == [EMAIL_REPLY_TOOL_NAME]

    def test_manual_run_injects_nothing(self):
        """No _triggerPayload → not a fired trigger → no reply capability."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {"id": "em1", "type": "trigger-email", "config": {}},
                {"id": "agent_1", "type": "agent", "config": {}},
            ],
            edges=[{"source": "em1", "target": "agent_1"}],
        )
        _, tool_configs, _ = agent._collect_tool_definitions({"em1": _trigger_output()})
        assert EMAIL_REPLY_TOOL_NAME not in tool_configs

    def test_indirect_trigger_injects_nothing(self):
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {"id": "em1", "type": "trigger-email", "config": {"_triggerPayload": {"x": 1}}},
                {"id": "fn1", "type": "automation-serverless-function", "config": {}},
                {"id": "agent_1", "type": "agent", "config": {}},
            ],
            edges=[
                {"source": "em1", "target": "fn1"},
                {"source": "fn1", "target": "agent_1"},
            ],
        )
        _, tool_configs, _ = agent._collect_tool_definitions(
            {"em1": _trigger_output(), "fn1": {"r": 1}}
        )
        assert EMAIL_REPLY_TOOL_NAME not in tool_configs

    def test_fired_non_email_trigger_injects_nothing(self):
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {"id": "wh1", "type": "trigger-webhook", "config": {"_triggerPayload": {"x": 1}}},
                {"id": "agent_1", "type": "agent", "config": {}},
            ],
            edges=[{"source": "wh1", "target": "agent_1"}],
        )
        _, tool_configs, _ = agent._collect_tool_definitions(
            {"wh1": {"type": "webhook-trigger", "payload": {}}}
        )
        assert EMAIL_REPLY_TOOL_NAME not in tool_configs

    def test_tokenless_output_injects_nothing(self):
        """Fired marker but no verifiable payload (e.g. fabricated config)."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {"id": "em1", "type": "trigger-email", "config": {"_triggerPayload": {"x": 1}}},
                {"id": "agent_1", "type": "agent", "config": {}},
            ],
            edges=[{"source": "em1", "target": "agent_1"}],
        )
        out = _trigger_output()
        out["reply_token"] = None
        _, tool_configs, _ = agent._collect_tool_definitions({"em1": out})
        assert EMAIL_REPLY_TOOL_NAME not in tool_configs


# ---------------------------------------------------------------------------
# resolve_agent_event (email → agent user turn)
# ---------------------------------------------------------------------------

class TestEmailResolveAgentEvent:
    def test_delivers_email_and_threads_per_sender(self):
        out = _trigger_output(attachments=[{
            "name": "inv.pdf", "mime_type": "application/pdf",
            "download_url": "https://r2/inv.pdf",
        }])
        event = InboundEmailTriggerNode.resolve_agent_event(out)
        assert event["conversation_key"] == "alice@example.com"
        assert "Where is my order?" in event["text"]
        assert "Order #42" in event["text"]
        assert "inv.pdf" in event["text"]

    def test_no_sender_delivers_nothing(self):
        assert InboundEmailTriggerNode.resolve_agent_event({"subject": "x"}) is None


# ---------------------------------------------------------------------------
# Execution: guards → gate → send → charge
# ---------------------------------------------------------------------------

def _exec_node():
    node = MagicMock()
    node.user_id = "runner-user"
    node.organization_id = "org-1"
    node.workflow_id = "wf-1"
    node.sio = None
    node.sid = None
    node._email_replies_sent = 0
    return node


def _tool_info():
    return build_email_reply_tool("trig1", _trigger_output())[1]


@pytest.mark.asyncio
class TestExecuteEmailReply:

    async def test_gate_failure_blocks_send(self):
        node = _exec_node()
        tracker = MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())
        tracker.enforce_credit_gate.side_effect = RuntimeError("Insufficient credits")
        send = AsyncMock()
        with patch("billing.usage_tracker.usage_tracker", tracker), \
             patch("utils.email_reply.send_email_reply", send):
            with pytest.raises(RuntimeError, match="Insufficient credits"):
                await execute_email_reply(node, {"body": "hi"}, _tool_info())
        send.assert_not_awaited()
        tracker.track_usage_event.assert_not_called()

    async def test_refused_context_never_reaches_gate_or_send(self):
        node = _exec_node()
        tool_info = _tool_info()
        tool_info["reply_context"]["reply_token"] = "forged"
        tracker = MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())
        send = AsyncMock()
        with patch("billing.usage_tracker.usage_tracker", tracker), \
             patch("utils.email_reply.send_email_reply", send):
            result = await execute_email_reply(node, {"body": "hi"}, tool_info)
        assert result["success"] is False
        assert "Reply refused" in result["error"]
        tracker.enforce_credit_gate.assert_not_called()
        send.assert_not_awaited()

    async def test_per_run_cap(self):
        node = _exec_node()
        node._email_replies_sent = MAX_REPLIES_PER_RUN
        tracker = MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())
        send = AsyncMock()
        with patch("billing.usage_tracker.usage_tracker", tracker), \
             patch("utils.email_reply.send_email_reply", send):
            result = await execute_email_reply(node, {"body": "hi"}, _tool_info())
        assert result["success"] is False
        assert "limit" in result["error"].lower()
        send.assert_not_awaited()

    async def test_empty_body_rejected(self):
        result = await execute_email_reply(_exec_node(), {"body": "  "}, _tool_info())
        assert result["success"] is False
        assert "body" in result["error"].lower()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# Pricing invariant
# ---------------------------------------------------------------------------
