"""Offline native factory tests; response snippets retain their official source URLs."""
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from nodes import bluepillow_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/bluepillow"
TOKEN = "synthetic-bluepillow-key-42"
KEY = "9d87e29c-2085-4c3a-9b04-755c62f7c4de"
STAY = {"check_in": "2027-03-10", "check_out": "2027-03-13", "adults": 2, "rooms": 1, "idempotency_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def example(page):
    return json.loads((FIXTURES / (page + ".json")).read_text())[0]["body"]


def node(config, credentials=True):
    if config["operation"] == "resolve_destination":
        config = {"name": "Rome", **config}
    return NodeFactory.create_node(node_id="bluepillow-fixture", node_type="automation-bluepillow",
        node_data={"config": config, **({"credentials": {"credential_type": native.CREDENTIAL, "api_key": TOKEN}} if credentials else {})})


def transport(monkeypatch, body, code=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(code, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_health"}, {"status": "ok", "version": "2026-05-08"}, "GET", "/health", 200),
    ({"operation": "issue_anonymous_key", "agent": "my-agent-name"}, {"key": "synthetic-issued-key", "created_at": "2026-05-08T00:00:00Z", "rate_limit": {"requests_per_minute": 120, "requests_per_day": 60000}}, "POST", "/keys", 201),
    ({"operation": "get_property_preview", "property_id": "prop_abc123", "src": "noclick"}, {"id": "prop_abc123", "name": "Hotel Blue Sky", "property_type": "hotel", "location": {"city": "Rome", "country": "IT"}, "upgrade": {}}, "GET", "/properties/prop_abc123/preview", 200),
    ({"operation": "get_property", "property_id": "prop_abc123", "include": "reviews_aggregate,reviews_extended", "currency": "EUR"}, {"id": "prop_abc123", "name": "Hotel Blue Sky", "property_type": "hotel", "rating": 4.7, "location": {"lat": 41.9097, "lon": 12.4801, "address": "Via del Babuino 9", "city": "Rome", "country": "IT"}, "amenities": ["wifi"], "ota_coverage": ["Booking"]}, "GET", "/properties/prop_abc123", 200),
    ({"operation": "resolve_destination", "name": "Rome", "country": "IT"}, "destinations", "POST", "/destinations/resolve", 200),
    ({"operation": "discover_destinations", "lat": 43.7696, "lon": 11.2558, "radius_km": 25.0, "type": "city"}, {"candidates": [], "total_matches": 0}, "POST", "/destinations/discover-near", 200),
    ({"operation": "search_stays", **STAY, "destination_id": "dest_5f3a...", "min_rating": 4.0, "price_max_eur": 300, "property_types": ["hotel", "aparthotel"], "cursor": "opaque-cursor"}, "search-stays", "POST", "/search/stays", 200),
    ({"operation": "recommend_stay", **STAY, "destination_id": "dest_5f3a...", "price_max_eur": 250, "min_rating": 4.0, "end_user_country": "IT", "currency": "EUR", "language": "en"}, "decide", "POST", "/decide", 200),
    ({"operation": "recommend_by_hotel", **STAY, "property_id": "prop_abc123"}, "recommendations", "POST", "/recommendations/by-hotel", 200),
    ({"operation": "validate_offer", **STAY, "property_id": "prop_abc123", "total_eur": 210, "ota": "Booking"}, "validate", "POST", "/validate", 200),
    ({"operation": "initiate_booking", **STAY, "property_id": "prop_abc123", "ota": "Booking"}, "bookings", "POST", "/bookings/initiate", 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,body,method,path,code", CASES)
async def test_bluepillow_native_routes_auth_and_documented_responses(monkeypatch, config, body, method, path, code):
    if isinstance(body, str):
        body = example(body)
    requests = transport(monkeypatch, body, code)
    result = await node(config, credentials=config["operation"] not in native.PUBLIC).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v1" + path
    assert request.url.host == "api.b2a.bluepillow.com"
    assert request.headers["B2A-Version"] == native.VERSION
    assert request.headers.get("Authorization") == (None if config["operation"] in native.PUBLIC else "Bearer " + TOKEN)
    if config["operation"] in native.IDEMPOTENT:
        assert request.headers["Idempotency-Key"] == KEY == result["idempotency_key"]
        wire = json.loads(request.content)
        assert wire["dates"] == {"check_in": STAY["check_in"], "check_out": STAY["check_out"]}
        assert wire["guests"] == {"adults": 2, "rooms": 1}
        assert "idempotency_key" not in wire and "operation" not in wire
    else:
        assert "Idempotency-Key" not in request.headers
    if config["operation"] == "search_stays":
        assert wire["page"] == {"limit": 20, "cursor": "opaque-cursor"}
        assert wire["filters"] == {"min_rating": 4.0, "price_max_eur": 300, "property_types": ["hotel", "aparthotel"]}
        assert wire["location"] == {"type": "destination_id", "value": "dest_5f3a..."}
        assert result["data"]["page"]["next_cursor"] == "eyJv..."
    if config["operation"] == "validate_offer":
        assert wire["offer_to_compare"] == {"ota": "Booking", "total_eur": 210}
        assert result["data"]["still_valid"] is False
    if config["operation"] == "initiate_booking":
        assert wire["ota"] == "Booking" and result["booking_completed"] is False
    if config["operation"] == "get_property":
        assert dict(request.url.params) == {"include": "reviews_aggregate,reviews_extended", "currency": "EUR"}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_bluepillow_connection_evidence_uses_authenticated_nonmutating_resolution(monkeypatch):
    requests = transport(monkeypatch, example("destinations"))
    evidence = native.BluepillowNode.connection_evidence
    result = await node({"operation": evidence.operation}).execute({})
    assert evidence.proves == "reachability" and result["status"] == "success"
    assert json.loads(requests[0].content) == {"name": "Rome", "language": "en"}
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_bluepillow_generates_uuid_without_replaying_or_claiming_reservation(monkeypatch):
    requests = transport(monkeypatch, example("bookings"))
    config = {"operation": "initiate_booking", **STAY, "property_id": "prop_abc123"}
    del config["idempotency_key"]
    result = await node(config).execute({})
    assert str(UUID(result["idempotency_key"])) == requests[0].headers["Idempotency-Key"]
    assert result["booking_completed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [202, 204, 301, 302, 400, 401, 403, 404, 429, 500])
async def test_bluepillow_errors_preserve_provider_reason_and_redact_key(monkeypatch, code):
    requests = transport(monkeypatch, {"error": {"code": "authentication_failed", "message": "Rejected " + TOKEN}}, code)
    result = await node({"operation": "resolve_destination"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert result["message"] == "Rejected [redacted]" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"error": {"message": "failed"}}, {"candidates": [], "total_matches": True, "disambiguation_recommended": False}])
async def test_bluepillow_malformed_success_is_not_accepted(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="could not be verified"):
        await node({"operation": "resolve_destination"}).execute({})


@pytest.mark.asyncio
async def test_bluepillow_missing_credential_sends_no_request(monkeypatch):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="Connect a Bluepillow"):
        await node({"operation": "resolve_destination"}, credentials=False).execute({})
    assert requests == []


@pytest.mark.parametrize("config", [
    {"operation": "get_property", "property_id": "../keys"},
    {"operation": "get_property", "property_id": "a?include=other"},
    {"operation": "search_stays", **STAY, "destination_id": "dest_5f3a...", "check_out": STAY["check_in"]},
    {"operation": "discover_destinations", "lat": 91, "lon": 0},
    {"operation": "get_property", "property_id": "prop_abc123", "include": "invented"},
    {"operation": "delete_booking", "property_id": "prop_abc123"},
])
def test_bluepillow_invalid_input_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        native.BluepillowNode.parse_config({"config": config})


def test_bluepillow_manual_credential_defaults_and_schema():
    credential = native.BluepillowAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == native.CREDENTIAL and credential.api_key == TOKEN
    schema = native.BluepillowAPIKeyCredential.model_json_schema()
    assert schema["required"] == ["api_key"]
    assert schema["properties"]["credential_type"]["default"] == native.CREDENTIAL
    assert len(native.ROUTES) == 11
    for key in ["Bearer " + TOKEN, "https://example.com/key", "<token>"]:
        with pytest.raises(ValidationError):
            native.BluepillowAPIKeyCredential(api_key=key)
