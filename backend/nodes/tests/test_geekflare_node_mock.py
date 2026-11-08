"""Geekflare fixed-route, auth, response and failure regression tests."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import geekflare_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-geekflare-token-42"


def node(config):
    return NodeFactory.create_node(node_id="geekflare-test", node_type="automation-geekflare",
        node_data={"config": config, "credentials": {"api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.ROUTES))
async def test_each_operation_one_fixed_request_auth_and_wire_fields(monkeypatch, operation):
    method, route = native.ROUTES[operation]
    config = {"operation": operation}
    if operation in {"get_discovery", "get_crawl", "cancel_crawl"}:
        config["id"] = "owned-job-123"
    elif operation == "search_web":
        config["query"] = "best running shoes"
    elif operation != "list_crawls":
        config["url"] = "https://example.com"
    body = {"apiStatus": "success", "apiCode": 200, "data": {"ok": True}}
    if operation == "list_crawls":
        body = {"items": [], "pagination": {"offset": 0, "limit": 20, "total": 0}}
    elif operation in {"start_crawl", "get_crawl", "cancel_crawl", "start_discovery", "get_discovery"}:
        body = {"id": "owned-job-123", "status": "queued"}
    requests = transport(monkeypatch, body, 202 if operation.startswith("start_") else 200)
    actual = await node(config).execute({})
    assert actual == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "api.geekflare.com"
    assert request.url.path == route.replace("{id}", "owned-job-123")
    assert request.headers["x-api-key"] == TOKEN
    assert "authorization" not in request.headers and "cookie" not in request.headers
    if method == "GET":
        assert not request.content
        if operation == "list_crawls":
            assert dict(request.url.params) == {"offset": "0", "limit": "20"}
    elif operation == "cancel_crawl":
        assert not request.content
    else:
        wire = json.loads(request.content)
        assert "operation" not in wire and "id" not in wire
        assert wire.get("url", wire.get("query")) == config.get("url", config.get("query"))
    assert TOKEN not in str(actual)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_rejection_redacted_no_retry_or_redirect(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as err:
        await node({"operation": "list_crawls"}).execute({})
    assert TOKEN not in str(err.value) and str(status) in str(err.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"apiStatus": "failure", "message": "invalid key"}, {"items": []}])
async def test_malformed_and_error_envelopes_fail_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_crawls"}).execute({})


@pytest.mark.asyncio
async def test_job_scope_secret_redaction_partial_states_and_pagination(monkeypatch):
    body = {"id": "job-123", "status": "running", "discoveryPartial": True,
        "pagination": {"offset": 20, "limit": 20, "total": 55}, "webhookSecret": "hidden",
        "pages": [{"content": TOKEN}]}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "get_crawl", "id": "job-123", "offset": 20}).execute({})
    assert result["status"] == "running" and result["discoveryPartial"]
    assert result["pagination"] == body["pagination"]
    assert "webhookSecret" not in result and TOKEN not in str(result)
    assert requests[0].url.params["offset"] == "20"
    with pytest.raises(ValueError, match="different job"):
        await node({"operation": "get_crawl", "id": "other-job"}).execute({})


@pytest.mark.asyncio
async def test_provider_authored_dns_example(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/geekflare/dns_response.json").read_text())
    transport(monkeypatch, fixture)
    assert await node({"operation": "lookup_dns", "url": "https://example.com", "types": ["A", "MX"]}).execute({}) == fixture


@pytest.mark.parametrize("config", [
    {"operation": "get_crawl", "id": "../other"},
    {"operation": "get_crawl", "id": "job?x=y"},
    {"operation": "lookup_dns", "url": "file:///tmp/private"},
    {"operation": "lookup_dns", "url": "https://user:pass@example.com"},
    {"operation": "list_crawls", "limit": 0},
    {"operation": "start_crawl", "url": "https://example.com", "maxPages": 501},
    {"operation": "lookup_dns", "url": "https://example.com", "types": ["INVALID"]},
    {"operation": "search_web", "query": "x", "endpoint": "https://evil.test"},
])
def test_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        node(config)


def test_hand_entry_default_type_and_password_schema():
    credential = native.GeekflareAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "geekflare_api_key"
    assert TOKEN not in repr(credential)
    schema = native.GeekflareAPIKeyCredential.model_json_schema()
    assert schema["properties"]["api_key"]["ui:widget"] == "password"
    for bad in ["https://example.com/key", "<token>", "Bearer abc", "abc\r\nx: bad"]:
        with pytest.raises((ValueError, ValidationError)):
            native.GeekflareAPIKeyCredential(api_key=bad)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,config", [
    ("search", {"operation": "search_web", "query": "best running shoes"}),
    ("loadtime", {"operation": "measure_load_time", "url": "https://example.com"}),
])
async def test_published_examples_despite_missing_pinned_response_refs(monkeypatch, name, config):
    body = json.loads((Path(__file__).parent / "fixtures/geekflare" / (name + "_response.json")).read_text())
    transport(monkeypatch, body)
    assert await node(config).execute({}) == body
