"""Exercise Hive through the real node factory with no external API calls."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError
from nodes import hive_node as hive
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "hive_api_key", "api_key": "hive-fixture-key"}
PAGE = {"edges": [{"cursor": "c1", "node": {"_id": "w1", "name": "My workspace"}}],
        "pageInfo": {"endCursor": "c1", "hasNextPage": True}}

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.headers["api_key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        assert request.url.host == "app.hive.com"
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as session:
            yield session
    monkeypatch.setattr(hive, "guarded_async_client", client)
    return requests, replies

async def run(operation, **config):
    node = NodeFactory.create_node(node_id="hive-test", node_type="automation-hive",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})
    return await node.execute({})

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("create_action", {"title": "Review", "workspace": "w1", "project_id": "p1", "assignees": ["u1"]}, "POST", "/actions", {"title": "Review", "workspace": "w1", "projectId": "p1", "assignees": ["u1"]}),
    ("update_action", {"action_id": "a1", "status": "Completed", "assignees": []}, "PUT", "/actions/a1", {"status": "Completed", "assignees": []}),
    ("create_comment", {"action_id": "a1", "body": "Done"}, "POST", "/actions/a1/comments", {"body": "Done"}),
    ("create_label", {"workspace_id": "w1", "name": "Review", "color": "#3390dc"}, "POST", "/workspaces/w1/labels", {"name": "Review", "color": "#3390dc"}),
    ("delete_action", {"action_id": "a1"}, "DELETE", "/actions/a1", None),
    ("delete_project", {"project_id": "p1"}, "DELETE", "/projects/p1", None),
])
async def test_writes_exact_wire_and_one_request(transport, operation, config, method, path, body):
    requests, replies = transport
    replies.append((200, {"message": "Success"}))
    assert (await run(operation, **config))["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v2" + path
    assert (json.loads(request.content) if request.content else None) == body

@pytest.mark.asyncio
async def test_cursor_page_preserves_resources_and_does_not_fetch_more(transport):
    requests, replies = transport
    replies.append((200, PAGE))
    result = await run("list_workspaces", first=10, after="opaque+/=")
    assert result["items"] == [{"_id": "w1", "name": "My workspace"}]
    assert result["next_cursor"] == "c1" and result["page_info"] == PAGE["pageInfo"]
    assert len(requests) == 1 and requests[0].url.params["after"] == "opaque+/="
    assert requests[0].url.params["first"] == "10"

@pytest.mark.asyncio
async def test_search_uses_offset_pagination_not_cursor(transport):
    requests, replies = transport
    replies.append((200, [{"_id": "a1", "title": "Review"}]))
    result = await run("search_actions", workspace_id="w1", search_term="Review & ship", project_id="p1", skip=20)
    assert result["items"][0]["_id"] == "a1"
    assert dict(requests[0].url.params) == {"searchTerm": "Review & ship", "projectId": "p1", "skip": "20", "limit": "20"}

@pytest.mark.asyncio
@pytest.mark.parametrize("code,payload", [(403, {"error": 403, "message": "Forbidden"}), (429, {"message": "Rate limit exceeded"}), (200, {"error": 400, "message": "Bad Request"}), (200, {"unexpected": []})])
async def test_rejected_or_malformed_reads_do_not_succeed(transport, code, payload):
    requests, replies = transport
    replies.append((code, payload))
    result = await run("list_workspaces")
    assert result["status"] == "error" and len(requests) == 1
    if "message" in payload:
        assert result["error"] == payload["message"]

@pytest.mark.parametrize("config", [
    {"operation": "get_action", "action_id": "../other"},
    {"operation": "list_workspaces", "first": 201},
    {"operation": "create_label", "workspace_id": "w1", "name": "x", "color": "red"},
    {"operation": "update_action", "action_id": "a1"},
])
def test_invalid_config_is_refused(config):
    assert hive.HiveNode.validate_config({"config": config, "credentials": AUTH})["valid"] is False

@pytest.mark.parametrize("key", ["https://example.com/key", "a\r\nb", "<token>"])
def test_credential_refuses_urls_headers_and_placeholders(key):
    with pytest.raises(ValidationError):
        hive.HiveAPIKeyCredential(api_key=key)
