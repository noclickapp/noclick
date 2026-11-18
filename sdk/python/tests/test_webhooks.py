"""Webhooks and events, the event types, and agents and channels hearing NoClick's events.

Against the mocked transport: the routes, bodies and user headers each call
sends, what it parses, and ``Webhook.verify`` checking real signatures.
"""

import hashlib
import hmac
import json
import time

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing

SECRET = "nk_whsec_3f9c2a7e5b1d4c8a"
HOOK = {"object": "webhook", "id": "wh_1", "url": "https://api.yourco.test/noclick/events",
        "events": ["operation.succeeded", "human.answered"], "enabled": True, "status": "healthy",
        "description": "Production receiver", "success_rate_24h": 0.998, "last_failure": None,
        "user_id": None, "created_at": "2026-09-25T10:00:00Z"}
DELIVERY = {"object": "webhook_delivery", "id": "whd_1", "webhook_id": "wh_1", "event_id": "evt_1",
            "event_type": "operation.failed", "status": "retrying", "attempts": 3, "response_status": 502,
            "response_body": "Bad gateway", "request_body": "{\"id\": \"evt_1\"}", "duration_ms": 10004,
            "next_retry_at": "2026-09-25T12:00:00Z", "created_at": "2026-09-25T10:00:00Z"}
EVENT = {"object": "event", "id": "evt_1", "type": "operation.failed", "user_id": USER_ID,
         "data": {"object": "operation", "id": "op_9", "kind": "agent.message", "status": "failed"},
         "created_at": "2026-09-25T10:00:00Z"}


def _signed(payload: bytes, secret: str = SECRET, at: int = None) -> dict:
    at = int(time.time()) if at is None else at
    mac = hmac.new(secret.encode(), f"{at}.".encode() + payload, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "NoClick-Signature": f"t={at},v1={mac}"}


# --- webhooks ---------------------------------------------------------------------

def test_create_shows_the_secret_once_and_never_prints_it(api, client):
    create = api.post("/v1/webhooks").respond(json={**HOOK, "secret": SECRET})
    api.get("/v1/webhooks/wh_1").respond(json=HOOK)
    hook = nc.Webhook.create(
        "https://api.yourco.test/noclick/events", events=("operation.succeeded", "human.answered"),
        description="Production receiver",
    )
    assert body(create.calls.last.request) == {
        "url": "https://api.yourco.test/noclick/events", "events": ["operation.succeeded", "human.answered"],
        "description": "Production receiver"}
    assert "NoClick-User" not in create.calls.last.request.headers
    assert create.calls.last.request.headers["Idempotency-Key"]
    assert (hook.secret, hook.status, hook.success_rate_24h) == (SECRET, "healthy", 0.998)
    assert SECRET not in repr(hook) and repr(hook).startswith("Webhook(id='wh_1'")
    assert nc.Webhook.get("wh_1").secret is None  # a read never carries it


def test_from_name_owns_the_endpoint_in_code_and_reveals_its_secret(api, client):
    url = HOOK["url"]
    lookup = api.get("/v1/webhooks").mock(side_effect=[
        httpx.Response(200, json=listing()), httpx.Response(200, json=listing(HOOK))])
    create = api.post("/v1/webhooks").respond(json={**HOOK, "secret": SECRET})
    patch = api.patch("/v1/webhooks/wh_1").respond(json={**HOOK, "events": ["operation.*"]})
    reveal = api.get("/v1/webhooks/wh_1/secret").respond(json={"object": "webhook_secret", "secret": SECRET})

    made = nc.Webhook.from_name(url, create_if_missing=True, events=["operation.succeeded", "human.answered"],
                                description="Production receiver")
    assert made.secret == SECRET and lookup.calls.last.request.url.params["url"] == url
    assert body(create.calls.last.request) == {"url": url, "events": ["operation.succeeded", "human.answered"],
                                               "description": "Production receiver"}
    # Found rather than created: only what differs is sent, and the secret is read back under its scope.
    found = nc.Webhook.from_name(url, create_if_missing=True, events=["operation.*"], description="Production receiver")
    assert found.id == "wh_1" and create.call_count == 1
    assert body(patch.calls.last.request) == {"events": ["operation.*"]}
    assert found.secret is None and found.reveal_secret() == SECRET and found.secret == SECRET
    assert reveal.call_count == 1 and SECRET not in repr(found)
    with pytest.raises(ValueError, match="events"):
        nc.Webhook.from_name(url, create_if_missing=True)
    api.get("/v1/webhooks").respond(json=listing())
    with pytest.raises(nc.NotFound, match="No webhook delivers to"):
        nc.Webhook.from_name("https://gone.test/hook").hydrate()


