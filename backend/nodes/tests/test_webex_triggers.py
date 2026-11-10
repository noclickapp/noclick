"""Exercise Webex subscriptions, signatures, payload routing, and agent turns.

Fixtures are copied from the provider pages named beside each example. Message
notifications contain metadata, so their content needs an authenticated read.
"""

import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from nodes.webex_node import TRIGGER_EVENTS, WebexNode
from nodes.tests.test_webex_node import _config, _transport


FIXTURES = Path(__file__).parent / "fixtures" / "webex"
EVENTS = json.loads((FIXTURES / "events.json").read_text())
MESSAGE = json.loads((FIXTURES / "message.json").read_text())["body"]


def _event(operation):
    return EVENTS[".".join(TRIGGER_EVENTS[operation])]["body"]


@pytest.mark.parametrize("operation", TRIGGER_EVENTS)
@pytest.mark.asyncio
async def test_webex_registers_signed_subscription_and_removes_it(monkeypatch, operation):
    seen = []

    def respond(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": _event(operation)["id"], **json.loads(request.content)})
        return httpx.Response(204)

    _transport(monkeypatch, respond)
    config = {"operation": operation}
    if operation == "on_new_message":
        config["room_id"] = _event(operation)["data"]["roomId"]
    elif operation == "on_new_recording":
        config["meeting_id"] = _event(operation)["data"]["meetingId"]
    extra = await WebexNode._register_external_webhook(
        webhook_url="https://example.com/mywebhook", credential={"access_token": "test-token"},
        config=config, node_id="example-node",
    )
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/webhooks"
    assert seen[0].headers["authorization"] == "Bearer test-token"
    assert (body["resource"], body["event"]) == TRIGGER_EVENTS[operation]
    assert body["targetUrl"] == "https://example.com/mywebhook"
    assert body["secret"] == extra["signing_secret"] and len(body["secret"]) == 64
    if operation == "on_new_message":
        assert body["filter"] == "roomId=" + config["room_id"]
    elif operation == "on_new_recording":
        assert body["filter"] == "meetingId=" + config["meeting_id"]
    else:
        assert "filter" not in body
    await WebexNode._unregister_external_webhook(
        credential={"access_token": "test-token"}, config={**config, **extra}, node_id="example-node",
    )
    assert seen[1].method == "DELETE"
    assert seen[1].url.path == "/v1/webhooks/" + extra["external_webhook_id"]
    assert _config(operation, **extra).config.signing_secret == body["secret"]


def test_webex_signature_uses_original_bytes_and_case_insensitive_header():
    body = json.dumps(_event("on_new_message")).encode()
    config = {"signing_secret": "example-secret"}
    signature = hmac.new(b"example-secret", body, hashlib.sha1).hexdigest()
    assert WebexNode.verify_webhook_signature(body, {"x-spark-signature": signature}, config)
    assert not WebexNode.verify_webhook_signature(body + b" ", {"X-Spark-Signature": signature}, config)
    assert not WebexNode.verify_webhook_signature(body, {}, config)
    assert not WebexNode.verify_webhook_signature(body, {"X-Spark-Signature": "invalid"}, config)
    assert not WebexNode.verify_webhook_signature(body, {"X-Spark-Signature": "é" * 40}, config)
    assert not WebexNode.verify_webhook_signature(body, {"X-Spark-Signature": signature}, {})


def test_webex_new_signature_header_matches_provider_verification_example():
    # https://developer.webex.com/docs/receive-and-verify-webhooks#authenticating-requests
    body = b'{"example":"webhook"}'
    signature = (
        "SHA-256=c7eeb9578693c5d55a7cdd25c515eec86a8416b47e68c67147f0dd6ad1398e76, "
        "SHA-512=261a573b95238d6c46906578453f400f232ff43e19e7500cb0d3062dd620c5e0018"
        "049b1d66586eccbf5436d56434ce2bd2f341f6a5605bb11ba5c1afc0e2407"
    )
    config = {"signing_secret": "example-secret"}
    for pair in [signature, *signature.split(", ")]:
        assert WebexNode.verify_webhook_signature(body, {"X-Webex-Signature": pair}, config)
        assert not WebexNode.verify_webhook_signature(body + b"\n", {"X-Webex-Signature": pair}, config)
    assert not WebexNode.verify_webhook_signature(body, {"X-Webex-Signature": "SHA-256=bad"}, config)
    assert not WebexNode.verify_webhook_signature(body, {"X-Webex-Signature": "MD5=bad"}, config)


@pytest.mark.parametrize("status", [404, 503])
@pytest.mark.asyncio
async def test_webex_cleanup_converges_only_when_already_absent(monkeypatch, status):
    _transport(monkeypatch, lambda request: httpx.Response(status, json={"message": "provider error"}))
    kwargs = {"credential": {"access_token": "test-token"},
              "config": {"external_webhook_id": _event("on_new_message")["id"]}, "node_id": "example"}
    if status == 404:
        await WebexNode._unregister_external_webhook(**kwargs)
    else:
        with pytest.raises(ValueError, match="Webex API error 503"):
            await WebexNode._unregister_external_webhook(**kwargs)


@pytest.mark.parametrize("operation", TRIGGER_EVENTS)
def test_webex_routes_only_the_configured_event_and_scope(operation):
    config = {"operation": operation}
    for candidate in TRIGGER_EVENTS:
        assert WebexNode.filter_trigger_payload(_event(candidate), config) == (candidate == operation)
    scoped = dict(config)
    for op, field, data_field in [("on_new_message", "room_id", "roomId"), ("on_new_recording", "meeting_id", "meetingId")]:
        if operation == op:
            scoped[field] = _event(operation)["data"][data_field]
            assert WebexNode.filter_trigger_payload(_event(operation), scoped)
            scoped[field] += "other"
            assert not WebexNode.filter_trigger_payload(_event(operation), scoped)
    assert WebexNode.registration_fingerprint_fields(scoped) == WebexNode.registration_fingerprint_fields({
        **scoped, "webhook_url": "https://example.com/new", "label": "Cosmetic change",
    })


@pytest.mark.asyncio
async def test_webex_message_fetches_content_and_gives_agent_reply_context(monkeypatch):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=MESSAGE)

    _transport(monkeypatch, respond)
    payload = _event("on_new_message")
    config = {"operation": "on_new_message", "credentialIds": {"webex_oauth": "example"}}
    resolve = AsyncMock(return_value=({"access_token": "test-token"}, "owner"))
    freshen = AsyncMock(return_value={"access_token": "test-token"})
    monkeypatch.setattr("utils.inbound_media.resolve_delivery_credential", resolve)
    monkeypatch.setattr(WebexNode, "freshen_credential", freshen)
    enriched = await WebexNode.transform_trigger_payload(
        payload, config, pool=Mock(), workflow_id="workflow", node_id="example",
    )
    assert "_message" not in payload
    enriched["_webhook"] = {"headers": {"X-Spark-Signature": "delivery metadata"}}
    output = WebexNode.resolve_trigger_payload(enriched, config)
    assert "_webhook" not in output["data"]
    assert "_message" not in output["data"]
    assert seen[0].url.path == "/v1/messages/" + payload["data"]["id"]
    assert output["message"]["text"] == MESSAGE["text"]
    turn = WebexNode.resolve_agent_event(output)
    assert MESSAGE["text"] in turn["text"]
    assert payload["data"]["personEmail"] in turn["text"]
    assert payload["data"]["id"] in turn["text"]
    assert turn["conversation_key"] == payload["data"]["roomId"]


