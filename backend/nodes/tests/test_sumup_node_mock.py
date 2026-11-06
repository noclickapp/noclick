"""Every SumUp operation against sourced OpenAPI responses.

Source: https://raw.githubusercontent.com/sumup/sumup-developer/240a391e1c6c2b1d55d3803b0a22ba09958ef877/openapi.json
Whole-response examples are copied verbatim. Customer, merchant and membership
fixtures assemble documented property examples; saved cards use the component
example. Tests use no live account credentials or network calls.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.sumup_node import SumUpNode, SumUpNodeConfig

FIXTURES = json.loads((Path(__file__).parent / "fixtures/sumup/responses.json").read_text())
KEY = "sumup-test-secret"


def node(config):
    return SumUpNode(node_id="sumup-test", node_type="automation-sumup", node_data={}, sio=Mock(),
                     config=SumUpNodeConfig(config=config, credentials={"api_key": KEY}))


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr("nodes.sumup_node.httpx.AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler), trust_env=False))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_documented_operation(monkeypatch, operation):
    f = FIXTURES[operation]
    seen = []

    def respond(request):
        seen.append(request)
        assert request.method == f["method"]
        assert request.url.host == "api.sumup.com"
        assert request.url.path == f["path"]
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.headers["accept"] == "application/json"
        assert KEY not in str(request.url)
        assert {k: request.url.params.get_list(k) for k in request.url.params} == f["query"]
        if f["request_body"] is None:
            assert request.content == b""
        else:
            assert request.headers["content-type"] == "application/json"
            assert json.loads(request.content) == f["request_body"]
        return httpx.Response(204) if f["status_code"] == 204 else httpx.Response(f["status_code"], json=f["body"])

    mock_http(monkeypatch, respond)
    result = await node({"operation": operation, **f["config"]}).execute({})
    assert len(seen) == 1
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["status_code"] == f["status_code"]
    expected = f["body"] if f["body"] is not None else {"success": True}
    collection = {"list_checkouts": "checkouts", "list_payment_instruments": "payment_instruments", "list_payouts": "payouts"}.get(operation)
    if collection:
        expected = {collection: expected}
    assert result["data"] == expected
    assert result["timing_ms"]["total"] >= result["timing_ms"]["api_request"] >= 0


def test_fixture_coverage_equals_schema():
    schema = SumUpNode.get_config_schema()
    configs = schema["properties"]["config"]["oneOf"]
    operations = {schema["$defs"][c["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for c in configs}
    assert operations == set(FIXTURES)


@pytest.mark.asyncio
@pytest.mark.parametrize("amount,body", [(None, {}), (5, {"amount": 5})])
async def test_full_or_partial_refund(monkeypatch, amount, body):
    def respond(request):
        assert json.loads(request.content) == body
        return httpx.Response(201, json={})
    mock_http(monkeypatch, respond)
    config = {"operation": "refund_transaction", "merchant_code": "MH4H92C7", "transaction_id": "transaction"}
    if amount is not None:
        config["amount"] = amount
    assert (await node(config).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_update_customer_omits_unsupplied_details(monkeypatch):
    def respond(request):
        assert json.loads(request.content) == {"personal_details": {"email": "user@example.com"}}
        return httpx.Response(200, json=FIXTURES["update_customer"]["body"])
    mock_http(monkeypatch, respond)
    await node({"operation": "update_customer", "customer_id": "831ff8d4cd5958ab5670", "email": "user@example.com"}).execute({})


@pytest.mark.asyncio
async def test_hosted_checkout_false_is_preserved(monkeypatch):
    def respond(request):
        assert json.loads(request.content)["hosted_checkout"] == {"enabled": False}
        return httpx.Response(201, json=FIXTURES["create_checkout"]["body"])
    mock_http(monkeypatch, respond)
    assert (await node({"operation": "create_checkout", **FIXTURES["create_checkout"]["config"], "hosted_checkout": False}).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_csv_filters_are_trimmed_and_blanks_omitted(monkeypatch):
    def respond(request):
        assert "statuses[]" not in request.url.params
        assert request.url.params.get_list("types[]") == ["PAYMENT", "REFUND"]
        return httpx.Response(200, json=FIXTURES["list_transactions"]["body"])
    mock_http(monkeypatch, respond)
    await node({"operation": "list_transactions", "merchant_code": "MH4H92C7", "statuses": " , ", "types": " PAYMENT, REFUND "}).execute({})


@pytest.mark.asyncio
async def test_path_segments_are_escaped(monkeypatch):
    def respond(request):
        assert request.url.raw_path == b"/v0.1/customers/customer%2Fid/payment-instruments/token%2F%3F%23"
        return httpx.Response(204)
    mock_http(monkeypatch, respond)
    await node({"operation": "deactivate_payment_instrument", "customer_id": "customer/id", "token": "token/?#"}).execute({})


@pytest.mark.asyncio
async def test_merchant_picker_uses_account_resources_and_paginates(monkeypatch):
    def respond(request):
        assert request.url.path == "/v0.1/memberships"
        assert dict(request.url.params) == {"offset": "1", "limit": "25"}
        return httpx.Response(200, json=FIXTURES["list_memberships"]["body"])
    mock_http(monkeypatch, respond)
    result = await SumUpNode.load_field_options("merchant_code", {"api_key": KEY}, page_token="1", search="ACME")
    assert result == {"options": [{"value": "M2DDT39A", "label": "Acme Corp"}], "next_page_token": "2"}
    assert await SumUpNode.load_field_options("unknown", {"api_key": KEY}) == {"options": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"items": [], "total_count": 0}, {"items": [{"id": "fake"}], "total_count": 1}])
async def test_merchant_picker_shape_validation(monkeypatch, body):
    mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    if body == {"items": [], "total_count": 0}:
        assert await SumUpNode.load_field_options("merchant_code", {"api_key": KEY}) == {"options": [], "next_page_token": None}
    else:
        with pytest.raises(ValueError, match="invalid"):
            await SumUpNode.load_field_options("merchant_code", {"api_key": KEY})


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 429, 500])
async def test_provider_errors_preserved_and_secrets_redacted(monkeypatch, code):
    # Problem detail schema from the pinned spec. Preserve the provider's
    # rejection text unless it echoes the credential.
    mock_http(monkeypatch, lambda r: httpx.Response(code, json={"detail": f"Unauthorized. {KEY}"}))
    result = await node({"operation": "list_memberships"}).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == code
    assert result["error"] == "Unauthorized. [redacted]"
    assert KEY not in json.dumps(result)
    with pytest.raises(ValueError, match="Unauthorized"):
        await SumUpNode.load_field_options("merchant_code", {"api_key": KEY})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "invalid_auth"}, {"errors": ["invalid_auth"]}, {"status": "failed"}])
async def test_200_error_envelope_is_not_connection_evidence(monkeypatch, body):
    mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    assert (await node({"operation": "list_memberships"}).execute({}))["status"] == "error"
    with pytest.raises(ValueError):
        await SumUpNode.load_field_options("merchant_code", {"api_key": KEY})


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "network", "html", "scalar"])
async def test_bad_responses_are_structured(monkeypatch, kind):
    def respond(request):
        if kind == "timeout":
            raise httpx.ReadTimeout(f"secret {KEY}", request=request)
        if kind == "network":
            raise httpx.ConnectError(f"secret {KEY}", request=request)
        return httpx.Response(200, text="<html>Sign in</html>") if kind == "html" else httpx.Response(200, json="unexpected")
    mock_http(monkeypatch, respond)
    result = await node({"operation": "list_memberships"}).execute({})
    assert result["status"] == "error"
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize("config", [
    {"operation": "refund_transaction", "merchant_code": "MH4H92C7", "transaction_id": "id", "amount": 0},
    {"operation": "get_payment_methods", "merchant_code": "MH4H92C7", "amount": 5},
    {"operation": "list_payouts", "merchant_code": "MH4H92C7", "start_date": "2024-02-29", "end_date": "2024-02-01"},
    {"operation": "list_memberships", "limit": 26},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises(ValidationError):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,reachable", [
    (200, FIXTURES["list_memberships"]["body"], True),
    (200, {"items": [], "total_count": 0}, True),
    (401, {"detail": "Unauthorized."}, False),
    (403, {"detail": "Forbidden."}, False),
    (200, {}, None),
])
async def test_real_connection_evidence_seam(monkeypatch, status, body, reachable):
    from nodes.core.connection_evidence import collect_evidence
    mock_http(monkeypatch, lambda r: httpx.Response(status, json=body))
    evidence = await collect_evidence(node_type="automation-sumup", user_id="test", credential_data={"api_key": KEY})
    assert evidence.reachable is reachable
    if status == 200 and body.get("items"):
        assert evidence.samples[0].label == "Acme Corp"
        assert evidence.samples[0].value == "M2DDT39A"
        assert evidence.answers_field == "merchant_code"
    if status in (401, 403):
        assert body["detail"] in evidence.error


@pytest.mark.asyncio
async def test_missing_credentials_refused_before_network():
    instance = node({"operation": "list_memberships"})
    instance.config.credentials = None
    with pytest.raises(ValueError, match="Connect a SumUp API key"):
        await instance.execute({})
