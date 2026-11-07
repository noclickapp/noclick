"""Proposify current stored authority, native execution and connect fixtures."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest
from nodes.proposify_node import ProposifyNode
from nodes.core.run_op import run_node_operation, run_node_lookup
from tests.test_proposify_node import TYPE, USER, KEY, RAW, DOCUMENT, DOC

OWNER = "33333333-3333-4333-8333-333333333333"
WORKFLOW = "44444444-4444-4444-8444-444444444444"
ORG = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


class Pool:
    def __init__(self):
        self.org, self.shared, self.authorized, self.workflow_owner = None, False, True, OWNER
        self.row = {"credential": deepcopy(RAW), "credential_type": "proposify_issued_token", "owner_id": USER, "revoked_at": None, "token_version": 1, "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    @asynccontextmanager
    async def acquire(self): yield self
    async def fetchval(self, sql, *args):
        if "organization_members" in sql: return self.org
        raise AssertionError("Unexpected storage fixture query")
    async def fetchrow(self, sql, *args):
        if "workflow_authorized_credentials" in sql and "SELECT 1 FROM" in sql and "FROM credentials c" not in sql: return {"allowed": 1} if self.authorized else None
        if "FROM workflows" in sql and "FROM credentials c" not in sql: return {"owner_id": self.workflow_owner}
        if "FROM credentials c" in sql:
            assert "resource_shares" in sql
            principal = str(args[1])
            if principal != self.row["owner_id"] and not self.shared: return None
            if len(args) >= 6 and principal != str(args[3]) and (not self.authorized or not args[5] or self.workflow_owner != principal): return None
            return deepcopy(self.row)
        if "organization_members" in sql: return {"organization_id": self.org} if self.org else None
        raise AssertionError("Unexpected storage fixture query")


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
@pytest.mark.parametrize("field,value", [("credential_type", "salesforce_oauth"), ("revoked_at", datetime(2026, 1, 1, tzinfo=timezone.utc)), ("token_version", 0), ("token_version", True)])
async def test_actual_raw_row_family_revocation_and_version_before_decrypt(authority, field, value):
    pool, crypto = authority
    pool.row[field] = value
    with pytest.raises(ValueError): await ProposifyNode.freshen_credential(RAW, pool=pool, user_id=USER, credential_id=KEY)
    crypto.decrypt_credential.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "version", "family", "revoked", "account", "scope", "app", "token", "expiry", "organization"])
async def test_current_grant_binding_and_authority_reloaded_without_known_expiry(authority, change):
    pool, _ = authority
    grant = await ProposifyNode.freshen_credential(RAW, pool=pool, user_id=USER, credential_id=KEY)
    if change == "owner": pool.row["owner_id"] = OWNER
    if change == "version": pool.row["token_version"] = 2
    if change == "family": pool.row["credential_type"] = "other_oauth"
    if change == "revoked": pool.row["revoked_at"] = datetime.now(timezone.utc)
    if change == "account": pool.row["credential"]["expected_account_id"] = 72
    if change == "scope": pool.row["credential"]["scopes"] = ["read_documents"]
    if change == "app": pool.row["credential"]["client_id"] = "different-synthetic-app"
    if change == "token": pool.row["credential"]["access_token"] = "different-synthetic-token"
    if change == "expiry": pool.row["credential"]["expires_at"] = "2999-01-01T00:00:00Z"
    if change == "organization": pool.org = ORG
    with pytest.raises(ValueError): await grant.reload()


@pytest.mark.asyncio
async def test_workflow_owner_fallback_and_live_acl(authority):
    pool, _ = authority
    pool.row["owner_id"] = OWNER
    grant = await ProposifyNode._load_current_credential(RAW, pool=pool, user_id=USER, credential_id=KEY, workflow_id=WORKFLOW)
    assert grant.store.current.principal_id == OWNER
    pool.authorized = False
    with pytest.raises(ValueError): await grant.reload()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["owner", "account", "scope", "version", "acl"])
async def test_actual_stored_factory_discards_old_response_and_blocks_patch_after_parent_race(authority, monkeypatch, race):
    pool, _ = authority
    if race == "acl": pool.row["owner_id"] = OWNER
    calls = []
    def handle(request):
        calls.append(request)
        if race == "owner": pool.row["owner_id"] = OWNER
        if race == "account": pool.row["credential"]["expected_account_id"] = 72
        if race == "scope": pool.row["credential"]["scopes"] = ["read_documents"]
        if race == "version": pool.row["token_version"] = 2
        if race == "acl": pool.authorized = False
        return httpx.Response(200, json=DOCUMENT)
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.proposify_node.guarded_async_client", client)
    monkeypatch.setattr("repositories.credential_approvals.CredentialApprovalRepo.admit", AsyncMock(return_value=None))
    result = await run_node_operation(node_type=TYPE, operation="rename_draft_document", arguments={"document_id": DOC, "name": "Renamed fixture"}, user_id=USER, credential_id=KEY, pool=pool, workflow_id=WORKFLOW if race == "acl" else None)
    assert result["status"] == "error" and "data" not in result and len(calls) == 1 and calls[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("result,valid", [({"status": "success", "reachability_verified": True}, True), ({"status": "success", "data": {}}, None), ({"status": "error", "status_code": 403}, False), ({"status": "error", "status_code": 429}, None)])
async def test_actual_post_connect_context_tri_state_and_no_empty_identity(result, valid):
    context = MagicMock()
    context.revalidate = AsyncMock()
    context.run_operation = AsyncMock(return_value=result)
    outcome = await ProposifyNode.validate_credential_access(RAW, validation_context=context)
    assert outcome["valid"] is valid and context.revalidate.await_count == 2
    context.run_operation.assert_awaited_once_with("check_connection")
