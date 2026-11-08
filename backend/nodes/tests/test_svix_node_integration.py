"""Exercise staging credential loading through actual native Svix entry points.

The repository SQL, approval admission, factory, connect/evidence and socket code
stay real. Only storage, decryption, session, DNS and HTTP boundaries are synthetic.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import svix_node as s
from nodes.core import connection_evidence as ce, credential_connect as cc, registry, run_op
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL
from utils import credential_approval, credentials, encryption, ssrf
from wss.handlers import workflow_handler
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest

CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
NODE = "automation-svix"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
CONTACT = "app_" + "A" * 27
KEY = {"credential_type": "svix_api_key", "region": "us", "api_key": "fixture.svix.key"}


@pytest.fixture
def ensure_native_db_pool():
    yield


class Scope:
    def __init__(self, value):
        self.value = value
    async def __aenter__(self):
        return self.value
    async def __aexit__(self, *_):
        return False


@pytest.fixture
def native(monkeypatch):
    state = SimpleNamespace(sql=[], calls=[], responses=[], reads=0, denied=False, approval=None, revoke_after_first=False,
        blob={**KEY, "credential_type": "stale-forged-tag"}, row={"id": CID, "name": "Owned application", "owner_id": USER,
            "credential_type": "svix_api_key", "credential": b"synthetic-ciphertext", "token_version": 4, "updated_at": UPDATED,
            "approval_revision": 1, "approval_operations": [], "revoked_at": None})
    class Storage:
        def acquire(self):
            return Scope(self)
        def transaction(self):
            return Scope(self)
        async def fetchrow(self, sql, *args):
            state.sql.append((sql, args))
            if sql == PRIMARY_ORG_SQL:
                assert args == (USER,)
                return None
            if "FROM credentials c" in sql:
                assert credential_access_predicate() in sql and args[:3] == (CID, USER, None)
                assert len(args) == 3
                state.reads += 1
                if state.denied:
                    return None
                row = deepcopy(state.row)
                if state.revoke_after_first and state.reads > 1:
                    row["revoked_at"] = UPDATED
                return row
            if "FROM credentials " in sql and "FOR UPDATE" in sql:
                assert args == (CID,)
                return {**deepcopy(state.row), "approval_operations": ["*"] if state.approval else []}
            if "FROM approval_requests" in sql and "FOR UPDATE" in sql:
                assert args[0] == CID and "expires_at>now()" in sql and "consumed_at IS NULL" in sql
                assert len(args[1]) == 64 and set(args[1]) <= set("0123456789abcdef")
                return {"id": CID, "status": state.approval, "consumed_at": None, "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc)} if state.approval else None
            raise AssertionError("Unexpected synthetic SQL boundary")
    state.pool = Storage()
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    for module in (credentials, encryption, workflow_handler):
        monkeypatch.setattr(module, "get_encryption", lambda: crypto)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.invalid")
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["8.8.8.8"]))
    def answer(request):
        state.calls.append(request)
        assert request.url.host == "api.us.svix.com" and request.method == "GET"
        assert request.headers["authorization"] == "Bearer " + KEY["api_key"]
        assert request.url.path == "/api/v1/app"
        params = dict(request.url.params)
        assert set(params) == {"limit"} and 1 <= int(params["limit"]) <= 250
        return httpx.Response(200, json={"data": [{"id": CONTACT, "name": "Owned application", "metadata": {"secret": "private"},
            "createdAt": "2026-10-06T00:00:00Z", "updatedAt": "2026-10-06T00:00:00Z"}], "done": True, "iterator": None})
    factory = ssrf.guarded_async_client
    monkeypatch.setattr(s, "guarded_async_client", lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(answer)))
    state.workflow = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    state.workflow.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    state.workflow.get_pool = AsyncMock(return_value=state.pool)
    async def capture(_sio, _sid, response, **_kwargs):
        state.responses.append(response.model_dump())
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    state.crypto = crypto
    return state


async def operation(native):
    return await run_op.run_node_operation(node_type=NODE, operation="list_applications", arguments={}, user_id=USER, pool=native.pool, credential_id=CID)


async def lookup(native):
    return await run_op.run_node_lookup(node_type=NODE, field_name="application_id", user_id=USER, pool=native.pool, credential_id=CID)


@pytest.mark.asyncio
async def test_actual_factory_current_owner_row_and_stale_blob_tag(native):
    assert registry.NODE_REGISTRY[NODE] is s.SvixNode
    assert (await operation(native))["items"][0]["name"] == "Owned application"
    assert (await lookup(native))["options"][0]["value"] == CONTACT
    assert any(len(args) == 3 and credential_access_predicate() in sql
        for sql, args in native.sql if "FROM credentials c" in sql)


@pytest.mark.asyncio
async def test_actual_connect_evidence_is_reachability_without_invented_identity(native):
    verdict = await cc.validate_for_connect(credential_type="svix_api_key", credential_data=deepcopy(KEY), user_id=USER, pool=native.pool)
    assert verdict.ok and verdict.node_type == NODE and verdict.evidence.reachable is True
    assert verdict.evidence.account_label is None
    assert s.SvixNode.connection_evidence.field is None and s.SvixNode.connection_evidence.identity_operation is None
    assert "private" not in str(verdict.evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["microsoft_oauth", "api_key", "", 42])
async def test_actual_foreign_row_family_denies_shaped_blob_before_provider(native, foreign):
    native.row["credential_type"] = foreign
    with pytest.raises(ValueError):
        await operation(native)
    with pytest.raises(ValueError):
        await lookup(native)
    assert not native.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["inaccessible", "revoked"])
async def test_actual_acl_and_revocation_precede_decryption(native, denial):
    if denial == "inaccessible":
        native.denied = True
    else:
        native.row["revoked_at"] = UPDATED
    with pytest.raises(ValueError):
        await operation(native)
    assert not native.calls and not native.crypto.decrypt_credential.called


@pytest.mark.asyncio
@pytest.mark.parametrize("approval", ["pending", "rejected"])
async def test_actual_stored_admission_denies_operation_picker_and_evidence(native, approval):
    native.approval = approval
    assert (await operation(native))["executed"] is False
    assert (await lookup(native))["executed"] is False
    evidence = await ce.collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=native.pool)
    assert evidence.reachable is None and not evidence.samples and evidence.account_label is None
    assert not native.calls


@pytest.mark.asyncio
async def test_actual_second_read_revocation_precedes_lookup(native):
    native.revoke_after_first = True
    with pytest.raises(ValueError):
        await lookup(native)
    assert not native.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "unauthed", "inaccessible", "invalid_family"])
async def test_actual_socket_picker_uses_staging_loader_and_session(native, outcome):
    native.blob = deepcopy(KEY)
    if outcome == "unauthed":
        native.workflow.sio.get_session = AsyncMock(return_value={})
    elif outcome == "inaccessible":
        native.denied = True
    elif outcome == "invalid_family":
        native.blob["credential_type"] = "api_key"
    await native.workflow.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(
        request_id="fixture-picker", node_type=NODE, field_name="application_id", credential_id=CID))
    response = native.responses[-1]["data"]
    assert response["success"] is (outcome == "success")
    if outcome == "success":
        assert response["options"][0]["value"] == CONTACT and len(native.calls) == 1
    else:
        assert not native.calls
