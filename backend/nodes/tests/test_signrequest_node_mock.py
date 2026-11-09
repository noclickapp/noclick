"""SignRequest wire regressions: synthetic credentials and responses only."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import signrequest_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-signrequest-key"
UUID = "f2bac751-4fa1-43f1-91de-a1b8905c239a"
DOCUMENT = native.BASE + "/documents/" + UUID + "/"
FILE = "https://signrequest.com/static/demo/SignRequestDemoDocument.pdf"
CREDENTIAL = {"credential_type": "signrequest_api_token", "api_token": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="signrequest-test", node_type="automation-signrequest",
        node_data={"config": config, "credentials": CREDENTIAL})


def mock(monkeypatch, status, body):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config(operation):
    method, path, _ = native.ROUTES[operation]
    result = {"operation": operation}
    if "{uuid}" in path:
        result["uuid"] = UUID
    if "{subdomain}" in path:
        result["subdomain"] = "example-team"
    if operation in {"create_document", "quick_create_signrequest", "create_document_attachment"}:
        result["file_from_url"] = FILE
    if operation in {"create_signrequest", "create_document_attachment"}:
        result["document"] = DOCUMENT
    if operation in {"create_signrequest", "quick_create_signrequest"}:
        result.update(signers=[{"email": "signer@example.com", "order": 1}], from_email="sender@example.com")
    if operation == "forward_signer":
        result.update(signer_email_to_forward="old@example.com", signer_email_to_forward_to="new@example.com", forwarded_reason="New contact")
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.ROUTES))
async def test_each_operation_exactly_one_documented_request(monkeypatch, operation):
    routes = json.loads((Path(__file__).parent / "fixtures/signrequest/routes.json").read_text())
    method, path, status = routes[operation]
    listing = method == "GET" and "{" not in path
    body = {"count": 1, "next": None, "previous": None, "results": [{"uuid": UUID, "name": "Agreement"}]} if listing else {"uuid": UUID}
    requests = mock(monkeypatch, status, body)
    cfg = config(operation)
    result = await node(cfg).execute({})
    assert result["status"] == "success" and TOKEN not in str(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "signrequest.com"
    assert request.url.path == "/api/v1" + path.replace("{uuid}", UUID).replace("{subdomain}", "example-team")
    assert request.headers["Authorization"] == "Token " + TOKEN
    expected = {k: v for k, v in cfg.items() if k not in {"operation", "uuid", "subdomain"}}
    if listing:
        assert dict(request.url.params) == {"page": "1", "limit": "20"}
        assert result["data"] == body["results"] and result["next_page"] is None
    elif expected:
        assert json.loads(request.content) == expected
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_filters_and_pagination_never_follow_links(monkeypatch):
    requests = mock(monkeypatch, 200, {"count": 80, "next": "https://other.example/steal", "results": []})
    result = await node({"operation": "list_documents", "page": 2, "limit": 25, "external_id": "Deal + Café", "signrequest__from_email": "owner@example.com"}).execute({})
    assert result["has_more"] and result["next_page"] == 3 and len(requests) == 1
    assert dict(requests[0].url.params) == {"page": "2", "limit": "25", "external_id": "Deal + Café", "signrequest__from_email": "owner@example.com"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_errors_redact_token(monkeypatch, status):
    mock(monkeypatch, status, {"detail": "Permission denied " + TOKEN})
    result = await node({"operation": "list_documents"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Permission denied" in result["message"] and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"count": 1, "results": "bad"}, {"count": 1, "results": [1]}, {"errors": {"detail": "bad"}}])
async def test_malformed_pages_are_not_connection_evidence(monkeypatch, body):
    mock(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_documents"}).execute({})


@pytest.mark.asyncio
async def test_document_source_and_template_prefill(monkeypatch):
    requests = mock(monkeypatch, 201, {"uuid": UUID})
    for changes in ({}, {"file_from_url": FILE, "template": native.BASE + "/templates/" + UUID + "/"}):
        with pytest.raises(ValueError, match="exactly one"):
            await node({"operation": "create_document", **changes}).execute({})
    await node({"operation": "create_document", "template": native.BASE + "/templates/" + UUID + "/", "prefill_tags": [{"external_id": "name", "text": "Ada"}]}).execute({})
    assert len(requests) == 1 and "template" in json.loads(requests[0].content)


def test_manual_credential_and_input_validation():
    assert native.SignRequestTokenCredential(api_token=TOKEN).credential_type == "signrequest_api_token"
    assert native.SignRequestNode.connection_evidence.operation == "list_documents"
    for cfg in ({"operation": "get_document", "uuid": "../teams"}, {"operation": "list_documents", "page": 0}, {"operation": "create_signrequest", "document": DOCUMENT, "signers": []}):
        with pytest.raises(ValidationError):
            native.SignRequestConfig.model_validate({"config": cfg, "credentials": CREDENTIAL})
    with pytest.raises(ValidationError):
        native.SignRequestTokenCredential(api_token="Token abc")
