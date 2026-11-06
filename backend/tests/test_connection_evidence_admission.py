"""Exercise evidence through real lookup and WorkflowNode.run admission.

Unit tests fake storage and provider I/O; grant-sharing tests use real approval storage.
"""

from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from nodes.core import connection_evidence as ce
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence, EvidenceResult, EvidenceSample
from tests.test_credential_approvals import USER, approval_db  # noqa: F401


NODE_TYPE = "evidence-admission-probe"


@pytest.fixture
def ensure_native_db_pool():
    """These tests use local repository fixtures, never a database."""
    yield


class _Credential(BaseModel):
    api_key: str


class _Config(BaseModel):
    operation: Literal["list_items", "get_identity"]


@pytest.fixture
def probe(monkeypatch):
    from nodes.core import registry, run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_approval, credentials

    state = SimpleNamespace(
        pool=object(), blocked={},
        responses={
            "options": {"options": [{"label": "A channel", "value": "c1"}]},
            "list_items": {"items": [{"name": "A channel"}]},
            "get_identity": {"name": "An account"},
        },
    )
    state.provider = AsyncMock(side_effect=lambda operation: state.responses[operation])
    state.resolve = AsyncMock(return_value={"api_key": "fixture-key"})

    async def admit(**kwargs):
        status = state.blocked.get(kwargs["operation"])
        if status is None:
            return None
        return {"id": "approval-id", "status": status, "new_request": False}

    state.admit = AsyncMock(side_effect=admit)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", state.admit)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.invalid")
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", state.resolve)
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", state.resolve)

    class ProbeNode(WorkflowNode):
        @classmethod
        def get_config_model(cls):
            return NodeConfig[_Config, _Credential]

        async def execute(self, inputs):
            return await state.provider(self.config.config.operation)

        @classmethod
        async def load_field_options(cls, field_name, credential_data):
            assert field_name == "channel"
            assert credential_data == {"api_key": "fixture-key"}
            return await state.provider("options")

    state.refresh = AsyncMock(side_effect=lambda credential_data, **kw: credential_data)
    monkeypatch.setattr(ProbeNode, "freshen_credential", state.refresh)
    monkeypatch.setitem(registry.NODE_REGISTRY, NODE_TYPE, ProbeNode)
    state.node = ProbeNode
    return state


def _declare(probe, path, *, fallback=False):
    probe.node.connection_evidence = ConnectionEvidence(
        noun="channels",
        field="channel" if path == "field" else None,
        operation="list_items" if path == "operation" else None,
        identity_operation="get_identity" if path == "identity" or fallback else None,
    )


async def _collect(probe, *, stored=True):
    return await ce.collect_evidence(
        node_type=NODE_TYPE, user_id="user", pool=probe.pool,
        organization_id="org", workflow_id="workflow",
        **({"credential_id": "credential"} if stored else
           {"credential_data": {"api_key": "fixture-key"}}),
    )


@pytest.mark.parametrize("path", ["field", "operation", "identity"])
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_pending_and_rejected_probes_do_not_refresh_execute_or_fall_back(probe, path, status):
    _declare(probe, path, fallback=True)
    operation = {"field": "__lookup__", "operation": "list_items", "identity": "get_identity"}[path]
    probe.blocked[operation] = status

    assert await _collect(probe) == EvidenceResult(noun="channels")
    probe.provider.assert_not_awaited()
    probe.refresh.assert_not_awaited()
    probe.resolve.assert_awaited_once_with(
        "credential", "user", probe.pool, org_id="org", workflow_id="workflow",
    )
    probe.admit.assert_awaited_once()
    call = probe.admit.call_args.kwargs
    assert call["credential_id"] == "credential" and call["user_id"] == "user"
    assert call["node_type"] == NODE_TYPE and call["operation"] == operation
    assert call["organization_id"] == "org" and call["workflow_id"] == "workflow"
    assert call["arguments"] == (
        {"field_name": "channel", "context": {}, "page_token": None, "search": None}
        if path == "field" else {}
    )


