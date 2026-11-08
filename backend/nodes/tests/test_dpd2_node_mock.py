"""Offline DPD v2 wire contracts through the real node factory."""
import base64
from urllib.parse import parse_qs
import httpx
import pytest
from pydantic import ValidationError
from nodes import dpd2_node as native
from nodes.core.registry import NodeFactory

PASSWORD = "dpd2-fixture-api-password"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="dpd2-test", node_type="automation-dpd2", node_data={
        "config": config, "credentials": {"credential_type": "dpd2_api_password", "username": "fixture-user", "api_password": PASSWORD}})


def transport(monkeypatch, reply):
    requests = []
    def handler(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "ping"}, "GET", "/v2/", {"status": "SUCCESS"}),
    ({"operation": "list_storefronts"}, "GET", "/v2/storefronts", [{"id": 1, "name": "Store"}]),
    ({"operation": "get_storefront", "id": 4}, "GET", "/v2/storefronts/4", {"id": 4}),
    ({"operation": "list_products", "storefront_id": 2}, "GET", "/v2/products", [{"id": 1}]),
    ({"operation": "get_product", "id": 4}, "GET", "/v2/products/4", {"id": 4}),
    ({"operation": "list_purchases", "ship": False, "total": "19.99", "total_op": "gt"}, "GET", "/v2/purchases", [{"id": 1}]),
    ({"operation": "get_purchase", "id": 4}, "GET", "/v2/purchases/4", {"id": 4}),
    ({"operation": "reactivate_purchase", "id": 4, "buyer_email": "buyer@example.com", "refulfill": False}, "POST", "/v2/purchases/4/reactivate", {"status": "OK"}),
    ({"operation": "list_customers", "receives_newsletters": False}, "GET", "/v2/customers", [{"id": 1}]),
    ({"operation": "get_customer", "id": 4}, "GET", "/v2/customers/4", {"id": 4}),
    ({"operation": "list_subscribers", "storefront_id": 3}, "GET", "/v2/storefronts/3/subscribers", [{"id": 1}]),
    ({"operation": "get_subscriber", "storefront_id": 3, "id": 4}, "GET", "/v2/storefronts/3/subscribers/4", {"id": 4}),
    ({"operation": "verify_subscriber", "storefront_id": 3, "username": "test@example.com"}, "GET", "/v2/storefronts/3/subscribers/verify", "ACTIVE"),
    ({"operation": "verify_notification", "verify_sign": "fixture-signature", "notification_fields": {"buyer_email": "buyer+tag@example.com", "custom": "A + B"}}, "POST", "/v2/notification/verify", "VERIFIED"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_all_operations_map_once_and_preserve_wire_values(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, text=body) if isinstance(body, str) else httpx.Response(200, json=body))
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path and request.url.host == "api.getdpd.com"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(("fixture-user:" + PASSWORD).encode()).decode()
    fields = dict(request.url.params) if method == "GET" else {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
    if config["operation"].startswith("list_"):
        assert fields["page"] == "1"
    if "ship" in config:
        assert fields["ship"] == "false" and fields["total"] == "19.99" and fields["total_op"] == "gt"
    if "refulfill" in config:
        assert fields == {"buyer_email": "buyer@example.com", "refulfill": "false"}
        assert result["email_delivery_verified"] is False and result["fulfillment_verified"] is False
    if "notification_fields" in config:
        assert fields == {**config["notification_fields"], "verify_sign": config["verify_sign"]}
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")


@pytest.mark.asyncio
async def test_pagination_full_short_and_notfound(monkeypatch):
    for size, following in [(100, 3), (1, None), (0, None)]:
        transport(monkeypatch, lambda req: httpx.Response(200, json=[{"id": i} for i in range(size)]))
        result = await node({"operation": "list_products", "page": 2}).execute({})
        assert result["next_page"] == following and result["has_more"] == (size == 100)
    transport(monkeypatch, lambda req: httpx.Response(404, json={"status": "NOTFOUND"}))
    result = await node({"operation": "list_products", "page": 3}).execute({})
    assert result["status"] == "success" and result["data"] == [] and result["next_page"] is None
    result = await node({"operation": "get_product", "id": 3}).execute({})
    assert result["status"] == "error" and result["http_status"] == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_provider_errors_never_report_success_or_echo_secrets(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, text=PASSWORD, headers={"location": "https://other.example"}))
    result = await node({"operation": "reactivate_purchase", "id": 1}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert PASSWORD not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_connection_rejection_preserves_provider_words(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(401, text="Unauthorized"))
    result = await node({"operation": "list_storefronts"}).execute({})
    assert result["error"] == "Unauthorized" and result["status_code"] == 401


@pytest.mark.asyncio
async def test_ambiguous_write_no_retry_and_invalid_response(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("secret " + PASSWORD, request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "reactivate_purchase", "id": 1}).execute({})
    assert result["status"] == "unknown" and PASSWORD not in str(result) and len(requests) == 1
    transport(monkeypatch, lambda req: httpx.Response(200, json={"status": "wrong"}))
    assert (await node({"operation": "reactivate_purchase", "id": 1}).execute({}))["status"] == "unknown"
    transport(monkeypatch, lambda req: httpx.Response(200, text="<html>Sign in</html>"))
    assert (await node({"operation": "list_storefronts"}).execute({}))["status"] == "error"


def test_manual_credential_and_input_validation():
    credential = native.Dpd2Credential(username=" seller ", api_password=PASSWORD)
    assert credential.credential_type == "dpd2_api_password" and credential.username == "seller"
    for values in [dict(username="bad:user", api_password=PASSWORD), dict(username="seller", api_password="https://example.com/token")]:
        with pytest.raises(ValidationError):
            native.Dpd2Credential(**values)
    with pytest.raises(ValidationError):
        native.Dpd2VerifySubscriberConfig(storefront_id=1)
    with pytest.raises(ValidationError):
        native.Dpd2VerifyNotificationConfig(verify_sign="signature", notification_fields={"verify_sign": "override"})
    with pytest.raises(ValidationError):
        native.Dpd2GetProductConfig(id="../other")
