"""Exercise Ignav through the real node factory with documented API examples.

HTTP is mocked; no account, request credits, or live booking service is used.
"""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import ignav_flights_node as native
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "ignav_flights_api_key", "api_key": "synthetic-ignav-key-42"}
DOCS = json.loads((Path(__file__).parent / "fixtures/ignav-flights/documented.json").read_text())
TRIP = {"origin": "SFO", "destination": "JFK", "departure_date": "2026-12-07"}
CALENDAR = {"origin": "NYC", "destination": "LON", "departure_date_range": {"start": "2026-12-07", "end": "2027-01-06"}, "carry_on_bags": 1, "checked_bags": 1}
CASES = [
    ("get_health", {}, "health", 0, {}),
    ("search_airports", {"q": "san fran", "limit": 5}, "airports", 0, {"q": "san fran", "limit": "5"}),
    ("check_connection", {}, "airports", 0, {"q": "san fran", "limit": "5"}),
    ("search_one_way", TRIP, "quickstart", 0, None),
    ("search_round_trip", {**TRIP, "return_date": "2026-12-14"}, "round-trip", 0, None),
    ("search_fares", {"legs": [{"origin": "SFO", "destination": "DEN", "departure_date": "2026-12-07"}, {"origin": "COS", "destination": "ORD", "departure_date": "2026-12-11", "max_stops": 0}], "adults": 2}, "search", 0, None),
    ("get_booking_links", {"ignav_id": "5e4fcd2f1dc340649eb19f6ee2afb57a"}, "booking-links", 0, None),
    ("get_manual_booking_links", {**TRIP, "outbound_carrier_code": "AA", "outbound_flight_number": "100"}, "booking-links", 0, None),
    ("search_cheapest_dates", CALENDAR, "cheapest-dates", 0, None),
    ("search_round_trip_dates", {**CALENDAR, "stay_days": 7}, "cheapest-dates", 0, None),
]


@pytest.fixture
def ensure_native_db_pool():
    yield


def node(operation, config=None):
    return NodeFactory.create_node(node_id="ignav-fixture", node_type="automation-ignav-flights",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": deepcopy(AUTH)})


def mock_http(monkeypatch, body, status=200):
    requests = []
    def send(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,doc,index,query", CASES)
async def test_documented_actions_exact_wire_and_unchanged_response(monkeypatch, operation, config, doc, index, query):
    body = DOCS[doc]["responses"][index]
    requests = mock_http(monkeypatch, body)
    result = await node(operation, config).execute({})
    assert result == {"data": body}
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == native.ROUTES[operation]
    assert request.url.host == "ignav.com" and request.url.scheme == "https"
    assert AUTH["api_key"] not in str(request.url) and AUTH["api_key"] not in str(result)
    if operation == "get_health":
        assert "X-Api-Key" not in request.headers
    else:
        assert request.headers["X-Api-Key"] == AUTH["api_key"]
    if query is not None:
        assert dict(request.url.params) == query
        assert request.content == b""
    else:
        sent = json.loads(request.content)
        assert "operation" not in sent and "credentials" not in sent
        assert {key: sent[key] for key in config} == config
        assert request.headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_flexible_booking_response_keeps_leg_indexes_and_price_status(monkeypatch):
    body = DOCS["search"]["responses"][1]
    mock_http(monkeypatch, body)
    assert (await node("get_booking_links", {"ignav_id": "b2c3d4e5f6789012345678abcdef0123"}).execute({}))["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 402, 403, 404, 429, 503])
async def test_provider_errors_are_not_success_and_secrets_are_redacted(monkeypatch, status):
    requests = mock_http(monkeypatch, {"error": {"message": "Key rejected " + AUTH["api_key"]}}, status)
    with pytest.raises(ValueError) as error:
        await node("check_connection").execute({})
    assert str(status) in str(error.value) and "Key rejected" in str(error.value)
    assert AUTH["api_key"] not in str(error.value) and len(requests) == 1


@pytest.mark.parametrize("operation,config", [
    ("search_airports", {"q": "x"}),
    ("search_airports", {"q": "san fran", "limit": 21}),
    ("search_one_way", {**TRIP, "adults": 0}),
    ("search_one_way", {**TRIP, "adults": True}),
    ("search_one_way", {**TRIP, "max_stops": 3}),
    ("search_one_way", {**TRIP, "checked_bags": 2}),
    ("search_one_way", {**TRIP, "infants_on_lap": 2}),
    ("search_one_way", {**TRIP, "airlines_include": ["AA"], "airlines_exclude": ["AA"]}),
    ("search_round_trip", {**TRIP, "return_date": "2026-12-01"}),
    ("search_fares", {"legs": []}),
    ("search_cheapest_dates", {**CALENDAR, "departure_date_range": {"start": "2026-12-07", "end": "2027-01-07"}}),
    ("get_manual_booking_links", {**TRIP}),
    ("get_manual_booking_links", {**TRIP, "outbound_carrier_code": "AA", "outbound_flight_number": "100", "return_date": "2026-12-14"}),
    ("search_round_trip_dates", CALENDAR),
])
def test_invalid_inputs_rejected_before_http(operation, config):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, config)


def test_manual_credential_defaults_and_reachability():
    credential = native.IgnavFlightsAPIKeyCredential(api_key=AUTH["api_key"])
    assert credential.credential_type == AUTH["credential_type"]
    assert native.IgnavFlightsNode.connection_evidence.proves == "reachability"
    assert native.IgnavFlightsNode.connection_evidence.operation != "get_health"
    assert len(native.ROUTES) == 10
