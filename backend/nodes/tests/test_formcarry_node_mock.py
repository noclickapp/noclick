"""Exercise Formcarry's HTTP boundary with a fake provider transport.

These tests pin bearer auth, parameter placement, pagination and API errors.
"""
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.formcarry_node import ROUTES


def node(config):
    return NodeFactory.create_node(node_id="formcarry-test", node_type="automation-formcarry", node_data={"config": config, "credentials": {"credential_type": "formcarry_api_key", "api_key": "fc_live_testkey123456789"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(ROUTES))
async def test_http_contract(monkeypatch, operation):
    method, path, query, body = ROUTES[operation]
    config = {"operation": operation}
    for field in ("form_id", "webhook_id", "submission_id", "email"):
        if "{" + field + "}" in path:
            config[field] = "me+tag@company.com" if field == "email" else "64b000000000000000000001"
    config.update({k: v for k, v in {"create_form": {"name": "Contact form"}, "add_recipient": {"email": "me@company.com"}, "create_webhook": {"url": "https://example.com/hooks/formcarry"}, "update_form": {"active": False}, "update_webhook": {"enabled": False}}.get(operation, {}).items()})
    response_body = {"data": [], "has_more": True, "next_cursor": "next"}
    def respond(request):
        assert request.method == method
        assert request.headers["Authorization"] == "Bearer fc_live_testkey123456789"
        assert request.url.host == "api.formcarry.com"
        if operation == "remove_recipient":
            assert "%2B" in request.url.raw_path.decode()
        if body:
            sent = json.loads(request.content)
            for k in body:
                if k in config:
                    assert sent[k] == config[k]
        return httpx.Response(200, json=response_body)
    import nodes.formcarry_node as module
    monkeypatch.setattr(module, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    assert await node(config).execute({}) == response_body


@pytest.mark.asyncio
async def test_rejection_and_empty_response(monkeypatch):
    import nodes.formcarry_node as module
    for status, body in [(401, {"error": {"message": "This API key or access token is unknown, revoked or expired."}}), (204, None)]:
        monkeypatch.setattr(module, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body) if body else httpx.Response(status))))
        result = await node({"operation": "delete_form", "form_id": "test"}).execute({})
        assert result["status"] == ("error" if status == 401 else "success")
        if status == 401:
            assert result["error"] == body["error"]["message"]


@pytest.mark.asyncio
async def test_optional_nulls_and_pagination(monkeypatch):
    import nodes.formcarry_node as module
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [], "next_cursor": "abc", "has_more": True})
    monkeypatch.setattr(module, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    await node({"operation": "update_form", "form_id": "test", "active": None, "folder_id": None}).execute({})
    assert json.loads(requests[-1].content) == {"folder_id": None}
    await node({"operation": "list_submissions", "form_id": "test", "cursor": "opaque+cursor", "read": "false", "limit": 10}).execute({})
    assert requests[-1].url.params["cursor"] == "opaque+cursor"
    assert requests[-1].url.params["read"] == "false"
    assert requests[-1].url.params["limit"] == "10"
