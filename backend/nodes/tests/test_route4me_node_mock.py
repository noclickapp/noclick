"""Exercise Route4Me's real factory and HTTP transport with synthetic account data.

These regressions pin all operation routes, query authentication, payloads,
pagination and failure handling without contacting a provider account.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import route4me_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-route4me-key-42"
ADDRESS = {"address_1": "123 Example St", "cached_lat": 38.2, "cached_lng": -85.2}
POLYGON = {"territory_name": "North", "vertices": ["38.2,-85.2", "38.3,-85.2", "38.3,-85.3"]}
CASES = [
    ("list_addresses", {}, "GET", "/addresses/index/pagination", {"page": "1", "per_page": "30", "display": "all"}, None),
    ("get_address", {"address_id": 123}, "GET", "/addresses/show", {"address_id": "123"}, None),
    ("create_address", ADDRESS, "POST", "/addresses", {}, ADDRESS),
    ("update_address", {**ADDRESS, "address_id": 123}, "PUT", "/addresses/123", {}, ADDRESS),
    ("delete_addresses", {"address_ids": [123, 124]}, "DELETE", "/addresses/delete", {}, {"address_ids": [123, 124]}),
    ("get_address_custom_fields", {}, "GET", "/addresses/custom-fields", {}, None),
    ("get_address_clusters", {}, "GET", "/addresses/index/clustering", {"display": "all"}, None),
    ("list_vehicles", {}, "GET", "/vehicles/paginate", {"page": "1", "per_page": "30"}, None),
    ("get_vehicle", {"vehicle_id": "ABC123"}, "GET", "/vehicles/ABC123", {}, None),
    ("create_vehicle", {"vehicle_alias": "Van"}, "POST", "/vehicles", {}, {"vehicle_alias": "Van"}),
    ("update_vehicle", {"vehicle_id": "ABC123", "vehicle_alias": "Van"}, "PATCH", "/vehicles/ABC123", {}, {"vehicle_alias": "Van"}),
    ("delete_vehicle", {"vehicle_id": "ABC123"}, "DELETE", "/vehicles/ABC123", {}, None),
    ("list_territories", {}, "GET", "/territories", {"addresses_count": "false", "orders_count": "false"}, None),
    ("get_territory", {"territory_id": "ABC123"}, "GET", "/territories/ABC123", {}, None),
    ("create_territory", POLYGON, "POST", "/territories", {}, {"territory_name": "North", "territory_color": "000000", "territory": {"type": "poly", "data": POLYGON["vertices"]}}),
    ("update_territory", {**POLYGON, "territory_id": "ABC123"}, "PUT", "/territories/ABC123", {}, {"territory_name": "North", "territory_color": "000000", "territory": {"type": "poly", "data": POLYGON["vertices"]}}),
    ("delete_territory", {"territory_id": "ABC123"}, "DELETE", "/territories/ABC123", {}, None),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="route4me-fixture", node_type="automation-route4me",
        node_data={"config": config, "credentials": {"credential_type": "route4me_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body", CASES)
async def test_route4me_operation_contract(monkeypatch, operation, config, method, path, query, body):
    requests = transport(monkeypatch, httpx.Response(200, json={"results": []}))
    result = await node({"operation": operation, **config}).execute({})
    assert result["success"] is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith(native.BASE)
    assert request.url.path == "/modules/api/v5.0" + path
    assert dict(request.url.params) == {**query, "api_key": TOKEN}
    assert (json.loads(request.content) if request.content else None) == body
    assert "authorization" not in request.headers


@pytest.mark.asyncio
async def test_route4me_address_pagination_and_evidence_rows(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"results": [{"address_alias": "Customer", "address_id": 123}], "current_page": 2, "last_page": 3}))
    result = await node({"operation": "list_addresses", "page": 2}).execute({})
    assert result["next_page"] == 3
    assert result["items"][0]["address_alias"] == "Customer"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Rejected " + TOKEN}), (200, {"status": False, "errors": ["Denied"]}), (200, {"error": "Denied"})])
async def test_route4me_error_envelopes_and_redaction(monkeypatch, status, body):
    transport(monkeypatch, httpx.Response(status, json=body))
    result = await node({"operation": "list_addresses"}).execute({})
    assert result["status"] == "error" and result["success"] is False
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_route4me_queued_delete_is_not_completion(monkeypatch):
    transport(monkeypatch, httpx.Response(202))
    result = await node({"operation": "delete_addresses", "address_ids": [123]}).execute({})
    assert result["queued"] is True and result["readback_verified"] is False


@pytest.mark.asyncio
async def test_route4me_transport_exception_hides_query_key(monkeypatch):
    def failure(request):
        raise httpx.ConnectError(str(request.url))
    transport(monkeypatch, failure)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_vehicle", "vehicle_alias": "Van"}).execute({})
    assert TOKEN not in str(exc.value)
    assert "before retrying" in str(exc.value)


@pytest.mark.parametrize("config", [
    {"operation": "get_vehicle", "vehicle_id": "../other"},
    {"operation": "delete_addresses", "address_ids": []},
    {"operation": "create_address", **ADDRESS, "cached_lat": 91},
    {"operation": "list_addresses", "per_page": 10000},
    {"operation": "create_territory", **POLYGON, "vertices": ["99,0"] * 3},
])
def test_route4me_invalid_input_fails_before_request(config):
    with pytest.raises(ValueError):
        node(config)


def test_route4me_manual_key_default_and_wrong_credential_family():
    assert native.Route4MeAPIKey(api_key=TOKEN).credential_type == "route4me_api_key"
    with pytest.raises(ValidationError):
        native.Route4MeAPIKey(api_key=TOKEN, credential_type="other_api_key")
