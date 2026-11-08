"""Exercise real factory dispatch using published xAI examples, without an account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import grok_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-grok-private-key"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/grok/published_examples.json").read_text())


def node(config):
    return NodeFactory.create_node(node_id="grok-test", node_type="automation-grok", node_data={
        "config": config, "credentials": {"credential_type": "grok_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, body, status=200):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["config"]["operation"])
async def test_published_response_and_exact_request(monkeypatch, example):
    calls = transport(monkeypatch, example["response"])
    result = await node(example["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == example["response"]
    assert len(calls) == 1
    request = calls[0]
    assert request.url.host == "api.x.ai"
    expected_path = example["path"]
    for key, value in example["config"].items():
        expected_path = expected_path.replace("{" + key + "}", str(value))
    assert request.url.path == expected_path and request.method == example["method"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if example["config"]["operation"] == "create_chat_completion":
        assert json.loads(request.content) == {"messages": example["config"]["messages"], "model": "latest", "stream": False}
    if example["config"]["operation"] == "generate_image":
        assert json.loads(request.content)["response_format"] == "url"
    if example["config"]["operation"] == "create_embeddings":
        assert json.loads(request.content)["encoding_format"] == "float"


@pytest.mark.asyncio
async def test_explicit_cursor_and_filters_preserved(monkeypatch):
    calls = transport(monkeypatch, {"data": [], "pagination_token": "next-file"})
    result = await node({"operation": "list_files", "pagination_token": "previous-file", "limit": 10,
                         "filter": 'name:"quarterly report"'}).execute({})
    assert dict(calls[0].url.params) == {"pagination_token": "previous-file", "limit": "10", "order": "desc", "sort_by": "created_at", "filter": 'name:"quarterly report"'}
    assert result["data"]["pagination_token"] == "next-file"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_video_result", "get_image_result"])
async def test_pending_is_not_completed_or_retried(monkeypatch, operation):
    calls = transport(monkeypatch, None, 202)
    result = await node({"operation": operation, "request_id": "job-1"}).execute({})
    assert result == {"status": "pending", "http_status": 202, "request_id": "job-1"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_http_200_failed_generation_is_error(monkeypatch):
    transport(monkeypatch, {"status": "failed", "error": {"code": "moderation", "message": "Generation refused"}})
    result = await node({"operation": "get_video_result", "request_id": "job-1"}).execute({})
    assert result["status"] == "error" and result["error"]["code"] == "moderation"


@pytest.mark.asyncio
async def test_provider_errors_are_verbatim_with_secrets_redacted(monkeypatch):
    calls = transport(monkeypatch, {"error": "Invalid API key " + TOKEN}, 401)
    result = await node({"operation": "get_me"}).execute({})
    assert result["error"] == "Invalid API key [redacted]" and result["http_status"] == 401
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_identity_cannot_verify_connection(monkeypatch):
    transport(monkeypatch, {"unexpected": "OK"})
    with pytest.raises(ValueError, match="identity"):
        await node({"operation": "get_me"}).execute({})


@pytest.mark.parametrize("bad", ["../secret", "https://api.x.ai/v1/files/id", "x/y", "..", "x?y"])
def test_paths_are_resource_ids(bad):
    with pytest.raises(ValidationError):
        native.GetFile(file_id=bad)


def test_credential_manual_defaults_and_mutually_exclusive_context():
    credential = native.GrokAPIKeyCredential(api_key=" " + TOKEN + " ")
    assert credential.credential_type == "grok_api_key" and credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.CreateResponse(model="latest", input="hello", instructions="test", previous_response_id="r-1")
    with pytest.raises(ValidationError):
        native.GenerateImage(model="grok-imagine-image", prompt="cat", response_format="b64_json")
