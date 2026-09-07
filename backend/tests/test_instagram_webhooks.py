"""Real Instagram signature/parser/fanout, with only infrastructure mocked.

Comment sample variants: Meta's official Instagram API Postman collection,
https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
(Comment webhook): direct entry.field/value and username-only author.
"""

from copy import deepcopy
import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
from fastapi import FastAPI, HTTPException
import httpx
import pytest

from utils import instagram_webhooks as ig

ACCOUNT = "123456789012345"
OTHER_ACCOUNT = "223456789012345"
SENDER = "323456789012345"
MEDIA = "423456789012345"
COMMENT = "523456789012345"
CREDENTIAL = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-000000000002"
WORKFLOW = "00000000-0000-4000-8000-000000000003"
SIGNING_SECRET = "synthetic-instagram-app-secret"


@pytest.fixture(autouse=True)
def ensure_native_db_pool(monkeypatch):
    """This module's database boundary is synthetic; never initialize a DB."""
    monkeypatch.setattr(ig, "current_time", lambda: 1788770000)
    yield


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_APP_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "synthetic-verification-token")
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_APP_ID", "123456789")
    monkeypatch.setenv("APP_WEBHOOK_BASE_URL", "https://api.example.test")


@pytest.fixture
async def redis(monkeypatch):
    from utils import redis_client

    client = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(redis_client, "_client", client)
    monkeypatch.setattr(ig, "get_shared_redis", lambda: client)
    yield client
    await client.aclose()


def comment_value(author=SENDER):
    return {"id": COMMENT, "from": {"id": author, "username": "review_sender"},
            "media": {"id": MEDIA, "media_product_type": "FEED"}, "text": "A controlled comment"}


def message_value(account=ACCOUNT, sender=SENDER, mid="mid.synthetic.1"):
    return {"sender": {"id": sender}, "recipient": {"id": account},
            "timestamp": 1788770000000, "message": {"mid": mid, "text": "A controlled message"}}


def body_for(account=ACCOUNT, *, comments=True, messages=True):
    entry = {"id": account, "time": 1788770000}
    if comments:
        entry["changes"] = [{"field": "comments", "value": comment_value()}]
    if messages:
        entry["messaging"] = [message_value(account)]
    return {"object": "instagram", "entry": [entry]}


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode()


