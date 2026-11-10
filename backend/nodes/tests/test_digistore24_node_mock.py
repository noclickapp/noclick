"""Offline regressions for Digistore24's published API contract."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import digistore24_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-digistore24-test-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="digistore24-test", node_type="automation-digistore24",
        node_data={"config": config, "credentials": {"api_key": KEY, "credential_type": "digistore24_api_key"}})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", [
    ({"operation": "get_user_info"}, "GET", "getUserInfo", {}, None),
    ({"operation": "list_products"}, "GET", "listProducts", {"sort_by": "name"}, None),
    ({"operation": "get_product", "product_id": 39}, "GET", "getProduct", {"product_id": "39"}, None),
    ({"operation": "list_buyers", "page_no": 2, "page_size": 10}, "GET", "listBuyers", {"page_no": "2", "page_size": "10"}, None),
    ({"operation": "get_buyer", "buyer_id": 20}, "GET", "getBuyer", {"buyer_id": "20"}, None),
    ({"operation": "update_buyer", "buyer_id": 20, "first_name": "Claus"}, "PUT", "updateBuyer", {"buyer_id": "20"}, {"first_name": "Claus"}),
    ({"operation": "list_purchases"}, "GET", "listPurchases", {"from": "-24h", "to": "now", "sort_by": "date", "sort_order": "asc", "load_transactions": "false", "page_no": "1", "page_size": "500"}, None),
    ({"operation": "get_purchase", "purchase_id": "ABC123"}, "GET", "getPurchase", {"purchase_id": "ABC123"}, None),
    ({"operation": "stop_rebilling", "purchase_id": "ABC123"}, "POST", "stopRebilling", {"purchase_id": "ABC123", "force": "false", "ignore_refund_possibility": "false"}, None),
    ({"operation": "start_rebilling", "purchase_id": "ABC123"}, "POST", "startRebilling", {"purchase_id": "ABC123"}, None),
    ({"operation": "list_transactions"}, "GET", "listTransactions", {"from": "-24h", "to": "now", "sort_by": "date", "sort_order": "asc", "page_no": "1", "page_size": "500"}, None),
    ({"operation": "list_vouchers"}, "GET", "listVouchers", {}, None),
    ({"operation": "get_voucher", "code": "SALE + 10"}, "GET", "getVoucher", {"code": "SALE + 10"}, None),
    ({"operation": "create_voucher", "code": "SALE10", "first_rate": 10}, "POST", "createVoucher", {}, {"code": "SALE10", "first_rate": 10.0, "product_ids": "all", "is_count_limited": False, "count_left": 1, "upgrade_policy": "valid"}),
    ({"operation": "delete_voucher", "code": "SALE10"}, "DELETE", "deleteVoucher", {"code": "SALE10"}, None),
])
async def test_exact_contract_request_and_single_call(monkeypatch, config, method, path, query, body):
    requests = transport(monkeypatch, {"result": "success", "data": {"user_id": 12345, "user_name": "fixture-vendor"}})
    result = await node(config).execute({})
    assert result["status"] == "success" and result["readback_verified"] is False
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and str(req.url).split("?")[0] == native.BASE + "/" + path
    assert dict(req.url.params) == query
    assert req.headers["X-DS-API-KEY"] == KEY
    assert KEY not in str(req.url) and KEY not in str(result)
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"result": "error", "code": 2, "message": "Invalid API key"},
    {"result": "error", "code": 5, "message": "Permission denied"},
    {"action": "show_message", "status": "error", "http_code": 400, "data": [], "message": "Invalid field"},
])
async def test_http_200_error_envelope_is_failure(monkeypatch, payload):
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "get_user_info"}).execute({})
    assert result["status"] == "error" and result["success"] is False
    assert result["error"] == payload["message"] and len(requests) == 1


@pytest.mark.asyncio
async def test_page_preserved_without_hidden_fetch(monkeypatch):
    page = {"page_no": 2, "page_size": 10, "page_count": 3, "item_count": 21, "items": [{"id": 20}]}
    requests = transport(monkeypatch, {"result": "success", "data": page})
    result = await node({"operation": "list_buyers", "page_no": 2, "page_size": 10}).execute({})
    assert result["data"] == page and len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_does_not_retry_mutation(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("synthetic timeout"))
    result = await node({"operation": "start_rebilling", "purchase_id": "ABC123"}).execute({})
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified" and len(requests) == 1


@pytest.mark.asyncio
async def test_provider_reflected_secret_is_redacted(monkeypatch):
    transport(monkeypatch, {"result": "error", "code": 2, "message": "Rejected " + KEY})
    result = await node({"operation": "get_user_info"}).execute({})
    assert KEY not in str(result) and "[redacted]" in result["error"]


@pytest.mark.parametrize("config", [
    {"operation": "get_product", "product_id": 0},
    {"operation": "list_buyers", "page_no": 0},
    {"operation": "list_transactions", "page_size": 1001},
    {"operation": "update_buyer", "buyer_id": 20},
    {"operation": "create_voucher", "code": "SALE", "first_rate": 101},
    {"operation": "stop_rebilling", "purchase_id": "ABC123", "force": "yes"},
])
def test_invalid_configs(config):
    with pytest.raises(ValidationError):
        native.Digistore24FullConfig.model_validate({"config": config, "credentials": {"api_key": KEY}})


def test_manual_credential_defaults_and_secret_shaping():
    credential = native.Digistore24APIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "digistore24_api_key" and credential.api_key == KEY
    for value in ("https://example.com/key", "<token>", "abc\nxyz"):
        with pytest.raises(ValidationError):
            native.Digistore24APIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_empty_account_response_cannot_prove_connection(monkeypatch):
    transport(monkeypatch, {"result": "success", "data": {}})
    result = await node({"operation": "get_user_info"}).execute({})
    assert result["status"] == "error" and result["success"] is False


# IPN fields and known SHA512 answer copied from the provider's Events page:
# https://dev.digistore24.com/hc/en-us/articles/32480561422353-Events
DOCUMENTED_ORDER = {
    "event": "on_payment", "api_mode": "live", "order_id": "34DEFS45DE2",
    "email": "claus@domain-xyz.com", "buyer_id": "333222", "product_id": "3323323",
    "product_name": "Fast wealth guide", "transaction_id": "3999938",
    "transaction_amount": "37.99", "transaction_currency": "USD",
}


def signed_form(params, secret="xxxxx"):
    import hashlib
    from urllib.parse import urlencode
    text = "".join(f"{key}={params[key]}{secret}" for key in sorted(params) if params[key] != "")
    return urlencode({**params, "sha_sign": hashlib.sha512(text.encode()).hexdigest().upper()}).encode()


def test_provider_known_sha512_answer():
    from urllib.parse import urlencode
    params = {"buyer_email": "claus@domain-xyz.de", "payment_id": "PAYID-39-22012", "order_id": "273732",
              "transaction_amount": "17.00", "transaction_currency": "USD",
              "sha_sign": "342770076245D14ED7DF4D2E5D82216D7EDF8F9E7969B5964C9C5DCB53E962BBECD545E90422B5329C69554FD8B1A7E7410736615FCA7FB5CBB3624CC016E4BC"}
    body = urlencode(params).encode()
    assert native.Digistore24Node.verify_webhook_signature(body, {}, {"signing_secret": "xxxxx"})
    assert not native.Digistore24Node.verify_webhook_signature(body.replace(b"17.00", b"18.00"), {}, {"signing_secret": "xxxxx"})
    assert not native.Digistore24Node.verify_webhook_signature(body, {}, {"signing_secret": "wrong"})
    assert not native.Digistore24Node.verify_webhook_signature(body, {}, {})
    assert not native.Digistore24Node.verify_webhook_signature(body + b"&order_id=other", {}, {"signing_secret": "xxxxx"})


@pytest.mark.parametrize("event", native.ORDER_EVENTS)
@pytest.mark.asyncio
async def test_all_documented_order_events_reach_agent(event):
    payload = {**DOCUMENTED_ORDER, "event": event, "sha_sign": "signature", "_webhook": {"id": "internal"}}
    config = {"operation": "on_order_event", "event_type": event, "_triggerPayload": payload}
    instance = node(config)
    assert native.Digistore24Node.filter_trigger_payload(payload, config)
    result = await instance.execute({"unrelated_run_input": "never forwarded"})
    assert result == native.Digistore24Node.resolve_trigger_payload(payload, config)
    assert "sha_sign" not in str(result) and "_webhook" not in str(result)
    assert "unrelated_run_input" not in str(result)
    agent = native.Digistore24Node.resolve_agent_event(result)
    for text in (native.ORDER_EVENTS[event][1], "claus@domain-xyz.com", "34DEFS45DE2", "3999938", "333222", "3323323", "37.99", "USD"):
        assert text in agent["text"]
    assert not native.Digistore24Node.filter_trigger_payload({"event": "on_affiliation"}, config)


def test_connection_test_requires_valid_signature_and_returns_plain_ok():
    cls = native.Digistore24Node
    config = {"signing_secret": "xxxxx"}
    params = {"event": "connection_test", "ipn_version": "1.2", "api_mode": "test", "merchant_id": "39499382", "merchant_name": "JohnSmith"}
    response = cls.handle_webhook_handshake(signed_form(params), {}, config)
    assert response.body == b"OK" and response.media_type == "text/plain"
    assert cls.handle_webhook_handshake(b"event=connection_test", {}, config) is None
    assert cls.handle_webhook_handshake(signed_form(DOCUMENTED_ORDER), {}, config) is None
    assert cls.webhook_ack_response() == {"content": "OK", "media_type": "text/plain"}


@pytest.mark.asyncio
async def test_ipn_register_delete_exact_contract_and_unique_scope(monkeypatch):
    requests = transport(monkeypatch, {"result": "success"})
    cls = native.Digistore24Node
    creds = {"api_key": KEY}
    registered = await cls._register_external_webhook(webhook_url="https://one.hooks.example.test", credential=creds,
        config={"operation": "on_order_event", "event_type": "on_refund", "product_ids": "3323323"}, node_id="same-node")
    body = json.loads(requests[0].content)
    assert requests[0].method == "POST" and requests[0].url.path == "/api/call/ipnSetup"
    assert body == {"ipn_url": "https://one.hooks.example.test", "name": "NoClick order events", "product_ids": "3323323",
                    "domain_id": registered["external_webhook_id"], "categories": "orders", "transactions": "refund",
                    "timing": "delayed", "sha_passphrase": registered["signing_secret"]}
    assert len(registered["signing_secret"]) == 60
    other = await cls._register_external_webhook(webhook_url="https://two.hooks.example.test", credential=creds,
        config={"operation": "on_order_event"}, node_id="same-node")
    assert other["external_webhook_id"] != registered["external_webhook_id"]
    await cls._unregister_external_webhook(credential=creds, config=registered, node_id="same-node")
    assert requests[-1].method == "DELETE" and requests[-1].url.path == "/api/call/ipnDelete"
    assert dict(requests[-1].url.params) == {"domain_id": registered["external_webhook_id"]}
    assert cls.registration_fingerprint_fields({"event_type": "on_refund", "product_ids": "3323323"}) == {
        "event_type": "on_refund", "product_ids": "3323323"}


@pytest.mark.asyncio
async def test_rejected_ipn_registration_never_looks_successful(monkeypatch):
    transport(monkeypatch, {"result": "error", "message": "Permission denied"})
    with pytest.raises(ValueError, match="rejected"):
        await native.Digistore24Node._register_external_webhook(webhook_url="https://one.hooks.example.test",
            credential={"api_key": KEY}, config={"operation": "on_order_event"}, node_id="node")


@pytest.mark.parametrize("products", ["", "0", "all,123", "1, 2", "1,", "-1"])
def test_trigger_product_scope_validation(products):
    with pytest.raises(ValidationError):
        native.Digistore24OnOrderEventConfig(product_ids=products)
