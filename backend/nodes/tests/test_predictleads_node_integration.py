"""PredictLeads saved-row authority and factory tests with synthetic storage and HTTPS."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from nodes import predictleads_node as p
from nodes.tests.test_predictleads_node_mock import wire, blob, subscription, USER
from nodes.core.run_op import run_node_operation, run_node_lookup
from repositories.credentials import credential_access_predicate
from utils import credentials

CID = "00000000-0000-4000-8000-000000000042"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
WF = "00000000-0000-4000-8000-000000000004"
UPDATED = datetime(2026, 10, 7, tzinfo=timezone.utc)


class Pool:
    def __init__(self):
        self.row = {"id": CID, "name": "Fixture key", "credential_type": p.FAMILY,
            "credential": b"synthetic-row", "metadata": {}, "created_at": UPDATED,
            "updated_at": UPDATED, "owner_id": USER, "token_version": 3,
            "approval_revision": 1, "revoked_at": None}
        self.allowed, self.authorized, self.calls = {(USER, None), (USER, ORG)}, False, []
    async def fetchval(self, *_): return None
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "workflow_authorized_credentials" in sql:
            assert tuple(map(str, args)) == (WF, CID)
            return {"authorized": 1} if self.authorized else None
        assert "FROM credentials c" in sql and credential_access_predicate() in sql
        assert args[0] == CID
        return deepcopy(self.row) if (args[1], args[2]) in self.allowed else None


@pytest.fixture
def storage(monkeypatch):
    state = SimpleNamespace(pool=Pool(), blob=blob())
    encryption = MagicMock()
    encryption.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    state.decrypt = encryption.decrypt_credential
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: encryption)
    monkeypatch.setattr(credentials, "get_encryption", lambda: encryption)
    return state


async def bound(state, **context):
    return await p.PredictLeadsNode._freshen_current_credential(state.blob, pool=state.pool,
        user_id=USER, credential_id=CID, organization_id=context.get("organization_id"), workflow_id=context.get("workflow_id"))


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value", [("credential_type", "legacy_app_id"), ("revoked_at", UPDATED),
    ("owner_id", None), ("token_version", True), ("token_version", 0), ("approval_revision", False),
    ("updated_at", datetime(2026, 1, 1))])
async def test_native_current_row_invalidity_precedes_native_decrypt_and_request(storage, wire, key, value):
    storage.pool.row[key] = value
    with pytest.raises(ValueError): await bound(storage)
    storage.decrypt.assert_not_called()
    assert not wire.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("key,value", [("owner_id", OWNER), ("token_version", 4), ("approval_revision", 2),
    ("revoked_at", UPDATED), ("credential_type", "slack_oauth"), ("credential", b"rotated-synthetic-row")])
async def test_bound_current_authority_race_rejects_before_second_decrypt(storage, wire, key, value):
    current = await bound(storage)
    storage.decrypt.reset_mock()
    storage.pool.row[key] = value
    with pytest.raises(ValueError): await p.check_subscription(current)
    storage.decrypt.assert_not_called()
    assert not wire.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["after_headers", "after_body"])
async def test_actual_response_acceptance_revalidates_current_authority(storage, wire, race):
    current = await bound(storage)
    wire.queue = [subscription()]
    def revoke():
        storage.decrypt.reset_mock()
        storage.pool.row["revoked_at"] = UPDATED
    setattr(wire, race, revoke)
    with pytest.raises(ValueError): await p.check_subscription(current)
    storage.decrypt.assert_not_called()
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_raw_bound_marker_and_saved_company_credit_grants_cannot_be_replaced(storage, wire):
    current = await bound(storage)
    with pytest.raises(ValueError, match="authority was lost"): await p.current_credential(dict(current))
    storage.blob["allow_credit_reads"] = False
    with pytest.raises(ValueError, match="grants changed"): await p.current_credential(current)
    assert not wire.calls


@pytest.mark.asyncio
async def test_current_org_shared_access_and_loss_use_actual_canonical_predicate(storage, wire):
    current = await bound(storage, organization_id=ORG)
    assert current.authority.principal_id == USER and current.authority.organization_id == ORG
    storage.pool.allowed = {(USER, None)}
    storage.decrypt.reset_mock()
    with pytest.raises(ValueError, match="access denied"): await p.current_credential(current)
    assert storage.pool.calls[-1][1] == (CID, USER, ORG)
    storage.decrypt.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("positive", [False, True])
async def test_positive_stored_workflow_authorization_required_for_owner_fallback(storage, monkeypatch, positive):
    storage.pool.allowed, storage.pool.authorized = {(OWNER, ORG)}, positive
    storage.pool.row["owner_id"] = OWNER
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value=OWNER))
    if positive:
        current = await bound(storage, organization_id=ORG, workflow_id=WF)
        assert current.authority.caller_id == USER and current.authority.principal_id == OWNER
        storage.decrypt.assert_called_once()
    else:
        with pytest.raises(ValueError): await bound(storage, organization_id=ORG, workflow_id=WF)
        storage.decrypt.assert_not_called()




@pytest.mark.asyncio
async def test_actual_agent_picker_lost_current_access_remains_error(storage, wire, monkeypatch):
    from utils import credential_approval as policy
    monkeypatch.setattr(policy, "admit_lookup", AsyncMock(return_value=None))
    storage.pool.allowed = set()
    with pytest.raises(ValueError):
        await run_node_lookup(node_type=p.NODE_TYPE, field_name="company", context={},
            user_id=USER, pool=storage.pool, credential_id=CID, organization_id=ORG)
    assert not wire.calls






@pytest.mark.asyncio
async def test_actual_factory_keeps_raw_bound_context_and_rejects_late_grant_change(storage, wire):
    from nodes.core.registry import NodeFactory
    current = await bound(storage)
    node = NodeFactory.create_node("fixture-node", p.NODE_TYPE,
        {"config": {"operation": "check_connection"}, "credentials": current, "credential_id": CID, "_approval_pool": storage.pool}, user_id=USER)
    assert node.node_data["credentials"] is current and isinstance(node.config.config, p.CheckConnection)
    wire.queue = [subscription()]
    positive = await node.execute({"operation": "follow_company"})
    assert positive["witness_verified"] and positive["documented_credits"] == 0
    storage.blob["api_token"] = "synthetic-rotated-token"
    with pytest.raises(ValueError, match="grants changed"): await node.execute({})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_actual_agent_picker_authoritative_local_scope_is_not_injected(storage, wire, monkeypatch):
    from utils import credential_approval as policy
    monkeypatch.setattr(policy, "admit_lookup", AsyncMock(return_value=None))
    result = await run_node_lookup(node_type=p.NODE_TYPE, field_name="company", context={"allowed_companies_json": '["injected.example"]'},
        user_id=USER, pool=storage.pool, credential_id=CID, organization_id=ORG)
    assert [item["value"] for item in result["options"]] == ["fixture.example", "second.example"]
    assert not wire.calls


@pytest.mark.asyncio
async def test_freshen_hook_accepts_base_keyword_and_binds_saved_authority(storage):
    current = await p.PredictLeadsNode.freshen_credential(
        credential_data=storage.blob, pool=storage.pool, user_id=USER, credential_id=CID)
    assert isinstance(current, p.BoundCredential)
    assert current.authority.caller_id == USER
    assert current.authority.credential_id == CID
    storage.pool.row["revoked_at"] = UPDATED
    with pytest.raises(ValueError):
        await p.PredictLeadsNode.freshen_credential(credential_data=current)
