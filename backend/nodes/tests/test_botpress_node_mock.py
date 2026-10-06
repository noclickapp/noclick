"""Unrun Botpress native factory, current-row, connect and picker fixtures.

Storage/encryption and HTTP boundaries are synthetic; no account, entitlement,
provider execution, generator or real UI proof is established by this source.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import botpress_node as native
from nodes.core import credential_connect, connection_evidence, registry, run_op
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, encryption
from wss.handlers import credentials_handler, workflow_handler
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

NODE = "automation-botpress"
USER, ORG = "botpress-fixture-user", "botpress-fixture-org"
CID = "00000000-0000-4000-8000-000000000042"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
OPS = {"get_workspace", "list_bots", "get_bound_bot", "list_tables", "get_table", "create_table",
    "delete_table", "find_rows", "get_row", "create_rows", "update_rows", "delete_rows", "list_files", "get_file"}
BOT = {"id": "bot_fixture", "name": "Synthetic bot", "type": "studio", "configuration": {"private": "fixture"},
    "signingSecret": "private-fixture-signing", "secrets": {"key": "private-fixture"}}
TABLE = {"id": "table_fixture", "name": "FixtureTable", "factor": 1, "isComputeEnabled": False,
    "schema": {"type": "object", "additionalProperties": True,
        "properties": {"name": {"type": "string", "x-zui": {"index": 0}}, "count": {"type": "number", "x-zui": {"index": 1}}}}}
FILE = {"id": "file_fixture", "botId": "bot_fixture", "key": "Fixture.txt", "size": 7,
    "contentType": "text/plain", "status": "upload_completed", "url": "https://private.example/signed",
    "metadata": {"private": "fixture"}, "accessPolicies": ["private"], "owner": {"id": "private-user"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def local(monkeypatch):
    state = SimpleNamespace(row={"id": CID, "name": "Synthetic Botpress", "credential_type": "botpress_pat",
        "credential": b"synthetic-encrypted", "metadata": {}, "owner_id": USER, "token_version": 7,
        "approval_revision": 0, "created_at": UPDATED, "updated_at": UPDATED, "revoked_at": None},
        blob={"credential_type": "botpress_pat", "workspace_id": "workspace_fixture", "bot_id": "bot_fixture",
            "personal_access_token": "synthetic-botpress-token"}, allowed=True, requests=[], queries=[], responses=[],
        pending=None, status=200, payload={"bots": [], "meta": {}}, bot_payload={"bot": deepcopy(BOT)},
        table_payload={"table": deepcopy(TABLE), "rows": 0, "stale": 0, "indexing": 0},
        raw=None, mutation=None, content_type="application/json")

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, sql, credential_id, user_id, org_id):
            assert "FROM credentials c" in sql and credential_id == CID
            assert (user_id, org_id) == (USER, ORG)
            state.queries.append(sql)
            return deepcopy(state.row) if state.allowed else None

    state.pool = Pool()
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    for module in (credentials, encryption, credentials_handler, workflow_handler):
        monkeypatch.setattr(module, "get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: state.pool)
    monkeypatch.setattr(credentials, "get_native_pool", lambda: state.pool)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credentials_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    state.admit = AsyncMock(side_effect=lambda **_: state.pending)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", state.admit)

    def transport(request):
        state.requests.append(request)
        if state.mutation:
            state.mutation()
        if state.raw is not None:
            return httpx.Response(state.status, content=state.raw, headers={"Content-Type": state.content_type})
        payload = (state.bot_payload if request.url.path == "/v1/admin/bots/bot_fixture" else
            state.table_payload if request.method == "GET" and request.url.path == "/v1/tables/table_fixture" else state.payload)
        return httpx.Response(state.status, json=payload)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    state.handler = credentials_handler.CredentialsHandler(sio)
    state.handler.get_pool = AsyncMock(return_value=state.pool)
    state.picker = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    state.picker.sio = sio
    state.picker.get_pool = AsyncMock(return_value=state.pool)

    async def capture(_sio, sid, event, **_):
        assert sid == "fixture-sid"
        state.responses.append(event.model_dump())

    monkeypatch.setattr(credentials_handler, "send_event", capture)
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    return state


async def run(local, operation="list_bots", **arguments):
    return await run_op.run_node_operation(node_type=NODE, operation=operation, arguments=arguments,
        user_id=USER, pool=local.pool, credential_id=CID, organization_id=ORG)


async def validate(local):
    request = CredentialValidateAccessRequest(request_id="fixture-validation", node_type=NODE, credential_id=CID)
    await local.handler.get_events()[request.event_name]("fixture-sid", request)
    return local.responses[-1]["data"]


async def pick(local, **kwargs):
    request = WorkflowNodeLoadOptionsRequest(request_id="fixture-picker", node_type=NODE,
        field_name="table", credential_id=CID, **kwargs)
    await local.picker.get_events()[request.event_name]("fixture-sid", request)
    return local.responses[-1]["data"]


def test_actual_factory_catalog_discriminator_and_hidden_pat():
    from coder.workflow.operation_catalog import get_operations_for_node_type, node_accepted_credential_types
    from nodes.agent.node_op_tools import node_supports_op_tools
    assert registry.NODE_REGISTRY[NODE] is native.BotpressNode
    assert {o.name for o in get_operations_for_node_type(NODE)} == OPS
    assert node_accepted_credential_types(NODE) == {"botpress_pat"} and node_supports_op_tools(NODE)
    schema = native.BotpressNode.get_config_schema()
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == OPS
    credential = schema["$defs"]["BotpressPATCredential"]
    assert set(credential["required"]) == {"workspace_id", "bot_id", "personal_access_token"}
    assert credential["properties"]["personal_access_token"]["ui:widget"] == "password"
    assert native.BotpressNode.connection_evidence.identity_operation is None
    assert native.BotpressNode.connection_evidence.proves == "reachability"
    assert "synthetic-hidden" not in repr(native.BotpressPATCredential(workspace_id="workspace_fixture", bot_id="bot_fixture", personal_access_token="synthetic-hidden"))


@pytest.mark.parametrize("data", [{"workspace_id": "../admin", "bot_id": "bot_fixture", "personal_access_token": "synthetic"},
    {"workspace_id": "workspace_fixture", "bot_id": "bot_fixture", "personal_access_token": "synthetic\r\nheader"},
    {"workspace_id": "workspace_fixture", "personal_access_token": "synthetic"}])
def test_actual_connect_shape_rejects_unbound_credentials(data):
    _, errors, resolved = credential_connect.shape_credential("botpress_pat", data)
    assert errors and resolved[0] == NODE


@pytest.mark.asyncio
async def test_current_row_type_overrides_blob_and_native_scope_headers(local):
    local.blob["credential_type"] = "stale-blob-tag"
    result = await run(local)
    assert result["status"] == "success" and result["bots"] == []
    request = local.requests[-1]
    assert str(request.url).startswith(native.ORIGIN + "/v1/admin/bots?")
    assert request.headers["Authorization"] == "Bearer synthetic-botpress-token"
    assert request.headers["x-workspace-id"] == "workspace_fixture" and "x-bot-id" not in request.headers
    assert dict(request.url.params) == {"dev": "false", "sortField": "createdAt", "sortDirection": "asc"}
    assert len(local.queries) >= 3
    local.payload = {"tables": [deepcopy(TABLE)]}
    result = await run(local, "list_tables")
    assert result["pagination"] == "unpaginated"
    assert local.requests[-2].headers["x-workspace-id"] == "workspace_fixture"
    assert local.requests[-1].headers["x-bot-id"] == "bot_fixture" and not local.requests[-1].url.query
    assert "x-user-role" not in local.requests[-1].headers and "x-user-id" not in local.requests[-1].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "revoked", "wrong_type"])
async def test_authority_refusal_before_transport(local, case):
    if case == "missing": local.allowed = False
    if case == "revoked": local.row["revoked_at"] = UPDATED
    if case == "wrong_type": local.row["credential_type"] = "other_provider"
    try:
        result = await run(local)
        assert result["category"] == "authority"
    except ValueError:
        pass
    assert not local.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["pending", "rejected"])
async def test_actual_admission_collector_and_saved_hook_nonexecution(local, pending):
    local.pending = {"id": "fixture-approval", "status": pending, "new_request": False}
    assert (await run(local))["executed"] is False
    evidence = await connection_evidence.collect_evidence(node_type=NODE, credential_id=CID,
        user_id=USER, pool=local.pool, organization_id=ORG)
    assert evidence.reachable is None and evidence.samples == []
    saved = await validate(local)
    assert saved["valid"] is False and saved["status"] in {"pending", "pending_approval", "rejected"}
    assert not local.requests


@pytest.mark.asyncio
async def test_actual_manual_connect_completed_bot_read_reachability_not_identity(local, monkeypatch):
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type="botpress_pat", credential_data=local.blob,
        user_id=USER, pool=local.pool, organization_id=ORG)
    assert verdict.ok and verdict.evidence.reachable is True and verdict.evidence.account_label is None
    from wss.sender.responses import CredentialTestConnectionResponse
    serialized = CredentialTestConnectionResponse.from_evidence(verdict.evidence).model_dump()
    assert serialized["proves"] == "reachability" and serialized["account_label"] is None
    assert "private-fixture" not in json.dumps(serialized)


@pytest.mark.asyncio
async def test_saved_hook_and_actual_socket_picker_ignore_caller_scope(local):
    assert (await validate(local))["valid"] is True
    local.payload = {"tables": [deepcopy(TABLE)]}
    options = await pick(local, search="Fixture", context={"bot_id": "caller_bot", "workspace_id": "caller_workspace", "personal_access_token": "caller_token"})
    assert options["options"][0]["value"] == "table_fixture"
    assert options["options"][0]["metadata"]["bot_id"] == "bot_fixture"
    assert local.requests[-1].headers["Authorization"] == "Bearer synthetic-botpress-token"
    local.row["credential_type"] = "other_provider"
    local.requests.clear()
    await pick(local)
    assert not local.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "revoked", "token", "workspace", "bot", "access"])
async def test_saved_hook_current_authority_races(local, change):
    def mutation():
        if change == "owner": local.row["owner_id"] = "changed-owner"
        if change == "revoked": local.row["revoked_at"] = UPDATED
        if change == "token": local.blob["personal_access_token"] = "changed-synthetic-token"
        if change == "workspace": local.blob["workspace_id"] = "changed_workspace"
        if change == "bot": local.blob["bot_id"] = "changed_bot"
        if change == "access": local.allowed = False
        if change in {"token", "workspace", "bot"}: local.row["token_version"] += 1
    local.mutation = mutation
    result = await validate(local)
    assert result["valid"] is False and len(local.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["malformed", "outage", "accepted", "wrong_bot"])
async def test_saved_ambiguous_probe_retains_unknown_and_private_diagnostics(local, case):
    if case == "malformed": local.raw = b"{broken"
    if case == "outage": local.status = 503
    if case == "accepted": local.status = 202
    if case == "wrong_bot": local.bot_payload = {"bot": {**BOT, "id": "different_bot"}}
    result = await validate(local)
    assert result["valid"] is None and "private-fixture" not in json.dumps(result)


@pytest.mark.asyncio
async def test_actual_agent_dispatch_refuses_outside_selected_table_scope(local):
    from nodes.agent.tool_execution import _execute_node_op_tool
    agent = SimpleNamespace(user_id=USER, organization_id=ORG, workflow_id=None, conversation_id="fixture-conversation")
    tool = {"node_type": NODE, "operation": "list_bots", "credential_id": CID}
    assert (await _execute_node_op_tool(agent, "botpress_list_bots", {}, tool, []))["status"] == "success"
    result = await _execute_node_op_tool(agent, "botpress_delete_table", {"table": "table_fixture", "confirm_delete": True},
        {**tool, "operation": "delete_table", "field_scopes": {"table": ["other_table"]}}, [])
    assert result["success"] is False and len(local.requests) == 1


@pytest.mark.asyncio
async def test_bound_membership_loss_prevents_data_or_write_transport(local):
    local.mutation = lambda: setattr(local, "allowed", False)
    result = await run(local, "delete_table", table="table_fixture", confirm_delete=True)
    assert result["category"] == "authority" and result["mutation_outcome"] == "not_attempted"
    assert len(local.requests) == 1 and local.requests[0].url.path.startswith("/v1/admin/bots/")


@pytest.mark.asyncio
async def test_find_select_offset_and_get_row_documented_query_private_projection(local):
    local.payload = {"rows": [{"id": 7, "name": "Synthetic row", "password": "private", "computed": {"name": {"error": "private"}}, "nested": {"private": 1}}],
        "hasMore": True, "offset": 0, "limit": 1, "warnings": ["private warning"]}
    result = await run(local, "find_rows", table="table_fixture", columns=["name"], limit=1)
    assert result["next_offset"] == 1 and result["rows"] == [{"id": 7, "name": "Synthetic row"}]
    assert json.loads(local.requests[-1].content) == {"limit": 1, "offset": 0, "select": ["name"], "orderBy": "id", "orderDirection": "asc"}
    local.payload = {"row": {"id": 7, "name": "Synthetic row", "password": "private"}}
    result = await run(local, "get_row", table="table_fixture", columns=["name"], row_id=7)
    assert result["row"] == {"id": 7, "name": "Synthetic row"}
    assert local.requests[-1].url.path == "/v1/tables/table_fixture/row" and local.requests[-1].url.params["id"] == "7"


@pytest.mark.asyncio
async def test_exact_plain_table_create_and_partial_rows_no_echo_or_retry(local):
    local.payload = {"table": deepcopy(TABLE)}
    result = await run(local, "create_table", name="FixtureTable", columns=[{"name": "name", "value_type": "string"}])
    assert result["status"] == "success"
    body = json.loads(local.requests[-1].content)
    assert body["factor"] == 1 and body["isComputeEnabled"] is False
    assert body["schema"]["properties"] == {"name": {"type": "string", "x-zui": {"index": 0}}}
    local.payload = {"rows": [{"id": 7, "name": "private echo"}], "errors": ["private error"], "warnings": ["private warning"]}
    result = await run(local, "update_rows", table="table_fixture", rows=[{"row_id": 7, "values": {"name": "Synthetic"}}])
    assert result["status"] == "partial" and result["rows"] == [{"id": 7}] and result["error_count"] == 1
    assert json.loads(local.requests[-1].content) == {"rows": [{"id": 7, "name": "Synthetic"}], "waitComputed": False}
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["compute", "searchable", "different_table", "wrong_column"])
async def test_write_preflight_refuses_compute_wrong_binding_and_silent_fields(local, case):
    if case == "compute": local.table_payload["table"]["isComputeEnabled"] = True
    if case == "searchable": local.table_payload["table"]["schema"]["properties"]["name"]["x-zui"]["searchable"] = True
    if case == "different_table": local.table_payload["table"].update(id="other_table", name="OtherTable")
    values = {"missing": "Synthetic"} if case == "wrong_column" else {"name": "Synthetic"}
    result = await run(local, "create_rows", table="table_fixture", rows=[{"values": values}])
    assert result["status"] == "error" and result["mutation_outcome"] == "not_attempted"
    assert len(local.requests) == 2 and all(r.method == "GET" for r in local.requests)


@pytest.mark.asyncio
async def test_delete_explicit_ids_async_unknown_and_exact_table_receipt(local):
    local.payload = {"deletedRows": 0, "job": {"id": "job_fixture", "status": "pending"}}
    result = await run(local, "delete_rows", table="table_fixture", row_ids=[7])
    assert result["status"] == "accepted" and result["mutation_outcome"] == "unverified"
    assert json.loads(local.requests[-1].content) == {"ids": [7]}
    local.payload = {}
    assert (await run(local, "delete_table", table="table_fixture", confirm_delete=True))["acknowledged"] is True
    assert local.requests[-1].method == "DELETE"


@pytest.mark.asyncio
async def test_file_cursor_and_projection_no_signed_asset_or_privileges(local):
    local.payload = {"files": [deepcopy(FILE)], "meta": {"nextToken": "opaque+next="}}
    result = await run(local, "list_files")
    assert result["next_token"] == "opaque+next=" and "url" not in result["files"][0]
    assert set(result["files"][0]).isdisjoint({"metadata", "tags", "accessPolicies", "owner"})
    local.payload = {"file": deepcopy(FILE)}
    assert (await run(local, "get_file", file_id="file_fixture"))["file"]["id"] == "file_fixture"
    local.payload["file"]["botId"] = "other_bot"
    assert (await run(local, "get_file", file_id="file_fixture"))["category"] == "protocol"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,category", [(401, "authentication"), (403, "permission"), (429, "rate_limit"), (202, "protocol"), (204, "protocol")])
async def test_http_refusal_private_diagnostics_no_retry(local, status, category):
    local.status = status
    local.payload = {"message": "private token synthetic-botpress-token"}
    result = await run(local)
    assert result["category"] == category and len(local.requests) == 1
    assert "synthetic-botpress-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_native_hazardous_and_malformed_inputs_refuse_before_requests(local):
    for op, arguments in [("delete_rows", {"table": "table_fixture", "row_ids": []}),
        ("delete_rows", {"table": "table_fixture", "row_ids": [True]}),
        ("find_rows", {"table": "../admin", "columns": ["name"]}),
        ("find_rows", {"table": "table_fixture", "columns": ["api_token"]}),
        ("create_rows", {"table": "table_fixture", "rows": [{"values": {"name": {"nested": "value"}}}]}),
        ("send_message", {}), ("deploy_bot", {}), ("generic_request", {}), ("index_file", {})]:
        with pytest.raises(ValueError):
            await run(local, op, **arguments)
    assert not local.requests
