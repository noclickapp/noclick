"""UNRUN real connect/factory/current-row/access/admission/socket/Agent seams.

Only SQL I/O, decrypt, HTTP transport and event delivery are fixtures. Actual
repositories, authority snapshots, native hooks and dispatch stay production.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from nodes import bloomerang_node as bm
from nodes.core import credential_connect as cc
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation, run_node_lookup
from repositories.credentials import credential_access_predicate
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

NODE = "automation-bloomerang"
USER, ORG, CID = ("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002", "00000000-0000-4000-8000-000000000042")
KEY = "synthetic-bloomerang-key-not-live"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    yield


class Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_):
        return False


class Storage:
    def __init__(self):
        self.row = {"id": CID, "name": "Fixture CRM", "credential": b"synthetic-encrypted", "credential_type": bm.TYPE, "owner_id": USER, "token_version": 7, "approval_revision": 0, "updated_at": UPDATED, "created_at": UPDATED, "revoked_at": None, "metadata": {}, "approval_operations": []}
        self.blob = {"credential_type": bm.TYPE, "api_key": KEY}
        self.allowed, self.calls, self.approval_status = True, [], None

    def acquire(self):
        return Context(self)

    def transaction(self):
        return Context(self)

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        if "organizations" in sql or "org_members" in sql or "organization_members" in sql:
            return ORG
        if "count(*) FROM approval_requests" in sql:
            return 0
        raise AssertionError("Unexpected native fetchval")

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "SELECT name,owner_id,approval_operations" in sql:
            assert args == (CID,) and "FOR UPDATE" in sql
            return deepcopy(self.row)
        if "SELECT id,status,consumed_at,expires_at" in sql:
            return {"id": UUID(int=99), "status": self.approval_status, "consumed_at": None, "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc)} if self.approval_status else None
        if "FROM credentials c" in sql:
            assert credential_access_predicate().strip() in sql and args[0] == CID and args[1] == USER
            if len(args) == 6:
                assert args[3] == USER and "workflow_authorized_credentials" in sql
            assert len(args) in {3, 6}
            return deepcopy(self.row) if self.allowed else None
        raise AssertionError("Unexpected native fetchrow")


def database():
    return {"Id": "fixture-database", "Name": "Fixture Organization"}


def current_user():
    return {"Id": 7, "Name": "Actual Key User", "IsActive": True, "PermissionLevel": "Admin"}


def binding():
    return [(200, database()), (200, current_user())]


def constituent(identifier=42, name="Fixture Constituent"):
    return {"Id": identifier, "AccountNumber": 9000, "Type": "Organization", "FullName": name}


def page(rows, *, start=0, total=None):
    return {"Total": len(rows) if total is None else total, "TotalFiltered": len(rows) if total is None else total, "Start": start, "ResultCount": len(rows), "Results": rows}


@pytest.fixture
def harness(monkeypatch):
    from utils import credentials
    from wss.handlers import credentials_handler, workflow_handler
    state = SimpleNamespace(storage=Storage(), http=[], replies=[], events=[], after_http=None)
    encryption = MagicMock()
    encryption.decrypt_credential.side_effect = lambda _: deepcopy(state.storage.blob)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: encryption)
    monkeypatch.setattr(credentials, "get_encryption", lambda: encryption)
    monkeypatch.setattr(credentials_handler, "get_encryption", lambda: encryption)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credentials_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)

    async def send(request):
        state.http.append(request)
        if state.after_http:
            state.after_http(len(state.http))
        assert request.url.host == "api.bloomerang.co" and request.headers["X-API-KEY"] == KEY
        code, payload = state.replies.pop(0)
        return httpx.Response(code, json=payload)

    native = httpx.AsyncClient
    monkeypatch.setattr(bm, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)), HTTPError=httpx.HTTPError, Timeout=httpx.Timeout))

    async def capture(sio, sid, response):
        state.events.append(response.model_dump())

    monkeypatch.setattr(credentials_handler, "send_event", capture)
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    sio = AsyncMock()
    sio.get_session.return_value = {"user_id": USER}
    state.access = credentials_handler.CredentialsHandler(sio)
    state.picker = workflow_handler.WorkflowHandler(sio)
    monkeypatch.setattr(state.access, "get_pool", AsyncMock(return_value=state.storage))
    monkeypatch.setattr(state.picker, "get_pool", AsyncMock(return_value=state.storage))
    return state


@pytest.mark.asyncio
async def test_actual_manual_connect_shapes_private_key_and_exact_current_identity(harness):
    harness.replies = binding()
    verdict = await cc.validate_for_connect(credential_type=bm.TYPE, credential_data={"api_key": KEY}, user_id=USER, probe=True)
    assert verdict.field_errors == {} and verdict.credential_data == harness.storage.blob
    assert verdict.evidence.reachable is True and verdict.evidence.samples[0].label == "Actual Key User"
    assert [r.url.path for r in harness.http] == ["/v2/database", "/v2/user/current"]


@pytest.mark.parametrize("row_type", [None, "bloomerang_public_key", "slack_bot_token", "", 42])
@pytest.mark.asyncio
async def test_actual_null_foreign_or_malformed_authoritative_row_cannot_use_private_blob(harness, row_type):
    harness.storage.row["credential_type"] = row_type
    with pytest.raises((ValueError, TypeError)):
        await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert harness.http == []
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is False and harness.http == []


@pytest.mark.asyncio
async def test_saved_factory_and_actual_post_connect_native_context_positive(harness):
    harness.replies = binding()
    result = await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert result["status"] == "success" and result["identity_verified"] is True
    assert any(len(args) == 6 for _, args in harness.storage.calls)
    harness.replies = binding()
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is True and harness.events[-1]["data"]["identity_verified"] is True


@pytest.mark.parametrize("change", ["owner", "version", "type", "revoked", "acl", "revision", "key"])
@pytest.mark.asyncio
async def test_actual_current_authority_race_after_http_never_finishes_success(harness, change):
    def mutate(_):
        row = harness.storage.row
        if change == "owner": row["owner_id"] = "00000000-0000-4000-8000-000000000099"
        if change == "version": row["token_version"] += 1
        if change == "type": row["credential_type"] = "bloomerang_public_key"
        if change == "revoked": row["revoked_at"] = UPDATED
        if change == "acl": harness.storage.allowed = False
        if change == "revision": row["approval_revision"] += 1
        if change == "key": harness.storage.blob["api_key"] = "changed-key"
    harness.after_http = mutate
    harness.replies = [(200, database())]
    with pytest.raises(ValueError):
        await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert len(harness.http) == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
@pytest.mark.asyncio
async def test_actual_admission_parks_native_run_lookup_and_identity_evidence(harness, status):
    harness.storage.row["approval_operations"] = ["*"]
    harness.storage.approval_status = status
    result = await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert result["executed"] is False and result["status"] == ("pending_approval" if status == "pending" else "rejected")
    lookup = await run_node_lookup(node_type=NODE, field_name="constituent_id", user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert lookup["executed"] is False
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=harness.storage, organization_id=ORG)
    assert evidence.reachable is None and harness.http == []


@pytest.mark.asyncio
async def test_actual_socket_picker_uses_api_ids_and_refuses_foreign_row(harness):
    harness.replies = binding() + [(200, page([constituent()]))]
    await harness.picker.load_node_options("fixture", WorkflowNodeLoadOptionsRequest(request_id="fixture", node_type=NODE, field_name="constituent_id", credential_id=CID, context={}))
    assert harness.events[-1]["data"]["options"] == [{"label": "Fixture Constituent", "value": "42"}]
    count = len(harness.http)
    harness.storage.row["credential_type"] = "slack_bot_token"
    await harness.picker.load_node_options("fixture", WorkflowNodeLoadOptionsRequest(request_id="fixture", node_type=NODE, field_name="constituent_id", credential_id=CID, context={}))
    assert harness.events[-1]["data"]["success"] is False and len(harness.http) == count


@pytest.mark.asyncio
async def test_handler_refusal_unknown_status_and_no_context_keep_tri_state(harness):
    harness.replies = [(403, {"error": "Do not expose"})]
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is False
    harness.replies = [(202, database())]
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is None and harness.events[-1]["data"]["identity_verified"] is False
    assert (await bm.BloomerangNode.validate_credential_access(harness.storage.blob))["valid"] is None


@pytest.mark.asyncio
async def test_actual_parent_lookup_missing_context_refused_before_provider(harness):
    with pytest.raises(ValueError):
        await run_node_lookup(node_type=NODE, field_name="note_id", context={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert harness.http == []


@pytest.mark.asyncio
async def test_actual_stored_parent_lookup_searches_later_offset_without_broadening(harness):
    note1 = {"Id": 43, "AccountId": 42, "Date": "2026-10-05", "Note": "First"}
    note2 = {"Id": 44, "AccountId": 42, "Date": "2026-10-06", "Note": "Target"}
    harness.replies = binding() + [(200, constituent()), (200, page([note1], total=2)), (200, page([note2], start=1, total=2))]
    result = await run_node_lookup(node_type=NODE, field_name="note_id", context={"constituent_id": "42", "search": "2026-10-06"}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert result["options"] == [{"value": "44", "label": "2026-10-06", "metadata": {"database_id": "fixture-database", "constituent_id": "42"}}] and result["next_page_token"] is None
    assert harness.http[-1].url.params["skip"] == "1" and harness.http[-1].url.params["constituent"] == "42"


@pytest.mark.asyncio
async def test_actual_agent_tools_refuse_outside_parent_allowlist_before_i_o(harness):
    from nodes.agent.node_op_tools import build_node_op_tools, resource_creators
    from nodes.agent.tool_execution import _execute_node_op_tool, _execute_node_op_lookup
    tools, configs = build_node_op_tools(NODE, [{"operation": "get_note", "field_scopes": {"constituent_id": ["42"], "note_id": ["43"]}}, "create_note"], node_id="provider", credential_id=CID)
    action = next(name for name, info in configs.items() if info.get("operation") == "get_note")
    definition = next(tool for tool in tools if tool["function"]["name"] == action)
    assert definition["function"]["parameters"]["properties"]["constituent_id"]["enum"] == ["42"]
    assert resource_creators(NODE) == ()
    refused = await _execute_node_op_tool(SimpleNamespace(user_id=USER, organization_id=ORG, workflow_id=None), action, {"constituent_id": "99", "note_id": "43"}, configs[action], configs)
    assert refused["success"] is False and "restricted" in refused["error"] and harness.http == []
    lookup = next(name for name, info in configs.items() if info.get("tool_type") == "node_op_lookup")
    missing = await _execute_node_op_lookup(SimpleNamespace(user_id=USER, organization_id=ORG, workflow_id=None), lookup, {"field": "note_id", "context": {}}, configs[lookup])
    assert missing["success"] is False and "parent" in missing["error"] and harness.storage.calls == []
