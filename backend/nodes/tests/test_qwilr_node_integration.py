"""Qwilr contracts through staging factory, admission, picker and connect seams."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from nodes import qwilr_node as Q
from nodes.tests.test_qwilr_node_mock import AUTH, USER, PAGE, BLOCK, world
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL

CID = "00000000-0000-4000-8000-000000000042"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
WF = "00000000-0000-4000-8000-000000000004"


class Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *_): return False


class Storage:
    def __init__(self):
        self.row = {"credential": b"synthetic-only", "credential_type": Q.FAMILY, "owner_id": OWNER, "token_version": 7,
            "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "revoked_at": None, "approval_revision": 0}
        self.grant, self.calls = deepcopy(AUTH), []
        self.access = {(USER, ORG), (USER, None), (OWNER, ORG)}
        self.current_org, self.workflow_owner, self.workflow_authorized = ORG, OWNER, True
    def acquire(self): return Context(self)
    async def fetchrow(self, sql, *values):
        self.calls.append((sql, values))
        if sql == PRIMARY_ORG_SQL: return {"organization_id": self.current_org} if self.current_org else None
        if sql.startswith("SELECT owner_id,") and "FROM workflows" in sql: return {"owner_id": self.workflow_owner} if self.workflow_owner else None
        if "SELECT 1 FROM workflow_authorized_credentials" in sql: return {"authorized": 1} if self.workflow_authorized else None
        assert "FROM credentials c" in sql and credential_access_predicate() in sql and str(values[0]) == CID
        principal, org = str(values[1]), values[2]
        allowed = (principal, org) in self.access
        if len(values) == 6:
            caller, current, workflow = values[3:]
            assert caller == USER and "workflow_authorized_credentials" in sql
            if principal != caller: allowed = allowed and workflow == WF and self.workflow_owner == principal and self.workflow_authorized
            if current: allowed = allowed and org == self.current_org
        return deepcopy(self.row) if allowed and self.row else None
    async def fetchval(self, sql, *values):
        assert "workflow_authorized_credentials" in sql
        return None
    async def execute(self, *_): raise AssertionError("No account-token persistence or refresh is allowed")


@pytest.fixture
def storage(monkeypatch):
    value = Storage(); value.crypto = MagicMock()
    value.crypto.decrypt_credential.side_effect = lambda _: deepcopy(value.grant)
    value.crypto.encrypt_credential.side_effect = AssertionError("No account-token persistence")
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: value.crypto)
    monkeypatch.setattr("utils.credentials.get_encryption", lambda: value.crypto)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: value)
    monkeypatch.setattr("utils.credentials.get_native_pool", lambda: value)
    return value


@pytest.fixture
def admission(monkeypatch):
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_approval
    admit = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admit)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://synthetic.invalid")
    return admit


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_real_registered_operation_is_pinned_and_owner_fallback_is_gated(storage, world, admission, authorized):
    from nodes.core.run_op import run_node_operation
    storage.access = {(OWNER, ORG)}; storage.workflow_authorized = authorized
    if authorized:
        result = await run_node_operation(node_type=Q.NODE_TYPE, operation="get_page", arguments={"operation": "create_draft_from_template", "page_id": PAGE}, user_id=USER, credential_id=CID, workflow_id=WF, organization_id=ORG, pool=storage)
        assert result["record"]["id"] == PAGE and all(r.method == "GET" for r in world.calls)
        assert AUTH["api_token"] not in str(admission.call_args)
    else:
        with pytest.raises(ValueError): await run_node_operation(node_type=Q.NODE_TYPE, operation="get_page", arguments={"page_id": PAGE}, user_id=USER, credential_id=CID, workflow_id=WF, organization_id=ORG, pool=storage)
        assert world.calls == []; admission.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,expected", [("pending", "pending_approval"), ("rejected", "rejected")])
async def test_real_action_picker_and_collector_stop_at_stored_admission(storage, world, admission, decision, expected):
    from nodes.core.run_op import run_node_operation, run_node_lookup
    from nodes.core.connection_evidence import collect_evidence
    admission.return_value = {"id": "synthetic-approval", "status": decision, "new_request": False}
    result = await run_node_operation(node_type=Q.NODE_TYPE, operation="get_page", arguments={"page_id": PAGE}, credential_id=CID, user_id=USER, organization_id=ORG, pool=storage)
    picker = await run_node_lookup(node_type=Q.NODE_TYPE, field_name="page_id", credential_id=CID, user_id=USER, organization_id=ORG, pool=storage)
    evidence = await collect_evidence(node_type=Q.NODE_TYPE, credential_id=CID, user_id=USER, organization_id=ORG, pool=storage)
    assert result["status"] == picker["status"] == expected
    assert evidence.reachable is None and evidence.samples == [] and evidence.account_label is None and world.calls == []
    assert AUTH["api_token"] not in str(admission.call_args_list)


@pytest.mark.asyncio
async def test_actual_picker_connect_and_empty_account_do_not_invent_identity(storage, world, admission, monkeypatch):
    from nodes.core.run_op import run_node_lookup
    from nodes.core import credential_connect, connection_evidence
    result = await run_node_lookup(node_type=Q.NODE_TYPE, field_name="saved_block_id", credential_id=CID, user_id=USER, organization_id=ORG, pool=storage)
    assert result["options"] == [{"value": BLOCK, "label": "Owned saved block"}]
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=Q.FAMILY, credential_data=deepcopy(AUTH), user_id=USER)
    assert verdict.ok and verdict.credential_data == AUTH and verdict.evidence.reachable is True
    assert verdict.evidence.samples[0].label == "Owned fixture draft" and verdict.evidence.account_label is None
    world.raw = b'{"data":[],"nextCursor":null}'
    evidence = await connection_evidence.collect_evidence(node_type=Q.NODE_TYPE, credential_data=AUTH, user_id=USER)
    assert evidence.reachable is True and evidence.samples == [] and evidence.account_label is None
    assert all(r.url.path in {"/v1/pages", "/v1/blocks/saved"} for r in world.calls)


def test_actual_factory_foreign_row_cannot_be_reconciled_by_attachment_key(world):
    from nodes.core.registry import NodeFactory
    data = {"credentials": {**AUTH, "credential_type": "slack_oauth"}, "credentialIds": {Q.FAMILY: CID}, "credential_id": CID, "config": {"operation": "list_pages"}}
    with pytest.raises(ValueError): NodeFactory.create_node(node_id="fixture", node_type=Q.NODE_TYPE, node_data=data, sio=None, sid=None, user_id=USER)
    assert world.calls == []


@pytest.mark.asyncio
async def test_actual_agent_scope_and_resource_creator_contract(world, monkeypatch):
    from nodes.agent.node_op_tools import build_node_op_tools, resource_creators
    from nodes.core import run_op
    _, configs = build_node_op_tools(Q.NODE_TYPE, [{"operation": "get_page", "field_scopes": {"page_id": [PAGE]}}], node_id="fixture", credential_id=CID)
    info = next(value for value in configs.values() if value["tool_type"] == "node_op")
    resolve = AsyncMock(side_effect=AssertionError("Refuse outside-page scope before credential resolution"))
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", resolve)
    result = await run_op.run_node_op_tool(info, {"page_id": "z" * 24}, user_id=USER, organization_id=ORG, workflow_id=WF)
    assert result["success"] is False; resolve.assert_not_awaited(); assert world.calls == []
    assert set(resource_creators(Q.NODE_TYPE)) == {("create_draft_from_template", "qwilr_page", "record.id"), ("create_draft_from_blocks", "qwilr_page", "record.id")}


def test_public_provisioning_discovery_has_native_token_only():
    from utils import credential_request_routes as R
    method = R._get_credential_method(Q.FAMILY)
    assert method["credential_type"] == Q.FAMILY and method["is_oauth"] is False and method["oauth_scopes"] == []
    assert [(field["name"], field["type"]) for field in method["credential_fields"]] == [("api_token", "password")]
    assert "live account" in method["instructions"] and R._get_oauth_provider(Q.FAMILY) is None
