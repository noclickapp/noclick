"""Exercise native Adafruit IO requests with synthetic responses, offline.

These regressions pin write payloads, credential isolation, connection identity,
pagination and ambiguous failures without sending data to a real IoT account.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import adafruit_io_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-adafruit-account-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**changes):
    return {"credential_type": native.FAMILY, "username": "io_username", "api_key": TOKEN, **changes}


def node(config, **changes):
    return NodeFactory.create_node(node_id="adafruit-fixture", node_type="automation-adafruit-io",
        node_data={"config": config, "credentials": credential(**changes)})


def transport(monkeypatch, body=None, *, status=200, headers=None, error=None):
    requests = []

    def respond(request):
        requests.append(request)
        if error:
            raise error
        return httpx.Response(status, json=body, headers=headers)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_connection_identity_uses_key_header_without_username_route(monkeypatch):
    requests = transport(monkeypatch, {"id": 7, "username": "account-owner", "name": "Owner"})
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "success" and result["data"]["username"] == "account-owner"
    request = requests[0]
    assert request.method == "GET" and str(request.url) == native.BASE + "/user"
    assert request.headers["X-AIO-Key"] == TOKEN
    assert not request.url.query and not request.content
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("create_feed", {"name": "New Feed", "group_key": "weather"}, "POST", "/io_username/feeds", {"feed": {"name": "New Feed"}}),
    ("update_feed", {"feed_key": "weather.temp", "description": "Room temperature"}, "PATCH", "/io_username/feeds/weather.temp", {"feed": {"description": "Room temperature"}}),
    ("create_data", {"feed_key": "weather.temp", "value": "65.5", "lat": "40.726190", "lon": "-74.005334", "ele": "-6"}, "POST", "/io_username/feeds/weather.temp/data", {"value": "65.5", "lat": "40.726190", "lon": "-74.005334", "ele": "-6"}),
    ("update_data", {"feed_key": "weather.temp", "data_id": "01TESTPOINT", "value": "66"}, "PATCH", "/io_username/feeds/weather.temp/data/01TESTPOINT", {"value": "66"}),
    ("create_group", {"name": "Some Group", "description": "A collection of feeds"}, "POST", "/io_username/groups", {"name": "Some Group", "description": "A collection of feeds"}),
    ("update_group", {"group_key": "weather", "description": "Outdoor sensors"}, "PATCH", "/io_username/groups/weather", {"description": "Outdoor sensors"}),
], ids=["adafruit-io-create-feed", "adafruit-io-update-feed", "adafruit-io-create-data",
        "adafruit-io-update-data", "adafruit-io-create-group", "adafruit-io-update-group"])
async def test_write_contract_payloads(monkeypatch, operation, config, method, path, body):
    requests = transport(monkeypatch, {"id": "created", "name": "New Feed", "value": "65.5"})
    result = await node({"operation": operation, **config}).run({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v2" + path
    assert json.loads(request.content) == body
    assert dict(request.url.params) == ({"group_key": "weather"} if operation == "create_feed" else {})
    assert request.headers["content-type"] == "application/json"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path,listing", [
    ("get_throttle", {}, "/throttle", False),
    ("list_feeds", {}, "/feeds", True),
    ("get_feed", {"feed_key": "weather.temp"}, "/feeds/weather.temp", False),
    ("get_feed_details", {"feed_key": "weather.temp"}, "/feeds/weather.temp/details", False),
    ("list_data", {"feed_key": "weather.temp"}, "/feeds/weather.temp/data", True),
    ("get_data", {"feed_key": "weather.temp", "data_id": "01POINT"}, "/feeds/weather.temp/data/01POINT", False),
    ("get_last_data", {"feed_key": "weather.temp"}, "/feeds/weather.temp/data/last", False),
    ("get_first_data", {"feed_key": "weather.temp"}, "/feeds/weather.temp/data/first", False),
    ("list_groups", {}, "/groups", True),
    ("get_group", {"group_key": "weather"}, "/groups/weather", False),
    ("list_group_feeds", {"group_key": "weather"}, "/groups/weather/feeds", True),
], ids=["adafruit-io-throttle", "adafruit-io-list-feeds", "adafruit-io-get-feed",
        "adafruit-io-feed-details", "adafruit-io-list-data", "adafruit-io-get-data",
        "adafruit-io-last-data", "adafruit-io-first-data", "adafruit-io-list-groups",
        "adafruit-io-get-group", "adafruit-io-group-feeds"])
async def test_read_routes_and_empty_lists(monkeypatch, operation, config, path, listing):
    requests = transport(monkeypatch, [] if listing else {"id": 7, "value": "42"})
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/api/v2/io_username" + path
    if listing:
        assert result["count"] == 0 and result["page_only"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path", [
    ("delete_feed", {"feed_key": "weather.temp"}, "/feeds/weather.temp"),
    ("delete_data", {"feed_key": "weather.temp", "data_id": "01POINT"}, "/feeds/weather.temp/data/01POINT"),
], ids=["adafruit-io-delete-feed", "adafruit-io-delete-data"])
async def test_deletes_only_acknowledge_provider_success(monkeypatch, operation, config, path):
    requests = transport(monkeypatch, None)
    result = await node({"operation": operation, **config}).execute({})
    assert result["deletion_acknowledged"] and result["http_status"] == 200
    assert len(requests) == 1 and requests[0].method == "DELETE"
    assert requests[0].url.path == "/api/v2/io_username" + path


@pytest.mark.asyncio
async def test_data_time_filters_and_next_boundary(monkeypatch):
    requests = transport(monkeypatch, [{"id": "one", "value": "42"}],
        headers={"X-Pagination-Start": "2026-01-02T00:00:00Z"})
    result = await node({"operation": "list_data", "feed_key": "weather.temp", "limit": 1,
        "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-02-01T00:00:00+00:00"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "1", "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-02-01T00:00:00+00:00"}
    assert result["next_end_time"] == "2026-01-02T00:00:00Z" and result["page_only"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejection_preserved_with_secret_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "rejected " + TOKEN}, status=status)
    result = await node({"operation": "create_data", "feed_key": "temp", "value": "42"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "rejected" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, [], {"error": "Unauthorized"}, {"name": "No identity"}])
async def test_malformed_or_error_identity_is_not_connection_proof(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "get_current_user"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_write_timeout_is_not_retried(monkeypatch):
    requests = transport(monkeypatch, error=httpx.ReadTimeout("ambiguous " + TOKEN))
    result = await node({"operation": "create_data", "feed_key": "temp", "value": "42"}).execute({})
    assert result["status"] == "error" and "inspect writes" in result["error"]
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.parametrize("model,config", [
    (native.GetFeed, {"feed_key": "../other"}),
    (native.GetFeed, {"feed_key": "http://elsewhere.test"}),
    (native.GetData, {"feed_key": "temp", "data_id": "last"}),
    (native.CreateData, {"feed_key": "temp", "value": "42", "lat": "91"}),
    (native.CreateData, {"feed_key": "temp", "value": "42", "ele": "nan"}),
    (native.UpdateFeed, {"feed_key": "temp"}),
    (native.UpdateGroup, {"group_key": "weather"}),
    (native.ListData, {"feed_key": "temp", "start_time": "2026-01-01"}),
    (native.ListData, {"feed_key": "temp", "start_time": "2026-02-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"}),
])
def test_invalid_config_refused_before_request(model, config):
    with pytest.raises(ValidationError):
        model.model_validate(config)


@pytest.mark.parametrize("key", ["https://example.test/key", "<token>", "abc\n123", "abc 123"])
def test_manual_key_shaping_rejects_urls_placeholders_and_headers(key):
    with pytest.raises(ValidationError):
        native.AdafruitIOAPIKeyCredential.model_validate(credential(api_key=key))


@pytest.mark.asyncio
async def test_output_drops_secrets_without_dropping_feed_key(monkeypatch):
    transport(monkeypatch, {"id": 7, "key": "weather.temp", "api_key": TOKEN,
                            "details": {"nested": TOKEN}})
    result = await node({"operation": "get_feed", "feed_key": "weather.temp"}).execute({})
    assert result["data"]["key"] == "weather.temp"
    assert "api_key" not in result["data"] and TOKEN not in str(result)
