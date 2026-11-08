"""Contract-derived request cases and native operation execution, without live keys."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl

import httpx
import pytest
from pydantic import ValidationError

from nodes import explorium_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/explorium/requests.json").read_text())
AUTH = {"credential_type": "explorium_api_key", "api_key": "synthetic-explorium-key-12345"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.explorium.ai"
        assert request.headers["api_key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, body = replies.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-explorium", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_explorium_request_contract(transport, operation):
    requests, replies = transport
    case = CASES[operation]
    body = {"response_context": {"request_id": "unit-test"}, "data": [{"name": "Acme"}]}
    replies.append((201 if operation == "create_webhook" else 200, body))
    result = await run(operation, case["config"])
    assert result == {"status": "success", "success": True, "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    assert dict(request.url.params) == dict(parse_qsl(case["query"]))
    if case["body"] is not None:
        assert json.loads(request.content) == case["body"]
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_explorium_explicit_search_pagination(transport):
    requests, replies = transport
    replies.append((200, {"data": [], "total_pages": 3, "page": 2}))
    await run("fetch_businesses", {"page": 2, "page_size": 50, "filters": {"country_code": {"values": ["us"]}}})
    assert json.loads(requests[0].content) == {"mode": "full", "page_size": 50, "page": 2, "filters": {"country_code": {"values": ["us"]}}}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,ids", [
    ("enrich_firmographics", "business_ids", ["a" * 32, "b" * 32]),
    ("enrich_prospect_contacts", "prospect_ids", ["a" * 40, "b" * 40]),
])
async def test_explorium_v2_batch_enrichment(transport, operation, field, ids):
    requests, replies = transport
    replies.append((200, {"data": [], "response_context": {}}))
    await run(operation, {field: ids})
    assert len(requests) == 1
    assert requests[0].url.path.startswith("/v2/")
    assert json.loads(requests[0].content) == {field: ids}


@pytest.mark.asyncio
async def test_explorium_cursor_is_explicit(transport):
    requests, replies = transport
    body = {"data": [], "page": {"next_cursor": "next-page"}}
    replies.append((200, body))
    result = await run("fetch_prospects", {"next_cursor": "previous-page"})
    assert result["data"] == body
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"mode": "full", "page_size": 25, "next_cursor": "previous-page"}


@pytest.mark.asyncio
async def test_explorium_connection_read_needs_only_pasted_key(transport):
    requests, replies = transport
    body = {"allocated_credits": 1000, "remaining_credits": 42, "response_context": {}}
    replies.append((200, body))
    result = await run(node.ExploriumNode.connection_evidence.operation)
    assert result["data"] == body
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v2/credits"
    assert node.ExploriumAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == AUTH["credential_type"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 500])
async def test_explorium_error_redaction(transport, status):
    _, replies = transport
    replies.append((status, {"detail": "Rejected " + AUTH["api_key"]}))
    result = await run("get_credits")
    assert result["success"] is False
    assert result["http_status"] == status
    assert result["error"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not json", [], "unexpected", b"x" * (8 * 1024 * 1024 + 1)])
async def test_explorium_invalid_responses(transport, body):
    _, replies = transport
    replies.append((200, body))
    with pytest.raises(ValueError, match="Explorium"):
        await run("get_credits")


@pytest.mark.parametrize("model,config", [
    (node.Firmographics, {"business_ids": "wrong"}),
    (node.Firmographics, {"business_ids": ["a" * 32] * 51}),
    (node.Firmographics, {"business_id": "a" * 32}),
    (node.ProspectProfile, {"prospect_ids": "a" * 32}),
    (node.GetWebhook, {"webhook_id": "../escape"}),
    (node.CancelJob, {"job_id": "x?admin=true"}),
    (node.FetchBusinesses, {"page_size": 501}),
    (node.FetchBusinesses, {"size": 3}),
    (node.ListJobs, {"skip": -1}),
    (node.MatchBusinesses, {"businesses_to_match": [{}]}),
    (node.MatchProspects, {"prospects_to_match": [{}]}),
])
def test_explorium_invalid_input(model, config):
    with pytest.raises(ValidationError):
        model.model_validate(config)


@pytest.mark.parametrize("key", ["https://example.com/key", "<token>", "a\nb", "Bearer token"])
def test_explorium_credential_validation(key):
    with pytest.raises(ValueError):
        node.ExploriumAPIKeyCredential(api_key=key)
