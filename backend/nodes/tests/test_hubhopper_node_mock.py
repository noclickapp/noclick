"""Offline requests and polling against fields defined by Hubhopper Partner v5.

Test data below is synthetic and schema-shaped, not claimed as a live recording.
Conformance separately validates every operation against the pinned provider spec.
"""
import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes.hubhopper_node import HubhopperAPIKeyCredential, HubhopperNode, POLL_READS
from nodes.core.poll_trigger import poll_scope

CREDENTIAL = {"credential_type": "hubhopper_api_key", "api_key": "partner-access-123456", "partner_id": "partner-account-123456"}
PODCAST = {"podcastId": 91, "title": "Science Weekly", "author": "Alex", "description": "A science podcast", "url": "https://hubhopper.com/podcast/science-weekly", "latestEpisodeTime": "2026-11-11T00:00:00Z"}
EPISODE = {"episodeId": 202, "podcastId": 91, "title": "The Moon", "author": "Alex", "description": "Lunar exploration", "episodeUrl": "https://hubhopper.com/episode/the-moon", "publishedOn": 1794355200, "publishTime": "2026-11-11T00:00:00Z"}


def node(config):
    data = {"config": config, "credentials": CREDENTIAL}
    return HubhopperNode("test", "automation-hubhopper", data, config=HubhopperNode.parse_config(data))


def transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr("nodes.hubhopper_node.httpx.AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path,body", [
    ("list_categories", {}, "/categories", {"categories": [{"id": 1, "name": "Science"}]}),
    ("get_category", {"category_id": "1"}, "/categories/1", {"category": {"id": 1, "name": "Science"}}),
    ("list_category_podcasts", {"category_id": "1"}, "/categories/1/podcasts", {"podcasts": [PODCAST]}),
    ("list_podcasts", {}, "/podcasts", {"podcasts": [PODCAST]}),
    ("get_podcast", {"podcast_id": "91"}, "/podcasts/91", {"podcast": PODCAST}),
    ("list_episodes", {"podcast_id": "91"}, "/podcasts/91/episodes", {"episodes": [EPISODE]}),
    ("list_languages", {}, "/util/languages", {"languages": [{"id": 1, "name": "English", "code": "en"}]}),
])
async def test_contract_reads(monkeypatch, operation, config, path, body):
    seen = []
    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.url.host == "apis.hubhopper.com"
        assert request.url.path == "/partner" + path
        assert request.headers["x-api-key"] == CREDENTIAL["api_key"]
        assert request.headers["hhPartnerId"] == CREDENTIAL["partner_id"]
        assert "authorization" not in request.headers
        return httpx.Response(200, json=body)
    transport(monkeypatch, handler)
    assert await node({"operation": operation, **config}).execute({}) == body
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_pagination_and_filter_encoding(monkeypatch):
    def handler(request):
        assert dict(request.url.params) == {"page": "2", "pageSize": "25", "order": "newest", "filters": '{"lang":["en","hi"]}'}
        assert json.loads(request.url.params["filters"]) == {"lang": ["en", "hi"]}
        return httpx.Response(200, json={"podcasts": [], "page": 2})
    transport(monkeypatch, handler)
    await node({"operation": "list_podcasts", "page": 2, "page_size": 25, "filters_json": '{"lang": ["en", "hi"]}'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,key,item,id_field", [
    ("on_new_podcast", {}, "podcasts", PODCAST, "podcastId"),
    ("on_new_category_podcast", {"category_id": "1"}, "podcasts", PODCAST, "podcastId"),
    ("on_new_episode", {"podcast_id": "91"}, "episodes", EPISODE, "episodeId"),
])
async def test_poll_baseline_new_item_and_dedup(monkeypatch, operation, config, key, item, id_field):
    rows = [copy.deepcopy(item)]
    def handler(request):
        assert dict(request.url.params) == {"page": "1", "pageSize": "100", "order": "newest"}
        return httpx.Response(200, json={key: rows})
    transport(monkeypatch, handler)
    instance = node({"operation": operation, **config})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(state.copy())
        if new_state is not None:
            state.update(new_state)
        return result
    instance._update_node_state = update
    baseline = await instance.execute({})
    assert baseline["new_item_count"] == 0
    assert instance.trigger_produced_no_event(baseline)
    added = {**item, id_field: item[id_field] + 1, "title": "New arrival"}
    rows.insert(0, added)
    fresh = await instance.execute({})
    assert fresh[key] == [added]
    assert instance.trigger_emitted_event(fresh)
    event = HubhopperNode.resolve_agent_event(fresh)
    assert "New arrival" in event["text"] and "Alex" in event["text"] and str(added[id_field]) in event["text"]
    assert HubhopperNode.should_propagate_output(fresh, {"operation": operation})
    assert (await instance.execute({}))["new_item_count"] == 0
    assert HubhopperNode.resolve_agent_event(baseline) is None
    assert HubhopperNode.resolve_trigger_payload({"untrusted": "payload"}, config) is None


def test_poll_scope_changes_only_with_declared_watch_fields():
    base = {"operation": "on_new_episode", "podcast_id": "91"}
    assert poll_scope(HubhopperNode, base) == poll_scope(HubhopperNode, {**base, "label": "Changed", "schedule": {"frequency": "minutes", "interval": 10}})
    assert poll_scope(HubhopperNode, base) != poll_scope(HubhopperNode, {**base, "podcast_id": "92"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_http_errors_and_secrets(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, text="Denied " + CREDENTIAL["api_key"]))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_categories"}).execute({})
    assert str(status) in str(exc.value)
    assert CREDENTIAL["api_key"] not in str(exc.value)


@pytest.mark.asyncio
async def test_language_no_content(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(204))
    assert await node({"operation": "list_languages"}).execute({}) == {"languages": []}


@pytest.mark.parametrize("bad", ["../podcasts", "https://example.com", "x/y", ".."])
def test_path_ids_cannot_change_route(bad):
    with pytest.raises(ValueError):
        node({"operation": "get_podcast", "podcast_id": bad})


def test_manual_credentials_and_evidence():
    assert HubhopperAPIKeyCredential(api_key=CREDENTIAL["api_key"], partner_id=CREDENTIAL["partner_id"]).credential_type == "hubhopper_api_key"
    for field in ("api_key", "partner_id"):
        with pytest.raises(ValidationError):
            HubhopperAPIKeyCredential.model_validate({**CREDENTIAL, field: "value\r\ninjected"})
    assert HubhopperNode.connection_evidence.proves == "reachability"
    assert HubhopperNode.connection_evidence.operation == "list_categories"
    assert len(POLL_READS) == 3
