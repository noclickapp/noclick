"""Verify Canva body encodings, authentication and server selection over HTTPX."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from nodes.canva_node import CanvaNode, CanvaNodeConfig


UPLOADS = [
    (
        "upload_asset_from_binary",
        "name",
        "Asset-Upload-Metadata",
        "name_base64",
        "/v1/asset-uploads",
    ),
    (
        "import_design_from_binary_file",
        "title",
        "Import-Metadata",
        "title_base64",
        "/v1/imports",
    ),
]


def make_node(operation, fields):
    return CanvaNode(
        node_id="canva-binary-test",
        node_type="canva",
        node_data={},
        config=CanvaNodeConfig(
            config={"operation": operation, **fields},
            credentials={
                "credential_type": "canva_oauth",
                "access_token": "synthetic-access-token",
                "refresh_token": "synthetic-refresh-token",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        ),
    )


def execute(monkeypatch, node, handler):
    node._get_access_token = AsyncMock(return_value="synthetic-access-token")
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )
    return asyncio.run(node.execute({}))


@pytest.mark.parametrize("operation,field,header,key,path", UPLOADS)
@pytest.mark.parametrize("label", ["Review asset", "Review 🌱 café", "a" * 50])
def test_binary_upload_contract(
    monkeypatch, operation, field, header, key, path, label
):
    binary = b"\x00\xff\x89PNG\r\n\x1a\nreview-bytes"
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "POST"
        assert request.url == f"https://api.canva.com/rest{path}"
        assert request.headers["Authorization"] == "Bearer synthetic-access-token"
        assert request.headers["Content-Type"] == "application/octet-stream"
        assert request.content == binary
        assert json.loads(request.headers[header]) == {
            key: base64.b64encode(label.encode("utf-8")).decode("ascii")
        }
        return httpx.Response(
            200, json={"job": {"id": "synthetic-job", "status": "in_progress"}}
        )

    node = make_node(
        operation, {"file_data": base64.b64encode(binary).decode(), field: label}
    )
    result = execute(monkeypatch, node, handler)
    assert len(seen) == 1
    node._get_access_token.assert_awaited_once()
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["status_code"] == 200
    assert result["data"]["job"]["status"] == "in_progress"


@pytest.mark.parametrize("operation,field,header,key,path", UPLOADS)
@pytest.mark.parametrize("file_data", ["not base64!", "", "  "])
def test_invalid_binary_fails_before_oauth_or_network(
    monkeypatch, operation, field, header, key, path, file_data
):
    node = make_node(operation, {"file_data": file_data, field: "Review"})
    node._get_access_token = AsyncMock(
        side_effect=AssertionError("Must not authenticate")
    )
    with pytest.raises(ValueError):
        asyncio.run(node.execute({}))
    node._get_access_token.assert_not_awaited()


@pytest.mark.parametrize("operation,field,header,key,path", UPLOADS)
@pytest.mark.parametrize("label", [None, "", "a" * 51])
def test_required_upload_metadata_is_validated(
    operation, field, header, key, path, label
):
    with pytest.raises(ValueError):
        make_node(operation, {"file_data": "Ynl0ZXM=", field: label})


def test_upload_tags_are_not_silently_discarded():
    node = make_node(
        "upload_asset_from_binary",
        {"file_data": "Ynl0ZXM=", "name": "Review", "tags": ["tag"]},
    )
    node._get_access_token = AsyncMock(
        side_effect=AssertionError("Must not authenticate")
    )
    with pytest.raises(ValueError, match="tags"):
        asyncio.run(node.execute({}))
    node._get_access_token.assert_not_awaited()


@pytest.mark.parametrize("operation,field,header,key,path", UPLOADS)
def test_binary_provider_rejection_is_not_success(
    monkeypatch, operation, field, header, key, path
):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(403, json={"message": "Not allowed"})

    result = execute(
        monkeypatch,
        make_node(operation, {"file_data": "Ynl0ZXM=", field: "Review"}),
        handler,
    )
    assert len(seen) == 1
    assert result["status"] == "error"
    assert result["status_code"] == 403
    assert result["error"] == "Not allowed"
    assert "data" not in result


def test_json_requests_remain_json(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "name": "Review",
            "parent_folder_id": "root",
        }
        assert "Asset-Upload-Metadata" not in request.headers
        return httpx.Response(200, json={"folder": {"id": "synthetic-folder"}})

    result = execute(
        monkeypatch, make_node("create_folder", {"name": "Review"}), handler
    )
    assert len(seen) == 1
    assert result["status"] == "success"


@pytest.mark.parametrize("operation,field,header,key,path", UPLOADS)
@pytest.mark.parametrize(
    "file_data", ["data:image/png;base64,Ynl0ZXM=", "Yn\nl0\nZXM="]
)
def test_inline_media_is_resolved_before_upload(
    monkeypatch, operation, field, header, key, path, file_data
):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.content == b"bytes"
        assert request.headers["Content-Type"] == "application/octet-stream"
        return httpx.Response(200, json={"job": {"id": "synthetic-job"}})

    result = execute(
        monkeypatch,
        make_node(operation, {"file_data": file_data, field: "Review"}),
        handler,
    )
    assert len(seen) == 1
    assert result["status"] == "success"


@pytest.mark.parametrize("operation,field,header,key,path", UPLOADS)
def test_local_media_url_is_rejected_before_canva_oauth(
    operation, field, header, key, path
):
    node = make_node(
        operation, {"file_data": "http://127.0.0.1/private", field: "Review"}
    )
    node._get_access_token = AsyncMock(
        side_effect=AssertionError("Must not authenticate")
    )
    with pytest.raises(ValueError):
        asyncio.run(node.execute({}))
    node._get_access_token.assert_not_awaited()


def test_mixed_request_bodies_fail_before_oauth():
    node = make_node("create_folder", {"name": "Review"})
    node._get_access_token = AsyncMock(
        side_effect=AssertionError("Must not authenticate")
    )
    with pytest.raises(ValueError, match="both JSON and binary"):
        asyncio.run(
            node._make_request(
                "POST",
                "/v1/imports",
                node.config.credentials,
                json_body={"a": 1},
                binary_body=b"bytes",
            )
        )
    node._get_access_token.assert_not_awaited()


def _make_contract_node(operation, **fields):
    return CanvaNode(
        node_id="canva-contract", node_type="automation-canva", node_data={},
        config=CanvaNodeConfig(
            config={"operation": operation, **fields},
            credentials={
                "credential_type": "canva_oauth",
                "access_token": "access+token/with=reserved&characters",
                "refresh_token": "refresh+token/with=reserved&characters",
                "expires_at": "2000-01-01T00:00:00Z",
            },
        ),
    )


def _execute_contract(monkeypatch, node, handler):
    original = httpx.AsyncClient
    seen = []

    def capture(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(capture), **kwargs),
    )
    result = asyncio.run(node.execute({}))
    assert len(seen) == 1
    return result


def test_resize_serializes_custom_design_type(monkeypatch):
    node = _make_contract_node(
        "create_design_resize_job", design_id="DAGirp_1ZUA", width=1000, height=1500
    )
    node._get_access_token = AsyncMock(return_value="fresh-access-token")

    def handler(request):
        assert request.method == "POST"
        assert request.url == "https://api.canva.com/rest/v1/resizes"
        assert request.headers["Authorization"] == "Bearer fresh-access-token"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "design_id": "DAGirp_1ZUA",
            "design_type": {"type": "custom", "width": 1000, "height": 1500},
        }
        return httpx.Response(200, json={"job": {"id": "job", "status": "in_progress"}})

    result = _execute_contract(monkeypatch, node, handler)
    assert result["status"] == "success"
    assert result["data"]["job"]["status"] == "in_progress"
    node._get_access_token.assert_awaited_once()


@pytest.mark.parametrize(
    "operation,fields,endpoint,token_field",
    [
        ("verify_token_validity", {}, "introspect", "access_token"),
        ("revoke_access_or_refresh_token", {}, "revoke", "access_token"),
        ("revoke_access_or_refresh_token", {"token_type": "refresh_token"}, "revoke", "refresh_token"),
    ],
)
@pytest.mark.parametrize("status", [200, 401])
def test_token_management_uses_client_auth_and_form_encoding(
    monkeypatch, operation, fields, endpoint, token_field, status
):
    monkeypatch.setenv("CANVA_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("CANVA_CLIENT_SECRET", "cnvca-synthetic-secret")
    node = _make_contract_node(operation, **fields)
    node._get_access_token = AsyncMock(side_effect=AssertionError("Must not refresh"))
    payload = {"active": True} if endpoint == "introspect" else {}
    if status == 401:
        payload = {"code": "invalid_client", "message": "Client authentication failed"}

    def handler(request):
        assert request.method == "POST"
        assert request.url == f"https://api.canva.com/rest/v1/oauth/{endpoint}"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        scheme, value = request.headers["Authorization"].split(" ", 1)
        assert scheme == "Basic"
        assert base64.b64decode(value).decode() == "synthetic-client:cnvca-synthetic-secret"
        assert parse_qs(request.content.decode()) == {
            "token": [getattr(node.config.credentials, token_field)]
        }
        return httpx.Response(status, json=payload)

    result = _execute_contract(monkeypatch, node, handler)
    node._get_access_token.assert_not_awaited()
    assert result["status_code"] == status
    assert result["action"] == operation
    if status == 200:
        assert result["status"] == "success"
        assert result["data"] == payload
    else:
        assert result["status"] == "error"
        assert result["error"] == payload["message"]
        assert "data" not in result


@pytest.mark.parametrize(
    "operation,endpoint,public,payload",
    [
        ("get_openid_connect_jwks", "jwks", True, {"keys": []}),
        ("fetch_current_user_oidc_claims", "userinfo", False, {"sub": "user"}),
    ],
)
def test_oidc_uses_auth_server(monkeypatch, operation, endpoint, public, payload):
    node = _make_contract_node(operation)
    node._get_access_token = (
        AsyncMock(side_effect=AssertionError("Public keys need no token"))
        if public else AsyncMock(return_value="fresh-access-token")
    )

    def handler(request):
        assert request.method == "GET"
        assert request.url == f"https://api.canva.com/auth/v1/oidc/{endpoint}"
        assert request.content == b""
        if public:
            assert "Authorization" not in request.headers
        else:
            assert request.headers["Authorization"] == "Bearer fresh-access-token"
        return httpx.Response(200, json=payload)

    result = _execute_contract(monkeypatch, node, handler)
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["data"] == payload
    if public:
        node._get_access_token.assert_not_awaited()
    else:
        node._get_access_token.assert_awaited_once()


def test_oidc_scopes_are_requested_without_dropping_existing_scopes():
    from nodes.canva_node import CanvaOAuthCredential
    from nodes.scopes.canva import CANVA_SCOPES

    required = CanvaNode.scope_registry.require("fetch_current_user_oidc_claims")
    assert set(required.scopes) == {"openid", "profile"}
    requested = set(CanvaOAuthCredential.model_json_schema()["x-oauth-scopes"])
    assert set(CANVA_SCOPES.declared_scopes()) <= requested
    assert set(required.scopes) <= requested
