"""SimplyBook integration with staging's factory, credential and evidence seams."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import simplybook_node as F
from nodes.tests.test_simplybook_node_mock import AUTH, USER, world

CID = "00000000-0000-4000-8000-000000000042"
ORG = "00000000-0000-4000-8000-000000000003"
WF = "00000000-0000-4000-8000-000000000004"


def test_registered_credential_families_are_discovered_by_staging():
    from coder.workflow.operation_catalog import node_accepted_credential_types
    assert node_accepted_credential_types("automation-simplybook") == set(F.FAMILIES)


@pytest.mark.asyncio
async def test_registered_factory_pins_read_operation(world):
    from nodes.core.run_op import run_node_operation
    output = await run_node_operation(node_type="automation-simplybook", operation="get_service",
        arguments={"operation": "create_client", "service_id": "1", "name": "Must not write"},
        user_id=USER, credential_data=deepcopy(AUTH))
    assert output["record"]["id"] == "1"
    assert not any(b"addClient" in request.content for request in world.calls)


@pytest.mark.asyncio
async def test_saved_picker_uses_shared_resolution(world, monkeypatch):
    from nodes.core import run_op
    resolver = AsyncMock(return_value=deepcopy(AUTH))
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", resolver)
    monkeypatch.setattr("utils.credential_approval.admit_lookup", AsyncMock(return_value=None))
    result = await run_op.run_node_lookup(node_type="automation-simplybook", field_name="provider_id",
        context={"service_id": "1"}, user_id=USER, credential_id=CID, organization_id=ORG, workflow_id=WF)
    assert result["options"] == [{"value": "2", "label": "Fixture Provider"}]
    assert all(call.kwargs["workflow_id"] == WF and call.kwargs["org_id"] == ORG for call in resolver.await_args_list)
    assert len(world.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["pending_approval", "rejected"])
async def test_shared_admission_blocks_picker_before_provider_io(world, monkeypatch, decision):
    from nodes.core import run_op
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", AsyncMock(return_value=deepcopy(AUTH)))
    monkeypatch.setattr("utils.credential_approval.admit_lookup", AsyncMock(return_value={"status": decision}))
    result = await run_op.run_node_lookup(node_type="automation-simplybook", field_name="provider_id",
        context={"service_id": "1"}, user_id=USER, credential_id=CID, organization_id=ORG)
    assert result["status"] == decision and world.calls == []


@pytest.mark.asyncio
async def test_connect_evidence_proves_only_reachability(world, monkeypatch):
    from nodes.core import credential_connect, connection_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=AUTH["credential_type"],
        credential_data=deepcopy(AUTH), user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert F.SimplyBookNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.account_label is None and verdict.evidence.samples == []
    assert verdict.credential_data == AUTH


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [{}, {"service_id": "999"}, {"service_id": ["1", "999"]}])
async def test_native_picker_rejects_missing_or_foreign_parent(world, context):
    with pytest.raises(ValueError):
        await F.SimplyBookNode.load_field_options("provider_id", deepcopy(AUTH), context=context)
    # A foreign ID is checked against the company catalogue;
    # malformed or missing IDs are refused before login.
    assert len(world.calls) == (2 if context.get("service_id") == "999" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(200, True), (401, False), (403, False), (429, None), (503, None)])
async def test_registered_actual_post_connect_handler_runs_current_read_witness(world, monkeypatch, status, expected):
    from wss.handlers import credentials_handler as H, workflow_handler
    from wss.receiver.client_events import CredentialValidateAccessRequest
    monkeypatch.setattr(H, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(H, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _blob: deepcopy(AUTH)))
    repo = SimpleNamespace(fetch_with_access=AsyncMock(return_value=SimpleNamespace(credential=b"fixture")))
    monkeypatch.setattr(H, "CredentialsRepo", lambda _pool: repo)
    sent = []
    async def send(_sio, _sid, response): sent.append(response.model_dump()["data"])
    monkeypatch.setattr(H, "send_event", send)
    handler = H.CredentialsHandler(SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER})))
    class Pool:
        def acquire(self): return self
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
    handler.get_pool = AsyncMock(return_value=Pool())
    if status != 200: world.override = lambda _request, _body: httpx.Response(status, json={"message": "PRIVATE-PROVIDER-BODY"})
    request = CredentialValidateAccessRequest(request_id="synthetic-validation", node_type="automation-simplybook", credential_id=CID)
    await handler.get_events()[request.event_name]("synthetic-sid", request)
    assert sent[0]["valid"] is expected and "PRIVATE-" not in str(sent)
    if expected is True: assert sent[0]["identity_verified"] is False
    assert len(world.calls) == (2 if status == 200 else 1)
