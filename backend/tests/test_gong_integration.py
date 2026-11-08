"""Gong operation dispatch, account URL safety, and OAuth protocol contracts."""

import base64
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes.gong_node import CONFIG_MODELS, GONG_SCOPES, GongNode, GongNodeConfig
from nodes.gong_operations import OPERATIONS
from nodes.oauth.gong_oauth import OAUTH_PROVIDER, validate_api_base_url
from nodes.core.binary_output import BinaryOutput

OAUTH = {"credential_type": "gong_oauth", "access_token": "access", "refresh_token": "refresh",
         "expires_at": "2099-01-01T00:00:00+00:00",
         "api_base_url_for_customer": "https://company-17.api.gong.io",
         "scope": "api:workspaces:read"}
BASIC = {"credential_type": "gong_access_key", "access_key": "key",
         "access_key_secret": "secret", "api_base_url_for_customer": "https://company-17.api.gong.io"}


def node_for(operation, *, credentials=None, **fields):
    node = object.__new__(GongNode)
    node._config = GongNodeConfig.model_validate({
        "config": {"operation": operation, **fields}, "credentials": credentials or OAUTH,
    })
    node.node_data = {}
    node.user_id = None
    return node


def fields_for(op):
    fields = {name.replace("-", "_"): "id/a @b" for name, location, required, _ in op.params if required}
    if op.path == "/v2/crm/entities" and op.method == "GET":
        fields["objectsCrmIds"] = '["crm-1"]'
    if op.body == "json":
        fields["body_json"] = '{"test":"value"}'
    elif op.body == "multipart":
        fields.update(file_base64=base64.b64encode(b"test file").decode(), file_name="sample.txt")
    return fields


@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.asyncio
async def test_every_gong_action_dispatches(name):
    op = OPERATIONS[name]
    node = node_for(name, **fields_for(op))
    with patch.object(GongNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"records": []}
        result = await node.execute({})
    request.assert_awaited_once()
    method, base, path, authorization, params, body, file = request.await_args.args
    assert method == op.method
    assert base == "https://company-17.api.gong.io"
    assert authorization == "Bearer access"
    assert path.startswith("/v2/") and "{" not in path
    assert result["data"] == {"records": []}
    if op.body == "multipart":
        assert file[0] == op.file_field and file[1] == b"test file"
    if op.body == "json":
        assert body == {"test": "value"}


def test_catalog_and_scope_contract():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 60
    assert GONG_SCOPES.keys_declared == frozenset(OPERATIONS)
    assert "api:calls:read:transcript" in GONG_SCOPES.declared_scopes()
    assert GongNode.connection_evidence.operation == "list_workspaces"


@pytest.mark.asyncio
async def test_query_path_and_basic_auth():
    node = node_for("get_call", credentials=BASIC, id="a/b")
    with patch.object(GongNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"id": "1"}
        await node.execute({})
    assert request.await_args.args[:4] == (
        "GET", "https://company-17.api.gong.io", "/v2/calls/a%2Fb",
        "Basic " + base64.b64encode(b"key:secret").decode(),
    )


@pytest.mark.parametrize("bad", [
    "http://company.api.gong.io", "https://api.gong.io", "https://evil.com",
    "https://company.api.gong.io.evil.com", "https://company.api.gong.io:444",
    "https://company.api.gong.io/other", "https://user:pass@company.api.gong.io",
])
def test_reject_untrusted_customer_urls(bad):
    with pytest.raises(ValueError, match="Gong API URL"):
        validate_api_base_url(bad)


