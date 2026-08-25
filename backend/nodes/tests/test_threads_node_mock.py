"""Mock tests for the Threads node: every op dispatches to a resolved Threads
path, the webhook handshake/signature/filter behave, and the op surface is locked."""

import hashlib
import hmac
import json
from typing import get_args
from unittest.mock import Mock, patch

import pytest

import nodes.threads_node as tmod
from nodes.threads_node import (
    ThreadsConfig,
    ThreadsNode,
    ThreadsNodeConfig,
    ThreadsOAuthCredential,
    THREADS_TRIGGER_CONFIGS,
    THREADS_TRIGGER_EVENT,
)

_MEMBERS = {m.model_fields["operation"].default: m for m in get_args(get_args(ThreadsConfig)[0])}
_ACTION_OPS = [op for op in _MEMBERS if op not in THREADS_TRIGGER_CONFIGS]
_CRED = ThreadsOAuthCredential(access_token="tok", expires_at="2099-01-01T00:00:00+00:00")


def _build_min(model):
    kwargs = {}
    for name, field in model.model_fields.items():
        if name == "operation" or not field.is_required():
            continue
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        enum = extra.get("enum")
        kwargs[name] = enum[0] if enum else ("{}" if name.endswith("_json") else "1")
    return model(**kwargs)


def _node(cfg):
    return ThreadsNode(
        node_id="n", node_type="automation-threads", node_data={},
        config=cfg, sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )


@pytest.mark.parametrize("op", _ACTION_OPS)
@pytest.mark.asyncio
async def test_threads_operation_dispatches(op):
    captured = {}

    async def fake_request(token, method, endpoint, params=None, data=None, action_name="request"):
        captured.update(method=method, endpoint=endpoint, action=action_name)
        return {"status": "success", "action": action_name, "data": {}}

    node = _node(ThreadsNodeConfig(config=_build_min(_MEMBERS[op]), credentials=_CRED))
    with patch.object(tmod, "_threads_request", side_effect=fake_request):
        result = await node.execute({})
    assert result["status"] == "success", f"{op}: {result.get('error')}"
    assert result["action"] == op
    assert captured["endpoint"].startswith("/"), f"{op}: bad endpoint {captured['endpoint']}"
    assert "{" not in captured["endpoint"], f"{op}: unresolved path {captured['endpoint']}"


def test_op_surface_counts():
    assert len(_ACTION_OPS) >= 24
    assert len(THREADS_TRIGGER_CONFIGS) == 5  # replies, mentions, publish, delete, on_any
    # every action op has a handler
    for op in _ACTION_OPS:
        assert op in tmod.OPERATION_HANDLERS, f"missing handler for {op}"


def test_key_paths_correct():
    """Spot-check the paths that matter most against the Threads API docs."""
    async def cap(op_name, **overrides):
        rec = {}

        async def fake(token, method, endpoint, params=None, data=None, action_name="x"):
            rec.update(method=method, endpoint=endpoint, params=params or {}, data=data or {})
            return {"status": "success", "action": action_name, "data": {}}

        model = _MEMBERS[op_name]
        cfg = _build_min(model)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        node = _node(ThreadsNodeConfig(config=cfg, credentials=_CRED))
        with patch.object(tmod, "_threads_request", side_effect=fake):
            import asyncio
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        return rec

    import asyncio

    async def run():
        checks = {
            "create_post": ("POST", "/me/threads"),
            "publish_post": ("POST", "/me/threads_publish"),
            "list_posts": ("GET", "/me/threads"),
            "post_insights": ("GET", "/1/insights"),
            "account_insights": ("GET", "/me/threads_insights"),
            "hide_reply": ("POST", "/1/manage_reply"),
            "keyword_search": ("GET", "/keyword_search"),
            "get_publishing_limit": ("GET", "/me/threads_publishing_limit"),
            "lookup_profile": ("GET", "/profile_lookup"),
            "delete_post": ("DELETE", "/1"),
        }
        for op_name, (want_method, want_ep) in checks.items():
            rec = {}

            async def fake(token, method, endpoint, params=None, data=None, action_name="x"):
                rec.update(method=method, endpoint=endpoint)
                return {"status": "success", "action": action_name, "data": {}}

            node = _node(ThreadsNodeConfig(config=_build_min(_MEMBERS[op_name]), credentials=_CRED))
            with patch.object(tmod, "_threads_request", side_effect=fake):
                await node.execute({})
            assert rec["method"] == want_method, f"{op_name}: method {rec['method']} != {want_method}"
            assert rec["endpoint"] == want_ep, f"{op_name}: endpoint {rec['endpoint']} != {want_ep}"

    asyncio.get_event_loop().run_until_complete(run())


# ----- Webhook trigger mechanics -----

def test_webhook_handshake_echoes_challenge():
    body = b""
    headers = {"__method__": "GET", "__query_params__": {
        "hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "12345"}}
    resp = ThreadsNode.handle_webhook_handshake(body, headers, {"verify_token": "vt"})
    assert resp is not None and resp.status_code == 200
    assert resp.body == b"12345"
    # wrong verify token -> rejected
    assert ThreadsNode.handle_webhook_handshake(body, headers, {"verify_token": "other"}) is None


def test_webhook_signature_verification():
    secret = "s3cr3t"
    body = json.dumps({"topic": "replies"}).encode()
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert ThreadsNode.verify_webhook_signature(body, {"x-hub-signature-256": good}, {"app_secret": secret})
    assert not ThreadsNode.verify_webhook_signature(body, {"x-hub-signature-256": "sha256=bad"}, {"app_secret": secret})
    # no configured secret -> accepts (dashboard test pings)
    assert ThreadsNode.verify_webhook_signature(body, {}, {})


@pytest.mark.parametrize("op,topic", [(op, THREADS_TRIGGER_EVENT[op]) for op in THREADS_TRIGGER_CONFIGS])
def test_trigger_filter_routing(op, topic):
    if topic == "*":
        assert ThreadsNode.filter_trigger_payload({"topic": "replies"}, {"operation": op})
        return
    # matching topic fires
    assert ThreadsNode.filter_trigger_payload({"topic": topic}, {"operation": op})
    # different topic does not
    other = "mentions" if topic != "mentions" else "replies"
    assert not ThreadsNode.filter_trigger_payload({"topic": other}, {"operation": op})


@pytest.mark.asyncio
async def test_trigger_execute_passthrough():
    op = "on_replies"
    cfg = THREADS_TRIGGER_CONFIGS[op](webhook_url="https://x.hooks.example.test/webhook/abc", verify_token="v")
    node = _node(ThreadsNodeConfig(config=cfg))
    out = await node.execute({"entry": [{"changes": [{"field": "replies"}]}]})
    assert out["status"] == "success" and out["action"] == "on_replies"
    assert out["data"]["webhook_url"].startswith("https://")


def test_oauth_hidden_token_method_visible():
    """OAuth is hidden from the credentials UI until Meta approves our OAuth app;
    the manual access-token method stays visible with its acquisition link.
    ThreadsOAuthCredential still parses/executes (every dispatch test above runs on it)."""
    defs = ThreadsNode.get_config_schema()["$defs"]
    assert defs["ThreadsOAuthCredential"].get("x-credential-hidden") is True
    assert "x-credential-hidden" not in defs["ThreadsAccessTokenCredential"]
    assert defs["ThreadsAccessTokenCredential"].get("x-credential-url") == (
        "https://developers.facebook.com/docs/threads/get-started"
    )
