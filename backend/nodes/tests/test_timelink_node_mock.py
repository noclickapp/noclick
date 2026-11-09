"""Timelink transport regressions with synthetic data and published wire fields."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import timelink_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-timelink-token-42"
CASES = json.loads(
    (Path(__file__).parent / "fixtures/timelink/operations.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="timelink-fixture",
        node_type="automation-timelink",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "timelink_api_token",
                "api_token": TOKEN,
            },
        },
    )


def transport(monkeypatch, status, payload):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_timelink_wire_contract(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.timelink.io"
    assert request.url.path == case["path"]
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert not request.url.query
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert result["status"] == "success"
    assert result["data"] == case["response"]["data"]
    if case["config"]["operation"].startswith("list_"):
        assert result["single_page"] is True
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_timelink_query_false_date_and_filters(monkeypatch):
    requests = transport(monkeypatch, 200, {"data": []})
    await node(
        {
            "operation": "list_time_entries",
            "limit": 10,
            "isBilled": False,
            "projectId": "01jd9kk3es6s9amhn8smf6dsj6",
            "start": "2024-08-01T06:25:00Z",
        }
    ).execute({})
    assert dict(requests[0].url.params) == {
        "limit": "10",
        "isBilled": "false",
        "projectId": "01jd9kk3es6s9amhn8smf6dsj6",
        "start": "2024-08-01T06:25:00Z",
    }


@pytest.mark.asyncio
async def test_timelink_patch_preserves_null_and_false(monkeypatch):
    requests = transport(monkeypatch, 200, {"data": {"id": "owned"}, "success": True})
    await node(
        {
            "operation": "update_time_entry",
            "id": "owned",
            "ended_at": None,
            "description": None,
            "client_id": None,
            "billable": False,
        }
    ).execute({})
    assert json.loads(requests[0].content) == {
        "ended_at": None,
        "description": None,
        "client_id": None,
        "billable": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 422, 429, 500])
async def test_timelink_provider_rejection_no_retries_and_redaction(
    monkeypatch, status
):
    requests = transport(monkeypatch, status, {"message": "Rejected " + TOKEN})
    result = await node({"operation": "create_client", "name": "Test GmbH"}).execute({})
    assert len(requests) == 1
    assert result["success"] is False and result["http_status"] == status
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{"success": False, "data": {}}, {"message": "bad"}, {"data": {}}]
)
async def test_timelink_rejects_invalid_list_envelopes(monkeypatch, payload):
    transport(monkeypatch, 200, payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_clients"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_client", "id": "../token"},
        {"operation": "update_client", "id": "owned"},
        {"operation": "update_client", "id": "owned", "name": None},
        {
            "operation": "create_time_entry",
            "user_id": "owned",
            "started_at": "2024-01-01T00:00:00",
        },
        {"operation": "create_client", "name": "Test", "unexpected": True},
    ],
)
def test_timelink_rejects_invalid_inputs(config):
    with pytest.raises((ValueError, ValidationError)):
        native.TimelinkNode.parse_config({"config": config})


def test_timelink_manual_token_default_and_evidence():
    credential = native.TimelinkTokenCredential(api_token=TOKEN)
    assert credential.credential_type == "timelink_api_token"
    assert native.TimelinkNode.connection_evidence.operation == "list_clients"
    assert len(CASES) == len(native.ROUTES) == 25
