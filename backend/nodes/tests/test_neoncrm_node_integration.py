"""Regressions for Neon CRM connect and staging dispatcher admission.
Mocks database/transport boundaries; factory, admission and evidence consumers are real.
No live provider, account or notification action is included.
"""
from unittest.mock import AsyncMock
from uuid import UUID
import pytest
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect
from nodes import neoncrm_node as native
from nodes.tests.test_neoncrm_node_mock import CREDENTIAL, node

CID = "11111111-1111-4111-8111-111111111111"


@pytest.mark.asyncio
async def test_manual_connect_actual_shaping_and_real_probe(monkeypatch):
    import nodes.core.credential_connect as connect
    import httpx
    monkeypatch.setattr(connect, "_collect_evidence", collect_evidence)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"orgId": "owned-org", "name": "Owned Organization"})), **kw))
    out = await validate_for_connect(credential_type=native.FAMILY, credential_data=dict(CREDENTIAL), user_id="fixture-caller")
    assert out.field_errors == {}
    assert out.evidence.reachable is True and out.evidence.account_label == "Owned Organization"
    assert NODE_REGISTRY["automation-neoncrm"] is native.NeonCRMNode


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_stored_probe_traverses_real_dispatcher_admission_without_execute(monkeypatch, status):
    import nodes.core.run_op as run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=dict(CREDENTIAL)))
    admission = AsyncMock(return_value={"status": status, "id": UUID(CID), "new_request": False})
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(native.NeonCRMNode, "execute", AsyncMock(side_effect=AssertionError("non-admitted native execution")))
    result = await collect_evidence(node_type="automation-neoncrm", credential_id=CID, user_id="fixture-caller", pool=object())
    assert result.reachable is None and not result.samples
    assert admission.await_count == 1
    call = admission.call_args.kwargs
    assert call["operation"] == "get_organization_profile" and call["arguments"] == {}
    assert call["workflow_id"] is None
    native.NeonCRMNode.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_map_only_selection_reaches_actual_admission_before_execute(monkeypatch):
    from repositories.credential_approvals import CredentialApprovalRepo
    admission = AsyncMock(return_value={"status": "pending", "id": UUID(CID), "new_request": False})
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    instance = node("get_current_user", credentialIds={native.FAMILY: CID}, _approval_pool=object())
    monkeypatch.setattr(instance, "execute", AsyncMock(side_effect=AssertionError("unapproved execution")))
    result = await instance.run({})
    assert result["executed"] is False
    assert admission.call_args.kwargs["credential_id"] == CID
    instance.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_arguments_changed_while_admission_waits_are_not_executed(monkeypatch):
    from repositories.credential_approvals import CredentialApprovalRepo
    instance = node("get_account", {"account_id": "11"}, credential_id=CID, _approval_pool=object())
    async def admit(self, **kwargs):
        instance.config.config.account_id = "12"
        return None
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admit)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: pytest.fail("changed approval arguments reached transport"))
    with pytest.raises(ValueError, match="changed after admission"):
        await instance.run({})


@pytest.mark.asyncio
async def test_selection_changed_during_admission_is_not_executed(monkeypatch):
    from repositories.credential_approvals import CredentialApprovalRepo
    instance = node("get_current_user", credential_id=CID, _approval_pool=object())
    async def admit(self, **kwargs):
        instance.node_data["credential_id"] = "22222222-2222-4222-8222-222222222222"
        return None
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admit)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: pytest.fail("changed approval selection reached transport"))
    with pytest.raises(ValueError, match="credential context changed after admission"):
        await instance.run({})


@pytest.mark.asyncio
async def test_stored_operation_uses_staging_credential_resolver(monkeypatch):
    import httpx
    import nodes.core.run_op as run_op
    from repositories.credential_approvals import CredentialApprovalRepo

    resolved = AsyncMock(return_value=dict(CREDENTIAL))
    monkeypatch.setattr(run_op, "resolve_operation_credential", resolved)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == httpx.BasicAuth(
            CREDENTIAL["org_id"], CREDENTIAL["api_key"]
        )._auth_header
        return httpx.Response(200, json={"id": "1", "firstName": "Owner"})

    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), **kw))
    result = await run_node_operation(
        node_type="automation-neoncrm", operation="get_current_user", arguments={},
        credential_id=CID, user_id="fixture-caller", pool=object(),
    )
    resolved.assert_awaited_once()
    assert len(requests) == 1 and result["data"]["id"] == "1"
