"""Opt-in guarded dispatch must not change existing provider semantics."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx
from fastapi import FastAPI, HTTPException

from utils import app_event_dedup, app_webhooks, webhook_routes
from nodes.core import webhook_subscriptions


@pytest.fixture
def guarded(monkeypatch):
    state = {"done": False, "exits": [], "ids": []}

    @asynccontextmanager
    async def guard(event_id):
        state["ids"].append(event_id)
        try:
            yield not state["done"]
        except BaseException:
            state["exits"].append("failed")
            raise
        else:
            state["done"] = True
            state["exits"].append("completed")

    payload = {"account_id": "111", "event_id": "111:msg1"}
    adapter = {
        "parse": lambda body: [("111", "messages", payload, "222")],
        "event_id": lambda data: data["event_id"],
        "event_guard": guard,
    }
    monkeypatch.setitem(app_webhooks.APP_PROVIDERS, "guarded-test", adapter)
    monkeypatch.setattr(webhook_routes, "get_native_pool", lambda: MagicMock())
    subscriptions = AsyncMock(return_value=[{"node_id": "one"}, {"node_id": "two"}])
    fire = AsyncMock(return_value=True)
    monkeypatch.setattr(webhook_subscriptions, "find_subscriptions", subscriptions)
    monkeypatch.setattr(webhook_routes, "_fire_subscription", fire)
    legacy_check, legacy_mark = AsyncMock(return_value=False), AsyncMock()
    monkeypatch.setattr(app_event_dedup, "was_delivered", legacy_check)
    monkeypatch.setattr(app_event_dedup, "mark_delivered", legacy_mark)
    return state, adapter, subscriptions, fire, legacy_check, legacy_mark


async def test_guard_wraps_entire_fanout_and_drops_completed_retry(guarded):
    state, _, subscriptions, fire, check, mark = guarded
    assert await webhook_routes.dispatch_app_events("guarded-test", b"{}") == 2
    assert await webhook_routes.dispatch_app_events("guarded-test", b"{}") == 0
    assert state["ids"] == ["messages:111:msg1"] * 2
    assert state["done"]
    assert subscriptions.await_count == 1
    assert fire.await_count == 2
    check.assert_not_awaited()
    mark.assert_not_awaited()


async def test_failed_fanout_releases_guard_for_retry(guarded):
    state, _, subscriptions, fire, _, _ = guarded
    subscriptions.side_effect = RuntimeError("synthetic unavailable database")
    with pytest.raises(RuntimeError):
        await webhook_routes.dispatch_app_events("guarded-test", b"{}")
    assert state["done"] is False
    assert state["exits"] == ["failed"]
    fire.assert_not_awaited()
    subscriptions.side_effect = None
    assert await webhook_routes.dispatch_app_events("guarded-test", b"{}") == 2


async def test_missing_stable_id_never_fans_out(guarded):
    state, adapter, subscriptions, fire, _, _ = guarded
    adapter["event_id"] = lambda payload: None
    with pytest.raises(HTTPException) as error:
        await webhook_routes.dispatch_app_events("guarded-test", b"{}")
    assert error.value.status_code == 503
    assert not state["ids"]
    subscriptions.assert_not_awaited()
    fire.assert_not_awaited()


async def test_guard_contention_never_fans_out(guarded):
    _, adapter, subscriptions, fire, _, _ = guarded

    @asynccontextmanager
    async def busy(event_id):
        raise HTTPException(status_code=503, detail="Delivery in progress")
        yield  # pragma: no cover

    adapter["event_guard"] = busy
    with pytest.raises(HTTPException) as error:
        await webhook_routes.dispatch_app_events("guarded-test", b"{}")
    assert error.value.status_code == 503
    subscriptions.assert_not_awaited()
    fire.assert_not_awaited()


async def test_legacy_provider_keeps_check_then_mark(guarded):
    _, adapter, subscriptions, fire, check, mark = guarded
    del adapter["event_guard"]
    assert await webhook_routes.dispatch_app_events("guarded-test", b"{}") == 2
    check.assert_awaited_once_with("guarded-test", "messages:111:msg1")
    mark.assert_awaited_once_with("guarded-test", "messages:111:msg1")
    check.return_value = True
    assert await webhook_routes.dispatch_app_events("guarded-test", b"{}") == 0
    assert subscriptions.await_count == 1
    assert fire.await_count == 2


async def test_final_drop_is_guarded_and_does_not_call_subscription_lookup(guarded):
    state, adapter, subscriptions, fire, check, mark = guarded
    adapter["drop_event"] = AsyncMock(return_value="self echo")
    assert await webhook_routes.dispatch_app_events("guarded-test", b"{}") == 0
    assert state["done"]
    subscriptions.assert_not_awaited()
    fire.assert_not_awaited()
    mark.assert_not_awaited()


@pytest.mark.parametrize("failure_kind", ["http", "unexpected"])
@pytest.mark.parametrize("second_event", [False, True])
async def test_asgi_failure_preserves_queued_work_and_retry_skips_it(
    monkeypatch, failure_kind, second_event
):
    """Exercise real response background execution, not just queued mocks.

    Covers A queued/B failed in one batch, and subscriber1 queued/subscriber2
    failed for the same event. Retry must execute only the unfinished work.
    """
    delivered, executed, queued, active = set(), [], [], set()

    @asynccontextmanager
    async def guard(event_id):
        if event_id in delivered:
            yield False
            return
        assert event_id not in active
        active.add(event_id)
        try:
            yield True
        except BaseException:
            raise
        else:
            delivered.add(event_id)
        finally:
            active.remove(event_id)

    events = [("111", "messages", {"event_id": "A"}, "222")]
    if second_event:
        events.append(("111", "messages", {"event_id": "B"}, "222"))
    adapter = {
        "verify": lambda *args: True,
        "handshake": lambda body: None,
        "parse": lambda body: events,
        "event_id": lambda payload: payload["event_id"],
        "event_guard": guard,
        "subscription_guard": guard,
    }
    monkeypatch.setitem(app_webhooks.APP_PROVIDERS, "guarded-test", adapter)
    monkeypatch.setattr(webhook_routes, "get_native_pool", lambda: MagicMock())
    rows = [{"workflow_id": "workflow-one", "node_id": "one"}]
    if not second_event:
        rows.append({"workflow_id": "workflow-two", "node_id": "two"})
    monkeypatch.setattr(webhook_subscriptions, "find_subscriptions", AsyncMock(return_value=rows))
    should_fail = True

    async def run(identity):
        executed.append(identity)

    async def fire(tasks, sub, payload, channel):
        is_failure_target = payload["event_id"] == "B" if second_event else sub["node_id"] == "two"
        if should_fail and is_failure_target:
            if failure_kind == "http":
                raise HTTPException(status_code=503, detail="Synthetic temporary failure")
            raise RuntimeError("must-not-leak-sensitive-detail")
        identity = (payload["event_id"], sub["node_id"])
        queued.append(identity)
        tasks.add_task(run, identity)
        return True

    monkeypatch.setattr(webhook_routes, "_fire_subscription", fire)
    app = FastAPI()
    app.include_router(webhook_routes.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://example.test") as client:
        first = await client.post("/webhook/app/guarded-test", content=b"{}")
        assert first.status_code == 503
        assert "must-not-leak" not in first.text
        assert executed == [("A", "one")]
        assert not active
        should_fail = False
        retry = await client.post("/webhook/app/guarded-test", content=b"{}")
        assert retry.status_code == 200
    expected = [("A", "one"), ("B", "one") if second_event else ("A", "two")]
    assert queued == expected
    assert executed == expected
    assert not active
