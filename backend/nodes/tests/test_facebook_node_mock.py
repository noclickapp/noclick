"""Mock tests for the Facebook node: every op dispatches to a resolved Graph path,
webhook handshake/signature/filter behave, and the op surface is locked."""

import hashlib
import hmac
import json
from typing import get_args
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

import nodes.facebook_node as fmod
from nodes.facebook_node import (
    FacebookConfig, FacebookNode, FacebookNodeConfig,
    FacebookAccessTokenCredential, FB_TRIGGER_CONFIGS, FB_TRIGGER_EVENT,
)
from utils.ssrf import SSRFError

_MEMBERS = {m.model_fields["operation"].default: m for m in get_args(get_args(FacebookConfig)[0])}
_ACTION_OPS = [op for op in _MEMBERS if op not in FB_TRIGGER_CONFIGS]
_CRED = FacebookAccessTokenCredential(access_token="tok", app_secret="s3cr3t")


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
    return FacebookNode(node_id="n", node_type="automation-facebook", node_data={},
                        config=cfg, sio=Mock(), sid="s", workflow_id="w", user_id="u")


# Multi-step ops (reels / stories) chain start → hosted upload → finish; the
# start phase must hand back a video_id/upload_url (or a photo id) for the flow
# to proceed, and the hosted upload is a raw rupload call, not a _fb_request.
_MULTISTEP_OPS = {"publish_reel", "publish_video_story", "publish_photo_story"}


@pytest.mark.parametrize(
    "upload_url",
    [
        "https://attacker.example/video-upload/session",
        "https://evil.rupload.facebook.com/video-upload/session",
        "https://rupload.facebook.com.attacker.example/video-upload/session",
        "https://attacker@rupload.facebook.com/video-upload/session",
    ],
)
@pytest.mark.asyncio
async def test_hosted_upload_rejects_non_facebook_credential_origins(upload_url):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        with pytest.raises(SSRFError, match="outside"):
            await fmod._hosted_upload_to_url(
                "page-token", upload_url, "https://cdn.example/video.mp4", "publish_reel"
            )
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_hosted_upload_accepts_official_facebook_rupload_origin():
    response = MagicMock(status_code=200, content=b'{"success":true}')
    response.json.return_value = {"success": True}

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response
    ) as post:
        result = await fmod._hosted_upload_to_url(
            "page-token",
            "https://rupload.facebook.com/video-upload/v25.0/session?offset=0",
            "https://cdn.example/video.mp4",
            "publish_reel",
        )

    assert result["status"] == "success"
    assert post.await_args.args[0].startswith("https://rupload.facebook.com/")
    assert post.await_args.kwargs["headers"]["Authorization"] == "OAuth page-token"


@pytest.mark.parametrize("op", _ACTION_OPS)
@pytest.mark.asyncio
async def test_facebook_operation_dispatches(op):
    captured = {}

    async def fake(token, method, endpoint, params=None, data=None, app_secret=None, action_name="request"):
        captured.update(method=method, endpoint=endpoint, app_secret=app_secret)
        return {"status": "success", "action": action_name,
                "data": {"video_id": "v1", "upload_url": "https://rupload.facebook.com/x", "id": "p1"}}

    async def fake_upload(token, upload_url, file_url, action_name):
        return {"status": "success", "action": action_name, "data": {"success": True}}

    node = _node(FacebookNodeConfig(config=_build_min(_MEMBERS[op]), credentials=_CRED))
    with patch.object(fmod, "_fb_request", side_effect=fake), \
            patch.object(fmod, "_hosted_upload_to_url", side_effect=fake_upload):
        result = await node.execute({})
    assert result["status"] == "success", f"{op}: {result.get('error')}"
    assert result["action"] == op
    assert captured["endpoint"].startswith("/"), f"{op}: bad endpoint {captured['endpoint']}"
    assert "{" not in captured["endpoint"], f"{op}: unresolved path {captured['endpoint']}"
    assert captured["app_secret"] == "s3cr3t", f"{op}: appsecret_proof secret not threaded"


def test_op_surface():
    assert len(_ACTION_OPS) >= 45
    assert len(FB_TRIGGER_CONFIGS) == 11  # 10 fields + on_any
    for op in _ACTION_OPS:
        assert op in fmod.OPERATION_HANDLERS, f"missing handler for {op}"


