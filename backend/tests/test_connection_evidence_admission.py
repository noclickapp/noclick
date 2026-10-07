"""Admission controls cannot stand in for a provider's connection evidence.

Stored probes use the real collector, credential resolver, factory, parsed
WorkflowNode.run, admit_node and pending_result. Only repository/storage and
provider boundaries are local fixtures; no account or external I/O is needed.
"""

import importlib.util
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from nodes.core import connection_evidence as ce, credential_connect as cc
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from wss.sender.responses import CredentialTestConnectionResponse


NODE_TYPE = "automation-admission-probe"
CREDENTIAL_TYPE = "admission_probe"
USER = "fixture-user"
CREDENTIAL_ID = "fixture-credential"


@pytest.fixture
def ensure_native_db_pool():
    """These regressions use local storage/repository fixtures, never a DB pool."""
    yield


class _Credential(BaseModel):
    credential_type: Literal["admission_probe"] = CREDENTIAL_TYPE
    api_key: str


class _Config(BaseModel):
    operation: Literal["list_items", "get_identity"]
    limit: int = 3


@pytest.fixture
def probe(monkeypatch):
    from nodes.core import registry, run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_approval, credentials

    state = SimpleNamespace(
        responses={"list_items": {"items": []}, "get_identity": {"name": "Fixture account"}},
        blocked={}, pool=object(), instances=[],
    )

    async def provider(operation):
        answer = state.responses[operation]
        if isinstance(answer, Exception):
            raise answer
        return answer

    state.provider = AsyncMock(side_effect=provider)
    state.resolve = AsyncMock(return_value={
        "credential_type": CREDENTIAL_TYPE, "api_key": "fixture-key",
    })

    async def admission(**kwargs):
        status = state.blocked.get(kwargs["operation"])
        if status is None:
            return None
        return {"id": "fixture-approval", "status": status, "new_request": False}

    state.admit = AsyncMock(side_effect=admission)
    # Retain resolve_operation_credential and real admit_node/pending_result.
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", state.resolve)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", state.resolve)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", state.admit)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.invalid")

    class ProbeNode(WorkflowNode):
        connection_evidence = ConnectionEvidence(noun="fixture items", identity_operation="get_identity")

        @classmethod
        def get_config_model(cls):
            return NodeConfig[_Config, _Credential]

        async def execute(self, inputs):
            state.instances.append(self)
            return await state.provider(self.config.config.operation)

        @classmethod
        async def load_field_options(cls, field_name, credential_data):
            assert field_name == "item_id"
            assert credential_data["api_key"] == "fixture-key"
            return await state.provider("options")

    state.node = ProbeNode
    monkeypatch.setitem(registry.NODE_REGISTRY, NODE_TYPE, ProbeNode)
    monkeypatch.setattr(cc, "resolve_credential_class", lambda t: (NODE_TYPE, _Credential)
                        if t == CREDENTIAL_TYPE else None)
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    return state


def _declare(probe, path="identity", proves="account", fallback=False):
    probe.node.connection_evidence = ConnectionEvidence(
        noun="fixture items", proves=proves,
        field="item_id" if path == "field" else None,
        operation="list_items" if path == "operation" else None,
        operation_arguments={"limit": 3} if path == "operation" else {},
        identity_operation="get_identity" if path == "identity" or fallback else None,
    )


async def _collect(probe, *, stored=True):
    return await ce.collect_evidence(
        node_type=NODE_TYPE, user_id=USER, pool=probe.pool,
        organization_id="fixture-org", workflow_id="fixture-workflow",
        **({"credential_id": CREDENTIAL_ID} if stored else
           {"credential_data": {"credential_type": CREDENTIAL_TYPE, "api_key": "fixture-key"}}),
    )


def _assert_unknown(result, proves="account"):
    assert result.reachable is None
    assert result.noun == "fixture items" and result.proves == proves
    assert result.samples == [] and result.account_label is None
    assert result.answers_field is None and result.total is None
    assert result.error is None and result.hint is None
    assert cc.ConnectVerdict(credential_data={}, evidence=result).verified_metadata() == {}
    wire = CredentialTestConnectionResponse.from_evidence(result).model_dump()
    assert wire["reachable"] is None and wire["proves"] == proves
    assert wire["samples"] == [] and wire["account_label"] is None
    assert wire["answers_field"] is None and wire["total"] is None
    assert wire["error"] is None and wire["hint"] is None