def test_a_user_webhook_is_created_for_that_user(api, client):
    create = api.post("/v1/webhooks").respond(json={**HOOK, "user_id": USER_ID})
    with nc.as_user("acme"):
        hook = nc.Webhook.create("https://api.yourco.test/acme", events=["connection.*"])
    assert create.calls.last.request.headers["NoClick-User"] == "acme"
    assert body(create.calls.last.request) == {"url": "https://api.yourco.test/acme", "events": ["connection.*"]}
    delete = api.delete("/v1/webhooks/wh_1").respond(204)
    hook.delete()
    assert delete.calls.last.request.headers["NoClick-User"] == USER_ID  # the webhook's own user


def test_list_update_rotate_and_delete(api, client):
    listed = api.get("/v1/webhooks").respond(json=listing(HOOK, {**HOOK, "id": "wh_2", "status": "failing",
                                                                 "last_failure": {"response_status": 500}}))
    patch = api.patch("/v1/webhooks/wh_1").respond(json={**HOOK, "enabled": False, "status": "disabled"})
    rotate = api.post("/v1/webhooks/wh_1/rotate_secret").respond(json={**HOOK, "secret": "nk_whsec_new"})
    delete = api.delete("/v1/webhooks/wh_1").respond(204)

    first, failing = nc.Webhook.list(user_filter=nc.ALL_USERS, limit=10)
    params = listed.calls.last.request.url.params
    assert (params["user_id"], params["limit"]) == ("all", "10")
    assert failing.status == "failing" and failing.last_failure == {"response_status": 500}

    first.update(enabled=False, events=("operation.*",))
    assert body(patch.calls.last.request) == {"enabled": False, "events": ["operation.*"]}
    assert (first.enabled, first.status) == (False, "disabled")
    first.update(description=None)
    assert body(patch.calls.last.request) == {"description": None}  # None clears; unset fields stay out

    assert first.rotate_secret(grace_s=0) == "nk_whsec_new" and first.secret == "nk_whsec_new"
    assert body(rotate.calls.last.request) == {"grace_s": 0}
    first.rotate_secret()
    assert body(rotate.calls.last.request) == {}
    first.delete()
    assert delete.call_count == 1


def test_test_deliveries_and_redeliver(api, client):
    test = api.post("/v1/webhooks/wh_1/test").respond(json={**DELIVERY, "id": "whd_t", "status": "succeeded",
                                                            "attempts": 1, "response_status": 204,
                                                            "next_retry_at": None})
    deliveries = api.get("/v1/webhooks/wh_1/deliveries").respond(json=listing(DELIVERY))
    redeliver = api.post("/v1/webhooks/wh_1/deliveries/whd_1/redeliver").respond(json={
        **DELIVERY, "status": "succeeded", "attempts": 4, "response_status": 200, "next_retry_at": None})

    hook = nc.Webhook.from_id("wh_1")
    sent = hook.test("human.answered")
    assert body(test.calls.last.request) == {"event_type": "human.answered"}
    assert (sent.status, sent.ok, sent.response_status) == ("succeeded", True, 204)
    hook.test()
    assert body(test.calls.last.request) == {"event_type": "operation.succeeded"}

    [missed] = hook.deliveries(status=["retrying", "failed"], event=nc.Event.from_id("evt_1"), limit=5)
    params = deliveries.calls.last.request.url.params
    assert (params["status"], params["event_id"], params["limit"]) == ("retrying,failed", "evt_1", "5")
    assert (missed.attempts, missed.response_status, missed.ok, missed.next_retry_at.hour) == (3, 502, False, 12)
    assert (missed.event_type, missed.response_body, missed.duration_ms) == ("operation.failed", "Bad gateway", 10004)

    again = hook.redeliver(missed)
    assert (again.status, again.attempts) == ("succeeded", 4)
    hook.redeliver("whd_1")
    assert redeliver.call_count == 2


