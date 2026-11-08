"""Native Veryfi transport, signing, projection and lifecycle fixtures.

HTTPX MockTransport replaces the remote boundary of the actual guarded client.
"""
import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import veryfi_node as node
from utils import ssrf

CREDENTIAL = {"credential_type": node.TYPES[0], "client_id": "fixtureClient", "api_key": "fixture-key", "environment": "production", "client_secret": None}
DOCUMENT = {"id": 17, "status": "processed", "created_date": "2026-10-06T00:00:00Z", "total": 12.5, "currency_code": "USD", "document_type": "receipt", "ocr_text": "PRIVATE OCR", "vendor": {"bank_account_number": "PRIVATE BANK"}, "customer": {"email": "PRIVATE EMAIL"}, "card_number": "PRIVATE CARD", "img_url": "https://private.example/secret"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    state = {"responses": [], "calls": []}
    async def respond(request):
        state["calls"].append(request)
        assert request.url.host in {"api.veryfi.com", "devapi.veryfi.com"}
        assert request.headers["CLIENT-ID"] == "fixtureClient"
        assert "api_key" not in request.url.params and "client_secret" not in request.url.params
        response = state["responses"].pop(0)
        return response(request) if callable(response) else response
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(respond), **kwargs))
    return state


def upload(operation="process_document"):
    return {"operation": operation, "file_name": "fixture.pdf", "file_data": base64.b64encode(b"%PDF-1.4\n" + b"x" * 250).decode(), "idempotency_key": "fixture-upload-unique", "confirm_processing": True}


def test_raw_types_and_explicit_confirmation_before_shared_coercion():
    for credential in ({}, {**CREDENTIAL, "credential_type": "veryfi_oauth"}, {**CREDENTIAL, "credential_type": None}):
        raw = {"credentials": credential, "config": {"operation": "list_documents"}}
        with pytest.raises(ValueError):
            node.VeryfiNode.parse_config(raw)
        assert node.VeryfiNode.validate_config(raw)["valid"] is False
    for changes in ({"document_id": 17}, {"document_id": "17", "confirm_delete": 1}, {"document_id": "17", "confirm_delete": "true"}):
        with pytest.raises(ValueError):
            node.VeryfiNode.parse_config({"credentials": CREDENTIAL, "config": {"operation": "delete_document", **changes}})


@pytest.mark.parametrize("change", [{"file_name": "../fixture.pdf"}, {"file_data": "data:application/pdf;base64,YWJj"}, {"file_data": base64.b64encode(b"x" * 300).decode()}, {"file_data": "YQ=="}, {"idempotency_key": "bad\r\nheader"}, {"idempotency_key": "é"}, {"max_pages_to_process": 16}, {"confirm_processing": False}])
def test_upload_rejects_paths_bad_content_and_unsafe_header(change):
    with pytest.raises(ValueError):
        node.ProcessDocument.model_validate({**upload(), **change})


def test_signing_matches_exact_documented_python_message():
    payload = {"file_name": "fixture.pdf", "async": False, "allowed_async_enrichments": []}
    message = b"timestamp:1791244800123,file_name:fixture.pdf,async:False,allowed_async_enrichments:[]"
    expected = base64.b64encode(hmac.new(b"fixture-signing-secret", message, hashlib.sha256).digest()).decode()
    assert node.signature("fixture-signing-secret", payload, 1791244800123) == expected
    assert node.signature("fixture-signing-secret", {}, 1791244800123) != expected


async def test_signed_bearer_upload_201_projection_and_idempotency(transport, monkeypatch):
    monkeypatch.setattr(node.time, "time", lambda: 1791244800.123)
    transport["responses"] = [httpx.Response(201, json=DOCUMENT)]
    config = node.ProcessDocument.model_validate(upload())
    result = await node.request_operation({**CREDENTIAL, "client_secret": "fixture-signing-secret"}, config)
    request = transport["calls"][0]
    body = json.loads(request.content)
    assert request.headers["Authorization"] == "Bearer fixture-key"
    assert request.headers["Idempotency-Key"] == config.idempotency_key
    assert request.headers["X-Veryfi-Request-Signature"] == node.signature("fixture-signing-secret", body, 1791244800123)
    assert body["async"] is False and body["allowed_async_enrichments"] == [] and body["max_pages_to_process"] == 1
    assert result["http_status"] == 201 and result["submission_accepted"] is True
    assert result["data"]["total"] == 12.5 and result["processing_completion_verified"] is False
    assert all(secret not in str(result) for secret in ("PRIVATE", "img_url", "ocr_text", "fixture-key", "fixture-signing-secret"))


