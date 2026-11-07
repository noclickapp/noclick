"""Hevo behavior against staging credential resolution and mocked HTTP/storage."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import hevo_node as native
from nodes.core import credential_connect, connection_evidence, registry, run_op
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credential_approval, credentials, encryption
from wss.handlers import credentials_handler, workflow_handler
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

NODE, USER, ORG = "automation-hevo", "hevo-fixture-user", "hevo-fixture-org"
CID = "00000000-0000-4000-8000-000000000042"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
OPS = {"list_pipelines", "get_pipeline", "get_pipeline_source", "get_pipeline_schedule", "update_pipeline_schedule",
    "set_pipeline_state", "update_pipeline_priority", "list_pipeline_objects", "get_pipeline_object",
    "get_pipeline_object_stats", "list_destinations", "get_destination", "get_destination_table_stats", "list_workflows", "get_workflow"}
SCHEDULE = {"type": "FREQUENCY", "schedule": "Fixture", "schedule_configurable": True,
    "metadata": {"frequency": 600, "min_allowed_frequency": 300, "max_allowed_frequency": 3600, "suggested_frequencies": [300, 600], "destination_tables": ["private-table-fixture"]}}
DESTINATION = {"id": 8, "name": "Fixture destination", "status": "ACTIVE", "health_status": "OK",
    "type": {"name": "REDSHIFT", "display_name": "Redshift", "documentation_url": "https://private.example"},
    "config": {"password": "private-destination-fixture"}, "failure_reason": "private-failure-fixture"}
PIPELINE = {"id": 7, "status": "ACTIVE", "priority": "NORMAL", "health_status": "OK", "schedule": SCHEDULE,
    "source": {"name": "Fixture source", "type": {"name": "POSTGRES", "display_name": "PostgreSQL", "pauseable": True},
        "config": {"password": "private-source-fixture"}, "failure_reason": "private-failure-fixture"},
    "destination": DESTINATION, "webhook_url": "https://private.example/secret"}
OBJECT = {"name": "public.orders", "status": "ACTIVE", "last_run_ts": 1791297000, "position": {"offset": {"private": "fixture"}}}
WORKFLOW = {"id": 9, "name": "Fixture workflow", "status": "SCHEDULED", "schedule": SCHEDULE,
    "last_run_failure_message": "private-query-fixture", "config": {"query": "private-query-fixture"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def local(monkeypatch):
    state = SimpleNamespace(row={"id": CID, "name": "Synthetic Hevo", "credential_type": "hevo_api_key",
        "credential": b"synthetic-encrypted", "metadata": {}, "owner_id": USER, "token_version": 7,
        "approval_revision": 0, "created_at": UPDATED, "updated_at": UPDATED, "revoked_at": None},
        blob={"credential_type": "hevo_api_key", "api_key": "synthetic-hevo-key", "api_secret": "synthetic:secret", "region": "eu"},
        allowed=True, allowed_users={USER}, requests=[], queries=[], responses=[], pending=None, status=200,
        method_status={}, raw=None, payload=None, mutation=None, ignore_update=False, pipeline=deepcopy(PIPELINE))

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, sql, credential_id, user_id, org_id):
            assert "FROM credentials c" in sql and credential_id == CID and org_id == ORG
            assert user_id in {USER, "fixture-workflow-owner"}
            state.queries.append(sql)
            return deepcopy(state.row) if state.allowed and user_id in state.allowed_users else None

    state.pool = Pool()
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    for module in (credentials, encryption, credentials_handler, workflow_handler):
        monkeypatch.setattr(module, "get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: state.pool)
    monkeypatch.setattr(credentials, "get_native_pool", lambda: state.pool)
    monkeypatch.setattr(credential_approval, "get_native_pool", lambda: state.pool)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credentials_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(side_effect=lambda **_: state.pending))

    def transport(request):
        state.requests.append(request)
        if state.mutation: state.mutation()
        status = state.method_status.get(request.method, 204 if request.method == "PUT" and state.status == 200 else state.status)
        if state.raw is not None:
            return httpx.Response(status, content=state.raw, headers={"Content-Type": "application/json"})
        route = request.url.path.removeprefix("/api/public/v2.0")
        if request.method == "PUT":
            body = json.loads(request.content)
            if not state.ignore_update:
                if "frequency" in body: state.pipeline["schedule"]["metadata"]["frequency"] = body["frequency"]
                else: state.pipeline["status" if "state" in body else "priority"] = next(iter(body.values()))
            return httpx.Response(status, content=b"")
        if state.payload is not None: payload = state.payload
        elif route.endswith("/stats"): payload = {"data": [{"stage": "LOADED", "count": 42, "private": "fixture"}]}
        elif route.endswith("/objects"): payload = {"data": [OBJECT]}
        elif "/objects/" in route: payload = {"data": OBJECT}
        elif route.endswith("/schedule"): payload = {"data": [SCHEDULE]}
        elif route == "/pipelines": payload = {"data": [state.pipeline]}
        elif route.startswith("/pipelines/"): payload = {"data": state.pipeline}
        elif route == "/destinations": payload = {"data": [DESTINATION]}
        elif route.startswith("/destinations/"): payload = {"data": DESTINATION}
        elif route == "/workflows": payload = {"data": [WORKFLOW]}
        else: payload = {"data": WORKFLOW}
        return httpx.Response(status, json=deepcopy(payload))

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    state.handler = credentials_handler.CredentialsHandler(sio)
    state.handler.get_pool = AsyncMock(return_value=state.pool)
    state.picker = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    state.picker.sio, state.picker.get_pool = sio, AsyncMock(return_value=state.pool)

    async def capture(_sio, sid, event, **_):
        assert sid == "fixture-sid"
        state.responses.append(event.model_dump())

    monkeypatch.setattr(credentials_handler, "send_event", capture)
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    return state


async def run(local, operation="list_pipelines", **arguments):
    return await run_op.run_node_operation(node_type=NODE, operation=operation, arguments=arguments,
        user_id=USER, pool=local.pool, credential_id=CID, organization_id=ORG)


async def validate(local):
    request = CredentialValidateAccessRequest(request_id="fixture-validation", node_type=NODE, credential_id=CID)
    await local.handler.get_events()[request.event_name]("fixture-sid", request)
    return local.responses[-1]["data"]


async def pick(local, **kwargs):
    request = WorkflowNodeLoadOptionsRequest(request_id="fixture-picker", node_type=NODE,
        field_name="pipeline_id", credential_id=CID, **kwargs)
    await local.picker.get_events()[request.event_name]("fixture-sid", request)
    return local.responses[-1]["data"]


def test_actual_catalog_closed_config_secret_fields_and_reachability():
    from coder.workflow.operation_catalog import get_operations_for_node_type, node_accepted_credential_types
    from nodes.agent.node_op_tools import node_supports_op_tools
    assert registry.NODE_REGISTRY[NODE] is native.HevoNode
    assert {o.name for o in get_operations_for_node_type(NODE)} == OPS
    assert node_accepted_credential_types(NODE) == {"hevo_api_key"} and node_supports_op_tools(NODE)
    schema = native.HevoNode.get_config_schema()
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == OPS
    credential = schema["$defs"]["HevoAPIKeyCredential"]
    assert set(credential["required"]) == {"api_key", "api_secret", "region"}
    assert all(credential["properties"][field]["ui:widget"] == "password" for field in ("api_key", "api_secret"))
    assert native.HevoNode.connection_evidence.proves == "reachability" and native.HevoNode.connection_evidence.identity_operation is None
    assert "synthetic" not in repr(native.HevoAPIKeyCredential(api_key="synthetic", api_secret="synthetic", region="eu"))


@pytest.mark.parametrize("fields", [{"api_key": "bad:key"}, {"api_secret": "bad\nsecret"}, {"region": "https://private.example"}, {"region": "unknown"}])
def test_actual_connect_shape_refuses_unbound_region_and_bad_basic_fields(fields):
    _, errors, resolved = credential_connect.shape_credential("hevo_api_key", {"api_key": "synthetic", "api_secret": "synthetic", "region": "eu", **fields})
    assert errors and resolved[0] == NODE


@pytest.mark.asyncio
@pytest.mark.parametrize("region", native.REGIONS)
async def test_actual_factory_fixed_v2_region_header_saved_type_and_private_projection(local, region):
    local.blob.update(region=region, credential_type="stale-blob-type")
    result = await run(local, limit=5)
    assert result["status"] == "success" and result["region"] == region
    request = local.requests[-1]
    assert request.url.host == region + ".hevodata.com" and request.url.path == "/api/public/v2.0/pipelines"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"synthetic-hevo-key:synthetic:secret").decode()
    assert dict(request.url.params) == {"limit": "5"} and len(local.queries) >= 3
    assert "private-" not in json.dumps(result) and "config" not in result["items"][0]["source"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "revoked", "wrong_type"])
async def test_unavailable_authority_refuses_before_http(local, case):
    if case == "missing": local.allowed = False
    if case == "revoked": local.row["revoked_at"] = UPDATED
    if case == "wrong_type": local.row["credential_type"] = "airbyte_api_key"
    try:
        assert (await run(local))["category"] == "authority"
    except ValueError:
        pass
    assert not local.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["pending", "rejected"])
async def test_actual_admission_collector_does_not_invent_execution(local, pending):
    local.pending = {"id": "fixture-approval", "status": pending, "new_request": False}
    assert (await run(local))["executed"] is False
    evidence = await connection_evidence.collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=local.pool, organization_id=ORG)
    assert evidence.reachable is None and evidence.samples == []
    assert not local.requests


@pytest.mark.asyncio
async def test_actual_empty_connect_and_serialized_evidence_is_not_human_identity(local, monkeypatch):
    local.payload = {"data": []}
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type="hevo_api_key", credential_data=local.blob,
        user_id=USER, pool=local.pool, organization_id=ORG)
    assert verdict.ok and verdict.evidence.reachable is True and verdict.evidence.account_label is None
    from wss.sender.responses import CredentialTestConnectionResponse
    serialized = CredentialTestConnectionResponse.from_evidence(verdict.evidence, proves=native.HevoNode.connection_evidence.proves).model_dump()
    assert serialized["proves"] == "reachability" and serialized["account_label"] is None


@pytest.mark.asyncio
async def test_saved_hook_and_socket_picker_ignore_caller_region_and_auth(local):
    assert (await validate(local))["valid"] is True
    result = await pick(local, context={"region": "us", "api_secret": "caller-secret", "base_url": "https://private.example"})
    assert result["options"][0]["value"] == "7" and result["options"][0]["metadata"]["region"] == "eu"
    assert all(r.url.host == "eu.hevodata.com" for r in local.requests)
    local.blob["credential_type"] = "airbyte_api_key"
    local.requests.clear()
    await pick(local)
    assert not local.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "key", "secret", "region", "access"])
async def test_saved_current_authority_races_reject_after_read(local, change):
    def mutation():
        if change == "revoked": local.row["revoked_at"] = UPDATED
        if change == "key": local.blob["api_key"] = "changed-synthetic"
        if change == "secret": local.blob["api_secret"] = "changed-synthetic"
        if change == "region": local.blob["region"] = "us"
        if change == "access": local.allowed = False
    local.mutation = mutation
    assert (await run(local))["category"] == "authority" and len(local.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["malformed", "outage", "accepted", "shape", "provider_error"])
async def test_ambiguous_read_unknown_and_private_error_body_omitted(local, case):
    if case == "malformed": local.raw = b"{broken"
    if case == "outage": local.status = 503
    if case == "accepted": local.status = 202
    if case == "shape": local.payload = {"data": "private-provider-fixture"}
    if case == "provider_error": local.payload = {"success": False, "error_code": 42, "error_message": "synthetic:secret"}
    result = await validate(local)
    assert result["valid"] is None and "private-provider-fixture" not in json.dumps(result) and "synthetic:secret" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,body", [("set_pipeline_state", {"state": "PAUSED"}, {"state": "PAUSED"}),
    ("update_pipeline_priority", {"priority": "HIGH"}, {"priority": "HIGH"}),
    ("update_pipeline_schedule", {"frequency": 900}, {"frequency": 900})])
async def test_lifecycle_closed_put204_and_same_pipeline_readback(local, operation, arguments, body):
    result = await run(local, operation, pipeline_id="7", **arguments)
    assert result["status"] == "success" and result["acknowledged"] is True and result["readback_performed"] is True
    assert [r.method for r in local.requests] == ["GET", "PUT", "GET"]
    assert json.loads(local.requests[1].content) == body and "private-" not in json.dumps(result)


@pytest.mark.asyncio
async def test_frequency_current_bounds_and_preflight_authority_loss_prevent_put(local):
    assert (await run(local, "update_pipeline_schedule", pipeline_id="7", frequency=100))["mutation_outcome"] == "not_attempted"
    assert [r.method for r in local.requests] == ["GET"]
    local.requests.clear()
    local.mutation = lambda: setattr(local, "allowed", False)
    assert (await run(local, "set_pipeline_state", pipeline_id="7", state="PAUSED"))["mutation_outcome"] == "not_attempted"
    assert [r.method for r in local.requests] == ["GET"]


@pytest.mark.asyncio
async def test_conflict_async_and_failed_readback_are_unverified_without_retry(local):
    for status in (409, 202):
        local.method_status["PUT"] = status
        local.requests.clear()
        result = await run(local, "set_pipeline_state", pipeline_id="7", state="PAUSED")
        assert result["status"] == "error" and result["mutation_outcome"] == "unverified" and len(local.requests) == 2
    local.method_status.clear()
    local.ignore_update = True
    result = await run(local, "update_pipeline_priority", pipeline_id="7", priority="HIGH")
    assert result["mutation_outcome"] == "unverified"


@pytest.mark.asyncio
async def test_actual_agent_selected_pipeline_scope_blocks_before_lifecycle(local):
    from nodes.agent.tool_execution import _execute_node_op_tool
    agent = SimpleNamespace(user_id=USER, organization_id=ORG, workflow_id=None, conversation_id="fixture-conversation")
    tool = {"node_type": NODE, "operation": "list_pipelines", "credential_id": CID}
    assert (await _execute_node_op_tool(agent, "hevo_pipelines", {}, tool, []))["status"] == "success"
    result = await _execute_node_op_tool(agent, "hevo_pause", {"pipeline_id": "7", "state": "PAUSED"},
        {**tool, "operation": "set_pipeline_state", "field_scopes": {"pipeline_id": ["8"]}}, [])
    assert result["success"] is False and len(local.requests) == 1


@pytest.mark.asyncio
async def test_canonical_authorized_workflow_owner_fallback_and_withdrawal(local, monkeypatch):
    owner = "fixture-workflow-owner"
    local.allowed_users, local.row["owner_id"] = {owner}, owner
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value=owner))
    authorized = AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", authorized)
    async def workflow_run(operation, arguments):
        return await run_op.run_node_operation(node_type=NODE, operation=operation, arguments=arguments,
            user_id=USER, pool=local.pool, credential_id=CID, organization_id=ORG, workflow_id="fixture-workflow")
    assert (await workflow_run("list_pipelines", {}))["status"] == "success"
    authorized.assert_awaited_with(local.pool, "fixture-workflow", CID)
    local.mutation = lambda: setattr(authorized, "return_value", False)
    result = await workflow_run("set_pipeline_state", {"pipeline_id": "7", "state": "PAUSED"})
    assert result["category"] == "authority" and result["mutation_outcome"] == "not_attempted"


@pytest.mark.asyncio
async def test_cursor_exact_count_absence_and_no_url_following(local):
    local.payload = {"data": [PIPELINE], "pagination": {"count": 1, "starting_after": "Nw=="}}
    result = await run(local, starting_after="Ng==", limit=1)
    assert result["has_more"] is True and result["next_starting_after"] == "Nw=="
    assert dict(local.requests[-1].url.params) == {"limit": "1", "starting_after": "Ng=="}
    local.payload["pagination"]["starting_after"] = "Ng=="
    assert (await run(local, starting_after="Ng=="))["category"] == "protocol"
    local.payload = [PIPELINE]
    assert (await run(local))["has_more"] is False


@pytest.mark.asyncio
async def test_selected_source_object_table_stats_schedule_and_workflow_privacy(local):
    assert (await run(local, "get_pipeline_source", pipeline_id="7"))["source"]["name"] == "Fixture source"
    assert (await run(local, "get_pipeline_schedule", pipeline_id="7"))["schedules"][0]["type"] == "FREQUENCY"
    obj = await run(local, "get_pipeline_object", pipeline_id="7", object_name="public.orders")
    assert obj["record"] == {key: OBJECT[key] for key in ("name", "status", "last_run_ts")}
    stats = await run(local, "get_destination_table_stats", destination_id="8", table_name="public.orders")
    assert stats["items"] == [{"stage": "LOADED", "count": 42}] and dict(local.requests[-1].url.params) == {"duration": "120"}
    assert "private-" not in json.dumps(await run(local, "get_workflow", workflow_id="9"))


@pytest.mark.asyncio
async def test_supplied_credential_lifecycle_and_undocumented_operations(local):
    node = registry.NodeFactory.create_node(node_id="fixture", node_type=NODE, node_data={
        "config": {"operation": "set_pipeline_state", "pipeline_id": "7", "state": "PAUSED"}, "credentials": local.blob}, user_id=USER, organization_id=ORG)
    assert (await node.execute({}))["acknowledged"] is True
    assert [r.method for r in local.requests] == ["GET", "PUT", "GET"]
    local.requests.clear()
    for op, data in [("get_pipeline", {"pipeline_id": "../sources"}), ("get_pipeline_object", {"pipeline_id": "7", "object_name": "../query"}),
        ("update_pipeline_schedule", {"pipeline_id": "7", "frequency": 900, "source_config": {"password": "private"}}),
        ("run_pipeline", {}), ("restart_pipeline_object", {}), ("run_workflow", {}), ("create_destination", {}), ("generic_request", {})]:
        with pytest.raises(ValueError):
            await run(local, op, **data)
    assert not local.requests
