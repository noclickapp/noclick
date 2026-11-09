"""Factory-level Community API regressions; all credentials and responses are synthetic."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import gainsight_customer_communities_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-gainsight-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/gainsight-customer-communities/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(node_id="gainsight-contract", node_type=native.GainsightCustomerCommunitiesNode.integration_type,
        node_data={"config": config, "credentials": {"credential_type": "gainsight_customer_communities_token", "access_token": TOKEN, **credentials}})


def mock_http(monkeypatch, handler):
    requests = []
    actual_client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return actual_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_gainsight_customer_communities_exact_resource_contract(monkeypatch, case):
    def response(request):
        assert request.method == case["method"]
        assert request.url.host == "api2-eu-west-1.insided.com"
        assert request.url.path == case["path"]
        assert dict(request.url.params) == case["query"]
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert (json.loads(request.content) if request.content else None) == case["body"]
        return httpx.Response(case["status"], json=case["response"]) if case["response"] is not None else httpx.Response(case["status"])
    requests = mock_http(monkeypatch, response)
    result = await node(case["config"]).execute({})
    assert result["success"] is True and result["http_status"] == case["status"]
    assert len(requests) == 1
    if case["method"] == "POST":
        assert result["write_acknowledged"] is True and result["readback_verified"] is False
    elif "page" in case["config"]:
        assert result["data"] == case["response"]["result"]
        assert result["page"] == 2 and result["next_page"] is None
    else:
        assert result["data"] == case["response"]


@pytest.mark.asyncio
async def test_gainsight_customer_communities_full_page_requires_explicit_continuation(monkeypatch):
    requests = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"result": [{"id": "1"}, {"id": "2"}]}))
    result = await node({"operation": "list_categories", "page_size": 2}).execute({})
    assert result["next_page"] == 2 and result["has_more"] is None
    assert len(requests) == 1
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"result": []}))
    result = await node({"operation": "list_categories", "page": 2}).execute({})
    assert result["has_more"] is False and result["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 422, 429, 500])
async def test_gainsight_customer_communities_failures_do_not_follow_or_retry(monkeypatch, status):
    requests = mock_http(monkeypatch, lambda r: httpx.Response(status, json={"message": "refused " + TOKEN}, headers={"Location": "https://example.test/"}))
    result = await node({"operation": "list_categories"}).execute({})
    assert result["success"] is False and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1
    assert "refused" in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"result": "wrong"}, {"result": [None]}, {"result": [], "error": "bad"}, {"result": [], "success": False}])
async def test_gainsight_customer_communities_bad_lists_are_not_connection_proof(monkeypatch, payload):
    mock_http(monkeypatch, lambda r: httpx.Response(200, json=payload))
    assert (await node({"operation": "list_categories"}).execute({}))["success"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["start_conversation", "reply_conversation", "edit_conversation_tags"])
async def test_gainsight_customer_communities_ambiguous_writes_never_claim_success(monkeypatch, operation):
    def response(request):
        raise httpx.ReadTimeout("lost response " + TOKEN, request=request)
    requests = mock_http(monkeypatch, response)
    config = next(c["config"] for c in CASES if c["config"]["operation"] == operation)
    result = await node(config).execute({})
    assert result["success"] is False and result["status"] == "unknown"
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_gainsight_customer_communities_region_and_secret_projection(monkeypatch):
    requests = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"id": "42", "content": TOKEN, "access_token": "other-secret"}))
    result = await node({"operation": "get_conversation", "id": "42"}, api_base_url=native.HOSTS[1]).execute({})
    assert requests[0].url.host == "api2-us-west-2.insided.com"
    assert result["data"] == {"id": "42", "content": "[redacted]"}


@pytest.mark.asyncio
async def test_gainsight_customer_communities_unexpected_html_and_missing_write_ids(monkeypatch):
    mock_http(monkeypatch, lambda r: httpx.Response(200, text="<html>" + TOKEN))
    assert (await node({"operation": "list_categories"}).execute({}))["success"] is False
    mock_http(monkeypatch, lambda r: httpx.Response(201, json={}))
    config = next(c["config"] for c in CASES if c["config"]["operation"] == "start_conversation")
    result = await node(config).execute({})
    assert result["status"] == "unknown" and result["success"] is False


def test_gainsight_customer_communities_hand_connect_defaults_and_contract_inventory():
    credential = native.GainsightCustomerCommunitiesToken(access_token=TOKEN)
    assert credential.credential_type == "gainsight_customer_communities_token"
    assert set(native.ROUTES) == {c["config"]["operation"] for c in CASES}
    assert len(native.ROUTES) == 20
    for changes in [{"access_token": "Bearer " + TOKEN}, {"access_token": "https://example.test"}, {"api_base_url": "https://api2-eu-west-1.insided.com.evil.test"}, {"api_base_url": "http://api2-eu-west-1.insided.com"}]:
        with pytest.raises((ValueError, ValidationError)):
            native.GainsightCustomerCommunitiesToken.model_validate({"access_token": TOKEN, **changes})
    for config in [{"operation": "get_conversation", "id": "../42"}, {"operation": "list_categories", "page": 0}, {"operation": "list_categories", "page_size": 101}, {"operation": "reply_conversation", "id": "42", "content": "reply"}]:
        with pytest.raises(ValueError):
            native.GainsightCustomerCommunitiesNode.parse_config({"config": config, "credentials": credential.model_dump()})


@pytest.mark.asyncio
async def test_gainsight_customer_communities_plaintext_rejection_preserves_status(monkeypatch):
    mock_http(monkeypatch, lambda r: httpx.Response(401, text="Token expired: " + TOKEN))
    result = await node({"operation": "list_categories"}).execute({})
    assert result["http_status"] == 401 and result["error"] == "Token expired: [redacted]"
