"""Transport-level tests of Fireberry's published CRM record endpoints."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import fireberry_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import validate_for_connect

ID = "d8fe29c2-0523-4e8b-91bb-d8ae4f41139d"
TOKEN = "synthetic-fireberry-test-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="fireberry-test",
        node_type="automation-fireberry",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "fireberry_api_token",
                "api_token": TOKEN,
            },
        },
    )


@pytest.fixture
def wire(monkeypatch):
    state = {
        "requests": [],
        "code": 200,
        "body": {"success": True, "data": {"Record": {"accountid": ID}}, "message": ""},
    }

    def send(request):
        state["requests"].append(request)
        return httpx.Response(state["code"], json=state["body"])

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource,required",
    [
        ("account", {"accountname": "Customer"}),
        ("contact", {"firstname": "Jane"}),
        ("opportunity", {"accountid": ID, "name": "Deal"}),
        ("task", {"subject": "Follow up"}),
    ],
)
@pytest.mark.parametrize("action", ["list", "get", "create", "update", "delete"])
async def test_all_operation_routes_and_payloads(wire, resource, required, action):
    plural = "opportunities" if resource == "opportunity" else resource + "s"
    operation = action + "_" + (plural if action == "list" else resource)
    config = {"operation": operation}
    if action in {"get", "update", "delete"}:
        config["record_id"] = ID
    if action in {"create", "update"}:
        config.update(required)
    if action == "list":
        wire["body"] = json.loads(
            (Path(__file__).parent / "fixtures/fireberry/accounts.json").read_text()
        )
        config.update(pagesize=25, pagenumber=2)
    result = await node(config).execute({})
    (request,) = wire["requests"]
    assert (
        request.method
        == {
            "list": "GET",
            "get": "GET",
            "create": "POST",
            "update": "PUT",
            "delete": "DELETE",
        }[action]
    )
    assert request.url.host == "api.fireberry.com"
    assert request.url.path == "/api/record/" + resource + (
        "/" + ID if action in {"get", "update", "delete"} else ""
    )
    assert request.headers["tokenid"] == TOKEN and TOKEN not in str(request.url)
    assert result["status"] == "success"
    if action in {"create", "update"}:
        assert json.loads(request.content) == required
    elif action == "list":
        assert dict(request.url.params) == {"pagesize": "25", "pagenumber": "2"}
        assert result["items"][0]["accountname"] == "Customer"
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_connection_evidence_uses_account_records_and_rejects_bad_key(wire):
    wire["body"] = json.loads(
        (Path(__file__).parent / "fixtures/fireberry/accounts.json").read_text()
    )
    result = await validate_for_connect(
        credential_type="fireberry_api_token",
        credential_data={"api_token": TOKEN},
        user_id=ID,
        probe=True,
    )
    assert not result.field_errors and result.evidence.reachable is True
    assert result.evidence.samples[0].label == "Customer"
    wire["code"] = 401
    wire["body"] = {"Message": "Unauthorized"}
    rejected = await validate_for_connect(
        credential_type="fireberry_api_token",
        credential_data={"api_token": TOKEN},
        user_id=ID,
        probe=True,
    )
    assert rejected.evidence.reachable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"success": False, "message": "Permission denied"},
        {"success": True, "data": {}},
        [],
    ],
)
async def test_bad_response_is_not_success(wire, body):
    wire["body"] = body
    with pytest.raises(ValueError):
        await node({"operation": "list_accounts"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "list_accounts", "pagesize": 51},
        {"operation": "list_accounts", "pagenumber": 11},
        {"operation": "get_account", "record_id": "../contact"},
        {"operation": "create_account"},
        {"operation": "update_contact", "record_id": ID},
        {"operation": "create_task", "subject": "Call", "objectid": ID},
    ],
)
def test_invalid_config(config):
    assert native.FireberryNode.validate_config({"config": config})["valid"] is False
