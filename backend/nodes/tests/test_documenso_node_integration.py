"""Contract tests for the V2 Documenso envelope integration.

The provider account is exercised separately in live FlowCanvas QA. These tests
assert the real HTTP shape, draft/send separation, and safe PDF handling.
"""

import base64
import json
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.binary_output import BinaryOutput

from nodes.documenso_node import (
    AddEnvelopeItem,
    AddFields,
    AddRecipients,
    CreateEnvelope,
    CreateFolder,
    DeleteFolder,
    DeleteEnvelopeItem,
    DistributeEnvelope,
    DownloadEnvelopeItem,
    DocumensoAPIKeyCredential,
    DocumensoNode,
    DocumensoNodeConfig,
    ListEnvelopes,
    UpdateFolder,
    UseTemplate,
    _bounded_pdf,
    _pdf_bytes,
    _request,
)


def _node(config):
    return DocumensoNode(
        node_id="documenso-test", node_type="automation-documenso", node_data={},
        config=DocumensoNodeConfig(
            config=config, credentials=DocumensoAPIKeyCredential(api_key="api_test_secret")
        ),
        sio=Mock(), sid="test-sid", workflow_id="test-workflow", user_id="test-user",
    )


@pytest.mark.parametrize("model,values", [(CreateFolder, {}), (UpdateFolder, {"folder_id": "folder_1"})])
def test_folder_name_limits_match_provider(model, values):
    for size in (1, 101):
        with pytest.raises(ValidationError):
            model(name="a" * size, **values)
    for size in (2, 100):
        assert model(name="a" * size, **values).name == "a" * size
    assert UpdateFolder(folder_id="folder_1", pinned=True).name is None


@pytest.mark.asyncio
async def test_create_envelope_uploads_pdf_as_unsent_multipart(monkeypatch):
    seen = []
    original_client = httpx.AsyncClient

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "envelope_created"})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        "nodes.documenso_node.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    pdf = b"%PDF-1.4\n1 0 obj\nendobj\n%%EOF"
    node = _node(CreateEnvelope(
        title="QA agreement", pdf_base64=base64.b64encode(pdf).decode(),
        recipients_json='[{"email":"qa@example.com","name":"QA","role":"SIGNER"}]',
    ))

    result = await node.execute({})

    assert result["data"]["id"] == "envelope_created"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v2/envelope/create"
    assert request.headers["authorization"] == "api_test_secret"
    assert request.headers["content-type"].startswith("multipart/form-data;")
    body = request.content.decode("latin-1")
    assert 'name="payload"' in body
    assert 'name="files"; filename="document.pdf"' in body
    assert '"type": "DOCUMENT"' in body
    assert '"distributeDocument"' not in body
    assert "%PDF-1.4" in body


@pytest.mark.asyncio
async def test_template_use_explicitly_stays_draft(monkeypatch):
    seen = []
    original_client = httpx.AsyncClient

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "envelope_draft"})

    monkeypatch.setattr(
        "nodes.documenso_node.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await _node(UseTemplate(envelope_id="envelope_template", external_id="qa-1")).execute({})

    assert result["data"]["id"] == "envelope_draft"
    assert seen[0].url.path == "/api/v2/envelope/use"
    assert seen[0].headers["content-type"].startswith("multipart/form-data;")
    assert '"distributeDocument": false' in seen[0].content.decode()


@pytest.mark.asyncio
async def test_prepare_then_send_is_separate_operation(monkeypatch):
    calls = []

    async def fake_request(key, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"success": True}

    monkeypatch.setattr("nodes.documenso_node._request", fake_request)
    await _node(AddRecipients(
        envelope_id="envelope_draft",
        recipients_json='[{"email":"qa@example.com","name":"QA","role":"SIGNER"}]',
    )).execute({})
    await _node(AddFields(
        envelope_id="envelope_draft",
        fields_json='[{"type":"SIGNATURE","recipientId":1,"page":1,"positionX":10,"positionY":80,"width":30,"height":5}]',
    )).execute({})
    assert [path for _, path, _ in calls] == [
        "/envelope/recipient/create-many", "/envelope/field/create-many"
    ]
    assert calls[1][2]["body"]["data"][0]["type"] == "SIGNATURE"

    await _node(DistributeEnvelope(envelope_id="envelope_draft")).execute({})
    assert calls[2] == (
        "POST", "/envelope/distribute", {"body": {"envelopeId": "envelope_draft"}}
    )


@pytest.mark.asyncio
async def test_list_envelopes_uses_documented_filters_and_paginates(monkeypatch):
    calls = []

    async def fake_request(key, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"data": [{"id": "envelope_a", "title": "QA"}], "currentPage": 2, "totalPages": 3}

    monkeypatch.setattr("nodes.documenso_node._request", fake_request)
    result = await _node(ListEnvelopes(page=2, status="DRAFT", envelope_type="DOCUMENT")).execute({})
    assert result["data"]["data"][0]["id"] == "envelope_a"
    assert calls[0][0:2] == ("GET", "/envelope")
    assert calls[0][2]["params"]["status"] == "DRAFT"
    assert calls[0][2]["params"]["type"] == "DOCUMENT"

    options = await DocumensoNode.load_field_options("envelope_id", {"api_key": "api_test_secret"}, page_token="2")
    assert options["options"] == [{"value": "envelope_a", "label": "QA"}]
    assert options["next_page_token"] == "3"


@pytest.mark.asyncio
async def test_http_error_never_leaks_token(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.documenso_node.httpx.AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"message": "Unauthorized"})),
            **kwargs,
        ),
    )
    with pytest.raises(ValueError, match="HTTP 401") as exc:
        await _request("api_test_secret", "GET", "/envelope")
    assert "api_test_secret" not in str(exc.value)


