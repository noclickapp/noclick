"""Mindbody fixtures at native stored-credential boundaries.

The registered handler, canonical repository/resolver, factory and admission
execute with synthetic storage, encryption and HTTP, never a provider account.
"""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from nodes import mindbody_node as native
from nodes.core.registry import NodeFactory
from repositories.credentials import credential_access_predicate

CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
WORKFLOW = "00000000-0000-4000-8000-000000000004"
STAMP = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


class _Scope:
    def __init__(self, storage):
        self.storage = storage
    async def __aenter__(self):
        return self.storage
    async def __aexit__(self, *_):
        return False


class _Storage:
    def __init__(self):
        self.row = {"id": CID, "name": "Owned fixture", "owner_id": OWNER,
            "credential_type": native.FAMILY, "credential": b"synthetic-ciphertext",
            "updated_at": STAMP, "token_version": 7, "approval_revision": 1,
            "revoked_at": None, "approval_operations": []}
        self.allowed = {(USER, ORG)}
        self.grants, self.timeline, self.queries = {}, [], []
        self.authorized = False
        self.on_admission = None
    def acquire(self):
        return _Scope(self)
    def transaction(self):
        return _Scope(self)
    async def fetchrow(self, sql, *args):
        self.queries.append((sql, args))
        if "SELECT c.credential" in sql:
            assert credential_access_predicate() in sql
            assert len(args) == 3 and args[0] == CID
            self.timeline.append("row")
            return deepcopy(self.row) if (args[1], args[2]) in self.allowed else None
        if "SELECT owner_id" in sql and "FROM workflows" in sql:
            return {"owner_id": OWNER}
        if "SELECT 1 FROM workflow_authorized_credentials" in sql:
            assert args == (UUID(WORKFLOW), UUID(CID))
            return {"exists": 1} if self.authorized else None
        if "SELECT name,owner_id,approval_operations" in sql:
            assert args == (CID,) and "FOR UPDATE" in sql
            self.timeline.append("admission")
            if self.on_admission:
                self.on_admission()
            return deepcopy(self.row)
        if "SELECT id,status,consumed_at,expires_at" in sql:
            grant = self.grants.get(args[1])
            return grant if grant and grant["consumed_at"] is None else None
        if "INSERT INTO approval_requests" in sql:
            fingerprint, payload = args[-2:]
            grant = {"id": UUID(int=100 + len(self.grants)), "status": "pending",
                "consumed_at": None, "expires_at": STAMP, "payload": deepcopy(payload)}
            self.grants[fingerprint] = grant
            return grant
        raise AssertionError("Unexpected synthetic SQL")
    async def fetchval(self, sql, *args):
        if "workflow_authorized_credentials" in sql: return None
        assert "SELECT count(*) FROM approval_requests" in sql and args == (CID,)
        return sum(grant["status"] == "pending" for grant in self.grants.values())
    async def execute(self, sql, identifier):
        assert sql == "UPDATE approval_requests SET consumed_at=now() WHERE id=$1"
        for grant in self.grants.values():
            if grant["id"] == identifier:
                grant["consumed_at"] = STAMP
                return "UPDATE 1"
        raise AssertionError("Unknown synthetic approval")


@pytest.fixture
def state(monkeypatch):
    from utils import credentials
    from wss.handlers import credentials_handler, workflow_handler
    storage = _Storage()
    value = SimpleNamespace(storage=storage, requests=[], responses=[], callback=None,
        blob={"credential_type": "foreign-blob", "site_id": 42, "user_authorization": "current-synthetic-staff-42",
            "api_key": "current-synthetic-key-42"})
    crypto = MagicMock()
    def decrypt(_):
        storage.timeline.append("decrypt")
        return deepcopy(value.blob)
    crypto.decrypt_credential.side_effect = decrypt
    value.crypto = crypto
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials_handler, "get_encryption", lambda: crypto)
    monkeypatch.setattr(workflow_handler, "get_encryption", lambda: crypto)
    value.org = AsyncMock(return_value=ORG)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", value.org)
    monkeypatch.setattr("utils.credential_approval.notify_created", AsyncMock())
    async def provider(request):
        storage.timeline.append("provider")
        value.requests.append(request)
        if value.callback:
            value.callback()
        return httpx.Response(200, json={"Clients": [], "PaginationResponse": {
            "RequestedLimit": int(request.url.params["request.limit"]),
            "RequestedOffset": int(request.url.params["request.offset"]), "PageSize": 0, "TotalResults": 0}})
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(provider), **kwargs))
    async def capture(_sio, _sid, event, **kwargs):
        value.responses.append(event.model_dump())
    monkeypatch.setattr(credentials_handler, "send_event", capture)
    handler = credentials_handler.CredentialsHandler(SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER})))
    handler.get_pool = AsyncMock(return_value=storage)
    value.handler = handler
    return value


