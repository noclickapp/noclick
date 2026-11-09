"""Native Aviato requests with unchanged official documentation examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import aviato_node as api
from nodes.core.run_op import run_node_operation
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/aviato/documented-responses.json").read_text())
AUTH = {"credential_type": "aviato_api_key", "api_key": "aviato-synthetic-fixture-key"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "data.api.aviato.co"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, payload, *headers = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, headers=headers[0] if headers else {})
        return httpx.Response(status, json=payload, headers=headers[0] if headers else {})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(api, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-aviato", operation=operation,
        arguments=arguments or {}, credential_data=AUTH, user_id=USER)


def arguments(operation):
    if operation.startswith("bulk_"):
        lookup = {"website": "aviato.co"} if operation == "bulk_enrich_companies" else {"email": "fixture@example.test"}
        return {"lookups": json.dumps([lookup])}
    if operation.startswith("search_"):
        return {"dsl": json.dumps({"offset": 0, "limit": 25, "sort": [], "filters": [], "nameQuery": "Aviato"})}
    if operation == "generate_market_map":
        return {"company_id": "company-fixture"}
    if operation == "get_market_map":
        return {"map_id": "mapID"}
    if operation == "get_balance":
        return {}
    return {"lookup_value": "fixture-id"}


@pytest.mark.parametrize("operation,endpoint", list(api.ROUTES.items()))
@pytest.mark.asyncio
async def test_aviato_all_operations_with_provider_examples(transport, operation, endpoint):
    method, path = endpoint
    payload = EXAMPLES[method + " " + path]["body"]
    transport[1].append((200, payload))
    result = await run(operation, arguments(operation))
    assert result == {"status": "success", "data": payload}
    request, = transport[0]
    assert (request.method, request.url.path) == endpoint
    assert not transport[1]
    if method == "POST":
        body = json.loads(request.content)
        assert request.headers["Content-Type"].startswith("application/json")
        if operation.startswith("bulk_"): assert body["lookups"][0]
        if operation.startswith("search_"): assert body["dsl"]["nameQuery"] == "Aviato"
        if operation == "generate_market_map": assert body == {"id": "company-fixture"}
    elif "page" in request.url.params:
        assert request.url.params["page"] == "0" and request.url.params["perPage"] == "25"


@pytest.mark.asyncio
async def test_aviato_query_encoding_booleans_arrays_and_selectors(transport):
    transport[1].append((200, {"id": "company-id"}))
    await run("enrich_company", {"lookup_by": "website", "lookup_value": "https://example.com/a?x=1&b=2", "preview": False, "full": True, "required_fields": ["description", "industryList"]})
    query = transport[0][0].url.params
    assert query["website"] == "https://example.com/a?x=1&b=2"
    assert query["preview"] == "false" and query["full"] == "true"
    assert query.get_list("require") == ["description", "industryList"]
    assert "lookup_by" not in query and "lookup_value" not in query


@pytest.mark.asyncio
async def test_aviato_contact_filter_and_pagination(transport):
    transport[1].extend([(200, {"emails": []}), (200, {"data": [], "total": 0})])
    await run("get_person_email", {"lookup_by": "email", "lookup_value": "fixture@example.test", "email_type": "work"})
    assert transport[0][-1].url.params["type"] == "work"
    await run("get_company_employees", {"lookup_value": "company-id", "page": 3, "per_page": 100})
    assert transport[0][-1].url.params["page"] == "3"
    assert transport[0][-1].url.params["perPage"] == "100"


@pytest.mark.asyncio
async def test_aviato_bulk_partial_failures_remain_visible(transport):
    payload = [{"lookupSuccessful": False}, {"lookupSuccessful": True, "person": {"id": "found"}}]
    transport[1].append((200, payload))
    result = await run("bulk_enrich_people", {"lookups": '[{"id":"missing"},{"id":"found"}]', "preview": False, "required_fields": ["fullName"]})
    assert result["data"][0]["lookupSuccessful"] is False
    assert json.loads(transport[0][0].content) == {"lookups": [{"id": "missing"}, {"id": "found"}], "preview": False, "require": ["fullName"]}


@pytest.mark.parametrize("operation,config", [
    ("bulk_enrich_people", {"lookups": "[]"}),
    ("bulk_enrich_people", {"lookups": "[{}]"}),
    ("bulk_enrich_people", {"lookups": json.dumps([{"id": "id"}] * 21)}),
    ("bulk_enrich_companies", {"lookups": json.dumps([{"id": "id"}] * 101)}),
    ("get_company_employees", {"lookup_value": "id", "page": -1}),
    ("get_company_employees", {"lookup_value": "id", "per_page": 101}),
    ("get_person_email", {"lookup_value": "id", "email_type": "professional"}),
    ("generate_market_map", {}),
    ("get_market_map", {}),
    ("search_people", {"dsl": "not json"}),
    ("search_people", {"dsl": '{"limit":251}'}),
])
@pytest.mark.asyncio
async def test_aviato_invalid_inputs_never_send(transport, operation, config):
    with pytest.raises(ValueError):
        await run(operation, config)
    assert not transport[0]


@pytest.mark.parametrize("status,body,headers", [
    (401, {"message": "Invalid API key"}, {}),
    (429, {"message": "Rate limit exceeded"}, {"Retry-After": "60"}),
    (302, b"", {"Location": "https://elsewhere.test"}),
    (200, b"<html>login</html>", {"Content-Type": "text/html"}),
    (200, {"error": "invalid key"}, {}),
    (200, [], {}),
])
@pytest.mark.asyncio
async def test_aviato_connection_rejections_redirects_and_bad_shapes(transport, status, body, headers):
    transport[1].append((status, body, headers))
    with pytest.raises(ValueError):
        await run("get_balance")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_aviato_never_retries_market_map_creation_or_leaks_key(transport):
    transport[1].append((500, {"message": "rejected " + AUTH["api_key"]}))
    with pytest.raises(ValueError) as error:
        await run("generate_market_map", {"company_id": "id"})
    assert AUTH["api_key"] not in str(error.value)
    assert len(transport[0]) == 1


def test_aviato_manual_credential_default_and_wrong_family():
    assert api.AviatoAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "aviato_api_key"
    with pytest.raises(ValueError):
        api.AviatoAPIKeyCredential(**{**AUTH, "credential_type": "another_api_key"})
    for bad in ["Bearer key", "key\nvalue", "https://example.com/key"]:
        with pytest.raises(ValueError):
            api.AviatoAPIKeyCredential(api_key=bad)