# --- verifying a delivery ---------------------------------------------------------

def test_verify_accepts_a_signed_body_and_returns_its_event():
    payload = json.dumps(EVENT).encode()
    event = nc.Webhook.verify(payload, _signed(payload), SECRET)
    assert isinstance(event, nc.Event)
    assert (event.id, event.type, event.user_id, event.data["id"]) == ("evt_1", "operation.failed", USER_ID, "op_9")
    assert event.created_at.year == 2026
    # Text, any header case, and a header that is a list (some frameworks) all verify.
    headers = {k.lower(): v for k, v in _signed(payload).items()}
    assert nc.Webhook.verify(payload.decode(), headers, SECRET).id == "evt_1"
    listed = {"noclick-signature": [_signed(payload)["NoClick-Signature"]]}
    assert nc.Webhook.verify(bytearray(payload), listed, SECRET).id == "evt_1"


def test_verify_accepts_either_secret_while_rotating():
    payload = json.dumps(EVENT).encode()
    at = int(time.time())
    old = _signed(payload, "nk_whsec_old", at)["NoClick-Signature"]
    new = _signed(payload, "nk_whsec_new", at)["NoClick-Signature"].split(",")[1]
    both = {"NoClick-Signature": f"{old},{new}"}
    assert nc.Webhook.verify(payload, both, "nk_whsec_new").id == "evt_1"
    assert nc.Webhook.verify(payload, both, "nk_whsec_old").id == "evt_1"
    assert nc.Webhook.verify(payload, _signed(payload, "nk_whsec_old"), ["nk_whsec_new", "nk_whsec_old"]).id == "evt_1"


@pytest.mark.parametrize("headers, secret, match", [
    ({}, SECRET, "no NoClick-Signature"),
    ({"NoClick-Signature": "sha256=abc"}, SECRET, "isn't t=<timestamp>"),
    ("stale", SECRET, "more than the 300s"),
    ("fresh", "nk_whsec_wrong", "No signature matches"),
    ("tampered", SECRET, "No signature matches"),
])
def test_verify_refuses_what_it_cannot_prove(headers, secret, match):
    payload = json.dumps(EVENT).encode()
    if headers == "stale":
        headers = _signed(payload, at=int(time.time()) - 301)
    elif headers == "fresh":
        headers = _signed(payload)
    elif headers == "tampered":
        headers = _signed(payload)
        payload = payload.replace(b"failed", b"succeeded")
    with pytest.raises(nc.WebhookSignatureError, match=match) as info:
        nc.Webhook.verify(payload, headers, secret)
    assert info.value.type == "webhook_signature_invalid"


def test_verify_tolerance_is_yours_to_widen():
    payload = json.dumps(EVENT).encode()
    stale = _signed(payload, at=int(time.time()) - 600)
    assert nc.Webhook.verify(payload, stale, SECRET, tolerance_s=900).id == "evt_1"


# --- events -----------------------------------------------------------------------

def test_event_list_filters_and_reads_across_users(api, client):
    from datetime import datetime, timezone

    listed = api.get("/v1/events").respond(json=listing(EVENT, next_cursor="c2"))
    page = nc.Event.list_page(type=["operation.failed", "domain.*"], since=datetime(2026, 9, 20, tzinfo=timezone.utc),
                              user_filter=nc.ALL_USERS, limit=1)
    params = listed.calls.last.request.url.params
    assert (params["type"], params["since"], params["user_id"], params["limit"]) == (
        "operation.failed,domain.*", "2026-09-20T00:00:00+00:00", "all", "1")
    assert "NoClick-User" not in listed.calls.last.request.headers
    assert page.next_cursor == "c2" and page.data[0].type == "operation.failed"

    with nc.as_user("user_42"):
        nc.Event.list(type="human.answered", limit=1)
    assert listed.calls.last.request.headers["NoClick-User"] == "user_42"
    assert listed.calls.last.request.url.params["type"] == "human.answered"


