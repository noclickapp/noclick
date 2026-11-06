"""Skyvia current-row authority, revocation and saved execution fixtures."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from nodes import skyvia_node as p
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_lookup
from repositories.organization import PRIMARY_ORG_SQL
from utils import credential_approval, credentials, encryption

USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
OWNER = "33333333-3333-4333-8333-333333333333"
ORG = "44444444-4444-4444-8444-444444444444"
WORKFLOW = "55555555-5555-4555-8555-555555555555"
KEY = {"credential_type": "skyvia_api_token", "api_token": "synthetic-private-token", "workspace_ids": [101]}
ACCOUNT = 101


@pytest.fixture
def ensure_native_db_pool():
    yield


class Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *_args): return False


class Storage:
    def __init__(self):
        self.row = {"credential": b"synthetic-ciphertext", "credential_type": KEY["credential_type"], "owner_id": OWNER, "revoked_at": None, "token_version": 3}
        self.policy = {"name": "Fixture Skyvia application", "owner_id": OWNER, "approval_operations": [], "approval_revision": 1, "revoked_at": None}
        self.calls, self.allowed, self.approval = [], {(USER, ORG), (USER, None)}, None
    def acquire(self): return Context(self)
    def transaction(self): return Context(self)
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if sql == PRIMARY_ORG_SQL:
            return {"organization_id": ORG}
        if "SELECT c.credential" in sql:
            assert "resource_shares" in sql and "$2" in sql and "$3" in sql
            return deepcopy(self.row) if args[0] == CID and (args[1], args[2]) in self.allowed else None
        if "SELECT name,owner_id,approval_operations" in sql:
            assert "FOR UPDATE" in sql and args == (CID,)
            return self.policy
        if "SELECT id,status,consumed_at,expires_at" in sql:
            return self.approval
        raise AssertionError("Unexpected synthetic repository query")


@pytest.fixture
def storage(monkeypatch):
    store = Storage()
    crypto = SimpleNamespace(decrypt_credential=Mock(return_value=deepcopy(KEY)))
    monkeypatch.setattr(encryption, "get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr(credential_approval, "get_native_pool", lambda: store)
    return store, crypto


@pytest.fixture
def provider(monkeypatch):
    calls = []
    @asynccontextmanager
    async def client(**_options):
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                calls.append((method, url, kwargs))
                assert method == 'GET' and url == p.ROOT + '/workspaces'
                assert kwargs['headers']['Authorization'] == KEY['api_token']
                assert KEY['api_token'] not in repr(kwargs) and KEY['api_token'] not in url
                payload = [{'id': ACCOUNT, 'isPersonal': False, 'private': 'omitted'}]
                yield httpx.Response(200, json=payload, request=httpx.Request(method, url))

        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return calls


async def read_fresh(store):
    fresh = await p.SkyviaNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID)
    await fresh["_skyvia_reader"].read()
    return fresh


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"credential_type": "foreign_provider"}, {"revoked_at": "revoked"}, {"owner_id": None}, {"token_version": True}, {"token_version": -1}, {"token_version": "3"}])
async def test_current_rows_refuse_before_decrypt_and_provider(storage, provider, change):
    store, crypto = storage
    store.row.update(change)
    with pytest.raises(ValueError): await read_fresh(store)
    crypto.decrypt_credential.assert_not_called()
    assert provider == []


@pytest.mark.asyncio
async def test_actual_factory_saved_id_without_caller_never_uses_cached_pair(storage, provider):
    store, crypto = storage
    node = NodeFactory.create_node("fixture", "automation-skyvia", {"config": {"operation": "list_workspaces"}, "credentials": KEY, "credential_id": CID, "_approval_pool": store})
    with pytest.raises(ValueError, match="require a caller"): await node.execute({})
    assert not store.calls and provider == []
    crypto.decrypt_credential.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"owner_id": USER}, {"token_version": 4}, {"api_token": "synthetic-replacement"}, {"workspace_ids": [102]}])
async def test_reader_binds_actual_owner_version_and_entire_grant(storage, change):
    store, crypto = storage
    reader = p.Reader(CID, USER, ORG, None, store)
    await reader.read()
    if "owner_id" in change or "token_version" in change: store.row.update(change)
    else: crypto.decrypt_credential.return_value.update(change)
    with pytest.raises(ValueError, match="changed during"): await reader.read()


@pytest.mark.asyncio
async def test_cached_rebinding_and_row_blob_type_mismatch_are_not_reconciled(storage, provider):
    store, crypto = storage
    crypto.decrypt_credential.return_value["api_token"] = "synthetic-replacement"
    with pytest.raises(ValueError, match="cached credential changed"):
        await read_fresh(store)
    crypto.decrypt_credential.return_value["credential_type"] = "foreign_provider"
    with pytest.raises(ValueError, match="does not match"):
        await read_fresh(store)
    assert provider == []


@pytest.mark.asyncio
async def test_authority_removed_after_request_suppresses_result(storage, provider):
    store, _ = storage
    reader = p.Reader(CID, USER, ORG, None, store)
    original, reads = reader.read, 0
    async def lose_access():
        nonlocal reads
        reads += 1
        if reads == 2: store.allowed.clear()
        return await original()
    reader.read = lose_access
    with pytest.raises(ValueError, match="unavailable"):
        await p.request(p.guard(KEY), "/workspaces", reader=reader)
    assert len(provider) == 1


@pytest.mark.asyncio
async def test_trusted_workflow_owner_fallback_is_current_and_revocable(storage, monkeypatch):
    store, _ = storage
    store.allowed = {(OWNER, ORG)}
    owner, allowed = AsyncMock(return_value=OWNER), AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "get_workflow_owner_id", owner)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", allowed)
    fresh = await p.SkyviaNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID)
    fresh["_skyvia_reader"].workflow_id = WORKFLOW
    await fresh["_skyvia_reader"].read()
    owner.assert_awaited_once_with(store, WORKFLOW)
    allowed.assert_awaited_once_with(store, WORKFLOW, CID)
    sql, args = store.calls[-1]
    assert "workflow_authorized_credentials" in sql and "w.owner_id = $2" in sql and args == (CID, OWNER, ORG, WORKFLOW)
    allowed.return_value = False
    with pytest.raises(ValueError): await fresh["_skyvia_reader"].read()
    with pytest.raises(ValueError): await read_fresh(store)


@pytest.mark.asyncio
async def test_actual_saved_factory_run_uses_current_row_and_locked_admission(storage, provider):
    store, crypto = storage
    node = NodeFactory.create_node("fixture", "automation-skyvia", {"config": {"operation": "list_workspaces"}, "credentials": KEY, "credential_id": CID, "_approval_pool": store}, user_id=USER, organization_id=ORG)
    result = await node.run({})
    assert result["items"][0]["id"] == ACCOUNT and len(provider) == 1
    assert crypto.decrypt_credential.call_count >= 3
    assert any("FOR UPDATE" in sql for sql, _ in store.calls)


@pytest.mark.asyncio
async def test_staging_picker_binds_server_org_and_trusted_workflow(storage, provider, monkeypatch):
    store, _ = storage
    # Staging's hook omits org/workflow; only the loader's underscored context is trusted.
    store.allowed = {(OWNER, ORG)}
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value=OWNER))
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", AsyncMock(return_value=True))
    fresh = await p.SkyviaNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID)
    result = await p.SkyviaNode.load_field_options("workspace_id", fresh, {"_workflow_id": WORKFLOW, "organization_id": USER, "workflow_id": "forged"})
    assert result["options"] == [{"value": "101", "label": "101"}] and len(provider) == 1
    assert all(args[2] == ORG for sql, args in store.calls if "SELECT c.credential" in sql)
    assert any(args == (CID, OWNER, ORG, WORKFLOW) for sql, args in store.calls)


@pytest.mark.asyncio
async def test_staging_lookup_reads_org_before_skyvia_request(storage, provider):
    store, _ = storage
    store.allowed = {(USER, ORG)}
    result = await run_node_lookup(node_type="automation-skyvia", field_name="workspace_id", credential_id=CID, user_id=USER, organization_id=ORG, pool=store, context={"organization_id": OWNER})
    assert result["options"] == [{"value": "101", "label": "101"}] and len(provider) == 1
    assert all(args[2] == ORG for sql, args in store.calls if "SELECT c.credential" in sql)
