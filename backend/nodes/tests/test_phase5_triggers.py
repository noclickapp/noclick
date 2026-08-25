"""Phase 5 app-level fan-out tests — Slack, HubSpot, and OAuth refresh behavior.

Slack/HubSpot deliver every event for the whole NoClick app to one URL, tagged
with a tenant id. Tests cover the signature primitives, the provider adapters
(verify / handshake / parse), the subscription-registering mixin, and the
trigger nodes.

Run: pytest nodes/tests/test_phase5_triggers.py -v
"""

import base64
import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

WF_UUID = str(uuid.uuid4())

import pytest
from unittest.mock import AsyncMock, patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodes.discord_node import DiscordNode
from nodes.github_rest_node import GithubOAuthCredential, GithubRestNode
from nodes.slack_node import (
    SlackNode,
    SlackOAuthCredential,
    SlackBotTokenCredential,
)
from nodes.hubspot_node import HubSpotNode
from nodes.core.webhook_subscriptions import AppEventTriggerMixin
from utils.webhook_signatures import verify_ed25519, verify_hubspot_v3, verify_slack_v0


def _slack_sig(body: bytes, timestamp: str, secret: str) -> str:
    basestring = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()


def _hubspot_sig(method, uri, body, timestamp, secret) -> str:
    basestring = method.encode() + uri.encode() + body + timestamp.encode()
    return base64.b64encode(
        hmac.new(secret.encode(), basestring, hashlib.sha256).digest()
    ).decode()


# ---------------------------------------------------------------------------
# Signature primitives
# ---------------------------------------------------------------------------


class TestSlackSignature:
    def test_valid_signature(self):
        body, secret = b'{"type":"event_callback"}', "slack-secret"
        ts = str(int(time.time()))
        sig = _slack_sig(body, ts, secret)
        assert verify_slack_v0(body, ts, sig, secret) is True

    def test_wrong_secret_rejected(self):
        body = b'{"a":1}'
        ts = str(int(time.time()))
        sig = _slack_sig(body, ts, "right")
        assert verify_slack_v0(body, ts, sig, "wrong") is False

    def test_stale_timestamp_rejected(self):
        body, secret = b'{"a":1}', "slack-secret"
        old_ts = str(int(time.time()) - 3600)  # 1 hour old
        sig = _slack_sig(body, old_ts, secret)
        assert verify_slack_v0(body, old_ts, sig, secret) is False

    def test_tampered_body_rejected(self):
        secret = "slack-secret"
        ts = str(int(time.time()))
        sig = _slack_sig(b'{"original":1}', ts, secret)
        assert verify_slack_v0(b'{"tampered":1}', ts, sig, secret) is False


class TestHubSpotSignature:
    def test_valid_signature(self):
        body, secret = b'[{"portalId":1}]', "hs-secret"
        uri = "https://api.example.test/webhook/app/hubspot"
        ts = str(int(time.time() * 1000))
        sig = _hubspot_sig("POST", uri, body, ts, secret)
        assert verify_hubspot_v3("POST", uri, body, ts, sig, secret) is True

    def test_wrong_secret_rejected(self):
        body = b"[]"
        uri = "https://api.example.test/webhook/app/hubspot"
        ts = str(int(time.time() * 1000))
        sig = _hubspot_sig("POST", uri, body, ts, "right")
        assert verify_hubspot_v3("POST", uri, body, ts, sig, "wrong") is False

    def test_stale_timestamp_rejected(self):
        body, secret = b"[]", "hs-secret"
        uri = "https://api.example.test/webhook/app/hubspot"
        old_ts = str(int(time.time() * 1000) - 3_600_000)
        sig = _hubspot_sig("POST", uri, body, old_ts, secret)
        assert verify_hubspot_v3("POST", uri, body, old_ts, sig, secret) is False


class TestDiscordSignature:
    def test_valid_signature(self):
        body = b'{"application_id":"123","type":1}'
        timestamp = str(int(time.time()))
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes_raw().hex()
        signature = private_key.sign(timestamp.encode() + body).hex()
        assert verify_ed25519(body, timestamp, signature, public_key) is True

    def test_tampered_body_rejected(self):
        original = b'{"application_id":"123","type":1}'
        timestamp = str(int(time.time()))
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes_raw().hex()
        signature = private_key.sign(timestamp.encode() + original).hex()
        assert verify_ed25519(b'{"application_id":"123","type":0}', timestamp, signature, public_key) is False


