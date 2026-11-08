"""Salesloft's current endpoint inventory, request encodings, and OAuth rotation."""

import base64
import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes.oauth.salesloft_oauth import OAUTH_PROVIDER, refresh_access_token
from nodes.core.binary_output import BinaryOutput
from nodes.salesloft_node import CONFIG_MODELS, SALESLOFT_SCOPES, SalesloftNode, SalesloftNodeConfig
from nodes.salesloft_operations import OPERATIONS

KEY = {"credential_type": "salesloft_api_key", "api_key": "test-key"}


def node_for(operation, **fields):
    node = object.__new__(SalesloftNode)
    node._config = SalesloftNodeConfig.model_validate({
        "config": {"operation": operation, **fields}, "credentials": KEY,
    })
    node.node_data = {}
    node.user_id = None
    return node


@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.asyncio
async def test_every_current_salesloft_action_dispatches(name):
    op = OPERATIONS[name]
    fields = {key: "a/b" for key in re.findall(r"\{([^}]+)\}", op.path)}
    if op.body_type == "application/json":
        fields["body_json"] = '{"example":"value"}'
    elif op.body_type == "multipart/form-data":
        fields["form_json"] = '{"name":"Example"}'
    with patch.object(SalesloftNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"data": []}
        result = await node_for(name, **fields).execute({})
    request.assert_awaited_once()
    method, path, token, params, body, form = request.await_args.args
    assert method == op.method and token == "test-key"
    assert path.startswith("/v2/") and "{" not in path
    if fields and "a/b" in fields.values():
        assert "%2F" in path
    assert body == ({"example": "value"} if op.body_type == "application/json" else None)
    assert form == ({"name": "Example"} if op.body_type == "multipart/form-data" else None)
    assert result["data"] == {"data": []}


def test_catalog_and_connection_evidence():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 200
    assert SALESLOFT_SCOPES.keys_declared == frozenset(OPERATIONS)
    assert SalesloftNode.connection_evidence.operation == "get_me"
    assert all(op.docs_url.startswith("https://developers.salesloft.com/docs/api/") for op in OPERATIONS.values())


def test_post_bodies_from_official_endpoint_definitions():
    assert OPERATIONS["conversations_calls_create"].body_type == "application/json"
    assert OPERATIONS["conversations_calls_create"].body_required
    for name in (
        "data_control_account_and_people_redaction_create",
        "data_control_account_redaction_create",
        "data_control_people_soft_deletion_create",
        "data_control_right_to_be_forgotten_create",
    ):
        assert OPERATIONS[name].body_type == "application/json"


@pytest.mark.asyncio
async def test_multipart_form_and_file_requests():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"data": {"id": 1}})

    client = httpx.AsyncClient
    with patch("nodes.salesloft_node.httpx.AsyncClient", side_effect=lambda **kw: client(
            transport=httpx.MockTransport(respond), **kw)):
        data = await SalesloftNode._request(
            "POST", "/v2/accounts", "token", {}, None,
            {"name": "Example", "tags[]": ["a", "b"],
             "attachment": {"base64": base64.b64encode(b"clip").decode(),
                                              "filename": "clip.wav", "content_type": "audio/wav"}},
        )
    assert seen[0].headers["Authorization"] == "Bearer token"
    assert "multipart/form-data" in seen[0].headers["Content-Type"]
    assert b'clip.wav' in seen[0].content and b'Example' in seen[0].content
    assert seen[0].content.count(b'name="tags[]"') == 2
    assert data == {"data": {"id": 1}}


@pytest.mark.asyncio
async def test_json_request_and_error_detail():
    seen = []
    client = httpx.AsyncClient

    def respond(request):
        seen.append(request)
        return httpx.Response(403, json={"message": "permission denied"})

    with patch("nodes.salesloft_node.httpx.AsyncClient", side_effect=lambda **kw: client(
            transport=httpx.MockTransport(respond), **kw)):
        with pytest.raises(ValueError, match="Salesloft API error 403: permission denied"):
            await SalesloftNode._request("POST", "/v2/bulk_jobs", "token", {}, {"a": 1}, None)
    assert seen[0].headers["Content-Type"] == "application/json"
    assert seen[0].content == b'{"a":1}'


