"""UNRUN actual current-row, factory, locked admission, Agent and socket fixtures."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest

from nodes import bytescale_node as p
from nodes.core.registry import NodeFactory
from nodes.core import run_op, connection_evidence
from nodes.core.run_op import run_node_lookup, run_node_operation
from nodes.agent.node_op_tools import build_node_op_tools
from utils import credential_approval, credentials, encryption

USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
OWNER = "33333333-3333-4333-8333-333333333333"
ORG = "44444444-4444-4444-8444-444444444444"
WORKFLOW = "55555555-5555-4555-8555-555555555555"
KEY = {"credential_type": "bytescale_secret_api_key", "api_key": "secret_synthetic_private", "account_id": "A623uY2", "folder_paths": ["/uploads"]}
LOCATION = "/uploads"
ACCOUNT = "A623uY2"
PRODUCT = "/uploads/file.jpg"


@pytest.fixture
def ensure_native_db_pool():
    yield


class Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *_args): return False


class Storage:
    def __init__(self):
        self.row = {"credential": b"synthetic-ciphertext", "credential_type": KEY["credential_type"], "owner_id": OWNER, "revoked_at": None, "token_version": 3, "updated_at": None}
        self.policy = {"name": "Fixture Bytescale application", "owner_id": OWNER, "approval_operations": [], "approval_revision": 1, "revoked_at": None}
        self.calls, self.allowed, self.approval = [], {(USER, ORG), (USER, None)}, None
    def acquire(self): return Context(self)
    def transaction(self): return Context(self)
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
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
                assert method == 'GET' and url == p.ROOT + '/accounts/A623uY2/folders/list'
                assert kwargs['headers']['Authorization'] == 'Bearer ' + KEY['api_key']
                assert KEY['api_key'] not in repr(kwargs) and KEY['api_key'] not in url
                payload = {'folder': {'type': 'Folder', 'folderPath': LOCATION, 'virtual': True}, 'items': [{'type': 'File', 'filePath': PRODUCT, 'size': 0}], 'cursor': PRODUCT, 'isPaginationComplete': True}
                yield httpx.Response(200, json=payload, request=httpx.Request(method, url))

        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"credential_type": "foreign_provider"}, {"revoked_at": "revoked"}, {"owner_id": None}, {"token_version": True}, {"token_version": -1}, {"token_version": "3"}])
async def test_current_rows_refuse_before_decrypt_and_provider(storage, provider, change):
    store, crypto = storage
    store.row.update(change)
    with pytest.raises(ValueError): await p.BytescaleNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID)
    crypto.decrypt_credential.assert_not_called()
    assert provider == []


@pytest.mark.asyncio
async def test_actual_factory_saved_id_without_caller_never_uses_cached_pair(storage, provider):
    store, crypto = storage
    node = NodeFactory.create_node("fixture", "automation-bytescale", {"config": {"operation": "list_folder"}, "credentials": KEY, "credential_id": CID, "_approval_pool": store})
    with pytest.raises(ValueError, match="require a caller"): await node.execute({})
    assert not store.calls and provider == []
    crypto.decrypt_credential.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"owner_id": USER}, {"token_version": 4}, {"api_key": "secret_synthetic_replacement"}, {"folder_paths": ["/other"]}, {"account_id": "B623uY2"}])
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
    crypto.decrypt_credential.return_value["api_key"] = "secret_synthetic_replacement"
    with pytest.raises(ValueError, match="cached credential changed"):
        await p.BytescaleNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID)
    crypto.decrypt_credential.return_value["credential_type"] = "foreign_provider"
    with pytest.raises(ValueError, match="does not match"):
        await p.BytescaleNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID)
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
        await p.request(p.guard(KEY), "folders/list", query={"folderPath": LOCATION, "limit": 1}, reader=reader)
    assert len(provider) == 1


@pytest.mark.asyncio
async def test_trusted_workflow_owner_fallback_is_current_and_revocable(storage, monkeypatch):
    store, _ = storage
    store.allowed = {(OWNER, ORG)}
    owner, allowed = AsyncMock(return_value=OWNER), AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "get_workflow_owner_id", owner)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", allowed)
    fresh = await p.BytescaleNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID, organization_id=ORG, workflow_id=WORKFLOW)
    owner.assert_awaited_once_with(store, WORKFLOW)
    allowed.assert_awaited_once_with(store, WORKFLOW, CID)
    sql, args = store.calls[-1]
    assert "workflow_authorized_credentials" in sql and "w.owner_id = $2" in sql and args == (CID, OWNER, ORG, WORKFLOW)
    allowed.return_value = False
    with pytest.raises(ValueError): await fresh["_bytescale_reader"].read()
    with pytest.raises(ValueError): await p.BytescaleNode.freshen_credential(KEY, pool=store, user_id=USER, credential_id=CID, organization_id=ORG)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_locked_admission_stops_factory_dispatcher_and_collector(storage, provider, status):
    store, _ = storage
    store.policy["approval_operations"] = ["automation-bytescale.list_folder", "automation-bytescale.get_folder_details"]
    store.approval = {"id": UUID(int=19), "status": status, "consumed_at": None, "expires_at": datetime(2999, 1, 1, tzinfo=timezone.utc)}
    node = NodeFactory.create_node("fixture", "automation-bytescale", {"config": {"operation": "list_folder"}, "credentials": KEY, "credential_id": CID, "_approval_pool": store}, user_id=USER, organization_id=ORG)
    result = await node.run({})
    assert result["executed"] is False and result["status"] == ("pending_approval" if status == "pending" else status)
    result = await run_node_operation(node_type="automation-bytescale", operation="list_folder", arguments={}, user_id=USER, organization_id=ORG, credential_id=CID, pool=store)
    assert result["executed"] is False
    evidence = await connection_evidence.collect_evidence(node_type="automation-bytescale", credential_id=CID, user_id=USER, organization_id=ORG, pool=store)
    assert evidence.reachable is None and evidence.proves == "reachability"
    assert provider == [] and any("FOR UPDATE" in sql for sql, _ in store.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("search,expected", [(None, [LOCATION]), ("  UPLOADS  ", [LOCATION]), ("absent", [])])
async def test_actual_lookup_uses_trusted_org_not_request_context(storage, provider, monkeypatch, search, expected):
    store, _ = storage
    loader = AsyncMock(wraps=p.BytescaleNode.freshen_credential)
    monkeypatch.setattr(p.BytescaleNode, "freshen_credential", loader)
    result = await run_node_lookup(node_type="automation-bytescale", field_name="folder_path", credential_id=CID, user_id=USER, organization_id=ORG, pool=store, context={"organization_id": OWNER, "workflow_id": "forged"}, search=search)
    assert [option["value"] for option in result["options"]] == expected and len(provider) == 1
    assert loader.await_args.kwargs["organization_id"] == ORG and loader.await_args.kwargs["workflow_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("org_failure", [False, True])
async def test_actual_socket_server_org_and_fail_closed_context(storage, provider, monkeypatch, org_failure):
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    store, _ = storage
    store.allowed = {(USER, ORG)}
    org = AsyncMock(side_effect=RuntimeError("synthetic context failure")) if org_failure else AsyncMock(return_value=ORG)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", org)
    sent = AsyncMock()
    monkeypatch.setattr(workflow_handler, "send_event", sent)
    handler = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler.get_pool = AsyncMock(return_value=store)
    event = WorkflowNodeLoadOptionsRequest(request_id="fixture", node_type="automation-bytescale", credential_id=CID, field_name="folder_path", context={"organization_id": OWNER, "workflow_id": "forged"})
    await handler.get_events()[event.event_name]("synthetic-sid", event)
    response = sent.await_args.args[2].data
    assert response["success"] is (not org_failure)
    if org_failure:
        assert provider == []
    else:
        assert response["options"][0]["value"] == str(LOCATION) and len(provider) == 1
        assert all(args[1:] == (USER, ORG) for sql, args in store.calls if "SELECT c.credential" in sql)


@pytest.mark.asyncio
async def test_actual_saved_factory_run_uses_current_row_and_locked_admission(storage, provider):
    store, crypto = storage
    node = NodeFactory.create_node("fixture", "automation-bytescale", {"config": {"operation": "list_folder"}, "credentials": KEY, "credential_id": CID, "_approval_pool": store}, user_id=USER, organization_id=ORG)
    result = await node.run({})
    assert result["items"] == [{"type": "File", "size": 0}] and len(provider) == 2
    assert crypto.decrypt_credential.call_count >= 3
    assert any("FOR UPDATE" in sql for sql, _ in store.calls)


@pytest.mark.asyncio
async def test_actual_agent_asset_scope_refuses_foreign_id_before_resolution(provider, monkeypatch):
    _, configs = build_node_op_tools("automation-bytescale", [{"operation": "get_file_details", "field_scopes": {"folder_path": [str(LOCATION)], "file_path": [str(PRODUCT)]}}], node_id="fixture", credential_id=CID)
    operation = next(info for info in configs.values() if info["tool_type"] == "node_op")
    resolved = AsyncMock()
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", resolved)
    result = await run_op.run_node_op_tool(operation, {"folder_path": "/other", "file_path": PRODUCT}, user_id=USER, organization_id=ORG, workflow_id=WORKFLOW)
    assert result["success"] is False
    resolved.assert_not_awaited()
    assert provider == []


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", [False, True])
async def test_actual_transport_postread_current_revocation_suppresses_success_or_refusal(storage, monkeypatch, refused):
    store, _ = storage
    calls = []
    @asynccontextmanager
    async def client(**_options):
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **_kwargs):
                calls.append(url)
                store.row["revoked_at"] = "now"
                payload = {'folder': {'type': 'Folder', 'folderPath': LOCATION, 'virtual': True}, 'items': [], 'cursor': PRODUCT, 'isPaginationComplete': True}
                yield httpx.Response(403 if refused else 200, json=payload, request=httpx.Request(method, url))
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    node = NodeFactory.create_node("fixture", "automation-bytescale", {"config": {"operation": "list_folder"}, "credentials": KEY, "credential_id": CID, "_approval_pool": store}, user_id=USER, organization_id=ORG)
    with pytest.raises(ValueError, match="unavailable"): await node.execute({})
    assert len(calls) == 1
