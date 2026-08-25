"""
The send-email node (self-notification only).

Containment contract under test:
- the recipient is resolved server-side from the runner's auth.users row —
  there is no recipient config field, so neither a human nor an agent tool
  call can email anyone else;
- a recipient on the trigger domain is refused (no workflow→workflow loops);
- every send is credit-gated BEFORE the send and charged a flat 0.01 credits
  (billing.pricing.EMAIL_SEND_PRICE) after it;
- the body ships in a branded wrapper with workflow provenance and a signed
  one-click disable link (+ RFC 8058 List-Unsubscribe headers);
- the single `send` operation makes the node an agent tool provider
  (send_email__send) with the self-only contract in its description.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from tests.mocks.mock_asyncpg import MockNativePool

import pytest

from billing.pricing import EMAIL_SEND_PRICE
from nodes.send_email_node import (
    SendEmailConfig,
    SendEmailNode,
    SendEmailNodeConfig,
    build_notification_email,
)
from utils.email_reservation_manager import require_inbound_email_domain
from utils.email_unsubscribe import (
    build_disable_url,
    mint_disable_sig,
    verify_disable_sig,
)


@pytest.fixture(autouse=True)
def relay_secret(monkeypatch):
    monkeypatch.setenv("EMAIL_RELAY_SECRET", "test-secret")


def _make_node(**kwargs) -> SendEmailNode:
    return SendEmailNode(
        node_id=kwargs.pop("node_id", "se1"),
        node_type="automation-send-email",
        node_data={},
        config=SendEmailNodeConfig(
            config=SendEmailConfig(subject="Daily report", body="All systems green."),
            credentials=None,
        ),
        sio=None,
        sid=None,
        workflow_id=kwargs.pop("workflow_id", "wf-1"),
        user_id="user-12345678",
        organization_id=kwargs.pop("organization_id", "org-1"),
        **kwargs,
    )


def _pool(email="owner@example.com", workflow_name="Lead Scraper"):
    """One shared pool double for the run: first fetchval resolves the account
    email, second the workflow name. Patched with return_value so repeated
    get_native_pool() calls share the side_effect sequence."""
    pool = MockNativePool()
    pool.fetchval.side_effect = [email, workflow_name]
    return pool


def _email_send_mock():
    from_addr = f"notifications@{require_inbound_email_domain()}"
    return AsyncMock(return_value={
        "message_id": "<message-9@mail.example>",
        "delivery_status": "delivered",
        "to": "owner@example.com",
        "from": from_addr,
    })


@pytest.mark.asyncio
class TestSendEmailNode:
    async def test_sends_to_account_email_and_charges_flat(self):
        node = _make_node()
        tracker = MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())
        send = _email_send_mock()
        with patch("utils.database_pool.get_native_pool", return_value=_pool()), \
             patch("billing.usage_tracker.usage_tracker", tracker), \
             patch("utils.email_sending.send_email", send):
            output = await node.execute({})

        assert output["status"] == "sent"
        assert output["to"] == "owner@example.com"
        expected_from = f"notifications@{require_inbound_email_domain()}"
        assert output["from"] == expected_from
        assert output["subject"] == "Daily report"
        assert output["delivery_status"] == "delivered"

        # Recipient comes from the DB lookup, never from config/arguments.
        send.assert_awaited_once()
        send_kwargs = send.await_args.kwargs
        assert send_kwargs["to"] == "owner@example.com"
        assert send_kwargs["from_addr"] == expected_from
        assert send_kwargs["subject"] == "Daily report"
        assert "All systems green." in send_kwargs["text"]

        tracker.enforce_credit_gate.assert_called_once()
        event = tracker.track_usage_event.call_args.args[0]
        assert event.total_cost == EMAIL_SEND_PRICE
        assert event.usage_subtype == "email/send_node"
        # Raw runner + org — organization attribution policy resolution happens in the tracker.
        assert event.user_id == "user-12345678"
        assert event.organization_id == "org-1"

    async def test_branded_wrapper_provenance_and_disable(self):
        node = _make_node()
        send = _email_send_mock()
        with patch("utils.database_pool.get_native_pool", return_value=_pool()), \
             patch("billing.usage_tracker.usage_tracker", MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())), \
             patch("utils.email_sending.send_email", send):
            await node.execute({})

        kwargs = send.await_args.kwargs
        disable_url = build_disable_url("wf-1", "se1")
        # Text part: body + provenance + disable link.
        assert "All systems green." in kwargs["text"]
        assert "Lead Scraper" in kwargs["text"]
        assert disable_url in kwargs["text"]
        # HTML part: branded shell with the same content (href is
        # attribute-escaped, so & appears as &amp;).
        import html as html_lib
        assert "All systems green." in kwargs["html"]
        assert "NoClick" in kwargs["html"]
        assert html_lib.escape(disable_url, quote=True) in kwargs["html"]
        # RFC 8058 one-click unsubscribe headers.
        headers = kwargs["extra_headers"]
        assert headers["List-Unsubscribe"] == f"<{disable_url}>"
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        # Brand uses the email shell without fetching remote assets. With no
        # attachments configured nothing reaches the transport and nothing
        # references a cid: image either.
        assert kwargs.get("attachments") is None
        assert "cid:" not in kwargs["html"]
        assert "apple-touch-icon.png" not in kwargs["html"]
        assert "https://www.noclick.com" not in kwargs["html"]

    async def test_agent_tool_send_has_no_disable_link(self):
        """run_op's synthetic node id has no canvas node to disable."""
        node = _make_node(node_id="node-op:automation-send-email:send")
        send = _email_send_mock()
        with patch("utils.database_pool.get_native_pool", return_value=_pool()), \
             patch("billing.usage_tracker.usage_tracker", MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())), \
             patch("utils.email_sending.send_email", send):
            await node.execute({})
        kwargs = send.await_args.kwargs
        assert kwargs["extra_headers"] == {}
        assert "Disable these emails" not in kwargs["text"]
        # Provenance still present.
        assert "Lead Scraper" in kwargs["text"]

    async def test_gate_failure_blocks_send(self):
        node = _make_node()
        tracker = MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())
        tracker.enforce_credit_gate.side_effect = RuntimeError("Insufficient credits")
        send = _email_send_mock()
        with patch("utils.database_pool.get_native_pool", return_value=_pool()), \
             patch("billing.usage_tracker.usage_tracker", tracker), \
             patch("utils.email_sending.send_email", send):
            with pytest.raises(RuntimeError, match="Insufficient credits"):
                await node.execute({})
        send.assert_not_awaited()
        tracker.track_usage_event.assert_not_called()

    async def test_trigger_domain_recipient_refused(self):
        node = _make_node()
        tracker = MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())
        send = _email_send_mock()
        domain = require_inbound_email_domain()
        with patch("utils.database_pool.get_native_pool", return_value=_pool(email=f"flow@{domain}")), \
             patch("billing.usage_tracker.usage_tracker", tracker), \
             patch("utils.email_sending.send_email", send):
            with pytest.raises(ValueError, match=domain):
                await node.execute({})
        send.assert_not_awaited()
        tracker.enforce_credit_gate.assert_not_called()

    async def test_missing_account_email_raises(self):
        node = _make_node()
        with patch("utils.database_pool.get_native_pool", return_value=_pool(email=None)):
            with pytest.raises(ValueError, match="No account email"):
                await node.execute({})

    async def test_missing_user_context_raises(self):
        node = _make_node()
        node.user_id = None
        with pytest.raises(ValueError, match="No user context"):
            await node.execute({})

    async def test_send_failure_skips_charge(self):
        node = _make_node()
        tracker = MagicMock(track_usage_event=AsyncMock(), enforce_credit_gate=AsyncMock())
        send = AsyncMock(side_effect=RuntimeError("outbound email send failed: quota"))
        with patch("utils.database_pool.get_native_pool", return_value=_pool()), \
             patch("billing.usage_tracker.usage_tracker", tracker), \
             patch("utils.email_sending.send_email", send):
            with pytest.raises(RuntimeError, match="quota"):
                await node.execute({})
        tracker.track_usage_event.assert_not_called()


