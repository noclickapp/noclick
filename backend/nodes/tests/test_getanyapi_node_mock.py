"""Fixed-route transport checks, provider example inputs and wallet evidence."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import getanyapi_node as api
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "getanyapi_api_key", "api_key": "fixture-anyapi-key"}
USER = "00000000-0000-4000-8000-000000000001"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/getanyapi/inputs.json").read_text())
READS = {
    "browse_catalog": ({"category": "search"}, "/catalog"),
    "search_catalog": ({"q": "web scraping", "limit": 3}, "/catalog/search"),
    "list_apis": ({}, "/v1/apis"),
    "get_api": ({"sku": "web.scrape"}, "/v1/apis/web.scrape"),
    "get_balance": ({}, "/v1/balance"),
    "get_request": ({"id": USER}, "/v1/requests/" + USER),
    "get_result": ({"id": "result-1"}, "/v1/results/result-1"),
}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    async def send(request):
        calls.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)
    native = httpx.AsyncClient
    monkeypatch.setattr(api.httpx, "AsyncClient", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies

async def run(operation, config=None):
    return await run_node_operation(node_type="automation-getanyapi", operation=operation,
        arguments=config or {}, credential_data=AUTH, user_id=USER)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(EXAMPLES) + list(READS))
async def test_fixed_operation_routes_and_inputs(operation, transport):
    calls, replies = transport
    payload = {"usd": 0} if operation == "get_balance" else {"output": {"found": True, "data": []}, "provider": "AnyAPI", "costUsd": 0.01, "items": 0, "replayed": False}
    replies.append((200, payload))
    if operation in READS:
        config, path = READS[operation]
        method, expected_body = "GET", None
    else:
        config = {k: v for k, v in EXAMPLES[operation]["config"].items() if k != "operation"}
        path = "/v1/run/" + operation.replace("_", ".", 1)
        expected_body = {"person": config} if operation == "email_find" else config
        method = "POST"
    result = await run(operation, config)
    assert result["status"] == "success" and result["data"] == payload
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.getanyapi.com"
    assert request.headers["authorization"] == "Bearer " + AUTH["api_key"]
    assert AUTH["api_key"] not in str(request.url)
    if expected_body is not None:
        assert json.loads(request.content) == expected_body
    else:
        assert dict(request.url.params) == {k: str(v) for k, v in config.items() if k not in {"sku", "id"}}

@pytest.mark.asyncio
async def test_paid_run_query_header_and_zero_false_values(transport):
    calls, replies = transport
    replies.append((200, {"output": {"found": False, "reason": "not_found"}}))
    await run("web_scrape", {"url": "https://example.com", "waitFor": 0, "onlyMainContent": False,
        "max_items": 0, "summary": False, "fields": "title", "max_cost_usd": "0.05", "idempotency_key": "one-request"})
    request = calls[0]
    assert dict(request.url.params) == {"max_items": "0", "summary": "false", "fields": "title", "max_cost_usd": "0.05"}
    assert request.headers["idempotency-key"] == "one-request"
    assert json.loads(request.content) == {"url": "https://example.com", "waitFor": 0, "onlyMainContent": False}

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 409, 429, 500])
async def test_provider_rejection_is_failure_without_retry(status, transport):
    calls, replies = transport
    replies.append((status, {"error": "Provider rejection: " + AUTH["api_key"]}))
    result = await run("get_balance")
    assert result["status"] == "error" and result["http_status"] == status
    assert "Provider rejection" in str(result) and AUTH["api_key"] not in str(result)
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_wallet_balance_evidence_accepts_empty_wallet(transport):
    _, replies = transport
    replies.append((200, {"usd": 0}))
    result = await run("get_balance")
    assert result["items"] == [{"name": "USD wallet balance: 0"}]
    assert api.GetanyapiNode.connection_evidence.proves == "account"

@pytest.mark.asyncio
async def test_redirect_is_not_success(transport):
    calls, replies = transport
    replies.append((302, {"error": "redirect"}))
    assert (await run("get_balance"))["status"] == "error"
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_invalid_wallet_response_is_not_evidence(transport):
    _, replies = transport
    replies.append((200, {}))
    with pytest.raises(ValueError, match="no USD balance"):
        await run("get_balance")

def test_manual_credential_has_default_tag_and_cleans_key():
    assert api.GetanyapiApiKeyCredential(api_key="  fixture-anyapi-key  ").model_dump() == AUTH

@pytest.mark.parametrize("key", ["https://example.com/key", "Bearer key", "bad\nkey"])
def test_invalid_credential_shape(key):
    with pytest.raises(ValidationError):
        api.GetanyapiApiKeyCredential(api_key=key)

@pytest.mark.parametrize("config", [
    {"operation": "search_catalog"}, {"operation": "youtube_video_transcript"},
    {"operation": "bing_search", "query": "hello", "limit": 11},
    {"operation": "web_scrape", "url": "https://example.com", "idempotency_key": "bad\r\nheader"},
])
def test_contract_rejects_invalid_inputs(config):
    assert not api.GetanyapiNode.validate_config({"config": config, "credentials": AUTH})["valid"]
