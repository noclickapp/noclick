"""Exercise Dixa actions against its unchanged published response examples.

Webhook tests use the provider's delivery-log payload, plus cryptographic
negative cases, so request routing and agent context have independent evidence.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from nodes.dixa_node import DixaNode, DixaNodeConfig, DixaAPITokenCredential, OPERATIONS

FIXTURES = json.loads((Path(__file__).parent / "fixtures/dixa/published_examples.json").read_text())
CREDENTIAL = {"credential_type": "dixa_api_token", "api_token": "dixa-test-key-123456"}
UUID = "a53b25da-f676-4c52-acac-58c9280aa23d"


def config_for(name):
    fields = {"conversation_id": 1234, "user_id": UUID, "tag_id": UUID, "agent_id": UUID,
        "query": "cancel my order", "message": "A sample note", "display_name": "Alice Brown", "name": "test"}
    return {"operation": name, **{k: fields[k] for k in OPERATIONS[name].fields if k in fields}}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(OPERATIONS))
async def test_actions_accept_published_examples(name, monkeypatch):
    example = FIXTURES["responses"][name]
    seen = []

    async def request(client, method, url, **kwargs):
        seen.append((method, url, kwargs))
        return httpx.Response(example["status"], json=example["body"] if example["body"] is not None else None,
            request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    parsed = DixaNodeConfig.model_validate({"config": config_for(name), "credentials": CREDENTIAL})
    node = DixaNode(node_id="test", node_type="automation-dixa", node_data={}, config=parsed, sio=Mock())
    node.emit = AsyncMock()
    output = await node.execute({})
    method, url, kwargs = seen[0]
    assert len(seen) == 1
    assert method == example["method"]
    expected = example["path"].replace("{conversationId}", "1234").replace("{userId}", UUID).replace("{tagId}", UUID)
    assert url == "https://dev.dixa.io" + expected
    assert kwargs["headers"]["Authorization"] == CREDENTIAL["api_token"]
    assert output == (example["body"] if example["body"] is not None else {"acknowledged": True})
    if name == "send_reply":
        assert kwargs["json"] == {"_type": "Outbound", "agentId": UUID, "content": {"_type": "Text", "value": "A sample note"}, "attachments": [], "cc": [], "bcc": []}
    if name == "patch_end_user":
        assert kwargs["json"] == {"displayName": "Alice Brown"}
    if name == "search_conversations":
        assert kwargs["params"] == {"pageLimit": 50, "query": "cancel my order", "exactMatch": False}


@pytest.mark.asyncio
async def test_api_errors_preserve_rejection_without_exposing_token(monkeypatch):
    async def request(client, method, url, **kwargs):
        return httpx.Response(401, json={"message": "Invalid token " + CREDENTIAL["api_token"]}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError, match=r"Dixa API 401: Invalid token \[redacted\]"):
        await DixaNode._request(CREDENTIAL, "GET", "/v1/organization")


@pytest.mark.asyncio
async def test_registration_and_cleanup_use_published_routes(monkeypatch):
    calls = []
    key = bytes(range(32))
    async def request(credential, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"data": {"id": UUID, "secretKey": key.hex()}}
    monkeypatch.setattr(DixaNode, "_request", request)
    registered = await DixaNode._register_external_webhook(webhook_url="https://example.hooks.example.test/events", credential=CREDENTIAL,
        config={"operation": "on_note_added"}, node_id="test")
    assert registered == {"external_webhook_id": UUID, "signing_secret": base64.b64encode(key).decode()}
    assert calls[0] == ("POST", "/v1/webhooks", {"body": {"name": "NoClick test", "url": "https://example.hooks.example.test/events",
        "events": ["ConversationNoteAdded"], "authorization": {"_type": "NoAuth"}, "customHeaders": {}, "enabled": True}})
    await DixaNode._unregister_external_webhook(credential=CREDENTIAL, config=registered, node_id="test")
    assert calls[1][:2] == ("DELETE", "/v1/webhooks/" + UUID)


def test_webhook_signature_and_human_event():
    payload = FIXTURES["event"]
    body = json.dumps(payload).encode()
    key = bytes(range(32))
    config = {"operation": "on_note_added", "signing_secret": base64.b64encode(key).decode()}
    stamp = "1689238949803"
    signature = hmac.new(key, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-DIXA-SIGNATURE": f"t={stamp},v1={signature}"}
    assert DixaNode.verify_webhook_signature(body, headers, config)
    assert not DixaNode.verify_webhook_signature(body + b" ", headers, config)
    assert not DixaNode.verify_webhook_signature(body, {}, config)
    assert not DixaNode.verify_webhook_signature(body, headers, {"signing_secret": "invalid!"})
    assert not DixaNode.verify_webhook_signature(body, headers, {**config, "signing_secret": base64.b64encode(b"wrong").decode()})
    assert DixaNode.filter_trigger_payload(payload, config)
    assert not DixaNode.filter_trigger_payload({"event_fqn": "CONVERSATION_CLOSED"}, config)
    event = DixaNode.resolve_agent_event(DixaNode.resolve_trigger_payload(payload, config))
    assert event["conversation_key"] == "dixa:g1b15dq2-bba8-48a8-a92e-852014a166r9:1234"
    for value in ["An Agent", "Test Requester", "Some Note Added", "1234", payload["data"]["note_id"], payload["data"]["author"]["id"]]:
        assert value in event["text"]


def test_manual_credential_type_defaults():
    assert DixaAPITokenCredential(api_token=CREDENTIAL["api_token"]).credential_type == "dixa_api_token"
    for value in ["Bearer some-key", "https://example.com/key", "key\nheader"]:
        with pytest.raises(ValueError):
            DixaAPITokenCredential(api_token=value)
