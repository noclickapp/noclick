"""Unrun actual repository/factory/admission/picker/connect seam fixtures."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from nodes import formbuilder123_node as F
from nodes.tests.test_formbuilder123_node_mock import AUTH, USER, world
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
        self.row = {"credential": b"synthetic-only", "credential_type": F.FAMILY, "owner_id": OWNER, "token_version": 7,
            "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "revoked_at": None, "approval_revision": 0}
        self.grant, self.calls = deepcopy(AUTH), []
        self.access = {(USER, ORG), (USER, None), (OWNER, ORG)}
        self.current_org, self.workflow_owner, self.workflow_authorized = ORG, OWNER, True
    def acquire(self): return Context(self)
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if sql == PRIMARY_ORG_SQL: return {"organization_id": self.current_org} if self.current_org else None
        if "FROM workflows WHERE id" in sql: return {"owner_id": self.workflow_owner, "system": None} if self.workflow_owner else None
        if "SELECT 1 FROM workflow_authorized_credentials" in sql: return {"authorized": 1} if self.workflow_authorized else None
        assert "FROM credentials c" in sql and credential_access_predicate() in sql and str(args[0]) == CID
        principal, org = str(args[1]), args[2]
        allowed = (principal, org) in self.access
        if len(args) == 6:
            caller, current, workflow = args[3:]
            assert caller == USER and "workflow_authorized_credentials" in sql
            if principal != caller: allowed = allowed and workflow == WF and self.workflow_owner == principal and self.workflow_authorized
            if current: allowed = allowed and org == self.current_org
        return deepcopy(self.row) if allowed and self.row else None
    async def fetchval(self, *_): return None
    async def execute(self, *_): raise AssertionError("Supplied v2 tokens must not be persisted or rotated by the native node")


@pytest.fixture
def storage(monkeypatch):
    value = Storage(); value.crypto = MagicMock()
    value.crypto.decrypt_credential.side_effect = lambda _b: deepcopy(value.grant)
    value.crypto.encrypt_credential.side_effect = AssertionError("No token rotation or persistence is configured")
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
@pytest.mark.parametrize("bad", ["missing", "foreign", "revoked", "version", "timestamp", "access"])
async def test_canonical_current_row_refuses_before_decrypt_and_token_transport(storage, world, bad):
    if bad == "missing": storage.row = None
    elif bad == "foreign": storage.row["credential_type"] = "slack_oauth"
    elif bad == "revoked": storage.row["revoked_at"] = datetime.now(timezone.utc)
    elif bad == "version": storage.row["token_version"] = True
    elif bad == "timestamp": storage.row["updated_at"] = "invalid"
    else: storage.access.clear()
    with pytest.raises(ValueError): await F.FormBuilder123Node._freshen_saved_credential(AUTH, pool=storage, user_id=USER, credential_id=CID, organization_id=ORG)
    storage.crypto.decrypt_credential.assert_not_called(); assert world.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "org", "family", "version", "access", "region", "token"])
async def test_saved_read_or_write_cannot_accept_changed_authority_after_response(storage, world, change):
    bound = await F.FormBuilder123Node.freshen_credential(AUTH, pool=storage, user_id=USER, credential_id=CID)
    def mutate(_request):
        world.after_request = None
        if change == "owner": storage.row["owner_id"] = USER
        elif change == "org": storage.current_org = OWNER
        elif change == "family": storage.row["credential_type"] = "slack_oauth"
        elif change == "version": storage.row["token_version"] += 1
        elif change == "access": storage.access.clear()
        elif change == "region": storage.grant["region"] = "eu"
        else: storage.grant["token"] = "changed-token"
    world.after_request = mutate
    with pytest.raises(ValueError): await F.records(bound, {"operation": "rename_form", "form_id": "1", "name": "Must not write"})
    assert len(world.calls) == 1 and world.calls[0].method == "GET"
    storage.crypto.encrypt_credential.assert_not_called()


@pytest.mark.asyncio
async def test_personal_org_none_current_context_and_marker_copy_are_distinct(storage, world):
    bound = await F.FormBuilder123Node._freshen_saved_credential(AUTH, pool=storage, user_id=USER, credential_id=CID, organization_id=None)
    assert bound.snapshot[0].organization_id is None and bound.snapshot[0].current_organization is False
    with pytest.raises(ValueError): await F.FormBuilder123Node.load_field_options("form_id", dict(bound))
    assert world.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_actual_registered_factory_pins_operation_and_gates_owner_fallback(storage, world, admission, authorized):
    from nodes.core.run_op import run_node_operation
    storage.access = {(OWNER, ORG)}; storage.workflow_authorized = authorized
    if authorized:
        output = await run_node_operation(node_type=F.NODE_TYPE, operation="get_form", arguments={"operation": "deactivate_form", "form_id": "1"}, user_id=USER, credential_id=CID, workflow_id=WF, organization_id=ORG, pool=storage)
        assert output["record"]["id"] == "1" and all(r.method == "GET" for r in world.calls)
        assert AUTH["token"] not in str(admission.call_args)
    else:
        with pytest.raises(ValueError): await run_node_operation(node_type=F.NODE_TYPE, operation="get_form", arguments={"form_id": "1"}, user_id=USER, credential_id=CID, workflow_id=WF, organization_id=ORG, pool=storage)
        assert world.calls == []; admission.assert_not_awaited()




@pytest.mark.asyncio
async def test_actual_stored_picker_connect_shape_and_honest_protected_form_evidence(storage, world, admission, monkeypatch):
    from nodes.core.run_op import run_node_lookup
    from nodes.core import credential_connect, connection_evidence
    result = await run_node_lookup(node_type=F.NODE_TYPE, field_name="field_id", context={"form_id": "1"}, credential_id=CID, user_id=USER, organization_id=ORG, pool=storage)
    assert result["options"] == [{"value": "4", "label": "Fixture field"}]
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=F.FAMILY, credential_data=deepcopy(AUTH), user_id=USER)
    assert verdict.ok and verdict.credential_data == AUTH and verdict.evidence.reachable is True
    assert verdict.evidence.samples[0].label == "Fixture form" and verdict.evidence.account_label is None
    assert (await F.FormBuilder123Node.validate_credential_access(AUTH))["valid"] is None