async def test_async_201_id_only_is_accepted_without_completion_claim(transport):
    transport["responses"] = [httpx.Response(201, json={"id": 17})]
    result = await node.request_operation(CREDENTIAL, node.ProcessDocumentAsync.model_validate(upload("process_document_async")))
    assert result["data"] == {"id": "17"} and result["processing_mode"] == "asynchronous"
    assert result["processing_completion_verified"] is False and result["webhook_delivery_verified"] is False
    assert len(transport["calls"]) == 1 and json.loads(transport["calls"][0].content)["async"] is True


async def test_legacy_header_development_and_empty_page(transport):
    transport["responses"] = [httpx.Response(200, json={"documents": [], "meta": {"documents_per_page": 10, "page_number": 1, "total_pages": 0, "total_results": 0}})]
    legacy = {**CREDENTIAL, "credential_type": node.TYPES[1], "username": "fixture-user", "environment": "development"}
    result = await node.request_operation(legacy, node.ListDocuments())
    assert result["data"]["items"] == [] and result["data"]["next_page_token"] is None
    request = transport["calls"][0]
    assert request.url.host == "devapi.veryfi.com" and request.headers["Authorization"] == "apikey fixture-user:fixture-key"
    assert "X-Veryfi-Request-Signature" not in request.headers


async def test_search_accurate_paging_binding_and_picker_native_results(transport):
    page = {"documents": [DOCUMENT], "meta": {"documents_per_page": 50, "page_number": 1, "total_pages": 2, "total_results": 51}}
    transport["responses"] = [httpx.Response(200, json=page)]
    result = await node.VeryfiNode.load_field_options("document_id", CREDENTIAL, search="merchant*")
    assert result["options"] == [{"value": "17", "label": "Document 17", "metadata": {"id": "17"}}]
    request = transport["calls"][0]
    assert request.url.params["q"] == "merchant*" and request.url.params["track_total_results"] == "true"
    for credential, search in (({**CREDENTIAL, "client_id": "changedClient"}, "merchant*"), (CREDENTIAL, "different*")):
        with pytest.raises(ValueError, match="Continuation changed"):
            await node.VeryfiNode.load_field_options("document_id", credential, page_token=result["next_page_token"], search=search)
    assert len(transport["calls"]) == 1


@pytest.mark.parametrize("response", [httpx.Response(202, json={"id": 17}), httpx.Response(204), httpx.Response(302, headers={"location": "https://foreign.example"}), httpx.Response(200, json={"status": "fail", "error": "fixture-key PRIVATE ERROR"}), httpx.Response(200, content=b'{"id":17,"total":1e999}', headers={"content-type": "application/json"}), httpx.Response(200, content=b'{"id":17,"id":18}', headers={"content-type": "application/json"}), httpx.Response(200, content=b"x" * (node.MAX_BYTES + 1), headers={"content-type": "application/json"})])
async def test_unexpected_status_error_and_nonfinite_results_fail_without_leak(transport, response):
    transport["responses"] = [response]
    with pytest.raises(ValueError) as error:
        await node.request_operation(CREDENTIAL, node.GetDocument(document_id="17"))
    assert "fixture-key" not in str(error.value) and "PRIVATE ERROR" not in str(error.value) and len(transport["calls"]) == 1


