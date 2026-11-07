"""Maia native factory, dispatcher, OAuth form and metadata tests.

Synthetic credentials and responses only; no provider request or qualification.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nodes import matillion_node as mn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup


def uid(n):
    return f"00000000-0000-0000-0000-{n:012x}"


PROJECT, EXECUTION = uid(1), uid(2)
CREDS = {"credential_type": mn.FAMILIES[0], "access_token": "synthetic+/=token", "region": "eu1"}
CLIENT = {"credential_type": mn.FAMILIES[1], "client_id": "synthetic-client", "client_secret": "synthetic+/=secret", "region": "us1"}
STAMP = datetime(2026, 10, 6, tzinfo=timezone.utc)
EX = {"projectId": PROJECT, "pipelineExecutionId": EXECUTION, "environmentName": "Dev", "pipelineName": "Owned pipeline", "status": "RUNNING", "trigger": "API", "user": "private", "message": "private", "scheduleId": "private"}
ART = {"versionName": "1.0", "enabled": True, "createdAt": "2026-10-06T00:00:00Z", "branch": "private", "commitHash": "private", "provider": "private"}


def page(rows, *, current=0, size=25, total=None):
    return {"results": rows, "page": current, "size": size, "total": len(rows) if total is None else total}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


class Response:
    def __init__(self, payload=None, *, status=200, raw=None, content_type="application/json"):
        self.status_code, self.headers = status, {"content-type": content_type}
        self.raw = raw if raw is not None else json.dumps(payload).encode()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw


@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(mn.httpx, "AsyncClient", client)
    return SimpleNamespace(calls=calls, responses=responses)


async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=mn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)


def test_actual_factory_families_regions_numeric_fields_and_foreign_saved_rows():
    schema = mn.MatillionNode.get_config_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 15
    data = {"config": {"operation": "list_environments", "project_id": PROJECT, "page": "0", "size": "25"}, "credentials": CREDS}
    node = NodeFactory.create_node(node_id="native", node_type=mn.NODE_TYPE, node_data=data, user_id="actor")
    assert node.config.config.page == 0 and node.config.config.size == 25
    for family in ("http_bearer", "matillion_pat", None):
        bad = {**data, "credential_id": "saved", "credentials": {**CREDS, "credential_type": family}}
        assert mn.MatillionNode.validate_config(bad)["valid"] is False
        with pytest.raises(ValueError, match="family"):
            mn.MatillionNode.parse_config(bad)
    for fields in ({"region": "eu"}, {"access_token": "Bearer wrong"}, {"expires_at": "2026-10-06T00:00:00"}, {"region": "https://evil.test"}):
        with pytest.raises(ValueError):
            mn.MatillionNode.parse_config({**data, "credentials": {**CREDS, **fields}})
    assert mn._shape({"access_token": "issued", "region": "au1"})["credential_type"] == mn.FAMILIES[0]
    with pytest.raises(ValueError):
        mn._shape({**CLIENT, "credential_type": None, "access_token": "ambiguous"})


@pytest.mark.asyncio
async def test_empty_protected_access_exact_bearer_and_honest_evidence(monkeypatch, wire):
    wire.responses.append(Response(page([], size=1)))
    result = await run("test_connection")
    assert result["data"]["protected_read_completed"] is True
    assert result["data"]["account_identity_verified"] is False and result["data"]["execution_permission_verified"] is False
    assert wire.calls[0]["url"] == mn.REGIONS["eu1"] + "/v1/projects"
    assert wire.calls[0]["headers"]["Authorization"] == "Bearer " + CREDS["access_token"]
    assert wire.calls[0]["params"] == {"page": 0, "size": 1}
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    monkeypatch.setattr(run_op, "run_node_operation", AsyncMock(return_value=result))
    evidence = await collect_evidence(node_type=mn.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.reachable is True and mn.MatillionNode.connection_evidence.proves == "reachability" and evidence.account_label is None


@pytest.mark.asyncio
async def test_client_credentials_exact_form_audience_region_and_no_refresh(wire):
    wire.responses.extend([Response({"access_token": "new-synthetic-token", "token_type": "Bearer", "expires_in": 1800}), Response(page([], size=1))])
    await run("test_connection", credential_data=CLIENT)
    assert wire.calls[0]["url"] == mn.TOKEN_URL and wire.calls[0]["method"] == "POST"
    assert wire.calls[0]["data"] == {"grant_type": "client_credentials", "client_id": CLIENT["client_id"], "client_secret": CLIENT["client_secret"], "audience": mn.AUDIENCE}
    assert wire.calls[0]["headers"]["Content-Type"] == "application/x-www-form-urlencoded" and "json" not in wire.calls[0]
    assert wire.calls[1]["url"].startswith(mn.REGIONS["us1"]) and wire.calls[1]["headers"]["Authorization"] == "Bearer new-synthetic-token"
    wire.responses.append(Response({"access_token": "new-synthetic-token", "token_type": "Bearer", "expires_in": 1801}))
    with pytest.raises(mn.MatillionAPIError, match="token response"):
        await run("test_connection", credential_data=CLIENT)
    assert len(wire.calls) == 3


@pytest.mark.asyncio
async def test_row_or_region_change_during_token_mint_discards_token(monkeypatch, wire):
    current = mn._shape(CLIENT)
    monkeypatch.setattr(mn, "_current_data", AsyncMock(side_effect=[current, current, {**current, "region": "eu1"}]))
    wire.responses.append(Response({"access_token": "discarded", "token_type": "Bearer", "expires_in": 1800}))
    with pytest.raises(ValueError, match="changed during authentication"):
        await run("test_connection", credential_data=CLIENT)
    assert len(wire.calls) == 1 and wire.calls[0]["url"] == mn.TOKEN_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,payload,route", [
    ("list_projects", {}, page([{"id": PROJECT, "name": "Project", "description": "private"}]), "/v1/projects"),
    ("list_environments", {"project_id": PROJECT}, page([{"name": "Dev", "defaultAgentName": "Runner", "defaultAgentId": "private"}]), f"/v1/projects/{PROJECT}/environments"),
    ("list_published_pipelines", {"project_id": PROJECT, "environment_name": "Dev"}, page([{"name": "Owned pipeline"}]), f"/v1/projects/{PROJECT}/published-pipelines"),
    ("list_artifacts", {"project_id": PROJECT, "environment_name": "Dev"}, page([ART]), f"/v1/projects/{PROJECT}/artifacts"),
    ("get_artifact_metadata", {"project_id": PROJECT, "environment_name": "Dev", "version_name": "1.0"}, {"details": ART, "assets": ["private"]}, f"/v1/projects/{PROJECT}/artifacts/details"),
    ("get_pipeline_execution_metadata", {"project_id": PROJECT, "pipeline_execution_id": EXECUTION}, EX, f"/v1/projects/{PROJECT}/pipeline-executions/{EXECUTION}"),
    ("get_pipeline_execution_status", {"project_id": PROJECT, "pipeline_execution_id": EXECUTION}, {"status": "FORBIDDEN"}, f"/v1/projects/{PROJECT}/pipeline-executions/{EXECUTION}/status"),
    ("list_shared_artifact_metadata", {}, page([{**ART, "sharedPipelineIdPrefix": "shared"}]), "/v1/shared-pipelines/artifacts"),
    ("get_shared_artifact_metadata", {"shared_pipeline_id_prefix": "shared", "version_name": "1.0"}, {"artifactDetails": {**ART, "sharedPipelineIdPrefix": "shared"}, "sharedPipelines": [{"sharedPipelineId": "shared/name", "sourcePipeline": "private"}]}, "/v1/shared-pipelines/artifacts/details"),
])
async def test_actual_closed_metadata_reads(wire, op, args, payload, route):
    wire.responses.append(Response(payload))
    result = await run(op, args)
    assert len(wire.calls) == 1 and wire.calls[0]["method"] == "GET" and wire.calls[0]["url"] == mn.REGIONS["eu1"] + route
    assert "private" not in json.dumps(result)
    if "environment_name" in args:
        assert wire.calls[0]["params"]["environmentName"] == "Dev"


@pytest.mark.asyncio
async def test_root_scoped_steps_and_documented_child_tasks(wire):
    step = {"id": uid(3), "name": "Step", "result": {"status": "SUCCESS", "message": "private"}, "childPipeline": {"name": "private"}}
    task = {"pipeline": {"pipelineExecutionId": uid(4)}, "task": {"id": uid(5), "name": "Child task", "iterator": False, "result": {"status": "SUCCESS", "message": "private"}}}
    for op, row in [("list_execution_steps", step), ("list_execution_tasks", task)]:
        wire.responses.extend([Response(EX), Response(page([row]))])
        result = await run(op, {"project_id": PROJECT, "pipeline_execution_id": EXECUTION})
        assert "private" not in json.dumps(result)
    assert result["data"]["results"][0]["pipelineExecutionId"] == uid(4)
    wire.responses.append(Response({**EX, "projectId": uid(99)}))
    with pytest.raises(mn.MatillionAPIError, match="selected project"):
        await run("list_execution_tasks", {"project_id": PROJECT, "pipeline_execution_id": EXECUTION})
    assert len(wire.calls) == 5


@pytest.mark.asyncio
async def test_execution_cursor_scope_filter_exhaustion_and_no_raw_message(wire):
    wire.responses.append(Response({"results": [EX], "more": "provider-cursor"}))
    first = (await run("list_pipeline_executions", {"project_id": PROJECT, "environment_name": "Dev", "pipeline_name_search": "Owned", "limit": 1}))["data"]
    assert wire.calls[-1]["params"] == {"projectId": PROJECT, "environmentName": "Dev", "pipelineName": "Owned", "limit": 1}
    with pytest.raises(ValueError, match="continuation"):
        await run("list_pipeline_executions", {"project_id": uid(99), "environment_name": "Dev", "pipeline_name_search": "Owned", "limit": 1, "continuation": first["next_continuation"]})
    wire.responses.append(Response({"results": [{**EX, "pipelineExecutionId": uid(6)}]}))
    final = (await run("list_pipeline_executions", {"project_id": PROJECT, "environment_name": "Dev", "pipeline_name_search": "Owned", "limit": 1, "continuation": first["next_continuation"]}))["data"]
    assert final["collection_exhausted"] is True and final["next_continuation"] is None and wire.calls[-1]["params"]["paginationToken"] == "provider-cursor"
    wire.responses.append(Response({"results": [], "more": None}))
    with pytest.raises(mn.MatillionAPIError, match="exhaustion is unknown"):
        await run("list_pipeline_executions", {"project_id": PROJECT})
    assert len(wire.calls) == 3


@pytest.mark.asyncio
async def test_confirmed_start_and_cancel_json_async_ack_no_replay(wire):
    for op, args in [("start_pipeline_execution", {"project_id": PROJECT, "environment_name": "Dev", "pipeline_name": "Owned pipeline"}), ("cancel_pipeline_execution", {"project_id": PROJECT, "pipeline_execution_id": EXECUTION})]:
        with pytest.raises(ValueError, match="Confirm"):
            await run(op, args)
    assert wire.calls == []
    wire.responses.extend([Response(page([{"name": "Dev"}])), Response(page([{"name": "Owned pipeline"}])), Response({"details": ART}), Response({"pipelineExecutionId": EXECUTION}, status=201)])
    result = (await run("start_pipeline_execution", {"project_id": PROJECT, "environment_name": "Dev", "pipeline_name": "Owned pipeline", "version_name": "1.0", "execution_tag": "owned-tag", "confirm_execution": True}))["data"]
    assert wire.calls[-1]["json"] == {"pipelineName": "Owned pipeline", "environmentName": "Dev", "versionName": "1.0", "executionTag": "owned-tag"}
    assert wire.calls[-1]["headers"]["Content-Type"] == "application/json" and result["http_status"] == 201
    assert result["execution_completed"] is False and result["independent_readback_verified"] is False
    wire.responses.extend([Response(EX), Response({"pipelineExecutionId": EXECUTION})])
    cancelled = (await run("cancel_pipeline_execution", {"project_id": PROJECT, "pipeline_execution_id": EXECUTION, "confirm_execution": True}))["data"]
    assert wire.calls[-1]["method"] == "PATCH" and wire.calls[-1]["json"] == {"forceUpdate": False, "status": "CANCELLED"}
    assert cancelled["cancellation_completed"] is False and cancelled["data_rollback_verified"] is False
    wire.responses.extend([Response(EX), Response({})])
    with pytest.raises(mn.MatillionAPIError, match="outcome is unknown"):
        await run("cancel_pipeline_execution", {"project_id": PROJECT, "pipeline_execution_id": EXECUTION, "confirm_execution": True})
    assert len(wire.calls) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,raw,ctype,status", [
    (page([]), None, "text/html", 200), (page([]), None, "application/json", 202),
    (dict(page([]), status="rejected"), None, "application/json", 200),
    (None, b'{"results":[],"page":0,"size":25,"total":0,"x":NaN}', "application/json", 200),
    (None, b'{"results":[],"page":0,"size":25,"total":0,"x":1e309}', "application/json", 200),
    ({"detail": "private synthetic+/=token"}, None, "application/json", 403),
    (page([], total=1), None, "application/json", 200),
])
async def test_unknown_or_rejected_response_is_private_and_not_replayed(wire, payload, raw, ctype, status):
    wire.responses.append(Response(payload, raw=raw, content_type=ctype, status=status))
    with pytest.raises(mn.MatillionAPIError) as caught:
        await run("list_projects")
    assert "private" not in str(caught.value) and CREDS["access_token"] not in str(caught.value) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_actual_picker_parent_before_auth_filtered_pages_and_bound_cursor(wire):
    with pytest.raises(ValueError):
        await mn.MatillionNode.load_field_options("pipeline_name", CLIENT, context={"_user_id": "actor"})
    assert wire.calls == []
    rows = [{"id": uid(10+i), "name": "Unmatched"} for i in range(25)]
    wire.responses.extend([Response(page(rows, total=26)), Response(page([{"id": uid(40), "name": "Wanted"}], current=1, total=26))])
    found = await mn.MatillionNode.load_field_options("project_id", CREDS, context={"_user_id": "actor"}, search="Wanted")
    assert found == {"options": [{"value": uid(40), "label": "Wanted"}], "next_page_token": None}
    wire.responses.append(Response({"results": [EX], "more": "picker-cursor"}))
    first = await mn.MatillionNode.load_field_options("pipeline_execution_id", CREDS, context={"_user_id": "actor", "project_id": PROJECT})
    before = len(wire.calls)
    with pytest.raises(ValueError, match="continuation"):
        await mn.MatillionNode.load_field_options("pipeline_execution_id", CREDS, context={"_user_id": "other", "project_id": PROJECT}, page_token=first["next_page_token"])
    assert len(wire.calls) == before
    wire.responses.append(Response({"results": [{**EX, "pipelineExecutionId": uid(41)}]}))
    assert (await mn.MatillionNode.load_field_options("pipeline_execution_id", CREDS, context={"_user_id": "actor", "project_id": PROJECT}, page_token=first["next_page_token"]))["next_page_token"] is None


@pytest.mark.asyncio
async def test_freshen_validates_resolved_credentials_without_transport(wire):
    assert await mn.MatillionNode.freshen_credential(CREDS) == mn._shape(CREDS)
    with pytest.raises(ValueError):
        await mn.MatillionNode.freshen_credential({**CREDS, "credential_type": "http_bearer"})
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_saved_admission_precedes_mint_and_resource_transport(monkeypatch, wire, status):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CLIENT))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"status": status, "id": "approval", "new_request": False}))
    result = await run("test_connection", credential_data=CLIENT, credential_id="saved", pool=object())
    lookup = await run_node_lookup(node_type=mn.NODE_TYPE, field_name="project_id", credential_id="saved", user_id="actor", pool=object())
    assert result["executed"] is False and lookup["status"] in ("pending_approval", "rejected") and wire.calls == []


@pytest.mark.asyncio
async def test_filter_cap_expiry_and_disabled_artifact_before_effect(wire):
    wire.responses.append(Response({"results": [EX]}))
    with pytest.raises(mn.MatillionAPIError, match="selected filters"):
        await run("list_pipeline_executions", {"project_id": PROJECT, "status_filter": "SUCCESS"})
    data = mn._shape(CREDS)
    binding = mn._continuation_binding(data, {"_user_id": "actor"}, ["picker", "project_id", None, None, "No match"])
    token = mn._pack({"binding": binding, "page": 39, "seen": [uid(i+100) for i in range(400)], "execution_continuation": None})
    wire.responses.append(Response(page([{"id": uid(i+1000), "name": "Unmatched"} for i in range(25)], current=39, total=1001)))
    with pytest.raises(mn.MatillionAPIError, match="1,000-item bound"):
        await mn.MatillionNode.load_field_options("project_id", CREDS, context={"_user_id": "actor"}, search="No match", page_token=token)
    before = len(wire.calls)
    with pytest.raises(ValueError):
        await run("test_connection", credential_data={**CREDS, "expires_at": "2000-01-01T00:00:00Z"})
    assert len(wire.calls) == before
    wire.responses.extend([Response(page([{"name": "Dev"}])), Response(page([{"name": "Owned pipeline"}])), Response({"details": {**ART, "enabled": False}})])
    with pytest.raises(ValueError, match="disabled"):
        await run("start_pipeline_execution", {"project_id": PROJECT, "environment_name": "Dev", "pipeline_name": "Owned pipeline", "version_name": "1.0", "confirm_execution": True})
    assert all(c["method"] == "GET" for c in wire.calls)
