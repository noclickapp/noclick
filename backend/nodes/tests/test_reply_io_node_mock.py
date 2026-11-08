"""Reply v3 wire-contract regressions; no provider account or network is used."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import reply_io_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-reply-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="reply-test", node_type="automation-reply-io",
        node_data={"config": config, "credentials": {"credential_type": "reply_io_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_current_user"}, "GET", "/v3/whoami", None),
    ({"operation": "list_contacts", "email": "john.doe@company.com"}, "GET", "/v3/contacts", None),
    ({"operation": "create_contact", "email": "john.doe@company.com", "firstName": "John"}, "POST", "/v3/contacts", {"email": "john.doe@company.com", "firstName": "John"}),
    ({"operation": "get_contact", "contact_id": 123}, "GET", "/v3/contacts/123", None),
    ({"operation": "update_contact", "contact_id": 123, "isOptedOut": False}, "PATCH", "/v3/contacts/123", {"isOptedOut": False}),
    ({"operation": "delete_contact", "contact_id": 123}, "DELETE", "/v3/contacts/123", None),
    ({"operation": "list_contact_lists", "search": "Sales"}, "GET", "/v3/contact-lists", None),
    ({"operation": "create_contact_list", "name": "Sales"}, "POST", "/v3/contact-lists", {"name": "Sales", "isShared": False}),
    ({"operation": "get_contact_list", "list_id": 10}, "GET", "/v3/contact-lists/10", None),
    ({"operation": "update_contact_list", "list_id": 10, "name": "Leads"}, "PUT", "/v3/contact-lists/10", {"name": "Leads"}),
    ({"operation": "delete_contact_list", "list_id": 10}, "DELETE", "/v3/contact-lists/10", None),
    ({"operation": "add_contacts_to_list", "list_id": 10, "contactIds": [123]}, "POST", "/v3/contact-lists/10/add-contacts", {"contactIds": [123]}),
    ({"operation": "list_sequences", "isArchived": False}, "GET", "/v3/sequences", None),
    ({"operation": "get_sequence", "sequence_id": 20}, "GET", "/v3/sequences/20", None),
    ({"operation": "update_sequence", "sequence_id": 20, "name": "Sales"}, "PATCH", "/v3/sequences/20", {"name": "Sales"}),
    ({"operation": "start_sequence", "sequence_id": 20}, "POST", "/v3/sequences/20/start", None),
    ({"operation": "pause_sequence", "sequence_id": 20}, "POST", "/v3/sequences/20/pause", None),
    ({"operation": "list_sequence_contacts", "sequence_id": 20}, "GET", "/v3/sequences/20/contacts", None),
    ({"operation": "add_contacts_to_sequence", "sequence_id": 20, "contactIds": [123]}, "POST", "/v3/sequences/20/contact-links/bulk", {"contactIds": [123], "removeFromExisting": False, "ignoreStepDelay": False}),
    ({"operation": "remove_contact_from_sequence", "sequence_id": 20, "contact_id": 123}, "DELETE", "/v3/sequences/20/contact-links/123", None),
    ({"operation": "list_tasks"}, "GET", "/v3/tasks", None),
    ({"operation": "get_task", "task_id": 30}, "GET", "/v3/tasks/30", None),
    ({"operation": "create_task", "taskType": "toDo", "startAt": "2026-11-08T09:00:00Z", "dueTo": "2026-11-08T10:00:00Z", "template": {"body": "Follow up"}}, "POST", "/v3/tasks", {"taskType": "toDo", "startAt": "2026-11-08T09:00:00Z", "dueTo": "2026-11-08T10:00:00Z", "template": {"body": "Follow up"}}),
    ({"operation": "complete_task", "task_id": 30}, "POST", "/v3/tasks/30/complete", {"finishProspectInSequence": False}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=["reply-io::" + case[0]["operation"] for case in CASES])
async def test_reply_io_requests(monkeypatch, config, method, path, body):
    payload = {"items": [{"id": 123}], "hasMore": False} if config["operation"].startswith("list_") else {"id": 123}
    if config["operation"] == "get_current_user":
        payload = {"userId": 42, "username": "alice@example.com", "teamId": 10}
    requests = transport(monkeypatch, lambda r: httpx.Response(204) if method == "DELETE" else httpx.Response(200, json=payload))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == (None if method == "DELETE" else payload)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.reply.io"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"].startswith("list_"):
        assert dict(request.url.params) == {"top": "25", "skip": "0", **{k: str(v).lower() if isinstance(v, bool) else v for k,v in config.items() if k not in {"operation", "sequence_id"}}}
    if config["operation"] == "get_task":
        assert dict(request.url.params) == {"includeContent": "false"}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_reply_io_pagination_and_current_user(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"items": [], "hasMore": True}))
    result = await node({"operation": "list_contacts", "top": 50, "skip": 100}).execute({})
    assert result["next_skip"] == 150
    assert dict(requests[0].url.params) == {"top": "50", "skip": "100"}
    transport(monkeypatch, lambda r: httpx.Response(200, json={"userId": 42, "username": "alice@example.com", "teamId": 10}))
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["data"]["username"] == "alice@example.com"
    assert native.ReplyIoNode.connection_evidence.identity_operation == "get_current_user"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_reply_io_errors_do_not_retry_or_expose_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text="Rejected " + TOKEN))
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_current_user"}).execute({})
    assert f"HTTP {status}" in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "create_contact"},
    {"operation": "update_contact", "contact_id": 1},
    {"operation": "get_contact", "contact_id": "../whoami"},
    {"operation": "add_contacts_to_list", "list_id": 1, "contactIds": []},
    {"operation": "list_tasks", "top": 1001},
    {"operation": "create_task", "taskType": "toDo", "startAt": "2026-01-02T00:00:00Z", "dueTo": "2026-01-01T00:00:00Z", "template": {"body": "Follow up"}},
])
def test_reply_io_invalid_config(config):
    with pytest.raises((ValueError, ValidationError)):
        native.ReplyIoNode.parse_config({"config": config})


@pytest.mark.asyncio
async def test_reply_io_malformed_page_is_rejected(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={"items": {}, "hasMore": False}))
    with pytest.raises(ValueError, match="invalid page"):
        await node({"operation": "list_contacts"}).execute({})


@pytest.mark.asyncio
async def test_reply_io_provider_contact_example(monkeypatch):
    from pathlib import Path

    payload = json.loads((Path(__file__).parent / "fixtures/reply-io/contact.json").read_text())
    transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    result = await node({"operation": "get_contact", "contact_id": 12345}).execute({})
    assert result["data"] == payload
    assert result["data"]["customFields"][0] == {"key": "leadSource", "value": "Conference"}
