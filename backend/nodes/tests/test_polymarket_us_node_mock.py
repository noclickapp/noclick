"""Native transport contracts with synthetic credentials; never trades live."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from nodes import polymarket_us_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/polymarket-us/requests.json").read_text())
SEED = bytes(range(32))
CREDENTIAL = {"credential_type": "polymarket_us_api_key", "key_id": "synthetic-key-id",
    "secret_key": base64.b64encode(SEED).decode()}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=CREDENTIAL):
    return NodeFactory.create_node(node_id="polymarket-us-test", node_type="automation-polymarket-us",
        node_data={"config": config, "credentials": credential})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_polymarket_us_native_requests_and_response_preservation(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, fixture["response"])
    output = await node(fixture["config"]).execute({})
    assert output["status"] == "success" and output["data"] == fixture["response"]
    if operation == "get_balances":
        assert output["items"] == [{"name": "USD: 123.45"}]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert str(request.url).split("?")[0] == fixture["url"]
    if request.url.host == "api.polymarket.us":
        assert request.headers["X-PM-Access-Key"] == CREDENTIAL["key_id"]
        timestamp = request.headers["X-PM-Timestamp"]
        assert abs(int(timestamp) - int(native.time.time() * 1000)) < 1000
        public_key = Ed25519PrivateKey.from_private_bytes(SEED).public_key()
        public_key.verify(base64.b64decode(request.headers["X-PM-Signature"]),
            (timestamp + request.method + request.url.path).encode())
    else:
        assert not any(k.startswith("x-pm-") for k in request.headers)
    assert CREDENTIAL["secret_key"] not in str(request.headers) + request.content.decode() + str(output)
    if "body" in fixture["config"]:
        expected = json.loads(json.dumps(fixture["config"]["body"]))
        if operation == "preview_order":
            expected["request"]["manualOrderIndicator"] = "MANUAL_ORDER_INDICATOR_AUTOMATIC"
        assert json.loads(request.content) == expected
    else:
        assert request.content == b""
    route = native.ROUTES[operation]
    for name in route["query_fields"]:
        if name not in fixture["config"]:
            assert name not in request.url.params
            continue
        value = fixture["config"][name]
        expected = value if isinstance(value, list) else [value]
        assert request.url.params.get_list(name) == [str(v).lower() if isinstance(v, bool) else str(v) for v in expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_polymarket_us_rejections_redact_credentials_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status,
        text="provider rejected " + CREDENTIAL["key_id"] + " " + CREDENTIAL["secret_key"],
        headers={"Location": "https://example.invalid/"}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_balances"}).execute({})
    assert f"HTTP {status}" in str(error.value)
    assert "provider rejected" in str(error.value)
    assert all(value not in str(error.value) for value in (CREDENTIAL["key_id"], CREDENTIAL["secret_key"]))
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], None, {"error": "rejected"}, {"errors": ["rejected"]}])
async def test_polymarket_us_invalid_response_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_balances"}).execute({})


@pytest.mark.parametrize("secret", ["<token>", "not-base64", base64.b64encode(b"short").decode()])
def test_polymarket_us_manual_credential_rejects_invalid_signing_keys(secret):
    with pytest.raises(ValidationError) as error:
        native.PolymarketUSAPIKeyCredential.model_validate({**CREDENTIAL, "secret_key": secret})
    assert secret not in str(error.value)


def test_polymarket_us_default_type_and_64_byte_private_key():
    credential = native.PolymarketUSAPIKeyCredential.model_validate({
        "key_id": CREDENTIAL["key_id"], "secret_key": base64.b64encode(SEED + SEED).decode()})
    assert credential.credential_type == "polymarket_us_api_key"


@pytest.mark.parametrize("config", [
    {"operation": "create_order", "body": {}},
    {"operation": "create_order", "body": {"marketSlug": "market", "type": "UNKNOWN"}},
    {"operation": "cancel_order", "orderId": "order-1", "body": {"unsupported": True}},
    {"operation": "list_positions", "limit": 0},
    {"operation": "list_markets", "offset": -1},
    {"operation": "get_order"},
    {"operation": "withdraw_funds"},
])
def test_polymarket_us_bad_config_rejected(config):
    with pytest.raises(ValidationError):
        native.PolymarketUSFullConfig.model_validate({"config": config, "credentials": CREDENTIAL})


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "a/b", "a?b", "a#b"])
async def test_polymarket_us_path_identifier_cannot_change_route(monkeypatch, identifier):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({"operation": "get_order", "orderId": identifier}).execute({})
    assert requests == []


@pytest.mark.parametrize("updates", [
    {"quantity": 0}, {"quantity": -1}, {"price": None}, {"intent": None},
    {"outcomeSide": "OUTCOME_SIDE_YES"}, {"cashOrderQty": {"value": "1", "currency": "USD"}},
    {"price": {"value": "NaN", "currency": "USD"}},
    {"tif": "TIME_IN_FORCE_GOOD_TILL_DATE"},
])
def test_polymarket_us_order_semantics_rejected_before_transport(updates):
    body = {**FIXTURES["create_order"]["config"]["body"], **updates}
    with pytest.raises(ValidationError):
        native.PolymarketUSFullConfig.model_validate({"config": {"operation": "create_order", "body": body}, "credentials": CREDENTIAL})
