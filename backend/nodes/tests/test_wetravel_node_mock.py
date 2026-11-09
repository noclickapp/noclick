"""Exercise WeTravel's actual node factory against fixture HTTP responses.

Verify auth exchange, every public action, pagination and failures without live credentials.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import wetravel_node as wt
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": wt.CREDENTIAL, "api_key": "fixture-partner-key"}
ACCESS = "fixture-access-token"
USER = "00000000-0000-4000-8000-000000000001"
FIXTURES = Path(__file__).parent / "fixtures/wetravel"
TRIP = json.loads((FIXTURES / "create_trip.json").read_text())
LINK = json.loads((FIXTURES / "create_payment_link.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.wetravel.com"
        assert not request.url.userinfo
        assert "fixture-partner-key" not in str(request.url)
        code, payload = replies.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(code, content=b"" if code == 204 else json.dumps(payload).encode(), headers={"Content-Type": "application/json"})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(wt, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-wetravel", operation=operation,
        arguments=arguments or {}, credential_data=dict(AUTH), user_id=USER)


CASES = [
    ("list_trips", {}, "GET", "/trips", {"data": [{"uuid": "12345678", "title": "London"}], "pagination": {"has_next": True}}),
    ("get_trip", {"trip_uuid": "12345678"}, "GET", "/trips/12345678", {"uuid": "12345678"}),
    ("create_trip", TRIP, "POST", "/trips", {"uuid": "12345678"}),
    ("update_trip", {"trip_uuid": "12345678", "title": "New title"}, "PATCH", "/trips/12345678", {"uuid": "12345678", "title": "New title"}),
    ("delete_trip", {"trip_uuid": "12345678"}, "DELETE", "/trips/12345678", None),
    ("list_payment_links", {}, "GET", "/payment_links", {"data": [], "pagination": {"has_next": False}}),
    ("get_payment_link", {"payment_link_uuid": "12345678"}, "GET", "/payment_links/12345678", {"uuid": "12345678"}),
    ("create_payment_link", LINK, "POST", "/payment_links", {"uuid": "12345678"}),
    ("update_payment_link", {"payment_link_uuid": "12345678", "title": "Changed"}, "PATCH", "/payment_links/12345678", {"uuid": "12345678"}),
    ("delete_payment_link", {"payment_link_uuid": "12345678"}, "DELETE", "/payment_links/12345678", None),
    ("get_trip_itinerary", {"trip_uuid": "12345678"}, "GET", "/trips/12345678/itinerary", {"sections": []}),
    ("update_trip_itinerary", {"trip_uuid": "12345678", "pdf_download_mode": "disabled"}, "PATCH", "/trips/12345678/itinerary", {"sections": [], "pdf_download_mode": "disabled"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,response", CASES)
async def test_wetravel_actions_and_auth_exchange(transport, operation, arguments, method, path, response):
    requests, replies = transport
    replies.extend([(201, {"access_token": ACCESS}), (204 if method == "DELETE" else 201 if method == "POST" else 200, response)])
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 2 and not replies
    exchange, request = requests
    assert exchange.method == "POST" and exchange.url.path == "/v3/auth/tokens/access"
    assert exchange.headers["Authorization"] == "Bearer fixture-partner-key"
    assert not exchange.content
    assert request.method == method and request.url.path == "/v3" + path
    assert request.headers["Authorization"] == "Bearer " + ACCESS
    if method in {"POST", "PATCH"}:
        expected = {k: v for k, v in arguments.items() if not k.endswith("_uuid")}
        if operation == "create_trip":
            expected = {**expected, "currency": "USD", "min_people": 1, "max_people": 25}
        if operation == "create_payment_link":
            expected = {**expected, "currency": "USD"}
        assert json.loads(request.content) == expected
    if operation == "list_trips":
        assert result["next_page"] == 2
    if method == "DELETE":
        assert result["deletion_acknowledged"] is True
    assert ACCESS not in json.dumps(result)


@pytest.mark.asyncio
async def test_wetravel_filters_pagination_and_false_preserved(transport):
    requests, replies = transport
    replies.extend([(201, {"access_token": ACCESS}), (200, {"data": [], "pagination": {"has_next": False}})])
    result = await run("list_trips", {"page": 3, "per_page": 10, "archived": False, "recurring": True, "query": "London", "currency": "USD"})
    assert dict(requests[-1].url.params) == {"page": "3", "per_page": "10", "archived": "false", "recurring": "true", "query": "London", "currency": "USD"}
    assert result["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../other", "a/b", "a%2Fb", "https://example.com", "a\n"])
async def test_wetravel_id_injection_refused(transport, bad):
    with pytest.raises(ValueError):
        await run("get_trip", {"trip_uuid": bad})
    assert not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", [
    ("update_trip", {"trip_uuid": "12345678"}),
    ("update_payment_link", {"payment_link_uuid": "12345678"}),
    ("update_trip_itinerary", {"trip_uuid": "12345678"}),
    ("create_trip", {**TRIP, "end_date": "2020-01-01"}),
    ("create_payment_link", {**LINK, "package": {"price": -1}}),
    ("create_trip", {**TRIP, "trip_options": [{"name": "Addon", "type": "option"}]}),
])
async def test_wetravel_bad_writes_do_not_connect(transport, operation, config):
    with pytest.raises(ValueError):
        await run(operation, config)
    assert not transport[0]


@pytest.mark.asyncio
async def test_wetravel_rejected_key_is_verbatim_and_not_retried(transport):
    requests, replies = transport
    replies.append((401, {"error": "A token is not valid."}))
    result = await run("list_trips")
    assert result["status"] == "error" and result["http_status"] == 401
    assert result["error"] == "A token is not valid."
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"access_token": "bad\nheader"}, {"access_token": 42}])
async def test_wetravel_unusable_access_token_stops_before_resource_call(transport, payload):
    requests, replies = transport
    replies.append((201, payload))
    result = await run("create_payment_link", LINK)
    assert result["status"] == "error" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"error": "Rejected"}, [], "html"])
async def test_wetravel_malformed_success_is_failure(transport, payload):
    _, replies = transport
    replies.extend([(201, {"access_token": ACCESS}), (200, payload)])
    result = await run("list_trips")
    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timed out"), {"error": "Unavailable"}])
async def test_wetravel_uncertain_write_never_retries(transport, failure):
    requests, replies = transport
    replies.extend([(201, {"access_token": ACCESS}), (503, failure)])
    result = await run("create_payment_link", LINK)
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_wetravel_secret_response_fields_and_echoes_redacted(transport):
    _, replies = transport
    replies.extend([(201, {"access_token": ACCESS}), (200, {"uuid": "12345678", "access_token": ACCESS, "title": AUTH["api_key"] + ACCESS})])
    result = await run("get_trip", {"trip_uuid": "12345678"})
    assert AUTH["api_key"] not in json.dumps(result) and ACCESS not in json.dumps(result)
    assert "access_token" not in result["data"]


def test_wetravel_manual_credential_default_and_secret_validation():
    assert wt.WeTravelPartnerAPIKey(api_key="fixture-key").credential_type == wt.CREDENTIAL
    for key in ["Bearer abc", "https://example.com/key", "key\nheader"]:
        with pytest.raises(ValueError):
            wt.WeTravelPartnerAPIKey(api_key=key)
