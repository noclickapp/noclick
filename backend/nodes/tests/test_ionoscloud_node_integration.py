"""Exercise the native node through staging's credential and lookup seams."""
from unittest.mock import AsyncMock

import pytest
from nodes import ionoscloud_node as p
from nodes.core import run_op
from nodes.tests.test_ionoscloud_node_mock import wire, blob, datacenter, collection, option, USER, DC

CID = "00000000-0000-4000-8000-000000000042"
ORG = "00000000-0000-4000-8000-000000000003"
WF = "00000000-0000-4000-8000-000000000004"


@pytest.mark.asyncio
async def test_operation_uses_shared_credential_resolution(wire, monkeypatch):
    resolver = AsyncMock(return_value=blob())
    monkeypatch.setattr(run_op, "resolve_operation_credential", resolver)
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))
    wire.queue = [collection([datacenter()])]
    result = await run_op.run_node_operation(node_type=p.NODE_TYPE, operation="check_connection",
        arguments={}, credential_id=CID, user_id=USER, organization_id=ORG, workflow_id=WF)
    resolver.assert_awaited_once_with(CID, USER, None, ORG, WF)
    assert result["witness_verified"] and not result["identity_verified"]
    assert wire.calls[0][2]["headers"]["Authorization"] == "Bearer synthetic-issued-token"


@pytest.mark.asyncio
async def test_picker_uses_shared_resolver_and_admission(wire, monkeypatch):
    resolver = AsyncMock(return_value=blob())
    monkeypatch.setattr(run_op, "resolve_operation_credential", resolver)
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr("utils.credential_approval.admit_lookup", admission)
    wire.queue = [collection([datacenter()])]
    result = await run_op.run_node_lookup(node_type=p.NODE_TYPE, field_name="datacenter_id",
        user_id=USER, credential_id=CID, organization_id=ORG, workflow_id=WF)
    assert result["options"] == [option(DC)]
    assert resolver.await_count == 2 and admission.await_count == 1
    pending = {"status": "pending_approval", "message": "Review required"}
    admission.return_value = pending
    assert await run_op.run_node_lookup(node_type=p.NODE_TYPE, field_name="datacenter_id",
        user_id=USER, credential_id=CID) == pending
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_shared_resolution_failure_precedes_provider_request(wire, monkeypatch):
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(side_effect=ValueError("Credential unavailable")))
    with pytest.raises(ValueError, match="Credential unavailable"):
        await run_op.run_node_operation(node_type=p.NODE_TYPE, operation="check_connection",
            arguments={}, user_id=USER, credential_id=CID)
    assert not wire.calls
