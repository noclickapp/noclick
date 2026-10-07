"""Evidence claims survive collection and every typed credential response.

The provider and persistence boundaries are local fixtures; shaping, collection,
connect validation and response conversion execute their real implementations.
"""

import asyncio
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
from nodes.core.connection_evidence import ConnectionEvidence, EvidenceResult
from wss.sender.responses import CredentialTestConnectionResponse


@pytest.fixture
def ensure_native_db_pool():
    """These response tests stub persistence and never need a native pool."""
    yield


class _Credential(BaseModel):
    credential_type: Literal["reachability_probe"] = "reachability_probe"
    api_key: str


@pytest.fixture
def empty_probe(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    calls = []

    class Node:
        connection_evidence = ConnectionEvidence(
            field="language", noun="languages", proves="reachability"
        )

        @classmethod
        async def load_field_options(cls, field_name, credential_data):
            calls.append((field_name, credential_data))
            return {"options": []}

    monkeypatch.setitem(NODE_REGISTRY, "automation-reachability-probe", Node)
    monkeypatch.setattr(
        cc, "resolve_credential_class",
        lambda t: ("automation-reachability-probe", _Credential)
        if t == "reachability_probe" else None,
    )
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    return Node, calls


def _assert_reachability_only(verification):
    assert verification["reachable"] is True
    assert verification["proves"] == "reachability"
    assert verification["samples"] == []
    assert verification["account_label"] is None
    assert verification["noun"] == "languages"


async def test_empty_raw_probe_proves_reachability_without_inventing_an_account(empty_probe):
    _, calls = empty_probe
    result = await ce.collect_evidence(
        node_type="automation-reachability-probe",
        credential_data={"api_key": "fixture-key"}, user_id="fixture-user",
    )
    _assert_reachability_only(CredentialTestConnectionResponse.from_evidence(result).model_dump())
    assert result.answers_field == "language"
    assert calls == [("language", {"api_key": "fixture-key"})]


@pytest.mark.parametrize(
    "outcome,reachable",
    [("rejected", False), ("unknown", None), ("broken", None), ("timeout", None)],
)
async def test_failed_probe_retains_its_declared_claim(monkeypatch, empty_probe, outcome, reachable):
    node, _ = empty_probe

    async def fail(**kwargs):
        if outcome == "timeout":
            await asyncio.Future()
        raise {
            "rejected": ValueError("HTTP 401: invalid_auth"),
            "unknown": RuntimeError("unexpected provider response"),
            "broken": AttributeError("missing field loader"),
        }[outcome]

    monkeypatch.setattr(node, "load_field_options", fail)
    monkeypatch.setattr(ce, "EVIDENCE_TIMEOUT_S", 0.01)
    result = await ce.collect_evidence(
        node_type="automation-reachability-probe",
        credential_data={"api_key": "fixture-key"}, user_id="fixture-user",
    )
    assert result.reachable is reachable
    assert result.proves == "reachability"
    assert result.samples == [] and result.account_label is None
    response = CredentialTestConnectionResponse.from_evidence(result)
    assert response.reachable is reachable and response.proves == "reachability"
    assert ("invalid_auth" in (result.error or "")) is (outcome == "rejected")


def test_conversion_inherits_claim_and_preserves_explicit_overrides():
    result = EvidenceResult(reachable=True, proves="reachability")
    assert CredentialTestConnectionResponse.from_evidence(result).proves == "reachability"
    assert CredentialTestConnectionResponse.from_evidence(result, proves="account").proves == "account"
    assert CredentialTestConnectionResponse.from_evidence(
        EvidenceResult(reachable=True), proves="reachability"
    ).proves == "reachability"
    assert CredentialTestConnectionResponse.from_evidence(EvidenceResult()).proves == "account"


def test_legacy_result_and_positional_constructor_keep_the_account_default():
    result = EvidenceResult(True, [], "channel", 7, "channels", "Workspace", "error", "hint")
    assert (result.answers_field, result.total, result.noun) == ("channel", 7, "channels")
    assert (result.account_label, result.error, result.hint, result.proves) == (
        "Workspace", "error", "hint", "account",
    )
    legacy = SimpleNamespace(**{k: v for k, v in vars(result).items() if k != "proves"})
    response = CredentialTestConnectionResponse.from_evidence(legacy)
    assert response.proves == "account" and response.hint == "hint"


async def test_response_override_matches_real_collector_claims(monkeypatch, empty_probe):
    override_path = Path(__file__).resolve().parents[2] / "oss/overrides/backend/wss/sender/responses.py"
    if not override_path.is_file():
        pytest.skip("override source is absent from the exported checkout")
    module_name = "credential_evidence_response_override"
    spec = importlib.util.spec_from_file_location(module_name, override_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    override = module.CredentialTestConnectionResponse
    node, _ = empty_probe
    for declared_claim in ("reachability", "account"):
        monkeypatch.setattr(node, "connection_evidence", ConnectionEvidence(
            field="language", noun="languages", proves=declared_claim,
        ))
        result = await ce.collect_evidence(
            node_type="automation-reachability-probe",
            credential_data={"api_key": "fixture-key"}, user_id="fixture-user",
        )
        inherited = override.from_evidence(result).model_dump()
        assert inherited["proves"] == declared_claim
        assert inherited["reachable"] is True and inherited["account_label"] is None
        assert inherited["samples"] == []
        assert inherited == CredentialTestConnectionResponse.from_evidence(result).model_dump()
        for claim in ("account", "reachability"):
            response = override.from_evidence(result, proves=claim)
            assert response.proves == claim
            assert response.model_dump() == CredentialTestConnectionResponse.from_evidence(
                result, proves=claim
            ).model_dump()
    legacy = SimpleNamespace(**{k: v for k, v in vars(result).items() if k != "proves"})
    response = override.from_evidence(legacy)
    assert response.proves == "account" and response.account_label is None
    assert response.model_dump() == CredentialTestConnectionResponse.from_evidence(legacy).model_dump()


class _Pool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_typed_save_response_preserves_reachability(monkeypatch, empty_probe, operation):
    from repositories import credentials as repo
    from utils import credentials
    from wss.handlers import credentials_handler as handler_module
    from wss.receiver.client_events import CredentialCreateRequest, CredentialUpdateRequest

    _, calls = empty_probe
    handler = handler_module.CredentialsHandler.__new__(handler_module.CredentialsHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": "fixture-user"}))
    handler.encryption = SimpleNamespace(encrypt_credential=lambda data: "encrypted fixture")
    handler.get_pool = AsyncMock(return_value=_Pool())
    send = AsyncMock()
    monkeypatch.setattr(handler_module, "send_event", send)
    now = datetime.now(timezone.utc)
    row = dict(
        id="fixture-credential", name="Fixture", credential_type="reachability_probe",
        metadata={}, created_at=now, updated_at=now,
    )

    if operation == "create":
        persist = AsyncMock(return_value=(row, None))
        monkeypatch.setattr(repo, "create_credential_with_limit_check", persist)
        await handler.create_credential("fixture-sid", CredentialCreateRequest(
            request_id="fixture-create", name="Fixture", credential_type="reachability_probe",
            credential_data={"api_key": " fixture-key "},
        ))
        metadata = persist.call_args.args[6]
    else:
        repository = SimpleNamespace(
            has_edit_permission=AsyncMock(return_value=True),
            fetch_with_access=AsyncMock(return_value=SimpleNamespace(**row)),
            update_metadata_or_fetch=AsyncMock(return_value=SimpleNamespace(**row)),
        )
        monkeypatch.setattr(handler_module, "CredentialsRepo", lambda pool: repository)
        monkeypatch.setattr(handler_module, "get_user_org_context", AsyncMock(return_value=None))
        persist = AsyncMock(return_value=True)
        monkeypatch.setattr(credentials, "update_credential_data", persist)
        await handler.update_credential("fixture-sid", CredentialUpdateRequest(
            request_id="fixture-update", credential_id="fixture-credential",
            credential_data={"api_key": " fixture-key "},
        ))
        assert persist.call_args.kwargs["new_data"] == {"api_key": "fixture-key"}
        metadata = persist.call_args.kwargs["metadata_updates"]

    send.assert_awaited_once()
    event = send.call_args.args[2]
    assert event.error is None and event.data["success"] is True
    _assert_reachability_only(event.data["verification"])
    assert metadata["verified_at"] and "verified_as" not in metadata
    assert calls == [("language", {"api_key": "fixture-key"})]


async def test_public_provide_response_preserves_reachability(monkeypatch, empty_probe):
    from utils import credential_request_routes as routes
    from utils.async_helpers import drain_spawned_tasks

    _, calls = empty_probe
    row = dict(
        id="fixture-request", token="fixture-token", requester_id="fixture-user",
        credential_type="reachability_probe", status="pending", expires_at=None,
        provision_attempts=0, target_email=None,
    )
    pool = SimpleNamespace(fetchrow=AsyncMock(return_value=row), execute=AsyncMock())
    monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
    persist = AsyncMock(return_value={"status": "success", "credential_id": "fixture-credential"})
    monkeypatch.setattr(routes, "_store_and_fulfill", persist)

    result = await routes.provide_credential("fixture-token", routes.ProvideCredentialBody(
        credential_data={"api_key": " fixture-key "},
    ))
    await drain_spawned_tasks()
    assert result["status"] == "success"
    _assert_reachability_only(result["verification"])
    persist.assert_awaited_once()
    assert persist.call_args.args[3] == {"api_key": "fixture-key"}
    metadata = persist.call_args.args[5]
    assert metadata["verified_at"] and "verified_as" not in metadata
    assert calls == [("language", {"api_key": "fixture-key"})]