def signed_headers(body):
    signature = hmac.new(SIGNING_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={signature}"}


def envelope(kind="comments"):
    parsed = ig.parse_instagram_webhook(encode(body_for()))
    return next(event[2] for event in parsed if event[1] == kind)


def subscription(kind="comments"):
    return {"provider": "instagram", "tenant_id": ACCOUNT, "event_type": kind,
            "workflow_id": WORKFLOW, "node_id": f"ig-{kind}", "user_id": USER,
            "credential_id": CREDENTIAL}


def node(kind="comments", canvas=False):
    config = {"operation": "on_comment" if kind == "comments" else "on_message",
              "credentialIds": {"instagram_login": CREDENTIAL}}
    return {"id": f"ig-{kind}", "type": "automation-instagram",
            "data" if canvas else "config": {"config": config} if canvas else config}


@pytest.mark.parametrize("key", ["INSTAGRAM_WEBHOOK_APP_SECRET", "INSTAGRAM_WEBHOOK_VERIFY_TOKEN",
                                "INSTAGRAM_WEBHOOK_APP_ID", "APP_WEBHOOK_BASE_URL"])
def test_registration_configuration_fails_closed(configured, monkeypatch, key):
    assert ig.require_instagram_webhook_configuration() == "123456789"
    monkeypatch.delenv(key)
    with pytest.raises(ValueError):
        ig.require_instagram_webhook_configuration()


@pytest.mark.parametrize("base", ["http://example.test", "https://user:secret@example.test",
                                 "https://example.test?token=no", "https://example.test/webhook"])
def test_callback_requires_canonical_https_origin(configured, monkeypatch, base):
    monkeypatch.setenv("APP_WEBHOOK_BASE_URL", base)
    with pytest.raises(ValueError, match="HTTPS origin"):
        ig.require_instagram_webhook_configuration()


def test_signature_covers_exact_raw_bytes(configured):
    raw = encode(body_for())
    headers = {k.lower(): v for k, v in signed_headers(raw).items()}
    assert ig.verify_instagram_webhook(None, raw, headers, "")
    assert not ig.verify_instagram_webhook(None, raw + b" ", headers, "")


@pytest.mark.parametrize("signature", ["", "sha256=bad", "sha256=" + "0" * 64,
                                      "sha256=" + "é" * 64, "sha1=" + "0" * 64])
def test_missing_forged_malformed_signature_rejected(configured, signature):
    assert not ig.verify_instagram_webhook(None, encode(body_for()),
                                          {"x-hub-signature-256": signature}, "")


def test_oauth_client_secret_is_not_a_signing_fallback(configured, monkeypatch):
    monkeypatch.delenv("INSTAGRAM_WEBHOOK_APP_SECRET")
    monkeypatch.setenv("INSTAGRAM_CLIENT_SECRET", SIGNING_SECRET)
    raw = encode(body_for())
    assert not ig.verify_instagram_webhook(None, raw,
        {k.lower(): v for k, v in signed_headers(raw).items()}, "")


def test_parser_batches_and_isolates_each_account():
    data = body_for()
    data["entry"].extend(body_for(OTHER_ACCOUNT)["entry"])
    events = ig.parse_instagram_webhook(encode(data))
    assert len(events) == 4
    for account, kind, payload, channel in events:
        assert payload["account_id"] == account
        assert payload["event_type"] == kind
        assert payload["event_id"].startswith(f"{account}:{kind}:")
        assert "entry" not in payload and "changes" not in payload["data"]
        if kind == "messages":
            assert payload["data"]["recipient"]["id"] == account
            assert channel == SENDER
        else:
            assert channel == MEDIA
    assert len({event[2]["event_id"] for event in events}) == 4


def test_direct_comment_sample_accepts_username_without_fabricated_id():
    value = comment_value()
    value["from"].pop("id")
    data = {"object": "instagram", "entry": [{"id": ACCOUNT, "time": 1788770000,
            "field": "comments", "value": value}]}
    events = ig.parse_instagram_webhook(encode(data))
    assert len(events) == 1
    assert events[0][2]["data"] == value
    assert "id" not in events[0][2]["data"]["from"]


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(object="page"),
    lambda p: p["entry"][0].update(id="not-an-id"),
    lambda p: p["entry"][0].update(id=True),
    lambda p: p["entry"][0]["changes"][0]["value"].update(id=None),
    lambda p: p["entry"][0]["changes"][0]["value"].update(media={}),
    lambda p: p["entry"][0]["changes"][0]["value"].update(**{"from": {}}),
    lambda p: p["entry"][0]["changes"][0]["value"].update(**{"from": {"id": ACCOUNT}}),
])
def test_malformed_cross_provider_and_own_comments_dropped(mutation):
    data = body_for(messages=False)
    mutation(data)
    assert ig.parse_instagram_webhook(encode(data)) == []


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(recipient={"id": OTHER_ACCOUNT}),
    lambda m: m.update(sender={"id": ACCOUNT}),
    lambda m: m["message"].update(is_echo=True),
    lambda m: m["message"].update(is_deleted=True),
    lambda m: m["message"].update(is_self=True),
    lambda m: m["message"].pop("mid"),
    lambda m: m.update(message=None),
])
def test_messages_drop_echo_cross_recipient_and_malformed(mutation):
    data = body_for(comments=False)
    mutation(data["entry"][0]["messaging"][0])
    assert ig.parse_instagram_webhook(encode(data)) == []


def test_attachment_only_messages_remain_deliverable():
    data = body_for(comments=False)
    message = data["entry"][0]["messaging"][0]["message"]
    message.pop("text")
    message["attachments"] = [{"type": "image", "payload": {"url": "https://example.test/image.jpg"}}]
    parsed = ig.parse_instagram_webhook(encode(data))
    assert len(parsed) == 1
    assert parsed[0][2]["data"]["message"] == message


@pytest.mark.parametrize("kind", ["comments", "messages"])
@pytest.mark.parametrize("seconds", [None, True, -1, float("nan"), float("inf"), 10**400,
                                     1788770000 - ig.MAX_EVENT_AGE_SECONDS - 1, 1788770301])