def node(state, *, workflow=None, operation="list_clients"):
    config = {"operation": operation}
    return NodeFactory.create_node(node_id="owned-test-node", node_type=native.NODE_TYPE,
        node_data={"credential_id": CID, "credentialIds": {native.FAMILY: CID},
            "config": config, "credentials": {"credential_type": native.FAMILY,
                "site_id": 24, "user_authorization": "stale-synthetic-staff", "api_key": "stale-synthetic-key"},
            "_approval_pool": state.storage}, user_id=USER, organization_id=ORG, workflow_id=workflow)


@pytest.mark.asyncio
async def test_native_saved_row_uses_current_key_site_staff_header_and_real_admission(state):
    result = await node(state).run({})
    assert result["status"] == "success" and len(state.requests) == 1
    assert state.requests[0].headers["authorization"] == "current-synthetic-staff-42"
    assert str(state.requests[0].url).startswith(native.API_ROOT + "/client/clients?")
    assert state.requests[0].headers["siteid"] == "42"
    assert state.requests[0].headers["api-key"] == "current-synthetic-key-42"
    assert state.storage.timeline.index("row") < state.storage.timeline.index("decrypt") < state.storage.timeline.index("admission") < state.storage.timeline.index("provider")


@pytest.mark.asyncio
async def test_real_standalone_dispatcher_resolver_factory_and_native_policy(state):
    from nodes.core.run_op import run_node_operation
    result = await run_node_operation(node_type=native.NODE_TYPE, operation="list_clients",
        arguments={"limit": 25},
        credential_id=CID, user_id=USER, pool=state.storage, organization_id=ORG)
    assert result["status"] == "success" and len(state.requests) == 1
    assert state.requests[0].headers["authorization"] == "current-synthetic-staff-42"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["foreign", "null-family", "revoked", "denied"])
async def test_native_current_row_negative_before_admission_or_provider(state, failure):
    row = state.storage.row
    if failure == "foreign": row["credential_type"] = "other_api_key"
    elif failure == "null-family": row["credential_type"] = None
    elif failure == "revoked": row["revoked_at"] = STAMP
    elif failure == "denied": state.storage.allowed.clear()
    with pytest.raises(native.CredentialValidationUnavailable):
        await node(state).run({})
    if failure in {"revoked", "denied"}:
        state.crypto.decrypt_credential.assert_not_called()
    assert "admission" not in state.storage.timeline and state.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["credential_type", "revoked_at", "access", "key"])
async def test_results_discarded_after_real_provider_if_current_authority_changes(state, changed):
    def change():
        if changed == "access": state.storage.allowed.clear()
        elif changed == "key": state.blob["api_key"] = "replacement-synthetic-key"
        else:
            state.storage.row[changed] = {"owner_id": USER, "credential_type": "other_api_key",
                "token_version": 8, "approval_revision": 2, "revoked_at": STAMP}[changed]
    state.callback = change
    with pytest.raises(native.CredentialValidationUnavailable):
        await node(state).run({})
    assert len(state.requests) == 1


