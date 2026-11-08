"""Exercise each Tidy operation at the HTTP boundary, without live credentials."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import tidy_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.tidy_oauth import OAUTH_PROVIDER

TOKEN = "synthetic-tidy-token"
CASES = json.loads((Path(__file__).parent / "fixtures/tidy/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="tidy-test", node_type="automation-tidy",
        node_data={"config": config, "credentials": {
            "credential_type": "tidy_oauth", "access_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_tidy_native_request_contract(monkeypatch, case):
    operation = case["config"]["operation"]
    deleting = case["method"] == "DELETE"
    status = 204 if deleting else 201 if operation == "create_contact" else 200
    payload = [{"id": "abc123"}] if operation.startswith("list_") else {"id": "abc123", "first_name": "First", "last_name": "Last", "metadata": None}
    requests = transport(monkeypatch, httpx.Response(status, **({} if deleting else {"json": payload})))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["http_status"] == status
    if deleting:
        assert result["deleted"] is True
    else:
        assert result["data"] == payload
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.tidyhq.com"
    assert request.url.path == "/v2" + case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_tidy_page_filters_headers_and_null_fields(monkeypatch):
    payload = [{"id": "abc123", "first_name": "First", "website": None, "metadata": None}]
    requests = transport(monkeypatch, httpx.Response(200, json=payload, headers={
        "X-Pagination-Per-Page": "25", "X-Pagination-Current-Page": "2",
        "X-Pagination-Total-Pages": "10", "X-Pagination-Total-Entries": "247"}))
    result = await node({"operation": "list_contacts", "offset": 25, "registered": False,
        "search_terms": "First", "updated_since": "2026-01-01T00:00:00Z"}).execute({})
    assert result["data"] == payload
    assert result["pagination"]["X-Pagination-Total-Entries"] == "247"
    assert dict(requests[0].url.params) == {"limit": "25", "offset": "25", "registered": "false",
        "search_terms": "First", "updated_since": "2026-01-01T00:00:00Z"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404, 422, 429, 500])
async def test_tidy_provider_errors_are_failures_and_hide_token(monkeypatch, code):
    transport(monkeypatch, httpx.Response(code, json={"message": "Rejected " + TOKEN}))
    result = await node({"operation": "list_contacts"}).execute({})
    assert result == {"status": "error", "http_status": code, "error": "Rejected [redacted]"}


@pytest.mark.asyncio
async def test_tidy_success_status_error_envelope_is_failure(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"errors": {"email": ["Invalid"]}}))
    assert (await node({"operation": "list_contacts"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_tidy_empty_subscription_update_acknowledgement(monkeypatch):
    transport(monkeypatch, httpx.Response(200))
    result = await node({"operation": "update_membership_subscription", "membership_id": "abc123",
        "subscription_id": "def456", "state": "cancelled"}).execute({})
    assert result == {"status": "success", "operation": "update_membership_subscription", "http_status": 200, "data": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://example.com"}),
    httpx.Response(200, text="<html>wrong host</html>"),
    httpx.Response(200, headers={"content-type": "application/json"}, content=b"invalid"),
    httpx.Response(200, json={}), httpx.Response(200, json=[None]),
])
async def test_tidy_malformed_list_never_succeeds(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_contacts"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_tidy_nested_token_redaction(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"id": "abc123", "notes": [{"text": TOKEN}]}))
    result = await node({"operation": "get_contact", "contact_id": "abc123"}).execute({})
    assert result["data"]["notes"] == [{"text": "[redacted]"}]


@pytest.mark.asyncio
async def test_tidy_write_timeout_is_never_retried(monkeypatch):
    calls = []

    async def request(self, *args, **kwargs):
        calls.append(args)
        raise httpx.ReadTimeout("timeout")

    transport(monkeypatch, httpx.Response(200, json={}))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(httpx.ReadTimeout):
        await node({"operation": "create_contact", "first_name": "First", "last_name": "Last"}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../contacts"},
    {"operation": "get_contact", "contact_id": ".."},
    {"operation": "get_contact", "contact_id": "abc?access_token=secret"},
    {"operation": "list_contacts", "limit": 0},
    {"operation": "list_contacts", "offset": -1},
    {"operation": "update_contact", "contact_id": "abc123"},
    {"operation": "create_membership_subscription", "membership_id": "abc123", "payment_type": "paid"},
    {"operation": "update_membership_subscription", "membership_id": "abc123", "subscription_id": "def456"},
    {"operation": "list_contacts", "base_url": "https://example.com"},
])
def test_tidy_invalid_input_rejected(config):
    assert native.TidyNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("token", ["", "Bearer secret", "https://example.com", "<api-token>", "abc\nxyz", 123])
def test_tidy_invalid_token_rejected(token):
    with pytest.raises((ValidationError, ValueError)):
        native.TidyOAuthCredential(access_token=token)


@pytest.mark.asyncio
async def test_tidy_oauth_exchange_nonexpiring_identity(monkeypatch):
    # Tidy's documented authorization-code response has null expiry and refresh.
    for name in ("TIDY_CLIENT_ID", "TIDY_CLIENT_SECRET"):
        monkeypatch.setenv(name, "synthetic-" + name)
    callback = "https://app.example/api/auth/oauth/tidy/callback"
    monkeypatch.setenv("TIDY_REDIRECT_URI", callback)
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/oauth/token":
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["authorization_code"], "code": ["synthetic-code"],
                "redirect_uri": [callback], "client_id": ["synthetic-TIDY_CLIENT_ID"],
                "client_secret": ["synthetic-TIDY_CLIENT_SECRET"]}
            return httpx.Response(200, json={"access_token": TOKEN, "token_type": "bearer",
                "expires_in": None, "refresh_token": None})
        assert str(request.url) == "https://api.tidyhq.com/v2/contacts/me"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        return httpx.Response(200, json={"id": "abc123", "full_name": "First Last"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    tokens, name = await OAUTH_PROVIDER.exchange("synthetic-code", callback)
    assert name == "First Last" and tokens.refresh_token is None and tokens.expires_at is None
    assert len(requests) == 2
    assert OAUTH_PROVIDER.scope_registry.declared_scopes() == []
    assert native.TidyNode.connection_evidence.identity_operation == "get_current_contact"
    credential = native.TidyOAuthCredential(access_token=tokens.access_token).model_dump()
    assert await native.TidyNode.freshen_credential(credential) == credential


@pytest.mark.asyncio
async def test_tidy_undocumented_delete_status_is_not_acknowledgement(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"id": "abc123"}))
    with pytest.raises(ValueError, match="did not confirm"):
        await node({"operation": "delete_contact", "contact_id": "abc123"}).execute({})
