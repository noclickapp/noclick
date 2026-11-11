"""Published HassleFreeBooks examples exercise writes, connection proof and deliveries."""
import copy
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.registry import NodeFactory
from nodes.hasslefreebooks_node import (
    HassleFreeBooksAPIKeyCredential, HassleFreeBooksNode, HassleFreeBooksNodeConfig,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hasslefreebooks"
EXAMPLES = json.loads((FIXTURES / "api-examples.json").read_text())
EVENT = json.loads((FIXTURES / "invoice-paid.json").read_text())["body"]
CREDENTIAL = {"credential_type": "hasslefreebooks_api_key", "api_key": "hfb_unit_test_0123456789"}


def node(config):
    return NodeFactory.create_node(node_id="hfb-test", node_type="automation-hasslefreebooks",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    def client(*args, **kwargs):
        assert kwargs.get("follow_redirects") is False
        return original(*args, **kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr("nodes.hasslefreebooks_node.httpx.AsyncClient", client)


@pytest.mark.asyncio
async def test_account_identity_uses_authenticated_me(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://hasslefreebooks.com/api/v1/me"
        assert request.headers["authorization"] == "Bearer " + CREDENTIAL["api_key"]
        return httpx.Response(200, json=EXAMPLES["getCurrentUser"]["response"])
    transport(monkeypatch, handler)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["data"]["user"]["name"] == "John Doe"
    assert result["data"]["entities"][0]["name"] == "My Business"


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture,operation", [
    ("createContact", "create_contact"), ("createInvoiceRest", "create_invoice"),
    ("createTransaction", "create_transaction"), ("payBill", "pay_bill"),
])
async def test_published_write_examples(monkeypatch, fixture, operation):
    example = EXAMPLES[fixture]
    config = {"operation": operation, **copy.deepcopy(example["request"])}
    if operation == "create_invoice":
        config.pop("subtotal")
        config.pop("total")
    if operation == "pay_bill":
        config["id"] = 1
    def handler(request):
        assert request.method == example["method"]
        assert request.url.path == example["path"].replace("{id}", "1")
        body = json.loads(request.content)
        assert body == {k: v for k, v in config.items() if k not in {"operation", "id"}}
        if operation == "create_invoice":
            assert set(body) == {"contact_id", "invoice_date", "due_date", "invoice_number", "notes", "lines"}
        return httpx.Response(example["status"], json=example["response"])
    transport(monkeypatch, handler)
    result = await node(config).execute({})
    assert result["data"] == example["response"]["data"]


@pytest.mark.asyncio
async def test_record_payment_parses_published_response_despite_invalid_spec_security(monkeypatch):
    """The spec's security contains [] instead of {}; offline scope parsing fails before the response."""
    example = EXAMPLES["recordInvoicePayment"]
    def handler(request):
        assert request.url.path == "/api/v1/invoices/record-payment"
        assert request.headers["authorization"].startswith("Bearer hfb_")
        assert json.loads(request.content) == {
            "invoice_id": 961003, "amount": 100.0, "payment_date": "2026-01-15", "deposit_account_id": 12}
        return httpx.Response(200, json=example["response"])
    transport(monkeypatch, handler)
    result = await node({"operation": "record_invoice_payment", "invoice_id": 961003,
        "amount": 100, "payment_date": "2026-01-15", "deposit_account_id": 12}).execute({})
    assert result["data"]["invoice_payment_id"] == 167
    assert result["data"]["status"] == "partial"


@pytest.mark.asyncio
async def test_paging_does_not_silently_override_page_with_default_offset(monkeypatch):
    def handler(request):
        assert request.url.params["page"] == "3"
        assert "offset" not in request.url.params
        return httpx.Response(200, json={"ok": True, "data": {"transactions": [], "pagination": {"page": 3}}})
    transport(monkeypatch, handler)
    result = await node({"operation": "list_transactions", "page": 3}).execute({})
    assert result["data"]["pagination"]["page"] == 3


@pytest.mark.asyncio
async def test_update_only_supplied_fields_including_clearable_null(monkeypatch):
    def handler(request):
        assert request.method == "PUT"
        assert request.url.path == "/api/v1/contacts/10"
        assert json.loads(request.content) == {"phone": None, "is_active": False}
        return httpx.Response(200, json={"ok": True, "data": {"contact": {"id": 10, "phone": None, "is_active": False}}})
    transport(monkeypatch, handler)
    result = await node({"operation": "update_contact", "id": 10, "phone": None, "is_active": False}).execute({})
    assert result["data"]["contact"]["is_active"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 409, 429])
async def test_rejection_never_becomes_connection_success(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, json={"ok": False,
        "error": {"code": "REJECTED", "message": "Provider rejection verbatim"}}))
    with pytest.raises(ValueError, match="Provider rejection verbatim|REJECTED"):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "update_contact", "id": 1},
    {"operation": "create_invoice", "contact_id": 10, "invoice_date": "2026-01-15", "lines": []},
    {"operation": "create_invoice", "contact_id": 10, "invoice_date": "2026-02-30", "lines": []},
    {"operation": "list_invoices", "per_page": 101},
])
def test_invalid_configs_fail_before_request(config):
    with pytest.raises(ValidationError):
        HassleFreeBooksNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL})


