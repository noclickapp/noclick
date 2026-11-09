"""Offline request contracts and documented/synthetic Memelord responses."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import memelord_node as native
from nodes.core.registry import NodeFactory

TOKEN = "mlord_live_synthetic_test_token"
CASES = [
    ("search_memes", "GET", "/api/v1/templates/search", {"query": "when the deploy works", "tags": ["coding", "work"], "limit": 5, "offset": 0, "include_nsfw": False}),
    ("get_meme_template", "GET", "/api/v1/templates/abc-123", {"template_id": "abc-123"}),
    ("get_trending_memes", "GET", "/api/v1/templates/trending", {"limit": 3, "media_type": "image"}),
    ("list_image_tools", "GET", "/api/v1/image-tools", {"category": "text-to-image"}),
    ("generate_caption_meme", "POST", "/api/v1/memes/caption", {"prompt": "developers fixing bugs at 3am", "count": 2, "caption_style": "snapchat", "use_search_context": False}),
    ("generate_ai_meme", "POST", "/api/v1/memes/ai", {"prompt": "shipping software", "count": 1, "reference_image_urls": ["https://example.test/photo.png"]}),
    ("edit_meme", "POST", "/api/v1/memes/edit", {"instruction": "make the bottom text about JavaScript instead", "edit_handle": "01234567-89ab-cdef-0123-456789abcdef", "target_index": 1}),
    ("generate_video_meme", "POST", "/api/v1/video-memes", {"prompt": "shipping on Friday", "force_caption_style": "top"}),
    ("edit_video_meme", "POST", "/api/v1/video-memes/edit", {"instruction": "mention Friday", "template_id": "abc-123", "caption": "shipping software"}),
    ("check_video_status", "GET", "/api/v1/video-jobs/render-123", {"job_id": "render-123"}),
    ("list_video_models", "GET", "/api/v1/video-models", {}),
    ("run_video_model", "POST", "/api/v1/video-models/run", {"model_id": "wan", "prompt": "a cinematic drone shot over Tokyo at night", "seed": 0, "generate_audio": False}),
    ("run_genjutsu", "POST", "/api/v1/genjutsu/run", {"video_job_id": "render-123", "characters": [{"target": "the king", "image_urls": ["https://example.test/photo.png"]}]}),
    ("run_gemini_omni", "POST", "/api/v1/gemini-omni/run", {"prompt": "make it snow", "video_job_id": "render-123"}),
    ("run_agent", "POST", "/api/v1/jester/run", {"prompt": "make a video meme about Mondays", "thread_id": "thread-123"}),
    ("run_image_tool", "POST", "/api/v1/image-tools/run", {"tool_id": "mascot-generator", "prompt": "a friendly dog", "params": {"quality": "high", "seed": 0, "transparent": False}}),
    ("get_account", "GET", "/api/v1/account", {}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **values):
    return NodeFactory.create_node(node_id="memelord-fixture", node_type="automation-memelord",
        node_data={"config": {"operation": operation, **values},
                   "credentials": {"credential_type": "memelord_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://example.test/foreign"})
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,values", CASES)
async def test_one_published_request_per_operation(monkeypatch, operation, method, path, values):
    body = {"success": True, "job_id": "render-123", "status": "processing"}
    requests = transport(monkeypatch, body)
    result = await node(operation, **values).execute({})
    assert result == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "www.memelord.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method == "POST":
        assert json.loads(request.content) == values
        assert not request.url.query
    else:
        expected = [(key, str(item).lower() if isinstance(item, bool) else str(item))
                    for key, value in values.items() if key not in {"template_id", "job_id"}
                    for item in (value if isinstance(value, list) else [value])]
        assert sorted(request.url.params.multi_items()) == sorted(expected)
        assert request.content == b""


@pytest.mark.asyncio
async def test_documented_caption_response_is_preserved(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/memelord/caption.json").read_text())
    transport(monkeypatch, fixture["body"])
    result = await node("generate_caption_meme", prompt="developers fixing bugs at 3am", count=2).execute({})
    assert result["data"] == fixture["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 402, 403, 404, 429, 500])
async def test_errors_and_redirects_do_not_claim_success(monkeypatch, status):
    requests = transport(monkeypatch, {"success": False, "code": "API_KEY_INVALID", "error": "Rejected " + TOKEN}, status)
    result = await node("get_account").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"success": False, "error": "Tool failed"}, {"status": "invalid_request", "issues": ["prompt"]}, {"status": "needs_input"}, {"status": "failed", "error": "Render failed"}])
async def test_200_tool_failures_remain_failures(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node("get_account").execute({})
    assert result["status"] == "error" and result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", ".", "a/b", "a?b", "a#b", "a\\b"])
async def test_path_injection_rejected_before_http(monkeypatch, identifier):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node("get_meme_template", template_id=identifier).execute({})
    assert requests == []


@pytest.mark.asyncio
async def test_semantic_media_and_end_user_query(monkeypatch):
    requests = transport(monkeypatch, {})
    await node("search_memes", method="semantic_media", media_url="https://example.test/input.png", end_user_id="customer:42").execute({})
    assert requests[0].url.params["end_user_id"] == "customer:42"
    assert "query" not in requests[0].url.params


@pytest.mark.asyncio
async def test_non_object_response_cannot_prove_connection(monkeypatch):
    transport(monkeypatch, [])
    with pytest.raises(ValueError, match="unexpected response shape"):
        await node("get_account").execute({})


def test_manual_key_default_and_contract_constraints():
    credential = native.MemelordAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "memelord_api_key" and credential.api_key == TOKEN
    assert native.MemelordNode.connection_evidence.identity_operation == "get_account"
    for config in [
        {"operation": "generate_caption_meme"},
        {"operation": "generate_caption_meme", "prompt": "", "count": 11},
        {"operation": "get_trending_memes", "limit": 13},
        {"operation": "search_memes", "offset": 1001},
        {"operation": "get_account", "end_user_id": "person@example.test"},
        {"operation": "edit_meme", "instruction": "edit", "edit_handle": "not-a-uuid"},
        {"operation": "run_video_model", "prompt": "test", "model_id": "invented"},
        {"operation": "get_account", "unknown": True},
    ]:
        with pytest.raises(ValidationError):
            native.MemelordFullConfig.model_validate({"config": config, "credentials": credential})
