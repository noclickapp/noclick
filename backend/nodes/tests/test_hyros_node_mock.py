"""Exercise every Hyros operation through the native factory at the HTTP boundary."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote

import httpx
import pytest
from nodes import hyros_node as hyros
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import shape_credential
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/hyros/operations.json").read_text())
AUTH = {"credential_type": "hyros_api_key", "api_key": "hyros-fixture-secret"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.hyros.com"
        assert request.headers["API-Key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception): raise reply
        status, body = reply
        return httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(hyros, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def node(op, config=None):
    return NodeFactory.create_node(node_id="hyros-test", node_type="automation-hyros",
        node_data={"config": {"operation": op, **(config or {})}, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("op", CASES)
async def test_documented_operation_wire_contract(transport, op):
    requests, replies = transport
    case = CASES[op]
    expected = case["response"]
    if expected is None:
        expected = {"result": {"userProfile": {"email": "person@example.test", "companyName": "Fixture Company"}}} if op == "get_user_info" else {"result": [], "nextPageId": "next-cursor", "request_id": "read-id"}
    replies.append((200, expected))
    result = await node(op, case["config"]).execute({})
    assert result["status"] == "success"
    for key, value in expected.items(): assert result[key] == value
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    path = case["path"]
    for key in ["id", "request_id"]:
        if key in case["config"]: path = path.replace("{" + key + "}", quote(case["config"][key], safe=""))
    assert request.url.raw_path.split(b"?")[0] == path.encode()
    if "body" in case["config"]: assert json.loads(request.content) == case["config"]["body"]
    else: assert not request.content
    expected_query = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in case["config"].items() if key not in {"body", "id", "request_id"}}
    assert dict(request.url.params) == expected_query
    if case["method"] != "GET": assert result["write_status"] == "accepted"


@pytest.mark.asyncio
async def test_cursors_filters_and_query_booleans(transport):
    requests, replies = transport
    replies.append((200, {"result": [], "nextPageId": "next"}))
    output = await node("list_calls", {"pageId": "prior+/=", "pageSize": 25, "qualified": False, "emails": '"john@doe.com"'}).execute({})
    assert output["nextPageId"] == "next"
    assert requests[0].url.params["pageId"] == "prior+/="
    assert requests[0].url.params["qualified"] == "false"
    assert requests[0].url.params["emails"] == '"john@doe.com"'


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": ["Wrong Api-Key"]}), (403, {"message": ["Forbidden, missing api key roles"]}), (429, {"message": ["Rate limit exceeded"]}), (200, {"result": "ERROR", "message": ["Invalid state"]}), (200, ["unexpected"]), (302, {})])
async def test_errors_never_report_success_or_retry(transport, status, body):
    requests, replies = transport
    replies.append((status, body))
    result = await node("get_user_info").execute({})
    assert result["status"] == "error"
    assert len(requests) == 1
    if body and isinstance(body, dict): assert result["error"] == body["message"]


@pytest.mark.asyncio
async def test_unknown_write_outcome_no_retry_and_secret_redaction(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout("lost response"))
    result = await node("create_lead", {"body": {"email": "john@doe.com"}}).execute({})
    assert "do not resend" in result["error"] and len(requests) == 1
    replies.append((403, {"message": ["Rejected " + AUTH["api_key"]]}))
    result = await node("get_user_info").execute({})
    assert AUTH["api_key"] not in json.dumps(result)


@pytest.mark.parametrize("op,config", [
    ("list_products", {"bogus": "x"}), ("list_leads", {"pageSize": 251}),
    ("create_lead", {"body": {}}), ("update_lead", {"body": {"firstName": "John"}}),
    ("create_call", {"body": {"name": "Call"}}), ("add_lead_tags", {"body": {"tags": ["!Tag1"]}}),
    ("create_order", {"body": {"email": "john@doe.com", "items": []}}),
    ("create_subscription", {"body": {"email": "john@doe.com", "status": "UNKNOWN", "periodicity": "MONTH", "price": 8.9, "startDate": "2025-01-16T20:35:00"}}),
    ("create_source", {"body": {"name": "Ad", "integrationType": "FACEBOOK"}}),
    ("create_product", {"body": {"name": "AB", "price": 1}}),
])
def test_invalid_inputs_rejected_before_http(op, config):
    with pytest.raises(ValueError): node(op, config)


def test_manual_credential_default_and_secret_normalization():
    shaped, errors, _ = shape_credential("hyros_api_key", {"api_key": "  " + AUTH["api_key"] + "  "})
    assert not errors and hyros.HyrosAPIKey.model_validate(shaped).credential_type == "hyros_api_key" and shaped["api_key"] == AUTH["api_key"]


@pytest.mark.asyncio
async def test_connection_proves_the_account_from_user_info(transport):
    requests, replies = transport
    replies.append((200, {"result": {"userProfile": {"email": "owner@example.test", "companyName": "Fixture Company"}}, "request_id": "identity-read"}))
    result = await collect_evidence(node_type="automation-hyros", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert result.reachable is True and result.account_label == "owner@example.test"
    assert len(requests) == 1 and requests[0].url.path == "/api/v1.0/user-info"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_key_is_definitive_connection_evidence(transport, status):
    requests, replies = transport
    replies.append((status, {"message": ["The supplied key was refused by this account"]}))
    result = await collect_evidence(node_type="automation-hyros", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert result.reachable is False
    assert "The supplied key was refused by this account" in result.error
    assert len(requests) == 1
