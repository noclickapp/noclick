"""Offline request and failure regressions for The Companies API v2.

Synthetic fixtures exercise every operation through the platform factory; no
account, token or real API call is required.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import thecompaniesapi_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-thecompaniesapi-token-123"
AUTH = {"credential_type": native.CREDENTIAL_TYPE, "api_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/thecompaniesapi/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None):
    return NodeFactory.create_node(node_id="thecompaniesapi-test", node_type=native.ThecompaniesapiNode.integration_type,
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": AUTH})


def transport(monkeypatch, *, body=None, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body,response", CASES, ids=[c[0] for c in CASES])
async def test_each_operation_sends_one_documented_request(monkeypatch, operation, config, method, path, query, body, response):
    requests = transport(monkeypatch, body=response)
    result = await node(operation, config).execute({})
    assert result == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.scheme == "https" and request.url.host == "api.thecompaniesapi.com"
    assert request.headers["authorization"] == "Basic " + TOKEN
    actual = {key: request.url.params.get_list(key) if isinstance(value, list) else request.url.params[key]
              for key, value in query.items()}
    assert actual == query and set(request.url.params) == set(query)
    assert (json.loads(request.content) if request.content else None) == body
    assert TOKEN not in str(request.url) and TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_failures_never_follow_or_retry_writes(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={"messages": "refused " + TOKEN},
        headers={"location": "https://foreign.test/"})
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await node("create_list", {"name": "Prospects"}).execute({})
    assert len(requests) == 1 and TOKEN not in str(exc.value)
    assert "refused" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "bad"}, {"errors": []}, {"status": 401, "messages": "refused"}, "not an object"])
async def test_error_envelopes_and_wrong_shapes_fail(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node("get_user").execute({})


@pytest.mark.asyncio
async def test_non_json_does_not_connect(monkeypatch):
    transport(monkeypatch, body={"id": 1}, headers={"content-type": "text/html"})
    with pytest.raises(ValueError, match="JSON"):
        await node("get_user").execute({})


@pytest.mark.parametrize("operation,config", [
    ("get_company", {"domain": ".."}), ("get_company", {"domain": "https://apple.com/x"}),
    ("delete_list", {"list_id": 0}), ("get_company_in_list", {"domain": "apple.com"}),
    ("toggle_companies_in_list", {"list_id": 1, "action": "attach", "domains": []}),
    ("toggle_companies_in_list", {"list_id": 1, "action": "toggle", "domains": ["apple.com"]}),
    ("search_companies_by_name", {"name": "Apple", "size": 26}),
    ("search_companies", {"query": [{"attribute": "unknown", "operator": "and", "sign": "equals", "values": []}]}),
    ("get_user", {"api_url": "https://foreign.test"}),
])
def test_invalid_inputs_are_rejected(operation, config):
    with pytest.raises((ValueError, ValidationError)):
        native.ThecompaniesapiNode.parse_config({"config": {"operation": operation, **config}, "credentials": AUTH})


def test_manual_token_default_and_evidence():
    credential = native.ThecompaniesapiCredential(api_token=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    assert not native.ThecompaniesapiCredential.model_fields["credential_type"].is_required()
    evidence = native.ThecompaniesapiNode.connection_evidence
    assert evidence.operation == "list_lists" and evidence.identity_operation == "get_user"
    assert native.ROUTES[evidence.operation][0] == native.ROUTES[evidence.identity_operation][0] == "GET"


@pytest.mark.parametrize("value", ["Basic token", "Bearer token", "line\nfeed", "https://example.test/token", "<token>"])
def test_bad_token_shapes_refused(value):
    with pytest.raises(ValueError):
        native.ThecompaniesapiCredential(api_token=value)