# ---------------------------------------------------------------------------
# Branded wrapper (pure)
# ---------------------------------------------------------------------------

class TestNotificationTemplate:
    def test_escapes_html_in_body(self):
        """A script tag is not structural HTML — the body stays in markdown
        mode, where raw HTML is escaped, never interpreted."""
        html, text = build_notification_email(
            "<script>alert(1)</script> & co", "Wf", "https://x/disable"
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<script>alert(1)</script> & co" in text  # text part untouched

    def test_newlines_become_br(self):
        html, _ = build_notification_email("line1\nline2", None, None)
        assert "line1<br>" in html

    def test_markdown_renders_into_wrapper(self):
        body = "### Report\n\n- **SMCI** dropped 28%\n- ORCL fell 5%"
        html, text = build_notification_email(body, "Wf", None)
        assert "<h3" in html and "<li" in html and "<strong>SMCI</strong>" in html
        assert "###" not in html and "**" not in html
        assert body in text  # text alternative keeps the markdown source

    def test_html_body_passes_through(self):
        html, text = build_notification_email(
            "<p>Already <strong>formatted</strong></p>", "Wf", None
        )
        assert "<p>Already <strong>formatted</strong></p>" in html
        assert "&lt;p&gt;" not in html
        assert "Already formatted" in text  # text alternative is tag-stripped

    def test_no_workflow_name_generic_provenance(self):
        _, text = build_notification_email("hi", None, None)
        assert "Sent by your NoClick workflow." in text
        assert "Disable" not in text


# ---------------------------------------------------------------------------
# Disable link (sig + DB op + routes)
# ---------------------------------------------------------------------------

class TestDisableSig:
    def test_roundtrip_and_tamper(self):
        sig = mint_disable_sig("wf-1", "se1")
        assert verify_disable_sig("wf-1", "se1", sig)
        assert not verify_disable_sig("wf-2", "se1", sig)
        assert not verify_disable_sig("wf-1", "other", sig)
        assert not verify_disable_sig("wf-1", "se1", "forged")
        assert not verify_disable_sig("", "", "")

    def test_disable_url_contains_signed_params(self):
        url = build_disable_url("wf-1", "se1")
        assert "wf=wf-1" in url and "node=se1" in url
        assert f"sig={mint_disable_sig('wf-1', 'se1')}" in url


@pytest.mark.asyncio
class TestDisableNodeInWorkflow:
    async def test_sets_disabled_flag_and_saves(self):
        from utils.email_unsubscribe import disable_node_in_workflow

        blob = {"nodes": [{"id": "se1", "type": "automation-send-email", "config": {}}], "edges": []}
        pool = MockNativePool()
        pool.fetchrow.side_effect = None
        pool.fetchrow.return_value = {"name": "Lead Scraper", "workflow": blob}
        with patch("utils.database_pool.get_native_pool", lambda: pool):
            name = await disable_node_in_workflow("wf-1", "se1")
        assert name == "Lead Scraper"
        saved_blob = pool.execute.await_args.args[1]
        node = saved_blob["nodes"][0]
        assert node["config"]["disabled"] is True

    async def test_missing_workflow_or_node_returns_none(self):
        from utils.email_unsubscribe import disable_node_in_workflow

        pool = MockNativePool()
        pool.fetchrow.side_effect = None
        pool.fetchrow.return_value = None
        with patch("utils.database_pool.get_native_pool", lambda: pool):
            assert await disable_node_in_workflow("wf-x", "se1") is None

        pool.fetchrow.return_value = {"name": "W", "workflow": {"nodes": []}}
        with patch("utils.database_pool.get_native_pool", lambda: pool):
            assert await disable_node_in_workflow("wf-1", "ghost") is None
        pool.execute.assert_not_awaited()


class TestDisableRoutes:
    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from utils import email_routes

        monkeypatch.setenv("EMAIL_RELAY_SECRET", "test-secret")
        app = FastAPI()
        app.include_router(email_routes.router)
        return TestClient(app)

    def test_get_disables_and_confirms(self, client):
        sig = mint_disable_sig("wf-1", "se1")
        with patch(
            "utils.email_unsubscribe.disable_node_in_workflow",
            AsyncMock(return_value="Lead Scraper"),
        ) as disable:
            resp = client.get(f"/email/disable?wf=wf-1&node=se1&sig={sig}")
        assert resp.status_code == 200
        assert "Lead Scraper" in resp.text
        disable.assert_awaited_once_with("wf-1", "se1")

    def test_post_one_click(self, client):
        sig = mint_disable_sig("wf-1", "se1")
        with patch(
            "utils.email_unsubscribe.disable_node_in_workflow",
            AsyncMock(return_value="Lead Scraper"),
        ):
            resp = client.post(f"/email/disable?wf=wf-1&node=se1&sig={sig}")
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

    def test_bad_sig_rejected(self, client):
        with patch(
            "utils.email_unsubscribe.disable_node_in_workflow", AsyncMock()
        ) as disable:
            resp = client.get("/email/disable?wf=wf-1&node=se1&sig=forged")
        assert resp.status_code == 403
        disable.assert_not_awaited()

    def test_gone_source_still_200(self, client):
        sig = mint_disable_sig("wf-1", "se1")
        with patch(
            "utils.email_unsubscribe.disable_node_in_workflow",
            AsyncMock(return_value=None),
        ):
            resp = client.get(f"/email/disable?wf=wf-1&node=se1&sig={sig}")
        assert resp.status_code == 200
        assert "no longer exists" in resp.text


# ---------------------------------------------------------------------------
# Agent tool provider (send_email__send)
# ---------------------------------------------------------------------------

class TestAgentToolProvider:
    def test_node_is_op_tool_provider(self):
        from nodes.agent.node_op_tools import node_supports_op_tools

        assert node_supports_op_tools("automation-send-email") is True

    def test_tool_is_explicit_about_self_only_recipient(self):
        from nodes.agent.node_op_tools import build_node_op_tools

        params, configs = build_node_op_tools(
            "automation-send-email", ["send"], node_id="se1", credential_id=None
        )
        (tool,) = params
        assert tool["function"]["name"] == "send_email__send"
        desc = tool["function"]["description"]
        assert "YOUR OWN account email" in desc
        assert "no other" in desc.lower()
        # The model only supplies content — never a recipient.
        props = set(tool["function"]["parameters"]["properties"])
        assert props == {"subject", "body", "attachments"}
        assert not {"to", "recipient", "recipients"} & props
        assert configs["send_email__send"]["tool_type"] == "node_op"


def test_registered_in_node_registry():
    from nodes.core.registry import NODE_REGISTRY

    assert NODE_REGISTRY["automation-send-email"] is SendEmailNode


def test_schema_has_no_recipient_field():
    """The containment IS the schema shape: no `to`/recipient config exists."""
    schema = SendEmailNode.get_config_schema()
    props = schema["$defs"]["SendEmailConfig"]["properties"]
    assert set(props) == {"operation", "subject", "body", "attachments"}
    assert not {"to", "recipient", "recipients", "email"} & set(props)


def test_generated_schema_is_stamped_as_tool_provider():
    """The provider stamp is added at generation time (generate_socket_types)
    and is what the canvas reads to allow top→bottom agent wiring."""
    import json
    from pathlib import Path

    generated = Path(__file__).resolve().parents[2] / "frontend/app/schemas/nodes/send-email.json"
    schema = json.loads(generated.read_text())
    assert schema.get("x-agent-tool-provider") is True
