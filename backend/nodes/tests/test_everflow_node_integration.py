"""Real staging factory/connect/current-row/admission/socket fixtures.

SQL, encryption, provider transport and socket delivery are synthetic I/O.
Canonical repositories, authority store, handlers, node and admission execute;
this does not execute database ACLs, provider permissions or live workflows.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from nodes import everflow_node as ef
from nodes.core import credential_connect as cc
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation, run_node_lookup
from repositories.credentials import credential_access_predicate
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

NODE = "automation-everflow"
USER = "00000000-0000-4000-8000-000000000001"
ORG = "00000000-0000-4000-8000-000000000002"
CID = "00000000-0000-4000-8000-000000000042"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
KEY = "synthetic-everflow-key-not-live"


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
        self.row = {"id": CID, "name": "Fixture key", "credential": b"synthetic-encrypted", "credential_type": "everflow_network_api_key", "owner_id": USER, "token_version": 7, "approval_revision": 0, "updated_at": UPDATED, "created_at": UPDATED, "revoked_at": None, "metadata": {}, "approval_operations": []}
        self.blob = {"credential_type": "everflow_network_api_key", "api_key": KEY, "network_id": "1"}
        self.allowed = True
        self.calls = []
        self.approval_status = None
        self.approval_payload = None

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
        from repositories.organization import PRIMARY_ORG_SQL
        if sql == PRIMARY_ORG_SQL:
            assert args == (USER,)
            return {"organization_id": ORG}
        if "SELECT name,owner_id,approval_operations" in sql:
            assert args == (CID,) and "FOR UPDATE" in sql
            return deepcopy(self.row)
        if "SELECT id,status,consumed_at,expires_at" in sql:
            self.approval_payload = args
            return {"id": UUID(int=99), "status": self.approval_status, "consumed_at": None, "expires_at": UPDATED} if self.approval_status else None
        if "FROM credentials c WHERE c.id = $1::uuid" in sql:
            assert args == (CID,)
            return deepcopy(self.row)
        if "FROM credentials c" in sql:
            assert credential_access_predicate().strip() in sql
            assert args[0] == CID and args[1] == USER
            if len(args) == 6:
                assert args[3] == USER and "workflow_authorized_credentials" in sql
            assert len(args) in {3, 6}
            return deepcopy(self.row) if self.allowed else None
        raise AssertionError("Unexpected native fetchrow")


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
    monkeypatch.setattr(workflow_handler, "get_encryption", lambda: encryption)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credentials_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)

    async def send(request):
        state.http.append(request)
        if state.after_http:
            state.after_http(len(state.http))
        assert request.url.host == "api.eflow.team" and request.headers["X-Eflow-API-Key"] == KEY
        code, data = state.replies.pop(0)
        return httpx.Response(code, json=data)

    native_client = httpx.AsyncClient
    monkeypatch.setattr(ef, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: native_client(**kwargs, transport=httpx.MockTransport(send)), HTTPError=httpx.HTTPError, Timeout=httpx.Timeout))

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
    state.encryption = encryption
    return state


def replies():
    return [(200, {"network_id": 1, "name": "Owned network"}), (200, {"offers": [], "paging": {"page": 1, "page_size": 5, "total_count": 0}})]


@pytest.mark.asyncio
async def test_actual_connect_collector_shapes_tag_and_does_not_invent_account_identity(harness):
    harness.replies = replies()
    verdict = await cc.validate_for_connect(credential_type="everflow_network_api_key", credential_data={"api_key": KEY, "network_id": "1"}, user_id=USER, probe=True)
    assert verdict.field_errors == {} and verdict.credential_data["api_key"] == KEY
    assert verdict.evidence.reachable is True and verdict.evidence.account_label is None
    assert len(harness.http) == 2
    harness.replies = [(401, {"Error": "No authentication method found"})]
    rejected = await cc.validate_for_connect(credential_type="everflow_network_api_key", credential_data=harness.storage.blob, user_id=USER, probe=True)
    assert rejected.evidence.reachable is False and rejected.rejection


@pytest.mark.parametrize("row_type", [None, "slack_bot_token", "", 42])
@pytest.mark.asyncio
async def test_actual_current_row_foreign_null_or_malformed_cannot_use_canonical_blob(harness, row_type):
    harness.storage.row["credential_type"] = row_type
    with pytest.raises((ValueError, TypeError)):
        await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert harness.http == []
    # Staging post-connect validation receives only the decrypted blob; row
    # authority checks belong to the execution and freshen paths above.


@pytest.mark.asyncio
async def test_actual_saved_factory_run_and_handler_positive_current_row(harness):
    harness.replies = replies()
    result = await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert result["status"] == "success" and result["identity_verified"] is False
    assert any(len(args) == 3 and credential_access_predicate().strip() in sql for sql, args in harness.storage.calls)
    harness.replies = replies()
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    data = harness.events[-1]["data"]
    assert data["valid"] is True and data["identity_verified"] is False


@pytest.mark.parametrize("change", ["owner", "token", "type", "revoked", "acl", "revision", "network"])
@pytest.mark.asyncio
async def test_current_authority_race_after_provider_cannot_return_success(harness, change):
    def mutate(_):
        row = harness.storage.row
        if change == "owner": row["owner_id"] = "00000000-0000-4000-8000-000000000099"
        if change == "token": row["token_version"] += 1
        if change == "type": row["credential_type"] = "slack_bot_token"
        if change == "revoked": row["revoked_at"] = UPDATED
        if change == "acl": harness.storage.allowed = False
        if change == "revision": row["approval_revision"] += 1
        if change == "network": harness.storage.blob["network_id"] = "2"
    harness.after_http = mutate
    harness.replies = replies()
    with pytest.raises(ValueError):
        await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert len(harness.http) == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
@pytest.mark.asyncio
async def test_actual_admission_parks_factory_run_lookup_and_connect_evidence(harness, status):
    harness.storage.row["approval_operations"] = ["*"]
    harness.storage.approval_status = status
    result = await run_node_operation(node_type=NODE, operation="check_connection", arguments={}, user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert result["executed"] is False and result["status"] == ("pending_approval" if status == "pending" else "rejected")
    lookup = await run_node_lookup(node_type=NODE, field_name="offer_id", user_id=USER, credential_id=CID, pool=harness.storage, organization_id=ORG)
    assert lookup["executed"] is False
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=harness.storage, organization_id=ORG)
    assert evidence.reachable is None and harness.http == []


@pytest.mark.asyncio
async def test_real_socket_picker_uses_current_row_and_foreign_refusal(harness):
    harness.replies = [(200, {"network_id": 1}), (200, {"offers": [{"network_id": 1, "network_offer_id": 7, "name": "Visible fixture"}], "paging": {"page": 1, "page_size": 50, "total_count": 1}})]
    await harness.picker.load_node_options("fixture", WorkflowNodeLoadOptionsRequest(request_id="fixture", node_type=NODE, field_name="offer_id", credential_id=CID, context={}))
    assert harness.events[-1]["data"]["options"] == [{"label": "Visible fixture", "value": "7", "metadata": None}]
    count = len(harness.http)
    harness.storage.row["credential_type"] = "slack_bot_token"
    await harness.picker.load_node_options("fixture", WorkflowNodeLoadOptionsRequest(request_id="fixture", node_type=NODE, field_name="offer_id", credential_id=CID, context={}))
    assert harness.events[-1]["data"]["success"] is False and len(harness.http) == count


@pytest.mark.asyncio
async def test_provider_refusal_and_pending_hook_preserve_unknown_vs_false(harness):
    harness.replies = [(403, {"Error": "Out of realm"})]
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is False
    harness.replies = [(202, {"network_id": 1})]
    await harness.access.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture", credential_id=CID, node_type=NODE))
    assert harness.events[-1]["data"]["valid"] is None
    harness.replies = replies()
    direct = await ef.EverflowNode.validate_credential_access(harness.storage.blob)
    assert direct["valid"] is True and direct["identity_verified"] is False
