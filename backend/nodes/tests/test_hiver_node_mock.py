"""Factory-level Hiver requests against examples from the pinned Hiver v1 contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hiver_node as native
from nodes.core.registry import NodeFactory

CONTRACT = json.loads((Path(__file__).parent / "fixtures/hiver/contract.json").read_text())
TOKEN = "synthetic-hiver-key-42"


def configuration(operation):
    cfg = {"operation": operation}
    if operation != "list_inboxes":
        cfg["inbox_id"] = "343"
    if operation in {"get_conversation", "update_conversation", "create_note"}:
        cfg.update(conversation_id="573741352", user_email="arun@hiverhq.com")
    cfg.update({
        "search_users": {"email": "bob@example.com"},
        "search_tags": {"name": "Priority"},
        "create_tag": {"name": "Property 123", "color_hexcode": "#64b5f6", "description": "Sales pipeline conversations"},
        "update_conversation": {"status_name": "closed", "assignee_email": "bob@example.com"},
        "create_shared_draft": {"body": "Sample Email body", "gmail_message_id": "19cfc4b2f216c9ez"},
        "create_note": {"content": "Please review arvind.hiver@gmail.com", "mentions": ["arvind.hiver@gmail.com"], "notify_all": True, "parent_note_id": "14510"},
    }.get(operation, {}))
    return cfg


def node(cfg):
    return NodeFactory.create_node(node_id="hiver-test", node_type="automation-hiver", node_data={
        "config": cfg, "credentials": {"credential_type": "hiver_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, status, body):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONTRACT)
async def test_one_published_operation_per_action(monkeypatch, operation):
    example = CONTRACT[operation]
    requests = transport(monkeypatch, example["status"], example["body"])
    result = await node(configuration(operation)).execute({})
    assert len(requests) == 1
    request = requests[0]
    expected = example["path"].replace("{inbox_id}", "343").replace("{inboxId}", "343").replace("{conversation_id}", "573741352").replace("{conversationId}", "573741352")
    assert request.method == example["method"] and request.url.path == "/v1" + expected
    assert request.url.host == "api2.hiverhq.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert result == {"status": "success", "http_status": example["status"], **(example["body"] or {})}
    if operation == "update_conversation":
        assert json.loads(request.content) == {"status": {"name": "closed"}, "assignee": {"email": "bob@example.com"}}
        assert request.url.params["user_email"] == "arun@hiverhq.com"
    if operation == "create_tag":
        assert json.loads(request.content)["color_hexcode"] == "#64b5f6"
    if operation in {"create_shared_draft", "create_note"}:
        assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
        assert b'name="body"' in request.content if operation == "create_shared_draft" else b'name="mentions"' in request.content
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_pagination_is_preserved_and_cursor_is_sent_as_data(monkeypatch):
    body = CONTRACT["list_inboxes"]["body"]
    requests = transport(monkeypatch, 200, body)
    result = await node({"operation": "list_inboxes", "limit": 100, "next_page": "opaque+/= &cursor"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "100", "next_page": "opaque+/= &cursor"}
    assert result["data"]["pagination"] == body["data"]["pagination"]
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_errors_are_visible_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, status, {"Message": "Provider rejected " + TOKEN})
    with pytest.raises(ValueError, match=f"Hiver HTTP {status}") as error:
        await node({"operation": "list_inboxes"}).execute({})
    assert "Provider rejected" in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"Message": "Rejected"}, {"data": [], "errors": []}])
async def test_bad_envelopes_never_claim_success(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_inboxes"}).execute({})


@pytest.mark.parametrize("cfg", [
    {"operation": "get_inbox", "inbox_id": "../evil"},
    {"operation": "get_conversation", "inbox_id": "343", "conversation_id": "x/y"},
    {"operation": "update_conversation", "inbox_id": "343", "conversation_id": "573741352"},
    {"operation": "create_shared_draft", "inbox_id": "343", "body": "Draft"},
    {"operation": "create_note", "inbox_id": "343", "conversation_id": "573741352"},
    {"operation": "list_inboxes", "limit": 101},
])
def test_invalid_configuration_rejected_before_transport(cfg):
    with pytest.raises((ValueError, ValidationError)):
        node(cfg)


def test_hand_connect_defaults_and_single_key():
    credential = native.HiverAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "hiver_api_key"
    assert native.HiverNode.connection_evidence.operation == "list_inboxes"
    assert native.HiverNode.validate_config({"config": {"operation": "list_inboxes"}, "credentials": credential.model_dump()})["valid"]
    with pytest.raises(ValueError):
        native.HiverAPIKeyCredential(api_key="Bearer " + TOKEN)
