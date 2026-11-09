"""HelloAsso HTTP contract regressions using synthetic responses and tokens.

Exercise the real factory and request path without signing into HelloAsso.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import helloasso_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-helloasso-access-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="helloasso-test", node_type="automation-helloasso",
        node_data={"config": config, "credentials": {"access_token": TOKEN, **credential}})


def transport(monkeypatch, *, body=None, status=200, content=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, content=content) if content is not None else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_helloasso_connection_reads_account_organizations(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/helloasso/organizations.json").read_text())
    requests = transport(monkeypatch, body=body)
    result = await node({"operation": "list_my_organizations"}).execute({})
    assert result == {"status": "success", "operation": "list_my_organizations", "data": body}
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://api.helloasso.com/v5/users/me/organizations"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    assert native.HelloAssoNode.connection_evidence.operation == "list_my_organizations"


# Independent expectations for the provider's published endpoint shapes.
READS = [
    ("get_organization", {"organization_slug": "our-association"}, "/organizations/our-association"),
    ("list_forms", {"organization_slug": "our-association"}, "/organizations/our-association/forms"),
    ("list_form_types", {"organization_slug": "our-association"}, "/organizations/our-association/formTypes"),
    ("get_form", {}, "/organizations/our-association/forms/Event/gala/public"),
    ("get_form_stats", {}, "/organizations/our-association/forms/Event/gala/stats"),
    ("list_organization_orders", {"organization_slug": "our-association"}, "/organizations/our-association/orders"),
    ("list_form_orders", {}, "/organizations/our-association/forms/Event/gala/orders"),
    ("get_order", {"order_id": 52}, "/orders/52"),
    ("list_organization_payments", {"organization_slug": "our-association"}, "/organizations/our-association/payments"),
    ("list_form_payments", {}, "/organizations/our-association/forms/Event/gala/payments"),
    ("get_payment", {"payment_id": 53}, "/payments/53"),
    ("list_organization_items", {"organization_slug": "our-association"}, "/organizations/our-association/items"),
    ("list_form_items", {}, "/organizations/our-association/forms/Event/gala/items"),
    ("get_item", {"item_id": 54}, "/items/54"),
    ("get_checkout_intent", {"organization_slug": "our-association", "checkout_intent_id": 55}, "/organizations/our-association/checkout-intents/55"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,path", READS)
async def test_helloasso_read_routes_and_unmodified_provider_pagination(monkeypatch, operation, config, path):
    body = {"data": [{"id": 52}], "pagination": {"continuationToken": "next+page/2", "totalCount": 72}}
    requests = transport(monkeypatch, body=body)
    config = config or {"organization_slug": "our-association", "form_type": "Event", "form_slug": "gala"}
    result = await node({"operation": operation, **config}).execute({})
    assert result["data"] == body
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/v5" + path


@pytest.mark.asyncio
async def test_helloasso_query_arrays_booleans_dates_and_continuation(monkeypatch):
    requests = transport(monkeypatch, body={"data": []})
    await node({"operation": "list_organization_orders", "organization_slug": "association",
        "form_types": ["Event", "Membership"], "with_details": True, "page_size": 25,
        "continuation_token": "opaque + / =", "from_date": "2026-10-01T00:00:00Z",
        "to_date": "2026-11-01T00:00:00Z", "user_search_key": "Élodie + Martin"}).execute({})
    query = requests[0].url.params
    assert query.get_list("formTypes") == ["Event", "Membership"]
    assert query["withDetails"] == "true" and query["pageSize"] == "25"
    assert query["continuationToken"] == "opaque + / ="
    assert query["from"] == "2026-10-01T00:00:00Z"
    assert query["userSearchKey"] == "Élodie + Martin"


@pytest.mark.asyncio
async def test_helloasso_checkout_required_body_and_cent_amounts(monkeypatch):
    body = {"totalAmount": 2500, "initialAmount": 2500, "itemName": "Gala ticket",
        "backUrl": "https://association.example/back", "errorUrl": "https://association.example/error",
        "returnUrl": "https://association.example/success", "containsDonation": False}
    requests = transport(monkeypatch, body={"id": 31, "redirectUrl": "https://www.helloasso.com/checkout/31"})
    result = await node({"operation": "create_checkout_intent", "organization_slug": "association", "body": body}).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/v5/organizations/association/checkout-intents"
    assert json.loads(requests[0].content) == body
    assert result["data"]["id"] == 31
    with pytest.raises(ValidationError):
        native.CheckoutBody.model_validate({**body, "totalAmount": 3000})


@pytest.mark.asyncio
async def test_helloasso_event_creation_and_state_changes(monkeypatch):
    requests = transport(monkeypatch, body={"formSlug": "gala"})
    await node({"operation": "create_event", "organization_slug": "association",
        "body": {"title": "Gala", "tierList": [{"label": "Entry", "price": 2500}]}}).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/v5/organizations/association/forms/Event/action/quick-create"
    body = json.loads(requests[0].content)
    assert body["title"] == "Gala" and body["tierList"][0]["price"] == 2500
    requests = transport(monkeypatch, content=b"")
    result = await node({"operation": "update_form_state", "organization_slug": "association",
        "form_type": "Event", "form_slug": "gala", "body": {"state": "Public"}}).execute({})
    assert requests[0].method == "PUT"
    assert json.loads(requests[0].content) == {"state": "Public"}
    assert result["status"] == "success" and result["data"] is None


@pytest.mark.asyncio
async def test_helloasso_cancel_and_refund_use_no_body_and_documented_query_headers(monkeypatch):
    requests = transport(monkeypatch, content=b"")
    assert (await node({"operation": "cancel_order", "order_id": 52}).execute({}))["status"] == "success"
    assert requests[0].method == "POST" and requests[0].url.path == "/v5/orders/52/cancel"
    assert requests[0].content == b""
    requests = transport(monkeypatch, body={"id": 1})
    await node({"operation": "refund_payment", "payment_id": 53, "amount": 1200, "comment": "Partial refund",
        "send_refund_mail": False, "cancel_order": False,
        "x_mfa_access_authorization": "synthetic-mfa-token"}).execute({})
    request = requests[0]
    assert request.method == "POST" and request.url.path == "/v5/payments/53/refund"
    assert dict(request.url.params) == {"amount": "1200", "comment": "Partial refund", "cancelOrder": "false", "sendRefundMail": "false"}
    assert request.headers["x-mfa-access-authorization"] == "synthetic-mfa-token" and request.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 409, 429, 500])
async def test_helloasso_failure_preserves_provider_verdict_and_never_retries(monkeypatch, status):
    requests = transport(monkeypatch, status=status, content=b"Access token expired")
    result = await node({"operation": "list_my_organizations"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Access token expired" and len(requests) == 1


@pytest.mark.parametrize("slug", ["../other", ".", "a/b", "a?b", "https://evil.example"])
def test_helloasso_path_injection_is_rejected(slug):
    with pytest.raises(ValidationError):
        native.HelloAssoGetOrganizationConfig(organization_slug=slug)


def test_helloasso_credential_default_and_bearer_prefix_validation():
    assert native.HelloAssoAccessToken(access_token=TOKEN).credential_type == "helloasso_access_token"
    with pytest.raises(ValidationError):
        native.HelloAssoAccessToken(access_token="Bearer " + TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"not json", b"{}"] )
async def test_helloasso_malformed_identity_response_is_never_success(monkeypatch, content):
    transport(monkeypatch, content=content)
    with pytest.raises(ValueError):
        await node({"operation": "list_my_organizations"}).execute({})
