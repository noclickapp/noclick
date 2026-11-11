"""Wire checks against Doqs v1's published schema and documented PDF format.

List fixtures are schema-shaped test data, not live recordings. Binary sentinels
exercise the response format described in the provider's fill/render docs.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.binary_output import BinaryOutput, resolve_binary_outputs
from nodes.doqs_node import DoqsAPIKeyCredential, DoqsNode, DoqsNodeConfig, ENDPOINTS

KEY = "doqs-test-secret"
TEMPLATE = {"id": "template-1", "created_at": "2026-01-01T00:00:00Z", "name": "Invoice", "pages": 1, "size_bytes": 100}
SUBMISSION = {"id": "submission-1", "created_at": "2026-01-01T00:00:00Z", "status": "success"}
PDF = b"%PDF-1.7\n%%EOF\n"


def node(config, credentials=True):
    parsed = DoqsNodeConfig.model_validate({"config": config, "credentials": {"api_key": KEY} if credentials else None})
    return DoqsNode(node_id="test-doqs", node_type="automation-doqs", node_data={}, config=parsed)


def mock_api(monkeypatch, handler):
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(*args, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,rows", [("list_templates", [TEMPLATE]), ("list_submissions", [SUBMISSION])])
async def test_lists_preserve_provider_envelopes_and_page(monkeypatch, operation, rows):
    requests = []

    def transport(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1" + ENDPOINTS[operation][1]
        assert dict(request.url.params) == {"limit": "12", "offset": "24"}
        assert request.headers["x-api-key"] == KEY
        assert request.content == b""
        return httpx.Response(200, json={"results": rows})

    mock_api(monkeypatch, transport)
    result = await node({"operation": operation, "limit": 12, "offset": 24}).execute({})
    assert result["status"] == "success" and result["data"] == {"results": rows}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_fill_request_and_documented_pdf_response(monkeypatch):
    # https://docs.doqs.dev/pdf-filling/fill-template: JSON data -> PDF bytes.
    def transport(request):
        assert request.method == "POST" and request.url.path == "/v1/pdf-filling/templates/template-1/fill"
        assert json.loads(request.content) == {"data": {"customer": "Ada", "approved": True}}
        assert request.headers["x-api-key"] == KEY
        assert "application/pdf" in request.headers["accept"]
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})

    mock_api(monkeypatch, transport)
    result = await node({"operation": "fill_template", "template_id": "template-1", "data": '{"customer":"Ada","approved":true}'}).execute({})
    assert isinstance(result["file"], BinaryOutput)
    assert result["file"].data == PDF
    assert result["file"].content_type == "application/pdf"
    assert result["file"].filename == "filled-template.pdf"
    assert result["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_render_all_contract_fields(monkeypatch):
    # https://docs.doqs.dev/pdf-generator/render and its presigned uploads guide.
    requests = []

    def transport(request):
        requests.append(request)
        assert request.url.path == "/v1/pdf-generator/render" and request.method == "POST"
        assert json.loads(request.content) == {
            "template_html": "<html>Your template</html>", "header_template": "Header", "footer_template": "Footer",
            "pdf": {"format": "a5", "orientation": "landscape", "scale": 0.8,
                "margin": {"top": "10mm", "bottom": "1cm", "left": "0px", "right": "0.1in"}},
            "presigned_upload": {"url": "https://storage.example.test/file?signature=abc", "method": "POST"},
        }
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf; charset=binary", "x-submission-id": "submission-1"})

    mock_api(monkeypatch, transport)
    result = await node({"operation": "render_pdf", "template_html": "<html>Your template</html>", "header_template": "Header", "footer_template": "Footer",
        "format": "a5", "orientation": "landscape", "scale": 0.8,
        "margin_top": "10mm", "margin_bottom": "1cm", "margin_left": "0px", "margin_right": "0.1in",
        "presigned_upload_url": "https://storage.example.test/file?signature=abc", "presigned_upload_method": "POST"}).execute({})
    assert result["submission_id"] == "submission-1"
    assert isinstance(result["file"], BinaryOutput)
    assert result["file"].data == PDF
    assert result["file"].content_type == "application/pdf"
    assert result["file"].filename == "rendered.pdf"
    assert len(requests) == 1  # Doqs performs the upload; NoClick never fetches that URL.


@pytest.mark.asyncio
@pytest.mark.parametrize("config,filename", [
    ({"operation": "fill_template", "template_id": "template-1"}, "filled-template.pdf"),
    ({"operation": "render_pdf", "template_html": "Invoice"}, "rendered.pdf"),
])
async def test_doqs_pdf_resolves_to_workflow_file(monkeypatch, config, filename):
    mock_api(monkeypatch, lambda request: httpx.Response(200, content=PDF,
        headers={"content-type": "application/pdf", "x-submission-id": "submission-1"}))
    stored = []

    async def store(**kwargs):
        stored.append(kwargs)
        return {"download_url": "https://files.example.test/document.pdf", "mime_type": "application/pdf",
            "name": filename, "size_bytes": len(PDF)}

    monkeypatch.setattr("nodes.core.binary_output.create_resource_from_bytes", store)
    output = await node(config).execute({})
    result = await resolve_binary_outputs(output, user_id="user-1", workflow_id="workflow-1", node_id="doqs-1")
    assert stored == [{"user_id": "user-1", "workflow_id": "workflow-1", "node_id": "doqs-1", "organization_id": None,
        "body": PDF, "content_type": "application/pdf", "filename": filename}]
    assert result["file"] == {"url": "https://files.example.test/document.pdf", "mime_type": "application/pdf",
        "name": filename, "size_bytes": len(PDF)}
    assert result["submission_id"] == "submission-1"
    assert "pdf_base64" not in result
    json.dumps(result)  # Canonical workflow output is JSON-safe after storage.


@pytest.mark.asyncio
async def test_defaults_and_openapi_json_alternative(monkeypatch):
    def transport(request):
        assert json.loads(request.content) == {"template_html": "<html>Your template</html>", "pdf": {"format": "a4", "orientation": "portrait", "scale": 1}}
        return httpx.Response(200, json={})

    mock_api(monkeypatch, transport)
    assert (await node({"operation": "render_pdf", "template_html": "<html>Your template</html>"}).execute({}))["data"] == {}


@pytest.mark.asyncio
async def test_template_id_is_encoded_as_one_path_segment(monkeypatch):
    def transport(request):
        assert "/templates/a%2Fb%3Fq%23f/fill" in request.url.raw_path.decode()
        return httpx.Response(200, json={})

    mock_api(monkeypatch, transport)
    await node({"operation": "fill_template", "template_id": "a/b?q#f"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 408, 426, 429, 500, 302])
async def test_provider_errors_and_redirects(monkeypatch, code):
    mock_api(monkeypatch, lambda request: httpx.Response(code, json={"message": "Rejected " + KEY}, headers={"location": "https://other.example.test"}))
    result = await node({"operation": "list_templates"}).execute({})
    assert result["status"] == "error" and result["status_code"] == code
    assert result["error"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Error</html>"), httpx.Response(200, json=[]), httpx.Response(200, json={})])
async def test_unexpected_list_cannot_prove_connection(monkeypatch, response):
    mock_api(monkeypatch, lambda request: response)
    with pytest.raises(ValueError, match="unexpected"):
        await node({"operation": "list_templates"}).execute({})


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_never_retried(monkeypatch):
    requests = []

    def transport(request):
        requests.append(request)
        raise httpx.ReadTimeout("secret transport details")

    mock_api(monkeypatch, transport)
    with pytest.raises(ValueError, match="completion is unknown"):
        await node({"operation": "render_pdf", "template_html": "Invoice"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_template_picker_pages_and_names(monkeypatch):
    def transport(request):
        assert request.url.params["offset"] == "100"
        return httpx.Response(200, json={"results": [TEMPLATE]})

    mock_api(monkeypatch, transport)
    result = await DoqsNode.load_field_options("template_id", {"api_key": KEY}, page_token="100")
    assert result == {"options": [{"value": "template-1", "label": "Invoice"}], "next_page_token": None}


@pytest.mark.asyncio
async def test_connection_reads_account_templates(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    mock_api(monkeypatch, lambda request: httpx.Response(200, json={"results": [TEMPLATE]}))
    evidence = await collect_evidence(node_type="automation-doqs", user_id="test-user", credential_data={"credential_type": "doqs_api_key", "api_key": KEY})
    assert evidence.reachable is True
    assert "Invoice" in str(evidence)


@pytest.mark.asyncio
async def test_missing_credential():
    with pytest.raises(ValueError, match="Connect a Doqs API key"):
        await node({"operation": "list_templates"}, credentials=False).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "list_templates", "limit": 1001}, {"operation": "list_submissions", "offset": -1},
    {"operation": "fill_template", "template_id": "id", "data": "[]"},
    {"operation": "fill_template", "template_id": "id", "data": '{"bad":NaN}'},
    {"operation": "render_pdf", "template_html": "x", "scale": 2.1},
    {"operation": "render_pdf", "template_html": "x", "presigned_upload_url": "http://example.test"},
])
def test_input_validation(config):
    with pytest.raises(ValidationError):
        node(config)


def test_credential_default_and_complete_operation_coverage():
    assert DoqsAPIKeyCredential(api_key=KEY).credential_type == "doqs_api_key"
    assert set(ENDPOINTS) == {"list_templates", "fill_template", "render_pdf", "list_submissions"}
