"""Wire-level tests for Royal Mail's published v1 contract (no live account)."""
from contextlib import asynccontextmanager
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory
from nodes import royalmail_node as rm

FIXTURES = Path(__file__).parent / "fixtures" / "royalmail"
CREDENTIAL = {"credential_type": "royalmail_api_token", "api_token": "unit-test-api-token"}


def node(config):
    return NodeFactory.create_node(node_id="royalmail-test", node_type="automation-royalmail",
                                   node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(rm, "guarded_async_client", client)


@pytest.mark.asyncio
async def test_provider_manifest_example_and_auth(monkeypatch):
    example = json.loads((FIXTURES / "manifest.json").read_text())["body"]
    def handle(request):
        assert str(request.url) == rm.BASE + "/manifests/1001"
        assert request.headers["Authorization"] == "Bearer unit-test-api-token"
        return httpx.Response(200, json=example)
    transport(monkeypatch, handle)
    assert await node({"operation": "get_manifest", "manifestIdentifier": 1001}).execute({}) == example


@pytest.mark.asyncio
async def test_provider_return_services_example(monkeypatch):
    example = json.loads((FIXTURES / "return_services.json").read_text())["body"]
    transport(monkeypatch, lambda request: httpx.Response(200, json=example))
    assert await node({"operation": "list_return_services"}).execute({}) == example


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,method,path", [
    ("list_orders", {"pageSize": 100, "continuationToken": "next"}, "GET", "/orders"),
    ("list_order_details", {}, "GET", "/orders/full"),
    ("get_orders", {"orderIdentifiers": '1001;"Reference;With/Special Symbols!"'}, "GET", '/orders/1001;%22Reference%3BWith%2FSpecial%20Symbols%21%22'),
    ("get_order_details", {"orderIdentifiers": "1001"}, "GET", "/orders/1001/full"),
    ("delete_orders", {"orderIdentifiers": "1001"}, "DELETE", "/orders/1001"),
    ("create_orders", {"items": [{"recipient": {"addressBookReference": "existing-recipient"}, "orderDate": "2026-11-10T12:00:00Z", "subtotal": 10, "shippingCostCharged": 2, "total": 12}]}, "POST", "/orders"),
    ("update_order_status", {"items": [{"orderIdentifier": 1001, "status": "despatched"}]}, "PUT", "/orders/status"),
    ("list_carriers", {}, "GET", "/carriers"),
    ("list_services", {"destinationCountryCode": "GBR", "destinationPostcode": "AB1 2CD"}, "GET", "/services"),
    ("manifest_orders", {"shippingAccountName": "Main Shipping Account"}, "POST", "/manifests"),
    ("retry_manifest", {"manifestIdentifier": 1001}, "POST", "/manifests/retry/1001"),
    ("list_olp_services", {"country": "GBR", "weight": 500}, "GET", "/services/olp"),
])
async def test_operation_wire(monkeypatch, operation, extra, method, path):
    captured = []
    def handle(request):
        captured.append(request)
        assert request.method == method
        assert request.url.raw_path.split(b"?")[0].decode() == "/api/v1" + path
        if method in {"POST", "PUT"} and operation != "retry_manifest":
            body = json.loads(request.content)
            assert set(body) == set(extra)
            assert "operation" not in body
        return httpx.Response(200, json={"ok": True})
    transport(monkeypatch, handle)
    await node({"operation": operation, **extra}).execute({})
    assert len(captured) == 1  # Mutations must not be retried automatically.
    if method == "GET":
        for key, value in extra.items():
            if key != "orderIdentifiers":
                assert captured[0].url.params[key] == str(value)


@pytest.mark.asyncio
async def test_label_is_binary_pdf(monkeypatch):
    pdf = b"%PDF-1.4\nprovider label\n%%EOF"
    def handle(request):
        assert request.url.params["documentType"] == "postageLabel"
        assert request.url.params["includeReturnsLabel"] == "false"
        return httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"})
    transport(monkeypatch, handle)
    result = await node({"operation": "get_labels", "orderIdentifiers": "1001"}).execute({})
    assert base64.b64decode(result["pdf_base64"]) == pdf