@pytest.mark.parametrize("path", ["identity", "operation"])
@pytest.mark.parametrize("status", ["pending", "rejected"])
@pytest.mark.parametrize("proves", ["account", "reachability"])
async def test_real_stored_admission_is_unknown_without_provider_or_fallback(probe, path, status, proves):
    _declare(probe, path, proves, fallback=True)
    operation = "get_identity" if path == "identity" else "list_items"
    probe.blocked[operation] = status
    _assert_unknown(await _collect(probe), proves)
    probe.provider.assert_not_awaited()
    assert probe.instances == []
    probe.resolve.assert_awaited_once_with(
        CREDENTIAL_ID, USER, probe.pool, org_id="fixture-org", workflow_id="fixture-workflow",
    )
    probe.admit.assert_awaited_once()
    call = probe.admit.call_args.kwargs
    assert call["credential_id"] == CREDENTIAL_ID and call["operation"] == operation
    assert call["node_type"] == NODE_TYPE and call["user_id"] == USER
    assert call["arguments"] == {"limit": 3}
    assert call["workflow_id"] == "fixture-workflow" and call["organization_id"] == "fixture-org"


@pytest.mark.parametrize("path", ["operation", "field"])
async def test_blocked_identity_discards_prior_empty_probe_claims(probe, path):
    _declare(probe, path, "reachability", fallback=True)
    probe.responses["options"] = {"options": []}
    probe.blocked["get_identity"] = "pending"
    _assert_unknown(await _collect(probe), "reachability")
    assert [c.args[0] for c in probe.provider.await_args_list] == [
        "list_items" if path == "operation" else "options",
    ]
    assert probe.admit.await_args_list[-1].kwargs["operation"] == "get_identity"


@pytest.mark.parametrize("path", ["identity", "operation", "field"])
@pytest.mark.parametrize("flags", [
    {"executed": False}, {"_halt_downstream": True},
    {"executed": False, "status": "error", "error": "HTTP 403 forbidden", "status_code": 403},
])
async def test_outer_nonexecuted_flags_win_over_identity_samples_and_refusal_text(probe, path, flags):
    _declare(probe, path, "reachability", fallback=True)
    operation = {"identity": "get_identity", "operation": "list_items", "field": "options"}[path]
    probe.responses[operation] = {
        "status": "success", "success": True, "name": "Never verified",
        "data": {"name": "Never verified"}, "items": [{"name": "Never sampled"}],
        "options": [{"label": "Never choosable", "value": "fixture-id"}], **flags,
    }
    _assert_unknown(await _collect(probe, stored=False), "reachability")
    probe.provider.assert_awaited_once_with(operation)
    probe.resolve.assert_not_awaited()
    probe.admit.assert_not_awaited()


@pytest.mark.parametrize("stored", [False, True])
@pytest.mark.parametrize("payload,label", [
    ({"name": "Fixture account"}, "Fixture account"),
    ({"success": True, "data": {"name": "Fixture account"}}, "Fixture account"),
    ({"status": "copying", "status_code": 202}, None),
    ({"success": True, "status_code": 204}, None),
    ({"status": "success", "data": {"success": True, "status_code": 204}}, None),
    ({}, None), ("Accepted provider text", None), (b"provider bytes", None),
    ({"data": {"name": "Fixture account", "executed": False,
               "_halt_downstream": True, "status": "rejected"}}, "Fixture account"),
    ({"status": "pending_approval", "name": "Provider record"}, "Provider record"),
])
async def test_legacy_executed_identity_shapes_remain_reachable(probe, stored, payload, label):
    _declare(probe)
    probe.responses["get_identity"] = payload
    result = await _collect(probe, stored=stored)
    assert result.reachable is True and result.account_label == label
    assert result.error is None and result.samples == []
    probe.provider.assert_awaited_once_with("get_identity")
    assert len(probe.instances) == 1 and isinstance(probe.instances[0].config, NodeConfig)
    assert probe.admit.await_count == int(stored) and probe.resolve.await_count == int(stored)


