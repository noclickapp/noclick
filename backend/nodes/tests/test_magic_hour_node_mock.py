"""Exercise every operation against independently pinned provider examples."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.magic_hour_node import MagicHourNode, MagicHourFullConfig, MagicHourAPIKeyCredential

SPEC = json.loads((Path(__file__).parent / "fixtures/magic-hour/openapi.json").read_text())
# Explicit bindings make accidental changes to a node's route table observable.
BINDINGS = {
    "get_account": ("GET", "/v1/account"),
    "list_saved_items": ("GET", "/v1/saved-items"),
    "list_voices": ("GET", "/v1/voices"),
    "create_upload_urls": ("POST", "/v1/files/upload-urls"),
    **{f"{verb}_{kind}_project": (verb.upper() if verb == "get" else "DELETE", f"/v1/{kind}-projects/{{id}}")
       for kind in ("video", "image", "audio") for verb in ("get", "delete")},
    **{op: ("POST", "/v1/" + path) for op, path in [
        ("create_text_to_video", "text-to-video"), ("create_image_to_video", "image-to-video"),
        ("create_lip_sync", "lip-sync"), ("create_face_swap_video", "face-swap"),
        ("create_talking_photo", "ai-talking-photo"), ("create_subtitles", "auto-subtitle-generator"),
        ("upscale_video", "ai-video-upscaler"), ("generate_images", "ai-image-generator"),
        ("edit_images", "ai-image-editor"), ("upscale_image", "ai-image-upscaler"),
        ("remove_image_background", "image-background-remover"), ("create_face_swap_photo", "face-swap-photo"),
        ("generate_speech", "ai-voice-generator"), ("generate_music", "ai-music-generator"),
    ]},
}


def example(schema):
    if "example" in schema:
        return schema["example"]
    if schema.get("type") == "object":
        return {key: example(value) for key, value in schema.get("properties", {}).items()
                if key in schema.get("required", []) or "example" in value}
    if schema.get("type") == "array":
        return [example(schema["items"])]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    return {"string": "example", "number": 1, "integer": 1, "boolean": False}[schema["type"]]


def config_for(op):
    method, path = BINDINGS[op]
    doc = SPEC["paths"][path][method.lower()]
    if method == "POST":
        return {"operation": op, **example(doc["requestBody"]["content"]["application/json"]["schema"])}
    return {"operation": op, **{p["name"]: example(p["schema"]) for p in doc.get("parameters", [])
                               if p.get("required") or "example" in p["schema"]}}


def node(config):
    return MagicHourNode(node_id="test", node_type="automation-magic-hour", node_data={}, sio=Mock(),
                         config=MagicHourFullConfig(config=config, credentials={"api_key": "mhk_live_testkey"}))


def mock_client(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as value:
            yield value
    monkeypatch.setattr("nodes.magic_hour_node.guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("op", BINDINGS)
async def test_documented_operation(op, monkeypatch):
    method, path = BINDINGS[op]
    config = config_for(op)
    doc = SPEC["paths"][path][method.lower()]
    status = next(int(key) for key in doc["responses"] if key.startswith("2"))
    content = doc["responses"][str(status)].get("content", {})
    body = example(content["application/json"]["schema"]) if content else None
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == method
        assert request.url.host == "api.magichour.ai"
        assert request.url.path == path.replace("{id}", config.get("id", ""))
        assert request.headers["Authorization"] == "Bearer mhk_live_testkey"
        expected = {key: value for key, value in config.items() if key not in {"operation", "id"}}
        if method == "POST":
            assert json.loads(request.content) == expected
        else:
            assert dict(request.url.params) == {key: str(value) for key, value in expected.items()}
        return httpx.Response(status, json=body) if content else httpx.Response(status)

    mock_client(monkeypatch, handler)
    result = await node(config).execute({})
    assert result == ({"data": body} if content else {"deleted": True})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 404, 422, 429, 500])
async def test_provider_rejections_remain_errors(status, monkeypatch):
    mock_client(monkeypatch, lambda request: httpx.Response(status, json={"code": "unauthorized", "message": "Rejected"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_cursor_and_provider_job_error_preserved(monkeypatch):
    payload = {"items": [], "next_cursor": "next/page+cursor"}
    def handler(request):
        assert request.url.params["cursor"] == "previous/page+cursor"
        assert request.url.params["limit"] == "2"
        return httpx.Response(200, json=payload)
    mock_client(monkeypatch, handler)
    assert await node({"operation": "list_saved_items", "cursor": "previous/page+cursor", "limit": 2}).execute({}) == {"data": payload}
    payload = {"status": "error", "error": {"code": "no_source_face", "message": "No face"}}
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=payload))
    assert await node({"operation": "get_image_project", "id": "project"}).execute({}) == {"data": payload}


@pytest.mark.parametrize("config", [
    {"operation": "generate_images", "image_count": 0, "style": {"prompt": "hello"}},
    {"operation": "create_lip_sync", "start_seconds": 5, "end_seconds": 5, "assets": {"audio_file_path": "file.mp3", "video_source": "file", "video_file_path": "file.mp4"}},
    {"operation": "create_lip_sync", "start_seconds": 0, "end_seconds": 5, "assets": {"audio_file_path": "file.mp3", "video_source": "file"}},
    {"operation": "create_face_swap_photo", "assets": {"target_file_path": "file.png"}},
    {"operation": "list_voices", "limit": 101},
    {"operation": "generate_music", "duration": 10, "style": {"prompt": "music"}},
    {"operation": "get_account", "unknown": "field"},
])
def test_reject_invalid_configs(config):
    with pytest.raises(ValidationError):
        node(config)


def test_manual_credential_and_evidence():
    credential = MagicHourAPIKeyCredential(api_key=" mhk_live_testkey ")
    assert credential.credential_type == "magic_hour_api_key"
    assert credential.api_key == "mhk_live_testkey"
    assert MagicHourNode.connection_evidence.identity_operation == "get_account"
