"""Offline request/response checks; provider examples are from Elai OpenAPI 1.0."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import elai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-elai-token-42"
VIDEO = "420c6769343dc7bb51513e63"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/elai/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="elai-test", node_type="automation-elai", node_data={
        "config": config, "credentials": {"credential_type": "elai_api_token", "api_token": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,key,path", [
    ({"operation": "list_videos"}, "GET /videos", "/videos"),
    ({"operation": "get_video", "video_id": VIDEO}, "GET /videos/{videoId}", "/videos/" + VIDEO),
    ({"operation": "list_avatars"}, "GET /avatars", "/avatars"),
    ({"operation": "list_voices"}, "GET /voices", "/voices"),
])
async def test_elai_documented_responses(monkeypatch, config, key, path):
    requests = transport(monkeypatch, EXAMPLES[key])
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == EXAMPLES[key]
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/api/v1" + path
    assert requests[0].headers["authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_elai_repeated_filters_preserve_boolean_and_pagination(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['GET /videos'])
    result = await node({"operation": "list_videos", "page": 2, "limit": 10,
        "status": ["validating", "moderation"], "tags": ["training", "sales"], "deleted": False}).execute({})
    assert requests[0].url.params.get_list("status") == ["validating", "moderation"]
    assert requests[0].url.params.get_list("tags") == ["training", "sales"]
    assert requests[0].url.params["deleted"] == "false"
    assert result["data"]["pages"] == 3


@pytest.mark.asyncio
async def test_elai_create_slides_and_update_false_empty_tags(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['GET /videos/{videoId}'])
    await node({"operation": "create_video", "name": "Training", "slides": [{"id": 1, "speech": "Welcome"}]}).execute({})
    body = json.loads(requests[0].content)
    assert body["slides"][0] == {"id": 1, "animation": "fade_in", "language": "English",
        "speech": "Welcome", "voiceType": "text", "voice": "en-US-AriaNeural", "voiceProvider": "azure"}
    assert requests[0].method == "POST" and "operation" not in body
    requests = transport(monkeypatch, EXAMPLES['GET /videos/{videoId}'])
    await node({"operation": "update_video", "video_id": VIDEO, "public": False, "tags": []}).execute({})
    assert requests[0].method == "PATCH" and json.loads(requests[0].content) == {"tags": [], "public": False}


@pytest.mark.asyncio
async def test_elai_render_acceptance_and_empty_deletion(monkeypatch):
    transport(monkeypatch, EXAMPLES['POST /videos/render/{videoId}'])
    result = await node({"operation": "render_video", "video_id": VIDEO}).execute({})
    assert result["data"] == {"accepted": True} and result["render_completed"] is False
    transport(monkeypatch, None)
    result = await node({"operation": "delete_video", "video_id": VIDEO}).execute({})
    assert result["data"] is None and result["deleted_video_id"] == VIDEO


@pytest.mark.asyncio
async def test_elai_text_path_source_and_translation_body(monkeypatch):
    requests = transport(monkeypatch, {})
    await node({"operation": "create_from_text", "source_type": "html", "source": "<h1>Welcome</h1>"}).execute({})
    assert requests[0].url.path == '/api/v1/videos/text/html'
    assert json.loads(requests[0].content) == {"from": "<h1>Welcome</h1>"}
    requests = transport(monkeypatch, {})
    await node({"operation": "translate_video", "video_id": VIDEO, "language": {"code": "so-So", "name": "Somali"}}).execute({})
    assert json.loads(requests[0].content) == {"language": {"code": "so-So", "name": "Somali"}}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500])
async def test_elai_errors_preserve_provider_message_and_redact(monkeypatch, status):
    transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result == {"status": "error", "http_status": status, "message": "Rejected [redacted]"}


@pytest.mark.asyncio
async def test_elai_connection_evidence_and_success_redaction(monkeypatch):
    requests = transport(monkeypatch, {"name": "Workspace admin", "apiToken": TOKEN})
    result = await node({"operation": "get_current_user"}).execute({})
    assert requests[0].url.path == '/api/v1/users/me'
    assert TOKEN not in str(result)
    assert native.ElaiNode.connection_evidence.identity_operation == "get_current_user"


@pytest.mark.parametrize('value', ['../escape', 'abc?query=1', 'abc/def', 'https://bad.test'])
def test_elai_resource_ids_cannot_change_route(value):
    with pytest.raises(ValidationError):
        native.GetVideo(video_id=value)


def test_elai_manual_credential_defaults_and_update_validation():
    cred = native.ElaiAPITokenCredential(api_token=TOKEN)
    assert cred.credential_type == 'elai_api_token'
    with pytest.raises(ValidationError):
        native.ElaiAPITokenCredential(api_token='Bearer ' + TOKEN)
    with pytest.raises(ValidationError):
        native.UpdateVideo(video_id=VIDEO)