@pytest.mark.asyncio
async def test_declared_oauth_uses_basic_auth_and_token_selected_identity(monkeypatch):
    monkeypatch.setenv("GONG_CLIENT_ID", "client")
    monkeypatch.setenv("GONG_CLIENT_SECRET", "secret")
    calls = []
    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"workspaces": [{"id": "623457276584334", "name": "Some Workspace"}]})
        return httpx.Response(200, json={"access_token": "new", "refresh_token": "fresh", "expires_in": 3600,
            "api_base_url_for_customer": "https://company-17.api.gong.io", "scope": "api:workspaces:read"})
    with patch.object(type(OAUTH_PROVIDER), "_client", side_effect=lambda *_: httpx.AsyncClient(transport=httpx.MockTransport(respond))):
        tokens, name = await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/gong/callback")
    assert tokens.api_base_url_for_customer == "https://company-17.api.gong.io"
    assert name == "Some Workspace"
    assert str(calls[0].url) == "https://app.gong.io/oauth2/generate-customer-token"
    assert calls[0].headers["Authorization"] == "Basic " + base64.b64encode(b"client:secret").decode()
    assert b"grant_type=authorization_code" in calls[0].content
    assert str(calls[1].url) == "https://company-17.api.gong.io/v2/workspaces"
    assert calls[1].headers["Authorization"] == "Bearer new"


@pytest.mark.asyncio
async def test_bound_refresh_retains_customer_origin(monkeypatch):
    monkeypatch.setenv("GONG_CLIENT_ID", "client")
    monkeypatch.setenv("GONG_CLIENT_SECRET", "secret")
    with patch.object(type(OAUTH_PROVIDER), "_client", side_effect=lambda *_: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
                "access_token": "new", "refresh_token": "new-refresh", "expires_in": 3600})))):
        tokens = await OAUTH_PROVIDER.bind_refresh(OAUTH)("old-refresh")
    assert tokens.api_base_url_for_customer == OAUTH["api_base_url_for_customer"]
    assert tokens.refresh_token == "new-refresh"


@pytest.mark.asyncio
async def test_exchange_rejects_untrusted_token_origin_before_identity(monkeypatch):
    monkeypatch.setenv("GONG_CLIENT_ID", "client")
    monkeypatch.setenv("GONG_CLIENT_SECRET", "secret")
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "new", "api_base_url_for_customer": "https://evil.com"})
    with patch.object(type(OAUTH_PROVIDER), "_client", side_effect=lambda *_: httpx.AsyncClient(transport=httpx.MockTransport(respond))):
        with pytest.raises(ValueError, match="context"):
            await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/gong/callback")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_multipart_upload_and_api_error():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"requestId": "1"})

    real_client = httpx.AsyncClient
    with patch("nodes.gong_node.guarded_async_client", side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(respond), **kw)):
        await node_for("add_call_recording", id="123", file_base64="dGVzdA==", file_name="clip.wav").execute({})
    assert requests[0].url.path == "/v2/calls/123/media"
    assert b'mediaFile' in requests[0].content and b'clip.wav' in requests[0].content
    assert requests[0].headers["Authorization"] == "Bearer access"

    with patch("nodes.gong_node.guarded_async_client", side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(403, json={"message": "missing scope"})), **kw)):
        with pytest.raises(ValueError, match="Gong API error 403: missing scope"):
            await node_for("list_workspaces").execute({})


@pytest.mark.asyncio
async def test_binary_download_uses_central_output_marker():
    with patch("nodes.gong_node.guarded_async_client", side_effect=lambda **kw: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"audio", headers={"content-type": "audio/wav"})), **kw)):
        data = await GongNode._request("GET", OAUTH["api_base_url_for_customer"], "/v2/calls", "Bearer access", {}, None, None)
    assert isinstance(data, BinaryOutput)
    assert data.data == b"audio" and data.content_type == "audio/wav"


@pytest.mark.asyncio
async def test_crm_upload_sends_required_query_parameters():
    with patch.object(GongNode, "_request", new_callable=AsyncMock) as request:
        await node_for("upload_crm_data", integrationId="6286478263646", objectType="STAGE", clientRequestId="1234",
                       file_base64="e30=", file_name="stages.jsonl").execute({})
    assert request.await_args.args[4] == {"integrationId": "6286478263646", "objectType": "STAGE", "clientRequestId": "1234"}


@pytest.mark.asyncio
async def test_query_json_must_remain_an_object():
    with patch.object(GongNode, "_request", new_callable=AsyncMock) as request:
        with pytest.raises(ValueError, match="Query Parameters JSON must be a JSON object"):
            await node_for("list_workspaces", query_json="1").execute({})
    request.assert_not_awaited()