# ---------------------------------------------------------------------------
# Provider adapters (utils/app_webhooks.py)
# ---------------------------------------------------------------------------


class TestProviderAdapters:
    def test_slack_handshake_echoes_challenge(self):
        from utils.app_webhooks import _slack_handshake

        body = json.dumps(
            {"type": "url_verification", "challenge": "abc123"}
        ).encode()
        assert _slack_handshake(body) == {"challenge": "abc123"}

    def test_slack_handshake_none_for_events(self):
        from utils.app_webhooks import _slack_handshake

        body = json.dumps({"type": "event_callback"}).encode()
        assert _slack_handshake(body) is None

    def test_slack_parse_extracts_team_and_event(self):
        from utils.app_webhooks import _slack_parse

        body = json.dumps(
            {
                "type": "event_callback",
                "team_id": "T123",
                "event": {"type": "app_mention", "text": "hi", "channel": "C7"},
            }
        ).encode()
        events = _slack_parse(body)
        assert len(events) == 1
        tenant_id, event_type, payload, channel = events[0]
        assert tenant_id == "T123"
        assert event_type == "app_mention"
        assert channel == "C7"

    def test_slack_parse_extracts_channel_per_event_shape(self):
        """Different Slack event types carry the channel under different keys."""
        from utils.app_webhooks import _slack_parse

        def _channel_for(event):
            body = json.dumps(
                {"type": "event_callback", "team_id": "T1", "event": event}
            ).encode()
            return _slack_parse(body)[0][3]

        assert _channel_for({"type": "message", "channel": "C1"}) == "C1"
        assert _channel_for({"type": "file_shared", "channel_id": "C2"}) == "C2"
        assert (
            _channel_for({"type": "reaction_added", "item": {"channel": "C3"}})
            == "C3"
        )
        # channel_created carries a channel object, not an id — no scoping.
        assert _channel_for({"type": "channel_created", "channel": {"id": "C4"}}) is None
        # member_joined_channel without a channel -> None.
        assert _channel_for({"type": "member_joined_channel"}) is None

    def test_slack_parse_ignores_non_event_callback(self):
        from utils.app_webhooks import _slack_parse

        assert _slack_parse(json.dumps({"type": "url_verification"}).encode()) == []

    def test_hubspot_parse_handles_event_array(self):
        from utils.app_webhooks import _hubspot_parse

        body = json.dumps(
            [
                {"portalId": 111, "subscriptionType": "contact.creation"},
                {"portalId": 111, "subscriptionType": "deal.creation"},
            ]
        ).encode()
        events = _hubspot_parse(body)
        assert len(events) == 2
        assert events[0] == (
            "111",
            "contact.creation",
            {"portalId": 111, "subscriptionType": "contact.creation"},
            None,
        )

    def test_hubspot_parse_normalizes_generic_object_type_ids(self):
        from utils.app_webhooks import _hubspot_parse

        body = json.dumps(
            [
                {
                    "portalId": 111,
                    "subscriptionType": "object.creation",
                    "objectTypeId": "0-1",
                },
                {
                    "portalId": 111,
                    "eventType": "object.creation",
                    "objectTypeId": "0-3",
                },
                {
                    "portalId": 111,
                    "subscriptionType": "object.creation",
                    "objectTypeId": "0-5",
                },
            ]
        ).encode()

        events = _hubspot_parse(body)
        assert [event[1] for event in events] == [
            "contact.creation",
            "deal.creation",
            "ticket.creation",
        ]

    def test_hubspot_parse_skips_incomplete_events(self):
        from utils.app_webhooks import _hubspot_parse

        body = json.dumps([{"portalId": 111}, {"subscriptionType": "x"}]).encode()
        assert _hubspot_parse(body) == []

    async def test_discord_verify_looks_up_stored_verify_key(self):
        from utils.app_webhooks import _discord_verify

        body = b'{"application_id":"app-1","type":1}'
        timestamp = str(int(time.time()))
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes_raw().hex()
        signature = private_key.sign(timestamp.encode() + body).hex()
        with patch(
            "utils.app_webhooks.get_verification_key",
            new=AsyncMock(return_value=public_key),
        ):
            assert (
                await _discord_verify(
                    object(),
                    body,
                    {
                        "x-signature-ed25519": signature,
                        "x-signature-timestamp": timestamp,
                    },
                    "https://api.example.test/webhook/app/discord",
                )
                is True
            )

    def test_discord_handshake_returns_204_for_app_event_ping(self):
        from utils.app_webhooks import _discord_handshake

        response = _discord_handshake(
            json.dumps({"application_id": "app-1", "type": 0}).encode()
        )
        assert response is not None
        assert response.status_code == 204

    def test_discord_handshake_returns_pong_for_interactions_ping(self):
        from utils.app_webhooks import _discord_handshake

        # Interactions PING has type=1 but NO `event` key
        response = _discord_handshake(
            json.dumps({"application_id": "app-1", "type": 1, "version": 1}).encode()
        )
        assert response is not None
        assert response.status_code == 200
        assert json.loads(response.body) == {"type": 1}

    def test_discord_parse_extracts_application_event(self):
        from utils.app_webhooks import _discord_parse

        body = json.dumps(
            {
                "application_id": "app-1",
                "type": 1,
                "event": {
                    "type": "APPLICATION_AUTHORIZED",
                    "data": {"integration_type": 0},
                },
            }
        ).encode()
        events = _discord_parse(body)
        assert len(events) == 1
        tenant_id, event_type, payload, channel = events[0]
        assert tenant_id == "app-1"
        assert event_type == "APPLICATION_AUTHORIZED"
        assert channel is None

    def test_discord_parse_extracts_slash_command_interaction(self):
        from utils.app_webhooks import _discord_parse

        body = json.dumps(
            {
                "application_id": "app-1",
                "type": 2,
                "channel_id": "chan-42",
                "data": {"name": "notify", "id": "cmd-1"},
            }
        ).encode()
        events = _discord_parse(body)
        assert len(events) == 1
        tenant_id, event_type, payload, channel = events[0]
        assert tenant_id == "app-1"
        assert event_type == "INTERACTION_APPLICATION_COMMAND"
        assert channel == "chan-42"

    def test_discord_ack_returns_deferred_for_slash_command(self):
        from utils.app_webhooks import _discord_ack

        body = json.dumps({"type": 2}).encode()
        response = _discord_ack(body)
        assert response.status_code == 200
        assert json.loads(response.body) == {"type": 5}

    def test_discord_ack_returns_204_for_app_events(self):
        from utils.app_webhooks import _discord_ack

        body = json.dumps({"type": 1, "event": {"type": "APPLICATION_AUTHORIZED"}}).encode()
        response = _discord_ack(body)
        assert response.status_code == 204

    def test_provider_registry(self):
        from utils.app_webhooks import APP_PROVIDERS

        assert set(APP_PROVIDERS) == {"slack", "hubspot", "discord"}
        for adapter in APP_PROVIDERS.values():
            assert {"verify", "handshake", "parse"} <= set(adapter)


