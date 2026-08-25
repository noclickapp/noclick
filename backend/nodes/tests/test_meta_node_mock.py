"""Mock tests for the Meta (Marketing/Ads) node: every op dispatches to a
resolved Graph path with appsecret_proof threaded, and key paths are pinned."""

import hashlib
import hmac
import json
from typing import get_args
from unittest.mock import Mock, patch

import pytest

import nodes.meta_node as mmod
from nodes.meta_node import (
    MetaConfig, MetaNode, MetaNodeConfig, MetaAccessTokenCredential,
    META_TRIGGER_CONFIGS, META_TRIGGER_EVENT,
)

_MEMBERS = {m.model_fields["operation"].default: m for m in get_args(get_args(MetaConfig)[0])}
_ACTION_OPS = [op for op in _MEMBERS if op not in META_TRIGGER_CONFIGS]
_CRED = MetaAccessTokenCredential(access_token="tok", app_secret="s3cr3t")


def _build_min(model):
    kw = {}
    for name, field in model.model_fields.items():
        if name == "operation" or not field.is_required():
            continue
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        enum = extra.get("enum")
        kw[name] = enum[0] if enum else ("{}" if name.endswith("_json") else "1")
    return model(**kw)


def _node(cfg):
    return MetaNode(node_id="n", node_type="automation-meta", node_data={},
                    config=cfg, sio=Mock(), sid="s", workflow_id="w", user_id="u")


@pytest.mark.parametrize("op", _ACTION_OPS)
@pytest.mark.asyncio
async def test_meta_operation_dispatches(op):
    captured = {}

    async def fake(token, method, endpoint, params=None, data=None, app_secret=None, action_name="request"):
        captured.update(method=method, endpoint=endpoint, app_secret=app_secret)
        # access_token lets page-token resolution (list_leadgen_forms) succeed.
        return {"status": "success", "action": action_name, "data": {"access_token": "pagetok"}}

    node = _node(MetaNodeConfig(config=_build_min(_MEMBERS[op]), credentials=_CRED))
    with patch.object(mmod, "_meta_request", side_effect=fake):
        result = await node.execute({})
    assert result["status"] == "success", f"{op}: {result.get('error')}"
    assert result["action"] == op
    assert captured["endpoint"].startswith("/"), f"{op}: bad endpoint {captured['endpoint']}"
    assert "{" not in captured["endpoint"], f"{op}: unresolved path {captured['endpoint']}"
    assert captured["app_secret"] == "s3cr3t", f"{op}: appsecret_proof secret not threaded"


def test_op_surface():
    assert len(_ACTION_OPS) >= 90
    assert len(META_TRIGGER_CONFIGS) == 8  # 7 fields + on_any
    for op in _ACTION_OPS:
        assert op in mmod.OPERATION_HANDLERS, f"missing handler for {op}"


@pytest.mark.parametrize("op,field", list(META_TRIGGER_EVENT.items()))
def test_trigger_routing(op, field):
    if field == "*":
        assert MetaNode.filter_trigger_payload({"entry": [{"changes": [{"field": "leadgen"}]}]}, {"operation": op})
        return
    payload = {"entry": [{"changes": [{"field": field}]}]}
    assert MetaNode.filter_trigger_payload(payload, {"operation": op}), f"{op} should accept {field}"
    other = "leadgen" if field != "leadgen" else "creative_fatigue"
    assert not MetaNode.filter_trigger_payload({"entry": [{"changes": [{"field": other}]}]}, {"operation": op})


