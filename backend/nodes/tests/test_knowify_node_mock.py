"""Native Knowify operations with HTTP transport interception."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import knowify_node as module
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {
    "credential_type": "knowify_session_token",
    "session_token": "fixture-knowify-session",
}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.url.host == "developer.knowify.com"
        assert request.headers["Authorization"] == "kauth " + AUTH["session_token"]
        assert AUTH["session_token"] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        module,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(
        node_type="automation-knowify",
        operation=operation,
        arguments=config or {},
        credential_data=AUTH,
        user_id=USER,
    )


CREATE = {
    "client": (
        {"client_name": "Acme Construction LLC", "email": "jane@acme.example"},
        {"ClientName": "Acme Construction LLC", "Email": "jane@acme.example"},
    ),
    "project": (
        {"project_name": "Acme HQ Buildout", "client_id": 42},
        {"ProjectName": "Acme HQ Buildout", "ClientId": 42},
    ),
    "vendor": ({"vendor_name": "ABC Drywall LLC"}, {"VendorName": "ABC Drywall LLC"}),
    "task": (
        {"milestone_id": 5102, "description": "Frame north wall", "priority": False},
        {"MilestoneId": 5102, "Description": "Frame north wall", "Priority": False},
    ),
    "invoice": (
        {"client_id": 42, "total_amount": 12500},
        {"ClientId": 42, "TotalAmount": 12500},
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", module.ROUTES)
async def test_every_operation(transport, operation):
    requests, replies = transport
    method, path, resource = module.ROUTES[operation]
    config, expected_body = {}, None
    if operation.startswith(("get_", "update_")) and operation != "get_company":
        config["record_id"] = 102345
        path = path.format(id=102345)
    if method in {"POST", "PATCH"}:
        values, expected_body = CREATE[resource]
        config.update(values)
    if operation.startswith("list_"):
        payload = {
            "data": [{"Id": 102345}],
            "meta": {"total": 51, "limit": 50, "offset": 0, "has_more": True},
        }
    else:
        payload = {"Id": 102345, **(expected_body or {})}
    replies.append((201 if method == "POST" else 200, payload))
    output = await run(operation, config)
    assert output["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/api/v2" + path
    if expected_body is not None:
        assert json.loads(request.content) == expected_body
    else:
        assert not request.content
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"limit": "50", "offset": "0"}
        assert output["data"] == payload["data"]
        assert output["meta"] == payload["meta"]
        assert output["next_offset"] == 50
    else:
        assert output["data"] == payload


@pytest.mark.asyncio
async def test_empty_final_page(transport):
    requests, replies = transport
    replies.append(
        (
            200,
            {
                "data": [],
                "meta": {"total": 0, "limit": 10, "offset": 20, "has_more": False},
            },
        )
    )
    result = await run("list_projects", {"offset": 20, "limit": 10})
    assert result["next_offset"] is None
    assert dict(requests[0].url.params) == {"limit": "10", "offset": "20"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": [], "meta": {}},
        {"data": ["wrong"], "meta": {"has_more": False}},
        {"didSucceed": False},
    ],
)
async def test_incomplete_list_is_error(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await run("list_projects")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_rejection(transport, status):
    _, replies = transport
    replies.append((status, {"title": "Access refused", "status": status}))
    with pytest.raises(httpx.HTTPStatusError):
        await run("list_projects")


@pytest.mark.parametrize(
    "operation,config",
    [
        ("update_client", {"record_id": 1}),
        ("get_project", {"record_id": -1}),
        ("create_task", {"description": "Missing milestone"}),
        ("create_project", {"project_name": "Missing client"}),
        ("list_projects", {"limit": 201}),
    ],
)
def test_invalid_config(operation, config):
    result = module.KnowifyNode.validate_config(
        {"config": {"operation": operation, **config}, "credentials": AUTH}
    )
    assert not result["valid"]


def test_manual_credential_default():
    assert (
        module.KnowifySessionToken(session_token="fixture-session").credential_type
        == "knowify_session_token"
    )
    with pytest.raises(ValueError):
        module.KnowifySessionToken(session_token="kauth fixture-session")


def test_documented_direct_auth_contract():
    from pathlib import Path

    contract = json.loads(
        (Path(__file__).parent / "fixtures/knowify/contract-auth.json").read_text()
    )
    assert contract["kauth"]["scheme"] == "kauth"
    assert "Authorization: kauth <kauth-token>" in contract["kauth"]["description"]
    assert "Authorization: kauth <token>" in contract["login"]
    assert contract["security_requirement"] == [{"bearer": []}]


@pytest.mark.asyncio
async def test_connection_shows_project_names(transport):
    from nodes.core.connection_evidence import collect_evidence

    _, replies = transport
    replies.append(
        (
            200,
            {
                "data": [{"Id": 102345, "ProjectName": "Acme HQ Buildout"}],
                "meta": {"total": 1, "limit": 50, "offset": 0, "has_more": False},
            },
        )
    )
    result = await collect_evidence(
        node_type="automation-knowify", credential_data=AUTH, user_id=USER
    )
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ["Acme HQ Buildout"]
