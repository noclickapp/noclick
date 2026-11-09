"""Offline route/body, paging, identity and error regressions for shopVOX v1."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import shopvox_node as native
from nodes.core.registry import NodeFactory

CONTRACT = json.loads((Path(__file__).parent / "fixtures/shopvox/contract.json").read_text())
ID = "123e4567-e89b-12d3-a456-426614174000"
TOKEN = "synthetic-shopvox-auth-83"
CREDENTIAL = {"credential_type": "shopvox_api_token", "account_id": ID, "auth_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="shopvox-test", node_type="automation-shopvox",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    calls = []
    def reply(request):
        calls.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


def config(operation):
    out = {"operation": operation}
    if operation.startswith(("get_", "update_")) and operation != "get_connection":
        out[operation.split("_", 1)[1] + "_id"] = ID
    if operation.startswith(("create_", "update_")):
        kind = operation.split("_", 1)[1]
        out["title" if kind in {"sales_order", "sales_lead"} else "name"] = "Example Signs"
        if kind in {"contact", "sales_order"}:
            out["company_id"] = ID
    if operation == "list_jobs":
        out.update(txn_type="sales_order", txn_number=1001)
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", CONTRACT["routes"].items())
async def test_every_operation_sends_one_published_route_and_auth(monkeypatch, operation, route):
    key = {"list_sales_orders": "salesOrders", "list_sales_leads": "salesLeads"}.get(operation, operation.removeprefix("list_"))
    body = CONTRACT["connection"] if operation == "get_connection" else (
        {key: [{"id": ID}], "stats": CONTRACT["stats"]} if operation.startswith("list_") else {"id": ID})
    calls = transport(monkeypatch, body)
    result = await node(config(operation)).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert (request.method, request.url.path) == (route[0], "/v1" + route[1].replace("{id}", ID))
    assert request.url.host == "api.shopvox.com"
    assert request.url.params["account_id"] == ID and request.url.params["authToken"] == TOKEN
    assert request.headers["content-type"] == "application/json"
    assert TOKEN not in str(result)
    if operation.startswith("list_"):
        assert result["next_page"] == 2 and result["pagination"]["perPage"] == 5
    if route[0] != "GET":
        payload = json.loads(request.content)
        wrapper = {"company": "company", "contact": "contact", "sales_order": "sales_order", "job": "job"}.get(operation.split("_", 1)[1])
        values = payload[wrapper] if wrapper else payload
        assert "operation" not in values
        assert not any(k.endswith("_id") and k != "company_id" for k in values)
        assert result["write_acknowledged"]


@pytest.mark.asyncio
async def test_false_filter_dates_and_quote_current_page_preserved(monkeypatch):
    calls = transport(monkeypatch, {"companies": [], "stats": {"nextPage": None}})
    assert (await node({"operation": "list_companies", "active": False, "page": 2}).execute({}))["next_page"] is None
    assert calls[0].url.params["active"] == "false" and calls[0].url.params["page"] == "2"
    calls = transport(monkeypatch, {"salesOrders": [], "stats": {"nextPage": None}})
    await node({"operation": "list_sales_orders", "txn_date_from": "2026-07-03"}).execute({})
    assert calls[0].url.params["txn_date_from"] == "2026-07-03"
    stats = {"currentPage": 3, "perPage": 10, "nextPage": None, "hasNextPage": False}
    transport(monkeypatch, {"quotes": [], "stats": stats})
    assert (await node({"operation": "list_quotes", "page": 3}).execute({}))["pagination"] == stats


@pytest.mark.asyncio
async def test_sales_order_line_items_use_dollars_and_lead_body_is_flat(monkeypatch):
    calls = transport(monkeypatch, {"id": ID})
    cfg = config("create_sales_order")
    cfg["line_items"] = [{"name": "Sign", "quantity": 2, "price_in_dollars": 25.5}]
    await node(cfg).execute({})
    assert json.loads(calls[0].content)["sales_order"]["line_items"] == cfg["line_items"]
    calls = transport(monkeypatch, {"id": ID, "dealValueInDollars": 25.5})
    cfg = config("create_sales_lead")
    cfg["deal_value_in_dollars"] = 25.5
    result = await node(cfg).execute({})
    assert json.loads(calls[0].content) == {"title": "Example Signs", "deal_value_in_dollars": 25.5}
    assert result["data"]["dealValueInDollars"] == 25.5


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_rejection_never_retried_or_exposes_token(monkeypatch, status):
    calls = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node(config("create_company")).execute({})
    assert not result["success"] and result["http_status"] == status
    assert TOKEN not in str(result) and len(calls) == 1
    if status == 500:
        assert "unknown" in result["write_outcome"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"errors": ["bad"]}, [], {"status": "ok"}, {"status": "bad", "name": "Jane"}])
async def test_connection_requires_account_identity_not_just_http200(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "get_connection"}).execute({})
    assert not result["success"]


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_does_not_retry_write(monkeypatch):
    calls = transport(monkeypatch, httpx.ReadTimeout("timeout " + TOKEN))
    result = await node(config("create_company")).execute({})
    assert result["status"] == "unknown" and "unknown" in result["write_outcome"]
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.parametrize("cfg", [
    {"operation": "get_company", "company_id": "../contacts"},
    {"operation": "list_jobs"},
    {"operation": "update_sales_order", "sales_order_id": ID, "company_id": ID, "title": "Test", "line_items": []},
    {"operation": "list_sales_orders", "txn_date_from": "2026-02-30"},
    {"operation": "list_companies", "page": 0},
])
def test_invalid_config_refused_before_network(cfg):
    with pytest.raises((ValidationError, ValueError)):
        native.ShopvoxNode.parse_config({"config": cfg, "credentials": CREDENTIAL})


def test_credential_has_default_type_and_only_manual_fields():
    credential = native.ShopvoxTokenCredential(account_id=ID, auth_token=TOKEN)
    assert credential.credential_type == "shopvox_api_token"
    assert {n for n, f in native.ShopvoxTokenCredential.model_fields.items() if f.is_required()} == {"account_id", "auth_token"}
