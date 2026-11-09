"""Exercise the native factory against the six published Shorten.REST routes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import shorten_rest_node as native
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="shorten-rest-test", node_type="automation-shorten-rest",
        node_data={"config": config, "credentials": {"api_key": "synthetic-shorten-rest-key"}})


@pytest.fixture
def intercept(monkeypatch):
    requests = []
    responses = json.loads((Path(__file__).parent / "fixtures/shorten-rest/responses.json").read_text())

    def respond(request):
        requests.append(request)
        assert request.headers["x-api-key"] == "synthetic-shorten-rest-key"
        assert request.url.host == "api.shorten.rest"
        if request.method in {"PUT", "DELETE"}:
            return httpx.Response(200, content=b"")
        return httpx.Response(200, json=responses[request.method + " " + request.url.path])

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", [
    ({"operation": "list_aliases", "continue_from": "1588788835614657618", "limit": 10}, "GET", "/aliases/all", {"domainName": "short.fyi", "continueFrom": "1588788835614657618", "limit": "10"}, None),
    ({"operation": "list_clicks", "limit": 1}, "GET", "/clicks", {"limit": "1"}, None),
    ({"operation": "get_alias", "alias_name": "aBcDe012"}, "GET", "/aliases", {"domainName": "short.fyi", "aliasName": "aBcDe012"}, None),
    ({"operation": "delete_alias", "alias_name": "aBcDe012"}, "DELETE", "/aliases", {"domainName": "short.fyi", "aliasName": "aBcDe012"}, None),
    ({"operation": "shorten_url", "url": "https://example.com"}, "POST", "/aliases", {"domainName": "short.fyi"}, {"destinations": [{"url": "https://example.com"}]}),
    ({"operation": "create_alias", "domain_name": "your.domain.com", "alias_name": "a+b/c", "destinations": [{"url": "https://example.com", "country": "US", "os": "iOS"}]}, "POST", "/aliases", {"domainName": "your.domain.com", "aliasName": "a+b/c"}, {"destinations": [{"url": "https://example.com", "country": "US", "os": "iOS"}]}),
    ({"operation": "update_alias", "alias_name": "aBcDe012", "metatags": []}, "PUT", "/aliases", {"domainName": "short.fyi", "aliasName": "aBcDe012"}, {"metatags": []}),
    ({"operation": "set_destinations", "alias_name": "aBcDe012", "destinations": [{"url": "https://example.com"}]}, "PUT", "/aliases", {"domainName": "short.fyi", "aliasName": "aBcDe012"}, {"destinations": [{"url": "https://example.com"}]}),
    ({"operation": "set_metatags", "alias_name": "aBcDe012", "metatags": [{"name": "og:title", "content": "Example"}]}, "PUT", "/aliases", {"domainName": "short.fyi", "aliasName": "aBcDe012"}, {"metatags": [{"name": "og:title", "content": "Example"}]}),
    ({"operation": "set_snippets", "alias_name": "aBcDe012", "snippets": [{"id": "fixture-pixel", "parameters": {"id": "123"}}]}, "PUT", "/aliases", {"domainName": "short.fyi", "aliasName": "aBcDe012"}, {"snippets": [{"id": "fixture-pixel", "parameters": {"id": "123"}}]}),
])
async def test_shorten_rest_exact_wire_contract(intercept, config, method, path, query, body):
    result = await node(config).run({})
    assert result["status"] == "success"
    assert len(intercept) == 1
    request = intercept[0]
    assert (request.method, request.url.path) == (method, path)
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    if method in {"PUT", "DELETE"}:
        assert result["acknowledged"] is True
    if config["operation"] == "list_aliases":
        assert result["data"] == ["aBcDe012"] and result["lastId"] == "1588788835614657618"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, "Invalid API key"), (429, "Rate limit exceeded"), (302, "Redirect refused")])
async def test_shorten_rest_provider_rejections(monkeypatch, status, body):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status, text=body)), **kwargs))
    result = await node({"operation": "list_aliases"}).execute({})
    assert result == {"status": "error", "status_code": status, "error": body}


@pytest.mark.asyncio
async def test_shorten_rest_null_alias_and_malformed_list(monkeypatch):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="null")), **kwargs))
    assert (await node({"operation": "get_alias", "alias_name": "missing"}).execute({}))["data"] is None
    with pytest.raises(ValueError, match="aliases array"):
        await node({"operation": "list_aliases"}).execute({})


def test_shorten_rest_manual_key_defaults_and_input_validation():
    assert native.ShortenRestAPIKeyCredential(api_key="valid-fixture-key").credential_type == "shorten_rest_api_key"
    for value in ["", "https://example.com", "invalid\nheader"]:
        with pytest.raises((ValidationError, ValueError)):
            native.ShortenRestAPIKeyCredential(api_key=value)
    for config in [
        {"operation": "list_clicks", "limit": 1001},
        {"operation": "get_alias"},
        {"operation": "update_alias", "alias_name": "aBcDe012"},
        {"operation": "create_alias", "destinations": [{"country": "US"}]},
    ]:
        with pytest.raises((ValidationError, ValueError)):
            node(config)
