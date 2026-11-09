"""Offline request/response checks for MyCase's documented v1 contract."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import mycase_node as module
from nodes.core.registry import NodeFactory
from nodes.oauth.mycase_oauth import OAUTH_PROVIDER
from nodes.scopes.mycase import MYCASE_SCOPES

CASES = json.loads((Path(__file__).parent / "fixtures/mycase/requests.json").read_text())
CREDENTIAL = {"credential_type": "mycase_oauth", "access_token": "mycase-test-secret", "refresh_token": "mycase-refresh-secret"}


def node(config):
    return NodeFactory.create_node(node_id="mycase-test", node_type="automation-mycase",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, callback):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(callback)) as session:
            yield session
    monkeypatch.setattr(module, "guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_mycase_requests_and_responses(monkeypatch, case):
    seen = []
    def request(req):
        seen.append(req)
        assert req.method == case["method"]
        assert req.url.host == "external-integrations.mycase.com"
        assert req.url.path == case["path"]
        assert req.headers["authorization"] == "Bearer mycase-test-secret"
        assert (json.loads(req.content) if req.content else None) == case["body"]
        operation = case["config"]["operation"]
        if operation.startswith("list_"):
            data = [{"id": 123, "name": "Smith matter"}]
            if operation != "list_case_notes":
                assert dict(req.url.params) == {"page_size": "25"}
        else:
            data = {"id": 123, "email": "john@example.com"}
        return httpx.Response(204 if req.method == "PUT" else 201 if req.method == "POST" and operation != "create_case_note" else 200,
            **({} if req.method == "PUT" else {"json": data}))
    transport(monkeypatch, request)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(seen) == 1
    assert result.get("write_acknowledged", False) == (case["method"] != "GET")


@pytest.mark.asyncio
async def test_mycase_cursor_and_filters(monkeypatch):
    def request(req):
        assert req.url.params["filter[email]"] == "john@example.com"
        assert req.url.params["page_token"] == "previous"
        return httpx.Response(200, json=[{"id": 123}], headers={"Link": '<https://external-integrations.mycase.com/v1/clients?page_token=next&page_size=10>; rel="next"'})
    transport(monkeypatch, request)
    result = await node({"operation": "list_clients", "page_token": "previous", "page_size": 10, "email": "john@example.com"}).execute({})
    assert result["next_page_token"] == "next" and result["has_more"]


@pytest.mark.asyncio
@pytest.mark.parametrize("link", [
    "https://evil.example/v1/clients?page_token=next",
    "https://external-integrations.mycase.com/v1/leads?page_token=next",
    "https://external-integrations.mycase.com/v1/clients?page_token=previous",
    "https://external-integrations.mycase.com/v1/clients",
    "http://external-integrations.mycase.com/v1/clients?page_token=next",
])
async def test_mycase_refuses_unsafe_or_stalled_pagination(monkeypatch, link):
    transport(monkeypatch, lambda req: httpx.Response(200, json=[], headers={"Link": '<' + link + '>; rel="next"'}))
    assert (await node({"operation": "list_clients", "page_token": "previous"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_mycase_rejection_is_verbatim_and_redacted(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(401, json={"message": "Rejected mycase-test-secret"}))
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["http_status"] == 401
    assert result["error"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [{}, [], {"error": "Invalid token"}])
async def test_mycase_bad_identity_never_proves_connection(monkeypatch, data):
    transport(monkeypatch, lambda req: httpx.Response(200, json=data))
    assert (await node({"operation": "get_current_user"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_mycase_uncertain_write_is_not_retried(monkeypatch):
    calls = []
    def request(req):
        calls.append(req)
        raise httpx.ReadTimeout("timed out", request=req)
    transport(monkeypatch, request)
    result = await node({"operation": "create_client", "first_name": "John", "last_name": "Doe"}).execute({})
    assert result["write_outcome"] == "unverified" and len(calls) == 1


@pytest.mark.asyncio
async def test_mycase_refresh_uses_shared_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    refresh = AsyncMock(return_value="fresh-token")
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", refresh)
    transport(monkeypatch, lambda req: httpx.Response(200, json={"id": 123}))
    assert (await node({"operation": "get_current_user"}).execute({}))["status"] == "success"
    assert refresh.await_args.kwargs["provider"] == "mycase"
    freshen = AsyncMock(return_value=CREDENTIAL)
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", freshen)
    await module.MyCaseNode.freshen_credential(CREDENTIAL)
    assert freshen.await_args.kwargs["provider"] == "mycase"


@pytest.mark.parametrize("config", [
    {"operation": "get_client", "client_id": "../me"},
    {"operation": "create_client", "first_name": "John"},
    {"operation": "update_case", "case_id": 123},
    {"operation": "create_task", "name": "Task", "staff_ids": [123]},
    {"operation": "create_event", "name": "Event", "staff_ids": [123], "start": "2026-11-10T10:00:00Z", "end": "2026-11-10T09:00:00Z"},
])
def test_mycase_invalid_configs(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_mycase_declared_oauth_and_scope_contract():
    assert OAUTH_PROVIDER.authorize_url == "https://auth.mycase.com/login_sessions/new"
    assert OAUTH_PROVIDER.token_url == "https://auth.mycase.com/tokens"
    assert OAUTH_PROVIDER.identity_url == module.BASE + "/v1/me"
    assert OAUTH_PROVIDER.token_format == "json"
    assert set(MYCASE_SCOPES) == set(module.OPERATIONS) | set(module.POLL_RESOURCES)
    assert not MYCASE_SCOPES.declared_scopes()
    assert module.MyCaseOAuthCredential(access_token="real-pasted-token").credential_type == "mycase_oauth"
