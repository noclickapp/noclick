"""HTTP and JWT checks with Shipmondo's official decoded event examples."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes.shipmondo_node import (
    BASE_URL,
    WEBHOOK_EVENTS,
    ShipmondoAPIKeyCredential,
    ShipmondoNode,
    ShipmondoNodeConfig,
    _decode_jwt,
)

CREDENTIAL = {
    "credential_type": "shipmondo_api_key",
    "api_username": "example-user",
    "api_key": "example-secret",
}
FIXTURES = Path(__file__).parent / "fixtures" / "shipmondo"


def node(config):
    return ShipmondoNode(
        node_id="test",
        node_type="automation-shipmondo",
        node_data={},
        config=ShipmondoNodeConfig.model_validate(
            {"config": config, "credentials": CREDENTIAL}
        ),
    )


def transport(monkeypatch, reply):
    requests = []
    original = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        assert (
            request.headers["authorization"]
            == "Basic " + base64.b64encode(b"example-user:example-secret").decode()
        )
        assert str(request.url).startswith(BASE_URL)
        return reply(request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handle), **kw),
    )
    return requests


@pytest.mark.asyncio
async def test_shipmondo_read_filters_and_pagination(monkeypatch):
    requests = transport(
        monkeypatch, lambda _: httpx.Response(200, json=[{"id": 11227}])
    )
    result = await node(
        {
            "operation": "list_sales_orders",
            "archived": False,
            "page": 2,
            "per_page": 25,
            "updated_at_min": "2024-07-08T10:08:58+02:00",
        }
    ).execute({})
    assert result["data"] == [{"id": 11227}]
    assert requests[0].url.path == "/api/public/v3/sales_orders"
    assert dict(requests[0].url.params) == {
        "archived": "false",
        "page": "2",
        "per_page": "25",
        "updated_at_min": "2024-07-08T10:08:58+02:00",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,method,path,body",
    [
        ({"operation": "get_account"}, "GET", "/account/", None),
        (
            {"operation": "get_shipment", "id": 123456789},
            "GET",
            "/shipments/123456789",
            None,
        ),
        (
            {"operation": "cancel_shipment", "id": 123456789},
            "PUT",
            "/shipments/123456789/cancel",
            None,
        ),
        (
            {"operation": "hold_sales_order", "id": 11227},
            "PUT",
            "/sales_orders/11227/hold",
            None,
        ),
        (
            {"operation": "resume_sales_order", "id": 11227},
            "PUT",
            "/sales_orders/11227/unhold",
            None,
        ),
        (
            {"operation": "create_sales_order_shipment", "id": 11227},
            "POST",
            "/sales_orders/11227/create_shipment",
            None,
        ),
        (
            {"operation": "update_sales_order_note", "id": 11227, "order_note": "Note"},
            "PUT",
            "/sales_orders/11227/order_note",
            {"order_note": "Note"},
        ),
        (
            {"operation": "create_item", "sku": "TS001-WH", "name": "T-Shirt"},
            "POST",
            "/items",
            {"sku": "TS001-WH", "name": "T-Shirt"},
        ),
        (
            {"operation": "update_item", "id": 12345678, "bin": "AB-001"},
            "PUT",
            "/items/12345678",
            {"bin": "AB-001"},
        ),
        (
            {
                "operation": "create_shipment",
                "payload": '{"product_code":"GLSDK_SD","own_agreement":false,"service_codes":"EMAIL_NT,SMS_NT","parcels":[{"weight":1000}]}',
            },
            "POST",
            "/shipments",
            {
                "product_code": "GLSDK_SD",
                "own_agreement": False,
                "service_codes": "EMAIL_NT,SMS_NT",
                "parcels": [{"weight": 1000}],
            },
        ),
    ],
)
async def test_shipmondo_exact_requests(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"id": 1}))
    await node(config).execute({})
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == "/api/public/v3" + path
    assert (json.loads(requests[0].content) if requests[0].content else None) == body


@pytest.mark.asyncio
async def test_shipmondo_rejection_preserves_text_without_credentials(monkeypatch):
    requests = transport(
        monkeypatch,
        lambda _: httpx.Response(401, json={"error": "Rejected example-secret"}),
    )
    with pytest.raises(ValueError, match=r"Rejected \[redacted\]"):
        await node({"operation": "get_account"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_shipment", "id": "../account"},
        {"operation": "get_shipment", "id": 0},
        {"operation": "list_sales_orders", "per_page": 26},
        {"operation": "create_shipment", "payload": "[]"},
        {"operation": "create_shipment", "payload": "{}"},
        {"operation": "create_shipment", "payload": "invalid"},
        {"operation": "create_item", "name": "T-Shirt"},
    ],
)
def test_shipmondo_invalid_configs(config):
    with pytest.raises(ValidationError):
        node(config)


def test_shipmondo_credential_is_manual():
    value = ShipmondoAPIKeyCredential.model_validate(
        {"api_username": " example-user ", "api_key": " example-secret "}
    )
    assert (
        value.credential_type == "shipmondo_api_key"
        and value.api_key == "example-secret"
    )
    assert ShipmondoAPIKeyCredential.model_json_schema()["required"] == [
        "api_username",
        "api_key",
    ]
    with pytest.raises(ValidationError):
        ShipmondoAPIKeyCredential(
            api_username="name:password", api_key="example-secret"
        )


def signed(body, secret="test-secret", *, string_payload=False, algorithm="HS256"):
    def enc(value):
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).rstrip(b"=")

    message = (
        enc({"alg": algorithm})
        + b"."
        + enc(json.dumps(body) if string_payload else body)
    )
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), message, hashlib.sha256).digest()
    ).rstrip(b"=")
    return (message + b"." + signature).decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("event", WEBHOOK_EVENTS)
async def test_shipmondo_documented_events_register_decode_and_resolve(
    monkeypatch, event
):
    resource, action = event.rsplit(".", 1)
    data = json.loads(
        (FIXTURES / (resource.lower().replace(" ", "_") + ".json")).read_text()
    )
    request = AsyncMock(side_effect=[[{"id": 1}], None])
    monkeypatch.setattr(ShipmondoNode, "_request", request)
    registration = await ShipmondoNode._register_external_webhook(
        webhook_url="https://example.com/webhook",
        credential=CREDENTIAL,
        config={"event_type": event},
        node_id="test",
    )
    body = request.call_args.kwargs["body"]
    assert body["resource_name"] == resource and body["action"] == action
    assert (
        body["endpoint"] == "https://example.com/webhook"
        and body["key"] == registration["signing_secret"]
    )
    token = signed(data, registration["signing_secret"])
    assert ShipmondoNode.verify_webhook_signature(
        json.dumps({"data": token}).encode(), {}, registration
    )
    decoded = await ShipmondoNode.transform_trigger_payload(
        {"data": token, "_webhook": {"headers": {"SMD-User": "Shipmondo user"}}},
        registration,
    )
    result = ShipmondoNode.resolve_trigger_payload(decoded, {"event_type": event})
    turn = ShipmondoNode.resolve_agent_event(result)
    assert str(data["data"]["id"]) in turn["text"] and "Shipmondo user" in turn["text"]
    if resource == "Shipment Monitor":
        assert "get_shipment id=123456789" in turn["text"]
    await ShipmondoNode._unregister_external_webhook(
        credential=CREDENTIAL, config=registration, node_id="test"
    )
    assert request.call_args.args[1:] == ("DELETE", "/webhooks/1")


@pytest.mark.parametrize("string_payload", [True, False])
def test_shipmondo_jwt_verification_is_fail_closed(string_payload):
    payload = json.loads((FIXTURES / "shipments.json").read_text())
    token = signed(payload, string_payload=string_payload)
    wire = json.dumps({"data": token}).encode()
    assert ShipmondoNode.verify_webhook_signature(
        wire, {}, {"signing_secret": "test-secret"}
    )
    assert _decode_jwt(token, "test-secret") == payload
    for body, config in [
        (wire, {}),
        (wire, {"signing_secret": "wrong-secret"}),
        (json.dumps(payload).encode(), {"signing_secret": "test-secret"}),
        (
            json.dumps({"data": signed(payload, algorithm="none")}).encode(),
            {"signing_secret": "test-secret"},
        ),
        (
            json.dumps({"data": token[:-5] + "xxxxx"}).encode(),
            {"signing_secret": "test-secret"},
        ),
        (b"invalid", {"signing_secret": "test-secret"}),
    ]:
        assert not ShipmondoNode.verify_webhook_signature(body, {}, config)


@pytest.mark.asyncio
async def test_shipmondo_manual_trigger_has_no_event():
    result = await node({"operation": "on_event"}).execute({"unrelated": "data"})
    assert (
        result["status"] == "no_event"
        and ShipmondoNode.resolve_agent_event(result) is None
    )
