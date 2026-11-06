"""Unrun actual Cliniko factory/run/connect/current-row/admission fixtures.

Only local repository storage, encryption and synthetic HTTP are substituted.
"""
from contextlib import asynccontextmanager
import base64
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import cliniko_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials as credential_utils, encryption, ssrf
from wss.handlers import workflow_handler

CREDENTIAL = {"credential_type": "cliniko_api_key", "api_key": "fixture-cliniko-key-uk2", "admin_contact_email": "admin@example.test", "shard": "uk2"}
CID = "11111111-1111-4111-8111-111111111111"
BUSINESS = {"id": "12", "business_name": "Fixture Business", "contact_information": "private-phone", "additional_information": "private-notes"}


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
    row = {"credential_type": "cliniko_api_key", "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql, state = [], [], {"row": row, "blob": deepcopy(CREDENTIAL), "businesses": [BUSINESS]}
    async def read(statement, *args):
        sql.append((statement, args))
        return state["row"]
    conn = SimpleNamespace(fetchrow=AsyncMock(side_effect=read))
    pool = Pool(conn)
    decryptor = lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"]))
    monkeypatch.setattr(encryption, "get_encryption", decryptor)
    monkeypatch.setattr(credential_utils, "get_encryption", decryptor)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="fixture-org"))
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        assert request.url.path == "/v1/businesses" and request.url.host == "api.uk2.cliniko.com"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode((CREDENTIAL["api_key"] + ":").encode()).decode()
        assert request.headers["User-Agent"] == "NoClick (admin@example.test)"
        assert CREDENTIAL["api_key"] not in str(request.url)
        return httpx.Response(200, json={"total_entries": len(state["businesses"]), "businesses": state["businesses"], "links": {}})
    actual_client = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual_client(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_registration_factory_run_uses_current_token_not_stale_payload(seams):
    assert NODE_REGISTRY["automation-cliniko"] is node.ClinikoNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-cliniko", node_data={"config": {"operation": "list_businesses"}, "credentials": {**CREDENTIAL, "api_key": "stale-fixture-key-uk2"}, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"]["items"] == [{"id": "12", "business_name": "Fixture Business", "name": "Fixture Business"}]
    assert len(seams.calls) == 1 and seams.admission.await_count == 1
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "list_businesses" and args["arguments"] == {"page": 1, "per_page": 50}
    assert args["credential_id"] == CID and CREDENTIAL["api_key"] not in repr(args)
    assert sum("token_version" in query for query, _ in seams.sql) >= 2


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_admission_parks_operation_and_evidence_before_provider(seams, status):
    seams.admission.return_value = {"id": "fixture-approval", "status": status, "new_request": False}
    result = await run_op.run_node_operation(node_type="automation-cliniko", operation="list_businesses", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and result["_halt_downstream"] is True
    evidence = await connection_evidence.collect_evidence(node_type="automation-cliniko", credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert evidence.reachable is None and evidence.proves == "reachability"
    assert evidence.samples == [] and evidence.account_label is None and evidence.noun == "business metadata"
    assert seams.calls == []


async def test_actual_manual_connect_shapes_native_family_and_reports_reachability(seams):
    verdict = await credential_connect.validate_for_connect(credential_type="cliniko_api_key", credential_data={"api_key": " " + CREDENTIAL["api_key"] + " ", "admin_contact_email": CREDENTIAL["admin_contact_email"]}, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None
    assert verdict.credential_data == CREDENTIAL
    assert verdict.evidence.reachable is True and verdict.evidence.samples[0].label == "Fixture Business"
    assert verdict.evidence.proves == "reachability" and verdict.evidence.account_label is None
    assert len(seams.calls) == 1 and seams.admission.await_count == 0


async def test_empty_private_catalog_does_not_invent_account_identity(seams):
    seams.state["businesses"] = []
    evidence = await connection_evidence.collect_evidence(node_type="automation-cliniko", credential_data=CREDENTIAL, user_id="fixture-user")
    assert evidence.reachable is True and evidence.account_label is None and evidence.samples == []
    assert len(seams.calls) == 1 and seams.calls[0].headers["Authorization"].startswith("Basic ")


@pytest.mark.parametrize("token", ["https://example.test/key", "YOUR_API_KEY", "bad\ncontrol", "Bearer fixture-key", "Token fixture-key"])
async def test_manual_shape_refuses_placeholder_url_or_header_before_io(seams, token):
    verdict = await credential_connect.validate_for_connect(credential_type="cliniko_api_key", credential_data={"api_key": token, "admin_contact_email": CREDENTIAL["admin_contact_email"]}, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []


@pytest.mark.parametrize("family", [None, "other_provider_api_key", "slack_oauth"])
async def test_current_wrong_family_refuses_stale_native_blob(seams, family):
    seams.row["credential_type"] = family
    with pytest.raises(ValueError, match="Current Cliniko authority"):
        await node.ClinikoNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


@pytest.mark.parametrize("condition", ["absent", "revoked", "lost_access_during_resolution", "changed_token_during_resolution", "blob_missing_api_key"])
async def test_saved_authority_loss_or_change_refuses_before_http(seams, condition):
    if condition == "absent":
        seams.state["row"] = None
    elif condition == "revoked":
        seams.row["revoked_at"] = datetime.now(timezone.utc)
    elif condition == "blob_missing_api_key":
        seams.state["blob"] = {"credential_type": "other_provider_api_key", "channel_token": "fixture-channel-token"}
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
        await node.ClinikoNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


async def test_authoritative_saved_family_overrides_only_a_stale_blob_tag(seams):
    seams.state["blob"]["credential_type"] = "stale-blob-tag"
    value = await node.ClinikoNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert value == CREDENTIAL and seams.calls == []


async def test_current_saved_issued_key_and_shard_override_stale_caller_scope(seams):
    seams.state["blob"] = {**CREDENTIAL, "api_key": "fixture-rotated-key-us1", "shard": "us1"}
    value = await node.ClinikoNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert value["api_key"] == "fixture-rotated-key-us1" and value["shard"] == "us1"
    assert node.base_url(node.credential_value(value)) == "https://api.us1.cliniko.com/v1"
    assert seams.calls == []


async def test_actual_lookup_preserves_admission_fingerprint_and_current_native_labels(seams):
    result = await run_op.run_node_lookup(node_type="automation-cliniko", field_name="business_id", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["options"] == [{"value": "12", "label": "Fixture Business", "metadata": {}}]
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "__lookup__" and args["arguments"] == {"field_name": "business_id", "context": None, "page_token": None, "search": None}
    assert len(seams.calls) == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_saved_lookup_admission_precedes_native_picker_io(seams, status):
    seams.admission.return_value = {"id": "fixture-approval", "status": status, "new_request": False}
    result = await run_op.run_node_lookup(node_type="automation-cliniko", field_name="business_id", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and result["_halt_downstream"] is True
    assert seams.calls == []


async def test_trusted_post_connect_reads_native_evidence_and_rechecks_acceptance(seams):
    from nodes.core.credential_validation import CredentialValidationContext
    context = await CredentialValidationContext.create(credential_id=CID, node_type="automation-cliniko", user_id="fixture-user", pool=seams.pool)
    result = await node.ClinikoNode.validate_credential_access(CREDENTIAL, validation_context=context)
    await context.accept(result)
    assert result == {"valid": True} and len(seams.calls) == 1
    seams.row["approval_revision"] += 1
    with pytest.raises(ValueError, match="authority changed"):
        await context.accept(result)


async def test_forged_validation_context_cannot_probe(seams):
    with pytest.raises(ValueError, match="trusted current authority"):
        await node.ClinikoNode.validate_credential_access(CREDENTIAL, validation_context={"owner_id": "fixture-user"})
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
        value = await node.ClinikoNode.freshen_credential({**CREDENTIAL, "api_key": "stale-fixture-key-uk2"}, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
        assert value == CREDENTIAL
        assert len(owner_reads) == 3 and all(args[2] == "fixture-org" for args in owner_reads)
    else:
        with pytest.raises(ValueError, match="Current Cliniko authority"):
            await node.ClinikoNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
        assert owner_reads == []
    assert seams.calls == []


@pytest.mark.parametrize("payload", [{"config": {"operation": "list_businesses"}, "credentials": {"api_key": CREDENTIAL["api_key"], "admin_contact_email": CREDENTIAL["admin_contact_email"]}}, {"config": {"operation": "list_businesses", "url": "https://foreign.example.test"}, "credentials": CREDENTIAL}, {"config": {"operation": "create_contact", "first_name": "Fixture", "notes": "private medical text"}, "credentials": CREDENTIAL}, {"config": {"operation": "create_patient"}, "credentials": CREDENTIAL}])
def test_raw_parse_and_validate_both_refuse_untyped_or_arbitrary_controls(payload):
    with pytest.raises(ValueError):
        node.ClinikoNode.parse_config(payload)
    assert node.ClinikoNode.validate_config(payload)["valid"] is False
