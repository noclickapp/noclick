"""App-webhook hardening: event-redelivery dedup + trigger fire budget.

Slack redelivers events on slow ACK (double-firing every subscription), and
no authorship/fingerprint check can see a two-party echo (NoClick posts, an
external bot auto-replies, the foreign reply re-triggers the workflow). The
dedup drops redeliveries; the budget bounds every loop topology.
"""

import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import app_event_dedup, fire_budget
from utils.app_webhooks import _slack_drop_event, _slack_event_id


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def incr(self, key):
        if key not in self.store:
            self.ttls.pop(key, None)  # INCR-created keys have no TTL
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key, seconds, nx=False):
        if nx and key in self.ttls:
            return False
        self.ttls[key] = seconds
        return True

    async def ttl(self, key):
        if key not in self.store:
            return -2
        return self.ttls.get(key, -1)


class SetNoopRedis(FakeRedis):
    """SET NX believes the key is alive (no-op) while INCR finds it gone —
    the expiry-in-the-gap race that mints a TTL-less counter."""

    async def set(self, key, value, ex=None, nx=False):
        return None


class BrokenRedis:
    def __getattr__(self, name):
        async def _fail(*a, **k):
            raise ConnectionError("redis down")
        return _fail


@pytest.fixture
def fake_redis(monkeypatch):
    from utils import redis_client
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "_client", fake)
    return fake


@pytest.fixture
def broken_redis(monkeypatch):
    from utils import redis_client
    monkeypatch.setattr(redis_client, "_client", BrokenRedis())


# ============================================================================
# Event dedup
# ============================================================================

class TestEventDedup:
    async def test_unseen_event_not_duplicate(self, fake_redis):
        assert await app_event_dedup.was_delivered("slack", "Ev1") is False

    async def test_marked_event_is_duplicate(self, fake_redis):
        await app_event_dedup.mark_delivered("slack", "Ev1")
        assert await app_event_dedup.was_delivered("slack", "Ev1") is True
        # TTL is set so entries don't accumulate forever
        assert fake_redis.ttls["appwebhook:delivered:slack:Ev1"] == app_event_dedup.DEDUP_TTL_SECONDS

    async def test_missing_event_id_noop(self, fake_redis):
        await app_event_dedup.mark_delivered("slack", None)
        assert await app_event_dedup.was_delivered("slack", None) is False
        assert fake_redis.store == {}

    async def test_redis_failure_fails_open(self, broken_redis):
        await app_event_dedup.mark_delivered("slack", "Ev1")  # must not raise
        assert await app_event_dedup.was_delivered("slack", "Ev1") is False

    def test_slack_event_id_extractor(self):
        assert _slack_event_id({"event_id": "Ev42", "event": {}}) == "Ev42"
        assert _slack_event_id({"event": {}}) is None

    async def test_malformed_redis_url_never_raises(self, monkeypatch):
        """get_shared_redis must return None (not raise) on a bad REDIS_URL —
        record_self_post runs AFTER a successful Slack send, and a config
        error must not turn a delivered message into a node run failure."""
        from utils import redis_client
        monkeypatch.setattr(redis_client, "_client", None)
        monkeypatch.setattr(redis_client, "_warned_missing", False)
        monkeypatch.setenv("REDIS_URL", "not-a-valid-url")
        assert redis_client.get_shared_redis() is None
        from utils.slack_self_echo import record_self_post
        await record_self_post("C1", "1.0")  # must not raise


# ============================================================================
# Fire budget
# ============================================================================

class TestFireBudget:
    async def test_under_budget_allows(self, fake_redis):
        for _ in range(fire_budget.FIRE_BUDGET_MAX):
            assert await fire_budget.over_fire_budget("wf1", "n1", "C1") is False

    async def test_over_budget_suppresses(self, fake_redis):
        for _ in range(fire_budget.FIRE_BUDGET_MAX):
            await fire_budget.over_fire_budget("wf1", "n1", "C1")
        assert await fire_budget.over_fire_budget("wf1", "n1", "C1") is True

    async def test_budget_scoped_per_node_and_channel(self, fake_redis):
        for _ in range(fire_budget.FIRE_BUDGET_MAX + 1):
            await fire_budget.over_fire_budget("wf1", "n1", "C1")
        # Different channel / node: independent windows
        assert await fire_budget.over_fire_budget("wf1", "n1", "C2") is False
        assert await fire_budget.over_fire_budget("wf1", "n2", "C1") is False

    async def test_window_ttl_set_once(self, fake_redis):
        await fire_budget.over_fire_budget("wf1", "n1", "C1")
        key = "appwebhook:firebudget:wf1:n1:C1"
        assert fake_redis.ttls[key] == fire_budget.FIRE_BUDGET_WINDOW_SECONDS

    async def test_redis_failure_fails_open(self, broken_redis):
        assert await fire_budget.over_fire_budget("wf1", "n1", "C1") is False

    # A TTL-less counter would suppress its channel FOREVER once past the cap
    # (2026-08-31: a WhatsApp trigger's counter stuck at 39 with TTL -1, every
    # inbound message acked 200 and silently dropped). Both mint paths — the
    # SET-NX/INCR expiry race and legacy orphans — must self-heal.

    async def test_orphaned_ttlless_counter_heals_instead_of_suppressing_forever(self, fake_redis):
        key = "appwebhook:firebudget:wf1:n1:C1"
        fake_redis.store[key] = 35  # legacy orphan: over cap, no TTL

        assert await fire_budget.over_fire_budget("wf1", "n1", "C1") is False
        # Reset into a fresh window: count restarted, TTL restored.
        assert fake_redis.store[key] == 1
        assert fake_redis.ttls[key] == fire_budget.FIRE_BUDGET_WINDOW_SECONDS
        assert await fire_budget.over_fire_budget("wf1", "n1", "C1") is False

    async def test_incr_created_key_gets_its_ttl_stamped(self, monkeypatch):
        from utils import redis_client
        redis = SetNoopRedis()
        monkeypatch.setattr(redis_client, "_client", redis)
        key = "appwebhook:firebudget:wf1:n1:C1"

        assert await fire_budget.over_fire_budget("wf1", "n1", "C1") is False
        assert redis.store[key] == 1
        assert redis.ttls[key] == fire_budget.FIRE_BUDGET_WINDOW_SECONDS

    async def test_ttld_counter_over_cap_still_suppresses(self, fake_redis):
        key = "appwebhook:firebudget:wf1:n1:C1"
        fake_redis.store[key] = fire_budget.FIRE_BUDGET_MAX + 5
        fake_redis.ttls[key] = 120  # healthy window, genuinely over budget

        assert await fire_budget.over_fire_budget("wf1", "n1", "C1") is True
        assert fake_redis.store[key] == fire_budget.FIRE_BUDGET_MAX + 6  # not reset


