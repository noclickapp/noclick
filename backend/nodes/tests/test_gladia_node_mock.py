"""Exercise the registered Gladia node with offline HTTP and documented shapes."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import gladia_node as gladia
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from utils import ssrf

ID = "45463597-20b7-4af7-b3b3-f5fb778203ab"
TOKEN = "gladia-test-secret"
AUTH = {"credential_type": "gladia_api_key", "api_key": TOKEN}
AUDIO = "https://files.gladia.io/example/audio-transcription/split_infinity.wav"
JOB = {"id": ID, "request_id": "G-45463597", "version": 2, "status": "done",
       "created_at": "2023-12-28T09:04:17.210Z", "post_session_metadata": {}, "kind": "pre-recorded",
       "result": {"transcription": {"full_transcript": "Hello from Gladia."}}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.gladia.io"
        assert request.headers["x-gladia-key"] == TOKEN
        assert TOKEN not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(gladia, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(config):
    node = NodeFactory.create_node("gladia-test", "automation-gladia", {"config": config, "credentials": deepcopy(AUTH)})
    return await node.execute({})


@pytest.mark.asyncio
async def test_transcription_features_are_body_fields_and_creation_is_async(transport):
    requests, replies = transport
    replies.append((201, {"id": ID, "result_url": f"https://api.gladia.io/v2/transcription/{ID}"}))
    result = await run({"operation": "create_pre_recorded", "audio_url": AUDIO, "diarization": True,
                        "subtitles": True, "summarization": True, "sentiment_analysis": True,
                        "custom_metadata": {"customer": "123"}})
    request, = requests
    assert request.method == "POST" and request.url.path == "/v2/pre-recorded"
    body = json.loads(request.content)
    assert body["audio_url"] == AUDIO and body["diarization"] is True and body["subtitles"] is True
    assert body["summarization"] is True and body["custom_metadata"] == {"customer": "123"}
    assert "credentials" not in body and "operation" not in body and "api_key" not in body
    assert result["processing_complete"] is False and result["data"]["id"] == ID


@pytest.mark.asyncio
async def test_upload_uses_documented_json_url_mode(transport):
    requests, replies = transport
    documented = json.loads((Path(__file__).parent / "fixtures/gladia/upload.json").read_text())["body"]
    replies.append((200, documented))
    result = await run({"operation": "upload_audio", "audio_url": AUDIO})
    assert requests[0].url.path == "/v2/upload" and requests[0].method == "POST"
    assert json.loads(requests[0].content) == {"audio_url": AUDIO}
    assert result["data"] == documented


@pytest.mark.asyncio
async def test_live_region_is_query_and_session_url_survives(transport):
    requests, replies = transport
    socket = f"wss://api.gladia.io/v2/live?token={ID}"
    replies.append((201, {"id": ID, "created_at": JOB["created_at"], "url": socket}))
    result = await run({"operation": "create_live_session", "region": "eu-west", "channels": 2, "sample_rate": 48000})
    assert requests[0].url.params["region"] == "eu-west"
    body = json.loads(requests[0].content)
    assert "region" not in body and body["channels"] == 2 and body["sample_rate"] == 48000
    assert result["data"]["url"] == socket and result["processing_complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("list_pre_recorded", "/v2/pre-recorded"), ("list_live_sessions", "/v2/live"), ("list_history", "/v1/history")])
async def test_lists_preserve_results_and_page_without_following_urls(transport, operation, path):
    requests, replies = transport
    following = "https://api.gladia.io/v2/transcription?offset=20&limit=20"
    replies.append((200, {"first": following, "current": following, "next": following, "items": [JOB]}))
    result = await run({"operation": operation, "status": ["done", "error"]})
    assert len(requests) == 1 and requests[0].url.path == path
    assert requests[0].url.params.get_list("status") == ["done", "error"]
    assert result["next_offset"] == 20 and result["has_more"] is True
    assert result["items"][0]["result"]["transcription"]["full_transcript"] == "Hello from Gladia."


@pytest.mark.asyncio
@pytest.mark.parametrize("following", [None, "https://example.test/opaque-cursor", "https://api.gladia.io/v2/live?offset=0"])
async def test_terminal_or_opaque_next_is_preserved_without_inventing_offset(transport, following):
    requests, replies = transport
    replies.append((200, {"first": "https://api.gladia.io/v2/live", "current": "https://api.gladia.io/v2/live", "next": following, "items": []}))
    result = await run({"operation": "list_live_sessions"})
    assert len(requests) == 1 and result["next_offset"] is None
    assert result["has_more"] is (following is not None) and result["data"]["next"] == following


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("get_pre_recorded", "/v2/pre-recorded/"), ("get_live_session", "/v2/live/")])
async def test_get_returns_transcript(transport, operation, path):
    requests, replies = transport
    replies.append((200, JOB))
    result = await run({"operation": operation, "job_id": ID})
    assert requests[0].method == "GET" and requests[0].url.path == path + ID
    assert result["data"] == JOB


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("delete_pre_recorded", "/v2/pre-recorded/"), ("delete_live_session", "/v2/live/")])
async def test_delete_acknowledges_without_claiming_absence(transport, operation, path):
    requests, replies = transport
    replies.append((202, None))
    result = await run({"operation": operation, "job_id": ID})
    assert requests[0].method == "DELETE" and requests[0].url.path == path + ID
    assert result["deletion_acknowledged"] is True and result["absence_verified"] is False


@pytest.mark.asyncio
async def test_rejections_remain_errors_and_secrets_are_redacted(transport):
    requests, replies = transport
    replies.append((401, {"message": "gladia key not found", "debug": TOKEN}))
    result = await run({"operation": "list_pre_recorded"})
    assert len(requests) == 1 and result["status"] == "error" and result["http_status"] == 401
    assert result["error"]["message"] == "gladia key not found" and TOKEN not in json.dumps(result)


def test_registry_evidence_and_validation():
    assert NODE_REGISTRY["automation-gladia"] is gladia.GladiaNode
    assert gladia.GladiaNode.connection_evidence.operation == "list_pre_recorded"
    for config in [{"operation": "get_pre_recorded", "job_id": "../live"},
                   {"operation": "upload_audio", "audio_url": "file:///etc/passwd"},
                   {"operation": "create_live_session", "sample_rate": 12345}]:
        with pytest.raises(ValueError):
            gladia.GladiaNode.parse_config({"config": config, "credentials": AUTH})
