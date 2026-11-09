"""Estimate Rocket v1 request/response regressions; no live account is used."""
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import converted_da_56088_node as native
from nodes.converted_da_56088_operations import ROUTES
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.oauth.converted_da_56088_oauth import OAUTH_PROVIDER

TOKEN = "synthetic-estimate-rocket-token"
REQUESTS = json.loads((Path(__file__).parent / "fixtures/converted-da-56088/requests.json").read_text())["examples"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="estimate-test", node_type=native.EstimateRocketNode.integration_type,
        node_data={"config": config, "credentials": {"credential_type": "estimaterocket_oauth", "access_token": TOKEN, **credential}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def test_discovery_oauth_contract_and_manual_default():
    assert NODE_REGISTRY[native.EstimateRocketNode.integration_type] is native.EstimateRocketNode
    assert native.EstimateRocketOAuthCredential(access_token=TOKEN).credential_type == "estimaterocket_oauth"
    assert OAUTH_PROVIDER.identity_url == native.BASE_URL + "/api/v1/me"
    assert OAUTH_PROVIDER.name_field == "employee.name"
    assert set(native.ESTIMATE_ROCKET_SCOPES) == set(ROUTES)
    assert set(native.ESTIMATE_ROCKET_SCOPES.declared_scopes()) == {"read", "write"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(ROUTES))
async def test_all_operations_one_exact_provider_call(monkeypatch, operation):
    method, template, envelope, query_filter = ROUTES[operation]
    config = {"operation": operation}
    expected_body = None
    expected_path = template
    if method == "POST":
        # Provider-authored examples, restricted to the documented input fields.
        expected_body = json.loads(json.dumps(REQUESTS[operation]))
        if operation == "create_client":
            for field in ("middle_name", "no_email", "no_phone", "tags"):
                expected_body[envelope].pop(field)
        config.update({key: value for key, value in expected_body[envelope].items() if value is not None})
        expected_body[envelope] = {key: value for key, value in expected_body[envelope].items() if value is not None}
    elif "{" in template:
        key = template.split("{")[1].split("}")[0]
        config[key] = "resource-123"
        expected_path = template.replace("{" + key + "}", "resource-123")
    elif query_filter:
        config[query_filter] = "A + B@example.com"
    record = {"id": "resource-123", "name": "Taylor Contractor"}
    body = {envelope: [record] if operation.startswith("list_") else record}
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "estimate-rocket-api.herokuapp.com"
    assert request.url.path == expected_path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == ({"filter[" + query_filter + "]": config[query_filter]} if query_filter else {})
    if expected_body is not None:
        sent = json.loads(request.content)
        if operation == "create_time_entry":
            for field in ("in_at", "out_at"):
                assert datetime.fromisoformat(sent[envelope].pop(field)) == datetime.fromisoformat(expected_body[envelope].pop(field))
        assert sent == expected_body
    else:
        assert request.content == b""
    assert result["status"] == "success" and result["data"] == body[envelope]
    if operation == "get_current_employee":
        assert result["name"] == "Taylor Contractor"


@pytest.mark.asyncio
async def test_empty_account_collection_and_encoded_identifier(monkeypatch):
    requests = transport(monkeypatch, {"clients": []})
    assert (await node({"operation": "list_clients"}).execute({}))["data"] == []
    assert not requests[0].url.query
    requests = transport(monkeypatch, {"client": {"id": "abc/def?x#y"}})
    await node({"operation": "get_client", "client_id": "abc/def?x#y"}).execute({})
    assert requests[0].url.raw_path == b"/api/v1/clients/abc%2Fdef%3Fx%23y"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    httpx.Response(302, headers={"location": "https://other.example/"}),
    httpx.Response(200, text="<html>Sign in</html>"),
    httpx.Response(200, json={"clients": {}}),
    httpx.Response(200, json={"clients": [1]}),
    httpx.Response(200, json={}),
    httpx.Response(200, content=b"{invalid", headers={"content-type": "application/json"}),
])
async def test_unconfirmed_response_is_never_success(monkeypatch, reply):
    transport(monkeypatch, lambda request: reply)
    with pytest.raises(ValueError):
        await node({"operation": "list_clients"}).execute({})


@pytest.mark.asyncio
async def test_rejected_token_and_error_redaction(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(401, json={"error": "Rejected " + TOKEN}))
    result = await node({"operation": "list_clients"}).execute({})
    assert result == {"status": "error", "http_status": 401, "error": "Rejected [redacted]"}
    transport(monkeypatch, {"clients": [{"id": "one", "internal_notes": TOKEN}]})
    assert TOKEN not in str(await node({"operation": "list_clients"}).execute({}))


@pytest.mark.asyncio
async def test_refresh_hook_uses_shared_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    calls = []
    async def freshen(data, **kwargs):
        calls.append(kwargs)
        return {**data, "access_token": "new-synthetic-token"}
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", freshen)
    result = await native.EstimateRocketNode.freshen_credential(
        {"access_token": TOKEN, "refresh_token": "synthetic-refresh"}, user_id="user", credential_id="credential")
    assert result["access_token"] == "new-synthetic-token"
    assert calls[0]["provider"] == "estimaterocket"
    assert calls[0]["credential_id"] == "credential"


@pytest.mark.parametrize("changes", [
    {"credential_type": "foreign_oauth"}, {"access_token": "Bearer two words"},
    {"access_token": "secret\r\nInjected: bad"},
])
def test_foreign_or_header_injection_credentials_refused(changes):
    with pytest.raises(ValidationError):
        native.EstimateRocketOAuthCredential.model_validate({"access_token": TOKEN, **changes})
