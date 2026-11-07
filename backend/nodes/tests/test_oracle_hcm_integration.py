"""Oracle HCM factory, connect, staging credential and approval regressions.

Only local repository storage, encryption and synthetic HTTP are substituted.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import oracle_hcm_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, encryption, ssrf
from wss.handlers import workflow_handler

CREDENTIAL = {"credential_type": node.BASIC, "username": "fixture-service", "password": "fixture-password", "tenant_url": "https://fixture.fa.us2.oraclecloud.com", "api_version": node.VERSION}
CID = "11111111-1111-4111-8111-111111111111"
DEPARTMENT = {"OrganizationId": 12, "Name": "Fixture Department", "privatePayroll": "excluded"}


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
    row = {"credential_type": node.BASIC, "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql, state = [], [], {"row": row, "blob": deepcopy(CREDENTIAL), "departments": [DEPARTMENT]}
    async def read(statement, *args):
        sql.append((statement, args))
        return state["row"]
    pool = Pool(SimpleNamespace(fetchrow=AsyncMock(side_effect=read)))
    fake_encryption = lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"]))
    monkeypatch.setattr(encryption, "get_encryption", fake_encryption)
    monkeypatch.setattr(credentials, "get_encryption", fake_encryption)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="fixture-org"))
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        current = node.credential_value(state["blob"])
        assert request.url.path == "/hcmRestApi/resources/11.13.18.05/departmentsLov"
        assert str(request.url).startswith(current.tenant_url + "/")
        assert request.headers["Authorization"] == node.auth_header(current)
        assert "password" not in request.url.params and "access_token" not in request.url.params
        return httpx.Response(200, json={"items": state["departments"], "count": len(state["departments"]), "offset": 0, "limit": 50, "hasMore": False})
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_factory_run_uses_current_saved_secret_and_native_arguments(seams):
    assert NODE_REGISTRY["automation-oracle-hcm"] is node.OracleHCMNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-oracle-hcm", node_data={"config": {"operation": "list_departments"}, "credentials": {**CREDENTIAL, "password": "stale-password"}, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"]["items"] == [{"id": "12", "OrganizationId": "12", "Name": "Fixture Department", "name": "Fixture Department"}]
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "list_departments" and args["arguments"] == {"offset": 0, "limit": 50} and args["credential_id"] == CID
    assert len(seams.calls) == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_operation_and_evidence_admission_stop_before_provider(seams, status):
    seams.admission.return_value = {"id": "fixture-approval", "status": status, "new_request": False}
    result = await run_op.run_node_operation(node_type="automation-oracle-hcm", operation="list_departments", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and result["_halt_downstream"] is True
    evidence = await connection_evidence.collect_evidence(node_type="automation-oracle-hcm", credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert evidence.reachable is None and evidence.account_label is None and evidence.samples == []
    assert evidence.noun == "HCM department metadata" and seams.calls == []


@pytest.mark.parametrize("family", [node.BASIC, node.OAUTH])
async def test_actual_manual_connect_both_supplied_families_have_honest_evidence(seams, family):
    supplied = deepcopy(CREDENTIAL) if family == node.BASIC else {"credential_type": node.OAUTH, "access_token": "fixture-issued-token", "tenant_url": CREDENTIAL["tenant_url"], "api_version": node.VERSION}
    seams.state["blob"] = supplied
    raw = {key: value for key, value in supplied.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=family, credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None and verdict.credential_data == supplied
    assert verdict.evidence.reachable is True and verdict.evidence.account_label is None
    assert len(seams.calls) == 1 and seams.admission.await_count == 0


async def test_empty_metadata_does_not_create_identity_or_me_fallback(seams):
    seams.state["departments"] = []
    evidence = await connection_evidence.collect_evidence(node_type="automation-oracle-hcm", credential_data=CREDENTIAL, user_id="fixture-user")
    assert evidence.reachable is True and evidence.account_label is None and evidence.samples == [] and len(seams.calls) == 1


@pytest.mark.parametrize("change", [{"tenant_url": "http://fixture.fa.us2.oraclecloud.com"}, {"api_version": "v1"}, {"password": ""}, {"api_version": None}])
async def test_real_manual_connect_rejects_malformed_connection_before_io(seams, change):
    supplied = {key: value for key, value in {**CREDENTIAL, **change}.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.BASIC, credential_data=supplied, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []



@pytest.mark.parametrize("resolved", [None, {**CREDENTIAL, "credential_type": "slack_oauth"}])
async def test_execute_rejects_unavailable_or_wrong_family_saved_credentials(seams, monkeypatch, resolved):
    resolver = AsyncMock(return_value=resolved)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolver)
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-oracle-hcm", node_data={"config": {"operation": "list_departments"}, "credentials": CREDENTIAL, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org", workflow_id="fixture-workflow")
    with pytest.raises(ValueError):
        await instance.execute({})
    resolver.assert_awaited_once_with(CID, "fixture-user", seams.pool, org_id="fixture-org", workflow_id="fixture-workflow")
    assert seams.calls == []


async def test_execute_uses_current_tenant_and_secret_from_staging_resolver(seams, monkeypatch):
    seams.state["blob"] = {**CREDENTIAL, "tenant_url": "https://rotated.fa.uk1.oraclecloud.com", "password": "rotated-password"}
    resolver = AsyncMock(return_value=seams.state["blob"])
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolver)
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-oracle-hcm", node_data={"config": {"operation": "list_departments"}, "credentials": CREDENTIAL, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org", workflow_id="fixture-workflow")
    result = await instance.execute({})
    assert result["status"] == "success" and seams.calls[0].url.host == "rotated.fa.uk1.oraclecloud.com"
    resolver.assert_awaited_once_with(CID, "fixture-user", seams.pool, org_id="fixture-org", workflow_id="fixture-workflow")


async def test_supplied_credentials_are_validated_without_implying_a_refresh_or_identity():
    assert await node.OracleHCMNode.freshen_credential(CREDENTIAL) == CREDENTIAL
    assert (await node.OracleHCMNode.validate_credential_access(CREDENTIAL))["valid"] is None


def test_raw_family_and_native_closed_config_are_consistent():
    invalid = [{"config": {"operation": "list_departments"}, "credentials": {key: value for key, value in CREDENTIAL.items() if key != "credential_type"}}, {"config": {"operation": "list_departments", "expand": "workers"}, "credentials": CREDENTIAL}]
    for raw in invalid:
        assert node.OracleHCMNode.validate_config(raw)["valid"] is False
        with pytest.raises(ValueError):
            node.OracleHCMNode.parse_config(raw)