def test_signed_event_timestamp_rejects_missing_malformed_stale_future(kind, seconds):
    data = body_for(comments=kind == "comments", messages=kind == "messages")
    entry = data["entry"][0]
    if kind == "comments":
        entry["time"] = seconds
    else:
        value = seconds * 1000 if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else seconds
        entry["messaging"][0]["timestamp"] = value
    assert ig.parse_instagram_webhook(encode(data)) == []


@pytest.mark.parametrize("kind", ["comments", "messages"])
@pytest.mark.parametrize("seconds", [1788770000 - ig.MAX_EVENT_AGE_SECONDS, 1788770300])
def test_provider_retry_and_clock_skew_timestamp_boundaries(kind, seconds):
    data = body_for(comments=kind == "comments", messages=kind == "messages")
    if kind == "comments":
        data["entry"][0]["time"] = seconds
    else:
        data["entry"][0]["messaging"][0]["timestamp"] = seconds * 1000
    assert len(ig.parse_instagram_webhook(encode(data))) == 1


def test_clock_skew_cannot_outlive_delivered_marker(monkeypatch):
    data = body_for(messages=False)
    data["entry"][0]["time"] += ig.MAX_EVENT_FUTURE_SKEW_SECONDS
    assert len(ig.parse_instagram_webhook(encode(data))) == 1
    monkeypatch.setattr(ig, "current_time", lambda: 1788770000 + ig.EVENT_DEDUP_SECONDS)
    assert ig.parse_instagram_webhook(encode(data)) == []


@pytest.mark.parametrize("raw", [b"null", b"[]", b"bad", b"\xff", b'{"object":"instagram","entry":[null,1]}'])
def test_malformed_json_never_dispatches(raw):
    assert ig.parse_instagram_webhook(raw) == []


@pytest.fixture
def credential_boundary(monkeypatch):
    """Real load_credential authorization/revocation/type logic, fake DB+crypto."""
    from utils import encryption
    from wss.handlers import workflow_handler

    row = {"credential": "synthetic-encrypted-blob", "credential_type": "instagram_login",
           "revoked_at": None, "token_version": 1, "updated_at": None}
    plaintext = {"instagram_user_id": ACCOUNT, "instagram_username": "company_test",
                 "access_token": "synthetic-not-a-real-token"}
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=lambda *args: deepcopy(row) if row else None)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=None))
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda blob: deepcopy(plaintext)
    monkeypatch.setattr(encryption, "get_encryption", lambda: crypto)
    return pool, conn, row, plaintext, crypto


@pytest.mark.parametrize("canvas", [False, True])
async def test_live_scope_accepts_authoritative_current_account(credential_boundary, canvas):
    pool, conn, _, _, _ = credential_boundary
    current = node(canvas=canvas)
    assert await ig.instagram_live_scope_filter(pool, subscription(), envelope(), current) is None
    sql, credential_id, user_id, org = conn.fetchrow.await_args.args
    assert credential_id == CREDENTIAL and user_id == USER and org is None
    assert "resource_shares" in sql and "revoked_at" in sql


@pytest.mark.parametrize("mutation", [
    lambda n: n.update(type="automation-facebook"),
    lambda n: n["config"].update(operation="get_user_profile"),
    lambda n: n["config"].update(credentialIds={"instagram_oauth": CREDENTIAL}),
    lambda n: n["config"].update(credentialIds={"instagram_login": USER}),
    lambda n: n["config"].update(credentialIds={"instagram_login": CREDENTIAL, "instagram_oauth": USER}),
    lambda n: n["config"].update(media_id="987654321"),
    lambda n: n["config"].update(disabled=True),
])
async def test_live_scope_rejects_changed_current_node(credential_boundary, mutation):
    current = node()
    mutation(current)
    assert await ig.instagram_live_scope_filter(credential_boundary[0], subscription(), envelope(), current)


async def test_canvas_disabled_is_honored(credential_boundary):
    current = node(canvas=True)
    current["data"]["disabled"] = True
    assert await ig.instagram_live_scope_filter(credential_boundary[0], subscription(), envelope(), current)


