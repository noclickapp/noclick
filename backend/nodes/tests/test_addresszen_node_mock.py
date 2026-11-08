"""HTTP-boundary coverage for Addresszen's published v1 operation mappings."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import addresszen_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/addresszen/requests.json").read_text())
CREDENTIAL = {"credential_type": "addresszen_api_keys", "api_key": "ak_fixture", "management_key": "uk_fixture"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="addresszen-test", node_type="automation-addresszen",
        node_data={"config": config, "credentials": credentials or CREDENTIAL})


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_published_request_mapping(monkeypatch, case):
    payload = {"code": 2000, "message": "Success", "result": {"name": "My API Key"}}
    requests = transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == payload["result"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.addresszen.com"
    assert request.url.path == "/v1" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    token = "uk_fixture" if case["path"].startswith("/keys/") else "ak_fixture"
    assert request.headers["Authorization"] == "Bearer " + token
    assert "user_token" not in request.url.params and "api_key" not in request.url.params


@pytest.mark.asyncio
async def test_connection_names_the_actual_key(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"code": 2000, "message": "Success", "result": {"name": "Shipping production", "key": "ak_fixture"}}))
    result = await collect_evidence(node_type="automation-addresszen", user_id="addresszen-test", credential_data=CREDENTIAL)
    assert result.reachable is True
    assert result.account_label == "Shipping production"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 429, 500, 200])
async def test_rejection_is_verbatim_except_secrets(monkeypatch, code):
    transport(monkeypatch, httpx.Response(code, json={"code": 4010, "message": "Rejected uk_fixture ak_fixture"}))
    result = await node({"operation": "get_key_details"}).execute({})
    assert result == {"status": "error", "http_status": code, "code": 4010, "error": "Rejected [redacted] [redacted]"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"licensees": [], "hasMore": False},
    {"licensees": [{"id": "56a11209ebe230380bf104c3", "key": "sl_generated", "name": "Widgets"}], "hasMore": True},
])
async def test_one_page_preserves_pagination_and_created_keys(monkeypatch, payload):
    requests = transport(monkeypatch, httpx.Response(200, json={"code": 2000, "message": "Success", "result": payload}))
    result = await node({"operation": "list_licensees", "limit": 1}).execute({})
    assert result["data"] == payload
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_recursive_redaction(monkeypatch):
    payload = {"code": 2000, "result": {"key": "ak_fixture", "nested": ["uk_fixture"]}}
    transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node({"operation": "get_key_details"}).execute({})
    assert result["data"] == {"key": "[redacted]", "nested": ["[redacted]"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://example.com"}),
    httpx.Response(200, text="<html>wrong host</html>"),
    httpx.Response(200, headers={"content-type": "application/json"}, content=b"invalid"),
    httpx.Response(200, json=[]), httpx.Response(200, json={"code": 2000}),
])
async def test_unexpected_response_is_not_success(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "get_key_details"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_does_not_leak_url_or_repeat_write(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("https://api.addresszen.com/v1/keys/ak_fixture/configs"))
    with pytest.raises(ValueError) as caught:
        await node({"operation": "create_config", "name": "checkout", "payload": "{}"}).execute({})
    assert "ak_fixture" not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [".", "..", "id\nvalue"])
async def test_path_identifiers_cannot_escape_route(monkeypatch, identifier):
    requests = transport(monkeypatch, httpx.Response(200, json={"code": 2000, "result": {}}))
    with pytest.raises(ValueError):
        await node({"operation": "get_config", "config_name": identifier}).execute({})
    assert not requests


@pytest.mark.parametrize("config", [
    {"operation": "find_address", "query": "Main", "limit": 101},
    {"operation": "list_licensees", "limit": 0},
    {"operation": "update_key_details"},
    {"operation": "update_licensee", "licensee": "sl_fixture"},
    {"operation": "update_key_details", "redact_days": 1096},
    {"operation": "get_key_usage", "start": 20, "end": 10},
    {"operation": "create_config", "name": "a", "payload": {}},
    {"operation": "validate_phone_number", "query": "+441234", "current_carrier": "false"},
    {"operation": "get_key_details", "base_url": "https://example.com"},
])
def test_invalid_config(config):
    assert native.AddresszenNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("value", ["", "Bearer secret", "https://example.com", "<api-key>", "ab\ncd", 123])
def test_invalid_keys(value):
    with pytest.raises(ValidationError):
        native.AddresszenAPIKeysCredential(api_key=value, management_key="uk_fixture")


def test_credential_errors_hide_secrets():
    with pytest.raises(ValidationError) as caught:
        native.AddresszenFullConfig.model_validate({"config": {"operation": "get_key_details"},
            "credentials": {"api_key": "Bearer private-api-key", "management_key": "uk_fixture"}})
    assert "private-api-key" not in str(caught.value)
