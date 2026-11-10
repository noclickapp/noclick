"""Exercise GeoDataSource requests against examples copied from its own docs.

Cover native factory calls, credential evidence, response envelopes and input
validation without live provider calls; query API keys must never leak.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import geodatasource_node as native
from nodes.core.registry import NodeFactory

TOKEN = "geodatasource-test-api-secret"
FIXTURES = Path(__file__).parent / "fixtures" / "geodatasource"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def body(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())["body"]

def node(config, credentials=True):
    return NodeFactory.create_node(node_id="geodatasource-test", node_type="automation-geodatasource", node_data={"config": config, "credentials": {"credential_type": "geodatasource_api_key", "api_key": TOKEN} if credentials else None})

def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,fixture,config", [
    ("get_nearest_city", "/city", "city", {"latitude": 37.3861, "longitude": -122.084}),
    ("list_nearby_cities", "/cities", "cities", {"latitude": 37.3861, "longitude": -122.084}),
    ("list_neighboring_countries", "/neighboring-countries", "countries", {"country_code": "US"}),
])
async def test_documented_requests_and_responses(monkeypatch, operation, path, fixture, config):
    payload = body(fixture)
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "success": True, "data": payload}
    request, = requests
    assert request.method == "GET" and request.url.scheme == "https" and request.url.host == "api.geodatasource.com"
    assert request.url.path == path
    params = {"key": TOKEN, "format": "json"}
    params.update({"country_code": "US"} if fixture == "countries" else {"lat": "37.3861", "lng": "-122.084"})
    assert dict(request.url.params) == params
    assert TOKEN not in str(result)

@pytest.mark.asyncio
async def test_connection_evidence_is_one_location_read(monkeypatch):
    spec = native.GeoDataSourceNode.connection_evidence
    assert spec.proves == "reachability"
    requests = transport(monkeypatch, body("city"))
    result = await node({"operation": spec.operation, **spec.operation_arguments}).execute({})
    assert result["data"]["city"] == "Mountain View" and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_documented_error_is_not_success_and_redacts_key(monkeypatch, status):
    payload = body("error")
    payload["error"]["error_message"] += " " + TOKEN
    transport(monkeypatch, payload, status)
    result = await node({"operation": "get_nearest_city", "latitude": 0, "longitude": 0}).execute({})
    assert result["status"] == "error" and result["success"] is False
    assert result["error_code"] == 10000 and result["http_status"] == status
    assert result["error"] == "Missing parameter. [redacted]" and TOKEN not in str(result)

@pytest.mark.asyncio
async def test_network_error_hides_query_key(monkeypatch):
    transport(monkeypatch, httpx.ConnectError("https://api.geodatasource.com/city?key=" + TOKEN))
    with pytest.raises(ValueError, match="could not be completed") as exc:
        await node({"operation": "get_nearest_city", "latitude": 0, "longitude": 0}).execute({})
    assert TOKEN not in str(exc.value)

@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, "not a location", {}, {"country": "US"}, []])
async def test_unexpected_success_shape_fails_closed(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError, match="unexpected|unreadable"):
        await node({"operation": "get_nearest_city", "latitude": 0, "longitude": 0}).execute({})

@pytest.mark.parametrize("latitude,longitude", [(91, 0), (-91, 0), (0, 181), (0, -181), (float("nan"), 0), (True, 0)])
def test_coordinate_bounds(latitude, longitude):
    with pytest.raises(ValidationError):
        native.GetNearestCityConfig(latitude=latitude, longitude=longitude)

def test_country_code_and_credential_default():
    assert native.ListNeighboringCountriesConfig(country_code=" us ").country_code == "US"
    for value in ["USA", "../US", "", 1]:
        with pytest.raises(ValidationError):
            native.ListNeighboringCountriesConfig(country_code=value)
    assert native.GeoDataSourceAPIKeyCredential(api_key=TOKEN).credential_type == "geodatasource_api_key"

@pytest.mark.asyncio
async def test_missing_credential_refuses_lookup():
    with pytest.raises(ValueError, match="Connect a GeoDataSource"):
        await node({"operation": "get_nearest_city", "latitude": 0, "longitude": 0}, credentials=False).execute({})