@pytest.mark.parametrize("failure", ["revoked", "deleted", "wrong_type", "wrong_account"])
async def test_live_scope_rechecks_credential_not_subscription_metadata(credential_boundary, failure):
    pool, _, row, plaintext, crypto = credential_boundary
    if failure == "revoked":
        row["revoked_at"] = "synthetic-revocation-time"
    elif failure == "deleted":
        row.clear()
    elif failure == "wrong_type":
        row["credential_type"] = "instagram_oauth"
    else:
        plaintext["instagram_user_id"] = OTHER_ACCOUNT
    assert await ig.instagram_live_scope_filter(pool, subscription(), envelope(), node())
    if failure in {"deleted", "revoked"}:
        crypto.decrypt_credential.assert_not_called()


@pytest.mark.parametrize("key,value", [("tenant_id", OTHER_ACCOUNT), ("event_type", "messages"),
                                     ("provider", "facebook")])
async def test_live_scope_rejects_subscription_account_type_mismatch(credential_boundary, key, value):
    sub = subscription()
    sub[key] = value
    assert await ig.instagram_live_scope_filter(credential_boundary[0], sub, envelope(), node())


async def test_credential_discriminator_metadata_matches_registration(credential_boundary):
    current = node()
    current["config"]["credentialIds"]["credential_type"] = "instagram_login"
    assert await ig.instagram_live_scope_filter(credential_boundary[0], subscription(), envelope(), current) is None
    current["config"]["credentialIds"]["credential_type"] = "instagram_oauth"
    assert await ig.instagram_live_scope_filter(credential_boundary[0], subscription(), envelope(), current)


async def test_transient_credential_read_is_retryable(credential_boundary):
    pool, conn, _, _, _ = credential_boundary
    conn.fetchrow.side_effect = ConnectionError("synthetic DB outage")
    with pytest.raises(ConnectionError):
        await ig.instagram_live_scope_filter(pool, subscription(), envelope(), node())


async def test_username_only_comment_self_guard(credential_boundary):
    pool, _, _, plaintext, _ = credential_boundary
    data = envelope()
    data["data"]["from"] = {"username": "COMPANY_TEST"}
    assert await ig.instagram_live_scope_filter(pool, subscription(), data, node())
    data["data"]["from"]["username"] = "controlled_sender"
    assert await ig.instagram_live_scope_filter(pool, subscription(), data, node()) is None
    plaintext.pop("instagram_username")
    assert await ig.instagram_live_scope_filter(pool, subscription(), data, node())


async def test_real_lua_replay_claim_and_account_isolation(redis):
    event = envelope()["event_id"]
    async with ig.instagram_event_guard(event) as first:
        assert first
        with pytest.raises(HTTPException) as busy:
            async with ig.instagram_event_guard(event):
                pytest.fail("Concurrent event must not acquire")
        assert busy.value.status_code == 503
    async with ig.instagram_event_guard(event) as duplicate:
        assert not duplicate
    async with ig.instagram_event_guard(event.replace(ACCOUNT, OTHER_ACCOUNT)) as other:
        assert other
    keys = await redis.keys("*delivered")
    assert len(keys) == 2
    ttls = [await redis.ttl(key) for key in keys]
    assert all(ttl > 0 for ttl in ttls)


async def test_real_lua_failed_attempt_releases_claim(redis):
    with pytest.raises(RuntimeError):
        async with ig.instagram_event_guard("synthetic-event"):
            raise RuntimeError("synthetic failure before enqueue")
    async with ig.instagram_event_guard("synthetic-event") as retry:
        assert retry


async def test_guard_bounds_processing_before_lease_expiry(redis, monkeypatch):
    assert ig.EVENT_PROCESSING_SECONDS < ig.EVENT_LEASE_SECONDS
    monkeypatch.setattr(ig, "EVENT_PROCESSING_SECONDS", 0.01)
    with pytest.raises(HTTPException) as timed_out:
        async with ig.instagram_event_guard("synthetic-timeout"):
            await asyncio.sleep(0.1)
    assert timed_out.value.status_code == 503
    async with ig.instagram_event_guard("synthetic-timeout") as retry:
        assert retry


async def test_redis_error_does_not_fail_open(monkeypatch):
    broken = MagicMock()
    broken.eval = AsyncMock(side_effect=ConnectionError("synthetic outage"))
    monkeypatch.setattr(ig, "get_shared_redis", lambda: broken)
    with pytest.raises(HTTPException) as unavailable:
        async with ig.instagram_event_guard("synthetic-event"):
            pytest.fail("Redis failure must not dispatch")
    assert unavailable.value.status_code == 503


