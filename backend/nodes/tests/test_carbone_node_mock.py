"""Carbone routing, documented envelopes, pagination and single-use files.

Official contracts:
https://carbone.io/documentation/developer/http-api/manage-templates.html
https://carbone.io/documentation/developer/http-api/generate-reports.html
https://carbone.io/documentation/developer/http-api/download-reports.html
"""
import json
from unittest.mock import Mock
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.carbone_node import CarboneAPITokenCredential, CarboneNode, CarboneNodeConfig, ENDPOINTS
from nodes.core.binary_output import BinaryOutput

TOKEN = "carbone-test-secret-token"
DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/carbone/documented_responses.json").read_text())


def node(config):
    parsed = CarboneNodeConfig.model_validate({"config": config, "credentials": {"api_token": TOKEN}})
    return CarboneNode("carbone-test", "automation-carbone", {}, config=parsed, sio=Mock())


def mock_api(monkeypatch, handler):
    client = httpx.AsyncClient
    def factory(*args, **kwargs):
        assert kwargs["follow_redirects"] is False
        return client(*args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False)
    monkeypatch.setattr(httpx, "AsyncClient", factory)


CASES = [
    ({"operation": "upload_template", "template": "PGh0bWw+SGVsbG88L2h0bWw+", "versioning": True, "name": "Invoice"}, "POST", "/template", {"success": True, "data": {"id": "123", "versionId": "abc", "type": "html", "size": 18, "createdAt": 1625097600}}),
    ({"operation": "update_template", "template_id": "123", "name": "Updated Template Name", "tags": [], "expireAt": 0}, "PATCH", "/template/123", {"success": True, "data": {"versionId": "abc", "name": "Updated Template Name", "tags": [], "expireAt": 0}}),
    ({"operation": "delete_template", "template_id": "123"}, "DELETE", "/template/123", {"success": True, "message": "Template deleted"}),
    ({"operation": "list_templates", "cursor": "CURSOR_HASH", "includeVersions": True, "limit": 1}, "GET", "/templates", {"success": True, "data": [{"id": "123", "name": "Invoice"}], "hasMore": True, "nextCursor": "NEXT_HASH"}),
    ({"operation": "list_categories"}, "GET", "/templates/categories", {"success": True, "data": [{"name": "folder1"}, {"name": "customer2"}]}),
    ({"operation": "list_tags"}, "GET", "/templates/tags", {"success": True, "data": [{"name": "contract"}, {"name": "invoice"}, {"name": "tag3"}, {"name": "v8.2.1"}]}),
    ({"operation": "generate_document", "template_id": "123", "data": {"firstname": "John", "lastname": "Wick"}, "convertTo": "pdf"}, "POST", "/render/123", {"success": True, "data": {"renderId": "MTAuMjAuMjEuMTAgICAg.pdf"}}),
    ({"operation": "convert_document", "template": "PGh0bWw+SGVsbG88L2h0bWw+", "converter": "C"}, "POST", "/render/template", {"success": True, "data": {"renderId": "MTAuMjAuMjEuMTAgICAg.pdf"}}),
    ({"operation": "get_status"}, "GET", "/status", {"success": True, "code": 200, "message": "OK", "version": "5.15.0"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,response", CASES)
async def test_json_operations(monkeypatch, config, method, path, response):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == method and request.url.path == path
        assert request.url.host == "api.carbone.io"
        assert request.headers["carbone-version"] == "5"
        assert request.headers.get("authorization") == (None if path == "/status" else "Bearer " + TOKEN)
        assert TOKEN not in str(request.url) and TOKEN.encode() not in request.content
        if method in {"POST", "PATCH"}:
            body = json.loads(request.content)
            assert "operation" not in body and "template_id" not in body and "download" not in body
            assert all(body[key] == value for key, value in config.items() if key not in {"operation", "template_id"})
            if config["operation"] == "update_template":
                assert body == {"name": "Updated Template Name", "tags": [], "expireAt": 0}
            if config["operation"] == "convert_document":
                assert "data" not in body
        if config["operation"] == "list_templates":
            assert dict(request.url.params) == {"cursor": "CURSOR_HASH", "includeVersions": "true", "limit": "1"}
        return httpx.Response(200, json=response)
    mock_api(monkeypatch, handler)
    result = await node(config).execute({})
    assert len(calls) == 1
    assert result["status"] == "success"
    assert all(result[key] == value for key, value in response.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,authenticated", [
    ({"operation": "download_template", "template_id": "123"}, "/template/123", True),
    ({"operation": "download_document", "render_id": "report.pdf"}, "/render/report.pdf", False),
    ({"operation": "generate_document", "template_id": "123", "download": True}, "/render/123", True),
    ({"operation": "convert_document", "template": "PGgxPkhlbGxvPC9oMT4=", "download": True}, "/render/template", True),
])
async def test_binary_downloads_are_single_requests(monkeypatch, config, path, authenticated):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == path
        assert ("authorization" in request.headers) is authenticated
        return httpx.Response(200, content=b"%PDF-1.4\n", headers={"content-type": "application/pdf", "content-disposition": 'attachment; filename="report.pdf"'})
    mock_api(monkeypatch, handler)
    result = await node(config).execute({})
    assert len(calls) == 1
    assert isinstance(result["file"], BinaryOutput)
    assert result["file"].data == b"%PDF-1.4\n"
    assert result["file"].filename == "report.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_error_envelopes_preserve_rejection_and_redact_token(monkeypatch, status):
    mock_api(monkeypatch, lambda request: httpx.Response(status, json={"success": False, "error": "Unauthorized " + TOKEN}))
    result = await node({"operation": "list_templates"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["error"] == "Unauthorized [redacted]"


@pytest.mark.asyncio
async def test_unexpected_list_cannot_prove_credential(monkeypatch):
    mock_api(monkeypatch, lambda request: httpx.Response(200, json={"success": True, "data": {}}))
    with pytest.raises(ValueError, match="list response"):
        await node({"operation": "list_templates"}).execute({})


@pytest.mark.asyncio
async def test_timeout_never_retries_single_use_download(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)
    mock_api(monkeypatch, handler)
    result = await node({"operation": "download_document", "render_id": "report.pdf"}).execute({})
    assert result["outcome_verified"] is False and len(calls) == 1


@pytest.mark.parametrize("value", ["https://example.com/token", "Bearer abc", "<token>", "abc\ndef"])
def test_bad_credentials(value):
    with pytest.raises((ValidationError, ValueError)):
        CarboneAPITokenCredential(api_token=value)


@pytest.mark.parametrize("value", ["../status", "x/y", "x?download=true", "https://example.com"])
def test_ids_cannot_change_route(value):
    with pytest.raises(ValidationError):
        node({"operation": "download_template", "template_id": value})


def test_all_contract_operations_and_account_evidence():
    covered = {case[0]["operation"] for case in CASES} | {"download_template", "download_document"}
    assert covered == set(ENDPOINTS) and len(covered) == 11
    assert CarboneNode.connection_evidence.operation == "list_templates"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [("list_categories", "GET /templates/categories"), ("list_tags", "GET /templates/tags"), ("delete_template", "DELETE /template/{templateId-or-versionId}")])
async def test_exact_documented_responses(monkeypatch, operation, route):
    fixture = DOCUMENTED[route]
    mock_api(monkeypatch, lambda request: httpx.Response(200, json=fixture["body"]))
    result = await node({"operation": operation, **({"template_id": "123"} if operation == "delete_template" else {})}).execute({})
    assert all(result[key] == value for key, value in fixture["body"].items())
    assert fixture["source"].startswith("https://carbone.io/")
