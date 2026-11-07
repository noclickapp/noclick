"""Landbot factory/run/connect/current-row/admission fixtures.

Only local repository storage, encryption and synthetic HTTP are substituted.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import landbot_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, encryption, ssrf
from wss.handlers import workflow_handler

CREDENTIAL = {"credential_type": "landbot_agent_token", "agent_token": "fixture-landbot-agent-token-89ba"}
CID = "11111111-1111-4111-8111-111111111111"
CHANNEL = {"id": 12, "name": "Fixture Channel", "active": True, "type": "landbot", "token": "private-channel-token"}


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
    row = {"credential_type": "landbot_agent_token", "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql, state = [], [], {"row": row, "blob": deepcopy(CREDENTIAL), "channels": [CHANNEL]}
    async def read(statement, *args):
        sql.append((statement, args))
        return state["row"]
    conn = SimpleNamespace(fetchrow=AsyncMock(side_effect=read))
    pool = Pool(conn)
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"])))
    monkeypatch.setattr(credentials, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"])))
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="fixture-org"))
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        assert request.url.path == "/v1/channels/" and request.url.host == "api.landbot.io"
        assert request.headers["Authorization"] == "Token " + CREDENTIAL["agent_token"]
        assert CREDENTIAL["agent_token"] not in str(request.url)
        return httpx.Response(200, json={"success": True, "total": len(state["channels"]), "channels": state["channels"]})
    actual_client = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual_client(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_registration_factory_run_uses_current_token_not_stale_payload(seams):
    assert NODE_REGISTRY["automation-landbot"] is node.LandbotNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-landbot", node_data={"config": {"operation": "list_channels"}, "credentials": {**CREDENTIAL, "agent_token": "stale-fixture-token"}, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"]["items"] == [{"id": "12", "name": "Fixture Channel", "type": "landbot", "active": True}]
    assert len(seams.calls) == 1 and seams.admission.await_count == 1
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "list_channels" and args["arguments"] == {"limit": 20, "offset": 0, "active": None, "channel_type": None}
    assert args["credential_id"] == CID and CREDENTIAL["agent_token"] not in repr(args)
    assert sum("token_version" in query for query, _ in seams.sql) >= 2


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_admission_parks_operation_and_evidence_before_provider(seams, status):
    seams.admission.return_value = {"id": "fixture-approval", "status": status, "new_request": False}
    result = await run_op.run_node_operation(node_type="automation-landbot", operation="list_channels", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and result["_halt_downstream"] is True
    evidence = await connection_evidence.collect_evidence(node_type="automation-landbot", credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert evidence.reachable is None
    assert evidence.samples == [] and evidence.account_label is None and evidence.noun == "workspace channels"
    assert seams.calls == []


async def test_actual_manual_connect_shapes_native_family_and_reports_reachability(seams):
    verdict = await credential_connect.validate_for_connect(credential_type="landbot_agent_token", credential_data={"agent_token": " " + CREDENTIAL["agent_token"] + " "}, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None
    assert verdict.credential_data == CREDENTIAL
    assert verdict.evidence.reachable is True and verdict.evidence.samples[0].label == "Fixture Channel"
    assert verdict.evidence.account_label is None
    assert len(seams.calls) == 1 and seams.admission.await_count == 0


async def test_empty_private_catalog_does_not_invent_account_identity(seams):
    seams.state["channels"] = []
    evidence = await connection_evidence.collect_evidence(node_type="automation-landbot", credential_data=CREDENTIAL, user_id="fixture-user")
    assert evidence.reachable is True and evidence.account_label is None and evidence.samples == []
    assert len(seams.calls) == 1 and seams.calls[0].headers["Authorization"].startswith("Token ")


@pytest.mark.parametrize("token", ["https://example.test/key", "YOUR_API_KEY", "bad\ncontrol", "Bearer fixture-key", "Token fixture-key"])
async def test_manual_shape_refuses_placeholder_url_or_header_before_io(seams, token):
    verdict = await credential_connect.validate_for_connect(credential_type="landbot_agent_token", credential_data={"agent_token": token}, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []


@pytest.mark.parametrize("family", [None, "landbot_apichat_token", "slack_oauth"])
async def test_current_wrong_family_refuses_stale_native_blob(seams, family):
    seams.row["credential_type"] = family
    with pytest.raises(ValueError, match="Current Landbot authority"):
        await node.LandbotNode._freshen_for_execution(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


@pytest.mark.parametrize("condition", ["absent", "revoked", "lost_access_during_resolution", "changed_token_during_resolution", "blob_missing_platform_token"])
async def test_saved_authority_loss_or_change_refuses_before_http(seams, condition):
    if condition == "absent":
        seams.state["row"] = None
    elif condition == "revoked":
        seams.row["revoked_at"] = datetime.now(timezone.utc)
    elif condition == "blob_missing_platform_token":
        seams.state["blob"] = {"credential_type": "landbot_apichat_token", "channel_token": "fixture-channel-token"}
    else:
        reads = 0
        async def read(statement, *args):
            nonlocal reads
            if "token_version" in statement:
                reads += 1
                if reads == 2:
                    return None if condition == "lost_access_during_resolution" else {**seams.row, "token_version": 8, "credential": b"changed-token-cipher"}
            return seams.row
        seams.pool.conn.fetchrow.side_effect = read
    with pytest.raises(ValueError):
        await node.LandbotNode._freshen_for_execution(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


async def test_authoritative_saved_family_overrides_only_a_stale_blob_tag(seams):
    seams.state["blob"]["credential_type"] = "stale-blob-tag"
    value = await node.LandbotNode._freshen_for_execution(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert value == CREDENTIAL and seams.calls == []


async def test_actual_lookup_preserves_admission_fingerprint_and_current_native_labels(seams):
    result = await run_op.run_node_lookup(node_type="automation-landbot", field_name="channel_id", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["options"] == [{"value": "12", "label": "Fixture Channel", "metadata": {}}]
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "__lookup__" and args["arguments"] == {"field_name": "channel_id", "context": None, "page_token": None, "search": None}
    assert len(seams.calls) == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_saved_lookup_admission_precedes_native_picker_io(seams, status):
    seams.admission.return_value = {"id": "fixture-approval", "status": status, "new_request": False}
    result = await run_op.run_node_lookup(node_type="automation-landbot", field_name="channel_id", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and result["_halt_downstream"] is True
    assert seams.calls == []


@pytest.mark.parametrize("authorized", [False, True])
async def test_workflow_owner_fallback_keeps_real_acl_and_organization(seams, authorized):
    workflow = "22222222-2222-4222-8222-222222222222"
    owner_reads = []
    async def read(statement, *args):
        seams.sql.append((statement, args))
        if "FROM workflows" in statement:
            return {"owner_id": "fixture-owner"}
        if "FROM workflow_authorized_credentials" in statement:
            assert str(args[0]) == workflow and str(args[1]) == CID
            return {"allowed": 1} if authorized else None
        if args[1] == "fixture-owner":
            owner_reads.append(args)
            return {**seams.row, "owner_id": "fixture-owner"}
        return None
    seams.pool.conn.fetchrow.side_effect = read
    if authorized:
        value = await node.LandbotNode._freshen_for_execution({**CREDENTIAL, "agent_token": "stale-fixture-token"}, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
        assert value == CREDENTIAL
        assert len(owner_reads) == 3 and all(args[2] == "fixture-org" for args in owner_reads)
    else:
        with pytest.raises(ValueError, match="Current Landbot authority"):
            await node.LandbotNode._freshen_for_execution(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
        assert owner_reads == []
    assert seams.calls == []


@pytest.mark.parametrize("payload", [{"config": {"operation": "list_channels"}, "credentials": {"agent_token": CREDENTIAL["agent_token"]}}, {"config": {"operation": "list_channels", "url": "https://foreign.example.test"}, "credentials": CREDENTIAL}, {"config": {"operation": "list_customers", "channel_id": "12", "search_by": "email"}, "credentials": CREDENTIAL}])
def test_raw_parse_and_validate_both_refuse_untyped_or_arbitrary_controls(payload):
    with pytest.raises(ValueError):
        node.LandbotNode.parse_config(payload)
    assert node.LandbotNode.validate_config(payload)["valid"] is False