def test_event_deliveries_load_the_full_view_once(api, client):
    listed = api.get("/v1/events").respond(json=listing(EVENT))
    full = api.get("/v1/events/evt_1").respond(json={**EVENT, "deliveries": [DELIVERY]})
    [event] = nc.Event.list()
    assert listed.call_count == 1 and full.call_count == 0
    [delivery] = event.deliveries
    assert (delivery.webhook_id, delivery.status) == ("wh_1", "retrying")
    assert full.calls.last.request.headers["NoClick-User"] == USER_ID  # the event's own user
    assert len(event.deliveries) == 1 and full.call_count == 1

    loaded = nc.Event.get("evt_1")
    assert [d.id for d in loaded.deliveries] == ["whd_1"] and full.call_count == 2


def test_event_types_is_the_catalog(api, client):
    types = api.get("/v1/events/types").respond(json=listing(
        {"name": "operation.succeeded", "description": "An operation finished.", "emitted": True},
        {"name": "card.authorization.requested", "description": "A card purchase waits for approval.",
         "emitted": False}))
    with nc.as_user("acme"):
        catalog = nc.Event.types()
    assert "NoClick-User" not in types.calls.last.request.headers  # the catalog is the same for everyone
    assert [(t.name, t.area, t.emitted) for t in catalog] == [
        ("operation.succeeded", "operation", True), ("card.authorization.requested", "card", False)]
    assert catalog[1].description == "A card purchase waits for approval."


# --- agents and channels hearing NoClick's events ---------------------------------------

def test_an_agent_trigger_on_a_noclick_event(api, client):
    agent = {"object": "agent", "id": "ag_1", "name": "triage", "user_id": None}
    api.get("/v1/agents/ag_1").respond(json=agent)
    trigger = {"object": "agent_trigger", "id": "tr_1", "agent_id": "ag_1", "kind": "platform",
               "spec": {"type": "operation.failed", "filters": {"kind": "agent.task"}, "message": "Find out why."},
               "status": "active", "url": None, "next_run": None, "last_fired_at": None, "error": None,
               "created_at": "2026-10-01T10:00:00Z"}
    add = api.post("/v1/agents/ag_1/triggers").respond(json=trigger)
    added = nc.Agent.from_id("ag_1").add_trigger(
        nc.OnPlatformEvent("operation.failed", filters={"kind": "agent.task"}, message="Find out why."))
    assert body(add.calls.last.request) == {"kind": "platform", "type": "operation.failed",
                                           "filters": {"kind": "agent.task"}, "message": "Find out why."}
    assert added.kind == "platform" and added.defined and added.spec["type"] == "operation.failed"
    create = api.post("/v1/agents").respond(json=agent)
    nc.Agent.create("watcher", instructions="Watch.", triggers=[nc.OnPlatformEvent("connection.*",
                                                                                    conversation="c-{data.id}")])
    assert body(create.calls.last.request)["triggers"] == [
        {"kind": "platform", "type": "connection.*", "conversation": "c-{data.id}"}]


def test_a_channel_subscribes_to_noclick_events(api, client):
    subscription = {"object": "subscription", "id": "sub_1", "channel_id": "ch_1", "workspace_id": None,
                    "channels": None, "source": {"kind": "platform", "type": "operation.failed"}, "wake": None,
                    "filters": {"kind": "agent.task"}, "status": "active", "error": None, "url": None,
                    "last_event_at": None, "created_at": "2026-10-01T10:00:00Z"}
    subscribe = api.post("/v1/channels/ch_1/subscriptions").respond(json=subscription)
    room = nc.Channel.from_id("ch_1")
    made = room.subscribe("operation.failed", filters={"kind": "agent.task"})
    assert body(subscribe.calls.last.request) == {"source": {"kind": "platform", "type": "operation.failed"},
                                                 "wake": None, "filters": {"kind": "agent.task"}}
    assert made.source == {"kind": "platform", "type": "operation.failed"}
    room.subscribe(nc.OnPlatformEvent("operation.failed", filters={"kind": "agent.task"}, message="Look."))
    assert body(subscribe.calls.last.request) == {"source": {"kind": "platform", "type": "operation.failed",
                                                             "message": "Look."},
                                                 "wake": None, "filters": {"kind": "agent.task"}}
    with pytest.raises(TypeError, match="once"):
        room.subscribe(nc.OnPlatformEvent("operation.failed", filters={"kind": "x"}), filters={"kind": "y"})
    with pytest.raises(ValueError, match="one conversation"):
        room.subscribe(nc.OnPlatformEvent("operation.failed", conversation="c-{data.id}"))
