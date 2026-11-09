"""Exercise the native factory and Soundee's published HTTP contract offline."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import soundee_node as native
from nodes.core.registry import NodeFactory

TOKEN = "soundee-synthetic-fixture-key"
AUTH = {"credential_type": "soundee_api_key", "api_key": TOKEN}
COUPON = json.loads((Path(__file__).parent / "fixtures/soundee/coupon.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="soundee-test", node_type="automation-soundee",
                                  node_data={"config": config, "credentials": AUTH})


def transport(monkeypatch, body, status=200):
    calls = []
    def send(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


CASES = [
    ({"operation": "get_account"}, "GET", "/me/", {"name": "Fixture Producer"}),
    ({"operation": "list_coupons", "list_type": "active", "q": "50%"}, "GET", "/me/coupons", {}),
    ({"operation": "get_coupon", "id": 994}, "GET", "/me/coupons/994", {}),
    ({"operation": "create_coupon"}, "POST", "/me/coupons", COUPON),
    ({"operation": "update_coupon", "id": 994, "amount": 25, "active": False, "maxUsage": 0}, "PUT", "/me/coupons/994", {}),
    ({"operation": "list_email_captures", "list_type": "download"}, "GET", "/me/email-captures", {}),
    ({"operation": "list_cart_abandonments", "list_type": "recoverable"}, "GET", "/me/cart-abandonments", ""),
    ({"operation": "get_cart_abandonment", "id_or_token": "cart-token"}, "GET", "/me/cart-abandonments/cart-token", ""),
    ({"operation": "list_transactions", "list_type": "refund"}, "GET", "/me/transactions", {}),
    ({"operation": "get_transaction", "id": "sale-1"}, "GET", "/me/transactions/sale-1", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_each_contract_operation(monkeypatch, config, method, path, body):
    calls = transport(monkeypatch, body)
    assert await node(config).execute({}) == {"status": "success", "data": body}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.soundee.com" and request.headers["x-api-key"] == TOKEN
    assert TOKEN not in str(request.url)
    if method == "POST":
        assert request.content == b""
    if method == "PUT":
        assert json.loads(request.content) == {"amount": 25, "active": False, "maxUsage": 0}
    if config["operation"].startswith("list_"):
        assert dict(request.url.params) == {"offset": "0", "limit": "30", **{k: str(v) for k,v in config.items() if k in {"list_type", "q"}}}


@pytest.mark.asyncio
async def test_update_nested_conditions_and_dates_omit_unset(monkeypatch):
    calls = transport(monkeypatch, {})
    await node({"operation": "update_coupon", "id": 994,
                "conditions": {"stores": {"exclude": False, "list": [1, 2]}},
                "startDate": "2026-11-09T00:00:00Z", "neverEnd": True}).execute({})
    assert json.loads(calls[0].content) == {"conditions": {"stores": {"exclude": False, "list": [1, 2]}},
                                          "startDate": "2026-11-09T00:00:00Z", "neverEnd": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_provider_failure_and_secret_redaction(monkeypatch, status):
    calls = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert TOKEN not in json.dumps(result) and len(calls) == 1


@pytest.mark.asyncio
async def test_error_envelope_and_nested_redaction(monkeypatch):
    transport(monkeypatch, {"error": "invalid key " + TOKEN})
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"
    transport(monkeypatch, {"nested": [{"echo": TOKEN}]})
    assert TOKEN not in json.dumps(await node({"operation": "get_account"}).execute({}))


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_without_retry(monkeypatch):
    calls = []
    def client(**kwargs):
        def send(request):
            calls.append(request)
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "create_coupon"}).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown" and len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_coupon", "id": 0}, {"operation": "get_transaction", "id": "../x"},
    {"operation": "get_cart_abandonment", "id_or_token": "https://evil.test"},
    {"operation": "list_transactions", "list_type": "active"},
    {"operation": "list_coupons", "limit": 101}, {"operation": "create_coupon", "name": "unsupported"},
])
def test_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        native.SoundeeNode.parse_config({"config": config, "credentials": AUTH})


def test_manual_credential_and_account_evidence():
    assert native.SoundeeAPIKeyCredential(api_key=TOKEN).credential_type == "soundee_api_key"
    assert native.SoundeeNode.connection_evidence.identity_operation == "get_account"
    with pytest.raises(ValueError):
        native.SoundeeAPIKeyCredential(api_key="https://soundee.com/key")


@pytest.mark.asyncio
async def test_empty_error_body_still_refuses_connection(monkeypatch):
    from nodes.core.connection_evidence import _raise_if_error_envelope
    transport(monkeypatch, {}, 401)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status_code"] == 401 and result["message"]
    with pytest.raises(Exception, match="401"):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
async def test_non_json_response_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html>login</html>")), **kwargs))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "get_account"}).execute({})