# ============================================================================
# _fire_subscription budget wiring
# ============================================================================

class TestFireSubscriptionBudget:
    def _sub_and_workflow(self):
        sub = {
            "provider": "slack",
            "workflow_id": uuid.uuid4(),
            "node_id": "slack_trigger",
            "user_id": uuid.uuid4(),
        }
        workflow = {"nodes": [{"id": "slack_trigger", "config": {}}], "edges": []}
        return sub, workflow

    async def _fire(self, over_budget: bool):
        from utils.webhook_routes import _fire_subscription
        sub, workflow = self._sub_and_workflow()
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"workflow": workflow})
        tasks = MagicMock()
        with patch("utils.webhook_routes.get_native_pool", return_value=pool), \
             patch("utils.fire_budget.over_fire_budget",
                   new=AsyncMock(return_value=over_budget)):
            fired = await _fire_subscription(tasks, sub, {"event": {}}, "C1")
        return fired, tasks

    async def test_over_budget_suppresses_run(self):
        fired, tasks = await self._fire(over_budget=True)
        assert fired is False
        tasks.add_task.assert_not_called()

    async def test_under_budget_fires(self):
        fired, tasks = await self._fire(over_budget=False)
        assert fired is True
        tasks.add_task.assert_called_once()

    async def test_non_slack_provider_bypasses_budget(self):
        """HubSpot legitimately bursts (bulk imports) — budget is Slack-only."""
        from utils.webhook_routes import _fire_subscription
        sub, workflow = self._sub_and_workflow()
        sub["provider"] = "hubspot"
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"workflow": workflow})
        tasks = MagicMock()
        with patch("utils.webhook_routes.get_native_pool", return_value=pool), \
             patch("utils.fire_budget.over_fire_budget",
                   new=AsyncMock(return_value=True)) as budget:
            fired = await _fire_subscription(tasks, sub, {"event": {}}, None)
        assert fired is True
        budget.assert_not_awaited()


# ============================================================================
# End-to-end: redelivered Slack event fans out exactly once
# ============================================================================

def _signed_headers(body: bytes, secret: str):
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(
        secret.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return {"x-slack-request-timestamp": ts, "x-slack-signature": sig}


class TestRedeliveryEndToEnd:
    SECRET = "test-signing-secret"

    async def test_second_delivery_dropped(self, fake_redis, monkeypatch):
        monkeypatch.setenv("SLACK_SIGNING_SECRET", self.SECRET)
        from utils.webhook_routes import handle_app_webhook_payload
        body = json.dumps({
            "type": "event_callback", "team_id": "T1", "api_app_id": "A1",
            "event_id": "Ev99",
            "event": {"type": "message", "channel": "C1", "ts": "5.0", "user": "U1"},
        }).encode()

        with patch("utils.webhook_routes.get_native_pool", return_value=MagicMock()), \
             patch("nodes.core.webhook_subscriptions.find_subscriptions",
                   new=AsyncMock(return_value=[])) as find_subs:
            await handle_app_webhook_payload(
                "slack", body, _signed_headers(body, self.SECRET), "https://x/app/slack",
            )
            await handle_app_webhook_payload(
                "slack", body, _signed_headers(body, self.SECRET), "https://x/app/slack",
            )
        # First delivery reaches fan-out; the redelivery is dropped by dedup.
        find_subs.assert_awaited_once()

    async def test_dropped_event_marked_delivered(self, fake_redis, monkeypatch):
        """A drop is a final decision: the event_id is marked delivered so a
        redelivery doesn't depend on the drop signal (fingerprint) surviving."""
        monkeypatch.setenv("SLACK_SIGNING_SECRET", self.SECRET)
        from utils import slack_self_echo, app_event_dedup
        from utils.webhook_routes import handle_app_webhook_payload
        await slack_self_echo.record_self_post("C1", "7.0")
        body = json.dumps({
            "type": "event_callback", "team_id": "T1", "api_app_id": "A1",
            "event_id": "Ev7",
            "event": {"type": "message", "channel": "C1", "ts": "7.0", "user": "U1"},
        }).encode()
        with patch("utils.webhook_routes.get_native_pool", return_value=MagicMock()), \
             patch("nodes.core.webhook_subscriptions.find_subscriptions",
                   new=AsyncMock(return_value=[])) as find_subs:
            await handle_app_webhook_payload(
                "slack", body, _signed_headers(body, self.SECRET), "https://x/app/slack",
            )
        find_subs.assert_not_awaited()
        assert await app_event_dedup.was_delivered("slack", "Ev7") is True