@pytest.mark.parametrize("path,payload", [
    ("operation", [{"name": "Fixture item", "executed": False, "status": "rejected"}]),
    ("operation", {"data": {"items": [{"name": "Fixture item"}]}}),
    ("field", {"options": [{"label": "Fixture item", "value": "fixture-id"}]}),
    ("field", []), ("operation", {"items": []}),
])
async def test_successful_rows_and_empty_picker_remain_truthful(probe, path, payload):
    _declare(probe, path, "reachability")
    probe.responses["list_items" if path == "operation" else "options"] = payload
    result = await _collect(probe)
    assert result.reachable is True and result.proves == "reachability"
    assert result.answers_field == ("item_id" if path == "field" else None)
    assert [s.label for s in result.samples] == (["Fixture item"] if payload and payload != {"items": []} else [])
    assert result.account_label is None and result.error is None


@pytest.mark.parametrize("code", [401, 403])
@pytest.mark.parametrize("path", ["identity", "operation", "field"])
async def test_real_provider_refusals_are_preserved(probe, path, code):
    _declare(probe, path, "reachability")
    operation = {"identity": "get_identity", "operation": "list_items", "field": "options"}[path]
    probe.responses[operation] = {"status": "error", "status_code": code,
        "error": f"HTTP {code} forbidden https://fixture.invalid?token=fixture-key"}
    result = await _collect(probe)
    assert result.reachable is False and result.proves == "reachability"
    assert str(code) in result.error and "fixture-key" not in result.error
    assert result.hint and result.samples == [] and result.account_label is None


