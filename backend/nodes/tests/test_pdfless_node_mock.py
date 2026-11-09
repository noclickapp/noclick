"""Offline regression tests for the three published Pdfless v1 operations."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import pdfless_node as native
from nodes.core.registry import NodeFactory

TOKEN = "pdfless-offline-api-key"
TEMPLATE = "1814309a-c198-469e-a583-227a69a6ecb2"


def make_node(config, credentials=True):
    data = {"config": config}
    if credentials:
        data["credentials"] = {"credential_type": "pdfless_api_key", "api_key": TOKEN}
    return NodeFactory.create_node(node_id="pdfless-test", node_type="automation-pdfless", node_data=data)


def mock_client(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def factory(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", factory)
    return requests


@pytest.mark.asyncio
async def test_workspace_is_account_specific_connection_evidence(monkeypatch):
    requests = mock_client(monkeypatch, {"name": "My workspace", "active": True, "quota": 500, "remainingQuota": 424})
    result = await make_node({"operation": "get_workspace"}).execute({})
    assert result["data"]["name"] == "My workspace"
    assert str(requests[0].url) == "https://api.pdfless.com/v1/workspaces"
    assert requests[0].method == "GET" and requests[0].headers["apikey"] == TOKEN
    assert not requests[0].content
    assert native.PdflessNode.connection_evidence.identity_operation == "get_workspace"


@pytest.mark.asyncio
async def test_list_templates_exact_query_names_and_single_page(monkeypatch):
    requests = mock_client(monkeypatch, [{"id": TEMPLATE, "name": "Invoice"}])
    result = await make_node({"operation": "list_document_templates", "workspace_id": 7, "page": 2, "page_size": 25}).execute({})
    assert result["items"][0]["id"] == TEMPLATE
    assert requests[0].url.path == "/v1/document-templates"
    assert dict(requests[0].url.params) == {"WorkspaceId": "7", "Page": "2", "PageSize": "25"}
    assert len(requests) == 1
    requests = mock_client(monkeypatch, [])
    assert (await make_node({"operation": "list_document_templates"}).execute({}))["items"] == []
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_documented_generate_request_response_and_encryption(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/pdfless/generate.json").read_text())
    requests = mock_client(monkeypatch, fixture)
    config = {"operation": "generate_pdf", "template_id": TEMPLATE, "payload": '{"Company":"Company & co"}',
              "workspace_id": 7, "reference_id": "invoice-42", "encryption_user_password": "open-this",
              "encryption_owner_password": "owner-only", "encryption_allow_printing": False,
              "encryption_allow_modifying": True}
    result = await make_node(config).execute({})
    assert result == {"status": "success", "data": fixture["data"]}
    assert requests[0].method == "POST" and requests[0].url.path == "/v1/pdfs"
    body = json.loads(requests[0].content)
    expected = {k: v for k, v in config.items() if k not in {"operation", "workspace_id", "payload"}}
    assert body == expected | {"workspaceId": 7, "payload": {"Company": "Company & co"}}
    assert len(requests) == 1 and "apikey" not in requests[0].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_errors_do_not_succeed_or_retry_and_redact_key(monkeypatch, status):
    requests = mock_client(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await make_node({"operation": "get_workspace"}).execute({})
    assert result == {"status": "error", "error": "Rejected [redacted]", "http_status": status}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("list_document_templates", {}), ("get_workspace", []), ("generate_pdf", {}), ("get_workspace", {"error_code": "invalid_key"})])
async def test_malformed_or_error_envelope_is_never_success(monkeypatch, operation, body):
    mock_client(monkeypatch, body)
    with pytest.raises(ValueError):
        await make_node({"operation": operation, **({"template_id": TEMPLATE} if operation == "generate_pdf" else {})}).execute({})


@pytest.mark.asyncio
async def test_missing_credential_fails_before_request():
    with pytest.raises(ValueError, match="Connect a Pdfless"):
        await make_node({"operation": "get_workspace"}, False).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "generate_pdf", "template_id": "../pdfs"},
    {"operation": "generate_pdf", "template_id": TEMPLATE, "payload": "NaN"},
    {"operation": "generate_pdf", "template_id": TEMPLATE, "payload": "{"},
    {"operation": "list_document_templates", "page": 0},
    {"operation": "delete_template"},
])
def test_invalid_configs_are_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        make_node(config)


def test_credential_can_be_typed_without_discriminator_and_is_secret():
    credential = native.PdflessAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "pdfless_api_key"
    assert TOKEN not in repr(credential)
    for bad in ["https://app.pdfless.com/", "a\nb", "bad key"]:
        with pytest.raises(ValidationError):
            native.PdflessAPIKeyCredential(api_key=bad)
