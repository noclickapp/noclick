"""NetLicensing request, credential and response regressions without an account.

The mock transport exercises the real factory and parser with property-list
responses, including error envelopes and the documented empty delete response.
"""
import base64
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import netlicensing_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-netlicensing-key-42"
CREDENTIAL = {"credential_type": "netlicensing_api_key", "api_key": KEY}
PRODUCT = json.loads((Path(__file__).parent / "fixtures/netlicensing/product.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="netlicensing-test", node_type="automation-netlicensing",
        node_data={"config": config, "credentials": CREDENTIAL})


def mock(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# These are the public REST resources and their immutable identifier fields.
RESOURCES = [
    ("product", "product", "Product", "productNumber", {"active": True, "name": "Example", "version": "1"}),
    ("product_module", "productmodule", "ProductModule", "productModuleNumber", {"productNumber": "P001", "active": True, "name": "Module", "licensingModel": "MultiFeature"}),
    ("license_template", "licensetemplate", "LicenseTemplate", "licenseTemplateNumber", {"productModuleNumber": "M001", "name": "Feature", "active": True, "licenseType": "FEATURE"}),
    ("licensee", "licensee", "Licensee", "licenseeNumber", {"productNumber": "P001", "active": True}),
    ("license", "license", "License", "licenseNumber", {"licenseeNumber": "I001", "licenseTemplateNumber": "E001", "active": True}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["list", "get", "create", "update"])
@pytest.mark.parametrize("name,resource,entity,identifier,creating", RESOURCES)
async def test_resource_requests_are_one_exact_form_or_read(monkeypatch, action, name, resource, entity, identifier, creating):
    config = {"operation": action + "_" + name + ("s" if action == "list" else "")}
    if action in {"get", "update"}:
        config[identifier] = "selected+number"
    if action == "create":
        config.update(creating)
    if action == "update":
        config["active"] = False
    body = {"items": {"item": [{"type": entity, "property": [{"name": "number", "value": "selected+number"}]}]}}
    requests = mock(monkeypatch, body)
    output = await node(config).execute({})
    assert output["status"] == "success" and output["items"] == [{"number": "selected+number"}]
    assert len(requests) == 1
    req = requests[0]
    assert req.url.host == "go.netlicensing.io"
    assert req.url.raw_path == ("/core/v2/rest/" + resource + ("/selected%2Bnumber" if action in {"get", "update"} else "")).encode()
    assert req.method == ("GET" if action in {"list", "get"} else "POST")
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(("apiKey:" + KEY).encode()).decode()
    assert req.headers["Accept"] == "application/json"
    if action in {"create", "update"}:
        expected = creating if action == "create" else {"active": False}
        assert parse_qs(req.content.decode()) == {k: [str(v).lower() if isinstance(v, bool) else str(v)] for k, v in expected.items()}
        assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    else:
        assert not req.content and not req.url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("resource,identifier", [("licensee", "licenseeNumber"), ("license", "licenseNumber")])
async def test_documented_delete_204_has_no_body_or_cascade(monkeypatch, resource, identifier):
    requests = mock(monkeypatch, None, 204)
    result = await node({"operation": "delete_" + resource, identifier: "I001"}).execute({})
    assert result["deleted_number"] == "I001" and result["http_status"] == 204
    assert len(requests) == 1 and requests[0].method == "DELETE"
    assert not requests[0].content and not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_transactions", "get_transaction"])
async def test_transaction_reads(monkeypatch, operation):
    requests = mock(monkeypatch, {"items": {"item": [{"type": "Transaction", "property": [{"name": "number", "value": "T001"}]}]}})
    result = await node({"operation": operation, **({"transactionNumber": "T001"} if operation.startswith("get_") else {})}).execute({})
    assert result["items"][0]["number"] == "T001"
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path.endswith("/transaction/T001" if operation.startswith("get_") else "/transaction")


@pytest.mark.asyncio
async def test_validation_preserves_nested_invalid_entitlement(monkeypatch):
    body = {"ttl": "2026-10-30T15:02:36.137Z", "items": {"item": [{"type": "ProductModuleValidation", "property": [{"name": "productModuleNumber", "value": "M011"}], "list": [{"name": "L011", "property": [{"name": "valid", "value": "false"}]}]}]}}
    requests = mock(monkeypatch, body)
    output = await node({"operation": "validate_licensee", "licenseeNumber": "I011", "productModuleNumber": "M001", "action": "checkOut", "sessionId": "abc"}).execute({})
    assert output["response"] == body and "valid" not in output
    assert requests[0].url.path.endswith("/licensee/I011/validate") and requests[0].method == "POST"
    assert parse_qs(requests[0].content.decode()) == {"productModuleNumber": ["M001"], "action": ["checkOut"], "sessionId": ["abc"]}


@pytest.mark.asyncio
async def test_connection_products_and_page_metadata(monkeypatch):
    body = copy.deepcopy(PRODUCT)
    body["items"].update({"pagenumber": "0", "itemsnumber": "1", "totalpages": "2"})
    mock(monkeypatch, body)
    result = await node({"operation": "list_products"}).execute({})
    assert result["items"][0]["name"] == "Product Numero Uno"
    assert result["response"]["items"]["totalpages"] == "2" and result["page_scope"] == "provider default page"
    assert native.NetlicensingNode.connection_evidence.operation == "list_products"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {}, {"items": []}, {"items": {"item": {}}}, {"items": {}, "infos": {"info": [{"type": "ERROR", "id": "rejected"}]}}, {"items": {"item": [{"type": "License", "property": []}]}}])
async def test_malformed_envelopes_never_prove_a_connection(monkeypatch, body):
    mock(monkeypatch, body)
    with pytest.raises(ValueError, match="invalid result"):
        await node({"operation": "list_products"}).execute({})


@pytest.mark.asyncio
async def test_duplicate_properties_and_cross_resource_detail_rejected(monkeypatch):
    body = copy.deepcopy(PRODUCT)
    body["items"]["item"][0]["property"].append({"name": "number", "value": "other"})
    mock(monkeypatch, body)
    with pytest.raises(ValueError, match="invalid result"):
        await node({"operation": "list_products"}).execute({})
    mock(monkeypatch, PRODUCT)
    with pytest.raises(ValueError, match="different resource"):
        await node({"operation": "get_product", "productNumber": "other"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_errors_keep_provider_text_and_redact_key(monkeypatch, status):
    mock(monkeypatch, {"infos": {"info": [{"type": "ERROR", "id": "accessDenied", "value": "Access denied " + KEY}]}}, status)
    result = await node({"operation": "list_products"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Access denied" in result["error"] and KEY not in str(result)


@pytest.mark.asyncio
async def test_transport_errors_do_not_retry_or_expose_credentials(monkeypatch):
    requests = mock(monkeypatch, httpx.ReadTimeout(KEY))
    with pytest.raises(ValueError, match="inspect writes") as exc:
        await node({"operation": "create_licensee", "productNumber": "P001", "active": True}).execute({})
    assert KEY not in str(exc.value) and len(requests) == 1


def test_manual_key_default_and_validation():
    assert native.NetlicensingAPIKeyCredential(api_key="  " + KEY + "  ").credential_type == "netlicensing_api_key"
    assert native.NetlicensingAPIKeyCredential(api_key="  " + KEY + "  ").api_key == KEY
    for value in ["", "https://example.com/key", "<token>", "key with spaces"]:
        with pytest.raises(ValidationError):
            native.NetlicensingAPIKeyCredential(api_key=value)
    for value in ["../other", "one/two", "one?two", "\n"]:
        with pytest.raises(ValidationError):
            native.GetProductConfig(productNumber=value)
    with pytest.raises(ValidationError, match="at least one"):
        native.UpdateLicenseeConfig(licenseeNumber="I001")