async def test_stored_connection_handler_sends_unknown_without_writing_metadata(monkeypatch, probe):
    from utils import database_pool
    from wss.handlers import workflow_handler as module
    from wss.receiver.client_events import CredentialTestConnectionRequest

    _declare(probe, "identity", "reachability")
    probe.blocked["get_identity"] = "rejected"
    monkeypatch.setattr(database_pool, "get_native_pool", lambda: probe.pool)
    send = AsyncMock()
    monkeypatch.setattr(module, "send_event", send)
    handler = module.WorkflowHandler.__new__(module.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    await handler.test_credential_connection("fixture-sid", CredentialTestConnectionRequest(
        request_id="fixture-test", node_type=NODE_TYPE, credential_id=CREDENTIAL_ID,
        organization_id="fixture-org", workflow_id="fixture-workflow",
    ))
    send.assert_awaited_once()
    response = send.call_args.args[2]
    assert response.error is None
    assert response.data["reachable"] is None and response.data["proves"] == "reachability"
    assert response.data["samples"] == [] and response.data["account_label"] is None
    assert response.data["error"] is None and response.data["hint"] is None
    probe.provider.assert_not_awaited()


async def test_hosted_and_actual_oss_override_preserve_unknown_claim(monkeypatch, probe):
    path = Path(__file__).resolve().parents[2] / "oss/overrides/backend/wss/sender/responses.py"
    if not path.is_file():
        pytest.skip("override source is absent from the exported checkout")
    name = "credential_evidence_admission_override"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    for claim in ("account", "reachability"):
        _declare(probe, "identity", claim)
        probe.blocked["get_identity"] = "pending"
        result = await _collect(probe)
        _assert_unknown(result, claim)
        assert module.CredentialTestConnectionResponse.from_evidence(result).model_dump() == (
            CredentialTestConnectionResponse.from_evidence(result).model_dump()
        )


class _Pool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_typed_save_retains_unverified_without_fabricated_metadata(monkeypatch, probe, operation):
    from repositories import credentials as repo
    from utils import credentials
    from wss.handlers import credentials_handler as module
    from wss.receiver.client_events import CredentialCreateRequest, CredentialUpdateRequest

    _declare(probe, "identity", "reachability")
    # Typed pre-save data has no stored ID. A control result from its operation
    # still must propagate as unknown through the actual connect/save flow.
    probe.responses["get_identity"] = {"executed": False, "name": "Never verified"}
    handler = module.CredentialsHandler.__new__(module.CredentialsHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler.encryption = SimpleNamespace(encrypt_credential=lambda data: "encrypted fixture")
    handler.get_pool = AsyncMock(return_value=_Pool())
    send = AsyncMock()
    monkeypatch.setattr(module, "send_event", send)
    now = datetime.now(timezone.utc)
    row = dict(id=CREDENTIAL_ID, name="Fixture", credential_type=CREDENTIAL_TYPE,
               metadata={}, created_at=now, updated_at=now)
    if operation == "create":
        persist = AsyncMock(return_value=(row, None))
        monkeypatch.setattr(repo, "create_credential_with_limit_check", persist)
        await handler.create_credential("fixture-sid", CredentialCreateRequest(
            request_id="fixture-create", name="Fixture", credential_type=CREDENTIAL_TYPE,
            credential_data={"api_key": " fixture-key "},
        ))
        metadata = persist.call_args.args[6]
    else:
        repository = SimpleNamespace(
            has_edit_permission=AsyncMock(return_value=True),
            fetch_with_access=AsyncMock(return_value=SimpleNamespace(**row)),
            update_metadata_or_fetch=AsyncMock(return_value=SimpleNamespace(**row)),
        )
        monkeypatch.setattr(module, "CredentialsRepo", lambda pool: repository)
        monkeypatch.setattr(module, "get_user_org_context", AsyncMock(return_value=None))
        persist = AsyncMock(return_value=True)
        monkeypatch.setattr(credentials, "update_credential_data", persist)
        await handler.update_credential("fixture-sid", CredentialUpdateRequest(
            request_id="fixture-update", credential_id=CREDENTIAL_ID,
            credential_data={"api_key": " fixture-key "},
        ))
        assert persist.call_args.kwargs["new_data"] == {"api_key": "fixture-key"}
        metadata = persist.call_args.kwargs["metadata_updates"]
    persist.assert_awaited_once()
    assert not metadata
    send.assert_awaited_once()
    event = send.call_args.args[2]
    assert event.error is None and event.data["success"] is True
    assert event.data["verification"]["reachable"] is None
    assert event.data["verification"]["proves"] == "reachability"
    assert event.data["verification"]["account_label"] is None
    probe.resolve.assert_not_awaited()
    probe.admit.assert_not_awaited()
    probe.provider.assert_awaited_once_with("get_identity")


async def test_public_provide_retains_unverified_without_fabricated_metadata(monkeypatch, probe):
    from utils import credential_request_routes as routes
    from utils.async_helpers import drain_spawned_tasks

    _declare(probe, "identity", "reachability")
    probe.responses["get_identity"] = {"_halt_downstream": True, "name": "Never verified"}
    row = dict(id="fixture-request", token="fixture-token", requester_id=USER,
               credential_type=CREDENTIAL_TYPE, status="pending", expires_at=None,
               provision_attempts=0, target_email=None)
    pool = SimpleNamespace(fetchrow=AsyncMock(return_value=row), execute=AsyncMock())
    monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
    persist = AsyncMock(return_value={"status": "success", "credential_id": CREDENTIAL_ID})
    monkeypatch.setattr(routes, "_store_and_fulfill", persist)
    result = await routes.provide_credential("fixture-token", routes.ProvideCredentialBody(
        credential_data={"api_key": " fixture-key "},
    ))
    await drain_spawned_tasks()
    assert result["status"] == "success" and result["verification"]["reachable"] is None
    assert result["verification"]["proves"] == "reachability"
    assert result["verification"]["account_label"] is None
    persist.assert_awaited_once()
    assert persist.call_args.args[3] == {"api_key": "fixture-key"}
    assert "verified_at" not in persist.call_args.args[5] and "verified_as" not in persist.call_args.args[5]
    probe.resolve.assert_not_awaited()
    probe.admit.assert_not_awaited()
    probe.provider.assert_awaited_once_with("get_identity")
