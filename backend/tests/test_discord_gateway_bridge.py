"""Gateway → fan-out: the bridge's edge filtering and delivery, the receiver's
Discord adapter for Gateway envelopes, the node's message triggers (guild-keyed
registration, payload and agent-turn translation), and the open edition's
in-process listener.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nodes.discord_node import DiscordNode
from utils import app_webhooks
from utils import discord_gateway_bridge as bridge_mod
from utils.discord_gateway_bridge import (
    GATEWAY_SIGNATURE_HEADER,
    DiscordGatewayBridge,
    GuildSubscriptionFilter,
    HttpForwarder,
    LocalDiscordListener,
    build_gateway_envelope,
    sign_gateway_body,
)
from utils.webhook_signatures import verify_hmac_sha256_hex

WF = str(uuid.uuid4())
INSTALL_CRED = {
    "credential_type": "discord_bot_install",
    "guild_id": "g1",
    "guild_name": "Acme HQ",
    "access_token": "user-token",
}


def _message(**overrides) -> Dict[str, Any]:
    message = {
        "id": "m1",
        "content": "hello <@bot-1> can you help?",
        "channel_id": "c1",
        "guild_id": "g1",
        "timestamp": "2026-09-03T10:00:00+00:00",
        "author": {"id": "u1", "username": "dana", "global_name": "Dana", "bot": False},
        "member": {"nick": "Dana K"},
        "mentions": [{"id": "bot-1"}],
        "attachments": [{"url": "https://cdn/x.png", "filename": "x.png", "content_type": "image/png", "size": 10}],
        "message_reference": {"message_id": "m0"},
    }
    message.update(overrides)
    return message


def _envelope(**overrides) -> Dict[str, Any]:
    return build_gateway_envelope(
        "MESSAGE_CREATE", _message(**overrides), bot_user_id="bot-1", application_id="app-1"
    )


class FakePool:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                conn = MagicMock()

                async def fetch(sql, *args):
                    if pool.error:
                        raise pool.error
                    return pool.rows
                conn.fetch = fetch
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _Ctx()


class CollectingForwarder:
    def __init__(self) -> None:
        self.bodies: List[bytes] = []

    async def forward(self, body: bytes) -> None:
        self.bodies.append(body)


# ============================================================================
# Bridge: edge filtering + delivery
# ============================================================================


class TestGuildSubscriptionFilter:
    async def test_refresh_reads_subscribed_guilds(self):
        pool = FakePool(rows=[{"tenant_id": "g1"}, {"tenant_id": "g2"}])
        f = GuildSubscriptionFilter(lambda: pool)
        await f.refresh()
        assert f.guild_ids == {"g1", "g2"}
        assert f.allows("g1") and not f.allows("g9") and not f.allows(None)

    async def test_refresh_error_keeps_last_good_set(self):
        pool = FakePool(rows=[{"tenant_id": "g1"}])
        f = GuildSubscriptionFilter(lambda: pool)
        await f.refresh()
        pool.error = RuntimeError("db down")
        await f.refresh()
        assert f.guild_ids == {"g1"}
        assert "db down" in f.last_error


class TestBridgeDispatch:
    def _bridge(self, forwarder, guilds=("g1",)):
        bridge = DiscordGatewayBridge(
            "tok", forwarder=forwarder, pool_getter=lambda: FakePool(), connect=lambda url: None
        )
        bridge.client.status.bot_user_id = "bot-1"
        bridge.client.status.application_id = "app-1"
        bridge._filter.guild_ids = set(guilds)
        return bridge

    async def _drain(self, bridge):
        task = asyncio.create_task(bridge._sender_loop())
        await asyncio.wait_for(bridge._queue.join(), 5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_subscribed_guild_message_is_forwarded_as_envelope(self):
        fwd = CollectingForwarder()
        bridge = self._bridge(fwd)
        await bridge._on_dispatch("MESSAGE_CREATE", _message())
        await self._drain(bridge)
        assert len(fwd.bodies) == 1
        envelope = json.loads(fwd.bodies[0])
        assert envelope["source"] == "gateway"
        assert envelope["t"] == "MESSAGE_CREATE"
        assert envelope["bot_user_id"] == "bot-1"
        assert envelope["application_id"] == "app-1"
        assert envelope["d"]["id"] == "m1"
        assert bridge.counters.forwarded == 1

    async def test_drops_own_dm_unsubscribed_and_other_events(self):
        fwd = CollectingForwarder()
        bridge = self._bridge(fwd)
        await bridge._on_dispatch("MESSAGE_CREATE", _message(author={"id": "bot-1", "bot": True}))
        await bridge._on_dispatch("MESSAGE_CREATE", _message(guild_id=None))
        await bridge._on_dispatch("MESSAGE_CREATE", _message(guild_id="g-other"))
        await bridge._on_dispatch("TYPING_START", {"guild_id": "g1"})
        assert bridge._queue.qsize() == 0
        assert bridge.counters.dropped_own == 1
        assert bridge.counters.dropped_dm == 1
        assert bridge.counters.dropped_unsubscribed == 1

    async def test_queue_overflow_is_counted_not_fatal(self):
        bridge = DiscordGatewayBridge(
            "tok", forwarder=CollectingForwarder(), pool_getter=lambda: FakePool(),
            connect=lambda url: None, queue_size=1,
        )
        bridge._filter.guild_ids = {"g1"}
        await bridge._on_dispatch("MESSAGE_CREATE", _message(id="a"))
        await bridge._on_dispatch("MESSAGE_CREATE", _message(id="b"))
        assert bridge._queue.qsize() == 1
        assert bridge.counters.dropped_overflow == 1

    async def test_forward_failure_is_counted_and_loop_continues(self):
        class Flaky:
            calls = 0

            async def forward(self, body):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("receiver 503")
        fwd = Flaky()
        bridge = self._bridge(fwd)
        await bridge._on_dispatch("MESSAGE_CREATE", _message(id="a"))
        await bridge._on_dispatch("MESSAGE_CREATE", _message(id="b"))
        await self._drain(bridge)
        assert bridge.counters.forward_failures == 1
        assert bridge.counters.forwarded == 1
        assert "receiver 503" in bridge.counters.last_forward_error

    async def test_status_merges_client_and_bridge_counters(self):
        bridge = self._bridge(CollectingForwarder())
        status = bridge.status()
        assert status["state"] == "starting"
        assert status["subscribed_guilds"] == 1
        assert status["forwarded"] == 0 and status["queue_depth"] == 0


class TestHttpForwarder:
    async def test_signs_body_and_posts(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = dict(request.headers)
            seen["body"] = request.content
            return httpx.Response(204)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        fwd = HttpForwarder("https://worker/webhook/app/discord", "s3cret", client=client)
        await fwd.forward(b'{"x":1}')
        assert seen["body"] == b'{"x":1}'
        assert verify_hmac_sha256_hex(b'{"x":1}', "s3cret", seen["headers"][GATEWAY_SIGNATURE_HEADER], prefix="sha256=")

    async def test_4xx_is_not_retried(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(401, text="bad signature")
        fwd = HttpForwarder("https://worker/x", "s", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with pytest.raises(RuntimeError, match="401"):
            await fwd.forward(b"{}")
        assert len(calls) == 1

    async def test_5xx_is_retried_then_raises(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)
        fwd = HttpForwarder("https://worker/x", "s", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            await fwd.forward(b"{}")
        assert len(calls) == bridge_mod.FORWARD_ATTEMPTS

    def test_requires_url_and_secret(self):
        with pytest.raises(ValueError):
            HttpForwarder("", "s")
        with pytest.raises(ValueError):
            HttpForwarder("https://x", "")


async def test_in_process_forwarder_dispatches_without_http():
    with patch("utils.webhook_routes.dispatch_app_events", new=AsyncMock(return_value=1)) as dispatch:
        await bridge_mod.InProcessForwarder().forward(b'{"source":"gateway"}')
    dispatch.assert_awaited_once_with("discord", b'{"source":"gateway"}')


# ============================================================================
# Receiver adapter: verify / parse / dedup id / drop / node filter
# ============================================================================


class TestDiscordGatewayAdapter:
    async def test_verify_accepts_our_hmac_and_rejects_bad_or_missing_secret(self, monkeypatch):
        body = json.dumps(_envelope()).encode()
        headers = {GATEWAY_SIGNATURE_HEADER: sign_gateway_body(body, "relay-secret")}
        monkeypatch.setenv(bridge_mod.GATEWAY_SECRET_ENV, "relay-secret")
        assert await app_webhooks._discord_verify(None, body, headers, "https://x") is True
        assert await app_webhooks._discord_verify(None, body + b" ", headers, "https://x") is False
        monkeypatch.delenv(bridge_mod.GATEWAY_SECRET_ENV)
        assert await app_webhooks._discord_verify(None, body, headers, "https://x") is False

    async def test_verify_without_gateway_header_still_requires_discord_signature(self):
        body = json.dumps({"type": 1, "application_id": "app-1", "event": {"type": "X"}}).encode()
        assert await app_webhooks._discord_verify(None, body, {}, "https://x") is False

    def test_parse_mints_mention_alongside_message(self):
        events = app_webhooks._discord_parse(json.dumps(_envelope()).encode())
        assert [(e[0], e[1], e[3]) for e in events] == [
            ("g1", "MESSAGE_CREATE", "c1"),
            ("g1", "MESSAGE_MENTION", "c1"),
        ]
        assert events[0][2]["d"]["id"] == "m1"

    def test_parse_plain_message_is_not_a_mention(self):
        events = app_webhooks._discord_parse(json.dumps(_envelope(mentions=[])).encode())
        assert [e[1] for e in events] == ["MESSAGE_CREATE"]

    def test_parse_ignores_dms_and_other_gateway_events(self):
        assert app_webhooks._discord_parse(json.dumps(_envelope(guild_id=None)).encode()) == []
        other = build_gateway_envelope("TYPING_START", {"guild_id": "g1"}, bot_user_id="bot-1", application_id="app-1")
        assert app_webhooks._discord_parse(json.dumps(other).encode()) == []

    def test_event_id_is_the_message_id(self):
        assert app_webhooks._discord_event_id(_envelope()) == "m1"
        assert app_webhooks._discord_event_id({"type": 2, "id": "int-1", "application_id": "app-1"}) == "int-1"
        assert app_webhooks._discord_event_id({"type": 1, "application_id": "app-1", "event": {}}) is None

    async def test_drop_event_catches_own_messages(self):
        assert await app_webhooks._discord_drop_event(_envelope(author={"id": "bot-1", "bot": True})) is not None
        assert await app_webhooks._discord_drop_event(_envelope(application_id="app-1", author={"id": "wh", "bot": True})) is not None
        assert await app_webhooks._discord_drop_event(_envelope()) is None
        assert await app_webhooks._discord_drop_event({"type": 2, "application_id": "app-1"}) is None

    def test_node_filter_ignores_bots_by_default(self):
        bot_message = _envelope(author={"id": "b2", "username": "otherbot", "bot": True})
        assert app_webhooks._discord_node_filter({}, bot_message) is not None
        assert app_webhooks._discord_node_filter({"ignore_bots": "true"}, bot_message) is not None
        assert app_webhooks._discord_node_filter({"ignore_bots": "false"}, bot_message) is None
        assert app_webhooks._discord_node_filter({}, _envelope()) is None
        assert app_webhooks._discord_node_filter({}, {"type": 2}) is None

    def test_adapter_declares_its_capabilities(self):
        discord = app_webhooks.APP_PROVIDERS["discord"]
        assert discord["fire_budget"] is True
        assert discord["channel_config_key"] == "channel_id"
        assert discord["node_filter"] is app_webhooks._discord_node_filter
        assert discord["event_id"] is app_webhooks._discord_event_id


class TestDispatchAndFire:
    async def test_mention_message_fires_both_subscriptions_with_distinct_dedup_keys(self, monkeypatch):
        from utils import webhook_routes

        delivered: List[str] = []
        subs = {
            ("discord", "g1", "MESSAGE_CREATE"): [{"provider": "discord", "workflow_id": WF, "node_id": "n-msg", "user_id": "u1"}],
            ("discord", "g1", "MESSAGE_MENTION"): [{"provider": "discord", "workflow_id": WF, "node_id": "n-men", "user_id": "u1"}],
        }
        fired: List[str] = []

        async def fake_fire(tasks, sub, payload, channel):
            fired.append(sub["node_id"])
            return True

        async def find(pool, provider, tenant, event_type):
            return subs.get((provider, tenant, event_type), [])

        async def was_delivered(provider, event_id):
            return event_id in delivered

        async def mark_delivered(provider, event_id):
            delivered.append(event_id)

        with patch("utils.webhook_routes.get_native_pool", return_value=MagicMock()), \
             patch("nodes.core.webhook_subscriptions.find_subscriptions", new=find), \
             patch("utils.app_event_dedup.was_delivered", new=was_delivered), \
             patch("utils.app_event_dedup.mark_delivered", new=mark_delivered), \
             patch("utils.webhook_routes._fire_subscription", new=fake_fire):
            body = json.dumps(_envelope()).encode()
            assert await webhook_routes.dispatch_app_events("discord", body) == 2
            # A replay (RESUME / forwarder retry) of the same message fires nothing.
            assert await webhook_routes.dispatch_app_events("discord", body) == 0
        assert fired == ["n-msg", "n-men"]
        assert delivered == ["MESSAGE_CREATE:m1", "MESSAGE_MENTION:m1"]

    async def _fire(self, config: Dict[str, Any], payload: Dict[str, Any], channel: str | None):
        from utils.webhook_routes import _fire_subscription

        workflow = {"nodes": [{"id": "n1", "config": {"operation": "on_message", **config}}], "edges": []}
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"workflow": workflow})
        tasks = MagicMock()
        sub = {"provider": "discord", "workflow_id": WF, "node_id": "n1", "user_id": "u1"}
        with patch("utils.webhook_routes.get_native_pool", return_value=pool):
            fired = await _fire_subscription(tasks, sub, payload, channel)
        return fired, tasks

    async def test_channel_scope_uses_the_discord_field_name(self):
        assert (await self._fire({"channel_id": "c1"}, _envelope(), "c1"))[0] is True
        assert (await self._fire({"channel_id": "c1"}, _envelope(), "c2"))[0] is False
        assert (await self._fire({}, _envelope(), "c2"))[0] is True

    async def test_ignore_bots_is_read_from_the_live_config(self):
        bot_message = _envelope(author={"id": "b2", "bot": True})
        assert (await self._fire({}, bot_message, "c1"))[0] is False
        assert (await self._fire({"ignore_bots": "false"}, bot_message, "c1"))[0] is True

    async def test_fire_injects_the_envelope_as_trigger_payload(self):
        fired, tasks = await self._fire({}, _envelope(), "c1")
        assert fired is True
        kwargs = tasks.add_task.call_args.kwargs
        trigger = next(n for n in kwargs["nodes"] if n["id"] == "n1")
        assert trigger["config"]["_triggerPayload"]["source"] == "gateway"
        assert kwargs["start_node_id"] == "n1"


# ============================================================================
# Node: registration, payload, agent turn, loaders
# ============================================================================


class TestDiscordNodeMessageTriggers:
    def test_trigger_map_and_gateway_sets(self):
        assert DiscordNode._trigger_event_map["on_message"] == ["MESSAGE_CREATE"]
        assert DiscordNode._trigger_event_map["on_mention"] == ["MESSAGE_MENTION"]
        assert DiscordNode._gateway_trigger_operations == {"on_message", "on_mention"}
        assert set(bridge_mod.SUBSCRIBED_EVENT_TYPES) == DiscordNode._gateway_event_types

    def test_schema_leads_with_the_channel_picker(self):
        schema = DiscordNode.get_config_schema()["$defs"]["DiscordOnMessageConfig"]
        props = list(schema["properties"])
        assert props.index("channel_id") < props.index("subscription_status")
        assert schema["properties"]["channel_id"]["x-dynamic-options"]["field_name"] == "channel_id"
        assert "depends_on" not in schema["properties"]["channel_id"]["x-dynamic-options"]
        assert schema["properties"]["operation"]["x-is-trigger"] is True
        assert schema["properties"]["ignore_bots"]["enum"] == ["true", "false"]

    async def test_registration_keys_rows_by_install_guild_without_provider_calls(self):
        with patch("nodes.core.webhook_subscriptions.get_node_subscriptions", new=AsyncMock(return_value=[])), \
             patch("nodes.core.webhook_subscriptions.save_subscriptions", new=AsyncMock()) as save, \
             patch.object(DiscordNode, "_fetch_current_application", new=AsyncMock()) as fetch_app, \
             patch.object(DiscordNode, "_update_event_webhooks", new=AsyncMock()) as update:
            status = await DiscordNode.register_node_subscriptions(
                object(), user_id="owner", workflow_id=WF, node_id="n1", operation="on_mention",
                credential_id="cred-1", credential=INSTALL_CRED, config={"channel_id": "c1"},
            )
        assert status == "Active — listening for mentions of the bot in channel c1 of Acme HQ"
        kwargs = save.await_args.kwargs
        assert kwargs["tenant_id"] == "g1"
        assert kwargs["event_types"] == ["MESSAGE_MENTION"]
        assert kwargs["user_id"] == "owner" and kwargs["credential_id"] == "cred-1"
        assert kwargs.get("verification_key") is None
        fetch_app.assert_not_awaited()
        update.assert_not_awaited()

    async def test_registration_is_idempotent_on_matching_rows(self):
        rows = [{"event_type": "MESSAGE_CREATE", "credential_id": "cred-1", "user_id": "owner", "tenant_id": "g1"}]
        with patch("nodes.core.webhook_subscriptions.get_node_subscriptions", new=AsyncMock(return_value=rows)), \
             patch("nodes.core.webhook_subscriptions.save_subscriptions", new=AsyncMock()) as save:
            status = await DiscordNode.register_node_subscriptions(
                object(), user_id="owner", workflow_id=WF, node_id="n1", operation="on_message",
                credential_id="cred-1", credential=INSTALL_CRED, config={},
            )
        assert status == "Active — listening for messages in every channel of Acme HQ"
        save.assert_not_awaited()

    async def test_registration_refuses_a_bot_token_credential(self):
        with pytest.raises(ValueError, match="Install bot"):
            await DiscordNode.register_node_subscriptions(
                object(), user_id="owner", workflow_id=WF, node_id="n1", operation="on_message",
                credential_id="cred-1", credential={"credential_type": "discord_bot_token", "bot_token": "t"},
            )

    async def test_cleanup_of_gateway_rows_never_touches_the_application(self):
        rows = [{"event_type": "MESSAGE_CREATE", "tenant_id": "g1", "workflow_id": WF, "node_id": "n1"}]
        with patch("nodes.core.webhook_subscriptions.get_node_subscriptions", new=AsyncMock(return_value=rows)), \
             patch("nodes.core.webhook_subscriptions.delete_subscriptions", new=AsyncMock()) as delete, \
             patch.object(DiscordNode, "_update_event_webhooks", new=AsyncMock()) as update:
            await DiscordNode.cleanup_external_webhook(object(), WF, "n1", {}, None)
        delete.assert_awaited_once()
        update.assert_not_awaited()

    async def test_application_webhook_union_never_includes_gateway_types(self):
        with patch.object(DiscordNode, "_discord_api_request", new=AsyncMock(return_value={})) as req, \
             patch.dict(os.environ, {"APP_WEBHOOK_BASE_URL": "https://hooks.example"}):
            await DiscordNode._update_event_webhooks(
                {"credential_type": "discord_bot_token", "bot_token": "t"},
                ["ENTITLEMENT_CREATE", "MESSAGE_CREATE", "MESSAGE_MENTION"],
            )
        assert req.await_args.kwargs["json_data"]["event_webhooks_types"] == ["ENTITLEMENT_CREATE"]

    def test_gateway_payload_resolves_to_named_fields(self):
        out = DiscordNode.resolve_trigger_payload(_envelope(), {"operation": "on_mention"})
        assert out["event_type"] == "on_mention" and out["status"] == "success"
        assert out["message_id"] == "m1" and out["channel_id"] == "c1" and out["guild_id"] == "g1"
        assert out["content"] == "hello <@bot-1> can you help?"
        assert out["author_display_name"] == "Dana K" and out["author_is_bot"] is False
        assert out["mentions_bot"] is True and out["mentioned_user_ids"] == ["bot-1"]
        assert out["attachments"][0]["url"] == "https://cdn/x.png"
        assert out["reply_to_message_id"] == "m0"
        assert out["message_url"] == "https://discord.com/channels/g1/c1/m1"
        assert out["data"]["source"] == "gateway"

    def test_slash_command_payload_still_resolves(self):
        """Regression: resolve_trigger_payload referenced a poll-trigger set that
        the June removal deleted, so every delivered slash command raised."""
        out = DiscordNode.resolve_trigger_payload(
            {"type": 2, "application_id": "app-1", "channel_id": "c1", "data": {"name": "ask"}},
            {"operation": "on_slash_command"},
        )
        assert out["event_type"] == "on_slash_command" and out["command_name"] == "ask"

    def test_message_becomes_the_agent_turn_keyed_on_the_channel(self):
        out = DiscordNode.resolve_trigger_payload(_envelope(), {"operation": "on_mention"})
        event = DiscordNode.resolve_agent_event(out)
        assert event["conversation_key"] == "c1"
        text = event["text"]
        assert text.startswith("Discord message from Dana K in channel c1 (server g1):")
        assert "hello  can you help?".replace("  ", " ") in text.replace("  ", " ")
        assert "<@bot-1>" not in text
        assert "Attachments: https://cdn/x.png" in text
        assert "a reply to message m0" in text
        assert "send_message_to_channel with channel_id=c1" in text
        assert "message_id=m1" in text

    def test_non_message_events_keep_the_base_delivery(self):
        from nodes.core.base import WorkflowNode

        out = {"event_type": "on_entitlement_create", "channel_id": "c1", "data": {"x": 1}}
        assert DiscordNode.resolve_agent_event(out) == WorkflowNode.resolve_agent_event(out)

    async def test_install_credential_guild_options_are_its_own_server_only(self):
        with patch.object(DiscordNode, "_dynamic_options_request", new=AsyncMock()) as req, \
             patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "platform"}):
            result = await DiscordNode.load_field_options("guild_id", INSTALL_CRED)
        assert result["options"] == [{"value": "g1", "label": "Acme HQ"}]
        req.assert_not_awaited()

    async def test_install_credential_channels_are_scoped_to_its_server(self):
        with patch.object(
            DiscordNode, "_dynamic_options_request",
            new=AsyncMock(return_value=[{"id": "c1", "name": "general", "type": 0}]),
        ) as req, patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "platform"}):
            result = await DiscordNode.load_field_options("channel_id", INSTALL_CRED, context={"operation": "on_message"})
        assert result["options"] == [{"value": "c1", "label": "#general", "metadata": {"type": 0}}]
        assert req.await_args.args[0] == "/guilds/g1/channels"

    def test_scope_registry_covers_the_new_operations(self):
        from nodes.scopes.discord import DISCORD_SCOPES
        for op in ("on_message", "on_mention"):
            assert "bot" in DISCORD_SCOPES.require(op).scopes


# ============================================================================
# Open edition: in-process listener follows the instance key
# ============================================================================


class FakeBridge:
    instances: List["FakeBridge"] = []

    def __init__(self, token, **kwargs):
        self.token = token
        self.kwargs = kwargs
        self.stopped = asyncio.Event()
        FakeBridge.instances.append(self)

    async def run(self):
        await self.stopped.wait()

    async def stop(self):
        self.stopped.set()

    def status(self):
        return {"state": "connected", "token": self.token}


class TestLocalDiscordListener:
    @pytest.fixture(autouse=True)
    def fake_bridge(self, monkeypatch):
        FakeBridge.instances = []
        monkeypatch.setattr(bridge_mod, "DiscordGatewayBridge", FakeBridge)
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    async def test_starts_stops_and_restarts_with_the_token(self, monkeypatch):
        listener = LocalDiscordListener(pool_getter=lambda: None, poll_s=0.01)
        await listener.reconcile()
        assert listener.status()["state"] == "disabled" and not FakeBridge.instances

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok-1")
        await listener.reconcile()
        assert [b.token for b in FakeBridge.instances] == ["tok-1"]
        assert listener.status() == {"state": "connected", "token": "tok-1"}
        await listener.reconcile()  # unchanged token: no churn
        assert len(FakeBridge.instances) == 1

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok-2")  # rotated in Settings
        await listener.reconcile()
        assert FakeBridge.instances[0].stopped.is_set()
        assert [b.token for b in FakeBridge.instances] == ["tok-1", "tok-2"]

        monkeypatch.delenv("DISCORD_BOT_TOKEN")
        await listener.reconcile()
        assert FakeBridge.instances[1].stopped.is_set()
        assert listener.status()["state"] == "disabled"

    async def test_supervisor_task_polls_and_stop_tears_down(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
        listener = LocalDiscordListener(pool_getter=lambda: None, poll_s=0.01)
        listener.start()
        for _ in range(200):
            if FakeBridge.instances:
                break
            await asyncio.sleep(0.01)
        assert FakeBridge.instances and FakeBridge.instances[0].kwargs["forwarder"].__class__.__name__ == "InProcessForwarder"
        await listener.stop()
        assert FakeBridge.instances[0].stopped.is_set()
        assert listener._supervisor is None

    async def test_module_entry_points_wire_the_native_pool(self, monkeypatch):
        monkeypatch.setattr(bridge_mod, "_local_listener", None)
        listener = bridge_mod.start_local_discord_listener()
        assert bridge_mod.local_discord_listener_status()["state"] == "disabled"
        await bridge_mod.stop_local_discord_listener()
        assert listener._supervisor is None
        assert bridge_mod.local_discord_listener_status()["state"] == "disabled"
