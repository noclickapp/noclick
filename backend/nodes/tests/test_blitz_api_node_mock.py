"""Exercise native BlitzAPI operations with provider-authored contract examples."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import blitz_api_node as blitz
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_operation
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/blitz-api/contract_examples.json").read_text())["operations"]
AUTH = {"credential_type": "blitz_api_key", "api_key": "blitz-fixture-secret-123"}
NODE = "automation-blitz-api"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.blitz-api.ai"
        assert request.headers["x-api-key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, payload = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload, headers={"content-type": "text/html"})
        return httpx.Response(code, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(blitz, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_blitz_api_contract_examples_and_exact_wire(transport, operation):
    requests, replies = transport
    case = EXAMPLES[operation]
    replies.append((200, case["response"]))
    result = await run(operation, case["config"])
    assert result["status"] == "success"
    assert result["data"] == case["response"]
    assert len(requests) == 1 and replies == []
    request = requests[0]
    assert (request.method, request.url.path) == (case["method"], case["path"])
    assert not request.url.query
    if case["method"] == "POST":
        model = blitz.BlitzAPIFullConfig.model_validate({"config": {"operation": operation, **case["config"]}, "credentials": AUTH})
        assert json.loads(request.content) == model.config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_blitz_api_cursor_and_filters_preserved_without_automatic_pagination(transport):
    requests, replies = transport
    payload = {"results": [], "cursor": "next-page-456", "max_results": 5, "results_length": 0}
    replies.append((200, payload))
    out = await run("find_people", {"cursor": "previous-page-123", "max_results": 5,
        "company": {"industry": {"include": ["Software Development"]}},
        "people": {"location": {"country_code": ["US"]}}})
    body = json.loads(requests[0].content)
    assert body["cursor"] == "previous-page-123" and body["max_results"] == 5
    assert body["company"]["industry"]["include"] == ["Software Development"]
    assert body["people"]["location"]["country_code"] == ["US"]
    assert out["data"] == payload and len(requests) == 1


@pytest.mark.asyncio
async def test_blitz_api_no_match_is_success(transport):
    transport[1].append((200, {"found": False, "person": None}))
    result = await run("enrich_person", EXAMPLES["enrich_person"]["config"])
    assert result["status"] == "success" and result["data"]["found"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("code,payload", [
    (401, {"success": False, "message": "Invalid API key"}),
    (402, {"message": "No records remaining"}),
    (422, {"message": "Invalid body"}),
    (423, {"blocked": True, "message": "Account locked"}),
    (429, {"message": "Rate limit exceeded"}),
    (503, {"message": "Service unavailable"}),
    (302, {"message": "Redirect refused"}),
    (200, b"<html>Oops</html>"),
    (200, []),
    (200, {"success": False}),
    (200, {"blocked": True}),
    (200, {"valid": False, "id": "key1"}),
    (200, {"valid": True}),
])
async def test_blitz_api_errors_fail_without_retry(transport, code, payload):
    transport[1].append((code, payload))
    with pytest.raises(ValueError):
        await run("get_key_info")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_blitz_api_connection_evidence_names_account_key(transport):
    transport[1].append((200, EXAMPLES["get_key_info"]["response"]))
    evidence = await collect_evidence(node_type=NODE, user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert evidence.reachable is True
    assert evidence.account_label == EXAMPLES["get_key_info"]["response"]["id"]
    assert transport[0][0].method == "GET"


@pytest.mark.asyncio
async def test_blitz_api_provider_rejection_survives_for_connect(transport):
    transport[1].append((401, {"message": "Invalid API key, please provide a valid API key"}))
    evidence = await collect_evidence(node_type=NODE, user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert evidence.reachable is False
    assert "Invalid API key" in evidence.error


@pytest.mark.asyncio
async def test_blitz_api_secret_is_redacted(transport):
    transport[1].append((200, {"found": False, "reflection": AUTH["api_key"]}))
    assert AUTH["api_key"] not in json.dumps(await run("enrich_person", EXAMPLES["enrich_person"]["config"]))


@pytest.mark.parametrize("config", [
    {"operation": "enrich_person"},
    {"operation": "find_employees", "company_linkedin_url": "x", "max_results": 51},
    {"operation": "find_employees", "company_linkedin_url": "x", "job_level": ["CEO"]},
    {"operation": "search_waterfall_icp", "company_linkedin_url": "x", "cascade": []},
    {"operation": "find_people", "company": {"made_up": True}},
    {"operation": "search_companies", "cursor": "xx"},
    {"operation": "search_jobs", "job": {"date_posted": {"last_days": 3651}}},
    {"operation": "get_key_info", "base_url": "https://attacker.test"},
])
def test_blitz_api_rejects_contract_invalid_inputs(config):
    with pytest.raises(ValidationError):
        blitz.BlitzAPIFullConfig.model_validate({"config": config, "credentials": AUTH})


@pytest.mark.parametrize("key", ["", "YOUR_API_KEY", "https://example.test", "x-api-key: secret", "abc\r\nHeader: x"])
def test_blitz_api_rejects_bad_credential(key):
    with pytest.raises((ValidationError, ValueError)):
        blitz.BlitzAPIKeyCredential(api_key=key)


def test_blitz_api_discovery_and_manual_defaults():
    assert NODE_REGISTRY[NODE] is blitz.BlitzAPINode
    credential = blitz.BlitzAPIKeyCredential(api_key="  "+AUTH["api_key"]+"  ")
    assert credential.credential_type == "blitz_api_key" and credential.api_key == AUTH["api_key"]
