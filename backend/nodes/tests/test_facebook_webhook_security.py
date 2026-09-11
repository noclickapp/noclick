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
from utils import facebook_subscriptions as fb_subs
from utils.meta_subscriptions import MetaAuthorizationDenied
import httpx
from types import SimpleNamespace
from urllib.parse import parse_qs


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
APP = "123123123"
USER = "456456456"


@pytest.fixture
async def facebook_registration(monkeypatch):
    from utils import redis_client

    redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(redis_client, "get_shared_redis", lambda: redis)
    monkeypatch.setattr(fb_events, "get_shared_redis", lambda: redis)
    for name, value in {"FACEBOOK_WEBHOOK_APP_ID": APP,
                        "FACEBOOK_WEBHOOK_APP_SECRET": "synthetic-signing-secret",
                        "FACEBOOK_WEBHOOK_VERIFY_TOKEN": "synthetic-verify",
                        "APP_WEBHOOK_BASE_URL": "https://callback.example"}.items():
        monkeypatch.setenv(name, value)
    s = SimpleNamespace(
        redis=redis, requests=[], posts=[], fields={"leadgen"}, failure=None,
        page_identity=PAGE, page_rows=[{"id": PAGE, "access_token": "synthetic-page-token", "tasks": ["MANAGE"]}],
        readback_missing=False, gate=None, entered=None, post_success=True,
        token_data={"app_id": APP, "user_id": USER, "type": "USER", "is_valid": True,
                    "expires_at": 4102444800, "data_access_expires_at": 4102444800,
                    "scopes": ["pages_show_list", "pages_manage_metadata", "pages_read_engagement", "pages_read_user_content", "pages_messaging"]},
        credential={"credential_type": "facebook_oauth", "facebook_user_id": USER, "access_token": "synthetic-user-token"},
        config={"operation": "on_feed", "callback_mode": "managed", "page_id": PAGE,
                "credentialIds": {"facebook_oauth": CREDENTIAL}},
        app_subscription={"object": "page", "active": True, "callback_url": "https://callback.example/webhook/app/facebook",
                          "fields": [{"name": name} for name, _ in fb_events.FB_WEBHOOK_FIELDS]},
    )
    original_client = httpx.AsyncClient
    s.client = original_client

    async def transport(request):
        s.requests.append(request)
        assert request.url.host == "graph.facebook.com"
        if s.failure:
            override = s.failure(request)
            if override is not None:
                return override
        if request.url.path.endswith("/debug_token"):
            assert request.headers["Authorization"] == f"Bearer {APP}|synthetic-signing-secret"
            assert request.url.params["input_token"] == "synthetic-user-token"
            return httpx.Response(200, json={"data": s.token_data})
        if request.url.path.endswith(f"/{APP}/subscriptions"):
            assert request.method == "GET"
            assert request.headers["Authorization"] == f"Bearer {APP}|synthetic-signing-secret"
            return httpx.Response(200, json={"data": [s.app_subscription]})
        assert "access_token" not in request.url.params
        assert "appsecret_proof" in request.url.params
        if request.url.path.endswith("/me/accounts"):
            assert request.headers["Authorization"] == "Bearer synthetic-user-token"
            return httpx.Response(200, json={"data": s.page_rows})
        assert request.headers["Authorization"] == "Bearer synthetic-page-token"
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": s.page_identity})
        assert request.url.path.endswith(f"/{PAGE}/subscribed_apps")
        if request.method == "POST":
            fields = set(parse_qs(request.content.decode())["subscribed_fields"][0].split(","))
            s.posts.append(fields)
            if s.post_success:
                s.fields = fields
            return httpx.Response(200, json={"success": s.post_success})
        if s.gate:
            s.entered.set()
            await s.gate.wait()
        fields = [] if s.posts and s.readback_missing else sorted(s.fields)
        return httpx.Response(200, json={"data": [{"id": APP, "subscribed_fields": fields}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original_client(*a, transport=httpx.MockTransport(transport), **kw))
    yield s
    await redis.aclose()


async def test_page_registration_preserves_union_is_idempotent_and_uses_only_page_token(facebook_registration):
    s = facebook_registration
    assert await fb_subs.ensure_page_subscription(s.credential, s.config) == PAGE
    assert s.posts == [{"leadgen", "feed"}]
    await fb_subs.ensure_page_subscription(s.credential, dict(s.config, operation="on_messages"))
    assert s.posts[-1] == {"leadgen", "feed", "messages"}
    await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert len(s.posts) == 2
    assert await s.redis.keys("*") == []


async def test_managed_page_picker_paginates_without_exposing_page_tokens(facebook_registration):
    s = facebook_registration
    def first_page(request):
        if "after" not in request.url.params:
            return httpx.Response(200, json={"data": [{"id": OTHER_PAGE, "name": "Another Page"}],
                "paging": {"next": "https://untrusted.example", "cursors": {"after": "next"}}})
        return None
    s.failure = first_page
    result = await FacebookNode.load_field_options("page_id", s.credential, context=s.config)
    assert result == {"options": [{"label": "Another Page", "value": OTHER_PAGE}, {"label": PAGE, "value": PAGE}]}
    assert len(s.requests) == 2 and "synthetic-page-token" not in json.dumps(result)


async def test_managed_picker_surfaces_provider_failure_instead_of_empty_success(facebook_registration):
    s = facebook_registration
    s.failure = lambda r: httpx.Response(503, json={})
    with pytest.raises(ValueError, match="HTTP 503"):
        await FacebookNode.load_field_options("page_id", s.credential, context=s.config)


@pytest.mark.parametrize("key,value", [("object", "instagram"), ("active", False), ("callback_url", "https://other.example"), ("fields", []), ("fields", ["feed"])])
async def test_app_callback_configuration_is_verified_before_page_subscription(facebook_registration, key, value):
    s = facebook_registration
    s.app_subscription[key] = value
    with pytest.raises(ValueError, match="app-level"):
        await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert not s.posts and not any("subscribed_apps" in r.url.path for r in s.requests)


@pytest.mark.parametrize("operation", ["on_" + f for f, _ in fb_events.FB_WEBHOOK_FIELDS] + ["on_any_facebook_event"])
async def test_all_facebook_event_fields_register(facebook_registration, operation):
    s = facebook_registration
    await fb_subs.ensure_page_subscription(s.credential, dict(s.config, operation=operation))
    expected = {f for f, _ in fb_events.FB_WEBHOOK_FIELDS} if operation == "on_any_facebook_event" else {operation[3:]}
    assert s.posts == [{"leadgen"} | expected]


@pytest.mark.parametrize("key,value", [
    ("app_id", "999"), ("user_id", "999"), ("type", "PAGE"), ("is_valid", False),
    ("is_valid", 1), ("expires_at", 1), ("expires_at", None), ("expires_at", True),
    ("data_access_expires_at", 1), ("scopes", []), ("scopes", "pages_manage_metadata"),
])
async def test_app_user_expiry_scopes_gate_precedes_page_lookup(facebook_registration, key, value):
    s = facebook_registration
    s.token_data[key] = value
    with pytest.raises(MetaAuthorizationDenied):
        await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert len(s.requests) == 1 and not s.posts


@pytest.mark.parametrize("change", ["not_selected", "duplicate", "no_management", "no_token", "wrong_page_token"])
async def test_registration_never_falls_back_to_another_page_or_user_token(facebook_registration, change):
    s = facebook_registration
    if change == "not_selected": s.page_rows[0]["id"] = OTHER_PAGE
    if change == "duplicate": s.page_rows.append(deepcopy(s.page_rows[0]))
    if change == "no_management": s.page_rows[0]["tasks"] = ["ANALYZE"]
    if change == "no_token": s.page_rows[0].pop("access_token")
    if change == "wrong_page_token": s.page_identity = OTHER_PAGE
    with pytest.raises(MetaAuthorizationDenied):
        await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert not s.posts and not any("subscribed_apps" in r.url.path for r in s.requests)


@pytest.mark.parametrize("mode", ["manual", "", None])
async def test_legacy_or_missing_callback_mode_never_registers_managed(facebook_registration, mode):
    s = facebook_registration
    with pytest.raises(ValueError):
        await fb_subs.ensure_page_subscription(s.credential, dict(s.config, callback_mode=mode))
    assert not s.requests


async def test_paginated_page_and_app_edges_use_cursors_not_next_urls(facebook_registration):
    s = facebook_registration

    def pagination(request):
        if request.method != "GET": return None
        if request.url.path.endswith("/me/accounts") and "after" not in request.url.params:
            return httpx.Response(200, json={"data": [{"id": OTHER_PAGE}], "paging": {
                "next": "https://evil.example/steal", "cursors": {"after": "next-pages"}}})
        if request.url.path.endswith("/subscribed_apps") and "after" not in request.url.params:
            return httpx.Response(200, json={"data": [{"id": "789789", "subscribed_fields": ["messages"]}], "paging": {
                "next": "https://evil.example/steal", "cursors": {"after": "next-apps"}}})
        return None
    s.failure = pagination
    await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert s.posts == [{"leadgen", "feed"}]
    assert {r.url.params.get("after") for r in s.requests} == {None, "next-pages", "next-apps"}


@pytest.mark.parametrize("path", ["/me/accounts", "/subscribed_apps"])
@pytest.mark.parametrize("broken", ["missing_cursor", "repeated_cursor", "malformed_page", "malformed_paging", "too_many"])
async def test_incomplete_edges_stop_before_registration(facebook_registration, path, broken):
    s = facebook_registration
    calls = []

    def fail(request):
        if not request.url.path.endswith(path): return None
        calls.append(request)
        body = {"data": [], "paging": {"next": "https://untrusted.example", "cursors": {"after": "repeat"}}}
        if broken == "missing_cursor": body["paging"].pop("cursors")
        if broken == "malformed_page": body["data"] = {}
        if broken == "malformed_paging": body["paging"] = []
        if broken == "too_many": body["paging"]["cursors"]["after"] = str(len(calls))
        return httpx.Response(200, json=body)
    s.failure = fail
    with pytest.raises(ValueError):
        await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert not s.posts
    assert len(calls) == ((50 if path == "/me/accounts" else 5) if broken == "too_many" else 2 if broken == "repeated_cursor" else 1)


@pytest.mark.parametrize("failure", ["false_success", "missing_fields", "readback_error"])
async def test_remote_update_is_not_success_until_readback_verified(facebook_registration, failure):
    s = facebook_registration
    if failure == "false_success": s.post_success = False
    if failure == "missing_fields": s.readback_missing = True
    if failure == "readback_error":
        s.failure = lambda r: httpx.Response(503, json={}) if s.posts and r.method == "GET" else None
    with pytest.raises(ValueError, match="no workflow subscription was saved"):
        await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert s.posts == [{"leadgen", "feed"}]
    assert not any(r.method == "DELETE" for r in s.requests)
    assert await s.redis.keys("*") == []


async def test_real_redis_serializes_page_union_updates(facebook_registration):
    s = facebook_registration
    s.gate, s.entered = asyncio.Event(), asyncio.Event()
    first = asyncio.create_task(fb_subs.ensure_page_subscription(s.credential, s.config))
    await asyncio.wait_for(s.entered.wait(), 1)
    try:
        with pytest.raises(ValueError, match="already in progress"):
            await fb_subs.ensure_page_subscription(s.credential, dict(s.config, operation="on_messages"))
    finally:
        s.gate.set()
        await first
    await fb_subs.ensure_page_subscription(s.credential, dict(s.config, operation="on_messages"))
    assert s.posts == [{"leadgen", "feed"}, {"leadgen", "feed", "messages"}]


async def test_lost_lease_stops_before_post_and_preserves_new_owner(facebook_registration):
    s = facebook_registration
    s.gate, s.entered = asyncio.Event(), asyncio.Event()
    attempt = asyncio.create_task(fb_subs.ensure_page_subscription(s.credential, s.config))
    await asyncio.wait_for(s.entered.wait(), 1)
    key = (await s.redis.keys("*"))[0]
    await s.redis.set(key, "replacement-owner", ex=90)
    s.gate.set()
    with pytest.raises(ValueError, match="lock was lost"):
        await attempt
    assert not s.posts and await s.redis.get(key) == b"replacement-owner"


async def test_transport_logs_and_errors_do_not_contain_token_or_provider_body(facebook_registration, caplog):
    import logging
    s = facebook_registration
    caplog.set_level(logging.INFO, logger="httpx")
    await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert "synthetic-user-token" not in caplog.text
    assert "synthetic-signing-secret" not in caplog.text
    assert "appsecret_proof" not in caplog.text
    assert "Meta Graph transport activity" in caplog.text
    s.failure = lambda r: httpx.Response(503, json={"error": {"message": "SECRET-SENTINEL"}})
    with pytest.raises(ValueError) as exc:
        await fb_subs.ensure_page_subscription(s.credential, s.config)
    assert "SECRET-SENTINEL" not in str(exc.value) + caplog.text


@pytest.fixture
def facebook_world(facebook_registration, monkeypatch):
    from nodes.core import webhook_subscriptions as subscriptions
    from utils import credential_loader, facebook_webhooks, webhook_manager, webhook_routes

    s = facebook_registration
    s.owner = "00000000-0000-4000-8000-000000000010"
    s.workflow = "00000000-0000-4000-8000-000000000020"
    s.node_id, s.rows = "facebook-trigger", []
    s.nodes = [{"id": s.node_id, "type": "automation-facebook", "config": s.config}]
    s.pool = MagicMock()
    s.pool.fetchrow = AsyncMock(side_effect=lambda *a: {"workflow": {"nodes": deepcopy(s.nodes), "edges": []}})
    s.loaded = s.credential

    async def load_credential(pool, user_id, credential_id, **kwargs):
        assert user_id == s.owner and credential_id == CREDENTIAL
        return deepcopy(s.loaded)

    async def owner_nodes(pool, wf, include_nodes=True):
        assert str(wf) == s.workflow
        return s.owner, deepcopy(s.nodes) if include_nodes else []

    async def save(pool, **data):
        s.rows = [dict(data, event_type=event) for event in data["event_types"]]

    async def delete(*args):
        s.rows = []

    monkeypatch.setattr(credential_loader, "load_credential", load_credential)
    monkeypatch.setattr(facebook_webhooks, "load_credential", load_credential)
    monkeypatch.setattr(webhook_manager, "_load_workflow_owner_and_nodes", owner_nodes)
    monkeypatch.setattr(FacebookNode, "freshen_credential", AsyncMock(side_effect=lambda data, **kw: data))
    monkeypatch.setattr(subscriptions, "get_node_subscriptions", AsyncMock(side_effect=lambda *a: deepcopy(s.rows)))
    s.save = AsyncMock(side_effect=save)
    monkeypatch.setattr(subscriptions, "save_subscriptions", s.save)
    monkeypatch.setattr(subscriptions, "delete_subscriptions", AsyncMock(side_effect=delete))
    monkeypatch.setattr(subscriptions, "find_subscriptions", AsyncMock(side_effect=lambda pool, provider, page, kind:
        [deepcopy(row) for row in s.rows if row["provider"] == provider and row["tenant_id"] == page and row["event_type"] == kind]))
    monkeypatch.setattr(webhook_routes, "get_native_pool", lambda: s.pool)
    monkeypatch.setattr("utils.fire_budget.over_fire_budget", AsyncMock(return_value=False))
    s.execute = AsyncMock()
    monkeypatch.setattr(webhook_routes, "_execute_workflow_with_relay", s.execute)
    monkeypatch.setattr(webhook_manager.WebhookManager, "merge_node_config_patch", AsyncMock())

    async def provision():
        return await webhook_manager.WebhookManager.provision_node_webhook(
            s.pool, user_id=s.owner, workflow_id=s.workflow, node_id=s.node_id,
            node_type="automation-facebook", operation=s.config["operation"], config=s.config)

    async def reconcile():
        return await webhook_manager.WebhookManager.reconcile_node(s.pool, s.workflow, s.node_id)

    s.provision, s.reconcile = provision, reconcile
    return s


async def test_managed_headless_registration_and_reconcile_use_live_page_binding(facebook_world):
    s = facebook_world
    result = await s.provision()
    assert result["trigger_registered"] is True
    assert result["subscription_status"].startswith("Registered")
    assert s.rows[0]["tenant_id"] == PAGE and s.rows[0]["user_id"] == s.owner
    before = len(s.requests)
    assert (await s.reconcile())["state"] == "live"
    assert len(s.requests) == before
    # Same credential, new Page: must not take the credential-only fast path.
    s.config["page_id"] = OTHER_PAGE
    assert (await s.reconcile())["state"] == "failed"
    assert len(s.requests) > before and s.rows[0]["tenant_id"] == PAGE


async def test_panel_separate_credential_argument_matches_headless_registration(facebook_world):
    s = facebook_world
    context = {key: value for key, value in s.config.items() if key != "credentialIds"}
    result = await FacebookNode.load_field_value("subscription_status", s.owner, s.workflow, s.node_id, s.pool,
                                                context=context, credential_ids={"facebook_oauth": CREDENTIAL})
    assert result["values"]["trigger_registered"] is True
    assert s.rows[0]["credential_id"] == CREDENTIAL and "credentialIds" not in context


async def test_conflicting_panel_credential_selectors_fail_before_provider_calls(facebook_world):
    s = facebook_world
    with pytest.raises(ValueError, match="selection changed"):
        await FacebookNode.load_field_value("subscription_status", s.owner, s.workflow, s.node_id, s.pool,
                                            context=s.config, credential_ids={"facebook_oauth": "different"})
    assert not s.requests and not s.rows


@pytest.mark.parametrize("change", ["manual", "disabled", "operation", "deleted"])
async def test_reconciliation_removes_obsolete_managed_rows_without_unsubscribing_shared_page(facebook_world, change, monkeypatch):
    s = facebook_world
    await s.provision()
    before = len(s.requests)
    if change == "manual": s.config["callback_mode"] = "manual"
    if change == "disabled": s.config["disabled"] = True
    if change == "operation": s.config["operation"] = "get_me"
    if change == "deleted":
        # The full deletion reconciler also checks legacy webhooks/cron rows.
        # Model that independent transport explicitly, including OSS where
        # the scheduler is configured; it must never hit the Graph fixture.
        prune_schedules = AsyncMock(return_value={"deleted": 0})
        monkeypatch.setattr("utils.cron_scheduler_client.delete_schedules_for_nodes", prune_schedules)
        s.nodes = []
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        s.pool.acquire.return_value = AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False))
    assert (await s.reconcile())["state"] == "deregistered"
    assert not s.rows and len(s.requests) == before
    assert s.fields == {"leadgen", "feed"}
    if change == "deleted":
        prune_schedules.assert_awaited_once_with(s.workflow, [s.node_id])


