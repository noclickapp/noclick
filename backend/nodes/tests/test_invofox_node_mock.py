"""Offline Invofox contract regressions; no live account or writes."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import invofox_node as api
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "invofox_api_key", "api_key": "invofox-test-key-42"}
ID = "507f1f77bcf86cd799439011"
BUSINESS = {"country_code": "ES", "tax_id": "B12345678", "name": "Example Company"}


def node(config, auth=None):
    return NodeFactory.create_node(node_id="invofox-fixture", node_type="automation-invofox",
        node_data={"config": config, "credentials": AUTH if auth is None else auth})


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    def respond(request):
        calls.append(request)
        code, body, headers = replies.pop(0)
        return httpx.Response(code, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(api, "guarded_async_client", client)
    return calls, replies


CASES = [
    ({"operation": "list_documents", "skip": 5, "limit": 10, "filter": '{"type":"invoice"}', "select": ["name", "data"]}, "GET", "/documents", None),
    ({"operation": "get_document", "document_id": ID}, "GET", f"/documents/{ID}", None),
    ({"operation": "update_document", "document_id": ID, "data": {"invoiceNumber": {"value": "INV-001"}}, "client_data": {"externalId": "42"}}, "PUT", f"/documents/{ID}", {"data": {"invoiceNumber": {"value": "INV-001"}}, "clientData": {"externalId": "42"}}),
    ({"operation": "get_document_ocr", "document_id": ID}, "GET", f"/documents/{ID}/ocr", None),
    ({"operation": "get_document_text", "document_id": ID}, "GET", f"/documents/{ID}/text", None),
    ({"operation": "change_document_type", "document_id": ID, "document_type": "invoice"}, "PUT", f"/documents/{ID}/type", {"type": "invoice"}),
    ({"operation": "change_document_state", "document_id": ID, "public_state": "approved"}, "PUT", f"/documents/{ID}/publicState", {"publicState": "approved"}),
    ({"operation": "list_companies", "country_code": "ES"}, "GET", "/companies", None),
    ({"operation": "create_company", **BUSINESS}, "POST", "/companies", {"countryCode": "ES", "taxId": "B12345678", "name": "Example Company"}),
    ({"operation": "update_company", "company_id": ID, **BUSINESS}, "PUT", f"/companies/{ID}", {"countryCode": "ES", "taxId": "B12345678", "name": "Example Company"}),
    ({"operation": "delete_company", "company_id": ID}, "DELETE", f"/companies/{ID}", None),
    ({"operation": "upload_files_by_url", "files": [{"url": "https://example.com/invoice.pdf", "info": {"type": "invoice"}}], "info": {"company": ID}}, "POST", "/v1/ingest/by-url", {"files": [{"url": "https://example.com/invoice.pdf", "info": {"type": "invoice"}}], "info": {"company": ID}}),
    ({"operation": "upload_single_by_url", "url": "https://example.com/invoice.pdf", "info": {"type": "invoice"}}, "POST", "/v1/ingest/single-url", {"url": "https://example.com/invoice.pdf", "info": {"type": "invoice"}}),
    ({"operation": "get_file", "file_id": ID}, "GET", f"/v1/ingest/files/{ID}", None),
    ({"operation": "list_imports", "environment_id": ID, "skip": 2, "limit": 15}, "GET", "/v1/ingest/imports", None),
    ({"operation": "get_import", "import_id": ID}, "GET", f"/v1/ingest/imports/{ID}", None),
]
for plural, singular, id_field in [("providers", "provider", "provider_id"), ("clients", "client", "client_id")]:
    root = f"/companies/{ID}/{plural}"
    CASES.extend([
        ({"operation": "list_" + plural, "company_id": ID}, "GET", root, None),
        ({"operation": "create_" + singular, "company_id": ID, **BUSINESS}, "POST", root, {"countryCode": "ES", "taxId": "B12345678", "name": "Example Company"}),
        ({"operation": "update_" + singular, "company_id": ID, id_field: ID, **BUSINESS}, "PUT", root + "/" + ID, {"countryCode": "ES", "taxId": "B12345678", "name": "Example Company"}),
        ({"operation": "delete_" + singular, "company_id": ID, id_field: ID}, "DELETE", root + "/" + ID, None),
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_invofox_operation_wire_contract(transport, config, method, path, body):
    calls, replies = transport
    response = {"result": [{"_id": ID, "name": "Example Company"}], "count": 1}
    replies.append((200, response, {}))
    assert await node(config).execute({}) == ({"file": response} if config["operation"] == "get_file" else response)
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.invofox.com"
    assert request.headers["x-api-key"] == AUTH["api_key"]
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"] == "list_documents":
        assert request.url.params.get_list("select") == ["name", "data"]
        assert request.url.params["skip"] == "5" and request.url.params["limit"] == "10"
        assert request.url.params["filter"] == config["filter"]
    if config["operation"] == "list_imports":
        assert dict(request.url.params) == {"skip": "2", "limit": "15", "environmentId": ID}


@pytest.mark.asyncio
async def test_empty_account_connection_read_and_manual_credential(transport):
    _, replies = transport
    replies.append((200, {"result": [], "count": 0}, {}))
    assert api.InvofoxAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "invofox_api_key"
    assert await node({"operation": "list_companies"}).execute({}) == {"result": [], "count": 0}
    assert api.InvofoxNode.connection_evidence.operation == "list_companies"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,headers", [
    (401, {"message": "Invalid key"}, {}), (403, {"message": "Forbidden"}, {}),
    (429, {"message": "Rate limited"}, {}), (500, {"message": "Unavailable"}, {}),
    (302, {}, {"location": "https://other.example"}),
    (200, {"code": "ERR_WRONG_PARAM"}, {}),
    (200, {}, {"content-type": "text/html"}),
])
async def test_invofox_errors_never_become_data(transport, status, body, headers):
    transport[1].append((status, body, headers))
    with pytest.raises(ValueError):
        await node({"operation": "list_companies"}).execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_error_redacts_key(transport):
    transport[1].append((401, {"message": AUTH["api_key"]}, {}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_companies"}).execute({})
    assert AUTH["api_key"] not in str(error.value)


@pytest.mark.asyncio
async def test_file_processing_failure_is_preserved(transport):
    body = {"id": ID, "status": "rejected", "error": "ERR_UNSUPPORTED_FORMAT"}
    transport[1].append((200, body, {}))
    assert await node({"operation": "get_file", "file_id": ID}).execute({}) == {"file": body}


@pytest.mark.parametrize("config", [
    {"operation": "get_document", "document_id": "../companies"},
    {"operation": "update_document", "document_id": ID},
    {"operation": "update_document", "document_id": ID, "data": {"total": {"wrong": "10"}}},
    {"operation": "list_imports", "skip": 11},
    {"operation": "list_imports", "limit": 16},
    {"operation": "change_document_state", "document_id": ID, "public_state": "processing"},
    {"operation": "upload_single_by_url", "url": "http://example.com/invoice.pdf"},
    {"operation": "upload_files_by_url", "files": []},
    {"operation": "upload_files_by_url", "files": [{"url": "https://example.com/a.pdf", "info": {"company": ID}}]},
])
def test_invalid_inputs_fail_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_all_operations_have_a_wire_regression():
    assert {c[0]["operation"] for c in CASES} == set(api.ROUTES)


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_invofox_published_response_examples(transport, config, method, path, body):
    from pathlib import Path
    responses = json.loads((Path(__file__).parent / "fixtures/invofox/responses.json").read_text())
    template = api.ROUTES[config["operation"]][1]
    for field, wire in {"document_id": "id", "company_id": "id", "provider_id": "providerId",
                        "client_id": "clientId", "file_id": "fileId", "import_id": "importId"}.items():
        template = template.replace("{" + field + "}", "{" + wire + "}")
    example = responses[method + " " + template]
    assert example["source"].startswith("https://developers.invofox.com/")
    transport[1].append((201 if config["operation"] in {"create_client", "create_provider", "upload_files_by_url", "upload_single_by_url"} else 200, example["body"], {}))
    expected = {"file": example["body"]} if config["operation"] == "get_file" else example["body"]
    assert await node(config).execute({}) == expected
