"""Native node requests and parsing against provider-published examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import scrapecreators_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import credential_classes_for_node
from nodes.core.registry import NodeFactory
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/scrapecreators/contract_examples.json").read_text())["operations"]
TOKEN = "fixture-scrapecreators-key-123456"
AUTH = {"credential_type": "scrapecreators_api_key", "api_key": TOKEN}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    def send(request):
        requests.append(request)
        assert request.url.host == "api.scrapecreators.com"
        assert request.headers["x-api-key"] == TOKEN
        assert TOKEN not in str(request.url)
        return responses.pop(0)
    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: guarded(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


def node(config):
    return NodeFactory.create_node(node_id="scrapecreators-test", node_type="automation-scrapecreators", node_data={"config": config, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_published_examples_exact_route_query_auth_and_response(transport, operation):
    requests, responses = transport
    case = CASES[operation]
    responses.append(httpx.Response(200, json=case["body"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == case["body"]
    if operation == "get_credit_balance":
        assert result["items"] == [{"name": "333 API credits"}]
    assert len(requests) == 1 and requests[0].method == "GET" and requests[0].url.path == case["path"]
    expected = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in case["config"].items() if k != "operation"}
    assert dict(requests[0].url.params) == expected


@pytest.mark.asyncio
async def test_cursors_query_encoding_and_false_preserved_in_one_page(transport):
    requests, responses = transport
    body = {"success": True, "videos": [], "continuationToken": "next+/=&"}
    responses.append(httpx.Response(200, json=body))
    result = await node({"operation": "search_youtube", "query": "café + music & news", "continuationToken": "cursor+/=&", "includeExtras": False}).execute({})
    assert result["data"] == body and len(requests) == 1
    assert dict(requests[0].url.params) == {"query": "café + music & news", "continuationToken": "cursor+/=&", "includeExtras": "false"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_http_failures_are_not_success_and_redact_key(transport, status):
    requests, responses = transport
    responses.append(httpx.Response(status, json={"message": "Invalid API key: " + TOKEN}, headers={"Location": "https://elsewhere.test"}))
    result = await node({"operation": "get_credit_balance"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Invalid API key:" in result["error"] and TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_key_redaction_precedes_error_message_truncation(transport):
    _, responses = transport
    responses.append(httpx.Response(401, json={"message": "x" * 1990 + TOKEN}))
    result = await node({"operation": "get_credit_balance"}).execute({})
    assert result["status"] == "error" and TOKEN[:10] not in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"success": False, "message": "No credits"}, {"error": "Refused"}, {}, {"creditCount": "333"}, {"creditCount": True}, [333]])
async def test_error_envelopes_and_invalid_balance_are_not_connection_proof(transport, body):
    _, responses = transport
    responses.append(httpx.Response(200, json=body))
    assert (await node({"operation": "get_credit_balance"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_non_json_is_error(transport):
    _, responses = transport
    responses.append(httpx.Response(200, text="<html>upstream failure</html>"))
    assert (await node({"operation": "get_credit_balance"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_manual_credential_default_and_account_evidence(transport):
    requests, responses = transport
    assert native.ScrapecreatorsAPIKeyCredential in credential_classes_for_node(native.ScrapecreatorsNode)
    credential = native.ScrapecreatorsAPIKeyCredential(api_key=" " + TOKEN + " ")
    assert credential.credential_type == "scrapecreators_api_key" and credential.api_key == TOKEN
    responses.append(httpx.Response(200, json={"success": True, "creditCount": 0}))
    evidence = await collect_evidence(node_type="automation-scrapecreators", credential_data=credential.model_dump(), user_id="00000000-0000-4000-8000-000000000001")
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ["0 API credits"]
    assert len(requests) == 1 and requests[0].url.path == "/v1/account/credit-balance"


@pytest.mark.parametrize("config", [
    {"operation": "get_tiktok_profile"}, {"operation": "get_youtube_channel"},
    {"operation": "get_youtube_videos"}, {"operation": "get_instagram_post"},
    {"operation": "search_twitter_posts"}, {"operation": "get_tiktok_videos", "handle": "creator", "sort_by": "invalid"},
    {"operation": "get_credit_balance", "url": "https://evil.test"}, {"operation": "create_post"},
])
def test_invalid_configs_are_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("key", ["https://example.test/key", "<token>", "key\r\nx-api-key: injected", "key with space"])
def test_bad_keys_are_rejected(key):
    with pytest.raises(ValidationError):
        native.ScrapecreatorsAPIKeyCredential(api_key=key)