async def test_504_no_blind_retry_and_numeric_rate_hint(transport):
    transport["responses"] = [httpx.Response(504)]
    with pytest.raises(node.VeryfiAPIError, match="billed"):
        await node.request_operation(CREDENTIAL, node.ProcessDocument.model_validate(upload()))
    assert len(transport["calls"]) == 1
    transport["responses"] = [httpx.Response(429, headers={"retry-after": "12"})]
    with pytest.raises(node.VeryfiAPIError) as error:
        await node.request_operation(CREDENTIAL, node.GetStatus(document_id="17"))
    assert error.value.retry_after == 12 and len(transport["calls"]) == 2


async def test_metadata_explicit_null_omitted_notes_and_actual_readback(transport):
    changed = {**DOCUMENT, "external_id": None, "notes": "keep me"}
    transport["responses"] = [httpx.Response(200, json=changed)] * 3
    result = await node.request_operation(CREDENTIAL, node.UpdateMetadata(document_id="17", external_id=None, confirm_update=True))
    assert json.loads(transport["calls"][1].content) == {"external_id": None}
    assert result["readback_verified"] is True and result["data"]["notes"] == "keep me"
    with pytest.raises(ValueError):
        node.UpdateMetadata(document_id="17", confirm_update=True)


async def test_wrong_document_preflight_prevents_metadata_write(transport):
    transport["responses"] = [httpx.Response(200, json={**DOCUMENT, "id": 18})]
    with pytest.raises(ValueError, match="different document"):
        await node.request_operation(CREDENTIAL, node.UpdateMetadata(document_id="17", notes="new", confirm_update=True))
    assert [request.method for request in transport["calls"]] == ["GET"]


@pytest.mark.parametrize("after, confirmed", [(httpx.Response(404), True), (httpx.Response(403), False), (httpx.Response(200, json=DOCUMENT), False)])
async def test_delete_200_empty_and_protected_absence_readback(transport, after, confirmed):
    transport["responses"] = [httpx.Response(200, json=DOCUMENT), httpx.Response(200), after]
    config = node.DeleteDocument(document_id="17", confirm_delete=True)
    if confirmed:
        result = await node.request_operation(CREDENTIAL, config)
        assert result["data"]["deleted"] is True and result["data"]["absence_readback_verified"] is True
    else:
        with pytest.raises(ValueError):
            await node.request_operation(CREDENTIAL, config)
    assert [request.method for request in transport["calls"]] == ["GET", "DELETE", "GET"]


async def test_add_and_unlink_parent_tags_are_verified(transport):
    tag = {"id": 7, "name": "expense"}
    transport["responses"] = [httpx.Response(200, json=DOCUMENT), httpx.Response(200, json={"tags": []}), httpx.Response(200, json=tag), httpx.Response(200, json={"tags": [tag]})]
    result = await node.request_operation(CREDENTIAL, node.AddTag(document_id="17", name="expense", confirm_update=True))
    assert result["readback_verified"] is True and result["data"]["tag"]["id"] == "7"
    transport["responses"] = [httpx.Response(200, json=DOCUMENT), httpx.Response(200, json={"tags": [tag]}), httpx.Response(200), httpx.Response(200, json={"tags": []})]
    result = await node.request_operation(CREDENTIAL, node.UnlinkTag(document_id="17", tag_id="7", confirm_update=True))
    assert result["data"]["unlinked"] is True and transport["calls"][-2].url.path.endswith("/17/tags/7")


async def test_tag_picker_requires_parent_and_refuses_scope_forgery_before_io(transport):
    for context in ({}, {"document_id": "17", "client_id": "forged"}, {"document_id": "17", "environment": "development"}):
        with pytest.raises(ValueError):
            await node.VeryfiNode.load_field_options("tag_id", CREDENTIAL, context=context)
    assert transport["calls"] == []


async def test_secret_input_and_private_override_stop_before_transport(transport, monkeypatch):
    with pytest.raises(ValueError, match="credential bytes"):
        await node.request_operation(CREDENTIAL, node.ListDocuments(q="fixture-key"))
    monkeypatch.setattr(node, "allow_private_hosts", lambda: True)
    with pytest.raises(ValueError, match="private overrides"):
        await node.request_operation(CREDENTIAL, node.ListDocuments())
    assert transport["calls"] == []
