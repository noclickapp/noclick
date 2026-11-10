"""Request contract and poll behavior. Provider payloads are cited in fixtures."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import json2video_node as mod
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "json2video"
KEY = "unit-test-json2video-key"
MOVIE = {"resolution": "full-hd", "scenes": [{"elements": [{"type": "text", "text": "Hello", "duration": 5}]}]}
PROJECT = "JkGxEoPRF9EgRb32"
TEMPLATE = "LerKrmBfiqaIgBuacLWn"


def node(config):
    return NodeFactory.create_node(node_id="test-json2video", node_type="automation-json2video",
        node_data={"config": config, "credentials": {"credential_type": "json2video_api_key", "api_key": KEY}})


# Representative complete requests; this catches body/query placement, DELETE bodies and wire names.
CASES = [
    ({"operation": "create_movie", "movie_json": json.dumps(MOVIE)}, "POST", "/movies", {}, MOVIE),
    ({"operation": "get_movie", "project": PROJECT}, "GET", "/movies", {"project": PROJECT}, None),
    ({"operation": "list_movies", "from_date": "2026-05-01T00:00:00Z", "to_date": "2026-05-12T23:59:59Z", "next_token": "page2"}, "GET", "/movies", {"from": "2026-05-01T00:00:00Z", "to": "2026-05-12T23:59:59Z", "limit": "100", "next_token": "page2"}, None),
    ({"operation": "delete_movie", "project": PROJECT}, "DELETE", "/movies", {"project": PROJECT}, None),
    ({"operation": "list_templates", "tag": "marketing"}, "GET", "/templates", {"tag": "marketing"}, None),
    ({"operation": "get_template", "id": TEMPLATE}, "GET", "/templates", {"id": TEMPLATE, "scopes": "movie"}, None),
    ({"operation": "create_template", "name": "My template", "movie_json": json.dumps(MOVIE)}, "POST", "/templates", {}, {"name": "My template", "movie": MOVIE}),
    ({"operation": "update_template", "id": TEMPLATE, "name": "My template", "movie_json": json.dumps(MOVIE)}, "POST", "/templates", {"id": TEMPLATE}, {"name": "My template", "movie": MOVIE}),
    ({"operation": "duplicate_template", "id": TEMPLATE, "variables_json": '{"headline":"Hello"}'}, "POST", "/templates", {"id": TEMPLATE, "action": "duplicate"}, {"variables": {"headline": "Hello"}}),
    ({"operation": "delete_template", "id": TEMPLATE}, "DELETE", "/templates", {"id": TEMPLATE}, None),
    ({"operation": "list_library_templates"}, "GET", "/templates/library", {}, None),
    ({"operation": "get_storage"}, "GET", "/media", {}, None),
    ({"operation": "get_media_file", "path": "folder/file.jpg"}, "GET", "/media/file", {"path": "folder/file.jpg"}, None),
    ({"operation": "request_upload", "name": "photo.png", "content_type": "image/png", "size": 42}, "POST", "/media/file", {}, {"name": "photo.png", "contentType": "image/png", "size": 42}),
    ({"operation": "move_media_file", "name": "photo.png", "destination": "/"}, "PUT", "/media/file", {}, {"name": "photo.png", "destination": ""}),
    ({"operation": "delete_media_file", "name": "photo.png", "folder": "temp"}, "DELETE", "/media/file", {}, {"name": "photo.png", "folder": "temp"}),
    ({"operation": "list_media_folder", "q": "photo"}, "GET", "/media/folder", {"path": "/", "page": "0", "page_size": "20", "q": "photo"}, None),
    ({"operation": "create_media_folder", "folder": "marketing/2025"}, "POST", "/media/folder", {}, {"folder": "marketing/2025"}),
    ({"operation": "delete_media_folder", "folder": "marketing/2025"}, "DELETE", "/media/folder", {}, {"folder": "marketing/2025"}),
    ({"operation": "render_subtitles", "srt": "1\n00:00:00,000 --> 00:00:02,000\nHello", "subtitles_json": '{"settings":{"style":"classic"}}'}, "POST", "/subtitles", {}, {"srt": "1\n00:00:00,000 --> 00:00:02,000\nHello", "resolution": "full-hd", "subtitles": {"settings": {"style": "classic"}}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_json2video_requests(monkeypatch, config, method, path, query, body):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == method
        assert str(request.url).split("?")[0] == mod.BASE + path
        assert dict(request.url.params) == query
        assert request.headers["x-api-key"] == KEY
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200, json={"success": True, "project": PROJECT})
    monkeypatch.setattr(mod, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle), **kw))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1  # Writes are never silently retried.


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,expected", [
    (401, {"message": "Invalid API key"}, "Invalid API key"),
    (200, {"success": False, "message": "Movie not found"}, "Movie not found"),
    (500, {"error": KEY}, "[redacted]"),
])
async def test_json2video_errors(monkeypatch, status, body, expected):
    monkeypatch.setattr(mod, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)), **kw))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_storage"}).execute({})
    assert expected in str(exc.value)
    assert KEY not in str(exc.value)


@pytest.mark.asyncio
async def test_json2video_documented_movie_poll(monkeypatch):
    fixture = json.loads((FIXTURES / "movies.json").read_text())
    movie = fixture["single"]["movie"]
    listing = fixture["list"]
    calls = []
    pages = [dict(listing, movies=[movie], has_next=True, next_token="next"), dict(listing, movies=[], has_next=False, next_token=None)]
    async def request(key, method, path, **kwargs):
        assert key == KEY and method == "GET" and path == "/movies"
        calls.append(kwargs["params"])
        return pages[(len(calls)-1) % 2]
    monkeypatch.setattr(mod.JSON2VideoNode, "_request", staticmethod(request))
    instance = node({"operation": "on_new_movie", "lookback_days": 7})
    state = {}
    async def update(mutator, **kwargs):
        replacement, result = mutator(state.copy())
        if replacement is not None:
            state.clear(); state.update(replacement)
        return result
    instance._update_node_state = update
    baseline = await instance.execute({})
    assert baseline["movies"] == []
    assert calls[1]["next_token"] == "next"  # Short page still follows has_next.
    assert "next_token" not in calls[0]
    assert "from" in calls[0] and "to" in calls[0]
    state["seen_ids"] = []
    fresh = await instance.execute({})
    assert fresh["movies"] == [movie]
    event = mod.JSON2VideoNode.resolve_agent_event(fresh)
    assert PROJECT in event["text"] and movie["url"] in event["text"]
    assert (await instance.execute({}))["movies"] == []
    assert instance.trigger_produced_no_event({})


@pytest.mark.asyncio
async def test_json2video_bad_cursor_never_updates_seen(monkeypatch):
    async def request(*args, **kw):
        return {"movies": [], "has_next": True, "next_token": "repeated"}
    monkeypatch.setattr(mod.JSON2VideoNode, "_request", staticmethod(request))
    with pytest.raises(ValueError, match="repeated page token"):
        await node({"operation": "on_new_movie"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["not json", "[]", "null"])
async def test_json2video_invalid_movie_json_never_requests(monkeypatch, value):
    async def forbidden(*args, **kw):
        pytest.fail("Invalid movie JSON made an API call")
    monkeypatch.setattr(mod.JSON2VideoNode, "_request", staticmethod(forbidden))
    with pytest.raises(ValueError, match="JSON"):
        await node({"operation": "create_movie", "movie_json": value}).execute({})


def test_json2video_manual_credential():
    assert mod.JSON2VideoAPIKeyCredential(api_key=KEY).credential_type == "json2video_api_key"
    assert mod.JSON2VideoAPIKeyCredential.model_fields["credential_type"].default == "json2video_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", list(json.loads((FIXTURES / "responses.json").read_text())))
async def test_json2video_preserves_documented_response(monkeypatch, selector):
    documented = json.loads((FIXTURES / "responses.json").read_text())[selector]
    method, route = selector.split(" ", 1)
    monkeypatch.setattr(mod, "guarded_async_client", lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=documented["body"])), **kw))
    assert await mod.JSON2VideoNode._request(KEY, method, route) == documented["body"]


@pytest.mark.asyncio
async def test_json2video_finished_trigger_detects_status_transition(monkeypatch):
    fixture = json.loads((FIXTURES / "movies.json").read_text())
    movie = fixture["single"]["movie"]
    current = dict(movie, status="running")
    async def request(*args, **kwargs):
        return {"movies": [current], "has_next": False}
    monkeypatch.setattr(mod.JSON2VideoNode, "_request", staticmethod(request))
    instance = node({"operation": "on_movie_finished"})
    state = {}
    async def update(mutator, **kw):
        replacement, result = mutator(state.copy())
        if replacement is not None:
            state.clear(); state.update(replacement)
        return result
    instance._update_node_state = update
    assert (await instance.execute({}))["movies"] == []
    current.update(movie)
    result = await instance.execute({})
    assert result["movies"] == [movie]
    assert "finished" in mod.JSON2VideoNode.resolve_agent_event(result)["text"]
    assert instance.should_propagate_output(result, {"operation": "on_movie_finished"})
    assert (await instance.execute({}))["movies"] == []
