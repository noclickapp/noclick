"""Offline JustCall v2.1 routing, payload, pagination and failure regressions."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import justcall_node as native
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**changes):
    return {
        "credential_type": "justcall_api_key",
        "api_key": "synthetic-key-42",
        "api_secret": "synthetic-secret-42",
        **changes,
    }


def node(config):
    return NodeFactory.create_node(
        node_id="justcall-fixture",
        node_type="automation-justcall",
        node_data={"config": config, "credentials": credential()},
    )


def mock_client(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return (
            response(request)
            if callable(response)
            else httpx.Response(200, json=response)
        )

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Expected wire contracts are independent of the node's routing table.
CASES = [
    (
        {"operation": "list_contacts", "page": 2, "first_name": "Rachel"},
        "GET",
        "/contacts",
        {"page": "2", "first_name": "Rachel"},
        None,
    ),
    ({"operation": "get_contact", "id": 1234}, "GET", "/contacts/1234", {}, None),
    (
        {
            "operation": "create_contact",
            "first_name": "Rachel",
            "contact_number": "19988776655",
        },
        "POST",
        "/contacts",
        {},
        {"first_name": "Rachel", "contact_number": "19988776655"},
    ),
    (
        {"operation": "update_contact", "id": 1234, "notes": [{"note": "Follow up"}]},
        "PUT",
        "/contacts",
        {},
        {"id": 1234, "notes": [{"note": "Follow up"}]},
    ),
    (
        {"operation": "delete_contact", "id": 1234},
        "DELETE",
        "/contacts",
        {"id": "1234"},
        None,
    ),
    (
        {
            "operation": "list_calls",
            "from_datetime": "2025-01-01",
            "fetch_ai_data": False,
        },
        "GET",
        "/calls",
        {"from_datetime": "2025-01-01", "fetch_ai_data": "false"},
        None,
    ),
    (
        {"operation": "get_call", "id": "call_sid-123", "fetch_queue_data": True},
        "GET",
        "/calls/call_sid-123",
        {"fetch_queue_data": "true"},
        None,
    ),
    (
        {
            "operation": "update_call",
            "id": "call_sid-123",
            "notes": "Replace old note",
            "rating": 4.5,
        },
        "PUT",
        "/calls/call_sid-123",
        {},
        {"notes": "Replace old note", "rating": 4.5},
    ),
    (
        {"operation": "get_call_journey", "id": "call_sid-123"},
        "GET",
        "/calls/call_sid-123/journey",
        {},
        None,
    ),
    (
        {"operation": "list_users", "email": "john.smith@abc.co"},
        "GET",
        "/users",
        {"email": "john.smith@abc.co"},
        None,
    ),
    ({"operation": "get_user", "id": 1234}, "GET", "/users/1234", {}, None),
    (
        {"operation": "list_phone_numbers", "capabilities": "sms"},
        "GET",
        "/phone-numbers",
        {"capabilities": "sms"},
        None,
    ),
    (
        {"operation": "get_phone_number", "id": 1234},
        "GET",
        "/phone-numbers/1234",
        {},
        None,
    ),
    (
        {"operation": "list_texts", "per_page": 100},
        "GET",
        "/texts",
        {"per_page": "100"},
        None,
    ),
    ({"operation": "get_text", "id": 1234}, "GET", "/texts/1234", {}, None),
    (
        {
            "operation": "send_sms",
            "body": "Hello",
            "justcall_number": "+14155550101",
            "contact_number": "+14155550102",
            "restrict_once": "Yes",
        },
        "POST",
        "/texts/new",
        {},
        {
            "body": "Hello",
            "justcall_number": "+14155550101",
            "contact_number": "+14155550102",
            "restrict_once": "Yes",
        },
    ),
    (
        {"operation": "list_tags", "order": "asc"},
        "GET",
        "/texts/tags",
        {"order": "asc"},
        None,
    ),
    ({"operation": "get_tag", "id": 1234}, "GET", "/texts/tags/1234", {}, None),
    (
        {"operation": "create_tag", "name": "Warm Lead", "color_code": "#721ea9"},
        "POST",
        "/texts/tags",
        {},
        {"name": "Warm Lead", "color_code": "#721ea9"},
    ),
    ({"operation": "delete_tag", "id": 1234}, "DELETE", "/texts/tags/1234", {}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES)
async def test_routes_auth_payload_and_response(
    monkeypatch, config, method, path, query, body
):
    reply = {
        "data": [{"id": 1234, "name": "John Doe"}],
        "next_page_link": "https://api.justcall.io/v2.1/users?page=3",
    }
    requests = mock_client(monkeypatch, reply)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": reply}
    assert len(requests) == 1
    req = requests[0]
    assert (
        req.method == method
        and req.url.host == "api.justcall.io"
        and req.url.path == "/v2.1" + path
    )
    assert req.headers["Authorization"] == "synthetic-key-42:synthetic-secret-42"
    assert req.headers["Accept"] == "application/json"
    assert dict(req.url.params) == query
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_contact", "id": 0},
        {"operation": "get_call", "id": "../contacts"},
        {"operation": "list_users", "per_page": 101},
        {"operation": "list_calls", "page": -1},
        {"operation": "update_contact", "id": 1234},
        {"operation": "update_call", "id": "1234"},
        {"operation": "update_call", "id": "1234", "rating": 2.3},
        {"operation": "create_tag", "name": "Warm Lead", "color_code": "red"},
        {
            "operation": "send_sms",
            "body": "Hello",
            "justcall_number": "14155550101",
            "contact_number": "+14155550102",
        },
        {"operation": "delete_contact", "id": 1234, "across_team": True},
    ],
)
def test_invalid_inputs_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key": "https://example.com/key"},
        {"api_secret": "key:secret"},
        {"api_secret": "bad\nheader"},
        {"api_key": "<token>"},
        {"credential_type": "other_api_key"},
    ],
)
def test_invalid_credentials_rejected(changes):
    with pytest.raises(ValidationError):
        native.JustCallAPIKeyCredential.model_validate(credential(**changes))


def test_manual_credential_default_and_trimming():
    c = native.JustCallAPIKeyCredential(
        api_key="  actual-key-42  ", api_secret="  actual-secret-42  "
    )
    assert (
        c.credential_type == "justcall_api_key"
        and c.api_key == "actual-key-42"
        and c.api_secret == "actual-secret-42"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_http_failures_no_retry_or_secret_leak(monkeypatch, status):
    requests = mock_client(
        monkeypatch,
        lambda _: httpx.Response(
            status,
            headers={"Location": "https://example.com"},
            json={"message": "Denied synthetic-key-42 synthetic-secret-42"},
        ),
    )
    result = await node(
        {"operation": "create_tag", "name": "Warm Lead", "color_code": "#721ea9"}
    ).execute({})
    assert (
        result["status"] == "error"
        and result["status_code"] == status
        and len(requests) == 1
    )
    assert "Denied" in result["error"] and "synthetic-" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [{"success": False, "message": "Denied"}, {"status": "error", "error": "Denied"}],
)
async def test_error_envelope_not_connection_success(monkeypatch, response):
    mock_client(monkeypatch, response)
    assert (await node({"operation": "list_users"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_read_evidence_response_and_failure_shapes(monkeypatch):
    requests = mock_client(monkeypatch, {"data": [{"name": "John Doe"}]})
    from nodes.core.connection_evidence import _rows_from_operation

    result = await node({"operation": "list_users"}).execute({})
    assert _rows_from_operation(result) == [{"name": "John Doe"}]
    assert requests[0].method == "GET" and not requests[0].url.query
    mock_client(monkeypatch, lambda _: httpx.Response(200, text="<html>Sign in</html>"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "list_users"}).execute({})


@pytest.mark.asyncio
async def test_transport_failure_has_no_credential_details(monkeypatch):
    def fail(request):
        raise httpx.ConnectError("synthetic-key-42", request=request)

    requests = mock_client(monkeypatch, fail)
    result = await node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and len(requests) == 1
    assert "synthetic-key-42" not in str(result)
