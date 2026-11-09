"""Ninety's documented requests exercised through the real node factory."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import ninety_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/ninety/cases.json").read_text())
TOKEN = "synthetic-ninety-token"
ID = "507f1f77bcf86cd799439011"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="ninety-test",
        node_type="automation-ninety",
        node_data={
            "config": config,
            "credentials": {"credential_type": "ninety_personal_token", "access_token": TOKEN},
        },
    )


def transport(monkeypatch, status, body=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda row: row["config"]["operation"])
async def test_each_operation_exactly_one_documented_request(monkeypatch, case):
    payload = {"_id": ID, "title": "Documented fixture"}
    if case["kind"] == "array":
        payload = [{"_id": ID, "name": "Leadership"}]
    elif case["kind"] == "page":
        payload = {"data": [payload], "pagination": {"nextToken": "opaque+cursor/="}}
    elif case["kind"] == "empty":
        payload = None
    requests = transport(monkeypatch, case["status"], payload)
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    expected_path = case["path"]
    for parameter, field in case["path_fields"].items():
        expected_path = expected_path.replace("{" + parameter + "}", case["config"][field])
    assert request.url.host == "api.public.ninety.io"
    assert request.url.path == expected_path
    assert request.method == case["method"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    expected_body = {k: v for k, v in case["config"].items() if k not in {"operation", *case["path_fields"].values()}}
    if case["method"] in {"POST", "PATCH"}:
        assert json.loads(request.content) == expected_body
    else:
        assert request.content == b""
    assert result["http_status"] == case["status"]
    if case["kind"] == "page":
        assert result["data"] == payload["data"]
        assert result["pagination"] == payload["pagination"]
    elif case["kind"] == "empty":
        assert result["deleted"] is True
    else:
        assert result["data"] == payload
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_filters_false_and_opaque_cursor_round_trip(monkeypatch):
    requests = transport(monkeypatch, 200, {"data": [], "pagination": {"nextToken": None}})
    result = await node(
        {
            "operation": "list_todos",
            "limit": 25,
            "nextToken": "abc+/=",
            "completed": False,
            "archived": True,
            "searchText": "Client + renewal",
            "sortOrder": "asc",
        }
    ).execute({})
    assert dict(requests[0].url.params) == {
        "limit": "25",
        "nextToken": "abc+/=",
        "completed": "false",
        "archived": "true",
        "searchText": "Client + renewal",
        "sortOrder": "asc",
    }
    assert result["data"] == [] and result["pagination"]["nextToken"] is None
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_nested_rock_and_zero_score(monkeypatch):
    case = next(row for row in CASES if row["config"]["operation"] == "create_rock")
    requests = transport(monkeypatch, case["status"], [{"id": ID}])
    await node(case["config"]).execute({})
    assert json.loads(requests[0].content)["rock"] == case["config"]["rock"]
    requests = transport(monkeypatch, 200, {"value": 0})
    await node(
        {"operation": "put_score", "kpi_id": ID, "value": 0, "periodStartDate": "2024-01-01T00:00:00.000Z"}
    ).execute({})
    assert json.loads(requests[0].content) == {"value": 0, "periodStartDate": "2024-01-01T00:00:00.000Z"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 429, 500, 502])
async def test_errors_and_partial_write_not_retried_or_reported_as_success(monkeypatch, status):
    requests = transport(monkeypatch, status, {"message": "Provider refused " + TOKEN})
    with pytest.raises(ValueError) as error:
        await node({"operation": "update_todo", "todo_id": ID, "completed": False}).execute({})
    assert str(status) in str(error.value) and "Provider refused" in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": []}, {"data": [], "pagination": []}, {"error": "Rejected"}])
async def test_malformed_pagination_fails(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_todos"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_todo", "todo_id": "../users"},
        {"operation": "create_todo"},
        {"operation": "create_todo", "title": "Follow up", "linkedItemId": ID},
        {"operation": "list_todos", "limit": 101},
        {"operation": "create_todo", "title": "Follow up", "dueDate": "2026-02-30"},
        {"operation": "update_rock", "rock_id": ID, "statusCode": "invented"},
        {"operation": "update_milestone", "milestone_id": ID, "isDone": True},
    ],
)
def test_invalid_inputs_refused_before_network(config):
    with pytest.raises((ValidationError, ValueError)):
        native.NinetyFullConfig.model_validate({"config": config})


@pytest.mark.asyncio
async def test_empty_patch_refused(monkeypatch):
    requests = transport(monkeypatch, 200, {})
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_todo", "todo_id": ID}).execute({})
    assert requests == []


def test_manual_credential_type_default_and_evidence_needs_no_config():
    credential = native.NinetyPersonalTokenCredential(access_token=TOKEN)
    assert credential.credential_type == "ninety_personal_token"
    assert native.NinetyNode.connection_evidence.operation == "list_teams"
    assert native.NinetyListTeamsConfig().operation == "list_teams"
    for invalid in ["Bearer secret", "https://example.com/token"]:
        with pytest.raises(ValueError):
            native.NinetyPersonalTokenCredential(access_token=invalid)
