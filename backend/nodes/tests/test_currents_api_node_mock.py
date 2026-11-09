"""Provider-authored examples and exact native request regressions; no live keys."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import currents_api_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-currents-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/currents-api/documented.json").read_text())["responses"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, creds=None):
    return NodeFactory.create_node(node_id="currents-test", node_type="automation-currents-api", node_data={
        "config": config, "credentials": creds or {"credential_type": "currents_api_key", "api_key": TOKEN}})


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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", native.ROUTES.items())
async def test_all_documented_responses_and_exact_routes(monkeypatch, operation, route):
    requests = transport(monkeypatch, EXAMPLES[route])
    result = await node({"operation": operation}).execute({})
    assert result["status"] == "success"
    assert {k: v for k, v in result.items() if k not in {"status", "success"}} == {k: v for k, v in EXAMPLES[route].items() if k != "status"}
    req = requests[0]
    assert len(requests) == 1 and req.method == "GET"
    assert req.url.host == "api.currentsapi.services" and req.url.path == "/v1" + route
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert "apiKey" not in req.url.params and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_search_filters_unicode_booleans_dates_and_manual_pagination(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["/search"])
    config = {"operation": "search_news", "keywords": "Beyoncé + climate", "query": '"AI" AND NOT "Ethics"',
              "start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-08T00:00:00Z", "page_number": 2,
              "page_size": 5, "country": "US", "category": "technology", "language": "en", "limit": 3,
              "domain": "reuters.com", "domain_not": "example.com", "author": "*newsroom*", "type": 1,
              "has_image": True, "has_description": False}
    await node(config).execute({})
    expected = {k: str(v) for k, v in config.items() if k not in {"operation", "has_description"}}
    expected["has_image"] = "true"
    assert dict(requests[0].url.params) == expected
    assert len(requests) == 1


@pytest.mark.parametrize("field,value", [("keywords", "technology"), ("query", "AI"), ("start_date", "2026-09-01T00:00:00Z"), ("limit", 5), ("has_image", True), ("cursor", "token")])
def test_latest_rejects_search_only_parameters(field, value):
    with pytest.raises(ValidationError):
        native.GetLatestNews.model_validate({field: value})


@pytest.mark.parametrize("field,value", [("page_number", 0), ("page_number", 181), ("page_size", 301), ("page_size", 0), ("type", 4)])
def test_provider_query_bounds(field, value):
    with pytest.raises(ValidationError):
        native.SearchNews.model_validate({field: value})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"msg": "Invalid token"}), (429, {"msg": "Daily quota exceeded"}), (200, {"status": "error", "msg": "Invalid parameters"})])
async def test_provider_errors_fail_closed_and_redact_secrets(monkeypatch, status, body):
    transport(monkeypatch, lambda req: httpx.Response(status, json=body, headers={"Retry-After": "60"}))
    result = await node({"operation": "get_latest_news"}).execute({})
    assert result["status"] == "error" and result["message"] == body["msg"]
    assert result["http_status"] == status and "news" not in result
    if status == 429:
        assert result["retry_after"] == "60"
    transport(monkeypatch, lambda req: httpx.Response(401, json={"msg": "Rejected " + TOKEN}))
    assert TOKEN not in str(await node({"operation": "get_latest_news"}).execute({}))


@pytest.mark.asyncio
async def test_empty_news_still_proves_reachability_and_nullable_metadata_survives(monkeypatch):
    transport(monkeypatch, {"status": "ok", "news": [], "page": 1})
    assert (await node({"operation": "get_latest_news"}).execute({}))["news"] == []
    body = {"status": "ok", "news": [{"author": None, "image": None}], "page": 1}
    transport(monkeypatch, body)
    assert (await node({"operation": "search_news"}).execute({}))["news"] == body["news"]
    assert native.CurrentsApiNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"status": "ok"}, {"status": "ok", "news": {}, "page": 1}, {"status": "ok", "news": [], "page": "1"}])
async def test_malformed_success_is_not_a_success(monkeypatch, body):
    transport(monkeypatch, body)
    try:
        result = await node({"operation": "get_latest_news"}).execute({})
    except ValueError:
        return
    assert result["status"] == "error"


def test_manual_credential_has_default_type_and_one_user_field():
    cred = native.CurrentsApiKeyCredential(api_key="  " + TOKEN + "  ")
    assert cred.credential_type == "currents_api_key" and cred.api_key == TOKEN
    assert {name for name, field in native.CurrentsApiKeyCredential.model_fields.items() if field.is_required()} == {"api_key"}


@pytest.mark.parametrize("key", ["https://example.com/key", "Bearer secret", "line\nbreak", "<token>"])
def test_invalid_pasted_credentials(key):
    with pytest.raises(ValidationError):
        native.CurrentsApiKeyCredential(api_key=key)


@pytest.mark.parametrize("value", ["2026-09-01", "2026-09-01T00:00:00", "2026-02-30T00:00:00Z"])
def test_dates_require_real_rfc3339_timestamps(value):
    with pytest.raises(ValidationError):
        native.SearchNews(start_date=value)
