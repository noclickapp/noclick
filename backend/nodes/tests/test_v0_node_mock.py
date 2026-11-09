"""Synthetic transport regressions; the external conformance harness owns contract validation."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from nodes import v0_node as native
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "v0_api_key", "api_key": "v0-synthetic-not-live"}
CASES = json.loads((Path(__file__).parent / "fixtures/v0/operations.json").read_text())


def transport(monkeypatch, body, status=200, content_type="application/json"):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": content_type})
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


async def run(operation, arguments=None):
    node = NodeFactory.create_node(node_id="v0-test", node_type=native.NODE_TYPE,
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": AUTH})
    return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", CASES)
async def test_v0_fixed_operation_routes(monkeypatch, operation, arguments, method, path, body):
    requests = transport(monkeypatch, body)
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.v0.dev"
    assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
    if operation == "list_messages":
        assert request.url.params["limit"] == "20"
    if operation == "update_files":
        assert json.loads(request.content)["files"][0]["content"] is None
    if operation == "create_webhook":
        assert json.loads(request.content)["chatId"] is None
    if operation == "duplicate_chat":
        assert json.loads(request.content) == {"privacy": "private"}
    if operation == "deploy_chat":
        assert request.content == b""
        assert "build_finished" not in result


@pytest.mark.asyncio
async def test_v0_query_filters_and_cursor_preserved(monkeypatch):
    requests = transport(monkeypatch, {"chats": [], "cursor": "more"})
    result = await run("list_chats", {"limit": 5, "cursor": "opaque+/=", "metadata": {"environment": "production"}, "order_by": "updatedAt", "order_direction": "asc"})
    query = requests[0].url.params
    assert query["metadata[environment]"] == "production"
    assert query["cursor"] == "opaque+/="
    assert query["orderBy"] == "updatedAt" and query["orderDirection"] == "asc"
    assert result["data"]["cursor"] == "more"


@pytest.mark.asyncio
async def test_v0_wire_names_and_nullable_metadata(monkeypatch):
    requests = transport(monkeypatch, {"id": "chat-one"})
    await run("create_chat", {"message": "Build", "system_prompt": "Use React", "model_configuration": {"modelId": "v0-pro"}})
    body = json.loads(requests[0].content)
    assert body["systemPrompt"] == "Use React"
    assert body["modelConfiguration"] == {"modelId": "v0-pro", "imageGenerations": False}
    assert body["privacy"] == "private"
    await run("update_chat", {"chat_id": "chat-one", "metadata": None})
    assert json.loads(requests[-1].content) == {"metadata": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_v0_provider_rejection_never_passes_or_exposes_key(monkeypatch, status):
    transport(monkeypatch, {"error": "Rejected " + AUTH["api_key"]}, status)
    result = await run("list_chats")
    assert result["status"] == "error" and result["http_status"] == status
    assert AUTH["api_key"] not in json.dumps(result)
    assert "Rejected" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body,content_type", [({}, "application/json"), ({"error": "denied"}, "application/json"), ({}, "text/html")])
async def test_v0_malformed_connection_response_not_empty_success(monkeypatch, body, content_type):
    transport(monkeypatch, body, content_type=content_type)
    with pytest.raises(ValueError):
        await run("list_chats")


@pytest.mark.parametrize("chat_id", ["..", "a/b", "https://evil.test", "x?key=y", "x\n"])
def test_v0_bad_resource_ids_refused(chat_id):
    with pytest.raises(ValueError):
        native.V0Node.parse_config({"config": {"operation": "get_chat", "chat_id": chat_id}, "credentials": AUTH})


def test_v0_default_credential_tag_and_unique_file_paths():
    assert native.V0APIKeyCredential(api_key=AUTH["api_key"]).credential_type == "v0_api_key"
    with pytest.raises(ValueError):
        native.UpdateFiles(chat_id="c", files=[{"path": "p", "content": "one"}, {"path": "p", "content": "two"}])
    assert set(native.ROUTES) == {case[0] for case in CASES}


def test_v0_saved_editor_config_keeps_platform_attachment_out_of_request():
    parsed = native.V0Node.parse_config({"config": {"operation": "get_chat", "chat_id": "chat-one", "credentialIds": {"v0_api_key": "saved-id"}}, "credentials": AUTH})
    assert parsed.config.chat_id == "chat-one"
    assert "credentialIds" not in parsed.config.model_dump()