class TestAppWebhookPayloadHandler:
    async def test_hubspot_payload_handler_fans_out_without_http(self, monkeypatch):
        from utils.webhook_routes import handle_app_webhook_payload

        secret = "hs-secret"
        uri = "https://trigger-tests.local/webhook/app/hubspot"
        timestamp = str(int(time.time() * 1000))
        body = json.dumps(
            [{
                "portalId": 246305976,
                "subscriptionType": "contact.creation",
                "objectId": 123,
            }]
        ).encode()
        signature = _hubspot_sig("POST", uri, body, timestamp, secret)
        queued = []

        class _FakePool:
            async def fetchrow(self, query, workflow_id):
                return {
                    "workflow": {
                        "nodes": [
                            {
                                "id": "hubspot-trigger",
                                "type": "automation-hubspot",
                                "config": {"operation": "on_contact_created"},
                            },
                            {
                                "id": "log-1",
                                "type": "log",
                                "config": {"message": "triggered"},
                            },
                        ],
                        "edges": [
                            {
                                "source": "hubspot-trigger",
                                "target": "log-1",
                            }
                        ],
                    }
                }

        async def _fake_execute(**kwargs):
            queued.append(kwargs)

        monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", secret)
        with patch(
            "nodes.core.webhook_subscriptions.find_subscriptions",
            new=AsyncMock(
                return_value=[
                    {
                        "workflow_id": "wf-1",
                        "node_id": "hubspot-trigger",
                        "user_id": "user-1",
                    }
                ]
            ),
        ), patch(
            "utils.webhook_routes.get_native_pool",
            return_value=_FakePool(),
        ), patch(
            "utils.webhook_routes._execute_workflow_with_relay",
            new=_fake_execute,
        ):
            response = await handle_app_webhook_payload(
                "hubspot",
                body,
                {
                    "X-HubSpot-Request-Timestamp": timestamp,
                    "X-HubSpot-Signature-v3": signature,
                },
                uri,
            )

        assert response.success is True
        await asyncio.sleep(0)
        assert len(queued) == 1
        assert queued[0]["workflow_id"] == "wf-1"
        assert queued[0]["start_node_id"] == "hubspot-trigger"
        trigger = queued[0]["nodes"][0]
        assert trigger["config"]["_triggerPayload"]["objectId"] == 123


