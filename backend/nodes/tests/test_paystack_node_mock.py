"""Offline factory and wire regressions for Paystack; no real key or account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import paystack_node as native
from nodes.core.registry import NodeFactory

KEY = "sk_test_synthetic_fixture_only"
CREDENTIAL = {"credential_type": "paystack_api_key", "secret_key": KEY}
CASES = [
    ({"operation": "initialize_transaction", "email": "test@demo.com", "amount": 10000}, "POST", "/transaction/initialize", {"email": "test@demo.com", "amount": 10000}),
    ({"operation": "verify_transaction", "reference": "re4lyvq3s3"}, "GET", "/transaction/verify/re4lyvq3s3", {}),
    ({"operation": "list_transactions"}, "GET", "/transaction", {"page": "1", "per_page": "50"}),
    ({"operation": "get_transaction", "id": 4099260516}, "GET", "/transaction/4099260516", {}),
    ({"operation": "create_customer", "email": "rock@sandy.com", "first_name": "Rock"}, "POST", "/customer", {"email": "rock@sandy.com", "first_name": "Rock"}),
    ({"operation": "list_customers"}, "GET", "/customer", {"page": "1", "perPage": "50"}),
    ({"operation": "get_customer", "code": "CUS_c6wqvwmvwopw4ms"}, "GET", "/customer/CUS_c6wqvwmvwopw4ms", {}),
    ({"operation": "update_customer", "code": "CUS_c6wqvwmvwopw4ms", "first_name": "Cecilia"}, "PUT", "/customer/CUS_c6wqvwmvwopw4ms", {"first_name": "Cecilia"}),
    ({"operation": "create_plan", "name": "Basic", "amount": 150000, "interval": "monthly"}, "POST", "/plan", {"name": "Basic", "amount": 150000, "interval": "monthly"}),
    ({"operation": "list_plans"}, "GET", "/plan", {"page": "1", "perPage": "50"}),
    ({"operation": "get_plan", "code": "PLN_gx2wn530m0i3w3m"}, "GET", "/plan/PLN_gx2wn530m0i3w3m", {}),
    ({"operation": "update_plan", "code": "PLN_gx2wn530m0i3w3m", "name": "Starter", "send_sms": False}, "PUT", "/plan/PLN_gx2wn530m0i3w3m", {"name": "Starter", "send_sms": False}),
    ({"operation": "create_subscription", "customer": "CUS_xnxdt6s1zg1f4nx", "plan": "PLN_gx2wn530m0i3w3m"}, "POST", "/subscription", {"customer": "CUS_xnxdt6s1zg1f4nx", "plan": "PLN_gx2wn530m0i3w3m"}),
    ({"operation": "list_subscriptions", "plan_id": 2697466, "customer": "123"}, "GET", "/subscription", {"page": "1", "perPage": "50", "plan": "2697466", "customer": "123"}),
    ({"operation": "get_subscription", "code": "SUB_vsyqdmlzble3uii"}, "GET", "/subscription/SUB_vsyqdmlzble3uii", {}),
    ({"operation": "enable_subscription", "code": "SUB_vsyqdmlzble3uii", "token": "d7gofp6yppn3qz7"}, "POST", "/subscription/enable", {"code": "SUB_vsyqdmlzble3uii", "token": "d7gofp6yppn3qz7"}),
    ({"operation": "disable_subscription", "code": "SUB_vsyqdmlzble3uii", "token": "d7gofp6yppn3qz7"}, "POST", "/subscription/disable", {"code": "SUB_vsyqdmlzble3uii", "token": "d7gofp6yppn3qz7"}),
    ({"operation": "create_refund", "transaction": "mpkr39h74k", "amount": 100}, "POST", "/refund", {"transaction": "mpkr39h74k", "amount": 100}),
    ({"operation": "list_refunds"}, "GET", "/refund", {"page": "1", "perPage": "50"}),
    ({"operation": "get_refund", "id": 15581137}, "GET", "/refund/15581137", {}),
    ({"operation": "get_balance"}, "GET", "/balance", {}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="paystack-fixture", node_type="automation-paystack",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, body, status=200):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,values", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_paystack_factory_exact_one_operation(monkeypatch, config, method, path, values):
    op = config["operation"]
    data = [] if op.startswith("list_") or op == "get_balance" else {"id": 123, "status": "pending"}
    body = {"status": True, "message": "Accepted", "data": data}
    if op in native._NO_DATA:
        body.pop("data")
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == body.get("data")
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == "api.paystack.co" and req.url.scheme == "https"
    assert req.headers["Authorization"] == "Bearer " + KEY
    assert (dict(req.url.params) if method == "GET" else json.loads(req.content)) == values
    assert result.get("write_acknowledged", False) == (method != "GET")
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_paystack_paging_filters_dates_and_no_follow(monkeypatch):
    reqs = transport(monkeypatch, {"status": True, "message": "Customers retrieved", "data": [{"email": "rock@sandy.com"}], "meta": {"page": 2, "pageCount": 3}})
    result = await node({"operation": "list_customers", "page": 2, "per_page": 10,
        "from_date": "2024-01-01T00:00:00Z", "to_date": "2024-02-01T00:00:00Z"}).execute({})
    assert dict(reqs[0].url.params) == {"page": "2", "perPage": "10", "from": "2024-01-01T00:00:00Z", "to": "2024-02-01T00:00:00Z"}
    assert result["meta"]["pageCount"] == 3 and result["page"] == 2 and len(reqs) == 1
    assert native.PaystackNode.connection_evidence.operation == "list_customers"


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [({"status": False, "message": "Invalid key"}, 401), ({"status": False, "message": "Forbidden"}, 403), ({"status": False, "message": "Bad input"}, 200), ({"status": True, "data": []}, 302), ({"status": True, "data": {}}, 200), ({}, 200)])
async def test_paystack_refuses_rejection_redirect_and_bad_envelopes(monkeypatch, body, status):
    reqs = transport(monkeypatch, body, status)
    result = await node({"operation": "list_customers"}).execute({})
    assert result["status"] == "error" and len(reqs) == 1
    if body.get("status") is False:
        assert result["error"] == body["message"]


@pytest.mark.asyncio
async def test_paystack_write_timeout_is_unknown_without_retry(monkeypatch):
    reqs = transport(monkeypatch, httpx.ReadTimeout("secret " + KEY))
    result = await node({"operation": "create_refund", "transaction": "mpkr39h74k"}).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown"
    assert len(reqs) == 1 and KEY not in str(result)


@pytest.mark.asyncio
async def test_paystack_response_redacts_api_key_and_subscription_token(monkeypatch):
    transport(monkeypatch, {"status": False, "message": KEY + " token-for-subscription"})
    result = await node({"operation": "disable_subscription", "code": "SUB_example", "token": "token-for-subscription"}).execute({})
    assert KEY not in str(result) and "token-for-subscription" not in str(result)


@pytest.mark.parametrize("value", ["pk_test_public", "Bearer sk_test_private", "sk_bad\nheader", "https://example.com", "<token>", " ", "sk_café"])
def test_paystack_invalid_keys(value):
    with pytest.raises(ValidationError):
        native.PaystackAPIKeyCredential(secret_key=value)


def test_paystack_key_shaping_and_wrong_credential_family():
    assert native.PaystackAPIKeyCredential(secret_key="  " + KEY + "\n").secret_key == KEY
    with pytest.raises(ValueError):
        node({"operation": "get_balance"}, {"credential_type": "other_api_key", "secret_key": KEY})


@pytest.mark.parametrize("config", [
    {"operation": "get_customer", "code": "../balance"},
    {"operation": "get_customer", "code": "CUS_a?x=1"},
    {"operation": "get_transaction", "id": -1},
    {"operation": "create_refund", "transaction": "ref", "amount": True},
    {"operation": "create_plan", "name": "Basic", "amount": 0, "interval": "monthly"},
    {"operation": "list_customers", "page": 0},
    {"operation": "list_refunds", "per_page": 101},
    {"operation": "list_plans", "from_date": "2024-02-01", "to_date": "2024-01-01"},
])
def test_paystack_invalid_configs(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_paystack_update_omits_null_and_preserves_metadata_string(monkeypatch):
    reqs = transport(monkeypatch, {"status": True, "data": {"customer_code": "CUS_example"}})
    await node({"operation": "update_customer", "code": "CUS_example", "phone": None, "metadata": '{"order": 123}'}).execute({})
    assert json.loads(reqs[0].content) == {"metadata": '{"order": 123}'}


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"operation": "update_customer", "code": "CUS_example"}, {"operation": "update_plan", "code": "PLN_example"}, {"operation": "create_customer", "email": "test@demo.com", "metadata": '[]'}])
async def test_paystack_empty_updates_and_bad_metadata_do_not_send(monkeypatch, config):
    reqs = transport(monkeypatch, {"status": True})
    with pytest.raises(ValueError):
        await node(config).execute({})
    assert not reqs


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,values", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_paystack_official_documentation_response(monkeypatch, config, method, path, values):
    fixtures = json.loads((Path(__file__).parent / "fixtures/paystack/documented_responses.json").read_text())
    verb, route, _ = native.ROUTES[config["operation"]]
    example = fixtures[verb + " " + route]
    transport(monkeypatch, example["body"])
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == example["body"].get("data")
    assert example["source"].startswith("https://raw.githubusercontent.com/PaystackOSS/doc-code-snippets/")
