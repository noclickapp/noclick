"""Verify Canva upload bytes and metadata through the real HTTPX serializer."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock

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
