"""Outreach live OpenAPI action, JSON:API request, and OAuth contracts."""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.outreach_node import CONFIG_MODELS, OUTREACH_SCOPES, OutreachNode, OutreachNodeConfig
from nodes.outreach_operations import OPERATIONS
from nodes.oauth.outreach_oauth import OAUTH_PROVIDER, refresh_access_token

OAUTH = {"credential_type": "outreach_oauth", "access_token": "access", "refresh_token": "refresh",
         "expires_at": "2099-01-01T00:00:00+00:00", "scope": "prospects.all"}


def node_for(operation, *, credentials=None, **fields):
    node = object.__new__(OutreachNode)
    node._config = OutreachNodeConfig.model_validate({
        "config": {"operation": operation, **fields}, "credentials": credentials or OAUTH,
    })
    node.node_data = {}
    node.user_id = None
    return node


def fields_for(op):
    values = {key: "id/a @b" for key in re.findall(r"\{([^}]+)\}", op.path)}
    if op.body_type == "required":
        values["body_json"] = '{"data":{"type":"prospect","attributes":{"firstName":"Test"}}}'
    return values


@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.asyncio
async def test_every_outreach_action_dispatches(name):
    op = OPERATIONS[name]
    node = node_for(name, **fields_for(op))
    with patch.object(OutreachNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"data": []}
        result = await node.execute({})
    request.assert_awaited_once()
    method, path, token, params, body = request.await_args.args
    assert method == op.method and token == "access"
    assert path.startswith("/") and "{" not in path
    if "{" in op.path:
        assert "%2F" in path
    assert params == {}
    assert body == ({"data": {"type": "prospect", "attributes": {"firstName": "Test"}}}
                    if op.body_type == "required" else None)
    assert result == {"status": "success", "operation": name, "data": {"data": []}}


def test_catalog_scope_and_credential_contract():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 254
    assert OUTREACH_SCOPES.keys_declared == frozenset((*OPERATIONS, "on_event"))
    scopes = set(OUTREACH_SCOPES.declared_scopes())
    assert "prospects.all" in scopes and "auditLogs.read" in scopes
    assert OutreachNode.connection_evidence.operation == "get_prospects"
    with pytest.raises(ValidationError):
        node_for("get_prospects", credentials={"credential_type": "outreach_api_token", "token": "x"})


def test_requested_scopes_exist_in_outreach_published_scope_list():
    published = json.loads(
        (Path(__file__).parent / "fixtures/outreach/oauth_scopes.json").read_text()
    )["scopes"]
    requested = set(OUTREACH_SCOPES.declared_scopes())
    assert len(requested) == 50
    assert requested <= set(published)
    assert OUTREACH_SCOPES.require("post_kaia_voice_imports").scopes == ("kaiaVoiceImports.write",)
    assert {scope for scope in published if scope.startswith("kaiaVoiceImports.")} == {"kaiaVoiceImports.write"}
    schema = OutreachNodeConfig.model_json_schema()
    assert set(schema["$defs"]["OutreachOAuthCredential"]["x-oauth-scopes"]) == requested
    frontend_schema = json.loads(
        (Path(__file__).parents[2] / "frontend/app/schemas/nodes/outreach.json").read_text()
    )
    assert set(frontend_schema["$defs"]["OutreachOAuthCredential"]["x-oauth-scopes"]) == requested


@pytest.mark.asyncio
async def test_path_query_body_and_validation():
    node = node_for("patch_prospects_by_id", id="prospect/x", body_json='{"data":{"type":"prospect"}}',
                    query_json=json.dumps({"filter[name]": "Acme", "page[size]": 10, "include": "account,owner", "filter[firstName][]": ["Sally", "Katie"]}))
    with patch.object(OutreachNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"data": {"id": "1"}}
        await node.execute({})
    assert request.await_args.args == (
        "PATCH", "/prospects/prospect%2Fx", "access",
        {"filter[name]": "Acme", "page[size]": "10", "include": "account,owner", "filter[firstName][]": ["Sally", "Katie"]},
        {"data": {"type": "prospect"}},
    )
    with pytest.raises(ValueError, match="JSON object"):
        await node_for("get_prospects", query_json="[]").execute({})
    with pytest.raises(ValueError, match="valid JSON"):
        await node_for("post_prospects", body_json="{").execute({})


