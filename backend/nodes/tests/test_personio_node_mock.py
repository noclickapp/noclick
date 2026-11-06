"""Every operation uses the provider-authored fixture and source URL in responses.json.

Sources: https://github.com/personio/api-docs and https://developer.personio.de/openapi
Fixtures are preserved even where Personio's published schemas reject their own examples.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs
import httpx
import pytest
from pydantic import ValidationError
from nodes.personio_node import (
    PersonioNode,
    PersonioNodeConfig,
    PersonioAccessTokenCredential,
    ROUTES,
)

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/personio/responses.json").read_text()
)
TOKEN = "personio-test-token"


def node(config):
    return PersonioNode(
        node_id="test-personio",
        node_type="automation-personio",
        node_data={},
        config=PersonioNodeConfig(
            config=config, credentials=PersonioAccessTokenCredential(access_token=TOKEN)
        ),
        sio=Mock(),
        sid="test",
        workflow_id="test",
        user_id="test",
    )


async def run(config, body, code=200):
    requests = []
    original = httpx.AsyncClient

    def transport(request):
        requests.append(request)
        return (
            httpx.Response(code, json=body)
            if body is not None
            else httpx.Response(code)
        )

    with patch(
        "nodes.personio_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(transport=httpx.MockTransport(transport)),
    ):
        result = await node(config).execute({})
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("action", list(FIXTURES))
async def test_documented_operation(action):
    f = FIXTURES[action]
    config = {"operation": action, **f["config"]}
    result, requests = await run(config, f["body"], f["status_code"])
    assert len(requests) == 1
    req = requests[0]
    path = f["path"]
    for key in ("employee_id", "attendance_id", "time_off_id"):
        if key in config:
            path = path.replace("{" + key + "}", str(config[key]))
    if "{id}" in path:
        path = path.replace(
            "{id}", str(config.get("attendance_id", config.get("time_off_id")))
        )
    assert (req.method, req.url.path) == (f["method"], path)
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert result["status"] == "success", result
    assert result["status_code"] == f["status_code"]
    assert result["raw_response"] == (f["body"] or {})
    assert result["data"] == (f["body"] or {}).get(
        "data", (f["body"] or {}).get("_data", f["body"] or {})
    )
    assert "total" in result["timing_ms"]
    if action in ("create_employee", "update_employee"):
        assert json.loads(req.content) == {
            "employee": {k: v for k, v in f["config"].items() if k != "employee_id"}
        }
    elif action == "create_time_off":
        assert req.headers["content-type"].startswith(
            "application/x-www-form-urlencoded"
        )
        assert parse_qs(req.content.decode()) == {
            k: [str(v).lower() if isinstance(v, bool) else str(v)]
            for k, v in f["config"].items()
        }
    elif action in ("create_attendance_period", "update_attendance_period"):
        payload = json.loads(req.content)
        assert payload["start"] == {"date_time": f["config"]["start"]}
        assert payload["end"] == {"date_time": f["config"]["end"]}
        assert payload["project"] == {"id": f["config"]["project_id"]}
        assert req.url.params["skip_approval"] == "false"
        if action == "create_attendance_period":
            assert payload["person"] == {"id": "1"}
            assert payload["type"] == "WORK"
    elif action == "list_time_offs":
        assert req.url.params["person.id"] == "123,456"
        assert req.url.params["updated_at.gte"] == "2023-01-01T12:00:00Z"
    elif action == "list_attendance_periods":
        assert req.url.params["person.id"] == "1,2,3"


def test_every_operation_has_a_documented_fixture():
    assert set(FIXTURES) == set(ROUTES)
    assert all(f["source"].startswith("https://") for f in FIXTURES.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 422, 429, 500])
async def test_errors_keep_provider_text(code):
    # Problem details: official attendance-period-service-v2.yaml.
    result, _ = await run(
        {"operation": "list_employees"},
        {"title": "Forbidden", "detail": "Insufficient permissions", "status": code},
        code,
    )
    assert result["status"] == "error"
    assert "Insufficient permissions" in result["error"]


@pytest.mark.asyncio
async def test_false_success_is_rejected():
    # ErrorResponse: official personio-personnel-data-api-oa3.yaml.
    result, _ = await run(
        {"operation": "get_employee", "employee_id": 1},
        {"success": False, "error": {"message": "Unauthorized"}},
    )
    assert result["status"] == "error"
    assert "Unauthorized" in result["error"]


@pytest.mark.asyncio
async def test_patch_nulls_survive_and_unset_fields_are_omitted():
    result, requests = await run(
        {
            "operation": "update_attendance_period",
            "attendance_id": "period-1",
            "end": None,
            "project_id": None,
        },
        None,
        204,
    )
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {"end": None, "project": None}
    _, requests = await run(
        {"operation": "update_employee", "employee_id": 1, "supervisor_id": None},
        {"success": True, "data": {"id": 1}},
    )
    assert json.loads(requests[0].content) == {"employee": {"supervisor_id": None}}


@pytest.mark.asyncio
async def test_open_attendance_omits_end():
    result, requests = await run(
        {
            "operation": "create_attendance_period",
            "person_id": "1",
            "start": "2024-01-01T10:00:00",
        },
        FIXTURES["create_attendance_period"]["body"],
        201,
    )
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {
        "person": {"id": "1"},
        "type": "WORK",
        "start": {"date_time": "2024-01-01T10:00:00"},
    }


@pytest.mark.asyncio
async def test_pagination_metadata_survives():
    fixture = FIXTURES["list_employees"]
    result, req = await run(
        {
            "operation": "list_employees",
            "limit": 10,
            "cursor": "next-page",
            "updated_since": "2023-01-01T12:00:00Z",
        },
        fixture["body"],
    )
    assert result["metadata"] == fixture["body"]["_meta"]
    assert req[0].url.params["cursor"] == "next-page"
    assert req[0].url.params["updated_at.gte"] == "2023-01-01T12:00:00Z"


def test_empty_updates_rejected():
    for config in (
        {"operation": "update_employee", "employee_id": 1},
        {"operation": "update_attendance_period", "attendance_id": "period-1"},
    ):
        with pytest.raises(ValidationError):
            PersonioNodeConfig(config=config)


def test_connection_evidence_is_account_specific_read():
    evidence = PersonioNode.connection_evidence
    assert evidence.operation == "list_employees"
    assert ROUTES[evidence.operation] == ("GET", "/v2/persons")


@pytest.mark.asyncio
async def test_employee_picker_uses_documented_person_list():
    f = FIXTURES["list_employees"]
    original = httpx.AsyncClient
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=f["body"])

    with patch(
        "nodes.personio_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(transport=httpx.MockTransport(transport)),
    ):
        result = await PersonioNode.load_field_options(
            "employee_id", {"access_token": TOKEN}, search="John"
        )
    assert requests[0].url.path == "/v2/persons"
    assert result["options"] == [{"value": "3003", "label": "John Smith"}]