# ---------------------------------------------------------------------------
# Trigger nodes
# ---------------------------------------------------------------------------


class TestTriggerNodes:
    def test_both_use_app_event_mixin(self):
        assert issubclass(SlackNode, AppEventTriggerMixin)
        assert issubclass(HubSpotNode, AppEventTriggerMixin)
        assert issubclass(DiscordNode, AppEventTriggerMixin)
        assert SlackNode._app_provider == "slack"
        assert HubSpotNode._app_provider == "hubspot"
        assert DiscordNode._app_provider == "discord"

    def test_trigger_ops_in_schema(self):
        # Each node exposes per-event trigger ops; verify the schema's trigger
        # ops match the app-event map plus any scheduled-poll trigger ops.
        for node_cls in [SlackNode, HubSpotNode, DiscordNode]:
            expected_ops = set(node_cls._trigger_event_map)
            expected_ops |= set(getattr(node_cls, "_poll_trigger_operations", set()))
            assert expected_ops, f"{node_cls.__name__} has no trigger ops"
            schema = node_cls.get_config_schema()
            trigger_ops = set()
            for definition in schema["$defs"].values():
                op_prop = definition.get("properties", {}).get("operation", {})
                if op_prop.get("x-is-trigger"):
                    trigger_ops.add(op_prop["const"])
            assert trigger_ops == expected_ops

    async def test_slack_resolve_tenant_from_credential(self):
        # team_id on the credential -> no API call needed.
        tenant = await SlackNode._resolve_tenant_id({"team_id": "T999"})
        assert tenant == "T999"

    async def test_hubspot_resolve_tenant_from_credential(self):
        tenant = await HubSpotNode._resolve_tenant_id({"hub_id": 12345})
        assert tenant == "12345"

    async def test_discord_resolve_tenant_from_current_application(self):
        with patch.object(
            DiscordNode,
            "_fetch_current_application",
            new=AsyncMock(return_value={"id": "app-123", "verify_key": "deadbeef"}),
        ):
            tenant = await DiscordNode._resolve_tenant_id(
                {"credential_type": "discord_bot_token", "bot_token": "tok"}
            )
        assert tenant == "app-123"


# ---------------------------------------------------------------------------
# AppEventTriggerMixin.load_field_value — subscription registration
# ---------------------------------------------------------------------------