@pytest.mark.asyncio
async def test_rejection_preserves_provider_reason_without_token(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(401, text="Invalid token unit-test-api-token"))
    with pytest.raises(ValueError, match="Royal Mail API 401: Invalid token \\[redacted\\]"):
        await node({"operation": "list_carriers"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "update_order_status", "items": [{"orderIdentifier": 1, "orderReference": "ref", "status": "new"}]},
    {"operation": "update_order_status", "items": [{"orderIdentifier": 1, "status": "despatchedByOtherCourier", "trackingNumber": "abc"}]},
    {"operation": "list_services", "destinationCountryCode": "GBR"},
    {"operation": "list_services", "packageWeight": 500},
    {"operation": "get_orders", "orderIdentifiers": "../../carriers"},
])
def test_provider_constraints(config):
    with pytest.raises(ConfigValidationError):
        node(config)


@pytest.mark.asyncio
async def test_poll_exhausts_pages_before_dedup_and_emits_human_event(monkeypatch):
    # Synthetic rows use only fields declared by GetOrderInfoResource.
    rows = [{"orderIdentifier": 1001, "orderReference": "reference", "createdOn": "2026-11-10T12:00:00Z"}]
    throttle = AsyncMock()
    monkeypatch.setattr(rm.asyncio, "sleep", throttle)
    n = node({"operation": "on_new_order", "startDateTime": "2026-11-01T00:00:00Z"})
    n._filter_unseen = AsyncMock(return_value=rows)
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.params["startDateTime"] == "2026-11-01T00:00:00+00:00"
        if "continuationToken" not in request.url.params:
            return httpx.Response(200, json={"orders": rows, "continuationToken": "page-two"})
        assert request.url.params["continuationToken"] == "page-two"
        return httpx.Response(200, json={"orders": []})
    transport(monkeypatch, handle)
    result = await n.execute({})
    assert len(calls) == 2
    throttle.assert_awaited_once_with(0.21)
    assert result == {"orders": rows, "new_order_count": 1}
    n._filter_unseen.assert_awaited_once()
    event = rm.RoyalMailNode.resolve_agent_event(result)
    assert "reference" in event["text"] and "1001" in event["text"]
    assert rm.RoyalMailNode.should_propagate_output(result, {"operation": "on_new_order"})
    assert not rm.RoyalMailNode.should_propagate_output({"new_order_count": 0}, {"operation": "on_new_order"})


@pytest.mark.asyncio
async def test_poll_does_not_advance_seen_state_after_incomplete_page(monkeypatch):
    n = node({"operation": "on_new_order"})
    n._filter_unseen = AsyncMock()
    transport(monkeypatch, lambda request: httpx.Response(200, json={"orders": [], "continuationToken": "repeat"}))
    with pytest.raises(ValueError, match="repeated"):
        await n.execute({})
    n._filter_unseen.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_return_sends_documented_request_shape(monkeypatch):
    address = {"firstName": "Test", "lastName": "Recipient", "addressLine1": "1 High Street", "city": "London", "postcode": "SW1A 1AA", "country": "United Kingdom", "countryIsoCode": "GBR"}
    config = {"operation": "create_return", "service": {"serviceCode": "TSN"},
              "shipment": {"shippingAddress": address, "returnAddress": address, "customerReference": {"reference": "return-reference"}}}
    def handle(request):
        assert request.method == "POST"
        assert request.url.path == "/api/v1/returns"
        assert json.loads(request.content) == {k: v for k, v in config.items() if k != "operation"}
        return httpx.Response(200, json={"shipment": {"trackingNumber": "tracking", "uniqueItemId": "item"}, "qrCode": "base64", "label": "base64"})
    transport(monkeypatch, handle)
    result = await node(config).execute({})
    assert result["shipment"]["uniqueItemId"] == "item"


@pytest.mark.asyncio
async def test_connection_shows_account_shipping_name(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    carriers = [{"carrierGuid": "e90e87c8-4ea6-49ec-a387-64ba37f66d84", "shippingAccountName": "My shipping account"}]
    transport(monkeypatch, lambda request: httpx.Response(200, json=carriers))

    async def run_operation(**kwargs):
        assert kwargs["operation"] == "list_carriers"
        return await node({"operation": kwargs["operation"]}).execute({})

    monkeypatch.setattr("nodes.core.run_op.run_node_operation", run_operation)
    result = await collect_evidence(node_type="automation-royalmail", user_id="test", pool=None,
                                    credential_data=CREDENTIAL)
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ["My shipping account"]
