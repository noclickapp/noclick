"""Synthetic responses shaped by the provider OpenAPI; no live key is used."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import zeno_node as native
from nodes.core.registry import NodeFactory

TOKEN = "zeno-test-api-key-12345"
ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=True):
    return NodeFactory.create_node(node_id="zeno-test", node_type="automation-zeno", node_data={
        "config": config, "credentials": {"credential_type": "zeno_api_key", "api_key": TOKEN} if credentials else None,
    })


def transport(monkeypatch, respond):
    requests = []
    def reply(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return ASYNC_CLIENT(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
async def test_account_read_auth_and_page(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=[{"key": "show-a", "title": "Morning Show"}]))
    result = await node({"operation": "list_podcasts", "limit": 25, "offset": 50}).execute({})
    assert result["data"][0]["title"] == "Morning Show"
    assert requests[0].url.path == "/podcast-bot/podcasts/list"
    assert dict(requests[0].url.params) == {"limit": "25", "offset": "50"}
    assert requests[0].headers["x-api-key"] == TOKEN
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(("operation", "method", "route"), [
    ("publish_episode", "PUT", "/publish"), ("unpublish_episode", "PUT", "/unpublish"),
    ("reprocess_episode", "POST", "/reprocess"), ("create_episode_video", "POST", "/createVideo"),
    ("create_episode_clips", "POST", "/autoClips"), ("delete_episode", "DELETE", ""),
])
async def test_episode_writes_and_optional_stored_config(monkeypatch, operation, method, route):
    requests = transport(monkeypatch, lambda _: httpx.Response(200))
    result = await node({"operation": operation, "podcast_key": "show-1", "episode_key": "ep-1"}).execute({})
    assert requests[0].method == method
    assert requests[0].url.path == "/podcast-bot/podcasts/show-1/episodes/ep-1" + route
    assert requests[0].content == b""
    assert result == {"data": None, "request_accepted": True}


@pytest.mark.asyncio
async def test_update_full_document_body_and_text_transcript(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"title": "New Title"}))
    body = {"title": "New Title", "description": "Daily radio", "language": "en", "ownerName": "Radio", "ownerEmail": "radio@example.org", "categories": ["News"], "explicit": False}
    await node({"operation": "update_podcast", "podcast_key": "show-1", **body}).execute({})
    assert requests[0].method == "PUT" and json.loads(requests[0].content) == body
    transport(monkeypatch, lambda _: httpx.Response(200, text="Welcome to today's show"))
    result = await node({"operation": "get_transcript", "podcast_key": "show-1", "episode_key": "ep-1"}).execute({})
    assert result["data"] == "Welcome to today's show"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_errors_do_not_become_success_or_leak_key(monkeypatch, status):
    transport(monkeypatch, lambda _: httpx.Response(status, json={"message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_podcasts"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_missing_credential_never_sends(monkeypatch):
    requests = transport(monkeypatch, lambda _: pytest.fail("must not call provider"))
    with pytest.raises(ValueError, match="Connect a Zeno"):
        await node({"operation": "list_podcasts"}, credentials=False).execute({})
    assert requests == []


def test_manual_default_and_required_config():
    assert native.ZenoAPIKeyCredential(api_key=TOKEN).credential_type == "zeno_api_key"
    with pytest.raises(ValidationError):
        native.ZenoAPIKeyCredential(api_key="bad\nkey")
    assert not native.ZenoNode.validate_config({"config": {"operation": "get_episode"}})["valid"]
    assert not native.ZenoNode.validate_config({"config": {"operation": "list_podcasts", "limit": 501}})["valid"]


@pytest.mark.asyncio
async def test_poll_baseline_dedup_new_video_and_agent_event(monkeypatch):
    rows = [{"id": 1, "episodeKey": "ep-1", "name": "Morning Show", "aspectRatio": "16:9", "fileUrl": "https://example.org/video.mp4"}]
    transport(monkeypatch, lambda _: httpx.Response(200, json={"data": rows, "total": len(rows)}))
    instance = node({"operation": "on_new_video", "podcast_key": "show-1"})
    state = {}
    async def update(mutator, **_):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result
    instance._update_node_state = update
    baseline = await instance.execute({})
    assert baseline["videos"] == [] and instance.trigger_produced_no_event(baseline)
    assert native.ZenoNode.resolve_agent_event(baseline) is None
    rows.append({"id": 2, "episodeKey": "ep-2", "name": "Evening Show", "aspectRatio": "1:1", "fileUrl": "https://example.org/new.mp4"})
    output = await instance.execute({})
    assert output["videos"] == [rows[1]] and instance.trigger_emitted_event(output)
    event = native.ZenoNode.resolve_agent_event(output)
    assert all(value in event["text"] for value in ("show-1", "ep-2", "Evening Show", "https://example.org/new.mp4"))
    assert (await instance.execute({}))["videos"] == []


@pytest.mark.asyncio
async def test_poll_incomplete_page_does_not_advance_state(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={"data": [], "total": 1}))
    with pytest.raises(ValueError, match="incomplete"):
        await node({"operation": "on_new_video", "podcast_key": "show-1"}).execute({})
