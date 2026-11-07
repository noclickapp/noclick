"""SignalWire factory, connect, stored credential resolution and admission.

Only local repository storage, encryption and synthetic HTTP are substituted.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import signalwire_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials as credential_utils, ssrf
from wss.handlers import workflow_handler

CREDENTIAL = {"credential_type": node.TYPE, "space_url": "https://fixture.signalwire.com", "project_id": "11111111-1111-4111-8111-111111111111", "api_token": "fixture-api-token"}
CID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def ensure_native_db_pool():
    yield


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture
def seams(monkeypatch):
    row = {"credential_type": node.TYPE, "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql, state = [], [], {"row": row, "blob": deepcopy(CREDENTIAL), "project_override": None}
    async def read(statement, *args):
        sql.append((statement, args))
        return state["row"]
    pool = Pool(SimpleNamespace(fetchrow=AsyncMock(side_effect=read)))
    monkeypatch.setattr(credential_utils, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"])))
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="fixture-org"))
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        current = node.credential_value(state["blob"])
        assert request.url.path == "/api/projects/" + current.project_id
        assert str(request.url).startswith(current.space_url + "/")
        assert request.headers["Authorization"] == node.auth_header(current)
        assert "api_token" not in request.url.params
        return httpx.Response(200, json=state["project_override"] if state["project_override"] is not None else {"id": current.project_id, "name": "Fixture project", "private_signing_key": "excluded"})
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_factory_uses_current_row_not_stale_supplied_token(seams):
    assert NODE_REGISTRY["automation-signalwire"] is node.SignalWireNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-signalwire", node_data={"config": {"operation": "get_project"}, "credentials": {**CREDENTIAL, "api_token": "stale-api-token"}, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"] == {"id": CREDENTIAL["project_id"], "name": "Fixture project"}
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "get_project" and args["arguments"] == {} and args["credential_id"] == CID
    assert len(seams.calls) == 1 and any("FROM credentials" in query for query, _ in seams.sql)


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_run_and_evidence_admission_park_before_provider(seams, status):
    seams.admission.return_value = {"id": "fixture-approval", "status": status, "new_request": False}
    result = await run_op.run_node_operation(node_type="automation-signalwire", operation="get_project", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and result["_halt_downstream"] is True
    evidence = await connection_evidence.collect_evidence(node_type="automation-signalwire", credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert evidence.reachable is None and node.SignalWireNode.connection_evidence.proves == "reachability" and evidence.account_label is None and evidence.samples == []
    assert evidence.noun == "SignalWire project metadata" and seams.calls == []


async def test_real_manual_connect_shapes_family_and_preserves_reachability_claim(seams):
    raw = {key: value for key, value in CREDENTIAL.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPE, credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None and verdict.credential_data == CREDENTIAL
    assert verdict.evidence.reachable is True and node.SignalWireNode.connection_evidence.proves == "reachability" and verdict.evidence.account_label is None
    assert len(seams.calls) == 1 and seams.admission.await_count == 0


@pytest.mark.parametrize("change", [{"space_url": "http://fixture.signalwire.com"}, {"project_id": "AccountSID"}, {"api_token": ""}, {"api_token": "pat_personal"}])
async def test_actual_manual_connect_rejects_malformed_auth_before_io(seams, change):
    supplied = {key: value for key, value in {**CREDENTIAL, **change}.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPE, credential_data=supplied, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []


@pytest.mark.parametrize("payload", [{}, {"id": "22222222-2222-4222-8222-222222222222", "name": "Foreign"}])
async def test_empty_or_wrong_project_does_not_produce_verified_identity(seams, payload):
    seams.state["project_override"] = payload
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPE, credential_data=CREDENTIAL, user_id="fixture-user", pool=seams.pool)
    assert verdict.evidence.reachable is not True and verdict.verified_metadata() == {} and verdict.evidence.account_label is None
    assert len(seams.calls) == 1


@pytest.mark.parametrize("family", ["twilio_account_auth", "signalwire_personal_token", "slack_oauth"])
async def test_wrong_current_family_prevents_stale_blob_use(seams, family):
    seams.row["credential_type"] = family
    with pytest.raises(ValueError, match="typed SignalWire"):
        await node.SignalWireNode._load_current_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


@pytest.mark.parametrize("condition", ["absent", "revoked"])
async def test_unavailable_stored_credential_stops_before_io(seams, condition):
    if condition == "absent":
        seams.state["row"] = None
    else:
        seams.row["revoked_at"] = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="unavailable"):
        await node.SignalWireNode._load_current_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


async def test_current_space_and_project_replace_stale_caller_scope(seams):
    seams.state["blob"] = {**CREDENTIAL, "space_url": "https://rotated.signalwire.com", "project_id": "22222222-2222-4222-8222-222222222222", "api_token": "rotated-api-token"}
    result = await run_op.run_node_operation(node_type="automation-signalwire", operation="get_project", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["status"] == "success" and seams.calls[0].url.host == "rotated.signalwire.com"
    assert result["data"]["id"] == seams.state["blob"]["project_id"]


async def test_real_saved_picker_fingerprint_parks_before_provider(seams):
    seams.admission.return_value = {"id": "fixture-approval", "status": "pending", "new_request": False}
    result = await run_op.run_node_lookup(node_type="automation-signalwire", field_name="phone_number_id", context={}, page_token=None, search="Fixture", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and seams.calls == []
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "__lookup__" and args["arguments"] == {"field_name": "phone_number_id", "context": {}, "page_token": None, "search": "Fixture"}


async def test_legacy_validation_defers_provider_verification_to_evidence(seams):
    result = await node.SignalWireNode.validate_credential_access(CREDENTIAL)
    assert result["valid"] is None
    assert seams.calls == []


async def test_stored_credential_requires_authorized_caller(seams):
    with pytest.raises(ValueError, match="authorized caller"):
        await node.SignalWireNode.freshen_credential(CREDENTIAL, credential_id=CID, pool=seams.pool)
    assert seams.calls == []
