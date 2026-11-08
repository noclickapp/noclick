"""Factory-level Goody requests and published response examples; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import goody_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "goody"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
REQUESTS = json.loads((FIXTURES / "requests.json").read_text())
TOKEN = "goody-synthetic-key-42"
ID = "40689dd7-8cbe-4a4c-82f7-dcbae14cc9c0"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential_type="goody_api_key"):
    return NodeFactory.create_node(
        node_id="goody-test",
        node_type="automation-goody",
        node_data={
            "config": config,
            "credentials": {"credential_type": credential_type, "api_key": TOKEN},
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,path",
    [
        ("list_brands", "/v1/brands"),
        ("list_cards", "/v1/cards"),
        ("list_collections", "/v1/collections"),
        ("get_collection", "/v1/collections/" + ID),
        ("list_gift_templates", "/v1/gift_templates"),
        ("get_gift_template", "/v1/gift_templates/" + ID),
        ("list_gifts_of_choice", "/v1/gifts_of_choice"),
        ("get_current_user", "/v1/me"),
        ("list_order_activities", "/v1/order_activities"),
        ("list_order_batches", "/v1/order_batches"),
        ("list_order_batch_orders", "/v1/order_batches/" + ID + "/orders"),
        ("list_order_batch_recipients", "/v1/order_batches/" + ID + "/recipients"),
        ("get_order_batch", "/v1/order_batches/" + ID),
        ("list_orders", "/v1/orders"),
        ("get_order", "/v1/orders/" + ID),
        ("list_payment_methods", "/v1/payment_methods"),
        ("list_products", "/v1/products"),
        ("get_product", "/v1/products/" + ID),
        ("list_workspaces", "/v1/workspaces"),
    ],
)
async def test_goody_read_routes_and_published_envelopes(monkeypatch, action, path):
    body = RESPONSES.get(
        action,
        {"email": "person@example.com"}
        if action == "get_current_user"
        else {"data": [], "list_meta": {"total_count": 0}},
    )
    calls = transport(monkeypatch, body)
    config = {"operation": action}
    if ID in path:
        config["id"] = ID
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1 and calls[0].method == "GET"
    assert str(calls[0].url).startswith("https://api.ongoody.com/")
    assert calls[0].url.path == path
    assert calls[0].headers["Authorization"] == "Bearer " + TOKEN
    assert result["data"] == body["data"] if "data" in body else result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,path,status",
    [
        ("create_order_batch", "/v1/order_batches", 201),
        ("calculate_order_batch_price", "/v1/order_batches/price", 200),
        ("cancel_order", "/v1/orders/" + ID + "/cancel", 200),
        ("update_order_expiration", "/v1/orders/" + ID + "/update_expiration", 200),
    ],
)
async def test_goody_writes_use_typed_documented_json_once(
    monkeypatch, action, path, status
):
    config = REQUESTS.get(action, {"operation": action, "id": ID})
    if action == "update_order_expiration":
        config["expiration"] = "2026-12-01T00:00:00Z"
    calls = transport(monkeypatch, RESPONSES[action], status)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["write_outcome"] == "acknowledged"
    assert len(calls) == 1 and calls[0].method == "POST" and calls[0].url.path == path
    if action in REQUESTS:
        body = json.loads(calls[0].content)
        assert body == {
            k: v for k, v in config.items() if k != "operation" and v is not None
        }
    elif action == "update_order_expiration":
        assert json.loads(calls[0].content) == {"expiration": "2026-12-01T00:00:00Z"}
    else:
        assert calls[0].content == b""


@pytest.mark.asyncio
async def test_goody_pagination_and_filters(monkeypatch):
    calls = transport(
        monkeypatch, {"data": [{"id": ID}], "list_meta": {"total_count": 3}}
    )
    result = await node(
        {
            "operation": "list_orders",
            "page": 2,
            "per_page": 1,
            "created_at[after]": "2026-01-01T00:00:00Z",
        }
    ).execute({})
    assert result["next_page"] == 3
    assert calls[0].url.params["created_at[after]"] == "2026-01-01T00:00:00Z"
    assert calls[0].url.params["page"] == "2"


@pytest.mark.asyncio
async def test_goody_rejection_preserves_provider_words_and_redacts_key(monkeypatch):
    transport(monkeypatch, {"error": "Unauthorized " + TOKEN}, 401)
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert result["message"] == "Unauthorized [redacted]"


@pytest.mark.asyncio
async def test_goody_error_envelope_and_malformed_list_are_not_success(monkeypatch):
    transport(monkeypatch, {"error": "Not allowed"})
    assert (await node({"operation": "list_workspaces"}).execute({}))[
        "status"
    ] == "error"
    transport(monkeypatch, {"data": {}, "list_meta": {}})
    with pytest.raises(ValueError, match="list envelope"):
        await node({"operation": "list_workspaces"}).execute({})


@pytest.mark.parametrize(
    "key", ["https://example.com/key", "<token>", "Bearer secret", "key\nheader"]
)
def test_goody_invalid_secrets(key):
    with pytest.raises(ValidationError):
        native.GoodyAPIKeyCredential(api_key=key)


def test_goody_rejects_foreign_credentials_and_route_injection():
    with pytest.raises(ValueError):
        node({"operation": "list_workspaces"}, credential_type="other_api_key")
    with pytest.raises(ValueError):
        node({"operation": "get_order", "id": "../me"})
    assert len(native.ROUTES) == 23
    assert len(set((method, path) for method, path, _ in native.ROUTES.values())) == 23