async def test_unverified_owner_credential_never_saves_registration(facebook_world):
    s = facebook_world
    s.loaded = None
    result = await s.provision()
    assert result["trigger_registered"] is False
    assert not s.rows and not s.requests


async def test_provider_readback_failure_never_saves_local_active_rows(facebook_world):
    s = facebook_world
    s.readback_missing = True
    result = await s.provision()
    assert result["trigger_registered"] is False and "readback" in result["trigger_error"]
    s.save.assert_not_awaited()
    assert not s.rows


@pytest.mark.parametrize("mode", [None, "manual"])
async def test_manual_mode_provisions_original_callback_and_rejects_managed_loader(facebook_world, monkeypatch, mode):
    from utils.webhook_manager import WebhookManager
    s = facebook_world
    s.config["callback_mode"] = mode
    mint = AsyncMock(return_value={"webhook_id": "synthetic-webhook", "webhook_url": "https://example.test"})
    monkeypatch.setattr(WebhookManager, "get_or_create_webhook", mint)
    assert (await s.provision())["webhook_url"] == "https://example.test"
    assert mint.await_count == 1 and not s.rows and not s.requests
    assert await FacebookNode.load_field_value("subscription_status", s.owner, s.workflow, s.node_id, s.pool, context=s.config) == {"value": None}


