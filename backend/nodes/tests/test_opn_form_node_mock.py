from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes import opn_form_node as module

CREDENTIAL = {"credential_type": "opn_form_api_token", "api_token": "realistic-personal-access-token"}

async def run(monkeypatch, config, handler):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(module, "guarded_async_client", client)
    node = NodeFactory.create_node(node_id="opn-test", node_type="automation-opn-form",
        node_data={"config": config, "credentials": CREDENTIAL})
    return await node.execute({})

@pytest.mark.asyncio
async def test_opn_form_paginated_submissions(monkeypatch):
    payload = {"data": [{"id": 5, "data": {"Name": "Alice"}}], "meta": {"current_page": 2, "last_page": 3}, "links": {"next": "https://api.opnform.com/open/forms/7/submissions?page=3"}}
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/open/forms/7/submissions"
        assert dict(request.url.params) == {"page": "2", "per_page": "10", "search": "Alice", "status": "completed"}
        assert request.headers["Authorization"] == "Bearer " + CREDENTIAL["api_token"]
        return httpx.Response(200, json=payload)
    result = await run(monkeypatch, {"operation": "list_submissions", "form_id": 7, "page": 2, "per_page": 10, "search": "Alice", "status": "completed"}, handler)
    assert result["data"] == payload

@pytest.mark.asyncio
async def test_opn_form_public_submission(monkeypatch):
    import json
    def handler(request):
        assert request.url.path == "/forms/contact-us/answer"
        assert "authorization" not in request.headers
        assert json.loads(request.content) == {"field-id": "Alice"}
        return httpx.Response(200, json={"type": "success", "submission_id": "123"})
    result = await run(monkeypatch, {"operation": "create_submission", "slug": "contact-us", "body": {"field-id": "Alice"}}, handler)
    assert result["data"]["submission_id"] == "123"

@pytest.mark.asyncio
async def test_opn_form_write(monkeypatch):
    import json
    def handler(request):
        assert request.method == "PUT"
        assert request.url.path == "/open/forms/7/integrations/8"
        assert json.loads(request.content) == {"integration_id": "webhook", "status": "inactive", "data": {"webhook_url": "https://example.com/hook"}}
        return httpx.Response(200, json={"message": "Form Integration was updated."})
    assert (await run(monkeypatch, {"operation": "update_webhook", "form_id": 7, "integration_id": 8, "body": {"status": "inactive", "data": {"webhook_url": "https://example.com/hook"}}}, handler))["http_status"] == 200

@pytest.mark.asyncio
async def test_opn_form_delete_empty(monkeypatch):
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.path == "/open/forms/7"
        return httpx.Response(204)
    assert (await run(monkeypatch, {"operation": "delete_form", "form_id": 7}, handler))["data"] == {"acknowledged": True}

@pytest.mark.asyncio
async def test_opn_form_rejection_redacts_secret(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"message": "Rejected " + CREDENTIAL["api_token"]})
    with pytest.raises(ValueError, match=r"HTTP 401: Rejected \[redacted\]"):
        await run(monkeypatch, {"operation": "list_workspaces"}, handler)
