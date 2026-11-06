"""Exercise current saved-row authority through actual native AccuLynx entry points.

The repository SQL, approval admission, factory, connect/evidence and socket code
stay real. Only storage, decryption, session, DNS and HTTP boundaries are synthetic.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import acculynx_node as s
from nodes.core import connection_evidence as ce, credential_connect as cc, registry, run_op
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL
from utils import credential_approval, credentials, encryption, ssrf
from wss.handlers import credentials_handler, workflow_handler
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
NODE = "automation-acculynx"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
COMPANY = "00000000-0000-4000-8000-000000000010"
CONTACT = "00000000-0000-4000-8000-000000000011"
KEY = {"credential_type": "acculynx_api_key", "api_key": "fixture.synthetic.key", "company_id": COMPANY}


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
    state = SimpleNamespace(sql=[], calls=[], responses=[], reads=0, denied=False, approval=None, revoke_after_first=False, revoke_after_http=False, change_after_http=None,
        blob={**KEY, "credential_type": "stale-forged-tag"}, row={"id": CID, "name": "Owned Roofing", "owner_id": USER,
            "credential_type": "acculynx_api_key", "credential": b"synthetic-ciphertext", "token_version": 4, "updated_at": UPDATED,
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
                if len(args) == 6:
                    assert args[3:] == (USER, True, None) and "workflow_authorized_credentials" in sql
                else:
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
        assert request.url.host == "api.acculynx.com" and request.method == "GET"
        assert request.headers["authorization"] == "Bearer " + KEY["api_key"]
        if state.revoke_after_http:
            state.row["revoked_at"] = UPDATED
        if state.change_after_http:
            state.row.update(state.change_after_http)
        if request.url.path == "/api/v2/company-settings":
            return httpx.Response(200, json={"companyId": COMPANY, "name": "Owned Roofing", "email": "private@example.test"})
        assert request.url.path == "/api/v2/contacts"
        assert dict(request.url.params) == {"pageStartIndex": "0", "pageSize": "25"}
        return httpx.Response(200, json={"items": [{"id": CONTACT, "firstName": "Owned", "lastName": "Contact"}], "count": 1, "pageSize": 25, "pageStartIndex": 0})
    factory = ssrf.guarded_async_client
    monkeypatch.setattr(s, "guarded_async_client", lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(answer)))
    state.workflow = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    state.workflow.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    state.workflow.get_pool = AsyncMock(return_value=state.pool)
    state.access = credentials_handler.CredentialsHandler.__new__(credentials_handler.CredentialsHandler)
    state.access.sio, state.access.get_pool = state.workflow.sio, state.workflow.get_pool
    async def capture(_sio, _sid, response, **_kwargs):
        state.responses.append(response.model_dump())
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    monkeypatch.setattr(credentials_handler, "send_event", capture)
    state.crypto = crypto
    return state


async def operation(native):
    return await run_op.run_node_operation(node_type=NODE, operation="get_company_settings", arguments={}, user_id=USER, pool=native.pool, credential_id=CID)


async def lookup(native):
    return await run_op.run_node_lookup(node_type=NODE, field_name="contact_id", user_id=USER, pool=native.pool, credential_id=CID)


async def access(native):
    await native.access.validate_access("fixture-sid", CredentialValidateAccessRequest(request_id="fixture-access", node_type=NODE, credential_id=CID))
    return native.responses[-1]["data"]


@pytest.mark.asyncio
async def test_actual_factory_current_owner_row_and_stale_blob_tag(native):
    assert registry.NODE_REGISTRY[NODE] is s.AccuLynxNode
    assert (await operation(native))["companies"][0]["name"] == "Owned Roofing"
    assert (await lookup(native))["options"][0]["value"] == CONTACT
    assert (await access(native))["valid"] is True
    # Standalone calls have no workflow-owner fallback; every read uses the
    # current caller's ACL (also checked by the Storage boundary above).
    reads = [args for sql, args in native.sql if "FROM credentials c" in sql]
    assert reads and all(args == (CID, USER, None) for args in reads)


@pytest.mark.asyncio
async def test_actual_connect_evidence_is_bound_company_not_user_identity(native):
    verdict = await cc.validate_for_connect(credential_type="acculynx_api_key", credential_data=deepcopy(KEY), user_id=USER, pool=native.pool)
    assert verdict.ok and verdict.node_type == NODE and verdict.evidence.reachable is True
    assert verdict.evidence.samples[0].label == "Owned Roofing"
    assert s.AccuLynxNode.connection_evidence.field is None and s.AccuLynxNode.connection_evidence.identity_operation is None
    assert "private" not in str(verdict.evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["microsoft_oauth", "api_key", "", 42])
async def test_actual_foreign_row_family_denies_shaped_blob_before_provider(native, foreign):
    native.row["credential_type"] = foreign
    with pytest.raises(ValueError):
        await operation(native)
    with pytest.raises(ValueError):
        await lookup(native)
    assert (await access(native))["valid"] is False and not native.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["inaccessible", "revoked"])
async def test_actual_acl_and_revocation_precede_decryption(native, denial):
    if denial == "inaccessible":
        native.denied = True
    else:
        native.row["revoked_at"] = UPDATED
    with pytest.raises(ValueError):
        await operation(native)
    assert (await access(native))["valid"] is False and not native.calls and not native.crypto.decrypt_credential.called


@pytest.mark.asyncio
@pytest.mark.parametrize("approval", ["pending", "rejected"])
async def test_actual_stored_admission_denies_operation_picker_evidence_and_access(native, approval):
    native.approval = approval
    assert (await operation(native))["executed"] is False
    assert (await lookup(native))["executed"] is False
    evidence = await ce.collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=native.pool)
    assert evidence.reachable is None and not evidence.samples and evidence.account_label is None
    assert (await access(native))["valid"] is False and not native.calls


@pytest.mark.asyncio
async def test_actual_second_read_revocation_and_post_read_authority(native):
    native.revoke_after_first = True
    with pytest.raises(ValueError):
        await lookup(native)
    assert not native.calls
    native.revoke_after_first = False
    native.revoke_after_http = True
    assert (await access(native))["valid"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"token_version": 5}, {"owner_id": "00000000-0000-4000-8000-000000000099"}, {"approval_revision": 2}, {"credential_type": "api_key"}])
async def test_actual_post_provider_row_change_cannot_accept_stale_evidence(native, change):
    native.change_after_http = change
    assert (await access(native))["valid"] is False
    assert len(native.calls) == 1 and native.reads > 1


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["unauthed", "foreign", "pending", "rejected"])
async def test_actual_socket_picker_uses_current_session_row_and_admission(native, denial):
    if denial == "unauthed":
        native.workflow.sio.get_session = AsyncMock(return_value={})
    elif denial == "foreign":
        native.row["credential_type"] = "api_key"
    else:
        native.approval = denial
    await native.workflow.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(request_id="fixture-picker", node_type=NODE, field_name="contact_id", credential_id=CID))
    assert native.responses[-1]["data"]["success"] is False and not native.calls