@pytest.mark.asyncio
async def test_actual_restricted_call_pending_rejected_approved_once(state):
    state.storage.row["approval_operations"] = [native.NODE_TYPE + ".list_clients"]
    result = await node(state).run({})
    assert result["status"] == "pending_approval" and result["executed"] is False and state.requests == []
    grant = next(iter(state.storage.grants.values()))
    grant["status"] = "rejected"
    assert (await node(state).execute({}))["status"] == "rejected" and state.requests == []
    grant["status"] = "approved"
    assert (await node(state).run({}))["status"] == "success"
    assert grant["consumed_at"] is not None and len(state.requests) == 1
    assert (await node(state).run({}))["status"] == "pending_approval" and len(state.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_saved_attachment_without_top_level_id_still_uses_real_admission(state, nested):
    instance = node(state)
    del instance.node_data["credential_id"]
    if nested:
        instance.node_data["config"]["credentialIds"] = instance.node_data.pop("credentialIds")
    state.storage.row["approval_operations"] = [native.NODE_TYPE + ".list_clients"]
    result = await instance.execute({})
    assert result["status"] == "pending_approval" and result["executed"] is False
    assert instance.node_data["credential_id"] == CID and state.requests == []
    assert "admission" in state.storage.timeline


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_real_canonical_positive_workflow_owner_fallback_is_required(state, authorized):
    state.storage.allowed = {(OWNER, ORG)}
    state.storage.authorized = authorized
    if authorized:
        assert (await node(state, workflow=WORKFLOW).run({}))["status"] == "success"
    else:
        with pytest.raises(native.CredentialValidationUnavailable):
            await node(state, workflow=WORKFLOW).run({})
        assert state.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("before_wire", [False, True])
async def test_owner_fallback_authorization_withdrawal_is_rechecked(state, before_wire):
    state.storage.allowed = {(OWNER, ORG)}
    state.storage.authorized = True
    def withdraw():
        state.storage.authorized = False
    if before_wire:
        state.storage.on_admission = withdraw
    else:
        state.callback = withdraw
    with pytest.raises(native.CredentialValidationUnavailable):
        await node(state, workflow=WORKFLOW).run({})
    assert len(state.requests) == (0 if before_wire else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("org,allowed,valid", [(ORG, {(USER, ORG)}, True), (None, {(USER, None)}, True),
    (None, {(USER, ORG)}, False)])
async def test_actual_current_shared_and_organization_acl_arguments(state, org, allowed, valid):
    state.org.return_value = org
    state.storage.allowed = allowed
    if valid:
        assert (await node(state).run({}))["status"] == "success"
    else:
        with pytest.raises(native.CredentialValidationUnavailable):
            await node(state).run({})
    assert all(args[2] == org for sql, args in state.storage.queries if "SELECT c.credential" in sql)


@pytest.mark.asyncio
async def test_native_raw_execute_cannot_claim_metadata_as_admission(state):
    instance = node(state)
    instance.node_data["_mindbody_admitted"] = True
    instance.node_data["validation_context"] = {"owner_id": USER, "approved": True}
    state.storage.row["approval_operations"] = ["*"]
    result = await instance.execute({})
    assert result["status"] == "pending_approval" and state.requests == []


@pytest.mark.asyncio
async def test_actual_collector_empty_protected_access_is_reachable_but_not_ownership(state):
    from nodes.core.connection_evidence import collect_evidence
    result = await collect_evidence(node_type=native.NODE_TYPE, credential_id=CID, user_id=USER, pool=state.storage, organization_id=ORG)
    assert result.reachable is True and len(state.requests) == 1
    assert native.MindbodyNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["agent", "socket"])
async def test_actual_lookup_refusal_is_error_not_empty_working_catalog(state, monkeypatch, boundary):
    from nodes.core.run_op import run_node_lookup
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    async def refuse(request):
        state.requests.append(request)
        return httpx.Response(403, json={"Error": {"Message": "synthetic-secret"}})
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(refuse), **kwargs))
    if boundary == "agent":
        with pytest.raises(ValueError, match="choices were not completed"):
            await run_node_lookup(node_type=native.NODE_TYPE, field_name="location_id", credential_id=CID, user_id=USER, pool=state.storage, organization_id=ORG)
    else:
        captured = []
        async def send(_sio, _sid, event, **kwargs): captured.append(event.model_dump())
        monkeypatch.setattr(workflow_handler, "send_event", send)
        handler = workflow_handler.WorkflowHandler(SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER})))
        handler.get_pool = AsyncMock(return_value=state.storage)
        request = WorkflowNodeLoadOptionsRequest(request_id="owned-fixture", node_type=native.NODE_TYPE, credential_id=CID, field_name="location_id")
        await handler.load_node_options("owned-fixture", request)
        assert captured[-1]["data"]["success"] is False
        assert "synthetic-secret" not in str(captured)
    assert len(state.requests) == 1


@pytest.mark.asyncio
async def test_actual_lookup_current_row_numeric_choice_paging_and_preload_race(state, monkeypatch):
    from nodes.core.run_op import run_node_lookup
    async def choices(request):
        state.requests.append(request)
        return httpx.Response(200, json={"Locations": [{"Id": 9, "Name": "Owned room", "Address": "private"}],
            "PaginationResponse": {"RequestedLimit": 100, "RequestedOffset": 0, "PageSize": 1, "TotalResults": 2}})
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(choices), **kwargs))
    result = await run_node_lookup(node_type=native.NODE_TYPE, field_name="location_id", credential_id=CID, user_id=USER, pool=state.storage, organization_id=ORG)
    assert result == {"options": [{"value": "9", "label": "Owned room"}], "next_page_token": "1"}
    assert state.requests[0].headers["siteid"] == "42"
    raw = await native.MindbodyNode.freshen_credential({"credential_type": native.FAMILY}, pool=state.storage, user_id=USER, credential_id=CID)
    state.blob["api_key"] = "replacement-synthetic-key"
    with pytest.raises(native.CredentialValidationUnavailable):
        await native.MindbodyNode.load_field_options("location_id", raw, context={"_user_id": OWNER, "approved": True})
    assert len(state.requests) == 1


@pytest.mark.asyncio
async def test_fabricated_lookup_authority_from_json_never_runs(state):
    with pytest.raises(native.CredentialValidationUnavailable):
        await native.MindbodyNode.load_field_options("location_id", {"_mindbody_lookup_authority": {"user_id": USER, "approved": True}})
    assert state.requests == []


@pytest.mark.asyncio
async def test_post_connect_hook_defers_to_explicit_protected_check_without_provider(state):
    result = await native.MindbodyNode.validate_credential_access({"credential_type": native.FAMILY})
    assert result["valid"] is None and "Check Protected Client Access" in result["message"]
    assert state.requests == []
