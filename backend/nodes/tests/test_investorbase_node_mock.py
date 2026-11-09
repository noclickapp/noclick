"""InvestorBase native factory and provider request regressions; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import investorbase_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-investorbase-api-key-42"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/investorbase/inputs.json").read_text())["configs"]
ARRAY_OPS = {"resolve_address", "search_buyers", "get_buyer_search_results", "search_investor_activity", "get_investor_comps"}
ENTERPRISE_OPS = {"get_account_details", "get_user", "create_user", "update_user", "create_user_subscription", "update_user_subscription"}
# Independent fixed expectations, rather than using the node routing table.
EXPECTED = {
    "resolve_address": ("POST", "/v1/autocomplete", 200),
    "search_buyers": ("POST", "/v1/buyer-search", 200),
    "get_buyer_search_results": ("GET", "/v1/buyer-search", 200),
    "get_retail_comps": ("POST", "/v1/retail-comps", 200),
    "search_investor_activity": ("POST", "/v1/analytics-search", 200),
    "get_market_summary": ("POST", "/v1/analytics-summary", 200),
    "get_investor_comps": ("POST", "/v1/investor-comps", 200),
    "get_buyer_history": ("POST", "/v1/linked-deals", 200),
    "get_usage": ("GET", "/v1/usage", 200),
    "get_account_details": ("GET", "/v1/api-credentials", 200),
    "get_user": ("GET", "/v1/api-users", 200),
    "create_user": ("POST", "/v1/api-users", 201),
    "update_user": ("PATCH", "/v1/api-users", 200),
    "create_user_subscription": ("POST", "/v1/api-user-subscriptions", 201),
    "update_user_subscription": ("PATCH", "/v1/api-user-subscriptions", 200),
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "investorbase_api_key", "api_key": TOKEN, **updates}


def node(operation, *, config=None, creds=None):
    return NodeFactory.create_node(node_id="investorbase-test", node_type="automation-investorbase",
        node_data={"config": {"operation": operation, **(FIXTURE[operation] if config is None else config)},
                   "credentials": credential() if creds is None else creds})


def transport(monkeypatch, body=None, status=200, *, reply=None):
    calls = []
    def respond(request):
        calls.append(request)
        return reply(request) if reply else httpx.Response(status, content=json.dumps(body), headers={"content-type": "application/json"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXPECTED)
async def test_investorbase_all_operations_one_documented_request(monkeypatch, operation):
    method, path, status = EXPECTED[operation]
    body = [] if operation in ARRAY_OPS else {"success": True}
    calls = transport(monkeypatch, body, status)
    creds = credential(key_kind="enterprise") if operation in ENTERPRISE_OPS else credential()
    result = await node(operation, creds=creds).execute({})
    assert result == {"status": "success", "http_status": status, "data": body}
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method and req.url.path == path and req.url.host == "api.investorbase.com"
    assert req.headers["x-api-key"] == TOKEN and "x-user-id" not in req.headers
    if method == "GET":
        assert not req.content
        assert dict(req.url.params) == FIXTURE[operation]
    else:
        data = json.loads(req.content)
        assert data.items() >= FIXTURE[operation].items()
        assert "operation" not in data and "async_search" not in data
        assert req.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_investorbase_enterprise_user_header_only_on_data_calls(monkeypatch):
    calls = transport(monkeypatch, [])
    creds = credential(key_kind="enterprise", enterprise_user_id="user_555")
    await node("resolve_address", creds=creds).execute({})
    assert calls[0].headers["x-user-id"] == "user_555"
    calls = transport(monkeypatch, {"user_id": "user_555"})
    await node("get_user", creds=creds).execute({})
    assert "x-user-id" not in calls[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("op,creds", [
    ("create_user", credential()),
    ("get_usage", credential(key_kind="enterprise")),
    ("resolve_address", credential(key_kind="enterprise")),
])
async def test_investorbase_key_kind_and_enterprise_user_checked_before_request(monkeypatch, op, creds):
    calls = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node(op, creds=creds).execute({})
    assert not calls


@pytest.mark.asyncio
async def test_investorbase_async_submission_and_pending_poll(monkeypatch):
    calls = transport(monkeypatch, {"search_id": "550e8400-e29b-41d4-a716-446655440000"}, 202)
    result = await node("search_buyers", config={"address": "123 Main St, Charleston, SC 29407", "async": True, "create_deal": False}).execute({})
    assert result["status"] == "pending" and result["search_id"]
    data = json.loads(calls[0].content)
    assert data["async"] is True and data["create_deal"] is False
    transport(monkeypatch, None)
    assert (await node("get_buyer_search_results").execute({}))["status"] == "pending"
    transport(monkeypatch, [])
    assert (await node("get_buyer_search_results").execute({}))["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_investorbase_refusals_preserve_error_and_never_retry(monkeypatch, status):
    calls = transport(monkeypatch, {"error": "Provider refusal"}, status)
    result = await node("update_user", creds=credential(key_kind="enterprise")).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Provider refusal"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_investorbase_rate_limit_plaintext_and_secret_echo(monkeypatch):
    calls = transport(monkeypatch, reply=lambda r: httpx.Response(429, text="Too many requests"))
    assert (await node("get_usage").execute({}))["status"] == "error"
    assert len(calls) == 1
    transport(monkeypatch, {"error": "Invalid " + TOKEN}, 401)
    assert TOKEN not in str(await node("get_usage").execute({}))


@pytest.mark.asyncio
async def test_investorbase_subscriber_and_enterprise_connection_evidence(monkeypatch):
    calls = transport(monkeypatch, {"plan": "standard", "period": {"resets_at": "2026-11-14T15:30:00.000Z"}, "company": {"buyer_search": {"used": 7}}})
    result = await native.InvestorBaseNode.load_field_options("account", credential())
    assert "7 buyer searches" in result["options"][0]["label"]
    assert calls[0].url.path == "/v1/usage"
    calls = transport(monkeypatch, {"account_name": "Acme Corp"})
    result = await native.InvestorBaseNode.load_field_options("account", credential(key_kind="enterprise"))
    assert result["options"][0]["label"] == "Acme Corp"
    assert calls[0].url.path == "/v1/api-credentials"
    transport(monkeypatch, {"error": "Key rejected"}, 401)
    assert (await native.InvestorBaseNode.load_field_options("account", credential()))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("op,body", [("get_usage", {}), ("resolve_address", {}), ("get_user", []), ("get_usage", {"error": "bad"}), ("resolve_address", [42])])
async def test_investorbase_rejects_wrong_response_shapes(monkeypatch, op, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node(op, creds=credential(key_kind="enterprise") if op in ENTERPRISE_OPS else credential()).execute({})


@pytest.mark.parametrize("model,data", [
    (native.SearchBuyers, {}),
    (native.SearchBuyers, {"latitude": 32.7765}),
    (native.SearchBuyers, {"latitude": 91, "longitude": 0}),
    (native.SearchBuyers, {"address": "123 Main", "radius_miles": 11}),
    (native.SearchBuyers, {"address": "123 Main", "min_bedrooms": 4, "max_bedrooms": 2}),
    (native.SearchBuyers, {"address": "123 Main", "webhook_url": "http://example.com"}),
    (native.GetBuyerHistory, {"search_string": "JD Properties, LLC"}),
    (native.GetBuyerHistory, {"property_address": "123 Main"}),
    (native.GetMarketSummary, {"latitude": 0, "longitude": 0, "lookback_months": 61}),
    (native.UpdateUser, {"user_id": "user_555", "active": "false"}),
])
def test_investorbase_constraints_and_conditional_inputs(model, data):
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_investorbase_manual_credential_has_default_type():
    value = native.InvestorBaseAPIKeyCredential.model_validate({"api_key": TOKEN})
    assert value.credential_type == "investorbase_api_key" and value.key_kind == "subscriber"
    assert TOKEN not in repr(value)
