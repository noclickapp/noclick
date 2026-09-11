"""Facebook's legacy callback must reject unconfigured and forged requests."""

import hashlib
import hmac
import json
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from fastapi import HTTPException

from nodes.facebook_node import FacebookNode
from utils import facebook_events as fb_events


BODY = b'{"object":"page","entry":[]}'
SECRET = "synthetic-app-secret"


def signed(body=BODY, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"app_secret": None},
        {"app_secret": ""},
        {"app_secret": "   "},
        {"app_secret": 123},
    ],
)
@pytest.mark.parametrize("signature", [None, "sha256=forged", signed()])
def test_signature_requires_configured_secret(config, signature):
    headers = {} if signature is None else {"x-hub-signature-256": signature}
    assert FacebookNode.verify_webhook_signature(BODY, headers, config) is False


@pytest.mark.parametrize(
    "signature",
    [
        None,
        "",
        "sha256=",
        "sha256=bad",
        "sha256=" + "0" * 64,
        "sha256=" + "é" * 64,
        "sha256=" + "a" * 65,
        signed() + "\n",
        123,
        [],
        {},
    ],
)
def test_signature_rejects_malformed_or_forged_digest(signature):
    assert (
        FacebookNode.verify_webhook_signature(
            BODY, {"x-hub-signature-256": signature}, {"app_secret": SECRET}
        )
        is False
    )


@pytest.mark.parametrize("header", ["x-hub-signature-256", "X-Hub-Signature-256"])
def test_signature_authenticates_exact_raw_bytes(header):
    assert FacebookNode.verify_webhook_signature(
        BODY, {header: signed()}, {"app_secret": SECRET}
    )
    assert not FacebookNode.verify_webhook_signature(
        BODY + b" ", {header: signed()}, {"app_secret": SECRET}
    )


def handshake(config, **query):
    return FacebookNode.handle_webhook_handshake(
        b"",
        {
            "__method__": "GET",
            "__query_params__": {
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-test",
                "hub.challenge": "123",
                **query,
            },
        },
        config,
    )


@pytest.mark.parametrize("token", [None, "", "   ", 123, [], {}])
def test_handshake_requires_configured_token(token):
    assert handshake({"verify_token": token}) is None


@pytest.mark.parametrize("token", [None, "", "wrong", 123, [], {}, "é"])
def test_handshake_rejects_nonmatching_token(token):
    assert (
        handshake({"verify_token": "verify-test"}, **{"hub.verify_token": token})
        is None
    )


@pytest.mark.parametrize("challenge", [None, "", "x" * 1025, 123, [], {}])
def test_handshake_requires_bounded_string_challenge(challenge):
    assert (
        handshake({"verify_token": "verify-test"}, **{"hub.challenge": challenge})
        is None
    )


def test_handshake_returns_uncached_plaintext():
    response = handshake({"verify_token": "verify-test"})
    assert response.status_code == 200
    assert response.body == b"123"
    assert response.media_type == "text/plain"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"app_secret": ""}, {"app_secret": SECRET}])
async def test_real_dispatcher_rejects_unsigned_deliveries(config):
    from utils.webhook_routes import _apply_trigger_node_hooks

    node = {
        "id": "trigger",
        "type": "automation-facebook",
        "config": {"operation": "on_feed", **config},
    }
    with pytest.raises(HTTPException) as failure:
        await _apply_trigger_node_hooks(node, BODY, {}, method="POST")
    assert failure.value.status_code in (401, 403)


NOW = 1789150000
PAGE = "123456789"
OTHER_PAGE = "223456789"
SENDER = "323456789"
CREDENTIAL = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def facebook_clock(monkeypatch):
    monkeypatch.setattr(fb_events, "current_time", lambda: NOW)


def _message(page=PAGE, **parts):
    return {"sender": {"id": SENDER}, "recipient": {"id": page},
            "timestamp": NOW * 1000,
            **(parts or {"message": {"mid": "m.synthetic-1", "text": "controlled message"}})}


def _batch(page=PAGE, **entry):
    return {"object": "page", "entry": [{"id": page, "time": NOW,
            **(entry or {"messaging": [_message(page)]})}]}


def _parse(body):
    return fb_events.parse_facebook_webhook(json.dumps(body).encode())


