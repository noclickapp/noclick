"""Offline request and credential regressions, using synthetic response fixtures."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import google_ai_studio_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-gemini-key-42"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="gemini-test", node_type=native.GoogleAIStudioNode.integration_type,
        node_data={"config": config, "credentials": credentials or {"api_key": TOKEN, "credential_type": "google_ai_studio_api_key"}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", [
    ({"operation": "list_files", "page_token": "next+token"}, "GET", "/files", {"pageSize": "20", "pageToken": "next+token"}, None),
    ({"operation": "get_model", "model": "gemini-2.5-flash"}, "GET", "/models/gemini-2.5-flash", {}, None),
    ({"operation": "generate_content", "model": "gemini-2.5-flash", "contents": [{"parts": [{"text": "Hello"}]}], "generation_config": {"temperature": 0}}, "POST", "/models/gemini-2.5-flash:generateContent", {}, {"model": "models/gemini-2.5-flash", "contents": [{"role": "user", "parts": [{"text": "Hello"}]}], "generationConfig": {"temperature": 0}}),
    ({"operation": "embed_content", "model": "gemini-embedding-001", "content": {"parts": [{"text": "Hello"}]}, "task_type": "RETRIEVAL_QUERY"}, "POST", "/models/gemini-embedding-001:embedContent", {}, {"model": "models/gemini-embedding-001", "content": {"role": "user", "parts": [{"text": "Hello"}]}, "taskType": "RETRIEVAL_QUERY"}),
    ({"operation": "delete_store", "store_id": "my-store", "force": True}, "DELETE", "/fileSearchStores/my-store", {"force": "true"}, None),
    ({"operation": "import_file", "store_id": "my-store", "file_name": "files/abc"}, "POST", "/fileSearchStores/my-store:importFile", {}, {"fileName": "files/abc"}),
    ({"operation": "get_import_operation", "store_id": "my-store", "operation_id": "abc"}, "GET", "/fileSearchStores/my-store/operations/abc", {}, None),
])
async def test_wire_contract(monkeypatch, config, method, path, params, body):
    requests = transport(monkeypatch, {"name": "documented-resource"})
    result = await node(config).execute({})
    req = requests[0]
    assert req.method == method and req.url.path == "/v1beta" + path
    assert req.url.host == "generativelanguage.googleapis.com"
    assert dict(req.url.params) == params
    assert req.headers["x-goog-api-key"] == TOKEN
    assert (json.loads(req.content) if req.content else None) == body
    assert result["data"] == {"name": "documented-resource"}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_generate_response_envelope_and_pagination(monkeypatch):
    response = json.loads((Path(__file__).parent / "fixtures/google-ai-studio/generate.json").read_text())
    transport(monkeypatch, response)
    result = await node({"operation": "generate_content", "model": "gemini-2.5-flash", "contents": [{"parts": [{"text": "Explain how AI works in a few words"}]}]}).execute({})
    assert result["data"]["candidates"][0]["content"]["parts"][0]["text"]
    transport(monkeypatch, {"files": [], "nextPageToken": "more"})
    assert (await node({"operation": "list_files"}).execute({}))["data"]["nextPageToken"] == "more"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_provider_rejection_redacts_secret(monkeypatch, status):
    transport(monkeypatch, {"error": {"message": "Rejected " + TOKEN}}, status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_files"}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)


@pytest.mark.parametrize("identifier", ["../other", "files/abc", "abc?key=x", "https://evil.test", "abc%2fdef"])
def test_resource_ids_do_not_change_route(identifier):
    with pytest.raises(ValueError):
        node({"operation": "get_file", "file_id": identifier})


def test_manual_credential_default_and_whitespace():
    cred = native.GoogleAIStudioAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert cred.api_key == TOKEN and cred.credential_type == "google_ai_studio_api_key"
    with pytest.raises(ValidationError):
        native.GoogleAIStudioAPIKeyCredential(api_key="https://example.com/key")


@pytest.mark.asyncio
async def test_long_running_import_returns_provider_state(monkeypatch):
    transport(monkeypatch, {"name": "fileSearchStores/store/operations/op", "done": False})
    result = await node({"operation": "import_file", "store_id": "store", "file_name": "files/abc"}).execute({})
    assert result["data"]["done"] is False
    transport(monkeypatch, {"name": "fileSearchStores/store/operations/op", "done": True, "error": {"code": 3, "message": "Invalid source file"}})
    result = await node({"operation": "get_import_operation", "store_id": "store", "operation_id": "op"}).execute({})
    assert result["status"] == "error" and result["data"]["error"]["code"] == 3
