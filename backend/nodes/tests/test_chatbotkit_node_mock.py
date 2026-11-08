"""Offline native execution tests for the ChatBotKit v1 integration.

Synthetic response fixtures exercise transport and parsing. The external
conformance gate independently validates requests against the pinned API spec.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import chatbotkit_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-chatbotkit-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="chatbotkit-fixture", node_type="automation-chatbotkit",
        node_data={"config": {"operation": operation, **config},
                   "credentials": {"credential_type": "chatbotkit_api_token", "api_token": TOKEN}})


def transport(monkeypatch, body=None, *, status=200, mime="application/json", failure=False):
    requests = []

    def respond(request):
        requests.append(request)
        if failure:
            raise httpx.ReadTimeout("Timed out " + TOKEN, request=request)
        return httpx.Response(status, json=body, headers={"content-type": mime})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_token_and_single_page_cursor_are_preserved(monkeypatch):
    body = {"items": [{"id": "bot-1", "name": "Support"}], "cursor": "bot-1"}
    requests = transport(monkeypatch, body)
    result = await node("list_bots", cursor="previous+cursor", order="asc", take=2).run({})
    assert result["status"] == "success" and result["data"] == body
    req, = requests
    assert req.method == "GET" and str(req.url).startswith(native.BASE_URL + "/bot/list?")
    assert dict(req.url.params) == {"cursor": "previous+cursor", "take": "2", "order": "asc"}
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert req.headers["Accept"] == "application/json"
    assert TOKEN not in str(req.url) and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path,expected", [
    ("create_bot", {"name": "Assistant", "dataset_id": "knowledge", "skillset_id": "skills", "privacy": False},
     "/bot/create", {"name": "Assistant", "datasetId": "knowledge", "skillsetId": "skills", "privacy": False}),
    ("update_bot", {"bot_id": "bot-1", "backstory": "Be helpful"},
     "/bot/bot-1/update", {"backstory": "Be helpful"}),
    ("create_conversation", {"bot_id": "bot-1", "name": "Support request"},
     "/conversation/create", {"botId": "bot-1", "name": "Support request"}),
    ("complete_conversation", {"conversation_id": "conv-1", "text": "Hello"},
     "/conversation/conv-1/complete", {"text": "Hello"}),
    ("create_dataset", {"name": "Knowledge"}, "/dataset/create", {"name": "Knowledge"}),
    ("create_dataset_record", {"dataset_id": "ds-1", "text": "A fact", "source": "https://example.org"},
     "/dataset/ds-1/record/create", {"text": "A fact", "source": "https://example.org"}),
    ("update_dataset_record", {"dataset_id": "ds-1", "record_id": "r-1", "text": "New fact"},
     "/dataset/ds-1/record/r-1/update", {"text": "New fact"}),
    ("create_contact", {"email": "person@example.org", "nick": "Person"},
     "/contact/create", {"email": "person@example.org", "nick": "Person"}),
    ("update_contact", {"contact_id": "c-1", "phone": "+15551234567"},
     "/contact/c-1/update", {"phone": "+15551234567"}),
    ("delete_bot", {"bot_id": "b-1"}, "/bot/b-1/delete", {}),
    ("delete_conversation", {"conversation_id": "c-1"}, "/conversation/c-1/delete", {}),
    ("delete_contact", {"contact_id": "c-1"}, "/contact/c-1/delete", {}),
    ("delete_dataset_record", {"dataset_id": "d-1", "record_id": "r-1"}, "/dataset/d-1/record/r-1/delete", {}),
])
async def test_mutations_send_only_documented_fields_once(monkeypatch, operation, config, path, expected):
    requests = transport(monkeypatch, {"id": "result-1", "text": "Hello", "usage": {}, "end": "stop"})
    result = await node(operation, **config).run({})
    assert result["status"] == "success"
    req, = requests
    assert req.method == "POST" and str(req.url) == native.BASE_URL + path
    assert json.loads(req.content) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path", [
    ("get_bot", {"bot_id": "b-1"}, "/bot/b-1/fetch"),
    ("get_conversation", {"conversation_id": "c-1"}, "/conversation/c-1/fetch"),
    ("get_dataset", {"dataset_id": "d-1"}, "/dataset/d-1/fetch"),
    ("get_contact", {"contact_id": "c-1"}, "/contact/c-1/fetch"),
    ("get_dataset_record", {"dataset_id": "d-1", "record_id": "r-1"}, "/dataset/d-1/record/r-1/fetch"),
])
async def test_reads_use_resource_path_without_body(monkeypatch, operation, config, path):
    requests = transport(monkeypatch, {"id": "result-1", "name": "Resource"})
    assert (await node(operation, **config).run({}))["status"] == "success"
    req, = requests
    assert req.method == "GET" and str(req.url) == native.BASE_URL + path and not req.content


@pytest.mark.asyncio
async def test_search_and_nested_pages(monkeypatch):
    requests = transport(monkeypatch, {"id": "d-1", "records": [{"id": "r-1", "text": "Fact", "score": .9}]})
    result = await node("search_dataset", dataset_id="d-1", search="what is it?").run({})
    assert result["data"]["records"][0]["score"] == .9
    assert json.loads(requests[0].content) == {"search": "what is it?"}
    for op, config, path in [
        ("list_conversations", {}, "/conversation/list"),
        ("list_contacts", {}, "/contact/list"),
        ("list_datasets", {}, "/dataset/list"),
        ("list_dataset_records", {"dataset_id": "d-1"}, "/dataset/d-1/record/list"),
        ("list_conversation_messages", {"conversation_id": "c-1"}, "/conversation/c-1/message/list"),
    ]:
        requests = transport(monkeypatch, {"items": [], "cursor": ""})
        assert (await node(op, **config).run({}))["data"] == {"items": [], "cursor": ""}
        assert requests[0].url.path == "/v1" + path


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_errors_keep_provider_message_and_redact_token_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN, "code": "NOT_AUTHORIZED"}, status=status)
    result = await node("list_bots").run({})
    assert result == {"status": "error", "http_status": status, "message": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_mutation_reports_unverified_outcome(monkeypatch):
    requests = transport(monkeypatch, failure=True)
    result = await node("create_dataset", name="Knowledge").run({})
    assert result["status"] == "error" and result["write_outcome"] == "unverified"
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,mime", [({}, "application/json"), ([], "application/json"),
    ({"error": "bad"}, "application/json"), ({"items": []}, "text/html")])
async def test_connection_rejects_unexpected_response(monkeypatch, body, mime):
    transport(monkeypatch, body, mime=mime)
    assert (await node("list_bots").run({}))["status"] == "error"


@pytest.mark.parametrize("identifier", ["..", ".", "../list", "id/other?x=#fragment", "https://evil.test"])
def test_path_values_cannot_change_the_fixed_route(identifier):
    with pytest.raises(ValueError):
        node("get_bot", bot_id=identifier)


@pytest.mark.asyncio
async def test_documented_conversation_create_body(monkeypatch):
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures/chatbotkit/documented_create.json").read_text())
    body = fixture["body"]
    requests = transport(monkeypatch, {"id": "conversation-1"})
    result = await node("create_conversation", bot_id=body["botId"], contact_id=body["contactId"],
                        name=body["name"], description=body["description"]).run({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == body


@pytest.mark.parametrize("value", ["", "https://api.chatbotkit.com", "Bearer key", "bad\r\nkey", "{{ secret }}"])
def test_manual_credential_accepts_only_a_token(value):
    with pytest.raises((ValueError, ValidationError)):
        native.ChatBotKitAPITokenCredential(api_token=value)


def test_manual_credential_defaults_type_and_config_refuses_unknown_fields():
    assert native.ChatBotKitAPITokenCredential(api_token=TOKEN).credential_type == "chatbotkit_api_token"
    with pytest.raises(ValueError):
        node("create_dataset", extra_params={"url": "https://example.org"})
