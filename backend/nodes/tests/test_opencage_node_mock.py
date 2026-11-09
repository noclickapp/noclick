"""OpenCage request regressions using the provider's published response examples.

Fixtures copied from https://opencagedata.com/api#response (JSON and GeoJSON
reverse geocoding, -22.6792, 14.5272); tests never contact the provider.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import opencage_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

KEY = "synthetic-opencage-key"
FIXTURES = Path(__file__).parent / "fixtures/opencage"


def body(fmt="json"):
    return json.loads((FIXTURES / (fmt + ".json")).read_text())


def node(config):
    return NodeFactory.create_node(node_id="test-opencage", node_type="automation-opencage",
        node_data={"config": config, "credentials": {"credential_type": "opencage_api_key", "api_key": KEY}})


def transport(monkeypatch, payload=None, status=200, *, error=False, text=None):
    requests = []
    def respond(request):
        requests.append(request)
        if error:
            raise httpx.ConnectError("secret URL " + KEY, request=request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,path,flags", [
    ("geocode", {"q": "Frauenplan 1, 99423 Weimar, Germany"}, "/json", {}),
    ("geocode_in_bounds", {"q": "London", "bounds": "-0.563160,51.280430,0.278970,51.683979"}, "/json", {}),
    ("geocode_in_country", {"q": "Berlin", "countrycode": "de"}, "/json", {}),
    ("geocode_near", {"q": "Berlin", "proximity": "52.3877830, 9.7334394"}, "/json", {}),
    ("reverse_geocode", {"latitude": -22.6792, "longitude": 14.5272}, "/json", {}),
    ("reverse_address", {"latitude": 50.976004, "longitude": 11.336753}, "/json", {"address_only": "1"}),
    ("reverse_road", {"latitude": -22.6792, "longitude": 14.5272}, "/json", {"roadinfo": "1"}),
    ("geocode_geojson", {"q": "Berlin"}, "/geojson", {}),
    ("reverse_geojson", {"latitude": -22.6792, "longitude": 14.5272}, "/geojson", {}),
])
async def test_documented_operation_mapping(monkeypatch, operation, extra, path, flags):
    payload = body("geojson" if path == "/geojson" else "json")
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **extra, "language": "de", "limit": 3, "no_record": True}).execute({})
    assert result["status"] == "success" and result["data"] == payload
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET" and req.url.host == "api.opencagedata.com"
    assert req.url.path == "/geocode/v1" + path
    query = dict(req.url.params)
    assert query["key"] == KEY and query["language"] == "de" and query["limit"] == "3" and query["no_record"] == "1"
    assert "operation" not in query and "latitude" not in query and "longitude" not in query
    if "latitude" in extra:
        assert query["q"] == f"{extra['latitude']},{extra['longitude']}"
    else:
        for name, value in extra.items():
            assert query[name] == value
    for name, value in flags.items():
        assert query[name] == value
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_evidence_is_authenticated_geocode_not_public_ping(monkeypatch):
    requests = transport(monkeypatch, body())
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "success"
    assert dict(requests[0].url.params) == {"key": KEY, "q": "Berlin, Germany", "limit": "1", "no_annotations": "1"}
    assert native.OpenCageNode.connection_evidence.proves == "reachability"
    requests = transport(monkeypatch, text="pong\n")
    result = await node({"operation": "get_health"}).execute({})
    assert result["key_verified"] is False and result["data"] == "pong"
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 402, 403, 429, 500])
async def test_provider_errors_preserved_and_secrets_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"status": {"code": status, "message": "quota exceeded " + KEY}}, status)
    result = await node({"operation": "check_connection"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "quota exceeded [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_empty_results_subscription_and_no_secret_echo(monkeypatch):
    transport(monkeypatch, {"status": {"code": 401, "message": "invalid API key"}, "results": []})
    assert (await node({"operation": "check_connection"}).execute({}))["status"] == "error"
    payload = body(); payload.pop("rate"); payload["results"] = []; payload["total_results"] = 0
    payload["request"] = {"key": KEY}; payload["thanks"] = KEY
    transport(monkeypatch, payload)
    result = await node({"operation": "check_connection"}).execute({})
    assert result["status"] == "success" and result["data"]["results"] == []
    assert KEY not in str(result) and "request" not in result["data"]
    transport(monkeypatch, error=True)
    assert KEY not in str(await node({"operation": "check_connection"}).execute({}))


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"status": {"code": 200}}, {"status": {"code": 200}, "results": [None]}])
async def test_malformed_success_is_not_evidence(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "check_connection"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "reverse_geocode", "latitude": 91, "longitude": 10},
    {"operation": "reverse_geocode", "latitude": 10, "longitude": float("nan")},
    {"operation": "geocode", "q": "  "},
    {"operation": "geocode", "q": "Berlin", "limit": 101},
    {"operation": "geocode_in_country", "q": "Berlin", "countrycode": "DE"},
    {"operation": "geocode_in_bounds", "q": "Berlin", "bounds": "0,90,10,-90"},
    {"operation": "geocode_near", "q": "Berlin", "proximity": "0,190"},
    {"operation": "geocode", "q": "Berlin", "api_url": "https://example.test"},
    {"operation": "create_location"},
])
def test_invalid_configs(config):
    with pytest.raises((ValueError, ValidationError)):
        native.OpenCageNode.parse_config({"config": config, "credentials": {"api_key": KEY}})


def test_discovery_and_manual_credential_defaults():
    assert NODE_REGISTRY["automation-opencage"] is native.OpenCageNode
    credential = native.OpenCageAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "opencage_api_key"
    assert native.OpenCageAPIKeyCredential.model_json_schema()["required"] == ["api_key"]
