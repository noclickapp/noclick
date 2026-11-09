"""Wayfront request mapping, manual credential shape, paging and failure handling."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import wayfront_node as wf
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "wayfront_api_token", "workspace_url": "https://example.wayfront.com", "api_token": "fixture-token-123456"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "example.wayfront.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, content=b"" if code == 204 else json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(wf, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-wayfront", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id="00000000-0000-4000-8000-000000000001")


CASES = [
    ("list_clients", {}, "GET", "/clients", None),
    ("get_client", {"client_id": 1}, "GET", "/clients/1", None),
    ("create_client", {"email": "user@example.org", "name_f": "John"}, "POST", "/clients", {"email": "user@example.org", "name_f": "John"}),
    ("update_client", {"client_id": 1, "optin": False}, "PUT", "/clients/1", {"optin": False}),
    ("list_companies", {}, "GET", "/companies", None),
    ("get_company", {"company_id": 1}, "GET", "/companies/1", None),
    ("create_company", {"name": "Acme Inc."}, "POST", "/companies", {"name": "Acme Inc."}),
    ("update_company", {"company_id": 1, "name": "Acme Inc."}, "PUT", "/companies/1", {"name": "Acme Inc."}),
    ("list_orders", {}, "GET", "/orders", None),
    ("get_order", {"order_id": "E4A269FC"}, "GET", "/orders/E4A269FC", None),
    ("create_order", {"user_id": 1, "service_id": 2}, "POST", "/orders", {"user_id": 1, "service_id": 2}),
    ("update_order", {"order_id": "E4A269FC", "status": 2}, "PUT", "/orders/E4A269FC", {"status": 2}),
    ("list_order_tasks", {"order_id": "E4A269FC"}, "GET", "/order_tasks/E4A269FC", None),
    ("create_order_task", {"order_id": "E4A269FC", "name": "Design Logo", "deadline": 7}, "POST", "/order_tasks/E4A269FC", {"name": "Design Logo", "deadline": 7}),
    ("update_task", {"task_id": 1, "name": "Design Logo", "employee_ids": [2, 7]}, "PUT", "/order_tasks/1", {"name": "Design Logo", "employee_ids": [2, 7]}),
    ("delete_task", {"task_id": 1}, "DELETE", "/order_tasks/1", None),
    ("list_order_messages", {"order_id": "E4A269FC"}, "GET", "/order_messages/E4A269FC", None),
    ("create_order_message", {"order_id": "E4A269FC", "message": "Hello world!"}, "POST", "/order_messages/E4A269FC", {"message": "Hello world!", "staff_only": False}),
    ("list_services", {}, "GET", "/services", None),
    ("get_service", {"service_id": 1}, "GET", "/services/1", None),
    ("list_invoices", {}, "GET", "/invoices", None),
    ("get_invoice", {"invoice_id": "INV123"}, "GET", "/invoices/INV123", None),
    ("list_subscriptions", {}, "GET", "/subscriptions", None),
    ("get_subscription", {"subscription_id": 1}, "GET", "/subscriptions/1", None),
    ("list_team", {}, "GET", "/team", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", CASES)
async def test_wayfront_operations(transport, operation, arguments, method, path, body):
    requests, replies = transport
    payload = {"data": [{"id": 1}], "meta": {"current_page": 1, "last_page": 3}} if operation.startswith("list_") else {"id": 1}
    replies.append((204 if operation == "delete_task" else 200, payload))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/api" + path
    assert (json.loads(req.content) if req.content else None) == body
    if operation.startswith("list_"):
        assert result["next_page"] == 2
        assert dict(req.url.params) == ({"page": "1", "limit": "20"} if operation not in {"list_order_tasks", "list_order_messages"} else {})


@pytest.mark.asyncio
async def test_wayfront_pagination(transport):
    requests, replies = transport
    replies.append((200, {"data": [], "meta": {"current_page": 3, "last_page": 3}}))
    out = await run("list_clients", {"page": 3, "limit": 10, "sort": "id:desc"})
    assert out["next_page"] is None
    assert dict(requests[0].url.params) == {"page": "3", "limit": "10", "sort": "id:desc"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_wayfront_provider_rejections(transport, status):
    requests, replies = transport
    replies.append((status, {"message": "Provider rejection " + AUTH["api_token"]}))
    out = await run("list_clients")
    assert out["status"] == "error" and out["http_status"] == status
    assert AUTH["api_token"] not in str(out)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_wayfront_malformed_list_is_not_connection_proof(transport):
    _, replies = transport
    replies.append((200, {"message": "Unexpected response"}))
    with pytest.raises(ValueError, match="invalid list envelope"):
        await run("list_clients")


@pytest.mark.parametrize("host", ["https://evil.test", "https://example.wayfront.com.evil.test", "https://user@example.wayfront.com", "http://example.wayfront.com", "https://example.wayfront.com/api", "https://example.wayfront.com:443", "https://127.0.0.1"])
def test_wayfront_refuses_unsafe_workspace(host):
    with pytest.raises(ValueError):
        wf.WayfrontTokenCredential.model_validate({**AUTH, "workspace_url": host})


def test_wayfront_manual_credentials_default_and_canonicalize():
    c = wf.WayfrontTokenCredential(workspace_url=" example.wayfront.com ", api_token=" fixture-token-123456 ")
    assert c.model_dump() == AUTH


def test_wayfront_order_path_and_deadline_validation():
    with pytest.raises(ValidationError):
        wf.WayfrontGetOrder(order_id="../clients")
    with pytest.raises(ValidationError):
        wf.WayfrontCreateOrderTask(order_id="E4A269FC", name="Task", deadline=7, due_at="2024-12-31T23:59:59+00:00")

    for due in ["2024-12-31", "2024-12-31T23:59:59"]:
        with pytest.raises(ValidationError):
            wf.WayfrontCreateOrderTask(order_id="E4A269FC", name="Task", due_at=due)
    assert wf.WayfrontCreateOrderTask(order_id="E4A269FC", name="Task", due_at="2024-12-31T23:59:59+00:00").due_at == "2024-12-31T23:59:59+00:00"
