"""Offline regressions using the provider's displayed JSON response blocks.

fixtures/chatwoot/documented.json records a Chatwoot reference URL per case.
Request expectations come independently from those pages' curl examples.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from utils.ssrf import _resolve_host_addresses

from nodes.chatwoot_node import ChatwootAPITokenCredential, ChatwootNode, ChatwootNodeConfig

CASES = json.loads((Path(__file__).parent / "fixtures/chatwoot/documented.json").read_text())
TOKEN = "chatwoot-test-token"


@pytest.fixture
def credential():
    return {"credential_type": "chatwoot_api_token", "api_token": TOKEN,
            "account_id": 1, "base_url": "https://app.chatwoot.com"}


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    async def resolve(*args, **kwargs):
        return ["93.184.215.14"]
    monkeypatch.setattr("utils.ssrf._resolve_host_addresses", resolve)


def node(config, credential):
    return ChatwootNode(node_id="test", node_type="automation-chatwoot", node_data={}, sio=Mock(),
                        config=ChatwootNodeConfig(config=config, credentials=credential))


def intercept(monkeypatch, handler):
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        assert kwargs.get("follow_redirects") is False
        assert kwargs.get("trust_env") is False
        return original(*args, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("nodes.chatwoot_node.httpx.AsyncClient", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("op", CASES)
async def test_documented_operation(op, credential, monkeypatch):
    case, captured = CASES[op], []

    def transport(request):
        captured.append(request)
        return httpx.Response(case["response_status"], json=case["response"])

    intercept(monkeypatch, transport)
    result = await node({"operation": op, **case["config"]}, credential).execute({})
    request, = captured
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    assert dict(request.url.params) == {k: str(v) for k, v in case["params"].items()}
    assert request.headers["api_access_token"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    assert (json.loads(request.content) if request.content else None) == case["body"]
    expected = case["response"] if case["response_status"] != 204 else {}
    if op == "get_profile":
        expected = {k: v for k, v in expected.items() if k not in {"access_token", "pubsub_token", "hmac_identifier"}}
    if op in {"list_conversation_labels", "set_conversation_labels"}:
        expected = {"labels": [{"label": label} for label in expected["payload"]]}
    assert result["data"] == expected
    assert result["status"] == "success" and result["timing_ms"]["request"] >= 0


@pytest.mark.asyncio
async def test_private_note_clear_priority_and_empty_labels(credential, monkeypatch):
    # https://developers.chatwoot.com/api-reference/messages/create-new-message
    # https://developers.chatwoot.com/api-reference/conversations/update-conversation
    # https://developers.chatwoot.com/api-reference/conversations/add-labels
    bodies = []

    def transport(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"payload": []})

    intercept(monkeypatch, transport)
    for config in [
        {"operation": "send_message", "content": "Hello, how can I help you?", "private": True},
        {"operation": "set_conversation_priority", "priority": "clear"},
        {"operation": "set_conversation_labels", "labels": "[]"},
    ]:
        await node({"conversation_id": 123, **config}, credential).execute({})
    await node({"operation": "update_contact", "contact_id": 123, "blocked": False}, credential).execute({})
    assert bodies == [{"content": "Hello, how can I help you?", "private": True,
                       "message_type": "outgoing", "content_type": "text"},
                      {"priority": None}, {"labels": []}, {"blocked": False}]


@pytest.mark.asyncio
async def test_pagination_preserves_provider_metadata(credential, monkeypatch):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=CASES["list_contacts"]["response"])

    intercept(monkeypatch, transport)
    result = await node({"operation": "list_contacts", "page": 2, "sort": "-name"}, credential).execute({})
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {"page": "2", "sort": "-name"}
    assert result["data"]["meta"] == CASES["list_contacts"]["response"]["meta"]
    await node({"operation": "list_messages", "conversation_id": 123, "before": 100}, credential).execute({})
    assert dict(requests[1].url.params) == {"before": "100"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": "Invalid Access Token"}),
                                         (403, {"error": "Access denied"}),
                                         (429, {"error": "Rate limit exceeded"}),
                                         (200, {"error": "Invalid Access Token"})])
async def test_provider_errors(credential, monkeypatch, status, body):
    intercept(monkeypatch, lambda request: httpx.Response(status, json=body))
    with pytest.raises(ValueError, match=body["error"]):
        await node({"operation": "get_profile"}, credential).execute({})


@pytest.mark.asyncio
async def test_error_redacts_token(credential, monkeypatch):
    intercept(monkeypatch, lambda request: httpx.Response(401, text=f"Rejected {TOKEN}"))
    with pytest.raises(ValueError) as caught:
        await node({"operation": "get_profile"}, credential).execute({})
    assert TOKEN not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content", [(302, "redirect"), (200, "<html>Sign in</html>"), (200, '"unexpected"')])
async def test_redirect_and_invalid_response(credential, monkeypatch, status, content):
    intercept(monkeypatch, lambda request: httpx.Response(status, text=content, headers={"Location": "https://other.example"}))
    with pytest.raises(ValueError):
        await node({"operation": "get_profile"}, credential).execute({})


@pytest.mark.asyncio
async def test_timeout_propagates(credential, monkeypatch):
    def transport(request):
        raise httpx.ReadTimeout("timed out", request=request)
    intercept(monkeypatch, transport)
    with pytest.raises(httpx.ReadTimeout):
        await node({"operation": "get_profile"}, credential).execute({})


@pytest.mark.asyncio
async def test_inbox_picker_and_empty_account(credential, monkeypatch):
    requests = []
    body = CASES["list_inboxes"]["response"]

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    intercept(monkeypatch, transport)
    assert await ChatwootNode.load_field_options("inbox_id", credential) == [
        {"value": str(row["id"]), "label": row["name"]} for row in body["payload"]]
    assert requests[0].url.path == "/api/v1/accounts/1/inboxes"
    body = {"payload": []}
    assert await ChatwootNode.load_field_options("inbox_id", credential) == []
    assert await ChatwootNode.load_field_options("unknown", credential) == []


@pytest.mark.asyncio
async def test_custom_instance_account_boundary(credential, monkeypatch):
    credential.update(base_url="https://support.acme.example", account_id=42)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=CASES["get_contact"]["response"])

    intercept(monkeypatch, transport)
    await node({"operation": "get_contact", "contact_id": 123}, credential).execute({})
    assert str(requests[0].url) == "https://support.acme.example/api/v1/accounts/42/contacts/123"


@pytest.mark.asyncio
async def test_private_destination_blocked(credential, monkeypatch):
    credential["base_url"] = "https://127.0.0.1"
    monkeypatch.setattr("utils.ssrf.allow_private_hosts", lambda: False)
    monkeypatch.setattr("utils.ssrf._resolve_host_addresses", _resolve_host_addresses)
    intercept(monkeypatch, lambda request: pytest.fail("No token may be sent to private hosts"))
    with pytest.raises(ValueError):
        await node({"operation": "get_profile"}, credential).execute({})


@pytest.mark.parametrize("url", ["http://app.chatwoot.com", "https://user:pass@app.chatwoot.com",
                                 "https://app.chatwoot.com/path", "https://app.chatwoot.com?x=1",
                                 "https://app.chatwoot.com#fragment"])
def test_invalid_origin(credential, url):
    with pytest.raises(ValueError):
        ChatwootAPITokenCredential.model_validate({**credential, "base_url": url})


@pytest.mark.parametrize("config", [
    {"operation": "assign_conversation", "conversation_id": 1},
    {"operation": "update_contact", "contact_id": 1},
    {"operation": "get_contact", "contact_id": "../profile"},
    {"operation": "create_conversation", "source_id": "1", "contact_id": 1, "inbox_id": -1},
    {"operation": "set_conversation_status", "conversation_id": 1, "status": "open", "snoozed_until": 123},
])
def test_invalid_config(config, credential):
    with pytest.raises(ValueError):
        node(config, credential)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,op", [("custom_attributes", "[]", "update_contact"),
                                            ("additional_attributes", "bad json", "update_contact"),
                                            ("labels", '[1]', "set_conversation_labels")])
async def test_invalid_json_before_request(field, value, op, credential, monkeypatch):
    intercept(monkeypatch, lambda request: pytest.fail("Invalid input must not send a request"))
    config = {"operation": op, "contact_id" if op == "update_contact" else "conversation_id": 123, field: value}
    with pytest.raises(ValueError, match="must be"):
        await node(config, credential).execute({})
