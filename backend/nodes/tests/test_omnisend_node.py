"""Omnisend official API contracts without a live account."""

import base64
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes.omnisend_node import CONFIG_MODELS, OPERATIONS, OmnisendNode, OmnisendNodeConfig


def _config(operation: str, **fields):
    return OmnisendNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": {"credential_type": "omnisend_api_key", "api_key": "key-example"},
    })


def _transport(monkeypatch, callback):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.omnisend_node.httpx.AsyncClient",
        lambda *args, **kwargs: original(transport=httpx.MockTransport(callback)),
    )


def test_catalog_schema_and_connection_evidence():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 83
    assert {"Contacts", "Campaigns", "Automations", "Products", "Segments", "Reports", "Statistics"} <= {
        op["category"] for op in OPERATIONS.values()
    }
    assert OmnisendNode.connection_evidence.operation == "list_contacts"
    assert '"ui:widget": "password"' in json.dumps(OmnisendNode.get_config_schema())
    with pytest.raises(ValidationError):
        _config("get_contacts_id")
    with pytest.raises(ValidationError):
        _config("post_campaigns")


@pytest.mark.asyncio
async def test_list_contacts_auth_version_and_cursor(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(200, json={
            "contacts": [{"id": "contact-1"}],
            "paging": {"hasMore": True, "cursors": {"after": "cursor-next"}},
        })

    _transport(monkeypatch, callback)
    result = await OmnisendNode._request("key-example", "list_contacts", {"query_json": '{"limit":10}'})
    assert result["data"]["contacts"][0]["id"] == "contact-1"
    assert result["next_cursor"] == "cursor-next"
    assert result["has_more"] is True
    assert str(seen[0].url) == "https://api.omnisend.com/api/contacts?limit=10"
    assert seen[0].headers["Authorization"] == "Omnisend-API-Key key-example"
    assert seen[0].headers["Omnisend-Version"] == "2026-03-15"


@pytest.mark.asyncio
async def test_campaign_required_body_and_contact_path_encoding(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "campaign-1"})

    _transport(monkeypatch, callback)
    with pytest.raises(ValueError, match="channel, type"):
        await OmnisendNode._request("key-example", "post_campaigns", {"body_json": '{"name":"Sale"}'})
    result = await OmnisendNode._request("key-example", "post_campaigns", {
        "body_json": '{"channel":"email","type":"regular"}',
    })
    assert result["data"]["id"] == "campaign-1"
    assert json.loads(seen[0].content)["channel"] == "email"
    await OmnisendNode._request("key-example", "get_contacts_id", {"path_id": "a/b"})
    assert seen[1].url.raw_path.endswith(b"/contacts/a%2Fb")
    with pytest.raises(ValueError, match="id is required"):
        await OmnisendNode._request("key-example", "get_contacts_id", {"path_id": ".."})
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_problem_json_error_and_multipart_upload(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        if request.url.path.endswith("/contacts"):
            return httpx.Response(403, headers={"content-type": "application/problem+json"},
                                  json={"title": "Permission denied"})
        return httpx.Response(201, json={"id": "image-1"})

    _transport(monkeypatch, callback)
    with pytest.raises(ValueError, match="Omnisend API error 403: Permission denied"):
        await OmnisendNode._request("key-example", "list_contacts", {})
    result = await OmnisendNode._request("key-example", "post_images_upload", {
        "file_base64": base64.b64encode(b"image content").decode(),
        "file_name": "product.png", "image_name": "Product",
    })
    assert result["data"]["id"] == "image-1"
    assert b'filename="product.png"' in seen[1].content
    assert b"image content" in seen[1].content
    assert b"Product" in seen[1].content
    with pytest.raises(ValueError, match="valid Base64"):
        await OmnisendNode._request("key-example", "post_images_upload", {
            "file_base64": "!", "file_name": "product.png",
        })


@pytest.mark.asyncio
async def test_non_json_response_uses_binary_output(monkeypatch):
    from nodes.core.binary_output import BinaryOutput

    _transport(monkeypatch, lambda request: httpx.Response(
        200, content=b"downloaded content", headers={"content-type": "application/octet-stream"},
    ))
    result = await OmnisendNode._request("key-example", "list_contacts", {})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"downloaded content"
    assert result["data"].content_type == "application/octet-stream"
    assert result["next_cursor"] is None


@pytest.mark.asyncio
async def test_connect_brand_requires_oauth_and_uses_bearer(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(200)

    _transport(monkeypatch, callback)
    values = {"body_json": '{"platform":"wordpress","version":"2","website":"https://www.example.com"}'}
    with pytest.raises(ValueError, match="requires an Omnisend OAuth account"):
        await OmnisendNode._request("key-example", "post_brands_current", dict(values))
    assert not seen
    result = await OmnisendNode._request("oauth-token", "post_brands_current", values, oauth=True)
    assert result["status"] == "success"
    assert seen[0].headers["Authorization"] == "Bearer oauth-token"
    assert seen[0].headers["Omnisend-Version"] == "2026-03-15"


@pytest.mark.asyncio
async def test_oauth_exchange_sends_documented_form_and_versioned_identity(monkeypatch):
    from nodes.oauth.omnisend_oauth import OAUTH_PROVIDER

    seen = []

    def callback(request):
        seen.append(request)
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={
                "access_token": "oauth-token", "refresh_token": "refresh-token",
                "expires_in": 9223372036, "scope": "brands.read brands.write", "token_type": "Bearer",
            })
        assert str(request.url) == "https://api.omnisend.com/api/brands/current"
        assert request.headers["Authorization"] == "Bearer oauth-token"
        assert request.headers["Omnisend-Version"] == "2026-03-15"
        return httpx.Response(200, json={"name": "Example brand"})

    monkeypatch.setenv("OMNISEND_CLIENT_ID", "client-id")
    monkeypatch.setenv("OMNISEND_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("OMNISEND_REDIRECT_URI", "https://example.com/callback")
    _transport(monkeypatch, callback)
    tokens, name = await OAUTH_PROVIDER.exchange("auth-code", "https://example.com/callback")
    assert tokens.access_token == "oauth-token"
    assert name == "Example brand"
    from urllib.parse import parse_qs
    assert parse_qs(seen[0].content.decode()) == {
        "grant_type": ["authorization_code"], "code": ["auth-code"],
        "redirect_uri": ["https://example.com/callback"],
        "client_id": ["client-id"], "client_secret": ["client-secret"],
    }


@pytest.mark.asyncio
async def test_execute_oauth_uses_shared_refresh_and_adopts_token(monkeypatch):
    from unittest.mock import AsyncMock

    config = OmnisendNodeConfig.model_validate({
        "config": {"operation": "list_contacts"},
        "credentials": {"credential_type": "omnisend_oauth", "access_token": "old-token"},
    })
    node = OmnisendNode("test", "automation-omnisend", {"credential_id": "credential-id"}, config=config, user_id="user-id")

    async def freshen(**kwargs):
        assert kwargs["provider"] == "omnisend"
        assert kwargs["credential_id"] == "credential-id"
        kwargs["credential"].update(access_token="new-token", refresh_token="new-refresh")

    fresh = AsyncMock(side_effect=freshen)
    request = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr("nodes.omnisend_node.ensure_fresh_oauth_token", fresh)
    monkeypatch.setattr(OmnisendNode, "_request", request)
    await node.execute({})
    fresh.assert_awaited_once()
    assert config.credentials.access_token == "new-token"
    assert config.credentials.refresh_token == "new-refresh"
    assert request.await_args.args[0] == "new-token"
    assert request.await_args.kwargs["oauth"] is True
