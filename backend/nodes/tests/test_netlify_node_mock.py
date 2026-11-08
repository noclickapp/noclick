"""Netlify action and OAuth transport contracts against the pinned API spec."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from nodes.netlify_node import CATALOG, CONFIG_MODELS, NetlifyNode, NetlifyNodeConfig
from nodes.oauth import netlify_oauth


def _mock_client(monkeypatch, handler):
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_catalog_covers_pinned_json_rest_actions():
    assert CATALOG["source_version"] == "2.60.0"
    assert len(CATALOG["operations"]) == 176
    assert len(CATALOG["excluded"]) == 5
    assert set(CONFIG_MODELS) == {op["name"] for op in CATALOG["operations"]} | {
        "test_connection"
    }
    assert all(item["reason"] == "binary upload" for item in CATALOG["excluded"])


def _node(operation, fields=None):
    return NetlifyNode(
        node_id="netlify-qa",
        node_type="netlify",
        node_data={},
        config=NetlifyNodeConfig(
            config={"operation": operation, **(fields or {})},
            credentials={
                "credential_type": "netlify_pat",
                "access_token": "synthetic-netlify-token",
            },
        ),
    )


@pytest.mark.asyncio
async def test_list_sites_uses_bearer_token_and_documented_query(monkeypatch):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == "https://api.netlify.com/api/v1/sites?name=qa"
        assert request.headers["authorization"] == "Bearer synthetic-netlify-token"
        return httpx.Response(200, json=[{"id": "site-1", "name": "qa"}])

    _mock_client(monkeypatch, handler)
    result = await _node("list_sites", {"query_json": '{"name":"qa"}'}).execute({})
    assert result["status"] == "success"
    assert result["data"] == [{"id": "site-1", "name": "qa"}]


@pytest.mark.asyncio
async def test_create_site_sends_json_body_and_returns_status(monkeypatch):
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/v1/sites"
        assert json.loads(request.content) == {"name": "noclick-netlify-qa"}
        return httpx.Response(201, json={"id": "site-1"})

    _mock_client(monkeypatch, handler)
    result = await _node("create_site", {"body_json": '{"name":"noclick-netlify-qa"}'}).execute({})
    assert result["status_code"] == 201
    assert result["data"]["id"] == "site-1"


@pytest.mark.asyncio
async def test_optional_body_is_not_sent_when_omitted(monkeypatch):
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/v1/sites/site-1/database"
        assert request.content == b""
        return httpx.Response(202, json={"status": "pending"})

    _mock_client(monkeypatch, handler)
    result = await _node("create_site_database", {"path_site_id": "site-1"}).execute({})
    assert result["status_code"] == 202
    assert result["data"] == {"status": "pending"}


@pytest.mark.asyncio
async def test_path_is_encoded_and_unknown_query_rejected(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "site-1"})

    _mock_client(monkeypatch, handler)
    await _node("get_site", {"path_site_id": "site 1"}).execute({})
    assert requests[0].url.path == "/api/v1/sites/site 1"
    assert str(requests[0].url).endswith("/sites/site%201")
    with pytest.raises(ValueError, match="Unknown query parameters"):
        await _node("get_site", {"path_site_id": "site-1", "query_json": '{"invalid":1}'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_api_error_does_not_leak_token(monkeypatch):
    _mock_client(
        monkeypatch,
        lambda request: httpx.Response(
            403, json={"message": "synthetic-netlify-token is forbidden"}
        ),
    )
    with pytest.raises(ValueError) as error:
        await _node("test_connection").execute({})
    assert "403" in str(error.value)
    assert "synthetic-netlify-token" not in str(error.value)
    assert "[REDACTED]" in str(error.value)


@pytest.mark.asyncio
async def test_oauth_exchanges_code_then_validates_user(monkeypatch):
    monkeypatch.setenv("NETLIFY_CLIENT_ID", "synthetic-client-id")
    monkeypatch.setenv("NETLIFY_CLIENT_SECRET", "synthetic-client-secret")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/oauth/token":
            form = parse_qs(request.content.decode())
            assert request.headers["authorization"].startswith("Basic ")
            assert form == {
                "grant_type": ["authorization_code"],
                "code": ["qa-code"],
                "redirect_uri": ["https://www.noclick.com/api/auth/netlify/callback"],
            }
            return httpx.Response(200, json={"access_token": "synthetic-access"})
        assert request.url.path == "/api/v1/user"
        assert request.headers["authorization"] == "Bearer synthetic-access"
        return httpx.Response(200, json={"id": "user-1", "email": "qa@example.com"})

    _mock_client(monkeypatch, handler)
    tokens, account_name = await netlify_oauth.OAUTH_PROVIDER.exchange(
        "qa-code", "https://www.noclick.com/api/auth/netlify/callback"
    )
    assert tokens.access_token == "synthetic-access"
    assert account_name == "qa@example.com"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_non_json_response_returns_binary_output(monkeypatch):
    from nodes.core.binary_output import BinaryOutput

    _mock_client(monkeypatch, lambda request: httpx.Response(
        200, content=b"diff --git a/index.html b/index.html\n", headers={"content-type": "text/plain"}
    ))
    result = await _node("get_site_file_by_path_name", {"path_site_id": "site-1", "path_file_path": "index.html"}).execute({})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"diff --git a/index.html b/index.html\n"
    assert result["data"].content_type == "text/plain"


def test_required_query_schema_exposes_the_provider_parameters():
    from pydantic import ValidationError

    model = CONFIG_MODELS["disable_site"]
    field = model.model_json_schema()["properties"]["query_json"]
    assert field["contentMediaType"] == "application/json"
    assert field["contentSchema"]["required"] == ["reason"]
    assert field["contentSchema"]["properties"]["reason"]["type"] == "string"
    with pytest.raises(ValidationError):
        model(path_site_id="site-1")