def test_pdf_and_json_validation():
    with pytest.raises(ValueError, match="not a PDF"):
        _pdf_bytes(base64.b64encode(b"hello").decode())
    with pytest.raises(ValueError, match="invalid"):
        _pdf_bytes("not-base64")
    with pytest.raises(ValueError, match="Recipients JSON must be a JSON array"):
        from nodes.documenso_node import _json_array
        _json_array(json.dumps({"email": "qa@example.com"}), "Recipients JSON")


@pytest.mark.asyncio
async def test_folder_crud_uses_current_v2_shapes(monkeypatch):
    calls = []

    async def fake_request(key, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"id": "folder_1"}

    monkeypatch.setattr("nodes.documenso_node._request", fake_request)
    await _node(CreateFolder(name="QA drafts", folder_type="DOCUMENT")).execute({})
    await _node(UpdateFolder(folder_id="folder_1", name="QA archive", pinned=True)).execute({})
    await _node(DeleteFolder(folder_id="folder_1")).execute({})
    assert calls == [
        ("POST", "/folder/create", {"body": {"name": "QA drafts", "type": "DOCUMENT"}}),
        ("POST", "/folder/update", {"body": {"folderId": "folder_1", "data": {"name": "QA archive", "pinned": True}}}),
        ("POST", "/folder/delete", {"body": {"folderId": "folder_1"}}),
    ]


@pytest.mark.asyncio
async def test_pdf_item_create_and_delete_use_v2_payloads(monkeypatch):
    calls = []

    async def fake_request(key, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"success": True}

    monkeypatch.setattr("nodes.documenso_node._request", fake_request)
    pdf = b"%PDF-1.4\n%%EOF"
    await _node(AddEnvelopeItem(
        envelope_id="envelope_draft", pdf_base64=base64.b64encode(pdf).decode(),
        filename="additional.pdf",
    )).execute({})
    await _node(DeleteEnvelopeItem(
        envelope_id="envelope_draft", envelope_item_id="envelope_item_extra",
    )).execute({})
    assert calls[0] == (
        "POST", "/envelope/item/create-many",
        {"payload": {"envelopeId": "envelope_draft"}, "pdf": pdf, "filename": "additional.pdf"},
    )
    assert calls[1] == (
        "POST", "/envelope/item/delete",
        {"body": {"envelopeId": "envelope_draft", "envelopeItemId": "envelope_item_extra"}},
    )


@pytest.mark.asyncio
async def test_download_signed_pdf_uses_item_endpoint(monkeypatch):
    requests = []
    original_client = httpx.AsyncClient
    pdf = b"%PDF-1.4\n%%EOF"

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})

    monkeypatch.setattr(
        "nodes.documenso_node.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await _node(DownloadEnvelopeItem(envelope_item_id="envelope_item_abc")).execute({})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == pdf
    assert result["data"].content_type == "application/pdf"
    assert result["data"].filename == "envelope_item_abc_signed.pdf"
    assert requests[0].url.path == "/api/v2/envelope/item/envelope_item_abc/download"
    assert requests[0].url.params["version"] == "signed"


@pytest.mark.asyncio
async def test_download_redirect_does_not_forward_api_key(monkeypatch):
    provider_requests = []
    storage_requests = []
    original_client = httpx.AsyncClient

    def provider(request):
        provider_requests.append(request)
        return httpx.Response(302, headers={"location": "https://storage.example.com/signed.pdf"})

    def storage(request):
        storage_requests.append(request)
        return httpx.Response(200, content=b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr(
        "nodes.documenso_node.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs),
    )
    monkeypatch.setattr(
        "nodes.documenso_node.guarded_async_client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(storage), **kwargs),
    )
    result = await _node(DownloadEnvelopeItem(envelope_item_id="envelope_item_abc")).execute({})
    assert result["status"] == "success"
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"%PDF-1.4\n%%EOF"
    assert result["data"].content_type == "application/pdf"
    assert result["data"].filename == "envelope_item_abc_signed.pdf"
    assert provider_requests[0].headers["authorization"] == "api_test_secret"
    assert "authorization" not in storage_requests[0].headers


@pytest.mark.asyncio
async def test_pdf_stream_rejects_oversize_before_accumulating(monkeypatch):
    from nodes.documenso_node import MAX_PDF_BYTES

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"%PDF-"
            yield b"x" * MAX_PDF_BYTES

    response = httpx.Response(200, stream=Chunks())
    with pytest.raises(ValueError, match="20 MB"):
        await _bounded_pdf(response)