class TestSubscriptionRegistration:
    async def test_registers_subscriptions(self):
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={"team_id": "T123", "access_token": "tok"}),
        ), patch(
            "utils.webhook_manager._load_workflow_owner_and_nodes",
            new=AsyncMock(return_value=("owner-1", [])),
        ), patch(
            "nodes.core.webhook_subscriptions.get_node_subscriptions",
            new=AsyncMock(return_value=[]),
        ), patch(
            "nodes.core.webhook_subscriptions.save_subscriptions", new=AsyncMock()
        ) as mock_save:
            result = await SlackNode.load_field_value(
                field_name="subscription_status",
                user_id="user-1",
                workflow_id=WF_UUID,
                node_id="n1",
                pool=object(),
                context={"operation": "on_app_mention"},
                credential_ids={"slack_oauth": "cred-1"},
            )
        values = result["values"]
        assert values["trigger_registered"] is True
        mock_save.assert_awaited_once()
        kwargs = mock_save.await_args.kwargs
        assert kwargs["provider"] == "slack"
        assert kwargs["tenant_id"] == "T123"
        assert kwargs["event_types"] == ["app_mention"]
        # Rows are stamped with the workflow OWNER (fire/billing identity),
        # never the session user that happened to open the panel.
        assert kwargs["user_id"] == "owner-1"

    async def test_matching_rows_skip_rewrite(self):
        """Panel re-opens must not churn the table (delete+insert used to
        reset created_at on every open)."""
        existing = [{
            "event_type": "app_mention", "tenant_id": "T123",
            "credential_id": "cred-1", "user_id": "owner-1",
        }]
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={"team_id": "T123", "access_token": "tok"}),
        ), patch(
            "utils.webhook_manager._load_workflow_owner_and_nodes",
            new=AsyncMock(return_value=("owner-1", [])),
        ), patch(
            "nodes.core.webhook_subscriptions.get_node_subscriptions",
            new=AsyncMock(return_value=existing),
        ), patch(
            "nodes.core.webhook_subscriptions.save_subscriptions", new=AsyncMock()
        ) as mock_save:
            result = await SlackNode.load_field_value(
                field_name="subscription_status",
                user_id="user-1",
                workflow_id=WF_UUID,
                node_id="n1",
                pool=object(),
                context={"operation": "on_app_mention"},
                credential_ids={"slack_oauth": "cred-1"},
            )
        assert result["values"]["trigger_registered"] is True
        mock_save.assert_not_awaited()

    async def test_no_credential_yields_unregistered(self):
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=None),
        ):
            result = await SlackNode.load_field_value(
                field_name="subscription_status",
                user_id="user-1",
                workflow_id="wf-1",
                node_id="n1",
                pool=object(),
                context={"operation": "on_channel_message"},
                credential_ids=None,
            )
        assert result["values"]["trigger_registered"] is False
        assert "credential" in result["values"]["trigger_error"].lower()
        # The failure must also surface on the visible status field.
        assert result["values"]["subscription_status"].startswith("⚠")

    async def test_unknown_operation_yields_error(self):
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={"team_id": "T123"}),
        ), patch(
            "utils.webhook_manager._load_workflow_owner_and_nodes",
            new=AsyncMock(return_value=("owner-1", [])),
        ):
            result = await SlackNode.load_field_value(
                field_name="subscription_status",
                user_id="user-1",
                workflow_id=WF_UUID,
                node_id="n1",
                pool=object(),
                context={"operation": "on_bogus_event"},
                credential_ids={"slack_oauth": "cred-1"},
            )
        assert result["values"]["trigger_registered"] is False
        assert "unknown trigger operation" in result["values"]["trigger_error"].lower()

    async def test_cleanup_deletes_subscriptions(self):
        with patch(
            "nodes.core.webhook_subscriptions.delete_subscriptions", new=AsyncMock()
        ) as mock_delete:
            await SlackNode.cleanup_external_webhook(
                object(), "wf-1", "n1", {}, None
            )
        mock_delete.assert_awaited_once()

    async def test_discord_registration_stores_verify_key_and_updates_app(self):
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(
                return_value={
                    "credential_type": "discord_bot_token",
                    "bot_token": "bot-token",
                }
            ),
        ), patch.object(
            DiscordNode,
            "_fetch_current_application",
            new=AsyncMock(return_value={"id": "app-1", "verify_key": "feedface"}),
        ), patch(
            "utils.webhook_manager._load_workflow_owner_and_nodes",
            new=AsyncMock(return_value=("owner-1", [])),
        ), patch(
            "nodes.core.webhook_subscriptions.get_node_subscriptions",
            new=AsyncMock(return_value=[]),
        ), patch(
            "nodes.core.webhook_subscriptions.list_subscriptions_for_tenant",
            new=AsyncMock(return_value=[]),
        ), patch(
            "nodes.core.webhook_subscriptions.save_subscriptions", new=AsyncMock()
        ) as mock_save, patch.object(
            DiscordNode, "_update_event_webhooks", new=AsyncMock()
        ) as mock_update:
            result = await DiscordNode.load_field_value(
                field_name="subscription_status",
                user_id="user-1",
                workflow_id=WF_UUID,
                node_id="n1",
                pool=object(),
                context={"operation": "on_entitlement_create"},
                credential_ids={"discord_bot_token": "cred-1"},
            )
        assert result["values"]["trigger_registered"] is True
        assert result["values"]["subscription_status"] == "Active — listening for ENTITLEMENT_CREATE"
        assert mock_save.await_args.kwargs["tenant_id"] == "app-1"
        assert mock_save.await_args.kwargs["verification_key"] == "feedface"
        assert mock_save.await_args.kwargs["event_types"] == ["ENTITLEMENT_CREATE"]
        mock_update.assert_awaited_once_with(
            {
                "credential_type": "discord_bot_token",
                "bot_token": "bot-token",
            },
            ["ENTITLEMENT_CREATE"],
        )

    async def test_discord_cleanup_reconciles_remaining_events(self):
        with patch(
            "nodes.core.webhook_subscriptions.get_node_subscriptions",
            new=AsyncMock(
                return_value=[
                    {
                        "tenant_id": "app-1",
                        "workflow_id": "wf-1",
                        "node_id": "n1",
                    }
                ]
            ),
        ), patch(
            "nodes.core.webhook_subscriptions.list_subscriptions_for_tenant",
            new=AsyncMock(
                return_value=[
                    {
                        "tenant_id": "app-1",
                        "workflow_id": "wf-1",
                        "node_id": "n1",
                        "event_type": "APPLICATION_AUTHORIZED",
                    },
                    {
                        "tenant_id": "app-1",
                        "workflow_id": "wf-2",
                        "node_id": "n2",
                        "event_type": "ENTITLEMENT_CREATE",
                    },
                ]
            ),
        ), patch.object(
            DiscordNode, "_update_event_webhooks", new=AsyncMock()
        ) as mock_update, patch(
            "nodes.core.webhook_subscriptions.delete_subscriptions", new=AsyncMock()
        ) as mock_delete:
            await DiscordNode.cleanup_external_webhook(
                object(),
                "wf-1",
                "n1",
                {},
                {"credential_type": "discord_bot_token", "bot_token": "bot-token"},
            )
        mock_update.assert_awaited_once_with(
            {"credential_type": "discord_bot_token", "bot_token": "bot-token"},
            ["ENTITLEMENT_CREATE"],
        )
        mock_delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Channel-scoped fan-out — _fire_subscription filters against the live config