@pytest.mark.parametrize("field", [field for field, _ in fb_events.FB_WEBHOOK_FIELDS])
def test_all_existing_facebook_fields_have_isolated_envelopes(facebook_clock, field):
    if field in fb_events.CHANGE_FIELDS:
        body = _batch(changes=[{"field": field, "value": {"post_id": "123_456", "verb": "add"}}])
        transport = "changes"
    elif field == "standby":
        body, transport = _batch(standby=[_message()]), "standby"
    else:
        key = next(k for k, value in fb_events.MESSAGING_FIELDS.items() if value == field)
        contents = {
            "message": {"mid": "m.synthetic-1", "text": "controlled message"},
            "postback": {"payload": "button", "title": "Review button"},
            "referral": {"ref": "source", "source": "SHORTLINK", "type": "OPEN_THREAD"},
            "reaction": {"mid": "m.synthetic-1", "action": "react", "reaction": "love"},
            "delivery": {"mids": ["m.synthetic-1"], "watermark": NOW * 1000},
            "read": {"watermark": NOW * 1000},
        }
        body, transport = _batch(messaging=[_message(**{key: contents[key]})]), "messaging"
    events = _parse(body)
    assert len(events) == 1
    page, actual_field, payload, channel = events[0]
    assert (page, actual_field) == (PAGE, field)
    assert payload["object"] == "page" and payload["page_id"] == PAGE
    assert payload["event_type"] == field and payload["event_id"]
    assert payload["entry"][0][transport] == body["entry"][0][transport]
    assert len(payload["entry"]) == 1 and len(payload["entry"][0][transport]) == 1
    assert channel == ("123_456" if field in fb_events.CHANGE_FIELDS else SENDER)


def test_mixed_pages_and_sibling_events_never_cross_envelopes(facebook_clock):
    body = _batch()
    body["entry"][0]["messaging"].append(_message(message={"mid": "m.second", "text": "second"}))
    body["entry"].extend(_batch(OTHER_PAGE)["entry"])
    body["entry"].insert(0, {"id": "bad-id", "messaging": [_message()]})
    events = _parse(body)
    assert len(events) == 3
    for page, _, payload, _ in events:
        entries = payload["entry"]
        assert len(entries) == 1
        assert entries[0]["id"] == page
        assert len(entries[0]["messaging"]) == 1
        assert entries[0]["messaging"][0]["recipient"]["id"] == page


def test_message_identity_ignores_outer_batch_time_and_formatting(facebook_clock):
    body = _batch()
    first = _parse(body)[0][2]["event_id"]
    body["entry"][0]["time"] = NOW + 1
    body["unrelated_batch_metadata"] = "ignored"
    altered = json.dumps(body, sort_keys=True, indent=2).encode()
    assert fb_events.parse_facebook_webhook(altered)[0][2]["event_id"] == first
    body["entry"][0]["messaging"][0]["message"]["mid"] = "m.different"
    assert _parse(body)[0][2]["event_id"] != first


def test_postback_referral_field_projections_share_dedup_identity(facebook_clock):
    body = _batch(messaging=[_message(postback={"payload": "button"}, referral={"ref": "source"})])
    events = _parse(body)
    assert {e[1] for e in events} == {"messaging_postbacks", "messaging_referrals"}
    assert len({e[2]["event_id"] for e in events}) == 1


@pytest.mark.parametrize("key", ["verb", "message"])
def test_feed_edits_do_not_collapse_into_original_event(facebook_clock, key):
    body = _batch(changes=[{"field": "feed", "value": {"post_id": "123_456", "verb": "add", "message": "one"}}])
    first = _parse(body)[0][2]["event_id"]
    body["entry"][0]["changes"][0]["value"][key] = "changed"
    assert _parse(body)[0][2]["event_id"] != first


@pytest.mark.parametrize("key", ["read", "delivery"])
def test_later_receipt_watermark_is_a_new_event(facebook_clock, key):
    body = _batch(messaging=[_message(**{key: {"watermark": NOW * 1000}})])
    first = _parse(body)[0][2]["event_id"]
    body["entry"][0]["messaging"][0][key]["watermark"] += 1
    assert _parse(body)[0][2]["event_id"] != first


@pytest.mark.parametrize("value", [None, True, False, 0, -1, "", " 123", "123\n", "abc", [], {}, 12.3, "1" * 33])
def test_page_identity_rejects_ambiguous_values(value):
    assert fb_events.facebook_page_id(value) is None


@pytest.mark.parametrize("value", [PAGE, int(PAGE)])
def test_page_identity_accepts_numeric_identifiers(value):
    assert fb_events.facebook_page_id(value) == PAGE


@pytest.mark.parametrize("payload", [None, [], 1, {}, {"object": "instagram"}, {"object": "page", "entry": {}}])
def test_invalid_top_level_payload_cannot_fan_out(facebook_clock, payload):
    assert _parse(payload) == []


@pytest.mark.parametrize("raw", [b"", b"not-json", b"\xff", b"[" * 1500])
def test_invalid_json_cannot_poison_dispatch(raw):
    assert fb_events.parse_facebook_webhook(raw) == []


