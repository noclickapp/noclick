"""Provider examples and native factory requests; no account or network needed."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import fatture_in_cloud_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-fatture-token"
FIXTURES = Path(__file__).parent / "fixtures" / "fatture-in-cloud"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": "fatture_in_cloud_token", "access_token": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="fatture-fixture", node_type="automation-fatture-in-cloud",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, payload=None, status=200, empty=False):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, content=b"" if empty else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("get_user_info", "GET", "/user/info", {}),
    ("list_companies", "GET", "/user/companies", {}),
    ("get_company_info", "GET", "/c/17/company/info", {"company_id": 17}),
]
for noun, resource in [("client", "entities/clients"), ("supplier", "entities/suppliers"), ("product", "products")]:
    for action, method in [("list", "GET"), ("get", "GET"), ("create", "POST"), ("modify", "PUT"), ("delete", "DELETE")]:
        config = {"company_id": 17}
        path = "/c/17/" + resource
        if action in {"get", "modify", "delete"}:
            config[noun + "_id"] = 16
            path += "/16"
        if action in {"create", "modify"}:
            config["data"] = {"name": "Rossi S.r.l."}
        CASES.append((action + "_" + noun + ("s" if action == "list" else ""), method, path, config))
INVOICE = {"type": "invoice", "entity": {"id": 16, "name": "Rossi S.r.l."}, "date": "2021-08-20",
    "items_list": [{"name": "Water bottle", "qty": 2, "net_price": 1.23, "vat": {"id": 3, "value": 22}}],
    "payments_list": [{"due_date": "2021-08-20", "amount": 3.0, "status": "not_paid"}]}
for op, method, path, extra in [
    ("list_issued_documents", "GET", "issued_documents", {"type": "invoice"}),
    ("get_issued_document", "GET", "issued_documents/16", {"document_id": 16}),
    ("create_issued_document", "POST", "issued_documents", {"data": INVOICE}),
    ("modify_issued_document", "PUT", "issued_documents/16", {"document_id": 16, "data": INVOICE}),
    ("list_received_documents", "GET", "received_documents", {"type": "expense"}),
    ("get_received_document", "GET", "received_documents/16", {"document_id": 16}),
]:
    CASES.append((op, method, "/c/17/" + path, {"company_id": 17, **extra}))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config", CASES, ids=["fatture-in-cloud:" + c[0] for c in CASES])
async def test_native_factory_all_24_contract_requests(monkeypatch, operation, method, path, config):
    payload = {"data": {"id": 16, "name": "Rossi S.r.l."}}
    if operation.startswith("list_"):
        payload = {"data": [{"id": 16}], "current_page": 1, "last_page": 2, "total": 26}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **config}).execute({})
    assert result == payload
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path, request.url.host) == (method, path, "api-v2.fattureincloud.it")
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    expected_query = {"page": "1", "per_page": "25"} if operation.startswith("list_") and operation != "list_companies" else {}
    if operation in {"list_issued_documents", "list_received_documents"}:
        expected_query["type"] = config["type"]
    assert dict(request.url.params) == expected_query
    if "data" in config:
        assert json.loads(request.content) == {"data": config["data"]}
    else:
        assert request.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,operation,config", [
    ("CreateClientResponse", "create_client", {"company_id": 17, "data": {"name": "Rossi S.r.l."}}),
    ("CreateProductResponse", "create_product", {"company_id": 17, "data": {"name": "Water bottle", "net_price": 1.23}}),
    ("CreateIssuedDocumentResponse", "create_issued_document", {"company_id": 17, "data": INVOICE}),
])
async def test_provider_authored_write_examples(monkeypatch, filename, operation, config):
    example = json.loads((FIXTURES / (filename + ".json")).read_text())
    transport(monkeypatch, example)
    assert await node({"operation": operation, **config}).execute({}) == example


@pytest.mark.asyncio
async def test_company_evidence_and_recursive_token_redaction(monkeypatch):
    payload = {"data": {"companies": [
        {"id": 17, "name": "My company", "type": "company", "access_token": "provider-returned-secret"},
        {"id": 18, "name": "Accountant", "type": "accountant", "controlled_companies": [
            {"id": 19, "name": "Controlled company", "access_token": "another-secret"}]}]}}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "list_companies"}).execute({})
    assert "secret" not in json.dumps(result) and "access_token" not in json.dumps(result)
    options = await native.FattureInCloudNode.load_field_options("company_id", credential())
    assert options == [{"value": "17", "label": "My company"}, {"value": "19", "label": "Controlled company"}]
    assert all(r.url.path == "/user/companies" for r in requests)
    assert await native.FattureInCloudNode.load_field_options("company_id", credential(), search="controlled") == [options[1]]


@pytest.mark.asyncio
async def test_pagination_filters_are_preserved(monkeypatch):
    payload = {"data": [], "current_page": 2, "last_page": 2, "total": 25}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": "list_clients", "company_id": 17, "page": 2,
        "per_page": 25, "q": "name = 'Rossi S.r.l.'", "sort": "-name"}).execute({})
    assert result == payload
    assert dict(requests[0].url.params) == {"page": "2", "per_page": "25", "q": "name = 'Rossi S.r.l.'", "sort": "-name"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_provider_rejection_is_not_retried_or_secret_leaked(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"message": "Denied " + TOKEN}}, status=status)
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await node({"operation": "create_client", "company_id": 17, "data": {"name": "Rossi"}}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_empty_delete_acknowledgement(monkeypatch):
    transport(monkeypatch, status=200, empty=True)
    result = await node({"operation": "delete_client", "company_id": 17, "client_id": 16}).execute({})
    assert result == {"deletion_acknowledged": True, "http_status": 200}


@pytest.mark.parametrize("config", [
    {"operation": "get_client", "company_id": -1, "client_id": 1},
    {"operation": "get_client", "company_id": 17, "client_id": "../2"},
    {"operation": "list_clients", "company_id": 17, "per_page": 101},
    {"operation": "list_issued_documents", "company_id": 17},
    {"operation": "create_client", "company_id": 17, "data": {"name": "Rossi", "unknown": True}},
    {"operation": "create_product", "company_id": 17, "data": {"name": "Water", "net_price": float("inf")}},
])
def test_invalid_input_rejected_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_hand_connect_default_type_and_secret_validation():
    assert native.FattureInCloudTokenCredential(access_token=TOKEN).credential_type == "fatture_in_cloud_token"
    for value in ["Bearer abc", "https://example.com/key", "a\nb"]:
        with pytest.raises(ValueError):
            native.FattureInCloudTokenCredential(access_token=value)
