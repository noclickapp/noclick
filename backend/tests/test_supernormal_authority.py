"""UNRUN Supernormal current-row, owner/ACL, actual socket and lookup fixtures.

The qualified real authority adapter queries a synthetic storage boundary.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest
from nodes.supernormal_node import SupernormalNode
from nodes.core.run_op import run_node_operation, run_node_lookup
from tests.test_supernormal_node import TYPE, USER, KEY, RAW, IDENTITY, RECORDING

OWNER = "33333333-3333-4333-8333-333333333333"
WORKFLOW = "44444444-4444-4444-8444-444444444444"
ORG = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


class Pool:
    def __init__(self):
        self.org, self.shared, self.authorized, self.workflow_owner = None, False, True, OWNER
        self.row = {"credential": deepcopy(RAW), "credential_type": "supernormal_api_key", "owner_id": USER, "revoked_at": None, "token_version": 1, "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def fetchval(self, sql, *args):
        if "organization_members" in sql: return self.org
        raise AssertionError("Unexpected SQL fixture call")

    async def fetchrow(self, sql, *args):
        if "workflow_authorized_credentials" in sql and "SELECT 1 FROM" in sql and "FROM credentials c" not in sql:
            return {"allowed": 1} if self.authorized else None
        if "FROM workflows" in sql and "FROM credentials c" not in sql:
            return {"owner_id": self.workflow_owner}
        if "FROM credentials c" in sql:
            assert "resource_shares" in sql
            principal = str(args[1])
            if principal != self.row["owner_id"] and not self.shared: return None
            if len(args) >= 6 and principal != str(args[3]) and (not self.authorized or not args[5] or self.workflow_owner != principal): return None
            return deepcopy(self.row)
        if "organization_members" in sql: return {"organization_id": self.org} if self.org else None
        raise AssertionError("Unexpected SQL fixture call")


@pytest.fixture
def authority(monkeypatch):
    pool, crypto = Pool(), MagicMock()
    crypto.decrypt_credential.side_effect = deepcopy
    crypto.encrypt_credential.side_effect = deepcopy
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.credentials.get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.credentials.get_native_pool", lambda: pool)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    return pool, crypto


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("credential_type", "other_api_key"), ("revoked_at", datetime.now(timezone.utc)), ("token_version", 0), ("token_version", True)])
async def test_raw_row_family_revocation_version_precede_decrypt(authority, field, value):
    pool, crypto = authority
    pool.row[field] = value
    with pytest.raises(ValueError):
        await SupernormalNode.freshen_credential(RAW, pool=pool, user_id=USER, credential_id=KEY)
    crypto.decrypt_credential.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "version", "family", "revoked", "principal", "key", "organization"])
async def test_issued_key_without_expiry_still_revalidates_current_authority(authority, change):
    pool, _ = authority
    grant = await SupernormalNode.freshen_credential(RAW, pool=pool, user_id=USER, credential_id=KEY)
    if change == "owner": pool.row["owner_id"] = OWNER
    if change == "version": pool.row["token_version"] = 2
    if change == "family": pool.row["credential_type"] = "other_api_key"
    if change == "revoked": pool.row["revoked_at"] = datetime.now(timezone.utc)
    if change == "principal": pool.row["credential"]["expected_user_id"] = "different-userfixture"
    if change == "key": pool.row["credential"]["api_token"] = "different-synthetic-key"
    if change == "organization": pool.org = ORG
    with pytest.raises(ValueError): await grant.reload()


@pytest.mark.asyncio
async def test_positive_workflow_owner_fallback_and_current_acl(authority):
    pool, _ = authority
    pool.row["owner_id"] = OWNER
    grant = await SupernormalNode._load_current_credential(RAW, pool=pool, user_id=USER, credential_id=KEY, workflow_id=WORKFLOW)
    assert grant.store.current.principal_id == OWNER
    pool.authorized = False
    with pytest.raises(ValueError): await grant.reload()


@pytest.mark.asyncio
async def test_actual_socket_stamps_raw_row_family_before_picker(authority, monkeypatch):
    from wss.handlers.workflow_handler import WorkflowHandler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    pool, _ = authority
    pool.row["credential_type"] = "other_api_key"
    handler = WorkflowHandler.__new__(WorkflowHandler)
    handler.sio = AsyncMock()
    handler.sio.get_session.return_value = {"user_id": USER}
    handler.get_pool = AsyncMock(return_value=pool)
    emitted = AsyncMock()
    monkeypatch.setattr("wss.handlers.workflow_handler.send_event", emitted)
    monkeypatch.setattr("utils.credential_approval.admit_lookup", AsyncMock(return_value=None))
    picker = AsyncMock(side_effect=AssertionError("Foreign family reached picker"))
    monkeypatch.setattr(SupernormalNode, "load_field_options", picker)
    await handler.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(request_id="fixture", node_type=TYPE, field_name="recording_id", credential_id=KEY, context={"visibility": "all"}))
    assert emitted.await_args.args[2].data["success"] is False
    picker.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["owner", "principal", "version", "acl"])
async def test_real_stored_factory_discards_old_response_after_race(authority, monkeypatch, race):
    pool, _ = authority
    if race == "acl": pool.row["owner_id"] = OWNER
    calls = []

    def handle(request):
        calls.append(request)
        if race == "owner": pool.row["owner_id"] = OWNER
        if race == "principal": pool.row["credential"]["expected_user_id"] = "different-userfixture"
        if race == "version": pool.row["token_version"] = 2
        if race == "acl": pool.authorized = False
        return httpx.Response(200, json=IDENTITY)

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance

    monkeypatch.setattr("nodes.supernormal_node.guarded_async_client", client)
    monkeypatch.setattr("repositories.credential_approvals.CredentialApprovalRepo.admit", AsyncMock(return_value=None))
    result = await run_node_operation(node_type=TYPE, operation="get_user", arguments={}, user_id=USER, credential_id=KEY, pool=pool, workflow_id=WORKFLOW if race == "acl" else None)
    assert result["status"] == "error" and "data" not in result and len(calls) == 1


@pytest.mark.asyncio
async def test_real_stored_lookup_preserves_visibility_context(authority, monkeypatch):
    pool, _ = authority
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=IDENTITY if request.url.path.endswith("/user") else {"recordings": [RECORDING], "meta": {"current_page": 1, "next_page": None, "total_pages": 1}})

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance

    monkeypatch.setattr("nodes.supernormal_node.guarded_async_client", client)
    monkeypatch.setattr("utils.credential_approval.admit_lookup", AsyncMock(return_value=None))
    result = await run_node_lookup(node_type=TYPE, field_name="recording_id", context={"visibility": "shared_with_me"}, credential_id=KEY, user_id=USER, pool=pool)
    assert {r["value"] for r in result["options"]} == {"recordingfixture1"}
    assert calls[-1].url.params["visibility"] == "shared_with_me" and calls[-1].url.host == "api.supernormal.com"


@pytest.mark.asyncio
async def test_post_connect_hook_requires_current_declared_native_probe():
    context = MagicMock()
    context.revalidate = AsyncMock()
    context.run_operation = AsyncMock(return_value={"status": "success", "executed": True, "data": []})
    result = await SupernormalNode.validate_credential_access(RAW, validation_context=context)
    assert result == {"valid": True, "provider_verified": True}
    context.run_operation.assert_awaited_once_with("get_user")
    assert context.revalidate.await_count == 2


@pytest.mark.asyncio
async def test_current_scopes_binding_changes_refused(authority):
    pool, _ = authority
    grant = await SupernormalNode.freshen_credential(RAW, pool=pool, user_id=USER, credential_id=KEY)
    pool.row["credential"]["scopes"] = ["user:read"]
    with pytest.raises(ValueError): await grant.reload()




@pytest.mark.asyncio
async def test_current_acl_race_between_recording_parent_and_transcript(authority, monkeypatch):
    pool, _ = authority
    pool.row["owner_id"] = OWNER
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/user"): return httpx.Response(200, json=IDENTITY)
        pool.authorized = False
        return httpx.Response(200, json=RECORDING)

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance

    monkeypatch.setattr("nodes.supernormal_node.guarded_async_client", client)
    monkeypatch.setattr("repositories.credential_approvals.CredentialApprovalRepo.admit", AsyncMock(return_value=None))
    result = await run_node_operation(node_type=TYPE, operation="get_transcript", arguments={"recording_id": "recordingfixture1", "visibility": "all"}, user_id=USER, credential_id=KEY, pool=pool, workflow_id=WORKFLOW)
    assert result["status"] == "error" and "data" not in result and len(calls) == 2
    assert all(not r.url.path.endswith("/transcript") for r in calls)