# ---------------------------------------------------------------------------


class TestFireSubscriptionChannelFilter:
    async def _fire(self, configured_channel, event_channel):
        """Run _fire_subscription for a one-node workflow; return whether a run
        was queued. configured_channel=None means the config has no channel."""
        from unittest.mock import AsyncMock, MagicMock
        from utils.webhook_routes import _fire_subscription

        config = {"operation": "on_channel_message"}
        if configured_channel is not None:
            config["channel"] = configured_channel
        workflow = {"nodes": [{"id": "n1", "config": config}], "edges": []}

        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"workflow": workflow})
        sub = {"workflow_id": "wf-1", "node_id": "n1", "user_id": "u1"}
        with patch("utils.webhook_routes.get_native_pool", return_value=pool):
            return await _fire_subscription(MagicMock(), sub, {"event": {}}, event_channel)

    async def test_unfiltered_trigger_fires_for_any_channel(self):
        assert await self._fire(None, "C1") is True
        assert await self._fire("", "C1") is True

    async def test_scoped_trigger_fires_only_for_its_channel(self):
        assert await self._fire("C1", "C1") is True

    async def test_scoped_trigger_skips_other_channels(self):
        assert await self._fire("C1", "C2") is False
        # An event with no channel never matches a channel-scoped trigger.
        assert await self._fire("C1", None) is False


# ---------------------------------------------------------------------------
# Slack OAuth token refresh (token rotation)
# ---------------------------------------------------------------------------


def _iso(delta_seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    ).isoformat()


def _slack_oauth_cred() -> SlackOAuthCredential:
    return SlackOAuthCredential(
        access_token="current-token",
        refresh_token="refresh-1",
        expires_at=_iso(-3600),  # expired an hour ago
        team_id="T1",
    )


