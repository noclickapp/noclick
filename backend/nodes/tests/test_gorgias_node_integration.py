"""Contract-level checks for the Gorgias API routes and both auth methods."""

import base64
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import httpx
import pytest

from nodes.gorgias_node import (
    CONFIG_MODELS,
    OPERATIONS,
    GorgiasApiKeyCredential,
    GorgiasNode,
    GorgiasOAuthCredential,
    _field_name,
)
from nodes.oauth.gorgias_oauth import OAUTH_PROVIDER


KEY = GorgiasApiKeyCredential(subdomain="acme", email="admin@example.com", api_key="key-test")
OAUTH = GorgiasOAuthCredential(subdomain="acme", access_token="access-test", refresh_token="refresh-test")


def _client_for(handler):
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    return lambda **kwargs: original(transport=transport, **kwargs)


def _values(op):
    configs = json.loads(Path(__file__).with_name("fixtures").joinpath("gorgias/request_configs.json").read_text())
    return {k: v for k, v in configs[op["name"]].items() if k != "operation"}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(OPERATIONS))
async def test_every_action_uses_documented_request_contract(name):
    op = OPERATIONS[name]
    values = _values(op)
    CONFIG_MODELS[name](**{"operation": name, **values})
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    with patch("nodes.gorgias_node.guarded_async_client", side_effect=_client_for(handler)):
        result = await GorgiasNode._request(KEY, name, values.copy())
    request = captured[0]
    if name == "download_legacy_statistic":
        from nodes.core.binary_output import BinaryOutput
        assert isinstance(result["data"], BinaryOutput)
    else:
        assert result["data"] == {"ok": True}
    assert request.method == op["method"]
    assert request.url.host == "acme.gorgias.com"
    assert unquote(request.url.path).startswith(op["path"].split("{")[0])
    assert request.headers["authorization"].startswith("Basic ")
    for param in op["query_params"]:
        if param["required"]:
            assert param["name"] in request.url.params
    for param in op["header_params"]:
        if param["required"]:
            assert request.headers[param["name"]] == values[_field_name("header", param["name"])]
    if op["body_json"] and op["body_required"]:
        assert json.loads(request.content) == json.loads(values["body_json"])
    if op["body_multipart"]:
        assert values["filename"].encode() in request.content
        assert base64.b64decode(values["file_base64"]) in request.content


@pytest.mark.asyncio
async def test_oauth_bearer_and_tenant_validation():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"id": 1})

    with patch("nodes.gorgias_node.guarded_async_client", side_effect=_client_for(handler)):
        await GorgiasNode._request(OAUTH, "get_account", {})
    assert captured[0].headers["authorization"] == "Bearer access-test"
    bad = GorgiasApiKeyCredential(subdomain="evil.com", email="x@y.com", api_key="x")
    with pytest.raises(ValueError):
        await GorgiasNode._request(bad, "get_account", {})
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_bad_json_and_bad_upload_fail_before_network():
    with pytest.raises(ValueError, match="valid JSON"):
        await GorgiasNode._request(KEY, "create_account_setting", {"body_json": "{"})
    with pytest.raises(ValueError, match="valid Base64"):
        await GorgiasNode._request(KEY, "post_api_upload", {"filename": "x.txt", "file_base64": "!"})


@pytest.mark.asyncio
async def test_oauth_code_exchange_and_refresh_use_tenant_and_client_basic(monkeypatch):
    monkeypatch.setenv("GORGIAS_CLIENT_ID", "client-id")
    monkeypatch.setenv("GORGIAS_CLIENT_SECRET", "client-secret")
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "acme.gorgias.com"
        if request.url.path == "/oauth/token":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer new-access"
        return httpx.Response(200, json={"domain": "acme"})

    with patch("utils.ssrf.guarded_async_client", side_effect=_client_for(handler)):
        tokens, account = await OAUTH_PROVIDER.exchange("auth-code", "https://noclick.com/api/auth/oauth/gorgias/callback", context={"subdomain": "acme.gorgias.com"})
        refreshed = await OAUTH_PROVIDER.bind_refresh({"subdomain": "acme.gorgias.com"})("old-refresh")
    assert tokens.access_token == "new-access"
    assert account == "acme"
    assert tokens.subdomain == "acme.gorgias.com"
    assert refreshed.refresh_token == "new-refresh"
    assert [r.url.path for r in requests] == ["/oauth/token", "/api/account", "/oauth/token"]


def test_oauth_context_rejects_other_hosts():
    for host in ("evil.com", "acme.gorgias.com.evil.com", "acme.gorgias.com:443", "127.0.0.1", "a/b.gorgias.com"):
        with pytest.raises(ValueError):
            OAUTH_PROVIDER.validate_context({"subdomain": host})


def test_documented_zero_expiry_means_24_hours():
    from datetime import datetime, timezone
    tokens, _ = OAUTH_PROVIDER.parse_tokens(httpx.Response(200, json={
        "access_token": "access", "expires_in": 0,
    }), context={"subdomain": "acme.gorgias.com"})
    assert 86390 < (datetime.fromisoformat(tokens.expires_at) - datetime.now(timezone.utc)).total_seconds() <= 86400


@pytest.mark.asyncio
async def test_json_body_types_rejected():
    for name, body in (("update_custom_fields", "{}"), ("create_tag", "[]"), ("update_ticket_custom_field", "{}")):
        with pytest.raises(ValueError, match="Request Body"):
            await GorgiasNode._request(KEY, name, {"path_ticket_id": "123", "path_id": "123", "body_json": body})


@pytest.mark.asyncio
async def test_deep_object_and_array_query_encoding():
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={})
    with patch("nodes.gorgias_node.guarded_async_client", side_effect=_client_for(handler)):
        await GorgiasNode._request(KEY, "list_events", {"query_created_datetime": '{"gt":"2020-06-10T00:00:00-05:00"}'})
        await GorgiasNode._request(KEY, "get_customer", {"path_id": "123", "query_relationships": ["custom_fields"]})
    assert captured[0].url.params["created_datetime[gt]"] == "2020-06-10T00:00:00-05:00"
    assert captured[1].url.params.get_list("relationships") == ["custom_fields"]


@pytest.mark.asyncio
async def test_download_redirect_returns_link_without_fetching():
    def handler(request):
        return httpx.Response(307, headers={"location": "https://files.gorgias.com/attachment.png"})
    with patch("nodes.gorgias_node.guarded_async_client", side_effect=_client_for(handler)):
        result = await GorgiasNode._request(KEY, "download_file", _values(OPERATIONS["download_file"]))
    assert result["download_url"] == "https://files.gorgias.com/attachment.png"


@pytest.mark.asyncio
async def test_statistic_download_preserves_complete_csv():
    from nodes.core.binary_output import BinaryOutput
    content = b"date,count\n" + b"2020-06-10,123\n" * 500
    def handler(request):
        return httpx.Response(201, content=content, headers={"content-type": "text/csv"})
    with patch("nodes.gorgias_node.guarded_async_client", side_effect=_client_for(handler)):
        result = await GorgiasNode._request(KEY, "download_legacy_statistic", _values(OPERATIONS["download_legacy_statistic"]))
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == content
