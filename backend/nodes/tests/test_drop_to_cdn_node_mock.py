"""Exercise the discovered node against the provider's five wire contracts."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import drop_to_cdn_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

TOKEN = "dtc_synthetic_test_key"
CREDENTIAL = {"credential_type": "drop_to_cdn_api_key", "api_key": TOKEN}
FILE = {"id": "file-123", "url": "https://cdn.droptocdn.com/file-123.txt", "expires_at": None, "size": 5, "mime_type": "text/plain", "original_name": "file.txt"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="fixture", node_type="automation-drop-to-cdn",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, *, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("pagination", [{}, {"cursor": "a+b/c=="}, {"page": 2}])
async def test_drop_to_cdn_list_query_and_account_evidence(monkeypatch, pagination):
    body = {"data": [FILE], "has_more": True, "next_cursor": "next-token"}
    requests = transport(monkeypatch, body=body)
    result = await node({"operation": "list_files", "limit": 50, **pagination}).run({})
    assert result["status"] == "success" and result["data"] == body
    request = requests[0]
    assert request.method == "GET" and request.url.path == "/v1/files"
    assert dict(request.url.params) == {"limit": "50", **{k: str(v) for k, v in pagination.items()}}
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert native.DropToCdnNode.connection_evidence.operation == "list_files"


@pytest.mark.asyncio
async def test_drop_to_cdn_get_and_bodyless_delete(monkeypatch):
    requests = transport(monkeypatch, body=FILE)
    assert (await node({"operation": "get_file", "file_id": "file-123"}).run({}))["data"] == FILE
    assert requests[0].url.path == "/v1/files/file-123"
    requests = transport(monkeypatch, status=204)
    result = await node({"operation": "delete_file", "file_id": "file-123"}).run({})
    assert result["deleted_id"] == "file-123" and result["http_status"] == 204
    assert requests[0].method == "DELETE" and requests[0].content == b""


@pytest.mark.asyncio
async def test_drop_to_cdn_publish_json_preserves_false_and_omits_retention(monkeypatch):
    requests = transport(monkeypatch, status=201, body={"id": "page-123", "url": "https://cdn.droptocdn.com/page-123", "expires_at": None})
    result = await node({"operation": "publish_page", "html": "<h1>Hello</h1>", "never_expire": False}).run({})
    assert result["status"] == "success"
    assert requests[0].url.path == "/v1/pages" and requests[0].method == "POST"
    assert json.loads(requests[0].content) == {"html": "<h1>Hello</h1>", "never_expire": False}


@pytest.mark.asyncio
async def test_drop_to_cdn_upload_real_multipart_bytes_and_retention(monkeypatch):
    requests = transport(monkeypatch, status=201, body=FILE)
    result = await node({"operation": "upload_file", "file": "data:text/plain;base64,SGVsbG8=", "retention_days": 7, "never_expire": False}).run({})
    assert result["data"] == FILE
    request = requests[0]
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="file.txt"' in request.content
    assert b'Content-Type: text/plain' in request.content and b'Hello' in request.content
    assert b'name="retention_days"\r\n\r\n7' in request.content
    assert b'name="never_expire"\r\n\r\nfalse' in request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_drop_to_cdn_errors_and_redirects_are_not_successful(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={"error": "Rejected", "message": "Rejected " + TOKEN})
    result = await node({"operation": "list_files"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["error"] and TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": "wrong"}, {"data": ["wrong"]}, {"error": "Unauthorized"}])
async def test_drop_to_cdn_malformed_list_is_not_connection_proof(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node({"operation": "list_files"}).execute({})


def test_drop_to_cdn_config_and_manual_credential_contract():
    credential = native.DropToCdnAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "drop_to_cdn_api_key" and credential.api_key == TOKEN
    for config in [{"operation": "list_files", "cursor": "next", "page": 1}, {"operation": "list_files", "limit": 101}, {"operation": "get_file", "file_id": "../other"}, {"operation": "publish_page"}]:
        with pytest.raises(ConfigValidationError):
            native.DropToCdnNode.parse_config({"config": config, "credentials": CREDENTIAL})
    with pytest.raises(ValidationError):
        native.DropToCdnAPIKeyCredential(api_key="Bearer " + TOKEN)
