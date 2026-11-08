"""Factory execution against provider examples and one schema-shaped geometry ID."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import geoapify_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-geoapify-key-42"
CREDENTIAL = {"credential_type": "geoapify_api_key", "api_key": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/geoapify/contract_examples.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="geoapify-fixture", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, *, status=200, body=None, content_type="application/json"):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Content-Type": content_type})
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_documented_contract_examples_through_factory(monkeypatch, case):
    requests = transport(monkeypatch, status=case["status"], body=case["response"], content_type=case["content_type"])
    config = {"operation": case["operation"], **case["config"]}
    result = await node(config).execute({})
    assert result == {"status": "success", "operation": case["operation"], "http_status": case["status"], "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "api.geoapify.com"
    assert request.headers["x-api-key"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    if case["operation"] == "store_geometry":
        assert json.loads(request.content) == case["config"]["geojson"]
    elif case["operation"].startswith("submit_batch_"):
        assert isinstance(json.loads(request.content), list)
        assert "pending" == result["data"]["status"]
    elif case["operation"] in {"calculate_route_matrix", "get_elevations"}:
        assert "operation" not in json.loads(request.content)


@pytest.mark.asyncio
async def test_query_array_styles_and_geometry_discriminator(monkeypatch):
    requests = transport(monkeypatch, body={"type": "FeatureCollection", "features": []})
    await node({"operation": "calculate_route", "waypoints": ["43.4,-123.2", "43.2,-123.3"],
        "avoid": ["tolls:1", "ferries"], "details": ["instruction_details", "admin_areas"]}).execute({})
    query = requests[-1].url.params
    assert query["waypoints"] == "43.4,-123.2|43.2,-123.3"
    assert query["avoid"] == "tolls:1|ferries"
    assert query["details"] == "instruction_details,admin_areas"
    ids = ["a" * 32, "b" * 32]
    await node({"operation": "calculate_geometry", "id": ids, "geometry_operation": "intersection"}).execute({})
    assert requests[-1].url.params.get_list("id") == ids
    assert requests[-1].url.params["operation"] == "intersection"
    await node({"operation": "get_place_details", "id": "place-id", "features": ["details", "radius_500"]}).execute({})
    assert requests[-1].url.params["features"] == "details|radius_500"
    await node({"operation": "calculate_isoline", "lat": 52.52, "lon": 13.405,
        "range": [300, 900], "avoid": ["tolls", "ferries"]}).execute({})
    assert requests[-1].url.params.get_list("avoid") == ["tolls", "ferries"]
    assert requests[-1].url.params["range"] == "300.0,900.0"


@pytest.mark.asyncio
async def test_connect_read_needs_only_pasted_key_and_marks_reachability(monkeypatch):
    case = next(c for c in CASES if c["operation"] == "get_ip_location")
    requests = transport(monkeypatch, body=case["response"])
    result = await node({"operation": "get_ip_location"}).execute({})
    assert result["status"] == "success" and not requests[0].url.query
    assert native.GeoapifyNode.connection_evidence.proves == "reachability"
    credential = native.GeoapifyAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "geoapify_api_key" and credential.api_key == TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_errors_keep_status_and_provider_message_without_secrets(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={"message": "Rejected " + TOKEN})
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_ip_location"}).execute({})
    assert f"HTTP {status}" in str(error.value)
    assert "Rejected [redacted]" in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,content_type", [({"error": "invalid"}, "application/json"), ({}, "application/json"),
    ({}, "text/html"), ("unexpected", "application/json")])
async def test_refuses_error_envelopes_and_unexpected_response(monkeypatch, body, content_type):
    transport(monkeypatch, body=body, content_type=content_type)
    with pytest.raises(ValueError):
        await node({"operation": "get_ip_location"}).execute({})


@pytest.mark.asyncio
async def test_pending_and_completed_batch_results_and_redaction(monkeypatch):
    requests = transport(monkeypatch, status=202, body={"id": "a" * 32, "status": "pending",
        "url": "https://api.geoapify.com/v1/batch/geocode/search?apiKey=" + TOKEN})
    result = await node({"operation": "get_batch_geocode", "id": "a" * 32}).execute({})
    assert result["data"]["status"] == "pending" and TOKEN not in str(result)
    assert len(requests) == 1
    transport(monkeypatch, body=[])
    assert (await node({"operation": "get_batch_geocode", "id": "a" * 32}).execute({}))["data"] == []
    transport(monkeypatch, status=202, body={"status": "pending"})
    with pytest.raises(ValueError, match="job ID"):
        await node({"operation": "get_batch_geocode", "id": "a" * 32}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "reverse_geocode", "lat": 91, "lon": 0},
    {"operation": "get_ip_location", "ip": "not-an-ip"},
    {"operation": "geocode_address", "text": "address", "apiKey": "overridden"},
    {"operation": "calculate_route", "waypoints": ["0,0"]},
    {"operation": "calculate_route_matrix", "sources": [{"location": [0, 91]}], "targets": [{"location": [0, 0]}]},
    {"operation": "get_elevations", "locations": []},
    {"operation": "calculate_geometry", "id": ["../other"], "geometry_operation": "union"},
    {"operation": "submit_batch_geocode", "addresses": []},
    {"operation": "get_timezone", "lat": 0, "lon": 0, "at": "tomorrow"},
    {"operation": "store_geometry", "geojson": {"type": "Polygon", "coordinates": [[[0,0],[1,1],[0,0]]]}}
])
def test_invalid_inputs_fail_before_http(config):
    with pytest.raises((ValidationError, ValueError)):
        native.GeoapifyFullConfig.model_validate({"config": config, "credentials": CREDENTIAL})


@pytest.mark.parametrize("key", ["https://example.com/key", "<token>", "Bearer secret key", "curly–key"])
def test_paste_key_validation(key):
    with pytest.raises((ValidationError, ValueError)):
        native.GeoapifyAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
async def test_transport_error_does_not_expose_key_or_request_url(monkeypatch):
    def fail(request):
        raise httpx.ConnectError("failed " + TOKEN, request=request)
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    with pytest.raises(ValueError, match="could not be completed") as error:
        await node({"operation": "get_ip_location"}).execute({})
    assert TOKEN not in str(error.value)
