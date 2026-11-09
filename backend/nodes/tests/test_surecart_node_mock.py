"""SureCart route, authentication, body and pagination regressions.

Fixtures are unmodified examples from SureCart's pinned OpenAPI documents;
requests use a local HTTP transport and never connect to an account.
"""
import json
import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import surecart_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential
from nodes.core.connection_evidence import _ProviderRefused, _raise_if_error_envelope, _looks_like_auth_rejection

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/surecart/responses.json").read_text())
KEY = "sc_test_synthetic_secret_42"
ID = "ed41947c-9671-4312-b0ba-01e32c3b0456"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="surecart-test", node_type="automation-surecart",
        node_data={"config": config, "credentials": {"credential_type": "surecart_api_key", "api_key": KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_all_operations_use_one_documented_route(monkeypatch, operation):
    example = EXAMPLES[operation]
    cfg = {"operation": operation}
    for field in re.findall(r"\{([^}]+)\}", native.ROUTES[operation][1]):
        cfg[field] = ID
    cfg.update({
        "create_customer": {"email": "person@example.com"},
        "create_product": {"name": "Membership"},
        "create_coupon": {"name": "Summer", "percent_off": 20},
        "create_purchase": {"customer_id": ID, "price_id": ID},
    }.get(operation, {}))
    requests = transport(monkeypatch, example["body"])
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["method"]
    assert request.url.path == example["path"].replace("{id}", ID)
    assert request.url.host == "api.surecart.com"
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert KEY not in str(result)
    if operation.startswith("list_"):
        assert result["items"] == example["body"]["data"]
        assert result["pagination"] == example["body"]["pagination"]
        assert dict(request.url.params) == {"page": "1", "limit": "20"}
    else:
        assert result["item"] == example["body"]


@pytest.mark.asyncio
async def test_customer_changes_preserve_false_and_omit_absent_fields(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["update_customer"]["body"])
    await node({"operation": "update_customer", "customer_id": ID, "unsubscribed": False, "name": "Ada"}).execute({})
    assert json.loads(requests[0].content) == {"customer": {"unsubscribed": False, "name": "Ada"}}


@pytest.mark.asyncio
async def test_grant_purchase_uses_documented_customer_and_price_fields(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["create_purchase"]["body"])
    await node({"operation": "create_purchase", "customer_id": ID, "price_id": ID, "quantity": 2}).execute({})
    assert json.loads(requests[0].content) == {"purchase": {"customer": ID, "price": ID, "quantity": 2}}
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_pause_uses_query_behavior_and_integer_body(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["cancel_subscription"]["body"])
    await node({"operation": "cancel_subscription", "subscription_id": ID,
        "cancel_behavior": "pending", "restore_at": 1800000000}).execute({})
    assert dict(requests[0].url.params) == {"cancel_behavior": "pending"}
    assert json.loads(requests[0].content) == {"subscription": {"restore_at": 1800000000}}


@pytest.mark.asyncio
async def test_list_keeps_explicit_page_filters_and_empty_result(monkeypatch):
    body = {"object": "list", "data": [], "pagination": {"page": 3, "limit": 10, "count": 0}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_orders", "page": 3, "limit": 10, "customer_id": ID, "live_mode": False}).execute({})
    assert dict(requests[0].url.params) == {"page": "3", "limit": "10", "customer_ids[]": ID, "live_mode": "false"}
    assert result["items"] == [] and result["pagination"] == body["pagination"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_errors_remain_errors_and_redact_key(monkeypatch, status):
    transport(monkeypatch, {"message": "Denied " + KEY}, status)
    result = await node({"operation": "list_products"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert "Denied" in result["error"] and KEY not in str(result)
    with pytest.raises(_ProviderRefused) as rejected:
        _raise_if_error_envelope(result)
    assert f"HTTP {status}" in str(rejected.value)
    if status in {401, 403}:
        assert _looks_like_auth_rejection(str(rejected.value))


@pytest.mark.asyncio
async def test_empty_rejection_still_blocks_connection(monkeypatch):
    transport(monkeypatch, b"", 401)
    result = await node({"operation": "list_products"}).execute({})
    with pytest.raises(_ProviderRefused) as rejected:
        _raise_if_error_envelope(result)
    assert _looks_like_auth_rejection(str(rejected.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"data": {}}, {"error": "denied"}, {"data": [], "pagination": None}])
async def test_malformed_lists_do_not_prove_connection(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_products"}).execute({})


@pytest.mark.parametrize("bad_id", ["../account", "a/b", "x?y", "https://evil.test"])
def test_resource_ids_cannot_change_routes(bad_id):
    with pytest.raises(ValueError):
        node({"operation": "get_customer", "customer_id": bad_id})


def test_manual_key_default_and_validation():
    shaped, errors, _ = shape_credential("surecart_api_key", {"api_key": KEY})
    assert not errors and shaped["api_key"] == KEY
    assert native.SureCartAPIKeyCredential.model_validate(shaped).credential_type == "surecart_api_key"
    for value in ["Bearer secret", "https://example.com/key", "x\ny"]:
        with pytest.raises(ValueError):
            native.SureCartAPIKeyCredential(api_key=value)
    with pytest.raises(ValidationError):
        native.SureCartCreateCouponConfig(name="Promo", percent_off=20, duration="repeating")
    with pytest.raises(ValidationError):
        native.SureCartListProductsConfig(limit=101)
