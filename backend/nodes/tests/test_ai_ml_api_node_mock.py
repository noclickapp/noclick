"""Exercise the real node and HTTP serialization without a provider account."""
import base64
import json
import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import ai_ml_api_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-aiml-key-42"
CREDENTIAL = {"credential_type": "ai_ml_api_key", "api_key": TOKEN}
CONFIGS = {
    "create_response": {"input": "Summarize this meeting"},
    "create_chat_completion": {"messages": [{"role": "user", "content": "Hello"}]},
    "create_embeddings": {"input": ["semantic search", "workflow automation"]},
    "generate_image": {"prompt": "A small red fox"},
    "create_transcription": {"url": "https://example.com/audio/sample.mp3"},
    "get_transcription": {"generation_id": "dzIgQQyw8KCfoI5clcbHZ"},
    "create_message": {"messages": [{"role": "user", "content": "Hello"}]},
    "generate_video": {"prompt": "A red fox running through snow"},
    "get_video": {"generation_id": "60ac7c34-3224-4b14-8e7d-0aa0db708325"},
    "generate_audio": {"prompt": "Peaceful solo piano"},
    "get_audio": {"generation_id": "60ac7c34-3224-4b14-8e7d-0aa0db708325"},
    "extract_document": {"document": "https://example.com/invoice.pdf"},
}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **changes):
    return NodeFactory.create_node(node_id="aiml-fixture", node_type="automation-ai-ml-api",
        node_data={"config": {"operation": operation, **CONFIGS[operation], **changes}, "credentials": CREDENTIAL})


def transport(monkeypatch, *, status=200, body=None):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"id": "fixture", "status": "queued"} if body is None else body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_native_factory_serializes_each_operation(monkeypatch, operation):
    requests = transport(monkeypatch)
    instance = node(operation)
    result = await instance.execute({})
    assert result["status"] == "success" and result["data"]["id"] == "fixture"
    request, = requests
    method, path = native.ROUTES[operation]
    if operation == "get_transcription":
        path = "/v1/stt/" + CONFIGS[operation]["generation_id"]
    assert request.method == method and request.url.host == "api.aimlapi.com" and request.url.path == path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    payload = dict(request.url.params) if method == "GET" else json.loads(request.content)
    expected = instance.config.config.model_dump(exclude={"operation"}, exclude_none=True)
    if operation == "get_transcription":
        expected.pop("generation_id")
    assert payload == expected
    assert "operation" not in payload and "api_key" not in payload and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_connection_reads_documented_billing_account(monkeypatch):
    requests = transport(monkeypatch, body={"user_id": 42, "email": "owner@example.com", "current_balance": 3.5, "currency": "USD"})
    result = await native.AiMlApiNode.load_field_options("account", CREDENTIAL)
    assert result == [{"value": "42", "label": "owner@example.com"}]
    assert requests[0].method == "GET" and requests[0].url.path == "/v2/billing/detail"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_http_failure_never_reports_success_or_leaks_key(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={"message": "Rejected " + TOKEN})
    with pytest.raises(ValueError) as error:
        await node("create_embeddings").execute({})
    assert f"HTTP {status}" in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_in_band_error_is_not_success(monkeypatch):
    transport(monkeypatch, body={"error": {"message": "invalid key"}})
    with pytest.raises(ValueError, match="invalid key"):
        await native.AiMlApiNode.load_field_options("account", CREDENTIAL)


@pytest.mark.asyncio
async def test_billing_shape_must_identify_account(monkeypatch):
    transport(monkeypatch, body={"current_balance": 3.5})
    with pytest.raises(ValueError, match="did not identify"):
        await native.AiMlApiNode.load_field_options("account", CREDENTIAL)


@pytest.mark.asyncio
async def test_base64_images_become_binary_outputs(monkeypatch):
    pixels = b"synthetic-image-bytes"
    transport(monkeypatch, body={"data": [{"b64_json": base64.b64encode(pixels).decode()}]})
    result = await node("generate_image", response_format="b64_json", output_format="webp").execute({})
    image = result["data"]["data"][0]
    assert "b64_json" not in image and isinstance(image["file"], BinaryOutput)
    assert image["file"].data == pixels and image["file"].content_type == "image/webp"


def test_reject_invalid_role_model_path_and_music_length():
    for operation, changes in [
        ("create_message", {"messages": [{"role": "system", "content": "Hello"}]}),
        ("create_response", {"model": "made-up-model"}),
        ("create_response", {"max_output_tokens": 1}),
        ("get_transcription", {"generation_id": "../secrets"}),
        ("generate_audio", {"music_length_ms": 1}),
    ]:
        with pytest.raises(ConfigValidationError):
            node(operation, **changes)


@pytest.mark.asyncio
async def test_documented_audio_response_preserves_opaque_generation_id(monkeypatch):
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / "fixtures/ai-ml-api/audio.json").read_text())
    queued = examples["POST /v2/generate/audio"]["body"]
    completed = examples["GET /v2/generate/audio"]["body"]
    transport(monkeypatch, body=queued)
    result = await node("generate_audio").execute({})
    generation_id = result["data"]["id"]
    assert generation_id == queued["id"] and ":elevenlabs/eleven_music" in generation_id
    monkeypatch.undo()
    requests = transport(monkeypatch, body=completed)
    result = await node("get_audio", generation_id=generation_id).execute({})
    assert dict(requests[0].url.params) == {"generation_id": generation_id}
    assert result["data"] == completed and result["data"]["status"] == "completed"
