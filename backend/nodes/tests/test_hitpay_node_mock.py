"""Native factory tests using published examples and an isolated HTTP transport."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hitpay_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-hitpay-business-key"
ID = "3c90c3cc-0d44-4b50-8888-8dd25736052a"
CONTRACT = json.loads((Path(__file__).parent / "fixtures/hitpay/contract.json").read_text())
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/hitpay/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(node_id="hitpay-test", node_type="automation-hitpay",
        node_data={"config": {"operation": operation, **fields},
            "credentials": {"credential_type": "hitpay_api_key", "api_key": KEY}})


def transport(monkeypatch, status=200, body=None, error=None, empty=False):
    requests = []
    def respond(request):
        requests.append(request)
        if error:
            raise error
        if empty:
            return httpx.Response(status, content=b"")
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONTRACT["operations"])
async def test_one_contract_operation_per_factory_execution(monkeypatch, operation):
    contract = CONTRACT["operations"][operation]
    method, path, ids, body_fields = (contract[key] for key in ("method", "path", "path_fields", "body_fields"))
    config = {field: ID for field in ids}
    if operation in {"create_payment_request", "update_payment_request"}:
        config.update(currency="SGD", amount=100, payment_methods=["card"], send_email="false", generate_qr=False)
    if operation == "create_customer":
        config.update(email="test@example.com", phone_number="91234567", name="John Doe")
    if operation == "update_customer":
        config.update(name="John Doe")
    if operation == "create_refund":
        config.update(amount=100.99, payment_id=ID)
    example = EXAMPLES.get(operation, {"status": 204 if operation == "delete_customer" else 200, "body": {"data": []}})
    requests = transport(monkeypatch, example["status"], example["body"])
    result = await node(operation, **config).run({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.hit-pay.com"
    for field in ids:
        path = path.replace("{" + field + "}", ID)
    assert request.url.path == path
    assert request.headers["X-BUSINESS-API-KEY"] == KEY
    assert request.headers["X-Requested-With"] == "XMLHttpRequest"
    if body_fields:
        assert json.loads(request.content) == {k: v for k, v in config.items() if k in body_fields}
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_paging_filters_and_nested_evidence(monkeypatch):
    body = {"data": [{"id": ID, "name": "John Doe"}], "meta": {"next_cursor": "next+page"}}
    requests = transport(monkeypatch, body=body)
    result = await node("list_customers", cursor="old+page", per_page=25).run({})
    assert dict(requests[0].url.params) == {"cursor": "old+page", "per_page": "25"}
    assert result["data"] == body and result["items"] == body["data"]
    assert native.HitpayNode.connection_evidence.operation == "list_customers"


@pytest.mark.asyncio
async def test_sandbox_and_repeated_query_filters(monkeypatch):
    requests = transport(monkeypatch, body={"data": []})
    n = node("list_charges", user_ids=["one", "two"], status="succeeded", date_from="2024-10-05")
    n.config.credentials.environment = "sandbox"
    await n.run({})
    assert requests[0].url.host == "api.sandbox.hit-pay.com"
    assert requests[0].url.params.get_list("user_ids") == ["one", "two"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 422, 429, 500])
async def test_errors_do_not_leak_key_or_follow_redirect(monkeypatch, status):
    requests = transport(monkeypatch, status, {"message": "Rejected " + KEY})
    result = await node("list_customers").run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_not_retried(monkeypatch):
    requests = transport(monkeypatch, error=httpx.ReadTimeout("private details"))
    result = await node("create_refund", amount=1, payment_id=ID).run({})
    assert result["status"] == "error" and result["outcome_unknown"] is True
    assert "private details" not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_rejected(monkeypatch):
    transport(monkeypatch, body={"success": False, "message": "Provider refused"})
    assert (await node("list_customers").run({}))["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "get_payment_request", "request_id": "../elsewhere"},
    {"operation": "create_payment_request", "currency": "SGD", "payment_methods": ["wifi_card_reader"]},
    {"operation": "create_customer", "email": "test@example.com"},
    {"operation": "create_refund", "payment_id": ID},
    {"operation": "list_customers", "per_page": 7},
    {"operation": "unknown"},
])
def test_required_fields_enums_and_path_validation(config):
    with pytest.raises((ValueError, ValidationError)):
        native.HitpayNode.parse_config({"config": config})


@pytest.mark.parametrize("key", ["https://example.com/key", "<your-key>", "two words", "header\r\ninjection"])
def test_invalid_key_is_hidden(key):
    with pytest.raises(ValidationError) as exc:
        native.HitpayAPIKeyCredential(api_key=key)
    assert key not in str(exc.value)


@pytest.mark.asyncio
async def test_empty_read_does_not_prove_a_connection(monkeypatch):
    transport(monkeypatch, empty=True)
    result = await node("list_customers").run({})
    assert result["status"] == "error" and "empty read" in result["error"]


@pytest.mark.asyncio
async def test_documented_empty_update_response_is_success(monkeypatch):
    transport(monkeypatch, empty=True)
    result = await node("update_payment_request", request_id=ID, amount=100, currency="SGD").run({})
    assert result == {"status": "success", "data": None}
