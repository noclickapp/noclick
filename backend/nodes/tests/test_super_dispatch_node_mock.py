"""Offline request/response, credential and write-boundary tests."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import nodes.super_dispatch_node as module
from nodes.core.registry import NodeFactory

KEY = "sd-test-secret-abc123"
CREDENTIAL = {"credential_type": "super_dispatch_api_key", "api_key": KEY}
CARRIERS = json.loads((Path(__file__).parent / "fixtures/super-dispatch/carriers.json").read_text())
VEHICLE = {"year": 2020, "make": "Tesla", "model": "Model 3", "vin": "5YJ3E1EA1LF123456"}
ORDER = {"price": 750.0, "pickup": {"venue": {"city": "New York", "state": "NY"}}, "delivery": {"venue": {"city": "Kansas City", "state": "MO"}}, "vehicles": [VEHICLE]}


def make(config, credential=CREDENTIAL):
    return NodeFactory.create_node(node_id="super-dispatch-test", node_type="automation-super-dispatch",
        node_data={"config": config, "credentials": credential})


def transport(monkeypatch, reply):
    calls = []
    async def handle(request):
        calls.append(request)
        return reply(request)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session
    monkeypatch.setattr(module, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(module.ROUTES))
async def test_super_dispatch_exact_single_request(monkeypatch, operation):
    method, path, field = module.ROUTES[operation]
    config = {"operation": operation}
    if field:
        config[field] = 7
    if operation == "assign_driver":
        config["driver_id"] = 8
    if operation == "create_order":
        config["body"] = ORDER
    elif operation == "update_order":
        config["body"] = {"price": 900.0}
    elif operation in {"create_vehicle", "update_vehicle"}:
        config["body"] = VEHICLE
    status = 204 if operation.startswith("delete_") else 201 if operation.startswith("create_") else 200
    payload = {"meta": {"code": status, "request_id": "req_1"}, "data": [{"id": 7}] if operation.startswith("list_") else {"id": 7}}
    calls = transport(monkeypatch, lambda req: httpx.Response(status, json=payload) if status != 204 else httpx.Response(204))
    result = await make(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert str(request.url).split("?")[0] == module.BASE_URL + path.replace("{id}", "7")
    assert request.headers["Authorization"] == "Bearer " + KEY
    if operation in {"list_carriers", "list_orders", "list_drivers", "list_offers"}:
        assert dict(request.url.params) == {"page": "1", "per_page": "20"}
    if "body" in config:
        assert json.loads(request.content) == config["body"]
    elif operation == "assign_driver":
        assert json.loads(request.content) == {"driver_id": 8}
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_super_dispatch_connection_and_pagination(monkeypatch):
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json=CARRIERS))
    result = await make({"operation": "list_carriers", "page": 2, "per_page": 10}).execute({})
    assert result["data"][0]["name"] == "Test Carrier"
    assert result["pagination"] == CARRIERS["pagination"]
    assert dict(calls[0].url.params) == {"page": "2", "per_page": "10"}
    assert len(calls) == 1
    assert module.SuperDispatchNode.connection_evidence.operation == "list_carriers"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_super_dispatch_errors_never_retry_or_echo_token(monkeypatch, status):
    calls = transport(monkeypatch, lambda req: httpx.Response(status, json={"error": "Rejected " + KEY}))
    result = await make({"operation": "get_order", "order_id": 7}).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert KEY not in json.dumps(result)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_super_dispatch_error_envelope(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={"meta": {"code": 403}, "error": "Permission denied"}))
    result = await make({"operation": "list_carriers"}).execute({})
    assert result == {"status": "error", "status_code": 403, "error": "Permission denied"}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"data": "bad"}, {"data": ["bad"]}])
async def test_super_dispatch_malformed_response(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await make({"operation": "list_carriers"}).execute({})


@pytest.mark.parametrize("value", ["https://example.com/key", "Bearer abc", "abc\r\nHeader: bad", "<token>", " "])
def test_super_dispatch_bad_manual_key(value):
    with pytest.raises(ValidationError):
        module.SuperDispatchAPIKeyCredential(api_key=value)


def test_super_dispatch_manual_key_default_and_shaping():
    credential = module.SuperDispatchAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "super_dispatch_api_key"
    assert credential.api_key == KEY


@pytest.mark.parametrize("config", [
    {"operation": "get_order", "order_id": "../orders"},
    {"operation": "get_order", "order_id": -1},
    {"operation": "list_carriers", "per_page": 101},
    {"operation": "list_orders", "status": "made-up"},
    {"operation": "update_order", "order_id": 7, "body": {}},
    {"operation": "update_order", "order_id": 7, "body": {"price": None}},
    {"operation": "create_order", "body": {"price": 5}},
    {"operation": "create_vehicle", "order_id": 7, "body": {"make": "Tesla"}},
])
def test_super_dispatch_rejects_invalid_config(config):
    assert module.SuperDispatchNode.validate_config({"config": config, "credentials": CREDENTIAL})["valid"] is False


def test_super_dispatch_contact_email_format():
    with pytest.raises(ValidationError):
        module.Contact(name="Jane Smith", phone="+1987654321", email="invalid")
