"""Offline Affinda v3 wire, response and credential boundary tests."""
from email.parser import BytesParser
from email.policy import default
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import affinda_node as native
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


async def run(monkeypatch, config, response, region="api"):
    seen = []
    original = httpx.AsyncClient

    def handler(request):
        seen.append(request)
        return response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    node = NodeFactory.create_node(node_id="affinda-test", node_type="automation-affinda", node_data={
        "config": config, "credentials": {"credential_type": "affinda_api_key", "api_key": "aff_test_secret", "region": region}})
    emitted = []

    async def emit(output):
        emitted.append(output)

    monkeypatch.setattr(node, "emit", emit)
    result = await node.execute({})
    assert emitted == [result]
    assert len(seen) == 1
    assert seen[0].headers["Authorization"] == "Bearer aff_test_secret"
    return seen[0], result


CASES = [
    ({"operation": "list_documents", "offset": 20, "include_data": False}, "GET", "/documents", {"limit": "20", "offset": "20", "include_data": "false"}),
    ({"operation": "get_document", "identifier": "doc-1"}, "GET", "/documents/doc-1", {"format": "json"}),
    ({"operation": "create_document", "workspace": "mEFayXdO", "url": "https://api.affinda.com/static/sample_resumes/example.docx", "file_name": "Document.pdf"}, "POST", "/documents", {"workspace": "mEFayXdO", "url": "https://api.affinda.com/static/sample_resumes/example.docx", "fileName": "Document.pdf"}),
    ({"operation": "update_document", "identifier": "doc-1", "is_confirmed": False, "document_type": "type-1"}, "PATCH", "/documents/doc-1", {"isConfirmed": False, "documentType": "type-1"}),
    ({"operation": "delete_document", "identifier": "doc-1"}, "DELETE", "/documents/doc-1", {}),
    ({"operation": "list_workspaces", "organization": "org-1"}, "GET", "/workspaces", {"organization": "org-1"}),
    ({"operation": "get_workspace", "identifier": "ws-1"}, "GET", "/workspaces/ws-1", {}),
    ({"operation": "list_collections", "workspace": "ws-1"}, "GET", "/collections", {"workspace": "ws-1"}),
    ({"operation": "get_collection", "identifier": "col-1"}, "GET", "/collections/col-1", {}),
    ({"operation": "list_document_types", "workspace": "ws-1"}, "GET", "/document_types", {"workspace": "ws-1"}),
    ({"operation": "get_document_type", "identifier": "type-1"}, "GET", "/document_types/type-1", {}),
    ({"operation": "list_tags", "offset": 40}, "GET", "/tags", {"limit": "20", "offset": "40"}),
    ({"operation": "get_tag", "id": 1}, "GET", "/tags/1", {}),
    ({"operation": "create_tag", "name": "Reviewed", "workspace": "ws-1"}, "POST", "/tags", {"name": "Reviewed", "workspace": "ws-1"}),
    ({"operation": "update_tag", "id": 1, "name": "Reviewed"}, "PATCH", "/tags/1", {"name": "Reviewed"}),
    ({"operation": "delete_tag", "id": 1}, "DELETE", "/tags/1", {}),
    ({"operation": "add_tag_to_documents", "identifiers": ["doc-1"], "tag": 1}, "POST", "/documents/batch_add_tag", {"identifiers": ["doc-1"], "tag": 1}),
    ({"operation": "remove_tag_from_documents", "identifiers": ["doc-1"], "tag": 1}, "POST", "/documents/batch_remove_tag", {"identifiers": ["doc-1"], "tag": 1}),
    ({"operation": "list_organizations"}, "GET", "/organizations", {}),
    ({"operation": "get_organization", "identifier": "org-1"}, "GET", "/organizations/org-1", {}),
    ({"operation": "get_usage", "organization": "org-1", "document_type": "type-1", "start": "2026-01-01", "end": "2026-01-31"}, "GET", "/usage", {"organization": "org-1", "document_type": "type-1", "start": "2026-01-01", "end": "2026-01-31"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,payload", CASES, ids=[x[0]["operation"] for x in CASES])
async def test_operations(monkeypatch, config, method, path, payload):
    empty = method == "DELETE" or "batch_" in path
    response = httpx.Response(204) if empty else httpx.Response(200, json={"results": [], "count": 0})
    request, result = await run(monkeypatch, config, response)
    assert request.method == method
    assert str(request.url).split("?")[0] == "https://api.affinda.com/v3" + path
    if method == "GET":
        assert dict(request.url.params) == payload
        assert not request.content
    elif config["operation"] == "create_document":
        content = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
        assert content.is_multipart()
        assert {p.get_param("name", header="content-disposition"): p.get_content() for p in content.iter_parts()} == payload
    elif method != "DELETE":
        assert json.loads(request.content) == payload
    else:
        assert not request.content
    assert result == {"status": "success", "data": {"acknowledged": True} if empty else {"results": [], "count": 0}}


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["api", "api.us1", "api.eu1"])
async def test_region_and_connection_evidence(monkeypatch, region):
    request, result = await run(monkeypatch, {"operation": "list_organizations"}, httpx.Response(200, json=[
        {"identifier": "mEFayXdO", "name": "Grove Street King", "resthookSignatureKey": "never-emit"}]), region)
    assert request.url.host == region + ".affinda.com"
    assert result["data"] == [{"identifier": "mEFayXdO", "name": "Grove Street King"}]
    assert native.AffindaNode.connection_evidence.operation == "list_organizations"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_errors_redact_secret_without_retry(monkeypatch, status):
    with pytest.raises(ValueError, match=rf"Affinda HTTP {status}: rejected \[redacted\]"):
        await run(monkeypatch, {"operation": "list_organizations"}, httpx.Response(status, text="rejected aff_test_secret"))


@pytest.mark.asyncio
async def test_pagination_urls_are_returned_without_fetching(monkeypatch):
    page = {"results": [], "count": 10, "next": "https://untrusted.example/next"}
    _, result = await run(monkeypatch, {"operation": "list_documents"}, httpx.Response(200, json=page))
    assert result["data"] == page


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>bad</html>"), httpx.Response(200, json="unexpected")])
async def test_invalid_json_shape(monkeypatch, response):
    with pytest.raises(ValueError, match="Affinda returned"):
        await run(monkeypatch, {"operation": "list_organizations"}, response)


@pytest.mark.parametrize("config", [
    {"operation": "get_document", "identifier": "../secret"},
    {"operation": "list_workspaces"},
    {"operation": "list_collections"},
    {"operation": "get_usage", "organization": "org", "start": "2026-02-01", "end": "2026-01-01"},
    {"operation": "get_tag", "id": 0},
    {"operation": "create_document", "workspace": "ws", "url": "file:///etc/passwd"},
    {"operation": "update_document", "identifier": "doc"},
    {"operation": "add_tag_to_documents", "identifiers": [], "tag": 1},
])
def test_invalid_config(config):
    assert not native.AffindaNode.validate_config({"config": config})["valid"]


@pytest.mark.parametrize("fields", [
    {"api_key": "https://example.com/token"},
    {"api_key": "Bearer token"},
    {"api_key": "aff_test", "region": "api.evil.example"},
])
def test_credential_boundary(fields):
    with pytest.raises(ValidationError):
        native.AffindaAPIKeyCredential.model_validate(fields)