@pytest.mark.asyncio
async def test_oauth_code_exchange_and_rotating_refresh(monkeypatch):
    from urllib.parse import parse_qs
    monkeypatch.setenv("SALESLOFT_CLIENT_ID", "client")
    monkeypatch.setenv("SALESLOFT_CLIENT_SECRET", "secret")
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"name": "Benjamin Franklin"}})
        return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh",
                                         "expires_in": 7200, "scope": "people:read"})

    client = httpx.AsyncClient
    with patch("nodes.core.oauth_provider.httpx.AsyncClient", side_effect=lambda **kw: client(
            transport=httpx.MockTransport(respond), **kw)):
        minted, name = await OAUTH_PROVIDER.exchange("auth-code", "https://noclick.com/api/auth/oauth/salesloft/callback")
        refreshed = await refresh_access_token("old-refresh")
    assert minted.refresh_token == refreshed.refresh_token == "new-refresh"
    assert name == "Benjamin Franklin"
    posts = [call for call in calls if call.method == "POST"]
    assert all(str(call.url) == "https://accounts.salesloft.com/oauth/token" for call in posts)
    assert all(call.headers["Content-Type"] == "application/x-www-form-urlencoded" for call in posts)
    assert parse_qs(posts[0].content.decode())["grant_type"] == ["authorization_code"]
    assert parse_qs(posts[1].content.decode())["refresh_token"] == ["old-refresh"]
    assert str(calls[1].url) == OAUTH_PROVIDER.identity_url


@pytest.mark.asyncio
async def test_refresh_requires_successor_token(monkeypatch):
    monkeypatch.setenv("SALESLOFT_CLIENT_ID", "client")
    monkeypatch.setenv("SALESLOFT_CLIENT_SECRET", "secret")
    client = httpx.AsyncClient
    with patch("nodes.core.oauth_provider.httpx.AsyncClient", side_effect=lambda **kw: client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"access_token": "new"})), **kw)):
        with pytest.raises(ValueError, match="refresh_token"):
            await refresh_access_token("old")


@pytest.mark.asyncio
async def test_binary_response_uses_workflow_media_marker():
    client = httpx.AsyncClient
    with patch("nodes.salesloft_node.httpx.AsyncClient", side_effect=lambda **kw: client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"recording", headers={"Content-Type": "audio/wav"})), **kw)):
        result = await SalesloftNode._request("GET", "/v2/conversations/1/recording", "token", {}, None, None)
    assert isinstance(result, BinaryOutput)
    assert result.data == b"recording" and result.content_type == "audio/wav"


@pytest.mark.parametrize("raw", ["null", "[]", '"filter"'])
def test_query_requires_an_object(raw):
    with pytest.raises(ValueError, match="JSON object"):
        SalesloftNode._parse_object(raw, "Query Parameters JSON")


@pytest.mark.asyncio
async def test_execution_adopts_rotated_credential_fields():
    from nodes.salesloft_node import SalesloftOAuthCredential
    credential = SalesloftOAuthCredential(access_token="old", refresh_token="old-refresh", expires_at="2020-01-01T00:00:00Z")
    node = node_for("get_me")

    async def fresh(**kwargs):
        kwargs["credential"].update(access_token="new", refresh_token="new-refresh", expires_at="2099-01-01T00:00:00Z")
        return "new"

    with patch("nodes.core.oauth_refresh.ensure_fresh_oauth_token", side_effect=fresh):
        assert await node._token(credential) == "new"
    assert credential.access_token == "new" and credential.refresh_token == "new-refresh"
    assert credential.expires_at == "2099-01-01T00:00:00Z"