def test_webhook_handshake():
    resp = MetaNode.handle_webhook_handshake(b"", {"__method__": "GET", "__query_params__": {
        "hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "88"}}, {"verify_token": "vt"})
    assert resp is not None and resp.body == b"88"
    assert MetaNode.handle_webhook_handshake(b"", {"__method__": "GET", "__query_params__": {
        "hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "88"}}, {"verify_token": "vt"}) is None


def test_webhook_signature():
    secret = "s3cr3t"
    body = json.dumps({"entry": [{"changes": [{"field": "leadgen"}]}]}).encode()
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert MetaNode.verify_webhook_signature(body, {"x-hub-signature-256": good}, {"app_secret": secret})
    assert not MetaNode.verify_webhook_signature(body, {"x-hub-signature-256": "sha256=bad"}, {"app_secret": secret})


@pytest.mark.asyncio
async def test_trigger_passthrough():
    cfg = META_TRIGGER_CONFIGS["on_leadgen"](webhook_url="https://x.hooks.example.test/webhook/abc", verify_token="v")
    out = await _node(MetaNodeConfig(config=cfg)).execute({"entry": [{"changes": [{"field": "leadgen"}]}]})
    assert out["status"] == "success" and out["action"] == "on_leadgen"
    assert out["data"]["webhook_url"].startswith("https://")


def test_key_paths():
    checks = {
        "list_ad_accounts": ("GET", "/me/adaccounts"),
        "get_ad_account": ("GET", "/act_1"),
        "create_campaign": ("POST", "/act_1/campaigns"),
        "create_adset": ("POST", "/act_1/adsets"),
        "create_ad": ("POST", "/act_1/ads"),
        "create_creative": ("POST", "/act_1/adcreatives"),
        "upload_image": ("POST", "/act_1/adimages"),
        "upload_video": ("POST", "/act_1/advideos"),
        "list_campaigns": ("GET", "/act_1/campaigns"),
        "get_insights": ("GET", "/1/insights"),
        "delete_campaign": ("DELETE", "/1"),
        "create_custom_audience": ("POST", "/act_1/customaudiences"),
        "add_audience_users": ("POST", "/1/users"),
        "remove_audience_users": ("DELETE", "/1/users"),
        "search_targeting": ("GET", "/search"),
        "reach_estimate": ("GET", "/act_1/reachestimate"),
        "create_insights_report": ("POST", "/1/insights"),
        "send_conversion_events": ("POST", "/1/events"),
        "create_pixel": ("POST", "/act_1/adpixels".replace("adpixels", "adspixels")),
        "list_businesses": ("GET", "/me/businesses"),
        "create_system_user": ("POST", "/1/system_users"),
        "create_catalog": ("POST", "/1/owned_product_catalogs"),
        "list_leads": ("GET", "/1/leads"),
        "create_test_lead": ("POST", "/1/test_leads"),
    }
    import asyncio

    async def run():
        for op, (wm, we) in checks.items():
            rec = {}

            async def fake(token, method, endpoint, params=None, data=None, app_secret=None, action_name="x"):
                rec.update(method=method, endpoint=endpoint)
                return {"status": "success", "action": action_name, "data": {}}

            node = _node(MetaNodeConfig(config=_build_min(_MEMBERS[op]), credentials=_CRED))
            with patch.object(mmod, "_meta_request", side_effect=fake):
                await node.execute({})
            assert rec["method"] == wm and rec["endpoint"] == we, f"{op}: {rec['method']} {rec['endpoint']} != {wm} {we}"

    asyncio.get_event_loop().run_until_complete(run())


def test_acct_normalization():
    assert mmod._acct("123") == "act_123"
    assert mmod._acct("act_123") == "act_123"


class _ErrResp:
    """Minimal httpx.Response stand-in exposing .json()."""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_extract_meta_error_prefers_user_message():
    """Meta buries the actionable reason in error_user_msg/title; the top-level
    'message' is often a useless generic. Both must survive, plus structured detail."""
    msg, details = mmod._extract_meta_error(_ErrResp({"error": {
        "message": "Invalid parameter", "code": 100, "error_subcode": 1359188,
        "type": "OAuthException", "fbtrace_id": "AbC123",
        "error_user_title": "No payment method",
        "error_user_msg": "Visit the billing centre to add a valid payment method.",
        "error_data": "{\"blame_field_specs\":[[\"adset_id\"]]}"}}))
    assert "Invalid parameter" in msg                       # technical message retained
    assert "No payment method" in msg                       # user title surfaced
    assert "billing centre" in msg                          # user message surfaced
    assert details["error_subcode"] == 1359188
    assert details["fbtrace_id"] == "AbC123"
    assert details["error_user_title"] == "No payment method"


def test_extract_meta_error_plain_and_no_details():
    msg, details = mmod._extract_meta_error(_ErrResp({"error": {"message": "Simple error", "code": 1}}))
    assert msg == "Simple error"
    assert details == {"code": 1}


@pytest.mark.asyncio
async def test_meta_request_surfaces_error_details_on_400():
    """A 4xx response must carry the enriched message + error_details dict."""
    import asyncio

    class Resp:
        status_code = 400
        content = b"{}"

        def json(self):
            return {"error": {"message": "Invalid parameter", "code": 100,
                              "error_user_title": "No payment method",
                              "error_user_msg": "Add a payment method.", "fbtrace_id": "z"}}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, params=None, data=None):
            return Resp()

    with patch.object(mmod.httpx, "AsyncClient", Client):
        res = await mmod._meta_request("tok", "POST", "/act_1/ads", data={"name": "x"})
    assert res["status"] == "error" and res["status_code"] == 400
    assert "No payment method" in res["error"] and "Add a payment method." in res["error"]
    assert res["error_details"]["error_user_title"] == "No payment method"
    assert res["error_details"]["fbtrace_id"] == "z"


@pytest.mark.asyncio
async def test_localized_items_batch_sends_item_type():
    """Meta requires item_type on /localized_items_batch; the node must default it."""
    captured = {}

    async def fake(token, method, endpoint, params=None, data=None, app_secret=None, action_name="request"):
        captured.update(data=data or {})
        return {"status": "success", "action": action_name, "data": {}}

    node = _node(MetaNodeConfig(config=_build_min(_MEMBERS["localized_items_batch"]), credentials=_CRED))
    with patch.object(mmod, "_meta_request", side_effect=fake):
        await node.execute({})
    assert captured["data"].get("item_type") == "PRODUCT_ITEM"


@pytest.mark.asyncio
async def test_list_leadgen_forms_resolves_page_token():
    """GET /{page}/leadgen_forms needs the Page's own token, not the user token."""
    calls = []

    async def fake(token, method, endpoint, params=None, data=None, app_secret=None, action_name="request"):
        calls.append((token, endpoint))
        if endpoint == "/1":  # page-token resolution
            return {"status": "success", "action": action_name, "data": {"access_token": "PAGETOK"}}
        return {"status": "success", "action": action_name, "data": {}}

    node = _node(MetaNodeConfig(config=_build_min(_MEMBERS["list_leadgen_forms"]), credentials=_CRED))
    with patch.object(mmod, "_meta_request", side_effect=fake):
        res = await node.execute({})
    assert res["status"] == "success"
    assert calls[0][1] == "/1"  # first resolves the page token
    assert any(tok == "PAGETOK" and ep == "/1/leadgen_forms" for tok, ep in calls)


def test_appsecret_proof_threaded_on_post():
    """Writes must carry appsecret_proof in BOTH params and form data."""
    import asyncio

    async def run():
        cfg = MetaNodeConfig(config=_build_min(_MEMBERS["create_campaign"]), credentials=_CRED)
        seen = {}

        class Resp:
            status_code = 200
            content = b"{}"

            def json(self):
                return {}

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def request(self, method, url, headers=None, params=None, data=None):
                seen.update(params=params or {}, data=data or {})
                return Resp()

        with patch.object(mmod.httpx, "AsyncClient", Client):
            await _node(cfg).execute({})
        assert "appsecret_proof" in seen["params"]
        assert "appsecret_proof" in seen["data"]

    asyncio.get_event_loop().run_until_complete(run())
