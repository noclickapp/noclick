"""Ashby request contracts against the published RPC methods."""

import base64
import json
from unittest.mock import Mock

import httpx
import pytest

from nodes.ashby_node import AshbyNode, AshbyNodeConfig, CONFIG_MODELS, OPERATION_SPECS
from nodes.tests import _httpx_mock as respx


def _fields_for(operation: str) -> dict:
    model = CONFIG_MODELS[operation]
    values = {}
    for name, field in model.model_fields.items():
        if name == "operation" or not field.is_required():
            continue
        values[name] = 1 if field.annotation is int else "Open" if name == "status" else "sample"
    return values


def node(operation: str, **fields) -> AshbyNode:
    return AshbyNode(
        node_id="ashby-test", node_type="automation-ashby", node_data={},
        config=AshbyNodeConfig.model_validate({
            "config": {"operation": operation, **_fields_for(operation), **fields},
            "credentials": {"credential_type": "ashby_api_key", "api_key": "secret"},
        }),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATION_SPECS)
async def test_every_operation_uses_versioned_api_and_basic_auth(operation):
    method = OPERATION_SPECS[operation][0]
    with respx.mock:
        route = respx.post(f"https://api.ashbyhq.com/{method}").mock(
            return_value=httpx.Response(200, json={"success": True, "results": {"id": "result"}})
        )
        output = await node(operation).execute({})
    assert output["operation"] == operation
    assert output["data"]["results"]["id"] == "result"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"secret:").decode()
    assert request.headers["Accept"] == "application/json; version=1"
    assert json.loads(request.content) == _fields_for(operation)


@pytest.mark.asyncio
async def test_candidate_create_and_application_stage_payloads():
    with respx.mock:
        route = respx.post("https://api.ashbyhq.com/candidate.create").mock(
            return_value=httpx.Response(200, json={"success": True, "results": {"id": "candidate"}})
        )
        await node("create_candidate", name="Ada Lovelace", email="ada@example.com").execute({})
    assert json.loads(route.calls.last.request.content) == {
        "name": "Ada Lovelace", "email": "ada@example.com",
    }

    with respx.mock:
        route = respx.post("https://api.ashbyhq.com/application.changeStage").mock(
            return_value=httpx.Response(200, json={"success": True, "results": {"id": "application"}})
        )
        await node("change_application_stage", applicationId="app", interviewStageId="stage").execute({})
    assert json.loads(route.calls.last.request.content) == {
        "applicationId": "app", "interviewStageId": "stage",
    }


@pytest.mark.asyncio
async def test_pagination_and_json_filter_are_preserved():
    with respx.mock:
        route = respx.post("https://api.ashbyhq.com/job.list").mock(
            return_value=httpx.Response(200, json={
                "success": True, "results": [{"id": "job", "title": "Engineer"}],
                "nextCursor": "next", "moreDataAvailable": True,
            })
        )
        output = await node("list_jobs", cursor="start", limit=25, status='["Open"]').execute({})
    assert json.loads(route.calls.last.request.content) == {
        "cursor": "start", "limit": 25, "status": ["Open"],
    }
    assert output["data"]["nextCursor"] == "next"
    with pytest.raises(ValueError, match="status must be valid JSON"):
        await node("list_jobs", status="not-json").execute({})


@pytest.mark.asyncio
async def test_http_and_rpc_failures_surface_without_disclosing_key():
    for status, payload in [
        (403, {"success": False, "error": "missing_endpoint_permission"}),
        (200, {"success": False, "errors": [{"message": "invalid request"}]}),
    ]:
        with respx.mock:
            respx.post("https://api.ashbyhq.com/job.list").mock(
                return_value=httpx.Response(status, json=payload)
            )
            with pytest.raises(ValueError, match="Ashby API error") as exc:
                await node("list_jobs").execute({})
            assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_dynamic_job_options_come_from_authenticated_account():
    with respx.mock:
        route = respx.post("https://api.ashbyhq.com/job.list").mock(
            return_value=httpx.Response(200, json={
                "success": True,
                "results": [{"id": "one", "title": "Engineer"}, {"id": "two", "title": "Designer"}],
            })
        )
        options = await AshbyNode.load_field_options(
            "jobId", {"api_key": "secret"}, page_token="next", search="design"
        )
    assert options == [{"value": "two", "label": "Designer"}]
    assert json.loads(route.calls.last.request.content) == {"cursor": "next", "limit": 100}


def test_schema_lists_every_operation_and_credential():
    schema = AshbyNode.get_config_schema()
    assert len(OPERATION_SPECS) == 29
    assert schema["properties"]["credentials"]["anyOf"][0]["$ref"].endswith("AshbyApiKeyCredential")
    assert all(name in CONFIG_MODELS for name in OPERATION_SPECS)