def test_key_paths():
    checks = {
        "list_pages": ("GET", "/me/accounts"),
        "publish_post": ("POST", "/1/feed"),
        "send_message": ("POST", "/1/messages"),
        "page_insights": ("GET", "/1/insights"),
        "subscribe_page_webhooks": ("POST", "/1/subscribed_apps"),
        "thread_control": ("POST", "/1/pass_thread_control"),
        "set_messenger_profile": ("POST", "/1/messenger_profile"),
        "hide_comment": ("POST", "/1"),
        "list_reels": ("GET", "/1/video_reels"),
        # multi-step ops record the last _fb_request (the finish phase / story create)
        "publish_reel": ("POST", "/1/video_reels"),
        "publish_video_story": ("POST", "/1/video_stories"),
        "publish_photo_story": ("POST", "/1/photo_stories"),
    }
    import asyncio

    async def run():
        for op, (wm, we) in checks.items():
            rec = {}

            async def fake(token, method, endpoint, params=None, data=None, app_secret=None, action_name="x"):
                rec.update(method=method, endpoint=endpoint)
                return {"status": "success", "action": action_name,
                        "data": {"video_id": "v1", "upload_url": "https://rupload/x", "id": "p1"}}

            async def fake_upload(token, upload_url, file_url, action_name):
                return {"status": "success", "action": action_name, "data": {"success": True}}

            node = _node(FacebookNodeConfig(config=_build_min(_MEMBERS[op]), credentials=_CRED))
            with patch.object(fmod, "_fb_request", side_effect=fake), \
                    patch.object(fmod, "_hosted_upload_to_url", side_effect=fake_upload):
                await node.execute({})
            assert rec["method"] == wm and rec["endpoint"] == we, f"{op}: {rec['method']} {rec['endpoint']} != {wm} {we}"

    asyncio.get_event_loop().run_until_complete(run())


def test_webhook_handshake():
    resp = FacebookNode.handle_webhook_handshake(b"", {"__method__": "GET", "__query_params__": {
        "hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "77"}}, {"verify_token": "vt"})
    assert resp is not None and resp.body == b"77"
    assert FacebookNode.handle_webhook_handshake(b"", {"__method__": "GET", "__query_params__": {
        "hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "77"}}, {"verify_token": "vt"}) is None


def test_webhook_signature():
    secret = "s3cr3t"
    body = json.dumps({"entry": [{"changes": [{"field": "feed"}]}]}).encode()
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert FacebookNode.verify_webhook_signature(body, {"x-hub-signature-256": good}, {"app_secret": secret})
    assert not FacebookNode.verify_webhook_signature(body, {"x-hub-signature-256": "sha256=bad"}, {"app_secret": secret})


async def test_crc_through_framework_seam():
    """The GET CRC must work via the real webhook dispatcher, not just the node
    method: _apply_trigger_node_hooks injects method/query_params and passes the
    node's PlainTextResponse through untouched (a JSONResponse would quote the
    challenge and Meta would reject it)."""
    from fastapi import HTTPException
    from utils.webhook_routes import _apply_trigger_node_hooks

    trig = {"id": "t", "type": "automation-facebook",
            "config": {"operation": "on_feed", "verify_token": "vt", "app_secret": "s"}}
    # correct verify_token → raw text/plain challenge echoed back
    resp = await _apply_trigger_node_hooks(trig, b"", {}, method="GET",
        query_params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "9"})
    assert resp is not None and resp.body == b"9" and resp.media_type == "text/plain"
    # wrong verify_token must never leak the challenge (rejected or falls through)
    try:
        bad = await _apply_trigger_node_hooks(trig, b"", {}, method="GET",
            query_params={"hub.mode": "subscribe", "hub.verify_token": "NOPE", "hub.challenge": "9"})
        assert bad is None or getattr(bad, "body", b"") != b"9"
    except HTTPException:
        pass


@pytest.mark.parametrize("op,field", [(op, FB_TRIGGER_EVENT[op]) for op in FB_TRIGGER_CONFIGS])
def test_trigger_routing(op, field):
    if field == "*":
        assert FacebookNode.filter_trigger_payload({"entry": [{"changes": [{"field": "feed"}]}]}, {"operation": op})
        return
    # messaging fields ride entry[].messaging; changes-based fields ride entry[].changes
    if field in ("messages", "messaging_postbacks", "message_reads", "message_deliveries", "message_reactions", "messaging_referrals"):
        key = {"messages": "message", "messaging_postbacks": "postback", "message_reads": "read",
               "message_deliveries": "delivery", "message_reactions": "reaction", "messaging_referrals": "referral"}[field]
        payload = {"entry": [{"messaging": [{key: {}}]}]}
    elif field == "standby":
        payload = {"entry": [{"standby": [{}]}]}
    else:
        payload = {"entry": [{"changes": [{"field": field}]}]}
    assert FacebookNode.filter_trigger_payload(payload, {"operation": op}), f"{op} should accept {field}"
    assert not FacebookNode.filter_trigger_payload({"entry": [{"changes": [{"field": "ratings" if field != "ratings" else "feed"}]}]},
                                                   {"operation": op})


@pytest.mark.asyncio
async def test_trigger_passthrough():
    cfg = FB_TRIGGER_CONFIGS["on_messages"](webhook_url="https://x.hooks.example.test/webhook/abc", verify_token="v")
    out = await _node(FacebookNodeConfig(config=cfg)).execute({"entry": [{"messaging": [{"message": {}}]}]})
    assert out["status"] == "success" and out["action"] == "on_messages"
    assert out["data"]["webhook_url"].startswith("https://")
