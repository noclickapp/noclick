"""Native node HTTP contract tests, with no live credentials or requests."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import yelp_node as yelp
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "yelp_api_key", "api_key": "yelp-unit-secret"}


@pytest.fixture
def ensure_native_db_pool():
    yield


CASES = [
    ("search_businesses", {"location": "San Francisco", "categories": ["restaurants", "italian"], "price": [1, 2], "open_now": False, "offset": 20}, "GET", "/v3/businesses/search"),
    ("search_businesses_by_phone", {"phone": "+14159083801"}, "GET", "/v3/businesses/search/phone"),
    ("match_businesses", {"name": "Yelp", "address1": "140 New Montgomery St", "city": "San Francisco", "state": "CA", "country": "US"}, "GET", "/v3/businesses/matches"),
    ("get_business", {"business_id_or_alias": "yelp-san-francisco"}, "GET", "/v3/businesses/yelp-san-francisco"),
    ("search_delivery", {"location": "San Francisco"}, "GET", "/v3/transactions/delivery/search"),
    ("get_business_engagement", {"business_ids": ["business-1", "business-2"], "date_range_start": "2025-01-01", "date_range_end": "2025-01-31"}, "GET", "/v3/businesses/engagement"),
    ("get_service_offerings", {"business_id_or_alias": "yelp-san-francisco"}, "GET", "/v3/businesses/yelp-san-francisco/service_offerings"),
    ("get_reviews", {"business_id_or_alias": "yelp-san-francisco", "limit": 10, "offset": 20}, "GET", "/v3/businesses/yelp-san-francisco/reviews"),
    ("get_review_highlights", {"business_id_or_alias": "yelp-san-francisco"}, "GET", "/v3/businesses/yelp-san-francisco/review_highlights"),
    ("search_events", {"location": "San Francisco", "is_free": True, "categories": ["food-and-drink"]}, "GET", "/v3/events"),
    ("get_event", {"event_id": "san-francisco-event"}, "GET", "/v3/events/san-francisco-event"),
    ("get_featured_event", {"latitude": 37.786882, "longitude": -122.399972}, "GET", "/v3/events/featured"),
    ("autocomplete", {"text": "pizza", "locale": "en_US"}, "GET", "/v3/autocomplete"),
    ("list_categories", {}, "GET", "/v3/categories"),
    ("get_category", {"alias": "restaurants"}, "GET", "/v3/categories/restaurants"),
    ("chat", {"query": "Find Thai restaurants in San Francisco", "chat_id": "session-123", "user_context": {"latitude": 37.786882, "longitude": -122.399972}, "request_context": {"skip_text_generation": True}}, "POST", "/ai/chat/v2"),
]


def make_node(config):
    return NodeFactory.create_node(node_id="yelp-test", node_type="automation-yelp",
        node_data={"config": deepcopy(config), "credentials": deepcopy(AUTH)})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        status, payload, headers = replies.pop(0)
        return httpx.Response(status, content=payload, headers=headers)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(yelp, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


@pytest.mark.parametrize("operation,arguments,method,path", CASES)
async def test_yelp_operation(transport, operation, arguments, method, path):
    requests, replies = transport
    payload = {"businesses": [{"id": "example", "rating": 4.5}], "total": 1, "extension": {"future": True}}
    replies.append((200,
                    json.dumps(payload).encode(),
                    {"Content-Type": "application/json"}))
    out = await make_node({"operation": operation, **arguments}).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.yelp.com" and request.headers["Authorization"] == "Bearer yelp-unit-secret"
    assert "yelp-unit-secret" not in str(request.url)
    if method == "POST":
        assert not request.url.query
        assert json.loads(request.content) == {k: v for k, v in arguments.items() if k != "business_id_or_alias"}
    if operation == "search_businesses":
        assert request.url.params["categories"] == "restaurants,italian"
        assert request.url.params["price"] == "1,2"
        assert request.url.params["open_now"] == "false"
        assert request.url.params["offset"] == "20"
    if operation == "get_business_engagement":
        assert request.url.params["business_ids"] == "business-1,business-2"
    assert out["data"] == payload


@pytest.mark.parametrize("config", [
    {"operation": "search_businesses"},
    {"operation": "search_businesses", "latitude": 38},
    {"operation": "search_businesses", "location": "SF", "open_now": True, "open_at": 123},
    {"operation": "search_businesses", "location": "SF", "price": [5]},
    {"operation": "search_businesses", "location": "SF", "price": [1, 1]},
    {"operation": "get_business", "business_id_or_alias": "../categories"},
    {"operation": "get_business", "business_id_or_alias": ".."},
    {"operation": "get_business_engagement", "business_ids": []},
    {"operation": "search_events", "start_date": 200, "end_date": 100},
    {"operation": "chat", "query": ""},
    {"operation": "chat", "query": "test", "user_context": {"latitude": 100, "longitude": 0}},
])
def test_yelp_rejects_invalid_input(config):
    with pytest.raises(ValueError):
        make_node(config)


@pytest.mark.parametrize("status,payload,mime", [
    (401, b'{"error":{"code":"TOKEN_INVALID","description":"Rejected yelp-unit-secret"}}', "application/json"),
    (429, b'{"error":{"code":"TOO_MANY_REQUESTS"}}', "application/json"),
    (302, b"redirect", "text/plain"),
    (200, b"<html>not JSON</html>", "text/html"),
    (200, b"[]", "application/json"),
    (200, b'{"error":{"code":"unexpected"}}', "application/json"),
])
async def test_yelp_fails_closed(transport, status, payload, mime):
    requests, replies = transport
    replies.append((status, payload, {"Content-Type": mime}))
    with pytest.raises(ValueError) as error:
        await make_node({"operation": "list_categories"}).execute({})
    assert "yelp-unit-secret" not in str(error.value)
    assert len(requests) == 1
    if status == 401:
        assert "TOKEN_INVALID" in str(error.value)


def test_yelp_manual_credential_and_evidence():
    auth = yelp.YelpAPIKeyCredential(api_key="  yelp-unit-secret  ")
    assert auth.credential_type == "yelp_api_key" and auth.api_key == "yelp-unit-secret"
    evidence = yelp.YelpNode.connection_evidence
    assert evidence.proves == "reachability" and evidence.operation == "list_categories"


@pytest.mark.parametrize("operation,fixture,arguments", [
    ("search_businesses", "business_search.json", {"location": "San Francisco"}),
    ("get_business", "business_info.json", {"business_id_or_alias": "golden-boy-pizza-hamburg"}),
])
async def test_yelp_documented_business_responses(transport, operation, fixture, arguments):
    from pathlib import Path
    payload = (Path(__file__).parent / "fixtures" / "yelp" / fixture).read_bytes()
    requests, replies = transport
    replies.append((200, payload, {"Content-Type": "application/json"}))
    result = await make_node({"operation": operation, **arguments}).execute({})
    assert result["data"] == json.loads(payload)
    business = result["data"]["businesses"][0] if operation == "search_businesses" else result["data"]
    assert business["rating"] == 4
    assert business["categories"][0] == {"alias": "pizza", "title": "Pizza"}
    assert len(requests) == 1