def test_body_limit_is_enforced_before_parsing():
    with pytest.raises(HTTPException) as exc:
        fb_events.parse_facebook_webhook(b"x" * (fb_events.MAX_BODY_BYTES + 1))
    assert exc.value.status_code == 413


@pytest.mark.parametrize("stamp", [None, True, "1789150000", -1, float("inf"), float("nan"),
                                  NOW - fb_events.MAX_EVENT_AGE_SECONDS - 1,
                                  NOW + fb_events.MAX_EVENT_FUTURE_SKEW_SECONDS + 1])
@pytest.mark.parametrize("transport", ["changes", "messaging"])
def test_stale_future_or_invalid_event_time_rejected(facebook_clock, stamp, transport):
    if transport == "changes":
        body = _batch(time=stamp, changes=[{"field": "feed", "value": {"verb": "add"}}])
    else:
        message = _message()
        message["timestamp"] = stamp * 1000 if type(stamp) in (int, float) else stamp
        body = _batch(messaging=[message])
    assert _parse(body) == []


@pytest.mark.parametrize("variation", ["other_recipient", "other_sender_and_recipient", "self", "echo", "deleted", "sender_missing"])
def test_cross_page_and_self_echo_messages_do_not_wake_workflows(facebook_clock, variation):
    msg = _message()
    if variation == "other_recipient": msg["recipient"]["id"] = OTHER_PAGE
    elif variation == "other_sender_and_recipient": msg["sender"]["id"], msg["recipient"]["id"] = OTHER_PAGE, SENDER
    elif variation == "self": msg["sender"]["id"], msg["recipient"]["id"] = PAGE, SENDER
    elif variation == "echo": msg["message"]["is_echo"] = True
    elif variation == "deleted": msg["message"]["is_deleted"] = True
    else: del msg["sender"]
    assert _parse(_batch(messaging=[msg])) == []


def test_legacy_messenger_agent_resolution_still_reads_individual_event(facebook_clock):
    payload = _parse(_batch())[0][2]
    resolved = FacebookNode.resolve_agent_event(payload)
    assert resolved["conversation_key"] == SENDER
    assert "controlled message" in resolved["text"]
    assert f"page_id={PAGE}" in resolved["text"]


def _managed_config():
    return {"operation": "on_messages", "callback_mode": "managed", "page_id": PAGE,
            "credentialIds": {"facebook_oauth": CREDENTIAL}}


@pytest.mark.parametrize("patch", [
    {"page_id": OTHER_PAGE}, {"page_id": None}, {"operation": "send_message"},
    {"operation": "on_feed"}, {"callback_mode": "manual"}, {"callback_mode": None},
    {"disabled": True}, {"disabled": "true"}, {"credentialIds": {}},
    {"credentialIds": {"facebook_access_token": CREDENTIAL}},
    {"credentialIds": {"facebook_oauth": "not-a-uuid"}},
    {"credentialIds": {"facebook_oauth": CREDENTIAL, "facebook_access_token": CREDENTIAL}},
])
def test_live_graph_gate_rejects_changed_page_operation_or_credentials(facebook_clock, patch):
    payload = _parse(_batch())[0][2]
    config = _managed_config()
    assert fb_events.facebook_event_matches_config(payload, config)
    config.update(patch)
    assert not fb_events.facebook_event_matches_config(payload, config)


def test_wildcard_retains_all_existing_field_operations(facebook_clock):
    from nodes.facebook_node import FB_TRIGGER_EVENT
    assert set(FB_TRIGGER_EVENT.values()) == {"*", *(f for f, _ in fb_events.FB_WEBHOOK_FIELDS)}
    payload = _parse(_batch())[0][2]
    config = _managed_config()
    config["operation"] = "on_any_facebook_event"
    assert fb_events.facebook_event_matches_config(payload, config)
    assert fb_events.facebook_trigger_credential_id({"credential_type": "facebook_oauth", "facebook_oauth": CREDENTIAL}) == CREDENTIAL


def test_invalid_sibling_does_not_discard_valid_message(facebook_clock):
    body = _batch()
    body["entry"][0]["messaging"].extend([None, [], "bad", {"message": {"text": "no addressing"}}])
    body["entry"].extend([None, [], "bad"])
    assert len(_parse(body)) == 1


def test_payload_projection_is_not_the_input_batch(facebook_clock):
    body = _batch()
    original = deepcopy(body)
    _parse(body)
    assert body == original


@pytest.fixture
async def facebook_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(fb_events, "get_shared_redis", lambda: client)
    yield client
    await client.aclose()


