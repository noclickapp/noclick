"""Fixed CallFire V2 requests and exact provider-authored response regressions."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import callfire_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "callfire"
RESPONSES = json.loads((FIXTURES / "documented_responses.json").read_text())
EMPTY_RESPONSES = json.loads((FIXTURES / "documented_empty_responses.json").read_text())
INPUTS = json.loads((FIXTURES / "documented_inputs.json").read_text())
CREDENTIAL = {"credential_type": "callfire_api_credentials", "api_login": "fixture-login", "api_password": "fixture-password"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="callfire-test", node_type="automation-callfire",
        node_data={"config": config, "credentials": CREDENTIAL})


# Independent expected routes, bodies and query locations. Each entry is a
# provider operation; never derive this expectation from the node's route map.
CASES = [
    ("get_account", "GET", "/me/account", {}, None),
    ("list_texts", "GET", "/texts", {"offset": 10, "limit": 10, "inbound": False}, None),
    ("get_text", "GET", "/texts/{id}", {"id": 379506003}, None),
    ("send_texts", "POST", "/texts", INPUTS["send_texts"]["config"], "recipients"),
    ("list_calls", "GET", "/calls", {"limit": 10}, None),
    ("get_call", "GET", "/calls/{id}", {"id": 379506003}, None),
    ("send_calls", "POST", "/calls", INPUTS["send_calls"]["config"], "recipients"),
    ("list_contacts", "GET", "/contacts", {}, None),
    ("get_contact", "GET", "/contacts/{id}", {"id": 379506003}, None),
    ("create_contacts", "POST", "/contacts", INPUTS["create_contacts"]["config"], "contacts"),
    ("update_contact", "PUT", "/contacts/{id}", INPUTS["update_contact"]["config"], "contact"),
    ("delete_contact", "DELETE", "/contacts/{id}", {"id": 379506003}, None),
    ("list_contact_lists", "GET", "/contacts/lists", {"name": "my list"}, None),
    ("get_contact_list", "GET", "/contacts/lists/{id}", {"id": 379506003}, None),
    ("create_contact_list", "POST", "/contacts/lists", INPUTS["create_contact_list"]["config"], "object"),
    ("update_contact_list", "PUT", "/contacts/lists/{id}", {"id": 379506003, "name": "New name"}, "object"),
    ("delete_contact_list", "DELETE", "/contacts/lists/{id}", {"id": 379506003}, None),
    ("list_contact_list_items", "GET", "/contacts/lists/{id}/items", {"id": 379506003}, None),
    ("add_contact_list_items", "POST", "/contacts/lists/{id}/items", INPUTS["add_contact_list_items"]["config"], "object"),
    ("list_text_broadcasts", "GET", "/texts/broadcasts", {}, None),
    ("get_text_broadcast", "GET", "/texts/broadcasts/{id}", {"id": 379506003}, None),
    ("create_text_broadcast", "POST", "/texts/broadcasts", INPUTS["create_text_broadcast"]["config"], "object"),
    ("start_text_broadcast", "POST", "/texts/broadcasts/{id}/start", {"id": 379506003}, None),
    ("stop_text_broadcast", "POST", "/texts/broadcasts/{id}/stop", {"id": 379506003}, None),
]


def mock_client(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config,body_key", CASES)
async def test_each_operation_one_request_auth_and_documented_response(monkeypatch, operation, method, path, config, body_key):
    witness = RESPONSES.get(method + " " + path)
    def reply(request):
        if witness:
            return httpx.Response(201 if operation == "create_text_broadcast" else 200, json=witness["body"])
        if method == "GET":
            return httpx.Response(200, json={"items": [], "totalCount": 0})
        return httpx.Response(EMPTY_RESPONSES[method + " " + path]["status"])
    requests = mock_client(monkeypatch, reply)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith("https://api.callfire.com/v2/")
    assert request.url.path == "/v2" + path.format(id=config.get("id"))
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"fixture-login:fixture-password").decode()
    assert "fixture-password" not in str(result)
    params = dict(request.url.params)
    if method == "GET":
        assert not request.content
        expected = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items() if k != "id"}
        if operation.startswith("list_"):
            expected = {"limit": "100", "offset": "0", **expected}
        if operation == "get_account":
            expected = {"fields": "id,name,companyName"}
        assert params == expected
    elif body_key:
        expected = {k: v for k, v in config.items() if k not in {"id", "campaignId", "defaultMessage"}}
        if body_key != "object":
            expected = config[body_key]
        assert json.loads(request.content) == expected
        if operation in {"send_texts", "send_calls"}:
            assert params == {"strictValidation": "true", **{k: str(v) for k, v in config.items() if k in {"campaignId", "defaultMessage"}}}
        elif operation == "create_text_broadcast":
            assert params == {"start": "false", "strictValidation": "true"}
        else:
            assert not params
    else:
        assert not request.content and not params
    if operation == "get_account":
        assert result["data"] == {"id": 1, "name": "Test Account"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_errors_preserve_rejection_and_never_retry(monkeypatch, status):
    requests = mock_client(monkeypatch, lambda request: httpx.Response(status,
        json={"message": "Rejected fixture-password", "httpStatusCode": status}))
    result = await node({"operation": "get_account"}).execute({})
    assert result == {"status": "error", "error": "Rejected [redacted]", "http_status": status}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"id": 1}, {"message": "failed", "httpStatusCode": 401}])
async def test_connection_requires_account_identity(monkeypatch, body):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_page_continuation_and_empty_page(monkeypatch):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json={"items": [{"id": 10}], "totalCount": 3}))
    result = await node({"operation": "list_contacts", "offset": 1, "limit": 1}).execute({})
    assert result["next_offset"] == 2
    mock_client(monkeypatch, lambda request: httpx.Response(200, json={"items": [], "totalCount": 3}))
    assert (await node({"operation": "list_contacts", "offset": 2, "limit": 1}).execute({}))["next_offset"] is None


def test_manual_credential_default_shape_and_rejection():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("callfire_api_credentials", {"api_login": " fixture-login ", "api_password": " fixture-password "})
    assert not errors and shaped == {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
    assert native.CallFireCredential.model_validate(shaped).credential_type == "callfire_api_credentials"
    assert resolved[0] == "automation-callfire"
    for value in ["https://example.com", "<token>", "Basic header", ""]:
        with pytest.raises(ValidationError):
            native.CallFireCredential(api_login=value, api_password="fixture-password")


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "id": "../texts"},
    {"operation": "get_contact", "id": 0},
    {"operation": "list_contacts", "offset": -1},
    {"operation": "send_texts", "recipients": [{"phoneNumber": "+12135551122", "message": "Hi"}]},
    {"operation": "send_texts", "recipients": [{"phoneNumber": "12135551122"}]},
    {"operation": "send_calls", "recipients": [{"phoneNumber": "12135551122", "liveMessage": "Hi"}] * 11},
    {"operation": "create_contacts", "contacts": [{"firstName": "Missing phone"}]},
])
def test_invalid_requests_rejected_before_network(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200), httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, json=[])])
async def test_empty_html_or_unexpected_identity_is_not_success(monkeypatch, response):
    requests = mock_client(monkeypatch, lambda request: response)
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_transport_timeout_does_not_retry_send(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("provider timeout", request=request)
    requests = mock_client(monkeypatch, timeout)
    result = await node({"operation": "send_texts", **INPUTS["send_texts"]["config"]}).execute({})
    assert result["status"] == "error" and "before retrying a write" in result["error"]
    assert len(requests) == 1