async def test_real_lua_expired_owner_cannot_complete_or_release_new_lease(redis):
    event = "synthetic-event"
    digest = hashlib.sha256(event.encode()).hexdigest()
    lease = f"appwebhook:instagram:{{{digest}}}:lease"
    with pytest.raises(HTTPException) as lost:
        async with ig.instagram_event_guard(event):
            await redis.set(lease, "different-owner", ex=300)
    assert lost.value.status_code == 503
    assert await redis.get(lease) == b"different-owner"
    assert not await redis.keys("*delivered")


async def test_guard_fails_closed_without_redis(monkeypatch):
    monkeypatch.setattr(ig, "get_shared_redis", lambda: None)
    with pytest.raises(HTTPException) as error:
        async with ig.instagram_event_guard("synthetic-event"):
            pytest.fail("Cannot dispatch without replay guard")
    assert error.value.status_code == 503


@pytest.fixture
async def client(monkeypatch, credential_boundary):
    from utils import webhook_routes

    pool = credential_boundary[0]
    monkeypatch.setattr(webhook_routes, "get_native_pool", lambda: pool)
    app = FastAPI()
    app.include_router(webhook_routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.example.test") as client:
        yield client


@pytest.mark.parametrize("token", [None, "", "wrong"])
async def test_http_handshake_rejects_missing_wrong_tokens(client, configured, token):
    params = {"hub.mode": "subscribe", "hub.challenge": "123456"}
    if token is not None:
        params["hub.verify_token"] = token
    response = await client.get("/webhook/app/instagram", params=params)
    assert response.status_code == 403
    assert "123456" not in response.text


async def test_http_handshake_exact_challenge_no_workflow(client, configured, monkeypatch):
    response = await client.get("/webhook/app/instagram", params={
        "hub.mode": "subscribe", "hub.verify_token": "synthetic-verification-token",
        "hub.challenge": "123456"})
    assert response.status_code == 200 and response.text == "123456"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    monkeypatch.delenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN")
    response = await client.get("/webhook/app/instagram", params={
        "hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "123456"})
    assert response.status_code == 403


async def test_http_signature_rejected_before_any_dispatch(client, configured, monkeypatch):
    from utils import webhook_routes

    dispatch = AsyncMock()
    monkeypatch.setattr(webhook_routes, "dispatch_app_events", dispatch)
    response = await client.post("/webhook/app/instagram", content=encode(body_for()))
    assert response.status_code == 401
    dispatch.assert_not_awaited()
    response = await client.post("/webhook/app/instagram", content=b"x" * (ig.MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    dispatch.assert_not_awaited()


async def test_http_signed_batch_dispatch_replay_echo_account_isolation(
        client, configured, redis, credential_boundary, monkeypatch):
    from nodes.core import webhook_subscriptions
    from utils import webhook_routes

    pool = credential_boundary[0]
    workflow = {"nodes": [node("comments"), node("messages")], "edges": []}
    pool.fetchrow = AsyncMock(side_effect=lambda *a: {"workflow": deepcopy(workflow)})
    async def subscriptions(_pool, provider, account, kind):
        assert provider == "instagram"
        return [subscription(kind)] if account == ACCOUNT else []
    monkeypatch.setattr(webhook_subscriptions, "find_subscriptions", subscriptions)
    execute = AsyncMock()
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", execute)
    data = body_for()
    data["entry"].extend(body_for(OTHER_ACCOUNT)["entry"])
    data["entry"][0]["messaging"].append({**message_value(), "message": {"mid": "echo", "is_echo": True}})
    raw = encode(data)
    response = await client.post("/webhook/app/instagram", content=raw, headers=signed_headers(raw))
    assert response.status_code == 200
    assert execute.await_count == 2
    for call in execute.await_args_list:
        kwargs = call.kwargs
        active = next(n for n in kwargs["nodes"] if n["id"] == kwargs["start_node_id"])
        payload = active["config"]["_triggerPayload"]
        assert payload["account_id"] == ACCOUNT and "entry" not in payload
        assert kwargs["user_id"] == USER
    response = await client.post("/webhook/app/instagram", content=raw, headers=signed_headers(raw))
    assert response.status_code == 200 and execute.await_count == 2