def test_managed_mode_never_accepts_the_legacy_per_workflow_callback():
    config = {"callback_mode": "managed", "app_secret": SECRET, "verify_token": "verify-test"}
    assert not FacebookNode.verify_webhook_signature(BODY, {"x-hub-signature-256": signed()}, config)
    assert handshake(config) is None


@pytest.mark.parametrize("change", ["none", "page", "operation", "manual", "credential", "revoked", "owner", "provider_revoked", "granular_scope", "app", "remote_unsubscribed"])
async def test_live_delivery_rechecks_current_authorization_without_provider_writes(facebook_world, facebook_clock, change):
    from utils.facebook_webhooks import facebook_live_scope_filter
    s = facebook_world
    await s.provision()
    row = deepcopy(s.rows[0])
    if change == "page": s.config["page_id"] = OTHER_PAGE
    if change == "operation": s.config["operation"] = "on_messages"
    if change == "manual": s.config["callback_mode"] = "manual"
    if change == "credential": s.config["credentialIds"] = {}
    if change == "revoked": s.loaded = None
    if change == "owner": s.owner = "00000000-0000-4000-8000-000000000011"
    if change == "provider_revoked": s.token_data["is_valid"] = False
    if change == "app": s.token_data["app_id"] = "999"
    if change == "granular_scope": s.token_data["granular_scopes"] = [{"scope": "pages_manage_metadata", "target_ids": [OTHER_PAGE]}]
    if change == "remote_unsubscribed": s.fields = {"leadgen"}
    payload = fb_events.parse_facebook_webhook(json.dumps({"object": "page", "entry": [{
        "id": PAGE, "time": NOW, "changes": [{"field": "feed", "value": {"post_id": "123_456", "verb": "add"}}]}]}).encode())[0][2]
    before = len(s.posts)
    result = await facebook_live_scope_filter(s.pool, row, payload, s.nodes[0])
    assert (result is None) == (change == "none")
    assert len(s.posts) == before


