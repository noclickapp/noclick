"""Slack self-trigger loop guard (channel agents replying into their own
trigger channel re-triggered themselves — CLAUDE.md known hazard).

Three layers under test:
1. _slack_parse drops THIS app's own bot-authored message/app_mention events
   (send_as="bot" case) while keeping foreign bots and humans.
2. utils.slack_self_echo fingerprints every message the Slack node creates
   ((channel, ts) in Redis) and is_self_echo_event matches inbound events —
   the only way to identify send_as="user" posts, which carry no authorship.
3. handle_app_webhook_payload consults the provider drop_event hook before
   fan-out; SlackNode._make_request records fingerprints for write endpoints.
"""

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import slack_self_echo
from utils.app_webhooks import _slack_parse, _slack_drop_event


# ============================================================================
# Fakes / helpers
# ============================================================================

class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value

    async def exists(self, key):
        return 1 if key in self.store else 0


class BrokenRedis:
    async def set(self, key, value, ex=None):
        raise ConnectionError("redis down")

    async def exists(self, key):
        raise ConnectionError("redis down")


@pytest.fixture
def fake_redis(monkeypatch):
    from utils import redis_client
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "_client", fake)
    return fake


def _event_callback(event, team_id="T1", api_app_id="A_NOCLICK"):
    return json.dumps({
        "type": "event_callback",
        "team_id": team_id,
        "api_app_id": api_app_id,
        "event": event,
    }).encode()


# ============================================================================
# Layer: _slack_parse own-bot drop
# ============================================================================

class TestSlackParseOwnBotDrop:
    def test_own_bot_message_dropped(self):
        body = _event_callback({
            "type": "message", "channel": "C1", "ts": "1.0",
            "bot_id": "B1", "app_id": "A_NOCLICK", "text": "agent reply",
        })
        assert _slack_parse(body) == []

    def test_own_bot_via_bot_profile_dropped(self):
        body = _event_callback({
            "type": "message", "channel": "C1", "ts": "1.0",
            "bot_id": "B1", "bot_profile": {"app_id": "A_NOCLICK"},
        })
        assert _slack_parse(body) == []

    def test_own_bot_app_mention_dropped(self):
        body = _event_callback({
            "type": "app_mention", "channel": "C1", "ts": "1.0",
            "app_id": "A_NOCLICK", "text": "<@U_BOT> hi",
        })
        assert _slack_parse(body) == []

    def test_foreign_bot_message_kept(self):
        """Agents legitimately react to OTHER apps' bot messages (alert bots)."""
        body = _event_callback({
            "type": "message", "channel": "C1", "ts": "1.0",
            "bot_id": "B2", "app_id": "A_OTHER",
        })
        events = _slack_parse(body)
        assert len(events) == 1
        assert events[0][1] == "message"

    def test_human_message_kept(self):
        body = _event_callback({
            "type": "message", "channel": "C1", "ts": "1.0",
            "user": "U_HUMAN", "text": "hello agent",
        })
        assert len(_slack_parse(body)) == 1

    def test_non_message_events_unaffected(self):
        body = _event_callback({
            "type": "reaction_added", "user": "U1",
            "item": {"channel": "C1", "ts": "1.0"},
        })
        events = _slack_parse(body)
        assert len(events) == 1
        assert events[0][3] == "C1"  # channel extraction still works


# ============================================================================
# Layer: fingerprint store + event matching
# ============================================================================

class TestSelfEchoFingerprints:
    async def test_recorded_post_matches_message_event(self, fake_redis):
        await slack_self_echo.record_self_post("C1", "111.222")
        assert await slack_self_echo.is_self_echo_event(
            {"type": "message", "channel": "C1", "ts": "111.222"}
        ) is True

    async def test_unrecorded_message_no_match(self, fake_redis):
        assert await slack_self_echo.is_self_echo_event(
            {"type": "message", "channel": "C1", "ts": "999.0"}
        ) is False

    async def test_app_mention_of_self_post_matches(self, fake_redis):
        """A self-post that @mentions the bot fires app_mention with the same ts."""
        await slack_self_echo.record_self_post("C1", "111.222")
        assert await slack_self_echo.is_self_echo_event(
            {"type": "app_mention", "channel": "C1", "ts": "111.222"}
        ) is True

    async def test_message_changed_nested_ts_matches(self, fake_redis):
        """chat.update fires a message_changed event whose edited-message ts is
        nested under event.message.ts (event.ts is the edit-event's own ts)."""
        await slack_self_echo.record_self_post("C1", "111.222")
        assert await slack_self_echo.is_self_echo_event({
            "type": "message", "subtype": "message_changed", "channel": "C1",
            "ts": "333.444", "message": {"ts": "111.222", "text": "edited"},
        }) is True

    async def test_other_event_types_never_match(self, fake_redis):
        await slack_self_echo.record_self_post("C1", "111.222")
        assert await slack_self_echo.is_self_echo_event(
            {"type": "reaction_added", "channel": "C1", "ts": "111.222"}
        ) is False

    async def test_redis_failure_fails_open(self, monkeypatch):
        """A Redis blip must fire the event (today's behavior), not eat it —
        and recording must never raise into the send path."""
        from utils import redis_client
        monkeypatch.setattr(redis_client, "_client", BrokenRedis())
        await slack_self_echo.record_self_post("C1", "1.0")  # must not raise
        assert await slack_self_echo.is_self_echo_event(
            {"type": "message", "channel": "C1", "ts": "1.0"}
        ) is False

    async def test_no_redis_url_fails_open(self, monkeypatch):
        from utils import redis_client
        monkeypatch.setattr(redis_client, "_client", None)
        monkeypatch.delenv("REDIS_URL", raising=False)
        await slack_self_echo.record_self_post("C1", "1.0")
        assert await slack_self_echo.is_self_echo_event(
            {"type": "message", "channel": "C1", "ts": "1.0"}
        ) is False

    async def test_record_ignores_missing_fields(self, fake_redis):
        await slack_self_echo.record_self_post(None, "1.0")
        await slack_self_echo.record_self_post("C1", None)
        assert fake_redis.store == {}


