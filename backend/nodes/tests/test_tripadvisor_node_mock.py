"""Tripadvisor Terra HTTP-boundary regressions; synthetic credentials, no live calls."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError
from nodes import tripadvisor_node as native
from nodes.core.registry import NodeFactory

TOKEN = "fixture-tripadvisor-api-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="tripadvisor-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": {"credential_type": "tripadvisor_api_key", "api_key": TOKEN}})


def capture(monkeypatch, status=200, body=None):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={} if body is None else body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as c:
            yield c
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


CASES = [
    ({"operation": "list_allowlist", "cursor": "next+page", "size": 5}, "GET", "/allowlist"),
    ({"operation": "update_allowlist", "operation_type": "APPEND", "allowlist": [187147]}, "POST", "/allowlist"),
    ({"operation": "search_nearby_catalog", "lat": 48.85, "lon": 2.33, "radius": 1, "unit": "KM"}, "GET", "/catalog/locations/nearby"),
    ({"operation": "search_catalog", "query": "Paris"}, "GET", "/catalog/locations/search"),
    ({"operation": "get_catalog_location", "id": 187147}, "GET", "/catalog/locations/187147"),
    ({"operation": "get_geos", "id": [187147, 60763]}, "GET", "/geos"),
    ({"operation": "get_geo", "id": 187147}, "GET", "/geos/187147"),
    ({"operation": "get_locations", "id": [183778, 23555902]}, "GET", "/locations"),
    ({"operation": "search_nearby_locations", "lat": 48.8566, "lon": 2.3522, "radius": 2, "unit": "KM", "include_photo": True}, "GET", "/locations/nearby"),
    ({"operation": "search_locations", "query": "café + Paris", "locale": ["en", "fr"], "page": 2}, "GET", "/locations/search"),
    ({"operation": "get_location", "id": 183778}, "GET", "/locations/183778"),
    ({"operation": "list_photos", "id": 183778, "page": 0}, "GET", "/locations/183778/photos"),
    ({"operation": "list_reviews", "id": 183778, "published_after_ts": "2026-01-01", "sort_by": "MOST_RECENT"}, "GET", "/locations/183778/reviews"),
    ({"operation": "list_feed_files", "page": 0, "size": 10}, "GET", "/feeds/files/list"),
    ({"operation": "get_feed_file_url", "filename": "locations data.json.gz"}, "GET", "/feeds/json/locations data.json.gz"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES)
async def test_each_operation_is_one_exact_authenticated_request(monkeypatch, config, method, path):
    payload = {"data": [], "pagination": {"next_cursor": "continue"}, "detail": "provider metadata"}
    calls = capture(monkeypatch, body=payload)
    output = await node(config).execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.host == "terra.tripadvisor.com" and request.url.scheme == "https"
    assert request.url.path == "/api" + path
    assert request.headers["X-API-Key"] == TOKEN
    assert TOKEN not in str(request.url)
    assert output["data"] == payload and output["http_status"] == 200
    if method == "POST":
        assert json.loads(request.content) == {"operation_type": config["operation_type"], "allowlist": config["allowlist"]}
    if isinstance(config.get("id"), list):
        assert request.url.params.get_list("id") == list(map(str, config["id"]))
    if "locale" in config:
        assert request.url.params.get_list("locale") == config["locale"]
    if "include_photo" in config:
        assert request.url.params["include_photo"] == "true"
    if "published_after_ts" in config:
        assert request.url.params["published_after_ts"] == "2026-01-01"
    if "cursor" in config:
        assert request.url.params["cursor"] == "next+page"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["APPEND", "DELETE", "OVERWRITE"])
async def test_allowlist_update_preserves_empty_overwrite_and_provider_counts(monkeypatch, mode):
    payload = {"added": 0, "deleted": 10, "no_change": 0}
    calls = capture(monkeypatch, body=payload)
    result = await node({"operation": "update_allowlist", "operation_type": mode, "allowlist": []}).execute({})
    assert json.loads(calls[0].content) == {"operation_type": mode, "allowlist": []}
    assert result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
async def test_failures_do_not_retry_and_redact_key(monkeypatch, status):
    calls = capture(monkeypatch, status, {"message": "rejected " + TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_allowlist"}).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_feed_urls_are_returned_without_following_and_secret_is_redacted(monkeypatch):
    calls = capture(monkeypatch, body={"url": "https://download.example.test/feed", "debug": TOKEN})
    result = await node({"operation": "get_feed_file_url", "filename": "feed.json"}).execute({})
    assert len(calls) == 1 and TOKEN not in str(result)
    assert result["data"]["url"] == "https://download.example.test/feed"


@pytest.mark.parametrize("config", [
    {"operation": "get_feed_file_url", "filename": "../feed"},
    {"operation": "search_nearby_locations"},
    {"operation": "search_nearby_locations", "lat": 1, "lon": 1, "radius": 9, "unit": "KM"},
    {"operation": "search_nearby_locations", "location_id": "187147", "lat": 1, "lon": 1, "radius": 1},
    {"operation": "search_nearby_locations", "sw_lat": "48.87", "sw_lon": "2", "ne_lat": "48.84", "ne_lon": "3"},
    {"operation": "get_locations", "id": [1, 1]},
    {"operation": "update_allowlist", "operation_type": "APPEND", "allowlist": [1, 1]},
    {"operation": "list_allowlist", "size": 1001},
])
def test_documented_invalid_inputs_fail_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_has_default_type_and_connection_evidence():
    credential = native.TripadvisorAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "tripadvisor_api_key" and credential.api_key == TOKEN
    assert native.TripadvisorNode.connection_evidence.operation == "list_allowlist"


@pytest.mark.asyncio
async def test_account_allowlist_ids_are_visible_to_the_shared_evidence_renderer(monkeypatch):
    from nodes.core.connection_evidence import _rows_from_operation, _label_from
    payload = {"data": [187147, 183778], "pagination": {"size": 1000, "next_cursor": "continue"}}
    calls = capture(monkeypatch, body=payload)
    result = await node({"operation": "list_allowlist"}).execute({})
    rows = _rows_from_operation(result)
    labels = [_label_from(row, native.TripadvisorNode.connection_evidence.label_keys) for row in rows]
    assert labels == ["Tripadvisor location 187147", "Tripadvisor location 183778"]
    assert result["data"] == payload and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": ["not-an-id"], "pagination": {}}, {"data": [True], "pagination": {}}])
async def test_malformed_allowlist_is_not_account_evidence(monkeypatch, payload):
    capture(monkeypatch, body=payload)
    with pytest.raises(ValueError, match="allowlist"):
        await node({"operation": "list_allowlist"}).execute({})


def review_page():
    # Replayed from the provider's pinned PageReview schema, not a live response.
    # The generated fixture records its source so evidence remains explicit.
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures/tripadvisor/reviews-schema.json").read_text())["body"]


def persist_poll_state(monkeypatch, instance):
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(state)
        if replacement is not None:
            state = replacement
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    return lambda: state


@pytest.mark.asyncio
async def test_review_trigger_baselines_deduplicates_and_rebaselines_on_scope_change(monkeypatch):
    import copy
    payload = review_page()
    calls = capture(monkeypatch, body=payload)
    instance = node({"operation": "on_new_review", "id": 183778, "published_after_ts": "2024-01-01"})
    state = persist_poll_state(monkeypatch, instance)
    first = await instance.execute({})
    assert first["reviews"] == [] and instance.trigger_produced_no_event(first)
    assert native.TripadvisorNode.resolve_agent_event(first) is None
    newer = copy.deepcopy(payload["data"][0])
    newer["id"] += 1
    payload["data"].insert(0, newer)
    fresh = await instance.execute({})
    assert fresh["reviews"] == [newer] and fresh["new_review_count"] == 1
    assert instance.trigger_emitted_event(fresh)
    assert native.TripadvisorNode.should_propagate_output(fresh, {"operation": "on_new_review"})
    event = native.TripadvisorNode.resolve_agent_event(fresh)
    for value in ["183778", str(newer["id"]), newer["publish_ts"], newer["title"][0]["value"], newer["text"][0]["value"], newer["user"]["username"]]:
        assert value in event["text"]
    assert (await instance.execute({}))["reviews"] == []
    assert calls[0].url.path == "/api/locations/183778/reviews"
    assert dict(calls[0].url.params) == {"sort_by": "MOST_RECENT", "language": "primary", "page": "1", "size": "100", "published_after_ts": "2024-01-01"}
    previous_scope = state()["scope"]
    instance.config.config.id = 60763
    assert (await instance.execute({}))["reviews"] == []
    assert state()["scope"] != previous_scope


@pytest.mark.asyncio
async def test_review_trigger_paginates_before_advancing_seen_state(monkeypatch):
    import copy
    payload = review_page()
    payload["pagination"]["total_pages"] = 2
    calls = []
    async def request(secret, method, path, params, body=None):
        calls.append(dict(params))
        page = copy.deepcopy(payload)
        page["data"][0]["id"] = int(dict(params)["page"])
        return page, 200
    monkeypatch.setattr(native.TripadvisorNode, "_request", staticmethod(request))
    instance = node({"operation": "on_new_review", "id": 183778})
    state = persist_poll_state(monkeypatch, instance)
    await instance.execute({})
    assert [call["page"] for call in calls] == ["1", "2"]
    assert set(state()["seen_ids"]) == {"1", "2"}
    payload["pagination"]["total_pages"] = 21
    with pytest.raises(ValueError, match="2,000"):
        await instance.execute({})
    assert set(state()["seen_ids"]) == {"1", "2"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": [{}], "pagination": {}}, {"data": [{"id": True}], "pagination": {}}])
async def test_review_trigger_rejects_malformed_pages_without_advancing_state(monkeypatch, payload):
    capture(monkeypatch, body=payload)
    instance = node({"operation": "on_new_review", "id": 183778})
    state = persist_poll_state(monkeypatch, instance)
    with pytest.raises(ValueError, match="review"):
        await instance.execute({})
    assert state() == {}


def test_review_trigger_scope_ignores_builder_metadata_and_tracks_declared_fields():
    cls = native.TripadvisorNode
    config = {"operation": "on_new_review", "id": 183778}
    scope = cls.schedule_poll_scope(config)
    assert scope == cls.schedule_poll_scope({**config, "label": "My reviews", "goal": "Alert me"})
    assert scope != cls.schedule_poll_scope({**config, "language": "fr"})
    assert scope != cls.schedule_poll_scope({**config, "published_after_ts": "2024-01-01"})
    assert cls._is_schedule_operation("on_new_review")
    assert not cls._is_schedule_operation("list_reviews")