@pytest.mark.parametrize("status,code", [(429, 4), (503, 2), (403, 4)])
async def test_transient_provider_failure_remains_retryable(facebook_world, facebook_clock, status, code):
    from utils.facebook_webhooks import facebook_live_scope_filter
    s = facebook_world
    await s.provision()
    s.failure = lambda r: httpx.Response(status, json={"error": {"code": code, "is_transient": True}})
    payload = {"object": "page", "page_id": PAGE, "event_type": "feed"}
    with pytest.raises(ValueError):
        await facebook_live_scope_filter(s.pool, s.rows[0], payload, s.nodes[0])


async def test_real_signed_asgi_delivery_isolated_to_authorized_page_and_retry_deduped(facebook_world, facebook_clock):
    from fastapi import FastAPI
    from utils import webhook_routes
    s = facebook_world
    await s.provision()
    app = FastAPI()
    app.include_router(webhook_routes.router)
    entries = [{"id": page, "time": NOW, "changes": [{"field": "feed", "value": {"post_id": page + "_111", "verb": "add"}}]} for page in (PAGE, OTHER_PAGE)]
    body = json.dumps({"object": "page", "entry": entries}).encode()
    async with s.client(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        url = "/webhook/app/facebook"
        bad = await client.post(url, content=body, headers={"x-hub-signature-256": signed(body)})
        assert bad.status_code in (401, 403) and s.execute.await_count == 0
        headers = {"x-hub-signature-256": signed(body, "synthetic-signing-secret")}
        good = await client.post(url, content=body, headers=headers)
        assert good.status_code == 200
        assert s.execute.await_count == 1
        delivered = s.execute.call_args.kwargs["nodes"][0]["config"]["_triggerPayload"]
        assert delivered["page_id"] == PAGE and len(delivered["entry"]) == 1
        assert OTHER_PAGE not in json.dumps(delivered)
        again = await client.post(url, content=body, headers=headers)
        assert again.status_code == 200 and s.execute.await_count == 1
        too_big = await client.post(url, content=b"x" * (fb_events.MAX_BODY_BYTES + 1))
        assert too_big.status_code == 413


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
