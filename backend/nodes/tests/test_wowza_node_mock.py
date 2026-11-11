"""Wowza request contracts, manual credentials, and scheduled video detection."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import wowza_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

TOKEN = "synthetic-wowza-access-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=True):
    return NodeFactory.create_node(node_id="wowza-fixture", node_type="automation-wowza", node_data={
        "config": config,
        **({"credentials": {"credential_type": "wowza_access_token", "access_token": TOKEN}} if credentials else {}),
    })


def wire(monkeypatch, status=200, body=None, handler=None):
    requests = []

    def respond(request):
        requests.append(request)
        if handler:
            return handler(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(status)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("list_live_streams", "GET", "/live_streams"),
    ("get_live_stream", "GET", "/live_streams/abc123"),
    ("create_live_stream", "POST", "/live_streams"),
    ("update_live_stream", "PATCH", "/live_streams/abc123"),
    ("delete_live_stream", "DELETE", "/live_streams/abc123"),
    ("start_live_stream", "PUT", "/live_streams/abc123/start"),
    ("stop_live_stream", "PUT", "/live_streams/abc123/stop"),
    ("reset_live_stream", "PUT", "/live_streams/abc123/reset"),
    ("get_live_stream_state", "GET", "/live_streams/abc123/state"),
    ("list_transcoders", "GET", "/transcoders"),
    ("get_transcoder", "GET", "/transcoders/abc123"),
    ("start_transcoder", "PUT", "/transcoders/abc123/start"),
    ("stop_transcoder", "PUT", "/transcoders/abc123/stop"),
    ("start_recording", "PUT", "/transcoders/abc123/start_recording"),
    ("stop_recording", "PUT", "/transcoders/abc123/stop_recording"),
    ("get_transcoder_state", "GET", "/transcoders/abc123/state"),
    ("list_videos", "GET", "/videos"),
    ("get_video", "GET", "/videos/abc123"),
    ("update_video", "PATCH", "/videos/abc123"),
    ("delete_video", "DELETE", "/videos/abc123"),
    ("list_schedules", "GET", "/schedules"),
    ("get_schedule", "GET", "/schedules/abc123"),
    ("enable_schedule", "PUT", "/schedules/abc123/enable"),
    ("disable_schedule", "PUT", "/schedules/abc123/disable"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path", CASES)
async def test_operation_contract_request(monkeypatch, operation, method, path):
    config = {"operation": operation}
    if "abc123" in path:
        config["id"] = "abc123"
    if operation.startswith("list_"):
        config.update(page=2, per_page=25)
    if operation == "create_live_stream":
        config.update(name="My Live Stream", broadcast_location="eu_germany", encoder="other_rtmp", recording=False)
    if operation.startswith("update_"):
        config.update(name="Updated name", description="Updated description")
    deleting = method == "DELETE"
    requests = wire(monkeypatch, 204 if deleting else 200, {"state": "started"})
    result = await node(config).execute({})
    assert result == ({"success": True} if deleting else {"state": "started"})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.video.wowza.com"
    assert request.url.path == "/api/beta" + path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == ({"page": "2", "per_page": "25"} if operation.startswith("list_") else {})
    if operation in {"create_live_stream", "update_live_stream", "update_video"}:
        wrapper = "video" if operation == "update_video" else "live_stream"
        assert json.loads(request.content) == {wrapper: {k: v for k, v in config.items() if k not in {"id", "operation"}}}
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_video_filters_and_explicit_false_are_preserved(monkeypatch):
    requests = wire(monkeypatch, body={"videos": []})
    await node({"operation": "list_videos", "created_at": "2024-01-01T00:00:00", "state": "FINISHED",
                "sort_column": "created_at", "sort_direction": "desc", "query": "foo:name,custom_fields"}).execute({})
    assert requests[0].url.params["query"] == "foo:name,custom_fields"
    assert requests[0].url.params["created_at"] == "2024-01-01T00:00:00"
    await node({"operation": "update_video", "id": "abc123", "published": False, "tags": []}).execute({})
    assert json.loads(requests[1].content) == {"video": {"published": False, "tags": []}}


@pytest.mark.parametrize("token", ["<token>", "https://example.com/token", "Bearer abc", "a\nb"])
def test_invalid_manual_credentials(token):
    with pytest.raises(ValidationError):
        native.WowzaAccessToken(access_token=token)


def test_manual_type_default_and_operation_validation():
    assert native.WowzaAccessToken(access_token=TOKEN).credential_type == "wowza_access_token"
    for config in [{"operation": "get_video", "id": "../other"}, {"operation": "list_videos", "page": 0},
                   {"operation": "create_live_stream", "name": "Missing encoder"},
                   {"operation": "update_video", "id": "abc123"}]:
        with pytest.raises(ValueError, match="Invalid configuration"):
            native.WowzaNode.parse_config({"config": config})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_provider_errors_are_visible_and_redacted(monkeypatch, status):
    wire(monkeypatch, status, {"meta": {"message": "Rejected " + TOKEN}})
    with pytest.raises(ValueError, match="Rejected") as exc:
        await node({"operation": "list_live_streams"}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_missing_credentials_and_connection_read(monkeypatch):
    requests = wire(monkeypatch, body={"live_streams": []})
    with pytest.raises(ValueError, match="Connect"):
        await node({"operation": "list_live_streams"}, credentials=False).execute({})
    assert not requests
    assert native.WowzaNode.connection_evidence.operation == "list_live_streams"
    assert await node({"operation": "list_live_streams"}).execute({}) == {"live_streams": []}


@pytest.mark.asyncio
async def test_response_redaction(monkeypatch):
    wire(monkeypatch, body={"live_stream": {"name": TOKEN, "access_token": TOKEN}})
    assert TOKEN not in str(await node({"operation": "get_live_stream", "id": "abc123"}).execute({}))


@pytest.mark.asyncio
async def test_poll_baseline_new_video_dedup_and_agent_event(monkeypatch):
    # Values copied from the provider's VideoListModel schema examples in the pinned contract.
    video = json.loads((Path(__file__).parent / "fixtures/wowza/video.json").read_text())["body"]
    requests = wire(monkeypatch, body={"videos": [video], "pagination": {"total_pages": 1}})
    instance = node({"operation": "on_new_video", "created_at": "2024-01-01T00:00:00"})
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        changed, result = mutator(state)
        if changed is not None:
            state = changed
        return result

    monkeypatch.setattr(instance, "_update_node_state", update)
    assert (await instance.execute({}))["new_video_count"] == 0
    assert instance.trigger_produced_no_event({})
    state["seen_ids"] = []
    result = await instance.execute({})
    assert result == {"videos": [video], "new_video_count": 1}
    assert instance.trigger_emitted_event(result)
    event = instance.resolve_agent_event(result)
    assert video["name"] in event["text"] and video["id"] in event["text"]
    assert (await instance.execute({}))["new_video_count"] == 0
    assert requests[0].url.params["sort_column"] == "created_at"
    assert requests[0].url.params["created_at"] == "2024-01-01T00:00:00"
    assert poll_scope(native.WowzaNode, {"operation": "on_new_video"}) != poll_scope(native.WowzaNode, {"operation": "on_new_video", "created_at": "2024-01-01T00:00:00"})


@pytest.mark.asyncio
async def test_poll_all_pages_before_state_write_and_fail_closed(monkeypatch):
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"videos": [{"id": str(page), "name": "Video"}], "pagination": {"total_pages": 2}})

    requests = wire(monkeypatch, handler=handler)
    instance = node({"operation": "on_new_video"})
    captured = []

    async def fresh(rows, key):
        captured.extend(key(row) for row in rows)
        return rows

    monkeypatch.setattr(instance, "_filter_unseen", fresh)
    assert (await instance.execute({}))["new_video_count"] == 2
    assert len(requests) == 2 and captured == ["1", "2"]
    wire(monkeypatch, body={"videos": [{"name": "No ID"}], "pagination": {"total_pages": 1}})
    with pytest.raises(ValueError, match="usable IDs"):
        await instance.execute({})
    assert captured == ["1", "2"]
    wire(monkeypatch, body={"videos": [], "pagination": {"total_pages": 11}})
    with pytest.raises(ValueError, match="10,000"):
        await instance.execute({})


@pytest.mark.asyncio
async def test_documented_invalid_token_error(monkeypatch):
    example = json.loads((Path(__file__).parent / "fixtures/wowza/invalid_token.json").read_text())["body"]
    wire(monkeypatch, 401, example)
    with pytest.raises(ValueError, match="Token is invalid"):
        await node({"operation": "list_live_streams"}).execute({})
