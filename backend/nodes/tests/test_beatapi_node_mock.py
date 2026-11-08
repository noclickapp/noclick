"""Run native BeatAPI nodes against verbatim published response fixtures."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import beatapi_node as beatapi
from nodes.core.registry import NodeFactory
from utils import ssrf

FIXTURES = json.loads((Path(__file__).parent / "fixtures/beatapi/published_examples.json").read_text())
AUTH = {"credential_type": "beatapi_api_key", "api_key": "fixture-beatapi-secret"}


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        calls.append(request)
        assert request.url.host == "api.beatapi.io"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, response = responses.pop(0)
        return httpx.Response(code, json=response)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(beatapi, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, responses


async def run(config):
    node = NodeFactory.create_node(node_id="beatapi-fixture", node_type="automation-beatapi", node_data={"config": config, "credentials": AUTH})
    return await node.execute({})


@pytest.mark.parametrize("operation", list(FIXTURES))
async def test_published_examples(transport, operation):
    calls, responses = transport
    case = FIXTURES[operation]
    responses.append((case["http_status"], case["response"]))
    result = await run(case["config"])
    assert len(calls) == 1 and not responses
    request = calls[0]
    assert request.method == case["method"]
    path = case["path"]
    for field, value in case["config"].items():
        path = path.replace("{" + ("id" if field == "webhook_id" else field) + "}", str(value))
    assert request.url.path == path
    assert result["data"] == case["response"]["data"]
    assert result["status"] == "success"
    if request.method == "POST" and request.content:
        body = json.loads(request.content)
        for field, value in case["config"].items():
            if field not in {"operation", "task_id", "shot_id"}:
                assert body[field] == value
        assert "operation" not in body


@pytest.mark.parametrize("operation,config,method,path,body", [
    ("edit_music_video_shot", {"task_id": "task_8K2qA", "shot_id": "shot_xxx", "prompt": "Night city chorus with brighter face lighting."}, "POST", "/v1/music-video/tasks/task_8K2qA/shots/shot_xxx/edit", {"prompt": "Night city chorus with brighter face lighting."}),
    ("compose_music_video_task", {"task_id": "task_8K2qA", "shot_ids": ["shot_xxx", "shot_yyy"]}, "POST", "/v1/music-video/tasks/task_8K2qA/compose", {"shot_ids": ["shot_xxx", "shot_yyy"]}),
    ("get_music_video_shot_media", {"task_id": "task_8K2qA", "shot_id": "shot_xxx"}, "POST", "/v1/music-video/tasks/task_8K2qA/shots/shot_xxx/media", None),
    ("update_webhook", {"webhook_id": "wh_9aBcD", "status": "disabled"}, "PATCH", "/v1/webhooks/wh_9aBcD", {"status": "disabled"}),
])
async def test_path_ids_and_transport_controls_are_not_body_fields(transport, operation, config, method, path, body):
    calls, responses = transport
    status = 202 if operation in {"edit_music_video_shot", "compose_music_video_task"} else 200
    responses.append((status, {"data": {"id": "task_8K2qA"}}))
    if method == "POST" and body is not None:
        config["idempotency_key"] = "music-edit-task_8K2qA-shot_xxx-01"
    await run({"operation": operation, **config})
    assert len(calls) == 1
    request = calls[0]
    assert (request.method, request.url.path) == (method, path)
    assert (json.loads(request.content) if request.content else None) == body
    if "idempotency_key" in config:
        assert request.headers["Idempotency-Key"] == config["idempotency_key"]


async def test_usage_period_is_the_only_query_and_account_evidence(transport):
    calls, responses = transport
    responses.append((200, FIXTURES["get_usage"]["response"]))
    await run({"operation": "get_usage", "period": "7d"})
    assert dict(calls[0].url.params) == {"period": "7d"}
    assert beatapi.BeatapiNode.connection_evidence.operation == "get_usage"


async def test_failed_task_is_preserved_as_provider_state(transport):
    _, responses = transport
    data = {"id": "task_8K2qA", "status": "failed", "error_code": "processing_timeout", "retryable": True, "poll_after_seconds": 10}
    responses.append((200, {"data": data}))
    result = await run({"operation": "get_task", "task_id": "task_8K2qA"})
    assert result["data"] == data


@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500, 503])
async def test_provider_errors_and_no_automatic_write_retries(transport, status):
    calls, responses = transport
    responses.append((status, {"error": {"message": "Provider refused " + AUTH["api_key"]}}))
    with pytest.raises(ValueError) as error:
        await run({"operation": "create_image_task", "prompt": "An image"})
    assert str(status) in str(error.value)
    assert "Provider refused" in str(error.value)
    assert AUTH["api_key"] not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("response", [{}, {"data": None}, {"data": {}, "error": {"message": "Rejected"}}])
async def test_malformed_envelopes_fail(transport, response):
    _, responses = transport
    responses.append((200, response))
    with pytest.raises(ValueError, match="envelope"):
        await run({"operation": "get_usage"})


@pytest.mark.parametrize("model,config", [
    (beatapi.CreateImageTask, {"prompt": "A crane", "background": "transparent", "output_format": "jpeg"}),
    (beatapi.CreateImageTask, {"prompt": "A crane", "images": ["http://example.com/a.png"]}),
    (beatapi.CreateImageTask, {"prompt": "A crane", "images": ["https://127.0.0.1/a.png"]}),
    (beatapi.CreateVideoTask, {"prompt": "A crane", "resolution": "2K", "duration": 30}),
    (beatapi.CreateVideoTask, {"prompt": "A crane", "reference_audios": ["https://cdn.beatapi.io/a.mp3"]}),
    (beatapi.CreateVideoTask, {"prompt": "A crane", "images": ["https://cdn.beatapi.io/a.png"], "reference_images": ["https://cdn.beatapi.io/b.png"]}),
    (beatapi.CreateMusicVideoTask, {"images": ["https://cdn.beatapi.io/a.png"], "audio_url": "https://cdn.beatapi.io/a.mp3", "lip_sync": True}),
    (beatapi.GetTask, {"task_id": "../../account"}),
    (beatapi.CreateImageTask, {"prompt": "A crane", "idempotency_key": "header\r\ninjection"}),
])
def test_contract_input_rules(model, config):
    with pytest.raises(ValidationError):
        model.model_validate(config)


def test_manual_credential_default_and_cleaning():
    credential = beatapi.BeatapiAPIKeyCredential.model_validate({"api_key": "  fixture-beatapi-secret  "})
    assert credential.model_dump() == AUTH
    with pytest.raises(ValidationError):
        beatapi.BeatapiAPIKeyCredential(api_key="Bearer secret")


@pytest.mark.parametrize("config,path,query,data", [
    ({"operation": "list_models", "media_type": "video"}, "/v1/media/models", {"media_type": "video"}, {"object": "list", "data": []}),
    ({"operation": "list_effects", "output_type": "video", "category": "portrait"}, "/v1/effects", {"output_type": "video", "category": "portrait"}, {"object": "list", "data": []}),
    ({"operation": "get_effect", "effect_id": "video-muscle-max"}, "/v1/effects/video-muscle-max", {}, {"id": "video-muscle-max"}),
])
async def test_catalog_filters_and_effect_lookup(transport, config, path, query, data):
    calls, responses = transport
    responses.append((200, {"data": data}))
    result = await run(config)
    assert len(calls) == 1
    assert calls[0].method == "GET" and calls[0].url.path == path
    assert dict(calls[0].url.params) == query
    assert result["data"] == data
