"""Offline MiniMax regressions: synthetic requests and provider-published responses."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import minimax_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.credential_connect import shape_credential
from nodes.core.connection_evidence import _raise_if_error_envelope, _rows_from_operation

FIXTURES = Path(__file__).parent / "fixtures" / "minimax"
CASES = json.loads((FIXTURES / "requests.json").read_text())
KEY = "synthetic-minimax-key"
HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, *, credentials=True):
    return NodeFactory.create_node(node_id="minimax-test", node_type="automation-minimax", node_data={
        "config": config,
        "credentials": {"credential_type": "minimax_api_key", "api_key": KEY} if credentials else None,
    })


def transport(monkeypatch, payload, status=200):
    requests = []
    original = HTTP_CLIENT
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


def test_minimax_registration_and_manual_credential():
    assert NODE_REGISTRY["automation-minimax"] is native.MinimaxNode
    assert native.MinimaxAPIKeyCredential(api_key=KEY).credential_type == "minimax_api_key"
    shaped, errors, _ = shape_credential("minimax_api_key", {"api_key": "  " + KEY + "\n"})
    assert not errors and shaped["api_key"] == KEY
    assert native.MinimaxNode.connection_evidence.operation == "list_files"
    for value in ["https://platform.minimax.io/", "<your-api-key>", "Bearer token"]:
        with pytest.raises(ValidationError):
            native.MinimaxAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_minimax_each_operation_one_authenticated_contract_request(monkeypatch, case):
    # Fixtures define independent expected wire bodies; responses here are synthetic.
    payload = {"base_resp": {"status_code": 0, "status_msg": "success"}, "task_id": "123"}
    requests = transport(monkeypatch, payload)
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "data": payload}
    assert len(requests) == 1
    r = requests[0]
    assert r.method == case["method"]
    assert r.url.scheme == "https" and r.url.host == "api.minimax.io"
    assert r.url.path == case["path"]
    assert dict(r.url.params) == case.get("params", {})
    assert r.headers["Authorization"] == "Bearer " + KEY
    assert r.headers["Content-Type"] == "application/json"
    assert (json.loads(r.content) if r.content else None) == case.get("body")


@pytest.mark.asyncio
async def test_minimax_empty_and_owned_files_are_connection_evidence(monkeypatch):
    for files in [[], [{"file_id": 123, "filename": "my-narration.txt"}]]:
        payload = {"files": files, "base_resp": {"status_code": 0, "status_msg": "success"}}
        requests = transport(monkeypatch, payload)
        result = await node({"operation": "list_files"}).execute({})
        _raise_if_error_envelope(result)
        assert _rows_from_operation(result) == files
        assert requests[0].method == "GET" and requests[0].url.path == "/v1/files/list"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [
    (401, {"error": {"message": "Invalid API key"}}),
    (200, {"base_resp": {"status_code": 1004, "status_msg": "Authentication failed"}}),
    (200, {"base_resp": {"status_code": 1008, "status_msg": "Insufficient balance"}}),
    (302, {}),
])
async def test_minimax_http_and_in_band_errors_cannot_claim_success(monkeypatch, status, payload):
    requests = transport(monkeypatch, payload, status)
    result = await node({"operation": "list_files"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(requests) == 1
    with pytest.raises(Exception):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
async def test_minimax_error_redacts_key_and_missing_key_makes_no_request(monkeypatch):
    requests = transport(monkeypatch, {"error": "Rejected " + KEY}, 403)
    result = await node({"operation": "list_files"}).execute({})
    assert KEY not in str(result)
    with pytest.raises(ValueError, match="Connect a MiniMax"):
        await node({"operation": "list_files"}, credentials=False).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_minimax_first_frame_video_uses_adaptive_ratio(monkeypatch):
    requests = transport(monkeypatch, {"task_id": "123"})
    await node({"operation": "create_video_task", "prompt": "A horse", "first_frame_url": "mm_file://123"}).execute({})
    body = json.loads(requests[0].content)
    assert body["ratio"] == "adaptive"
    assert body["content"][1] == {"type": "image_url", "image_url": {"url": "mm_file://123"}, "role": "first_frame"}


@pytest.mark.parametrize("changes", [
    {"model": "MiniMax-H3", "resolution": "480P"},
    {"model": "MiniMax-H3-Lite", "resolution": "2K"},
    {"model": "MiniMax-H3-Max", "duration": 4},
    {"duration": 16},
])
def test_minimax_invalid_video_combinations(changes):
    with pytest.raises(ValidationError):
        native.MinimaxCreateVideoConfig(prompt="A horse", **changes)


@pytest.mark.parametrize("operation", ["get_model", "get_video_task", "delete_video_task"])
def test_minimax_path_injection_rejected(operation):
    field = "model_id" if operation == "get_model" else "task_id"
    with pytest.raises(ValueError):
        native.MinimaxNode.parse_config({"config": {"operation": operation, field: "../other?key=1"}})


PUBLISHED = json.loads((FIXTURES / "published-responses.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [op for op in PUBLISHED if op != "design_voice"])
async def test_minimax_provider_published_response_parsers(monkeypatch, operation):
    # These bodies are copied intact, including the provider's placeholder
    # strings. sources are pinned provider OpenAPI URLs, not live account data.
    entry = PUBLISHED[operation]
    assert entry["source"].startswith("https://platform.minimax.io/docs/")
    transport(monkeypatch, entry["body"])
    config = next(c["config"] for c in CASES if c["config"]["operation"] == operation)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": entry["body"]}


@pytest.mark.asyncio
async def test_minimax_voice_preview_is_binary_output(monkeypatch):
    from nodes.core.binary_output import BinaryOutput
    transport(monkeypatch, {"voice_id": "test_voice", "trial_audio": b"ID3audio".hex()})
    result = await node({"operation": "design_voice", "prompt": "A warm narrator", "preview_text": "Hello"}).execute({})
    audio = result["data"]["trial_audio"]
    assert isinstance(audio, BinaryOutput)
    assert audio.data == b"ID3audio" and audio.content_type == "audio/mpeg"


@pytest.mark.asyncio
async def test_minimax_rejects_non_hex_voice_preview_placeholder(monkeypatch):
    # The published example literally says "hex-encoded audio"; it is not audio.
    transport(monkeypatch, PUBLISHED["design_voice"]["body"])
    with pytest.raises(ValueError, match="invalid hex preview audio"):
        await node({"operation": "design_voice", "prompt": "A narrator", "preview_text": "Hello"}).execute({})
