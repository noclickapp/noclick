"""Sling factory/connect/current-row regressions against staging APIs.

Only local repository storage, encryption and remote HTTP are substituted.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import sling_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials as credential_utils, ssrf
from wss.handlers import workflow_handler

CREDENTIAL = {"credential_type": node.TYPES[0], "token": "fixture-token", "organization_id": "12"}
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
    row = {"id": CID, "name": "Sling", "metadata": {}, "created_at": datetime(2026, 10, 7, tzinfo=timezone.utc), "credential_type": node.TYPES[0], "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 7, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql, state = [], [], {"row": row, "blob": deepcopy(CREDENTIAL), "organization": {"name": "Fixture Organization", "password": "PRIVATE PASSWORD"}, "users": [{"id": 31, "name": "Fixture User", "email": "PRIVATE EMAIL"}]}
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
        assert request.method == "GET" and request.url.host == "api.getsling.com"
        assert request.headers["Authorization"] == current.token and current.token not in str(request.url)
        if request.url.path == "/v1/organisations/" + current.organization_id:
            return httpx.Response(200, json=state["organization"])
        assert request.url.path == "/v1/users"
        return httpx.Response(200, json=state["users"])
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_factory_uses_current_row_and_real_admission(seams):
    assert NODE_REGISTRY["automation-sling"] is node.SlingNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-sling", node_data={"config": {"operation": "get_organization"}, "credentials": {**CREDENTIAL, "token": "stale-token"}, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"] == {"requested_organization_id": "12", "name": "Fixture Organization"}
    assert result["principal_identity_verified"] is False
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "get_organization" and args["credential_id"] == CID
    assert len(seams.calls) == 1 and sum("c.updated_at" in query for query, _ in seams.sql) >= 2




async def test_real_manual_connect_shapes_family_and_honest_resource_proof(seams):
    raw = {key: value for key, value in CREDENTIAL.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPES[0], credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None and verdict.credential_data == CREDENTIAL
    assert verdict.evidence.reachable is True and node.SlingNode.connection_evidence.proves == "reachability" and verdict.evidence.account_label is None
    assert len(seams.calls) == 1 and seams.admission.await_count == 0


@pytest.mark.parametrize("change", [{"organization_id": ""}, {"organization_id": "http://local"}, {"token": ""}, {"token": "Bearer fixture-token"}, {"token": "token\r\nheader"}])
async def test_actual_manual_connect_bad_auth_has_no_io(seams, change):
    raw = {key: value for key, value in {**CREDENTIAL, **change}.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPES[0], credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []


@pytest.mark.parametrize("family", [None, "sling_oauth", "slack_oauth"])
async def test_current_row_family_blocks_blob_and_provider(seams, family):
    seams.row["credential_type"] = family
    with pytest.raises(ValueError, match="Current Sling authority"):
        await node.SlingNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


@pytest.mark.parametrize("condition", ["absent", "revoked", "lost_access", "changed_revision"])
async def test_current_authority_loss_or_race_stops_before_io(seams, condition):
    if condition == "absent":
        seams.state["row"] = None
    elif condition == "revoked":
        seams.row["revoked_at"] = datetime.now(timezone.utc)
    else:
        reads = 0
        async def read(statement, *args):
            nonlocal reads
            if "c.updated_at" in statement:
                reads += 1
                if reads == 2:
                    return None if condition == "lost_access" else {**seams.row, "updated_at": datetime(2026, 10, 8, tzinfo=timezone.utc)}
            return seams.row
        seams.pool.conn.fetchrow.side_effect = read
    with pytest.raises(ValueError):
        await node.SlingNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert seams.calls == []


async def test_current_token_and_organization_replace_stale_caller(seams):
    seams.state["blob"] = {**CREDENTIAL, "token": "rotated-token", "organization_id": "13"}
    result = await run_op.run_node_operation(node_type="automation-sling", operation="get_organization", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["status"] == "success" and result["data"]["requested_organization_id"] == "13"
    assert seams.calls[0].url.path == "/v1/organisations/13"
    assert seams.calls[0].headers["Authorization"] == "rotated-token"




async def test_actual_stored_picker_uses_current_token(seams):
    result = await run_op.run_node_lookup(node_type="automation-sling", field_name="user_id", context=None, page_token=None, search="fixture", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["options"][0]["value"] == "31" and len(seams.calls) == 2
    assert "PRIVATE EMAIL" not in str(result)


async def test_malformed_protected_org_never_verified_identity(seams):
    seams.state["organization"] = {"status": "ok"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPES[0], credential_data=CREDENTIAL, user_id="fixture-user", pool=seams.pool)
    assert verdict.evidence.reachable is not True and verdict.verified_metadata() == {} and verdict.evidence.account_label is None
    assert len(seams.calls) == 1






@pytest.mark.parametrize("authorized", [False, True])
async def test_workflow_owner_fallback_requires_actual_acl_and_current_org(seams, authorized):
    workflow = "44444444-4444-4444-8444-444444444444"
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
        assert await node.SlingNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow) == CREDENTIAL
        assert len(owner_reads) == 3 and all(args[2] == "fixture-org" for args in owner_reads)
    else:
        with pytest.raises(ValueError, match="Current Sling authority"):
            await node.SlingNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
        assert owner_reads == []
