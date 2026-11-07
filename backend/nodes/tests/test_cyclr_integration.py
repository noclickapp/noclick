"""Cyclr factory/connect/current-credential regressions.

Only local repository storage, encryption and remote HTTP are substituted.
The native authority carrier remains real across saved operation/picker reads.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import cyclr_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, encryption, ssrf
from wss.handlers import workflow_handler

CREDENTIAL = {"credential_type": node.TYPES[0], "access_token": "fixture-console-token", "region": "us", "account_id": "fixture-account"}
CID = "33333333-3333-4333-8333-333333333333"
CYCLE_ID = "11111111-1111-4111-8111-111111111111"
STEP_ID = "22222222-2222-4222-8222-222222222222"


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
    row = {"id": CID, "name": "Cyclr", "metadata": {}, "created_at": datetime(2026, 10, 7, tzinfo=timezone.utc), "credential_type": node.TYPES[0], "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 7, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql = [], []
    state = {"row": row, "blob": deepcopy(CREDENTIAL), "org": "fixture-org", "status": 200, "content": None, "during_request": None,
             "account": {"Id": "fixture-account", "Name": "PRIVATE NAME", "Description": "PRIVATE DESCRIPTION", "Settings": {"password": "PRIVATE PASSWORD"}},
             "cycles": [{"Id": CYCLE_ID, "Status": "Stopped", "Name": "PRIVATE CYCLE", "Parameters": ["PRIVATE PARAMETERS"]}],
             "steps": [{"Id": STEP_ID, "ActionType": "Action", "connectorAuthValue": "PRIVATE AUTH"}]}
    async def read(statement, *args):
        sql.append((statement, args))
        return state["row"]
    pool = Pool(SimpleNamespace(fetchrow=AsyncMock(side_effect=read)))
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"])))
    monkeypatch.setattr(credentials, "get_encryption", encryption.get_encryption)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(side_effect=lambda *_: state["org"]))
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        current = node.credential_value(state["blob"])
        assert request.method == "GET" and str(request.url).startswith(node.ROOTS[current.region] + "/v1.0/")
        assert request.headers["Authorization"] == "Bearer " + current.access_token and current.access_token not in str(request.url)
        if request.url.path == "/v1.0/accounts/" + current.account_id:
            assert "X-Cyclr-Account" not in request.headers
            payload = state["account"]
        else:
            assert request.headers["X-Cyclr-Account"] == current.account_id
            payload = {"/v1.0/Cycles": state["cycles"], "/v1.0/Cycles/" + CYCLE_ID: state["cycles"][0], "/v1.0/Cycles/" + CYCLE_ID + "/steps": state["steps"]}[request.url.path]
        if state["during_request"]:
            state["during_request"]()
        kwargs = {"content": state["content"]} if state["content"] is not None else {"json": deepcopy(payload)}
        return httpx.Response(state["status"], headers={"Content-Type": "application/json"}, **kwargs)
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_factory_current_credential_and_admission(seams):
    assert NODE_REGISTRY["automation-cyclr"] is node.CyclrNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-cyclr", node_data={"config": {"operation": "get_account"}, "credentials": {**CREDENTIAL, "access_token": "stale-token", "account_id": "stale-account"}, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"] == {"id": "fixture-account"} and result["principal_identity_verified"] is False
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "get_account" and args["credential_id"] == CID
    assert len(seams.calls) == 1 and any("c.updated_at" in query for query, _ in seams.sql)




async def test_actual_manual_connect_and_honest_selected_resource_proof(seams):
    raw = {key: value for key, value in CREDENTIAL.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPES[0], credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None and verdict.credential_data == CREDENTIAL
    assert verdict.evidence.reachable is True and node.CyclrNode.connection_evidence.proves == "reachability" and verdict.evidence.account_label is None
    assert len(seams.calls) == 1 and seams.admission.await_count == 0


@pytest.mark.parametrize("change", [{"account_id": ""}, {"account_id": "https://private.example.test"}, {"account_id": "parent/other"}, {"region": "custom"}, {"access_token": ""}, {"access_token": "Bearer fixture-console-token"}, {"access_token": "token\r\nheader"}])
async def test_manual_connect_bad_auth_no_io(seams, change):
    raw = {key: value for key, value in {**CREDENTIAL, **change}.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPES[0], credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []


@pytest.mark.parametrize("family", [None, "cyclr_client_secret", "slack_oauth"])
async def test_current_row_family_blocks_blob_and_provider(seams, family):
    seams.row["credential_type"] = family
    with pytest.raises(ValueError, match="Current Cyclr authority"):
        await node.CyclrNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool)
    assert seams.calls == []


@pytest.mark.parametrize("condition", ["absent", "revoked", "lost_access", "changed_version"])
async def test_resolution_current_authority_race_no_io(seams, condition):
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
        await node.CyclrNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool)
    assert seams.calls == []


async def test_current_token_account_and_region_replace_stale_caller(seams):
    seams.state["blob"] = {**CREDENTIAL, "access_token": "rotated-console-token", "account_id": "rotated-account", "region": "eu"}
    seams.state["account"]["Id"] = "rotated-account"
    result = await run_op.run_node_operation(node_type="automation-cyclr", operation="get_account", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["status"] == "success" and str(seams.calls[0].url) == "https://api.eu.cyclr.com/v1.0/accounts/rotated-account"
    assert seams.calls[0].headers["Authorization"] == "Bearer rotated-console-token"


@pytest.mark.parametrize("field", ["updated_at", "credential_type", "revoked_at"])
@pytest.mark.parametrize("response", ["success", "refusal", "malformed"])
async def test_actual_picker_rechecks_after_http_even_refusal_and_parser(seams, field, response):
    def race():
        seams.row[field] = {"updated_at": datetime(2026, 10, 8, tzinfo=timezone.utc), "credential_type": "slack_oauth", "revoked_at": datetime.now(timezone.utc)}[field]
    seams.state["during_request"] = race
    if response == "refusal":
        seams.state["status"] = 401
    elif response == "malformed":
        seams.state["content"] = b"not-json"
    with pytest.raises(ValueError, match="authority changed"):
        await run_op.run_node_lookup(node_type="automation-cyclr", field_name="cycle_id", context=None, page_token=None, search=None, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert len(seams.calls) == 1  # No cycle catalog after the account request loses authority.


async def test_current_caller_org_loss_after_http_blocks_output(seams):
    seams.state["during_request"] = lambda: seams.state.update(org="other-org")
    with pytest.raises(ValueError, match="organization changed"):
        await run_op.run_node_operation(node_type="automation-cyclr", operation="get_account", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert len(seams.calls) == 1




async def test_actual_saved_picker_retains_native_authority_carrier(seams):
    result = await run_op.run_node_lookup(node_type="automation-cyclr", field_name="step_id", context={"cycle_id": CYCLE_ID}, page_token=None, search="2222", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["options"][0]["value"] == STEP_ID and len(seams.calls) == 3
    assert "PRIVATE" not in str(result) and any("c.updated_at" in query for query, _ in seams.sql)




async def test_malformed_or_foreign_account_never_verified(seams):
    seams.state["account"] = {"Id": "foreign-account", "Name": "PRIVATE NAME"}
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
        current = await node.CyclrNode._resolve_current_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
        assert current == CREDENTIAL and isinstance(current, node._CurrentCredential)
        await node.request_operation(current, node.GetAccount())
        assert len(owner_reads) >= 5 and all(args[2] == "fixture-org" for args in owner_reads)
    else:
        with pytest.raises(ValueError, match="Current Cyclr authority"):
            await node.CyclrNode._resolve_current_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
        assert owner_reads == [] and seams.calls == []


async def test_native_carrier_fields_cannot_change_after_resolution(seams):
    current = await node.CyclrNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool)
    current["account_id"] = "other-account"
    with pytest.raises(ValueError, match="fields changed"):
        await node.request_operation(current, node.GetAccount())
    assert seams.calls == []


async def test_actual_workflow_fallback_acl_removed_during_http(seams):
    workflow = "44444444-4444-4444-8444-444444444444"
    state = {"authorized": True}
    async def read(statement, *args):
        if "FROM workflows" in statement:
            return {"owner_id": "fixture-owner"}
        if "FROM workflow_authorized_credentials" in statement:
            return {"allowed": 1} if state["authorized"] else None
        return {**seams.row, "owner_id": "fixture-owner"} if args[1] == "fixture-owner" else None
    seams.pool.conn.fetchrow.side_effect = read
    current = await node.CyclrNode._resolve_current_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org", workflow_id=workflow)
    seams.state["during_request"] = lambda: state.update(authorized=False)
    with pytest.raises(ValueError, match="workflow owner authorization changed"):
        await node.request_operation(current, node.GetAccount())
    assert len(seams.calls) == 1


async def test_freshen_requires_current_caller_access_without_workflow_context(seams):
    seams.pool.conn.fetchrow.return_value = None
    seams.pool.conn.fetchrow.side_effect = None
    with pytest.raises(ValueError, match="Current Cyclr authority"):
        await node.CyclrNode.freshen_credential(
            CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool
        )
    workflow_handler.get_user_org_context.assert_awaited_once_with(seams.pool.conn, "fixture-user")
    assert seams.calls == []
