"""Verify FacturaDirecta's native node against provider-authored request examples.

The HTTP boundary is mocked; credentials and response fixtures are synthetic.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import facturadirecta_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

TOKEN = "synthetic-facturadirecta-key"
CREDENTIAL = {"credential_type": "facturadirecta_api_key", "api_key": TOKEN, "company_id": "company-example"}
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/facturadirecta/request_examples.json").read_text())["examples"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="facturadirecta-test", node_type="automation-facturadirecta",
        node_data={"config": config, "credentials": CREDENTIAL})


def mock_http(monkeypatch, callback):
    requests = []
    def respond(request):
        requests.append(request)
        return callback(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config_for(operation):
    method, route, kind = native.ROUTES[operation]
    config = {"operation": operation}
    if "{id}" in route:
        config["id"] = "resource-example"
    if kind:
        config.update(EXAMPLES[route.split('/')[0]])
        config["main"] = config.pop("content")["main"]
    if operation == "create_invoice_payments":
        config["payments"] = [{"bank": "ban_example", "amount": 100}]
    if method != "GET":
        config["idempotency_key"] = "source-record-123456"
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.ROUTES))
async def test_every_operation_sends_one_documented_request(monkeypatch, operation):
    method, route, kind = native.ROUTES[operation]
    config = config_for(operation)
    def reply(request):
        if operation.startswith("list_"):
            return httpx.Response(200, json={"items": [], "pagination": {"limit": 100, "offset": 0, "total": 0}})
        return httpx.Response(200, json={"scopes": ["contacts:read"]} if operation == "check_api_key" else {"content": {"type": kind or "invoice"}})
    requests = mock_http(monkeypatch, reply)
    result = await node(config).run({})
    assert result["success"] is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split('?')[0] == native.BASE_URL + "/company-example/" + route.replace("{id}", "resource-example")
    assert request.headers["facturadirecta-api-key"] == TOKEN
    assert request.headers["accept-version"] == "1.0.10"
    assert "authorization" not in request.headers
    if method != "GET":
        assert request.headers["Idempotency-Key"] == config["idempotency_key"]
        assert result["write_acknowledged"] is True
    if kind:
        assert json.loads(request.content) == {"content": {"type": kind, "main": config["main"]}}
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"limit": "100", "offset": "0"}
        assert result["next_offset"] is None
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_search_pagination_and_contact_evidence_labels(monkeypatch):
    body = {"items": [{"id": "con_1", "content": {"main": {"name": "Acme SL"}}}],
            "pagination": {"limit": 1, "offset": 3, "total": 7}}
    requests = mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    result = await node({"operation": "list_contacts", "limit": 1, "offset": 3, "search": "café + client"}).run({})
    assert result["next_offset"] == 4 and result["items"][0]["title"] == "Acme SL"
    assert requests[0].url.params["search"] == "café + client"
    assert result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 409, 422, 429, 500])
async def test_rejections_never_retry_or_report_success_and_redact_key(monkeypatch, status):
    requests = mock_http(monkeypatch, lambda r: httpx.Response(status, text="Rejected " + TOKEN, headers={"Location": "https://example.org"}))
    result = await node(config_for("create_invoice")).run({})
    assert result["success"] is False and result["http_status"] == status
    assert result["status"] == ("unknown" if status >= 500 else "error")
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_has_unknown_write_outcome(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("lost response", request=request)
    requests = mock_http(monkeypatch, timeout)
    result = await node(config_for("create_invoice_payments")).run({})
    assert result["status"] == "unknown" and not result["success"]
    assert "unverified" in result["write_outcome"] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"error": "rejected"}, {"items": [], "pagination": {"limit": 100, "offset": 0, "total": 1}}])
async def test_bad_list_envelopes_are_errors(monkeypatch, body):
    mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    result = await node({"operation": "list_contacts"}).run({})
    assert not result["success"] and result["status"] == "error"


@pytest.mark.asyncio
async def test_explicit_null_receipt_supplier_and_payment_amount_rule(monkeypatch):
    requests = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"content": {"type": "bill"}}))
    await node({"operation": "create_bill", "main": {"contact": None, "currency": "EUR", "lines": [{"text": "Receipt"}]}}).run({})
    assert json.loads(requests[0].content)["content"]["main"]["contact"] is None
    with pytest.raises(ValueError, match="final payment"):
        native.CreateInvoicePayments(id="inv_1", payments=[{"bank": "ban_1"}, {"bank": "ban_1", "amount": 1}])


def test_manual_connect_fields_and_secret_shape():
    shaped, errors, resolved = shape_credential("facturadirecta_api_key", {"api_key": TOKEN, "company_id": "company-example"})
    assert not errors and resolved[0] == "automation-facturadirecta"
    assert native.FacturaDirectaAPIKeyCredential.model_validate(shaped).credential_type == "facturadirecta_api_key"
    for field, value in [("company_id", "../other"), ("company_id", "https://example.org"), ("api_key", "https://example.org"), ("api_key", "bad\nheader")]:
        with pytest.raises(ValidationError):
            native.FacturaDirectaAPIKeyCredential(**{**CREDENTIAL, field: value})


@pytest.mark.parametrize("config", [
    {"operation": "get_invoice", "id": "../invoices"},
    {"operation": "create_contact", "main": {"name": "Missing accounting"}},
    {"operation": "create_invoice", "main": {"lines": []}},
    {"operation": "list_contacts", "limit": 501},
    {"operation": "delete_product", "id": "pro_1", "idempotency_key": "has spaces in it"},
])
def test_invalid_required_fields_and_routes_refused(config):
    with pytest.raises(ValueError):
        node(config)
