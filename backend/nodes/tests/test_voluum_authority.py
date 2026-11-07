"""Voluum uses staging's credential loading and admission contract.

The original authority adapter is outside this integration's scope. These tests
exercise the supported picker, evidence and workflow admission paths instead.
"""
from copy import deepcopy

import pytest

from nodes import voluum_node as v
from nodes.core.registry import NodeFactory
from nodes.tests.test_voluum_node_mock import CRED, WS, ID, SECRET, ACCESS, wire, node


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.mark.asyncio
async def test_picker_uses_credentials_supplied_by_staging_loader(wire):
    options = await v.VoluumNode.load_field_options("workspace_id", deepcopy(CRED))
    assert options == {"options": [{"value": WS, "label": "Owned workspace"}], "next_page_token": None}
    options = await v.VoluumNode.load_field_options("offer_id", deepcopy(CRED), context={"workspace_id": WS})
    assert options["options"] == [{"value": ID, "label": "fixture"}]
    assert [r.url.path for r in wire["requests"]] == ["/auth/access/session", "/startup", "/auth/access/session", "/startup", "/offer"]
    before = len(wire["requests"])
    with pytest.raises(ValueError, match="UUID"):
        await v.VoluumNode.load_field_options("offer_id", deepcopy(CRED))
    assert len(wire["requests"]) == before


@pytest.mark.asyncio
async def test_inherited_workflow_admission_precedes_provider_io(wire, monkeypatch):
    from utils import credential_approval

    pending = {"status": "approval_required"}
    async def admit(instance, inputs):
        assert instance.node_data["credential_id"] == ID
        assert inputs == {"example": True}
        return pending

    monkeypatch.setattr(credential_approval, "admit_node", admit)
    saved = node("test_connection")
    saved.node_data["credential_id"] = ID
    assert await saved.run({"example": True}) == pending
    assert wire["requests"] == []


@pytest.mark.asyncio
async def test_registered_connection_evidence_uses_account_workspaces(wire):
    from nodes.core.connection_evidence import collect_evidence

    evidence = await collect_evidence(node_type=v.TYPE, user_id=ACCESS, credential_data=deepcopy(CRED))
    assert evidence.reachable is True
    assert evidence.samples[0].label == "Owned workspace"
    assert SECRET not in repr(evidence)


def test_raw_foreign_family_cannot_be_reconciled_into_voluum():
    data = {"id": "fixture", "type": v.TYPE, "config": {"operation": "test_connection"},
            "credentials": {**CRED, "credential_type": "foreign"}}
    assert v.VoluumNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError, match="requires a Voluum"):
        NodeFactory.create_node(node_id="fixture", node_type=v.TYPE, node_data=data)
