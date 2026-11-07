"""Workvivo entry points using staging's factory, picker and connect flow.

Only stored credential resolution, DNS and HTTP transport are synthetic. Runtime
credential admission remains the responsibility of staging's shared code.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import workvivo_node as s
from nodes.core import connection_evidence, credential_connect, registry, run_op
from nodes.tests.test_workvivo_node_mock import CREDS, SPACE, collection, transport
from repositories.credentials import credential_access_predicate
from wss.handlers import workflow_handler
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest

CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
NODE = "automation-workvivo"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.mark.asyncio
async def test_registered_factory_operation_resolves_saved_credential(monkeypatch):
    resolve = AsyncMock(return_value=CREDS)
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", resolve)
    class Storage:
        def acquire(self): return self
        def transaction(self): return self
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def fetchrow(self, sql, *args):
            assert "FROM credentials" in sql and "FOR UPDATE" in sql and args == (CID,)
            return {"revoked_at": None, "approval_operations": []}
    pool = Storage()
    with transport(monkeypatch, [httpx.Response(200, json=collection([SPACE]))]) as calls:
        result = await run_op.run_node_operation(node_type=NODE, operation="list_spaces",
            arguments={}, user_id=USER, pool=pool, credential_id=CID)
    assert registry.NODE_REGISTRY[NODE] is s.WorkvivoNode
    assert result["items"][0]["name"] == SPACE["name"] and len(calls) == 1
    resolve.assert_awaited_once_with(CID, USER, pool, org_id=None, workflow_id=None)


@pytest.mark.asyncio
async def test_connect_uses_tenant_space_evidence(monkeypatch):
    credential_connect._class_index.cache_clear()
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    with transport(monkeypatch, [httpx.Response(200, json=collection([SPACE]))]) as calls:
        verdict = await credential_connect.validate_for_connect(credential_type=s.FAMILY,
            credential_data=CREDS, user_id=USER, probe=True)
    assert verdict.ok and verdict.node_type == NODE and verdict.evidence.reachable is True
    assert verdict.evidence.samples[0].label == SPACE["name"]
    assert s.WorkvivoNode.connection_evidence.identity_operation is None
    assert len(calls) == 1 and calls[0].url.path == "/v1/spaces"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["allowed", "inaccessible", "unauthed"])
async def test_socket_picker_uses_staging_credential_access(monkeypatch, mode):
    queries, responses = [], []
    class Storage:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def acquire(self): return self
        async def fetchrow(self, sql, *args):
            queries.append((sql, args))
            assert "SELECT c.credential" in sql and credential_access_predicate() in sql
            assert args == (CID, USER, None)
            return None if mode == "inaccessible" else {"credential": b"fixture-ciphertext"}
    pool = Storage()
    handler = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={} if mode == "unauthed" else {"user_id": USER}))
    handler.get_pool = AsyncMock(return_value=pool)
    crypto = MagicMock()
    crypto.decrypt_credential.return_value = CREDS
    monkeypatch.setattr(workflow_handler, "get_encryption", lambda: crypto)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=None))
    async def capture(_sio, _sid, response, **_kwargs): responses.append(response.model_dump()["data"])
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    replies = [httpx.Response(200, json=collection([SPACE]))] if mode == "allowed" else []
    with transport(monkeypatch, replies) as calls:
        await handler.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(
            request_id="fixture-picker", node_type=NODE, field_name="space_id", credential_id=CID))
    assert responses[-1]["success"] is (mode == "allowed")
    if mode == "allowed":
        assert responses[-1]["options"] == [{"value": "15", "label": "Owned space", "metadata": None}]
        assert len(calls) == 1 and queries
    else:
        assert not calls and not crypto.decrypt_credential.called


@pytest.mark.asyncio
async def test_credential_check_uses_bounded_space_read(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=collection([SPACE], size=5))]) as calls:
        result = await s.WorkvivoNode.validate_credential_access(CREDS)
    assert result["valid"] is True
    assert dict(calls[0].url.params) == {"skip": "0", "take": "5"}