def test_unbalanced_and_non_decimal_journals_are_rejected():
    config = {"operation": "create_transaction", **copy.deepcopy(EXAMPLES["createTransaction"]["request"])}
    for invalid in ["99.00", "NaN", "nope", "-100.00"]:
        config["lines"][0]["debit_amount"] = invalid
        with pytest.raises(ValidationError):
            HassleFreeBooksNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL})


def test_api_key_is_manually_connectable_without_type_tag():
    key = HassleFreeBooksAPIKeyCredential.model_validate({"api_key": "  hfb_unit_test_0123456789  "})
    assert key.credential_type == "hasslefreebooks_api_key"
    assert key.api_key == CREDENTIAL["api_key"]
    for bad in ["https://hasslefreebooks.com/api-keys", "Bearer hfb_key", "wrong\nheader"]:
        with pytest.raises(ValidationError):
            HassleFreeBooksAPIKeyCredential.model_validate({"api_key": bad})


@pytest.mark.asyncio
async def test_webhook_lifecycle_uses_one_time_secret_and_deletes_its_endpoint(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            assert json.loads(request.content) == {"name": "NoClick invoice-flow",
                "url": "https://hooks.hooks.example.test/hfb", "event_types": ["invoice.paid"]}
            return httpx.Response(201, json={"ok": True, "data": {"endpoint": {"id": 12}, "secret": "a" * 64}})
        assert request.url.path == "/api/v1/webhooks/endpoints/12"
        return httpx.Response(200, json={"ok": True, "data": {"deleted": True, "id": 12}})
    transport(monkeypatch, handler)
    extra = await HassleFreeBooksNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/hfb",
        credential=CREDENTIAL, config={"event_type": "invoice.paid"}, node_id="invoice-flow")
    assert extra == {"external_webhook_id": "12", "signing_secret": "a" * 64}
    await HassleFreeBooksNode._unregister_external_webhook(credential=CREDENTIAL, config=extra, node_id="invoice-flow")
    assert calls == ["POST", "DELETE"]


def test_provider_signature_example_and_tampering():
    body = json.dumps(EVENT).encode()
    config = {"signing_secret": "20c3ac5f56dbb1a829b95e8b040d54ffeca6e1a4b2cf3305d869eb0a642189fa"}
    signature = "sha256=" + hmac.new(config["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    assert HassleFreeBooksNode.verify_webhook_signature(body, {"X-HassleFreBooks-Signature": signature}, config)
    assert HassleFreeBooksNode.verify_webhook_signature(body, {"x-hasslefrebooks-signature": signature}, config)
    assert not HassleFreeBooksNode.verify_webhook_signature(body + b" ", {"X-HassleFreBooks-Signature": signature}, config)
    assert not HassleFreeBooksNode.verify_webhook_signature(body, {"X-HassleFreBooks-Signature": "sha256=é"}, config)
    assert not HassleFreeBooksNode.verify_webhook_signature(body, {}, config)
    assert not HassleFreeBooksNode.verify_webhook_signature(body, {"X-HassleFreBooks-Signature": signature}, {})


def test_documented_event_filter_and_agent_turn():
    assert HassleFreeBooksNode.filter_trigger_payload(EVENT, {"event_type": "invoice.paid"})
    assert not HassleFreeBooksNode.filter_trigger_payload({**EVENT, "event": "bill.paid"}, {"event_type": "invoice.paid"})
    output = HassleFreeBooksNode.resolve_trigger_payload(EVENT, {})
    turn = HassleFreeBooksNode.resolve_agent_event(output)
    assert "Acme Landscaping LLC" in turn["text"]
    assert "INV-1042" in turn["text"]
    assert "77" in turn["text"]
    assert turn["conversation_key"] == "hasslefreebooks:7:invoice:1042"
    assert HassleFreeBooksNode.registration_fingerprint_fields({"event_type": "invoice.paid"}) == {"event_type": "invoice.paid"}


@pytest.mark.asyncio
async def test_manual_trigger_run_is_not_a_delivery():
    assert (await node({"operation": "on_event"}).execute({}))["status"] == "no_event"
