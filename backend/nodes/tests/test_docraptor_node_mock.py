"""Native factory requests, binary results, and the read-only connect probe."""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import docraptor_node as module
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential
from utils import ssrf

TOKEN = "fixture-docraptor-key"
AUTH = {"credential_type": "docraptor_api_key", "api_key": TOKEN, "status_id": "123454321"}
SPREADSHEET = {"name": "July Invoice for User #1234", "document_content": "<table><tr><td>Example!</td></tr></table>"}
CONTENT = {"name": "docraptor-python.pdf", "document_content": "<html><body>Hello World</body></html>"}
# Provider response: https://docraptor.com/documentation/api#api_async
STATUS = json.loads((Path(__file__).parent / "fixtures/docraptor/status.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        status, payload = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, headers={"content-type": "application/pdf"})
        return httpx.Response(status, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(module, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, arguments=None, auth=None):
    return NodeFactory.create_node(node_id="docraptor-test", node_type="automation-docraptor", node_data={
        "config": {"operation": operation, **(arguments or {})}, "credentials": AUTH if auth is None else auth,
    })


CASES = [
    ("create_pdf", CONTENT, "POST", "/docs", b"%PDF-1.4"),
    ("create_xls", SPREADSHEET, "POST", "/docs", b"xls-bytes"),
    ("create_xlsx", SPREADSHEET, "POST", "/docs", b"xlsx-bytes"),
    ("create_hosted_document", {**CONTENT, "document_type": "pdf", "hosted_download_limit": 5}, "POST", "/hosted_docs", {"download_id": "id1", "download_url": "https://example.test/hosted"}),
    ("create_async_document", {**SPREADSHEET, "document_type": "xlsx", "callback_url": "https://example.test/callback"}, "POST", "/async_docs", {"status_id": "123454321"}),
    ("create_hosted_async_document", CONTENT, "POST", "/hosted_async_docs", {"status_id": "123454321"}),
    ("get_document_status", {"status_id": "123454321"}, "GET", "/status/123454321", STATUS),
    ("download_document", {"download_id": "12345asdf"}, "GET", "/download/12345asdf", b"%PDF-1.4"),
    ("expire_document", {"download_id": "12345asdf"}, "PATCH", "/expire/12345asdf", b""),
    ("check_connection", {}, "GET", "/status/123454321", STATUS),
]


@pytest.mark.parametrize("operation,arguments,method,path,payload", CASES)
async def test_native_request_and_output(transport, operation, arguments, method, path, payload):
    requests, replies = transport
    replies.append((200, payload))
    result = await node(operation, arguments).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.docraptor.com"
    assert request.url.path == path
    assert request.headers["Authorization"] == "Basic " + base64.b64encode((TOKEN + ":").encode()).decode()
    assert not request.url.query and TOKEN not in str(request.url)
    if method == "POST":
        body = json.loads(request.content)
        assert body["name"] == arguments["name"]
        assert body["document_content"] == arguments["document_content"]
        assert body["document_type"] == (operation.removeprefix("create_") if operation in {"create_pdf", "create_xls", "create_xlsx"} else arguments.get("document_type", "pdf"))
        assert body["test"] is True
        for key in ("hosted_download_limit", "callback_url"):
            if key in arguments:
                assert body[key] == arguments[key]
        assert "operation" not in body
    else:
        assert not request.content
    if isinstance(payload, bytes) and payload:
        assert isinstance(result["file"], BinaryOutput)
        assert result["file"].data == payload
    elif operation == "expire_document":
        assert result["expired"] is True
    else:
        assert result["data"] == payload


async def test_url_source_and_production_options(transport):
    requests, replies = transport
    replies.append((200, b"%PDF-1.4"))
    await node("create_pdf", {"name": "invoice.pdf", "document_url": "https://www.docraptor.com/documentation", "test": False,
        "prince_options": {"media": "screen", "pdf_title": "Invoice"}}).execute({})
    body = json.loads(requests[0].content)
    assert body["test"] is False
    assert "document_content" not in body
    assert body["prince_options"] == {"media": "screen", "pdf_title": "Invoice"}


@pytest.mark.parametrize("arguments", [{"name": "missing"}, {**CONTENT, "document_url": "https://example.test"}])
def test_content_source_required_and_exclusive(arguments):
    with pytest.raises(ValueError, match="exactly one"):
        node("create_pdf", arguments)


@pytest.mark.parametrize("identifier", ["../escape", "a/b", "a?query", "a#fragment", "", "https://example.test"])
def test_path_ids_reject_injection(identifier):
    with pytest.raises(ValueError):
        node("get_document_status", {"status_id": identifier})


def test_manual_credential_default_and_fields():
    credential = module.DocraptorAPIKeyCredential.model_validate({"api_key": TOKEN, "status_id": "123454321"})
    assert credential.credential_type == module.TYPE
    shaped, errors, resolved = shape_credential(module.TYPE, {"api_key": TOKEN, "status_id": "123454321"})
    assert not errors
    assert module.DocraptorAPIKeyCredential.model_validate(shaped).credential_type == module.TYPE
    assert resolved[1] is module.DocraptorAPIKeyCredential
    with pytest.raises(ValidationError):
        module.DocraptorAPIKeyCredential.model_validate({**AUTH, "api_key": "https://example.test/key"})


@pytest.mark.parametrize("code", [401, 403, 422, 500, 302])
async def test_errors_and_redirects_are_not_success(transport, code):
    requests, replies = transport
    replies.append((code, b"Provider rejected request"))
    result = await node("check_connection").execute({})
    assert result == {"status": "error", "http_status": code, "error": "Provider rejected request"}
    assert len(requests) == 1


async def test_connection_evidence_uses_only_existing_document_read(transport):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = transport
    replies.append((200, STATUS))
    evidence = await collect_evidence(node_type="automation-docraptor", user_id="00000000-0000-4000-8000-000000000001", credential_data=AUTH)
    assert evidence.reachable is True
    assert [(r.method, r.url.path) for r in requests] == [("GET", "/status/123454321")]
