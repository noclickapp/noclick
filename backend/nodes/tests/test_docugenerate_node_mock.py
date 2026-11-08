"""Exercise the native factory and DocuGenerate's published HTTP contract offline."""
import base64
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import docugenerate_node as native
from nodes.core.registry import NodeFactory

TOKEN = "docugenerate-test-secret-42"
CREDENTIAL = {"credential_type": "docugenerate_api_key", "api_key": TOKEN}
FIXTURES = Path(__file__).parent / "fixtures" / "docugenerate"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="docugenerate-test", node_type="automation-docugenerate",
        node_data={"config": config, "credentials": CREDENTIAL})


def mock(monkeypatch, status=200, body=None):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def multipart(request):
    message = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.content)
    return {part.get_param('name', header='content-disposition'): (part.get_filename(), part.get_payload(decode=True))
        for part in message.iter_parts()}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_docugenerate_all_ten_routes_auth_and_response(monkeypatch, operation):
    method, path = native.ROUTES[operation]
    config = {"operation": operation}
    if "{id}" in path or operation in {"list_documents", "generate_document"}:
        config["template_id" if "template" in operation or operation in {"list_documents", "generate_document"} else "document_id"] = "CctvL5PkbEifvnkDh6L0"
    if operation == "create_template":
        config.update(file_base64=base64.b64encode(b'Hello [Name]').decode(), file_name="letter.txt")
    if operation in {"update_template", "update_document"}:
        config["name"] = "New name"
    if operation == "generate_document":
        config.update(data={"Name": "Alice"}, output_format=".pdf", single_file=False, page_break=False)
    body = json.loads((FIXTURES / ("template.json" if "template" in operation else "document.json")).read_text())
    response_body = [body] if operation.startswith("list_") else body
    status = 204 if method == "DELETE" else 201 if method == "POST" else 200
    requests = mock(monkeypatch, status, response_body)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split('?')[0] == native.BASE_URL + path.replace("{id}", "CctvL5PkbEifvnkDh6L0")
    assert request.headers["Authorization"] == TOKEN
    assert request.headers["Accept"] == "application/json"
    if operation == "list_documents":
        assert dict(request.url.params) == {"template_id": config["template_id"]}
    if operation == "create_template":
        assert multipart(request)["file"] == ("letter.txt", b'Hello [Name]')
    if operation == "update_template":
        assert multipart(request) == {"name": (None, b"New name")}
    if operation == "generate_document":
        assert json.loads(request.content) == {k: v for k, v in config.items() if k != "operation"}
    if method == "DELETE":
        assert result["deleted"] is True and not request.content
    else:
        assert result["data"] == response_body


@pytest.mark.asyncio
async def test_docugenerate_folder_filter_repeats_query_keys(monkeypatch):
    requests = mock(monkeypatch, body=[])
    await node({"operation": "list_templates", "folder": ["Legal", "Contracts"]}).execute({})
    assert requests[0].url.params.multi_items() == [("folder", "Legal"), ("folder", "Contracts")]


@pytest.mark.asyncio
async def test_docugenerate_optional_template_flags_serialize_false_and_omit_unspecified(monkeypatch):
    requests = mock(monkeypatch, body={"id": "template"})
    await node({"operation": "update_template", "template_id": "template", "enhanced_syntax": False,
        "versioning_enabled": True}).execute({})
    assert multipart(requests[0]) == {"enhanced_syntax": (None, b"false"), "versioning_enabled": (None, b"true")}


@pytest.mark.asyncio
async def test_docugenerate_resource_id_is_one_path_component(monkeypatch):
    requests = mock(monkeypatch, body={"id": "x/y?z"})
    await node({"operation": "get_document", "document_id": "x/y?z"}).execute({})
    assert requests[0].url.raw_path == b"/v1/document/x%2Fy%3Fz"


@pytest.mark.asyncio
async def test_docugenerate_provider_rejection_keeps_words_and_redacts_key(monkeypatch):
    mock(monkeypatch, 401, {"message": "Unauthorized " + TOKEN})
    with pytest.raises(ValueError, match="DocuGenerate HTTP 401") as error:
        await node({"operation": "list_templates"}).execute({})
    assert "Unauthorized" in str(error.value) and TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_docugenerate_rejects_wrong_response_shape(monkeypatch):
    mock(monkeypatch, body={"message": "unexpected"})
    with pytest.raises(ValueError, match="unexpected JSON response"):
        await node({"operation": "list_templates"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "create_template", "file_base64": "invalid"},
    {"operation": "update_template", "template_id": "template"},
    {"operation": "update_document", "document_id": "document"},
    {"operation": "generate_document", "template_id": "template", "data": {}, "output_quality": 101},
    {"operation": "generate_document", "template_id": "template", "data": "invalid"},
    {"operation": "generate_document", "template_id": "template", "merge_with": ["invalid"]},
    {"operation": "generate_document", "template_id": "template", "attach": ["invalid"]},
])
def test_docugenerate_invalid_inputs_fail_before_http(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_docugenerate_credential_title_and_evidence_operation():
    assert native.DocugenerateAPIKey.model_json_schema()["title"] == "Docugenerate API Key"
    assert native.DocugenerateNode.connection_evidence.operation == "list_templates"
    assert native.ListTemplates().model_dump(exclude_none=True) == {"operation": "list_templates"}
    assert native.DocugenerateAPIKey(**{**CREDENTIAL, "api_key": "  " + TOKEN + "  "}).api_key == TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ['{"Name":"Alice"}', '[{"Name":"Alice"},{"Name":"Bob"}]'])
async def test_docugenerate_json_editor_text_becomes_structured_api_data(monkeypatch, data):
    requests = mock(monkeypatch, body={"id": "document"})
    await node({"operation": "generate_document", "template_id": "template", "data": data,
        "merge_with": ["https://example.com/append.pdf"],
        "attach": ["data:text/xml;name=invoice.xml;base64,PHgvPg=="]}).execute({})
    body = json.loads(requests[0].content)
    assert body["data"] == json.loads(data)
    assert body["merge_with"] == ["https://example.com/append.pdf"]
    assert body["attach"] == ["data:text/xml;name=invoice.xml;base64,PHgvPg=="]


@pytest.mark.parametrize("data", ['42', '"scalar"', '[1]', 'null'])
def test_docugenerate_json_editor_rejects_non_records(data):
    with pytest.raises((ValidationError, ValueError)):
        node({"operation": "generate_document", "template_id": "template", "data": data})
