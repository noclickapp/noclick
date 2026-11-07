"""Exercise Vagaro through staging's stored and unsaved credential dispatch.

Storage, decryption, DNS and HTTP boundaries are synthetic. The real runner,
credential loader, admission and connection-evidence implementations execute.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import vagaro_node as s
from nodes.core import connection_evidence as ce, credential_connect as cc, registry, run_op
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL
from utils import credential_approval, credentials, encryption, ssrf

CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
BID = "owned~location=="
NODE = "automation-vagaro"
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
KEY = {"credential_type": "vagaro_issued_client_token", "access_token": "fixture.private.access", "region": "us04", "granted_scopes": ["read access"], "expires_at": "2026-10-06T01:00:00Z"}


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
    state = SimpleNamespace(sql=[], calls=[], responses=[], reads=0, denied=False, approval=None, revoke_after_first=False, revoke_after_http=False, empty_locations=False,
        blob={**KEY, "credential_type": "stale-forged-tag"}, row={"id": CID, "name": "Owned Business", "owner_id": USER,
            "credential_type": "vagaro_issued_client_token", "credential": b"synthetic-ciphertext", "token_version": 4, "updated_at": UPDATED,
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
    for module in (credentials, encryption):
        monkeypatch.setattr(module, "get_encryption", lambda: crypto)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.invalid")
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["8.8.8.8"]))
    monkeypatch.setattr(s, "_now", lambda: UPDATED)
    def answer(request):
        state.calls.append(request)
        assert request.url.host == "api.vagaro.com"
        assert request.headers["accessToken"] == KEY["access_token"] and "authorization" not in request.headers
        if state.revoke_after_http:
            state.row["revoked_at"] = UPDATED
        assert request.url.path == "/us04/api/v2/locations" and request.method == "POST"
        return httpx.Response(200, json={"status": 200, "responseCode": 1000, "data": {"locations": [] if state.empty_locations else [{"businessId": BID, "businessName": "Owned Location", "businessPhone": "private"}]}})
    factory = ssrf.guarded_async_client
    monkeypatch.setattr(s, "guarded_async_client", lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(answer)))
    state.crypto = crypto
    return state


async def operation(native):
    return await run_op.run_node_operation(node_type=NODE, operation="list_locations", arguments={}, user_id=USER, pool=native.pool, credential_id=CID)


async def lookup(native):
    return await run_op.run_node_lookup(node_type=NODE, field_name="business_id", user_id=USER, pool=native.pool, credential_id=CID)


@pytest.mark.asyncio
async def test_actual_factory_owner_row_and_stale_blob_type(native):
    assert registry.NODE_REGISTRY[NODE] is s.VagaroNode
    assert (await operation(native))["locations"][0]["businessName"] == "Owned Location"
    assert (await lookup(native))["options"][0]["value"] == BID
    assert native.reads >= 2
    assert all(args == (CID, USER, None) for sql, args in native.sql if "FROM credentials c" in sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_actual_connect_has_owned_samples_or_empty_reachability_without_fake_identity(native, empty):
    native.empty_locations = empty
    verdict = await cc.validate_for_connect(credential_type="vagaro_issued_client_token", credential_data=deepcopy(KEY), user_id=USER, pool=native.pool)
    assert verdict.ok and verdict.node_type == NODE and verdict.evidence.reachable is True
    if empty:
        assert verdict.evidence.account_label is None and not verdict.evidence.samples
    else:
        assert verdict.evidence.samples[0].label == "Owned Location"
    assert s.VagaroNode.connection_evidence.field is None and s.VagaroNode.connection_evidence.identity_operation is None


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["microsoft_oauth", "api_key", "", 42])
async def test_actual_foreign_family_denies_shaped_blob_before_provider(native, foreign):
    native.row["credential_type"] = foreign
    with pytest.raises(ValueError):
        await operation(native)
    with pytest.raises(ValueError):
        await lookup(native)
    assert not native.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["inaccessible", "revoked"])
async def test_actual_acl_and_revocation_before_decryption(native, denial):
    if denial == "inaccessible":
        native.denied = True
    else:
        native.row["revoked_at"] = UPDATED
    with pytest.raises(ValueError):
        await operation(native)
    assert not native.calls and not native.crypto.decrypt_credential.called


@pytest.mark.asyncio
@pytest.mark.parametrize("approval", ["pending", "rejected"])
async def test_stored_native_admission_blocks_operation_picker_and_evidence(native, approval):
    native.approval = approval
    assert (await operation(native))["executed"] is False
    assert (await lookup(native))["executed"] is False
    evidence = await ce.collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=native.pool)
    assert evidence.reachable is None and not evidence.samples and evidence.account_label is None
    assert not native.calls


@pytest.mark.asyncio
async def test_credential_access_hook_uses_native_location_read(native):
    result = await s.VagaroNode.validate_credential_access(deepcopy(KEY))
    assert result == {"valid": True, "name": "Owned Location"}
    assert len(native.calls) == 1 and native.calls[0].url.params["pageSize"] == "5"


@pytest.mark.asyncio
async def test_saved_lookup_rechecks_current_row_before_dispatch(native):
    native.revoke_after_first = True
    with pytest.raises(ValueError):
        await lookup(native)
    assert not native.calls
