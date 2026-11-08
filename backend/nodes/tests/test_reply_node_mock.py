"""Offline Reply request/response regressions with synthetic account data."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import reply_node as native
from nodes.core.registry import NodeFactory

TOKEN = "reply-test-key-12345"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/reply/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="reply-fixture", node_type="automation-reply", node_data={
        "config": config,
        "credentials": credentials or {"credential_type": "reply_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, status=200, body=None, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs == {"timeout": 30.0, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Independent wire expectations: names in this table are the provider's v3 routes.
CASES = [
    ({"operation": "get_account"}, "GET", "/v3/whoami", None, 200, "account"),
    ({"operation": "list_contacts", "email": "john.doe@company.com"}, "GET", "/v3/contacts", None, 200, "page"),
    ({"operation": "get_contact", "contact_id": 42}, "GET", "/v3/contacts/42", None, 200, "contact"),
    ({"operation": "create_contact", "email": "john.doe@company.com", "firstName": "John"}, "POST", "/v3/contacts", {"email": "john.doe@company.com", "firstName": "John"}, 201, "contact"),
    ({"operation": "update_contact", "contact_id": 42, "firstName": "Jane", "isOptedOut": False}, "PATCH", "/v3/contacts/42", {"firstName": "Jane", "isOptedOut": False}, 200, "contact"),
    ({"operation": "delete_contact", "contact_id": 42}, "DELETE", "/v3/contacts/42", None, 204, None),
    ({"operation": "list_contact_notes", "contact_id": 42}, "GET", "/v3/contacts/42/notes", None, 200, "page"),
    ({"operation": "add_contact_note", "contact_id": 42, "notes": "Met at conference"}, "POST", "/v3/contacts/42/notes", {"notes": "Met at conference"}, 204, None),
    ({"operation": "list_contact_lists", "search": "Conference"}, "GET", "/v3/contact-lists", None, 200, "page"),
    ({"operation": "create_contact_list", "name": "Conference leads"}, "POST", "/v3/contact-lists", {"name": "Conference leads", "isShared": False}, 201, "contact_list"),
    ({"operation": "add_contacts_to_list", "list_id": 42, "contactIds": [42]}, "POST", "/v3/contact-lists/42/add-contacts", {"contactIds": [42]}, 200, "empty"),
    ({"operation": "list_sequences", "isArchived": False}, "GET", "/v3/sequences", None, 200, "page"),
    ({"operation": "get_sequence", "sequence_id": 42}, "GET", "/v3/sequences/42", None, 200, "sequence"),
    ({"operation": "start_sequence", "sequence_id": 42}, "POST", "/v3/sequences/42/start", None, 200, "sequence"),
    ({"operation": "pause_sequence", "sequence_id": 42}, "POST", "/v3/sequences/42/pause", None, 200, "sequence"),
    ({"operation": "list_sequence_contacts", "sequence_id": 42}, "GET", "/v3/sequences/42/contacts", None, 200, "page"),
    ({"operation": "add_contacts_to_sequence", "sequence_id": 42, "contactIds": [42]}, "POST", "/v3/sequences/42/contact-links/bulk", {"contactIds": [42], "removeFromExisting": False, "ignoreStepDelay": False}, 200, "bulk"),
    ({"operation": "remove_contact_from_sequence", "sequence_id": 42, "contact_id": 9}, "DELETE", "/v3/sequences/42/contact-links/9", None, 204, None),
    ({"operation": "list_tasks"}, "GET", "/v3/tasks", None, 200, "page"),
    ({"operation": "get_task", "task_id": 42}, "GET", "/v3/tasks/42", None, 200, "task"),
    ({"operation": "complete_task", "task_id": 42}, "POST", "/v3/tasks/42/complete", {"finishProspectInSequence": False}, 200, "task"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,status,fixture", CASES, ids=[x[0]["operation"] for x in CASES])
async def test_each_operation_exact_wire_contract(monkeypatch, config, method, path, body, status, fixture):
    response = {"items": [FIXTURE["contact_list"]], "hasMore": False} if fixture == "page" else {} if fixture == "empty" else FIXTURE.get(fixture)
    requests = transport(monkeypatch, status, response)
    result = await node(config).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.reply.io"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    expected_query = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items() if k not in {"operation", "contact_id", "sequence_id", "task_id"}} if method == "GET" else {}
    if fixture == "page": expected_query.update(top="25", skip="0")
    if config["operation"] == "get_task": expected_query["includeContent"] = "false"
    assert dict(request.url.params) == expected_query
    assert TOKEN not in str(result)
    if fixture == "page": assert result["has_more"] is False and result["next_skip"] is None
    if status == 204: assert result["acknowledged"] is True


@pytest.mark.asyncio
async def test_paging_preserves_filters_and_continuation(monkeypatch):
    requests = transport(monkeypatch, body={"items": [FIXTURE["contact"]], "hasMore": True})
    result = await node({"operation": "list_contacts", "top": 1, "skip": 10, "email": "a+b@example.test"}).execute({})
    assert result["next_skip"] == 11 and result["has_more"] is True
    assert dict(requests[0].url.params) == {"top": "1", "skip": "10", "email": "a+b@example.test"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 301, 302, 400, 401, 403, 404, 409, 429, 500])
async def test_failed_writes_no_retry_no_secret_no_redirect(monkeypatch, status):
    requests = transport(monkeypatch, status, {"detail": "Refused " + TOKEN}, {"Retry-After": "60", "Location": "https://evil.example.test"})
    result = await node({"operation": "start_sequence", "sequence_id": 42}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["retry_after"] == "60" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"items": [], "hasMore": "false"}, {"items": {}, "hasMore": False}, {"items": [], "hasMore": True}])
async def test_invalid_page_never_becomes_connection_evidence(monkeypatch, body):
    transport(monkeypatch, body=body)
    assert (await node({"operation": "list_contact_lists"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_empty_account_page_is_valid_and_token_is_redacted(monkeypatch):
    transport(monkeypatch, body={"items": [], "hasMore": False})
    assert (await node({"operation": "list_contact_lists"}).execute({}))["items"] == []
    transport(monkeypatch, body={"items": [{"name": TOKEN}], "hasMore": False})
    assert TOKEN not in str(await node({"operation": "list_contact_lists"}).execute({}))


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../42"},
    {"operation": "get_contact", "contact_id": 0},
    {"operation": "create_contact"},
    {"operation": "update_contact", "contact_id": 42},
    {"operation": "add_contacts_to_list", "list_id": 42, "contactIds": []},
    {"operation": "list_contacts", "top": 101},
    {"operation": "complete_task", "task_id": 42, "callResolution": 5},
    {"operation": "list_tasks", "url": "https://evil.example.test"},
])
def test_bad_configs_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_schema_and_credential_contract():
    assert len(CASES) == 21
    assert native.ReplyNode.connection_evidence.operation == "list_contact_lists"
    assert native.ReplyNode.connection_evidence.identity_keys == ("username",)
    credential = native.ReplyAPIKeyCredential(api_key="  " + TOKEN + "\n")
    assert credential.api_key == TOKEN
    for key in ["Bearer " + TOKEN, "https://example.test", "<api-key>"]:
        with pytest.raises(ValidationError): native.ReplyAPIKeyCredential(api_key=key)
    with pytest.raises(ValidationError): native.ReplyAPIKeyCredential(api_key=TOKEN, credential_type="another_key")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"username": "", "userId": 42, "teamId": 7}, {"username": "sales", "userId": "42", "teamId": 7}])
async def test_missing_identity_never_proves_account(monkeypatch, body):
    transport(monkeypatch, body=body)
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_success_status_error_envelope_is_not_success(monkeypatch):
    transport(monkeypatch, body={"status": 401, "detail": "Refused " + TOKEN})
    result = await node({"operation": "get_contact", "contact_id": 42}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)
