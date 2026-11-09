"""Assembly.com wire contracts; synthetic tokens, no live account or writes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import assemblycom_node as native
from nodes.core.registry import NodeFactory

ID = "550e8400-e29b-41d4-a716-446655440000"
TOKEN = "synthetic-assemblycom-key"
CREDENTIAL = {"credential_type": "assemblycom_api_key", "api_key": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="assembly-test", node_type="automation-assemblycom",
        node_data={"config": config, "credentials": CREDENTIAL})


@pytest.fixture
def wire(monkeypatch):
    requests = []
    reply = {"body": {"id": ID}, "status": 200, "headers": {}}
    def respond(request):
        requests.append(request)
        return httpx.Response(reply["status"], json=reply["body"], headers=reply["headers"])
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, reply


CASES = [
    ({"operation": "get_current_user"}, "GET", "/v1/me", None),
    ({"operation": "list_clients"}, "GET", "/v1/clients", None),
    ({"operation": "get_client", "client_id": ID}, "GET", f"/v1/clients/{ID}", None),
    ({"operation": "create_client", "givenName": "Jane", "familyName": "Doe", "companyId": ID}, "POST", "/v1/clients", {"givenName": "Jane", "familyName": "Doe", "companyId": ID}),
    ({"operation": "update_client", "client_id": ID, "familyName": "Smith"}, "PATCH", f"/v1/clients/{ID}", {"familyName": "Smith"}),
    ({"operation": "list_companies"}, "GET", "/v1/companies", None),
    ({"operation": "get_company", "company_id": ID}, "GET", f"/v1/companies/{ID}", None),
    ({"operation": "create_company", "name": "Acme"}, "POST", "/v1/companies", {"name": "Acme"}),
    ({"operation": "update_company", "company_id": ID, "name": "Acme"}, "PATCH", f"/v1/companies/{ID}", {"name": "Acme"}),
    ({"operation": "list_tasks", "status": "inProgress"}, "GET", "/v1/tasks", None),
    ({"operation": "get_task", "task_id": ID}, "GET", f"/v1/tasks/{ID}", None),
    ({"operation": "create_task", "name": "Onboard"}, "POST", "/v1/tasks", {"name": "Onboard"}),
    ({"operation": "update_task", "task_id": ID, "status": "completed"}, "PATCH", f"/v1/tasks/{ID}", {"status": "completed"}),
    ({"operation": "delete_task", "task_id": ID}, "DELETE", f"/v1/tasks/{ID}", None),
    ({"operation": "list_notes"}, "GET", "/v1/notes", None),
    ({"operation": "get_note", "note_id": ID}, "GET", f"/v1/notes/{ID}", None),
    ({"operation": "create_note", "entityId": ID, "entityType": "client", "title": "Kickoff"}, "POST", "/v1/notes", {"entityId": ID, "entityType": "client", "title": "Kickoff"}),
    ({"operation": "update_note", "note_id": ID, "title": "Follow up"}, "PATCH", f"/v1/notes/{ID}", {"title": "Follow up"}),
    ({"operation": "delete_note", "note_id": ID}, "DELETE", f"/v1/notes/{ID}", None),
    ({"operation": "list_message_channels"}, "GET", "/v1/message-channels", None),
    ({"operation": "create_message_channel", "membershipType": "group", "memberIds": [ID]}, "POST", "/v1/message-channels", {"membershipType": "group", "memberIds": [ID]}),
    ({"operation": "list_messages", "channelId": ID}, "GET", "/v1/messages", None),
    ({"operation": "send_message", "channelId": ID, "text": "Hello"}, "POST", "/v1/messages", {"channelId": ID, "text": "Hello"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_every_operation_one_exact_request(wire, config, method, path, body):
    requests, reply = wire
    if config["operation"].startswith("list_"):
        reply["body"] = {"data": [{"id": ID}], "nextToken": "opaque-token"}
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.assembly.com" and request.headers["X-API-KEY"] == TOKEN
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"].startswith("list_"):
        assert result["has_more"] and result["nextToken"] == "opaque-token"
        assert request.url.params["limit"] == "20"
    if config["operation"] in {"create_client", "update_client"}:
        assert request.url.params["sendInvite"] == "false"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_cursor_filters_booleans_and_empty_page(wire):
    requests, reply = wire
    reply["body"] = {"data": None, "nextToken": ""}
    result = await node({"operation": "list_companies", "name": "Acme + Co", "isPlaceholder": False, "limit": 50, "nextToken": "opaque+/="}).execute({})
    assert dict(requests[0].url.params) == {"limit": "50", "nextToken": "opaque+/=", "name": "Acme + Co", "isPlaceholder": "false"}
    assert result["data"] == [] and not result["has_more"] and result["nextToken"] is None
    assert not requests[0].content


@pytest.mark.asyncio
async def test_documented_identity_fields_and_missing_identity(wire):
    _, reply = wire
    example = json.loads((Path(__file__).parent / "fixtures/assemblycom/me.json").read_text())["body"]
    reply["body"] = example
    assert (await node({"operation": "get_current_user"}).execute({}))["data"] == example
    reply["body"] = {}
    with pytest.raises(ValueError, match="identity"):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.asyncio
async def test_custom_fields_dates_and_archive(wire):
    requests, _ = wire
    fields = {"tags": ["option-1"], "address": {"city": "Boston"}, "clear": None, "amount": "12"}
    await node({"operation": "update_client", "client_id": ID, "customFields": fields, "sendInvite": True}).execute({})
    assert json.loads(requests[-1].content) == {"customFields": fields}
    assert requests[-1].url.params["sendInvite"] == "true"
    await node({"operation": "create_task", "name": "Onboard", "clientId": ID, "companyId": ID, "dueDate": "2025-05-01T16:18:54Z"}).execute({})
    assert json.loads(requests[-1].content)["dueDate"] == "2025-05-01T16:18:54Z"
    await node({"operation": "update_client", "client_id": ID, "status": "archived"}).execute({})
    assert json.loads(requests[-1].content) == {"status": "archived"} and not requests[-1].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize("field", list(native.PICKERS))
async def test_pickers_share_api_and_preserve_cursor(wire, field):
    requests, reply = wire
    reply["body"] = {"data": [{"id": ID, "name": "Owned resource"}], "nextToken": "next-cursor"}
    result = await native.AssemblyComNode.load_field_options(field, CREDENTIAL, page_token="previous-cursor")
    assert result == {"options": [{"value": ID, "label": "Owned resource"}], "next_page_token": "next-cursor"}
    assert requests[0].url.params["nextToken"] == "previous-cursor"


@pytest.mark.asyncio
async def test_empty_account_uses_identity_evidence(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    example = json.loads((Path(__file__).parent / "fixtures/assemblycom/me.json").read_text())["body"]
    async def perform(cls, op, credential):
        if op.operation == "list_clients":
            return {"status": "success", "data": [], "nextToken": None}
        return {"status": "success", "data": example}
    monkeypatch.setattr(native.AssemblyComNode, "_perform", classmethod(perform))
    result = await collect_evidence(node_type="automation-assemblycom", credential_data=CREDENTIAL, user_id="test", pool=None)
    assert result.reachable is True and result.account_label == "alex.morgan@example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_no_success_no_key_leak_no_retry(wire, status):
    requests, reply = wire
    reply.update(status=status, body={"message": f"Rejected {TOKEN}"}, headers={"Location": "https://other.example/"})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_current_user"}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {}, {"data": "bad"}, {"data": [], "nextToken": 123}, {"error": "failed"}])
async def test_bad_list_response_rejected(wire, body):
    _, reply = wire
    reply["body"] = body
    with pytest.raises(ValueError):
        await node({"operation": "list_clients"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_client", "client_id": "../clients"},
    {"operation": "list_clients", "limit": True},
    {"operation": "list_clients", "limit": 101},
    {"operation": "list_notes", "entityId": ID},
    {"operation": "create_client", "givenName": "Jane", "familyName": "Doe"},
    {"operation": "update_client", "client_id": ID, "status": "archived", "familyName": "Doe"},
    {"operation": "create_task", "name": "Task", "clientId": ID},
    {"operation": "create_message_channel", "membershipType": "group"},
    {"operation": "create_message_channel", "membershipType": "company"},
    {"operation": "send_message", "channelId": "messaging:" + ID, "text": "Hello"},
    {"operation": "send_message", "channelId": ID, "text": "x" * 5001},
    {"operation": "create_task", "name": "Task", "dueDate": "2025-05-01"},
    {"operation": "list_clients", "url": "https://evil.example/"},
])
def test_invalid_config_fails_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize("key", ["https://example.com/key", "<token>", "bad\r\nkey", "Bearer token"])
def test_hand_connect_default_and_secret_cleaning(key):
    assert native.AssemblyComAPIKeyCredential(api_key=TOKEN).credential_type == native.CREDENTIAL_TYPE
    with pytest.raises((ValueError, ValidationError)):
        native.AssemblyComAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,id_field", [("update_client", "client_id"), ("update_company", "company_id"), ("update_task", "task_id"), ("update_note", "note_id")])
async def test_empty_update_refused_without_network(wire, operation, id_field):
    requests, _ = wire
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": operation, id_field: ID}).execute({})
    assert not requests


def test_editor_metadata_uses_the_same_validation_and_runtime_view():
    raw = {"config": {"operation": "get_client", "client_id": ID,
        "client_id__label": "Jane Doe", "credentialIds": {"assemblycom_api_key": "saved-id"}},
        "credentials": CREDENTIAL}
    assert native.AssemblyComNode.validate_config(raw)["valid"]
    assert native.AssemblyComNode.parse_config(raw).config.client_id == ID
    assert "client_id__label" in raw["config"]
