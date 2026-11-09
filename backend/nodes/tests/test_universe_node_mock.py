"""Exercise actual node execution at its HTTP boundary, including every action."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.core.registry import NodeFactory
from nodes.universe_node import UniverseNode, UniverseOAuthCredential
from nodes.oauth.universe_oauth import OAUTH_PROVIDER

CASES = json.loads((Path(__file__).parent / "fixtures/universe/requests.json").read_text())


def node(config):
    n = NodeFactory.create_node(node_id="universe-test", node_type="automation-universe", node_data={
        "config": config, "credentials": {"credential_type":"universe_oauth", "access_token":"actual-test-secret"}})
    n.emit = AsyncMock()
    return n


def mock_http(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as c:
            yield c
    monkeypatch.setattr("nodes.universe_node.guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_requests_match_published_contract(monkeypatch, case):
    calls = []
    def handler(req):
        calls.append(req)
        assert req.method == case["method"]
        assert req.url.host == "www.universe.com"
        assert req.url.path == case["path"]
        assert dict(req.url.params) == case["query"]
        assert req.headers["authorization"] == "Bearer actual-test-secret"
        if case["body"] is not None:
            assert json.loads(req.content) == case["body"]
            assert req.headers["content-type"] == "application/json; charset=UTF-8"
        else:
            assert not req.content
        return httpx.Response(200, json=case["response"])
    mock_http(monkeypatch, handler)
    n = node(case["config"])
    result = await n.execute({})
    assert result["data"] == case["response"].get("current_user", case["response"])
    assert len(calls) == 1
    n.emit.assert_awaited_once_with(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401,{"error":"invalid_token"}), (429, {"error":"rate_limit"}), (302, {}), (500,{})])
async def test_refusals_are_failures_and_writes_are_not_retried(monkeypatch, status, body):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, json=body)
    mock_http(monkeypatch, handler)
    n = node(CASES[-1]["config"])
    with pytest.raises(ValueError, match=f"Universe HTTP {status}"):
        await n.execute({})
    assert len(calls) == 1
    n.emit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"current_user":{}}, {"error":"invalid_token"}])
async def test_connection_requires_account_identity(monkeypatch, body):
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation":"get_current_user"}).execute({})


@pytest.mark.asyncio
async def test_secrets_never_reach_output(monkeypatch):
    mock_http(monkeypatch, lambda req: httpx.Response(200, json={"access_token":"different-secret", "echo":"actual-test-secret"}))
    result = await node({"operation":"get_token_info"}).execute({})
    assert result["data"] == {"echo":"[redacted]"}


def test_manual_credential_and_oauth_declaration():
    assert UniverseOAuthCredential(access_token="existing-secret").credential_type == "universe_oauth"
    assert OAUTH_PROVIDER.identity_url == "https://www.universe.com/api/v2/current_user"
    assert OAUTH_PROVIDER.name_field == "current_user.email"
    assert OAUTH_PROVIDER.scope_registry.declared_scopes() == ["public"]
    for bad in ["Bearer token", "https://example.com/token", "<token>"]:
        with pytest.raises(ValueError):
            UniverseOAuthCredential(access_token=bad)


@pytest.mark.parametrize("config", [
    {"operation":"list_guestlists", "limit":1001},
    {"operation":"create_percent_discount", "listing_id":"l", "code":"x", "percent":20},
    {"operation":"create_fixed_discount", "listing_id":"l", "code":"x", "fixed":-1},
    {"operation":"create_percent_discount", "listing_id":"l", "code":"x", "percent":0.2, "fixed":5},
    {"operation":"create_rate", "listing_id":"l", "name":"x", "price":float("nan")},
])
def test_invalid_config_rejected(config):
    with pytest.raises(ValueError):
        UniverseNode.parse_config({"config":config})


@pytest.mark.asyncio
async def test_shared_refresh_adopts_rotated_values(monkeypatch):
    async def refresh(**kwargs):
        assert kwargs["provider"] == "universe"
        kwargs["credential"].update(access_token="refreshed-test-secret", refresh_token="new-refresh")
        return "refreshed-test-secret"
    monkeypatch.setattr("nodes.universe_node.ensure_fresh_oauth_token", refresh)
    def handler(req):
        assert req.headers["authorization"] == "Bearer refreshed-test-secret"
        return httpx.Response(200, json={})
    mock_http(monkeypatch, handler)
    n = node({"operation":"get_token_info"})
    await n.execute({})
    assert n.config.credentials.refresh_token == "new-refresh"
