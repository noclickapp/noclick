"""InvoiceXpress transport and factory regressions; no live credentials used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import invoicexpress_node as native
from nodes.core.registry import NodeFactory

KEY = "test-invoicexpress-key+a&b/?="
CREDENTIAL = {"credential_type": "invoicexpress_api_key", "account_name": "example", "api_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="invoicexpress-test", node_type="automation-invoicexpress",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200):
    calls = []
    def reply(request):
        calls.append(request)
        if body is None:
            return httpx.Response(status, content=b"")
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
async def test_invoicexpress_documented_client_factory_and_query_auth(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/invoicexpress/client.json").read_text())
    calls = transport(monkeypatch, fixture["body"])
    result = await node({"operation": "get_client", "client_id": 12345}).execute({})
    assert result["client"] == fixture["body"]["client"]
    assert calls[0].method == "GET"
    assert calls[0].url.host == "example.app.invoicexpress.com"
    assert calls[0].url.path == "/clients/12345.json"
    assert calls[0].url.params["api_key"] == KEY
    assert "Authorization" not in calls[0].headers
    assert KEY not in str(result)


CASES = [
    ({"operation": "create_invoice", "invoice": {"date": "22/11/2025", "client": {"id": 1310176}, "items": [{"name": "Consulting", "unit_price": 50, "quantity": 2}], "proprietary_uid": "uuid-123"}}, "POST", "/invoices.json", "invoice", {"invoice": {"id": 1050}}),
    ({"operation": "update_invoice", "document_id": 1050, "invoice": {"items": [{"name": "Consulting", "unit_price": 50, "quantity": 2}]}}, "PUT", "/invoices/1050.json", "invoice", {"invoice": {"id": 1050}}),
    ({"operation": "change_invoice_state", "document_id": 1050, "invoice": {"state": "canceled", "message": "Wrong value"}}, "PUT", "/invoices/1050/change-state.json", "invoice", {"invoice": {"id": 1050}}),
    ({"operation": "send_invoice_email", "document_id": 1050, "message": {"client": {"email": "dest@mail.com", "save": "0"}, "subject": "Invoice", "body": "Attached."}}, "PUT", "/invoices/1050/email-document.json", "message", None),
    ({"operation": "generate_payment", "document_id": 1050, "partial_payment": {"amount": 10, "payment_mechanism": "TB", "payment_date": "22/11/2025"}}, "POST", "/documents/1050/partial_payments.json", "partial_payment", {"receipt": {"id": 1051}}),
    ({"operation": "create_client", "client": {"name": "Client Name", "code": "12345"}}, "POST", "/clients.json", "client", {"client": {"id": 12345}}),
    ({"operation": "update_client", "client_id": 12345, "client": {"name": "Client Name", "code": "12345", "email": "foo@bar.com"}}, "PUT", "/clients/12345.json", "client", None),
    ({"operation": "create_item", "item": {"name": "Item name", "unit_price": 9.99}}, "POST", "/items.json", "item", {"item": {"id": 12345}}),
    ({"operation": "update_item", "item_id": 12345, "item": {"name": "Item name", "unit_price": 9.99}}, "PUT", "/items/12345.json", "item", None),
    ({"operation": "delete_item", "item_id": 12345}, "DELETE", "/items/12345.json", None, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,wrapper,response", CASES)
async def test_invoicexpress_writes_preserve_body_wrappers(monkeypatch, config, method, path, wrapper, response):
    calls = transport(monkeypatch, response, 201 if method == "POST" else 200)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    req = calls[0]
    assert (req.method, req.url.path) == (method, path)
    assert dict(req.url.params) == {"api_key": KEY}
    if wrapper:
        assert json.loads(req.content) == {wrapper: config[wrapper]}
        assert req.headers["content-type"] == "application/json"
    else:
        assert not req.content


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,wrapper", [("list_clients", "clients"), ("list_items", "items"), ("list_invoices", "invoices")])
async def test_invoicexpress_lists_return_single_page_and_pagination(monkeypatch, operation, wrapper):
    body = {wrapper: [], "pagination": {"current_page": 2, "total_pages": 3, "per_page": 10}}
    calls = transport(monkeypatch, body)
    result = await node({"operation": operation, "page": 2, "per_page": 10}).execute({})
    assert result[wrapper] == [] and result["pagination"] == body["pagination"]
    assert dict(calls[0].url.params) == {"api_key": KEY, "page": "2", "per_page": "10"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_invoicexpress_exact_name_lookup_encoding_and_pending_pdf(monkeypatch):
    calls = transport(monkeypatch, {"client": {"id": 12345}})
    await node({"operation": "find_client_by_name", "client_name": "Client + A & B"}).execute({})
    assert calls[0].url.params["client_name"] == "Client + A & B"
    calls = transport(monkeypatch, {"output": {"id": 1050, "status": "queued"}}, 202)
    result = await node({"operation": "generate_pdf", "document_id": 1050}).execute({})
    assert result["output"]["status"] == "queued"
    assert calls[0].url.params["second_copy"] == "false"


@pytest.mark.parametrize("account", ["example.evil.test", "x/../y", "https://example.app.invoicexpress.com", "a@evil.test", "-example", "example:443", "a?x=1"])
def test_invoicexpress_credential_rejects_host_injection(account):
    with pytest.raises(ValidationError):
        native.InvoiceXpressCredential.model_validate({**CREDENTIAL, "account_name": account})


def test_invoicexpress_manual_type_default_and_required_body_fields():
    credential = native.InvoiceXpressCredential(account_name=" Example ", api_key=KEY)
    assert credential.credential_type == "invoicexpress_api_key"
    assert credential.account_name == "example"
    for config in [
        {"operation": "create_invoice", "invoice": {"items": []}},
        {"operation": "create_client", "client": {"name": "Client"}},
        {"operation": "create_item", "item": {"name": "Item"}},
        {"operation": "get_client", "client_id": -1},
        {"operation": "list_clients", "page": 0},
    ]:
        with pytest.raises(ValueError):
            node(config)


@pytest.mark.asyncio
async def test_invoicexpress_invalid_date_and_cancellation_reason_never_send(monkeypatch):
    calls = transport(monkeypatch, {})
    for config in [
        {"operation": "create_invoice", "invoice": {"date": "31/02/2025", "items": [{"name": "Consulting", "quantity": 2, "unit_price": 50}]}},
        {"operation": "change_invoice_state", "document_id": 1050, "invoice": {"state": "canceled"}},
    ]:
        with pytest.raises(ValueError):
            await node(config).execute({})
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": "Access denied"}), (302, {}), (200, {"errors": ["Invalid key"]}), (200, {}), (200, {"client": []})])
async def test_invoicexpress_errors_and_missing_resource_do_not_prove_connection(monkeypatch, status, body):
    calls = transport(monkeypatch, body, status)
    with pytest.raises(ValueError):
        await node({"operation": "get_client", "client_id": 12345}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_invoicexpress_network_and_provider_errors_do_not_leak_query_key(monkeypatch):
    def client(**kwargs):
        def reply(request):
            raise httpx.ConnectError(f"failed: {request.url}", request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_clients"}).execute({})
    assert KEY not in str(exc.value) and "api_key" not in str(exc.value)
    transport(monkeypatch, {"error": KEY}, 401)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_clients"}).execute({})
    assert KEY not in str(exc.value)
