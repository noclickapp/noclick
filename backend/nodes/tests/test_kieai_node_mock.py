"""Exercise the real factory with published examples and synthetic chat completions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import kieai_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/kieai/published_examples.json").read_text())
TOKEN = "synthetic-kieai-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None):
    return NodeFactory.create_node(node_id="kieai-fixture", node_type="automation-kieai", node_data={
        "config": {"operation": operation, **(config or {})},
        "credentials": {"credential_type": "kieai_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    original = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(EXAMPLES))
async def test_published_response_and_exact_request(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example["response"])
    result = await node(operation, example["config"]).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["method"]
    assert request.url.host == "api.kie.ai" and request.url.path == example["path"]
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    if operation == "get_task":
        assert dict(request.url.params) == {"taskId": "task_12345678"}
        assert result["completed"] is True and result["result"]["resultUrls"]
    elif operation == "transcribe_audio":
        body = json.loads(request.content)
        assert body == {"model": "nvidia/nemotron-3-5-transcribe", "input": {
            "audio_url": example["config"]["audio_url"], "timestamps": True},
            "callBackUrl": example["config"]["callback_url"]}
        assert result["completed"] is False and result["task_id"]
    elif operation.startswith("chat_") or operation == "create_kimi_response":
        body = json.loads(request.content)
        if operation != "chat_gpt_5_2":
            assert body["stream"] is False
        if operation == "create_kimi_response":
            assert body["input"] == example["config"]["prompt"]
        else:
            assert body["messages"] == [{"role": "user", "content": example["config"]["prompt"] if operation == "chat_claude_sonnet_4_6" else [{"type": "text", "text": example["config"]["prompt"]}]}]
    elif operation == "get_account_credits":
        assert result["credits"] == 100.5


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (200, {"code": 401, "msg": "Invalid API key", "data": None}),
    (200, {"code": 402, "msg": "Insufficient credits", "data": None}),
    (401, {"error": {"message": "Invalid API key"}}),
    (302, {}),
    (200, {}),
    (200, {"code": 200, "data": True}),
    (200, {"code": 200, "data": "100.5"}),
])
async def test_errors_never_prove_a_connection(monkeypatch, status, body):
    transport(monkeypatch, body, status)
    result = await node("get_account_credits").execute({})
    assert result["status"] == "error" and "credits" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["waiting", "queuing", "generating", "fail"])
async def test_task_lifecycle(monkeypatch, state):
    payload = {"code": 200, "data": {"taskId": "task-123", "state": state,
        "resultJson": None, "failMsg": "Provider task failed" if state == "fail" else None}}
    transport(monkeypatch, payload)
    result = await node("get_task", {"task_id": "task-123"}).execute({})
    assert result["completed"] == (state == "fail")
    assert result["status"] == ("error" if state == "fail" else "success")
    assert "result" not in result


@pytest.mark.asyncio
async def test_provider_error_redacts_key(monkeypatch):
    transport(monkeypatch, {"code": 401, "msg": "Rejected " + TOKEN})
    result = await node("get_account_credits").execute({})
    assert result["message"] == "Rejected [redacted]"


@pytest.mark.asyncio
async def test_translation_and_public_url_validation(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["transcribe_audio"]["response"])
    result = await node("transcribe_audio", {"audio_url": "https://example.com/audio.mp3", "target_language": "en"}).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content)["input"] == {
        "audio_url": "https://example.com/audio.mp3", "timestamps": False, "target_language": "en"}
    with pytest.raises(ValueError):
        node("transcribe_audio", {"audio_url": "https://example.com/audio.mp3", "timestamps": True, "target_language": "en"})
    with pytest.raises(ValueError, match="public HTTP"):
        await node("get_download_url", {"url": "file:///tmp/audio.mp3"}).execute({})


def test_manual_credential_default_and_secret_validation():
    credential = native.KieaiAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "kieai_api_key" and credential.api_key == TOKEN
    for value in ["https://kie.ai/api-key", "Bearer my-key", "<token>"]:
        with pytest.raises(ValidationError):
            native.KieaiAPIKeyCredential(api_key=value)
