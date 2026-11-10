"""Verify Reloadify requests and stateful polls without a live provider account.

Fixtures have synthetic values shaped by the pinned schemas. The separate
conformance harness independently validates all operations against that contract.
"""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import reloadify_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "reloadify_access_token", "access_token": "synthetic-reloadify-token"}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/reloadify/resources.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="reloadify-test", node_type="automation-reloadify",
        node_data={"config": config, "credentials": AUTH})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


READS = [
    ({"operation": "list_languages"}, "/languages", True),
    ({"operation": "get_language", "language_id": "en"}, "/languages/en", False),
    ({"operation": "list_profiles", "language_id": "en"}, "/languages/en/profiles", True),
    ({"operation": "get_profile", "language_id": "en", "profile_id": "p1"}, "/languages/en/profiles/p1", False),
    ({"operation": "list_products", "language_id": "en"}, "/languages/en/products", True),
    ({"operation": "get_product", "language_id": "en", "product_id": "p1"}, "/languages/en/products/p1", False),
    ({"operation": "list_orders", "language_id": "en"}, "/languages/en/orders", True),
    ({"operation": "get_order", "language_id": "en", "order_id": "o1"}, "/languages/en/orders/o1", False),
    ({"operation": "list_shopping_carts", "language_id": "en"}, "/languages/en/shopping_carts", True),
    ({"operation": "get_shopping_cart", "language_id": "en", "shopping_cart_id": "c1"}, "/languages/en/shopping_carts/c1", False),
    ({"operation": "list_categories", "language_id": "en"}, "/languages/en/categories", True),
    ({"operation": "list_segments"}, "/segments", True),
    ({"operation": "list_global_unsubscribes", "language_id": "en"}, "/languages/en/global_unsubscribes", True),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,is_list", READS)
async def test_reads(monkeypatch, config, path, is_list):
    row = {"profile_id": "p1", "profile_email": "customer@example.com"} if config["operation"] == "list_global_unsubscribes" else {"id": "r1", "name": "My shop"}
    requests = transport(monkeypatch, row)
    result = await node(config).execute({"unrelated": "must not be echoed"})
    assert result == ({"items": [row], "page": 1, "per_page": 100} if is_list else {"data": row})
    request, = requests
    assert request.method == "GET" and request.url.host == "app.reloadify.com"
    assert request.url.path == "/api/v2" + path
    assert dict(request.url.params) == ({"page": "1", "per_page": "100"} if is_list else {})
    assert request.content == b"" and request.headers["Authorization"] == "Bearer " + AUTH["access_token"]


WRITES = [
    ("upsert_profile", "PUT", "profiles", {"profile": {"id": "p1", "email": "person@example.com", "tags": ["vip"], "subscribed_to_newsletter": False}}),
    ("upsert_product", "PUT", "products", {"product": {"id": "sku1", "name": "Shirt", "price": 12.5, "visible": False}}),
    ("upsert_order", "PUT", "orders", {"order": {"id": "o1", "profile_id": "p1", "ordered_at": "2026-10-01T12:30:00Z", "paid": True}}),
    ("upsert_shopping_cart", "PUT", "shopping_carts", {"shopping_cart": {"id": "c1", "profile_id": "p1", "price": "12.50"}}),
    ("upsert_category", "PUT", "categories", {"category": {"id": "cat1", "name": "Clothes"}}),
    ("upsert_global_unsubscribe", "PUT", "global_unsubscribes", {"global_unsubscribe": {"email": "person@example.com", "unsubscribed": True}}),
    ("send_transactional_email", "POST", "transactional_emails/t1/send", {"profile": {"email": "person@example.com"}, "data": {"order_number": "1001"}}),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,body", WRITES)
async def test_writes(monkeypatch, operation, method, path, body):
    config = {"operation": operation, "language_id": "en", **body}
    if operation == "send_transactional_email": config["transactional_email_id"] = "t1"
    requests = transport(monkeypatch, {"id": "saved"})
    assert await node(config).execute({}) == {"data": {"id": "saved"}}
    request, = requests
    assert request.method == method and request.url.path == "/api/v2/languages/en/" + path
    assert not request.url.query and json.loads(request.content) == body

@pytest.mark.asyncio
@pytest.mark.parametrize("resource,field", [("profiles", "profile_id"), ("shopping_carts", "shopping_cart_id")])
async def test_deletes(monkeypatch, resource, field):
    requests = transport(monkeypatch, None, status=204)
    op = "delete_profile" if resource == "profiles" else "delete_shopping_cart"
    assert await node({"operation": op, "language_id": "en", field: "r1"}).execute({}) == {"data": {"status": "success"}}
    request, = requests
    assert request.method == "DELETE" and request.url.path == f"/api/v2/languages/en/{resource}/r1"
    assert not request.content and not request.url.query

@pytest.mark.asyncio
async def test_query_arrays_and_time_filters(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "list_profiles", "language_id": "en", "emails": ["a@example.com", "b@example.com"],
        "created_after": "2026-10-01T00:00:00Z", "page": 3, "per_page": 5}).execute({})
    query = requests[0].url.params
    assert query.get_list("emails[]") == ["a@example.com", "b@example.com"]
    assert query["created_after"] == "2026-10-01T00:00:00Z" and query["page"] == "3" and query["per_page"] == "5"

@pytest.mark.parametrize("value", ["..", "../en", "en?secret", "x#y", "a%2fb"])
def test_path_injection_is_rejected(value):
    with pytest.raises(ValueError): node({"operation": "list_profiles", "language_id": value})


def test_credential_defaults_and_secret_cleaning():
    cred = native.ReloadifyAccessTokenCredential(access_token="  synthetic-reloadify-token  ")
    assert cred.credential_type == "reloadify_access_token" and cred.access_token == AUTH["access_token"]
    assert AUTH["access_token"] not in repr(cred)
    for value in ["https://example.com/key", "Bearer secret", "secret\nheader"]:
        with pytest.raises(ValidationError): native.ReloadifyAccessTokenCredential(access_token=value)

@pytest.mark.asyncio
async def test_auth_error_redacts_secret_without_retry(monkeypatch):
    requests = transport(monkeypatch, {"error": "invalid_token", "detail": AUTH["access_token"]}, status=401)
    with pytest.raises(ValueError) as error: await node({"operation": "list_languages"}).execute({})
    assert "invalid_token" in str(error.value) and AUTH["access_token"] not in str(error.value)
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_malformed_list_fails(monkeypatch):
    transport(monkeypatch, {"unexpected": []})
    with pytest.raises(ValueError, match="unexpected resource list"): await node({"operation": "list_languages"}).execute({})

POLL_CASES = [("on_new_profile", "Profile"), ("on_new_order", "Order"), ("on_new_or_updated_cart", "ShoppingCart")]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture", POLL_CASES)
async def test_poll_baseline_dedup_and_agent_event(monkeypatch, operation, fixture):
    rows = [deepcopy(FIXTURES[fixture])]
    transport(monkeypatch, rows)
    instance = node({"operation": operation, "language_id": "en"})
    state = {}
    async def update(mutator, **kwargs):
        next_state, result = mutator(deepcopy(state))
        if next_state is not None:
            state.clear(); state.update(next_state)
        return result
    instance._update_node_state = update
    first = await instance.execute({})
    assert not first["items"] and instance.trigger_produced_no_event(first)
    rows.append({**rows[0], "id": "new-item"})
    transport(monkeypatch, rows)
    result = await instance.execute({})
    assert result["items"] == [rows[1]] and instance.trigger_emitted_event(result)
    event = native.ReloadifyNode.resolve_agent_event(result)
    assert "Reloadify" in event["text"] and "new-item" in event["text"] and "language en" in event["text"]
    assert not (await instance.execute({}))["items"]
    if fixture == "ShoppingCart":
        rows[1]["updated_at"] = "2026-10-02T10:00:00Z"
        transport(monkeypatch, rows)
        assert (await instance.execute({}))["items"] == [rows[1]]

@pytest.mark.asyncio
async def test_poll_pages_and_no_silent_truncation(monkeypatch):
    instance = node({"operation": "on_new_order", "language_id": "en", "created_after": "2026-10-01T00:00:00Z"})
    calls = []
    async def request(method, path, **kwargs):
        calls.append(kwargs["params"])
        assert path == "/v2/languages/en/orders" and kwargs["params"]["created_after"] == "2026-10-01T00:00:00Z"
        return [{**FIXTURES["Order"], "id": str(i)} for i in range(250)] if kwargs["params"]["page"] == 1 else [FIXTURES["Order"]]
    async def unseen(items, key): return items
    instance._request = request
    instance._filter_unseen = unseen
    assert len((await instance.execute({}))["items"]) == 251 and [c["page"] for c in calls] == [1, 2]
    async def full(*args, **kwargs): return [{**FIXTURES["Order"], "id": str(i)} for i in range(250)]
    instance._request = full
    with pytest.raises(ValueError, match="5000"): await instance.execute({})


def test_poll_scope_and_schedule_family():
    base = {"operation": "on_new_profile", "language_id": "en"}
    scope = poll_scope(native.ReloadifyNode, base)
    assert scope
    assert scope == poll_scope(native.ReloadifyNode, {**base, "label": "cosmetic", "schedule": {"frequency": "minutes", "interval": 15}})
    assert scope != poll_scope(native.ReloadifyNode, {**base, "language_id": "nl"})
    assert native.ReloadifyNode.resolve_trigger_payload({"cron": True}, base) is None