@pytest.mark.asyncio
async def test_outreach_request_auth_and_jsonapi_headers():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"data": []}, headers={"Content-Type": "application/vnd.api+json"})
    real_client = httpx.AsyncClient
    with patch("nodes.outreach_node.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await node_for("get_prospects", query_json='{"page[size]":5}').execute({})
    assert str(calls[0].url) == "https://api.outreach.io/api/v2/prospects?page%5Bsize%5D=5"
    assert calls[0].headers["Authorization"] == "Bearer access"
    assert calls[0].headers["Accept"] == "application/vnd.api+json"
    assert result["data"] == {"data": []}


@pytest.mark.asyncio
async def test_oauth_code_exchange_and_refresh(monkeypatch):
    monkeypatch.setenv("OUTREACH_CLIENT_ID", "client")
    monkeypatch.setenv("OUTREACH_CLIENT_SECRET", "secret")
    calls = []
    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"attributes": {"name": "Foo Bar"}}]})
        return httpx.Response(200, json={"access_token": "new", "refresh_token": "fresh",
                                         "scope": "prospects.all", "expires_in": 7200})
    real_client = httpx.AsyncClient
    with patch("nodes.core.oauth_provider.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)), patch(
        "nodes.oauth.outreach_oauth.guarded_async_client", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    ):
        minted, label = await OAUTH_PROVIDER.exchange("code", "https://app.example.com/api/auth/oauth/outreach/callback")
        refreshed = await refresh_access_token("fresh")
    assert label == "Outreach organization · Foo Bar"
    assert minted.access_token == refreshed.access_token == "new"
    assert minted.scope == "prospects.all"
    assert str(calls[0].url) == "https://api.outreach.io/oauth/token"
    assert b"redirect_uri=https%3A%2F%2Fapp.example.com%2Fapi%2Fauth%2Foauth%2Foutreach%2Fcallback" in calls[0].content
    assert b"client_id=client" in calls[0].content and b"client_secret=secret" in calls[0].content
    assert b"grant_type=authorization_code" in calls[0].content
    assert calls[1].headers["Accept"] == "application/vnd.api+json"
    assert b"grant_type=refresh_token" in calls[2].content


@pytest.mark.asyncio
async def test_binary_response_uses_shared_output_marker():
    from nodes.core.binary_output import BinaryOutput

    real_client = httpx.AsyncClient
    with patch("nodes.outreach_node.httpx.AsyncClient", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=b"audio bytes", headers={"Content-Type": "audio/mpeg"})), **kw
    )):
        result = await OutreachNode._request("GET", "/kaiaRecordings/1", "access", {}, None)
    assert isinstance(result, BinaryOutput)
    assert result.data == b"audio bytes"
    assert result.content_type == "audio/mpeg"


@pytest.mark.asyncio
async def test_rotated_credential_is_adopted_after_refresh():
    node = node_for("get_prospects")

    async def fresh(**kwargs):
        kwargs["credential"].update(access_token="new", refresh_token="successor", expires_at="2100-01-01T00:00:00+00:00")
        return "new"

    with patch("nodes.core.oauth_refresh.ensure_fresh_oauth_token", side_effect=fresh):
        token = await node._authorization(node.config.credentials)
    assert token == node.config.credentials.access_token == "new"
    assert node.config.credentials.refresh_token == "successor"


@pytest.mark.asyncio
async def test_refresh_requires_successor_refresh_token(monkeypatch):
    monkeypatch.setenv("OUTREACH_CLIENT_ID", "client")
    monkeypatch.setenv("OUTREACH_CLIENT_SECRET", "secret")
    real_client = httpx.AsyncClient
    with patch("nodes.core.oauth_provider.httpx.AsyncClient", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"access_token": "new", "expires_in": 7200})), **kw
    )):
        with pytest.raises(ValueError, match="refresh_token"):
            await refresh_access_token("old")