async def test_facebook_real_lua_concurrent_claim_completed_retry_and_provider_isolation(facebook_redis, monkeypatch):
    from utils import instagram_webhooks
    monkeypatch.setattr(instagram_webhooks, "get_shared_redis", lambda: facebook_redis)
    async with fb_events.facebook_event_guard("same-event") as first:
        assert first
        with pytest.raises(HTTPException) as busy:
            async with fb_events.facebook_event_guard("same-event"):
                pytest.fail("An active lease must not be acquired twice")
        assert busy.value.status_code == 503
    async with fb_events.facebook_event_guard("same-event") as duplicate:
        assert not duplicate
    async with instagram_webhooks.instagram_event_guard("same-event") as independent:
        assert independent
    assert len(await facebook_redis.keys("*delivered")) == 2
    for key in await facebook_redis.keys("*delivered"):
        assert await facebook_redis.ttl(key) >= fb_events.MAX_EVENT_AGE_SECONDS


async def test_facebook_failed_attempt_can_be_retried(facebook_redis):
    with pytest.raises(RuntimeError, match="synthetic"):
        async with fb_events.facebook_event_guard("failed-event"):
            raise RuntimeError("synthetic enqueue failure")
    async with fb_events.facebook_event_guard("failed-event") as retry:
        assert retry


async def test_facebook_timeout_releases_only_its_lease(facebook_redis, monkeypatch):
    monkeypatch.setattr(fb_events, "EVENT_PROCESSING_SECONDS", 0.01)
    with pytest.raises(HTTPException) as timed_out:
        async with fb_events.facebook_event_guard("slow-event"):
            await asyncio.sleep(0.1)
    assert timed_out.value.status_code == 503
    async with fb_events.facebook_event_guard("slow-event") as retry:
        assert retry


async def test_facebook_lease_loss_cannot_acknowledge_another_owner(facebook_redis):
    event = "lost-event"
    digest = hashlib.sha256(event.encode()).hexdigest()
    lease = f"appwebhook:facebook:{{{digest}}}:lease"
    with pytest.raises(HTTPException) as lost:
        async with fb_events.facebook_event_guard(event):
            await facebook_redis.set(lease, "new-owner", ex=300)
    assert lost.value.status_code == 503
    assert await facebook_redis.get(lease) == b"new-owner"
    assert not await facebook_redis.keys("*delivered")


@pytest.mark.parametrize("missing", [True, False])
async def test_facebook_redis_unavailable_never_fails_open(monkeypatch, missing):
    client = None if missing else MagicMock(eval=AsyncMock(side_effect=ConnectionError("synthetic-secret-error")))
    monkeypatch.setattr(fb_events, "get_shared_redis", lambda: client)
    with pytest.raises(HTTPException) as unavailable:
        async with fb_events.facebook_event_guard("event"):
            pytest.fail("No dispatch without atomic guard")
    assert unavailable.value.status_code == 503
    assert "synthetic-secret-error" not in unavailable.value.detail


async def test_real_dispatcher_deduplicates_wildcard_across_field_projections(facebook_clock, facebook_redis, monkeypatch):
    from nodes.core import webhook_subscriptions
    from utils import app_webhooks, webhook_routes

    # Adapter registered ONLY in this test. Production activation still requires
    # authenticated callback setup, registration and live credential checks.
    monkeypatch.setitem(app_webhooks.APP_PROVIDERS, "facebook", {
        "parse": fb_events.parse_facebook_webhook,
        "event_id": lambda payload: payload["event_id"],
        "subscription_event_id": lambda payload: payload["event_id"],
        "event_guard": fb_events.facebook_event_guard,
        "subscription_guard": fb_events.facebook_event_guard,
    })
    monkeypatch.setattr(webhook_routes, "get_native_pool", lambda: None)
    async def find(pool, provider, tenant, event_type):
        assert provider == "facebook" and tenant == PAGE
        return [{"workflow_id": "controlled-workflow", "node_id": name}
                for name in ("wildcard", event_type)]
    monkeypatch.setattr(webhook_subscriptions, "find_subscriptions", find)
    fire = AsyncMock(return_value=True)
    monkeypatch.setattr(webhook_routes, "_fire_subscription", fire)
    body = json.dumps(_batch(messaging=[_message(postback={"payload": "button"}, referral={"ref": "source"})])).encode()
    assert await webhook_routes.dispatch_app_events("facebook", body) == 3
    assert [call.args[1]["node_id"] for call in fire.await_args_list].count("wildcard") == 1
    assert await webhook_routes.dispatch_app_events("facebook", body) == 0
    assert fire.await_count == 3


@pytest.mark.parametrize("field", [None, [], {}, 3, "unrecognized"])
def test_graph_gate_rejects_malformed_event_types_without_crashing(facebook_clock, field):
    payload = _parse(_batch())[0][2]
    payload["event_type"] = field
    assert not fb_events.facebook_event_matches_config(payload, _managed_config())