@pytest.mark.parametrize("operation", ["on_meeting_ended", "on_new_recording"])
def test_webex_post_meeting_turns_keep_resource_ids_and_host_context(operation):
    payload = _event(operation)
    output = WebexNode.resolve_trigger_payload(payload, {"operation": operation})
    turn = WebexNode.resolve_agent_event(output)
    assert payload["data"]["id"] in turn["text"]
    assert payload["data"]["siteUrl"] in turn["text"]
    assert "To " in turn["text"]
    expected = payload["data"]["meetingId"] if operation == "on_new_recording" else payload["data"]["id"]
    assert turn["conversation_key"] == expected


@pytest.mark.parametrize("operation", TRIGGER_EVENTS)
@pytest.mark.asyncio
async def test_webex_manual_trigger_run_reports_no_event(operation):
    node = WebexNode(node_id="example", node_type="automation-webex", sio=Mock(),
                     node_data={}, config=_config(operation))
    output = await node.execute({"another_step": {"data": "not an event"}})
    assert output["status"] == "no_event"
    assert WebexNode.resolve_agent_event(output) is None


def test_webex_trigger_schema_declares_webhook_lifecycle():
    for operation in TRIGGER_EVENTS:
        config = _config(operation).config
        schema = type(config).model_json_schema()
        assert schema["x-requires-webhook"]
        assert schema["properties"]["operation"]["x-is-trigger"]
        assert "signing_secret" in type(config).model_fields
        assert WebexNode.scope_registry.require(operation)