class TestSlackDropEventHook:
    async def test_returns_reason_for_self_post(self, fake_redis):
        await slack_self_echo.record_self_post("C1", "1.0")
        payload = {"event": {"type": "message", "channel": "C1", "ts": "1.0"}}
        reason = await _slack_drop_event(payload)
        assert reason is not None and "C1" in reason

    async def test_returns_none_for_human_message(self, fake_redis):
        payload = {"event": {"type": "message", "channel": "C1", "ts": "2.0"}}
        assert await _slack_drop_event(payload) is None


# ============================================================================
# Layer: end-to-end through handle_app_webhook_payload (real signature)
# ============================================================================

def _signed_headers(body: bytes, secret: str):
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(
        secret.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return {"x-slack-request-timestamp": ts, "x-slack-signature": sig}


class TestHandleAppWebhookPayload:
    SECRET = "test-signing-secret"

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", self.SECRET)

    async def _post(self, body: bytes):
        from utils.webhook_routes import handle_app_webhook_payload
        with patch("utils.webhook_routes.get_native_pool", return_value=MagicMock()), \
             patch("nodes.core.webhook_subscriptions.find_subscriptions",
                   new=AsyncMock(return_value=[])) as find_subs:
            await handle_app_webhook_payload(
                "slack", body, _signed_headers(body, self.SECRET), "https://x/app/slack",
            )
        return find_subs

    async def test_self_posted_event_never_reaches_fanout(self, fake_redis):
        await slack_self_echo.record_self_post("C1", "10.0")
        body = _event_callback({
            "type": "message", "channel": "C1", "ts": "10.0", "user": "U_CONNECTOR",
        })
        find_subs = await self._post(body)
        find_subs.assert_not_awaited()

    async def test_human_message_reaches_fanout(self, fake_redis):
        body = _event_callback({
            "type": "message", "channel": "C1", "ts": "11.0", "user": "U_HUMAN",
        })
        find_subs = await self._post(body)
        find_subs.assert_awaited_once()


# ============================================================================
# Layer: SlackNode._make_request records fingerprints on write endpoints
# ============================================================================

class TestMakeRequestRecordsFingerprint:
    def _node(self):
        from nodes.slack_node import SlackNode
        node = SlackNode.__new__(SlackNode)
        node.node_id = "slack1"
        node.node_type = "automation-slack"
        node.node_data = {}
        node.sio = None
        node.sid = None
        node.workflow_id = None
        node._ensure_fresh_token = AsyncMock(return_value="xoxp-test")
        return node

    def _http_client(self, response_json):
        response = MagicMock()
        response.status_code = 200
        response.content = b"x"
        response.json.return_value = response_json
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    async def _call(self, endpoint, response_json):
        node = self._node()
        ctx = self._http_client(response_json)
        with patch("nodes.slack_node.httpx.AsyncClient", return_value=ctx), \
             patch("utils.slack_self_echo.record_self_post", new=AsyncMock()) as rec:
            await node._make_request(
                "POST", endpoint, credentials=MagicMock(),
                json_body={"channel": "C1"}, action_name="t", send_as="user",
            )
        return rec

    async def test_post_message_recorded(self):
        rec = await self._call(
            "chat.postMessage", {"ok": True, "channel": "C1", "ts": "42.1"},
        )
        rec.assert_awaited_once_with("C1", "42.1")

    async def test_update_recorded(self):
        rec = await self._call(
            "chat.update", {"ok": True, "channel": "C1", "ts": "42.1"},
        )
        rec.assert_awaited_once_with("C1", "42.1")

    async def test_delete_not_recorded(self):
        rec = await self._call(
            "chat.delete", {"ok": True, "channel": "C1", "ts": "42.1"},
        )
        rec.assert_not_awaited()