class TestSlackTokenRefresh:
    def _node(self, credential_id="cid"):
        return SlackNode(
            node_id="n1",
            node_type="automation-slack",
            node_data={"credential_id": credential_id} if credential_id else {},
            config=None,
            user_id="u1",
        )

    async def test_bot_token_returned_as_is(self):
        cred = SlackBotTokenCredential(bot_token="xoxb-123")
        with patch(
            "nodes.slack_node.refresh_access_token", new=AsyncMock()
        ) as mock_refresh:
            token = await self._node()._ensure_fresh_token(cred)
        assert token == "xoxb-123"
        mock_refresh.assert_not_awaited()

    async def test_fresh_oauth_token_not_refreshed(self):
        cred = SlackOAuthCredential(
            access_token="current-token",
            refresh_token="refresh-1",
            expires_at=_iso(3600),  # still valid
        )
        # Bare object(): the fresh path resolves the pool but must never use it.
        with patch(
            "utils.database_pool.get_native_pool", new=lambda: object()
        ), patch(
            "nodes.slack_node.refresh_access_token", new=AsyncMock()
        ) as mock_refresh:
            token = await self._node()._ensure_fresh_token(cred)
        assert token == "current-token"
        mock_refresh.assert_not_awaited()

    @staticmethod
    def _installation_db(access="current-token", refresh="refresh-1", expires_delta=-3600):
        from tests.slack_installation_fakes import _db, _enc

        return _db(installations=[{
            "id": "inst-1", "team_id": "T1", "app_id": "", "client_id": "",
            "installation": _enc({
                "team_id": "T1", "access_token": access,
                "refresh_token": refresh, "expires_at": _iso(expires_delta),
            }),
            "revoked_at": None, "revoked_reason": None, "token_version": 1,
        }])

    @staticmethod
    def _installation_pool_patches(db):
        from tests.slack_installation_fakes import _FakeEncryption, _FakePool

        fake_pool = _FakePool(db)
        return (
            patch("utils.database_pool.get_native_pool", new=lambda: fake_pool),
            patch("utils.encryption.get_encryption", return_value=_FakeEncryption()),
        )

    async def test_expired_token_refreshed_and_persisted(self):
        # The bot chain of record is the workspace slack_installations row:
        # an expired token rotates THERE and the fresh bundle mirrors back
        # onto the in-memory credential model.
        import json

        cred = _slack_oauth_cred()
        db = self._installation_db()
        new = type(
            "T",
            (),
            {
                "access_token": "new-token",
                "expires_at": _iso(3600),
                "refresh_token": "refresh-2",
            },
        )()
        p1, p2 = self._installation_pool_patches(db)
        with p1, p2, patch(
            "nodes.oauth.slack_oauth.refresh_access_token",
            new=AsyncMock(return_value=new),
        ) as mock_refresh:
            token = await self._node()._ensure_fresh_token(cred)
        assert token == "new-token"
        assert cred.access_token == "new-token"
        assert cred.refresh_token == "refresh-2"  # rotated token mirrored in-memory
        mock_refresh.assert_awaited_once_with("refresh-1", None, None)
        persisted = json.loads(db["installations"][0]["installation"])
        assert persisted["refresh_token"] == "refresh-2"  # persisted on the installation
        assert db["installations"][0]["token_version"] == 2

    async def test_concurrent_refresh_is_noop_when_db_already_fresh(self):
        # The local copy is expired but the installation row of record was
        # already rotated by another execution — adopt it, don't rotate again.
        cred = _slack_oauth_cred()
        db = self._installation_db(
            access="db-fresh-token", refresh="refresh-9", expires_delta=3600
        )
        p1, p2 = self._installation_pool_patches(db)
        with p1, p2, patch(
            "nodes.oauth.slack_oauth.refresh_access_token", new=AsyncMock()
        ) as mock_refresh:
            token = await self._node()._ensure_fresh_token(cred)
        assert token == "db-fresh-token"
        mock_refresh.assert_not_awaited()

    async def test_refresh_failure_recovers_from_db(self):
        # A rotating refresh token consumed by another container — the refresh
        # fails, but re-reading the installation row yields the token that
        # container persisted.
        from tests.slack_installation_fakes import _enc

        cred = _slack_oauth_cred()
        db = self._installation_db()

        async def consumed_elsewhere(rt, client_id=None, client_secret=None):
            # Simulate the other container winning: it persisted a fresh
            # bundle to the row of record before our call hit Slack.
            db["installations"][0]["installation"] = _enc({
                "team_id": "T1", "access_token": "other-container-token",
                "refresh_token": "refresh-5", "expires_at": _iso(3600),
            })
            db["installations"][0]["token_version"] += 1
            raise ValueError("invalid_refresh_token")

        p1, p2 = self._installation_pool_patches(db)
        with p1, p2, patch(
            "nodes.oauth.slack_oauth.refresh_access_token",
            new=consumed_elsewhere,
        ):
            token = await self._node()._ensure_fresh_token(cred)
        assert token == "other-container-token"

    async def test_expired_user_token_refreshes_user_fields_only(self):
        cred = SlackOAuthCredential(
            access_token="bot-token",
            refresh_token="bot-refresh",
            expires_at=_iso(3600),
            user_access_token="user-token",
            user_refresh_token="user-refresh-1",
            user_expires_at=_iso(-3600),
        )
        new = type(
            "T",
            (),
            {
                "access_token": "new-user-token",
                "expires_at": _iso(3600),
                "refresh_token": "user-refresh-2",
            },
        )()
        # Bare object(): the DB seams (load/persist) are mocked, so the pool
        # handle is threaded through but never used.
        with patch(
            "utils.database_pool.get_native_pool", new=lambda: object()
        ), patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(
                return_value={
                    "access_token": "bot-token",
                    "refresh_token": "bot-refresh",
                    "expires_at": _iso(3600),
                    "user_access_token": "user-token",
                    "user_refresh_token": "user-refresh-1",
                    "user_expires_at": _iso(-3600),
                }
            ),
        ), patch(
            "nodes.slack_node.refresh_access_token",
            new=AsyncMock(return_value=new),
        ) as mock_refresh, patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ) as mock_persist:
            token = await self._node()._ensure_fresh_token(cred, send_as="user")

        assert token == "new-user-token"
        assert cred.access_token == "bot-token"
        assert cred.refresh_token == "bot-refresh"
        assert cred.user_access_token == "new-user-token"
        assert cred.user_refresh_token == "user-refresh-2"
        mock_refresh.assert_awaited_once_with("user-refresh-1", None, None)
        persisted = mock_persist.await_args.kwargs["new_data"]
        assert persisted["access_token"] == "bot-token"
        assert persisted["user_access_token"] == "new-user-token"

    async def test_expired_user_token_without_refresh_requires_reauth(self):
        cred = SlackOAuthCredential(
            access_token="bot-token",
            refresh_token="bot-refresh",
            expires_at=_iso(3600),
            user_access_token="user-token",
            user_expires_at=_iso(-3600),
        )
        with pytest.raises(ValueError, match="missing a user refresh token"):
            await self._node()._ensure_fresh_token(cred, send_as="user")


