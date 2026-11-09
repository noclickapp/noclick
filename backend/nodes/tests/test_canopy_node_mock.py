"""Native factory and HTTP boundary tests; no live account or credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import canopy_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-canopy-api-key-12345"
PUBLISHED = json.loads((Path(__file__).parent / "fixtures/canopy/published_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="canopy-test", node_type="automation-canopy",
        node_data={"config": config, "credentials": {"credential_type": "canopy_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_canopy_connection_uses_tenant_clients_and_keeps_cursor(monkeypatch):
    payload = PUBLISHED["GET /clients"]
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "list_clients"}).execute({})
    assert result["data"] == payload
    assert native.CanopyNode.connection_evidence.operation == "list_clients"
    assert requests[0].headers["x-canopy-api-key"] == TOKEN
    assert requests[0].url.host == "api.dev.canopytax.com"
    assert requests[0].url.path == "/public/v4/clients"
    assert dict(requests[0].url.params) == {"limit": "100"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [
    ("get_client", "/clients/{client_id}"),
    ("get_contact", "/contacts/{contact_id}"),
])
async def test_canopy_parses_published_detail_responses(monkeypatch, operation, route):
    config = {"operation": operation}
    for field in ("client_id", "contact_id", "note_id", "task_id"):
        if "{" + field + "}" in route:
            config[field] = 123 if operation == "get_client_note" else "ABC123"
    payload = PUBLISHED["GET " + route]
    transport(monkeypatch, payload)
    assert (await node(config).execute({}))["data"] == payload


@pytest.mark.asyncio
async def test_canopy_search_encodes_query_and_cursor_without_url_follow(monkeypatch):
    payload = {"contacts": [], "next_cursor": "opaque + /cursor?x=1"}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "search_contacts", "q": "Jane + café@example.com",
        "query_field": "email", "next_cursor": "https://untrusted.invalid/page"}).execute({})
    assert result["data"] == payload
    assert requests[0].url.params["q"] == "Jane + café@example.com"
    assert requests[0].url.params["next_cursor"] == "https://untrusted.invalid/page"
    assert requests[0].url.host == "api.dev.canopytax.com" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,expected", [
    ({"operation": "create_client", "client": {"is_business": True, "name": "Example", "business_name": "Example LLC"}},
        "POST", "/clients", {"client": {"is_business": True, "name": "Example", "business_name": "Example LLC", "type": "CLIENT"}}),
    ({"operation": "create_contact", "contact": {"first_name": "Jane", "last_name": "Doe"}},
        "POST", "/contacts", {"contact": {"first_name": "Jane", "last_name": "Doe"}}),
    ({"operation": "create_client_note", "client_id": 123, "notes": {"title": "Call", "body": "Follow up"}},
        "POST", "/clients/123/notes", {"notes": {"title": "Call", "body": "Follow up"}}),
    ({"operation": "update_client_note", "client_id": 123, "note_id": 456, "notes": {"is_pinned": False}},
        "PATCH", "/clients/123/notes/456", {"notes": {"is_pinned": False}}),
    ({"operation": "create_task", "tasks": {"name": "Task 1", "status_id": "NOSTATUS"}},
        "POST", "/tasks", {"tasks": {"name": "Task 1", "status_id": "NOSTATUS", "description": ""}}),
    ({"operation": "update_task", "task_id": "ABCD", "task": {"status_id": "NOTSTARTED", "budgeted_hours": 0}},
        "PATCH", "/tasks/ABCD", {"status_id": "NOTSTARTED", "budgeted_hours": 0}),
])
async def test_canopy_write_envelopes_and_flat_task_patch(monkeypatch, config, method, path, expected):
    _, _, envelope, _ = native.ROUTES[config["operation"]]
    requests = transport(monkeypatch, lambda _: httpx.Response(201 if method == "POST" else 200, json={envelope: {"id": "123"}}))
    assert (await node(config).execute({}))["status"] == "success"
    assert len(requests) == 1 and requests[0].method == method
    assert requests[0].url.path == "/public/v4" + path
    assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_canopy_errors_do_not_retry_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, text="Denied " + TOKEN))
    result = await node({"operation": "list_clients"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"clients": {}}, {"clients": [], "errors": ["denied"]}])
async def test_canopy_rejects_malformed_success(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="response envelope"):
        await node({"operation": "list_clients"}).execute({})


@pytest.mark.parametrize("changes", [{"is_archived": True, "title": "ignored"}, {"is_pinned": False, "body": "ignored"}, {"is_pinned": True, "is_archived": False}, {}])
def test_canopy_note_update_does_not_silently_ignore_fields(changes):
    with pytest.raises(ValidationError):
        native.NoteChanges.model_validate(changes)


@pytest.mark.parametrize("bad_id", ["../other", "a/b", "a?b", "https://bad.invalid", "a#b"])
def test_canopy_path_ids_are_single_segments(bad_id):
    with pytest.raises(ValidationError):
        native.CanopyGetClientConfig(client_id=bad_id)


def test_canopy_individual_needs_primary_contact():
    with pytest.raises(ValidationError, match="primary contact"):
        native.IndividualClient(name="Jane", contacts=[{"id": "ABCD", "is_primary": False}])


def test_canopy_manual_credential_defaults_type_and_cleans_key():
    credential = native.CanopyAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "canopy_api_key" and credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.CanopyAPIKeyCredential(api_key="https://example.com/key")


@pytest.mark.asyncio
async def test_canopy_contact_email_write_uses_value_key_not_read_fields(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(201, json={"contact": {"id": "X9K2P"}}))
    await node({"operation": "create_contact", "contact": {"first_name": "Jane", "last_name": "Doe",
        "emails": [{"value": "jane@example.com", "key": "WORK", "is_primary": True}]}}).execute({})
    assert json.loads(requests[0].content)["contact"]["emails"] == [
        {"value": "jane@example.com", "key": "WORK", "is_primary": True}]