@pytest.mark.parametrize("path", ["field", "operation", "identity"])
async def test_approved_probe_executes_and_returns_evidence(probe, path):
    _declare(probe, path, fallback=True)
    result = await _collect(probe)

    assert result.reachable is True
    probe.admit.assert_awaited_once()
    probe.provider.assert_awaited_once_with(
        {"field": "options", "operation": "list_items", "identity": "get_identity"}[path]
    )
    if path == "field":
        probe.refresh.assert_awaited_once_with(
            {"api_key": "fixture-key"}, pool=probe.pool, user_id="user", credential_id="credential",
        )
        assert result.samples == [EvidenceSample("A channel", "c1")]
        assert result.answers_field == "channel"
    elif path == "operation":
        assert result.samples == [EvidenceSample("A channel")]
    else:
        assert result.account_label == "An account"


@pytest.mark.parametrize("path", ["field", "operation"])
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_blocked_identity_fallback_discards_prior_empty_success(probe, path, status):
    _declare(probe, path, fallback=True)
    probe.responses["options"] = {"options": []}
    probe.responses["list_items"] = {"items": []}
    probe.blocked["get_identity"] = status

    assert await _collect(probe) == EvidenceResult(noun="channels")
    probe.provider.assert_awaited_once_with("options" if path == "field" else "list_items")
    assert probe.admit.await_args_list[-1].kwargs["operation"] == "get_identity"


async def test_unsaved_field_probe_needs_no_stored_credential_admission(probe):
    _declare(probe, "field")
    result = await _collect(probe, stored=False)

    assert result.reachable is True
    assert result.samples == [EvidenceSample("A channel", "c1")]
    probe.provider.assert_awaited_once_with("options")
    probe.resolve.assert_not_awaited()
    probe.refresh.assert_not_awaited()
    probe.admit.assert_not_awaited()


@pytest.mark.parametrize("retry_path", ["picker", "evidence"])
async def test_picker_grant_admits_either_surface_with_the_real_fingerprint(approval_db, monkeypatch, retry_path):
    """A picker grant admits one retry through either surface, never two calls."""
    from mcp_server import NoClickMCPServer
    from nodes.core.registry import NODE_REGISTRY

    pool, repo, (credential_id, _) = approval_db
    credentials = {"api_key": "fixture-key"}
    loader = AsyncMock(return_value={"options": [{"label": "A channel", "value": "c1"}]})
    refresh = AsyncMock(return_value=credentials)
    monkeypatch.setitem(NODE_REGISTRY, NODE_TYPE, SimpleNamespace(
        connection_evidence=ConnectionEvidence(noun="channels", field="channel"),
        freshen_credential=refresh, load_field_options=loader,
    ))
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", AsyncMock(return_value=credentials))
    monkeypatch.setattr("utils.credential_approval.notify_created", AsyncMock())
    await repo.tighten(credential_id, USER, ["*"])
    server = SimpleNamespace(get_pool=AsyncMock(return_value=pool))

    async def picker():
        return await NoClickMCPServer._load_dynamic_options_for_field(
            server, NODE_TYPE, "channel", credentials, context={}, user_id=USER, credential_id=credential_id,
        )

    async def evidence():
        return await ce.collect_evidence(
            node_type=NODE_TYPE, credential_id=credential_id, user_id=USER, pool=pool,
        )

    pending = await picker()
    assert pending["status"] == "pending_approval"
    assert await evidence() == EvidenceResult(noun="channels")
    assert await pool.fetchval(
        "SELECT count(*) FROM approval_requests WHERE credential_id=$1::uuid", credential_id,
    ) == 1
    loader.assert_not_awaited()
    refresh.assert_not_awaited()

    await repo.decide_from_human(pending["approval_id"], USER, "approved")
    result = await (picker() if retry_path == "picker" else evidence())
    if retry_path == "picker":
        assert result["options"] == [{"label": "A channel", "value": "c1"}]
    else:
        assert result.reachable is True
        assert result.samples == [EvidenceSample("A channel", "c1")]
    loader.assert_awaited_once()
    refresh.assert_awaited_once()
    assert await pool.fetchval(
        "SELECT consumed_at IS NOT NULL FROM approval_requests WHERE id=$1::uuid", pending["approval_id"],
    )
    assert await pool.fetchval(
        "SELECT count(*) FROM approval_requests WHERE credential_id=$1::uuid", credential_id,
    ) == 1

    # Consuming the shared grant must still leave the next call awaiting review.
    assert await evidence() == EvidenceResult(noun="channels")
    loader.assert_awaited_once()
    assert await pool.fetchval(
        "SELECT count(*) FROM approval_requests WHERE credential_id=$1::uuid", credential_id,
    ) == 2