class TestGithubTokenRefresh:
    def _node(self, credential_id="cid"):
        return GithubRestNode(
            node_id="n1",
            node_type="automation-github-rest",
            node_data={"credential_id": credential_id} if credential_id else {},
            config=None,
            user_id="u1",
        )

    async def test_fresh_oauth_token_not_refreshed(self):
        cred = GithubOAuthCredential(
            access_token="current-token",
            refresh_token="refresh-1",
            expires_at=_iso(3600),
            login="neo-noclick",
        )
        # Bare object(): the fresh path resolves the pool but must never use it.
        with patch(
            "utils.database_pool.get_native_pool", new=lambda: object()
        ), patch(
            "nodes.oauth.github_oauth.refresh_access_token", new=AsyncMock()
        ) as mock_refresh:
            token = await self._node()._ensure_fresh_token(cred)
        assert token == "current-token"
        mock_refresh.assert_not_awaited()

    async def test_expired_oauth_token_refreshed_and_persisted(self):
        cred = GithubOAuthCredential(
            access_token="current-token",
            refresh_token="refresh-1",
            expires_at=_iso(-3600),
            login="neo-noclick",
        )
        new = type(
            "T",
            (),
            {
                "access_token": "new-token",
                "expires_at": _iso(3600),
                "refresh_token": "refresh-2",
            },
        )()
        # Bare object(): the DB seams (load/persist) are mocked, so the pool
        # handle is threaded through but never used.
        with patch(
            "utils.database_pool.get_native_pool", new=lambda: object()
        ), patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(
                return_value={
                    "access_token": "current-token",
                    "refresh_token": "refresh-1",
                    "expires_at": _iso(-3600),
                }
            ),
        ), patch(
            "nodes.oauth.github_oauth.refresh_access_token",
            new=AsyncMock(return_value=new),
        ) as mock_refresh, patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ) as mock_persist:
            token = await self._node()._ensure_fresh_token(cred)
        assert token == "new-token"
        assert cred.access_token == "new-token"
        assert cred.refresh_token == "refresh-2"
        mock_refresh.assert_awaited_once()
        mock_persist.assert_awaited_once()
