"""Paperform request/response regressions against the published v1 envelopes."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes import paperform_node as paperform

TOKEN = "paperform-test-access-token"


def node(config):
    data = {"config": config, "credentials": {"credential_type": "paperform_api_token", "api_token": TOKEN}}
    return paperform.PaperformNode(node_id="paperform-test", node_type="automation-paperform", node_data=data,
                                  config=paperform.PaperformNode.parse_config(data))


@pytest.fixture
def api(monkeypatch):
    calls = []
    reply = {"status": 200, "body": {"status": "ok", "results": {"forms": []}}}

    def handle(request):
        calls.append(request)
        assert request.url.host == "api.paperform.co"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        return httpx.Response(reply["status"], json=reply["body"])

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs) as session:
            yield session

    monkeypatch.setattr(paperform, "guarded_async_client", client)
    return calls, reply


@pytest.mark.asyncio
async def test_form_search_and_pagination_preserve_provider_data(api):
    calls, reply = api
    reply["body"] = {"status": "ok", "results": {"forms": [{"id": "form-1", "title": "Orders", "slug": "orders"}]},
                     "total": 57, "has_more": True, "limit": 20, "skip": 0}
    out = await node({"operation": "list_forms", "search": "Orders", "search_fields": ["title", "slug"],
                      "after_date": "2019-06-11T20:36:29Z"}).execute({})
    request = calls[0]
    assert request.method == "GET" and request.url.path == "/v1/forms"
    assert request.url.params.get_list("search_fields") == ["title", "slug"]
    assert request.url.params["after_date"] == "2019-06-11T20:36:29Z"
    assert out["data"][0]["title"] == "Orders"
    assert out["pagination"] == {"total": 57, "has_more": True, "limit": 20, "skip": 0}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_update_form_sends_only_supplied_fields_including_null_and_false(api):
    calls, reply = api
    reply["body"] = {"status": "ok", "results": {"form": {"title": "Orders", "disabled": False}}}
    await node({"operation": "update_form", "slug_or_id": "orders", "disabled": False, "translation_id": None}).execute({})
    assert calls[0].method == "PUT"
    assert calls[0].url.path == "/v1/forms/orders"
    assert json.loads(calls[0].content) == {"disabled": False, "translation_id": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,key,path", [
    ("list_partial_submissions", "partial-submissions", "/v1/forms/orders/partial-submissions"),
    ("get_partial_submission", "partial-submission", "/v1/partial-submissions/submission-1"),
])
async def test_partial_submission_hyphenated_result_envelopes(api, operation, key, path):
    calls, reply = api
    record = {"id": "submission-1", "data": [{"key": "email", "value": "person@example.com"}]}
    data = [record] if operation.startswith("list_") else record
    reply["body"] = {"status": "ok", "results": {key: data}}
    config = {"operation": operation, **({"slug_or_id": "orders"} if operation.startswith("list_") else {"submission_id": "submission-1"})}
    out = await node(config).execute({})
    assert out["data"] == data
    assert calls[0].url.path == path


@pytest.mark.asyncio
async def test_create_product_required_fields_and_nested_images(api):
    calls, reply = api
    reply["body"] = {"status": "ok", "results": {"product": {"SKU": "PRODUCT-1", "name": "Product 1", "price": 10}}}
    config = {"operation": "create_product", "slug_or_id": "orders", "product_field_key": "a1b2c3d4e5",
              "SKU": "PRODUCT-1", "name": "Product 1", "price": 10,
              "images": [{"url": "https://example.com/image.jpg", "width": 100, "height": None}]}
    out = await node(config).execute({})
    assert calls[0].method == "POST" and calls[0].url.path == "/v1/forms/orders/products"
    expected = {k: v for k, v in config.items() if k not in {"operation", "slug_or_id"}}
    expected["images"] = [{"url": "https://example.com/image.jpg", "width": 100}]
    assert json.loads(calls[0].content) == expected
    assert out["data"]["SKU"] == "PRODUCT-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field", [("update_product_quantity", "quantity"), ("update_product_sold", "sold")])
async def test_counter_updates_use_integer_acknowledgement(api, operation, field):
    calls, reply = api
    reply["body"] = {"ok": 1}
    out = await node({"operation": operation, "slug_or_id": "orders", "product_sku": "SKU-123", field: 0}).execute({})
    assert calls[0].method == "PUT" and calls[0].url.path == "/v1/forms/orders/products/SKU-123/" + field
    assert json.loads(calls[0].content) == {field: 0}
    assert out["update_acknowledged"] is True


@pytest.mark.asyncio
async def test_coupon_percent_and_expiry_clear_preserve_wire_names(api):
    calls, reply = api
    reply["body"] = {"status": "ok", "results": {"coupon": {"code": "DISCOUNT1", "discountPercentage": 10}}}
    await node({"operation": "update_coupon", "slug_or_id": "orders", "code": "DISCOUNT1",
                "discountPercentage": 10, "expiresAt": None, "enabled": False}).execute({})
    assert json.loads(calls[0].content) == {"discountPercentage": 10, "expiresAt": None, "enabled": False}


@pytest.mark.asyncio
async def test_webhook_creation_sends_explicit_triggers(api):
    calls, reply = api
    reply["body"] = {"status": "ok", "results": {"webhook": {"target_url": "https://example.com/webhook", "triggers": ["submission"]}}}
    await node({"operation": "create_webhook", "slug_or_id": "orders", "target_url": "https://example.com/webhook", "triggers": ["submission"]}).execute({})
    assert calls[0].method == "POST" and calls[0].url.path == "/v1/forms/orders/webhooks"
    assert json.loads(calls[0].content) == {"target_url": "https://example.com/webhook", "triggers": ["submission"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path", [
    ({"operation": "delete_submission", "submission_id": "submission-1"}, "/v1/submissions/submission-1"),
    ({"operation": "delete_product", "slug_or_id": "orders", "product_sku": "SKU-123"}, "/v1/forms/orders/products/SKU-123"),
    ({"operation": "delete_coupon", "slug_or_id": "orders", "code": "DISCOUNT1"}, "/v1/forms/orders/coupons/DISCOUNT1"),
    ({"operation": "delete_webhook", "webhook_id": "webhook-1"}, "/v1/webhooks/webhook-1"),
])
async def test_delete_requires_provider_acknowledgement(api, config, path):
    calls, reply = api
    reply["body"] = {"status": "ok"}
    out = await node(config).execute({})
    assert calls[0].method == "DELETE" and calls[0].url.path == path and not calls[0].content
    assert out["deletion_acknowledged"] is True
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"status": "error", "message": "Invalid token"}), (429, {"status": "error", "message": "Too many requests"}), (200, {"status": "error", "message": "Rejected"})])
async def test_errors_keep_provider_message_without_retry(api, status, body):
    calls, reply = api
    reply.update(status=status, body=body)
    out = await node({"operation": "list_forms"}).execute({})
    assert out["status"] == "error" and out["error"] == body["message"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_error_redacts_echoed_token(api):
    _, reply = api
    reply.update(status=401, body={"message": "Rejected " + TOKEN})
    out = await node({"operation": "list_forms"}).execute({})
    assert TOKEN not in json.dumps(out)
    assert "[redacted]" in out["error"]


@pytest.mark.asyncio
async def test_invalid_success_envelope_fails(api):
    _, reply = api
    reply["body"] = {"status": "ok", "results": {"forms": "not a list"}}
    with pytest.raises(ValueError, match="documented forms"):
        await node({"operation": "list_forms"}).execute({})


@pytest.mark.parametrize("identifier", [".", "..", "\norders", ""])
def test_invalid_path_component_rejected(identifier):
    with pytest.raises(ValueError):
        node({"operation": "get_form", "slug_or_id": identifier})


def test_evidence_read_requires_only_credentials():
    assert paperform.PaperformNode.connection_evidence.operation == "list_forms"
    assert node({"operation": "list_forms"}).config.config.limit == 20


@pytest.mark.asyncio
async def test_empty_update_rejected_before_network(api):
    calls, _ = api
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_form", "slug_or_id": "orders"}).execute({})
    assert calls == []


@pytest.mark.asyncio
async def test_single_product_endpoint_uses_plural_products_result(api):
    calls, reply = api
    products = [{"SKU": "SKU-123", "name": "Product 1", "price": 10}]
    reply["body"] = {"status": "ok", "results": {"products": products}}
    out = await node({"operation": "get_product", "slug_or_id": "orders", "product_sku": "SKU-123"}).execute({})
    assert calls[0].url.path == "/v1/forms/orders/products/SKU-123"
    assert out["data"] == products


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,key,collection", [
    ("get_submission", "submission", "submissions"),
    ("delete_submission", None, "submissions"),
    ("get_partial_submission", "partial-submission", "partial-submissions"),
])
async def test_documented_non_uuid_submission_identifiers_preserved(api, operation, key, collection):
    from pathlib import Path
    example = json.loads((Path(__file__).parent / "fixtures/paperform/documented_submission_id.json").read_text())
    identifier = example["id"]
    calls, reply = api
    reply["body"] = {"status": "ok", **({"results": {key: {"id": identifier}}} if key else {})}
    out = await node({"operation": operation, "submission_id": identifier}).execute({})
    assert calls[0].url.path == "/v1/" + collection + "/" + identifier
    assert out["status"] == "success"
