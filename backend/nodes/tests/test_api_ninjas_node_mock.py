"""Exercise the native node with provider-documented examples and captured HTTP."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import api_ninjas_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/api-ninjas/documented.json").read_text())
AUTH = {"credential_type": "api_ninjas_api_key", "api_key": "synthetic-ninjas-key-12345"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.api-ninjas.com"
        assert request.headers["X-Api-Key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, body, *headers = replies.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers=headers[0] if headers else {})
        return httpx.Response(status, json=body, headers=headers[0] if headers else {})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credential=AUTH):
    return await run_node_operation(node_type="automation-api-ninjas", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(credential), user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_api_ninjas_documented_requests_and_responses(transport, operation):
    requests, replies = transport
    case = CASES[operation]
    replies.append((200, case["body"]))
    result = await run(operation, case["config"])
    assert result["status"] == "success"
    assert result["data"] == case["body"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    if request.method == "POST":
        assert json.loads(request.content) == case["config"]
        assert not request.url.query
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert dict(request.url.params) == {k: str(v) for k, v in case["config"].items()}
        assert not request.content


@pytest.mark.asyncio
async def test_api_ninjas_optional_query_parameters(transport):
    requests, replies = transport
    replies.append((200, CASES["generate_password"]["body"]))
    await run("generate_password", {"length": 16, "exclude_numbers": True, "exclude_special_chars": False})
    assert dict(requests[0].url.params) == {"length": "16", "exclude_numbers": "true", "exclude_special_chars": "false"}
    replies.append((200, CASES["validate_phone"]["body"]))
    await run("validate_phone", {"number": "2065550100", "country": "US"})
    assert dict(requests[1].url.params) == {"number": "2065550100", "country": "US"}
    replies.append((200, CASES["geocode"]["body"]))
    await run("geocode", {"city": "Seattle", "state": "WA", "country": "US", "zipcode": "98101"})
    assert dict(requests[2].url.params) == {"city": "Seattle", "state": "WA", "country": "US", "zipcode": "98101"}


@pytest.mark.asyncio
async def test_api_ninjas_connection_probe_uses_default_timezone(transport):
    requests, replies = transport
    replies.append((200, CASES["get_world_time"]["body"]))
    await run("get_world_time")
    assert dict(requests[0].url.params) == {"timezone": "Europe/London"}
    assert node.ApiNinjasNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 429, 500])
async def test_api_ninjas_provider_errors_and_key_redaction(transport, status):
    requests, replies = transport
    replies.append((status, {"error": "Invalid API Key: " + AUTH["api_key"]}))
    result = await run("get_world_time")
    assert result["success"] is False
    assert result["http_status"] == status
    assert result["error"] == "Invalid API Key: [redacted]"
    assert AUTH["api_key"] not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"<html>error</html>", None, [], "not an object"])
async def test_api_ninjas_invalid_response_fails(transport, body):
    _, replies = transport
    replies.append((200, body))
    with pytest.raises(ValueError, match="API Ninjas"):
        await run("get_world_time")


@pytest.mark.asyncio
async def test_api_ninjas_redirect_is_not_followed(transport):
    requests, replies = transport
    replies.append((302, {"error": "Redirect refused"}, {"Location": "https://other.example/steal"}))
    result = await run("get_world_time")
    assert result["success"] is False
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_api_ninjas_response_size_is_bounded(transport):
    _, replies = transport
    replies.append((200, b" " * (2 * 1024 * 1024 + 1)))
    with pytest.raises(ValueError, match="exceeds"):
        await run("get_world_time")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", [
    ("get_weather", {"lat": 91, "lon": 0}),
    ("reverse_geocode", {"lat": 0, "lon": -181}),
    ("convert_currency", {"have": "GBP", "want": "AUD"}),
    ("analyze_sentiment", {"text": "x" * 2001}),
    ("detect_language", {"text": "x" * 1001}),
    ("compare_text", {"text_1": "hello", "text_2": "x" * 5001}),
    ("get_stock_price", {"ticker": ""}),
    ("get_world_time", {"url": "https://other.example"}),
])
async def test_api_ninjas_invalid_input_never_sends(transport, operation, config):
    requests, _ = transport
    with pytest.raises(ValueError):
        await run(operation, config)
    assert not requests


@pytest.mark.parametrize("key", ["", "<token>", "https://api-ninjas.com/profile", "key\r\nInjected: bad", "key with spaces", "nonasciié"])
def test_api_ninjas_bad_keys_rejected(key):
    with pytest.raises(ValueError):
        node.ApiNinjasApiKeyCredential(api_key=key)


def test_api_ninjas_pasted_key_and_schema():
    credential = node.ApiNinjasApiKeyCredential(api_key="  clean-key-123\n")
    assert credential.api_key == "clean-key-123"
    assert "clean-key-123" not in repr(credential)
    schema = node.ApiNinjasNode.get_config_schema()
    assert schema["$defs"]["ApiNinjasApiKeyCredential"]["title"] == "API Ninjas API Key"
