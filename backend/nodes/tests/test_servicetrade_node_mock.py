"""Exercise ServiceTrade through NoClick's real factory with a mocked HTTP transport.

Provider-authored response examples pin parsing; exact request assertions cover
all 25 operations without using the implementation's routing table as an oracle.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import servicetrade_node as st
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import shape_credential
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/servicetrade/documented_operations.json").read_text())
AUTH = {"credential_type": "servicetrade_session_token", "session_token": "fixture-not-live-session-123"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.servicetrade.com"
        assert request.headers["cookie"] == "PHPSESSID=" + AUTH["session_token"]
        assert "authorization" not in request.headers
        assert AUTH["session_token"] not in str(request.url)
        status, body = responses.pop(0)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(st, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(operation, config=None):
    return await run_node_operation(node_type="automation-servicetrade", operation=operation,
        arguments=deepcopy(config or {}), credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_all_operations_match_documented_requests_and_responses(transport, case):
    requests, responses = transport
    responses.append((200, case["response"]))
    result = await run(case["operation"], case["config"])
    assert result["status"] == "success"
    assert result["data"] == case["response"]["data"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == "/api" + case["path"]
    assert dict(request.url.params) == case["params"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["operation"].startswith("list_"):
        assert result["next_page"] is None
        assert isinstance(result["items"], list)


@pytest.mark.asyncio
async def test_pagination_filters_and_boolean_serialization(transport):
    requests, responses = transport
    responses.append((200, {"data": {"companies": [], "page": 2, "totalPages": 3}}))
    result = await run("list_companies", {"page": 2, "limit": 25, "is_customer": True, "updated_after": 1700000000})
    assert result["next_page"] == 3
    assert dict(requests[0].url.params) == {"page": "2", "limit": "25", "isCustomer": "true", "updatedAfter": "1700000000"}
    responses.append((200, {"data": {"jobs": [], "page": 1, "totalPages": 0}}))
    await run("list_jobs", {"status": "*"})
    assert requests[1].url.params["status"] == "*"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 400, 401, 403, 404, 429, 500])
async def test_error_envelopes_never_succeed_or_leak_token(transport, code):
    requests, responses = transport
    responses.append((code, {"data": None, "messages": {"error": ["Session rejected " + AUTH["session_token"]]}}))
    result = await run("list_companies")
    assert result["status"] == "error"
    assert result["http_status"] == code
    assert AUTH["session_token"] not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"<html>Sign in</html>", [], {"data": {}}, {"data": {"companies": [], "page": 0, "totalPages": 1}}])
async def test_malformed_success_is_unverified(transport, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError):
        await run("list_companies")


@pytest.mark.asyncio
async def test_partial_update_preserves_false_zero_and_empty_lists(transport):
    requests, responses = transport
    responses.append((200, {"data": {"id": 33}}))
    await run("update_job", {"job_id": 33, "percent_complete": 0, "service_request_ids": []})
    assert json.loads(requests[0].content) == {"percentComplete": 0, "serviceRequestIds": []}
    responses.append((200, {"data": {"id": 33}}))
    await run("update_appointment", {"appointment_id": 33, "released": False})
    assert json.loads(requests[1].content) == {"released": False}


@pytest.mark.asyncio
async def test_connection_evidence_uses_account_companies(transport):
    transport[1].append((200, CASES[0]["response"]))
    evidence = await collect_evidence(node_type="automation-servicetrade", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert evidence.reachable is True
    assert evidence.samples
    assert transport[0][0].method == "GET"
    assert transport[0][0].url.path == "/api/company"


def test_manual_connect_shapes_the_only_required_secret_and_default_type():
    shaped, errors, resolved = shape_credential("servicetrade_session_token", {"session_token": AUTH["session_token"]})
    assert not errors
    assert resolved is not None and resolved[1] is st.ServiceTradeSessionToken
    assert st.ServiceTradeSessionToken.model_validate(shaped).model_dump() == AUTH


@pytest.mark.parametrize("token", ["PHPSESSID=value", "Cookie: value", "https://example.com/token", "bad; injected=value", "bad\r\nHeader:value"])
def test_credential_rejects_headers_urls_and_cookie_injection(token):
    with pytest.raises(ValueError):
        st.ServiceTradeSessionToken(session_token=token)


@pytest.mark.parametrize("config", [
    {"operation": "get_job", "job_id": "../auth"},
    {"operation": "get_job", "job_id": True},
    {"operation": "get_job", "job_id": -1},
    {"operation": "update_job", "job_id": 33},
    {"operation": "update_appointment", "appointment_id": 33, "status": "unscheduled"},
    {"operation": "create_contact"},
    {"operation": "create_job", "location_id": 1},
    {"operation": "create_location", "company_id": 1, "name": "X", "address": {"street": "A"}},
    {"operation": "list_companies", "limit": 2001},
    {"operation": "update_job", "job_id": 33, "percent_complete": 101},
])
def test_invalid_inputs_rejected_before_transport(config):
    assert not st.ServiceTradeNode.validate_config({"config": config, "credentials": AUTH})["valid"]


@pytest.mark.asyncio
async def test_mutation_timeout_never_retries_or_exposes_transport_details(transport):
    transport[1].append((0, httpx.ReadTimeout("sensitive transport detail " + AUTH["session_token"])))
    with pytest.raises(ValueError, match="a write may have taken effect") as caught:
        await run("create_job", {"location_id": 33, "type": "repair"})
    assert AUTH["session_token"] not in str(caught.value)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_redirect_is_not_followed(transport):
    transport[1].append((302, {}))
    result = await run("list_companies")
    assert result["status"] == "error"
    assert len(transport[0]) == 1
