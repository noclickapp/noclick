"""Post-connect probes retain trusted current authority and native admission.

The registered receiver, handler, repository, resolver, factory and collector
run against synthetic storage/encryption and a local provider HTTP transport.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from nodes.core.credential_validation import CredentialValidationContext, accepts_validation_context
from repositories.credentials import credential_access_predicate
from wss.receiver.client_events import CredentialValidateAccessRequest

NODE = "automation-affinity"
GBP = "automation-google-business-profile"
EVENT = "credential:validate_access"
CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
UPDATED = datetime(2026, 10, 5, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    yield


class _Scope:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Storage:
    """Pins SQL/current actor bindings; it does not execute database ACL SQL."""
    def __init__(self):
        self.row = {
            "id": CID, "name": "Fixture", "owner_id": OWNER,
            "credential_type": "affinity_api_key", "credential": b"synthetic-ciphertext",
            "token_version": 7, "updated_at": UPDATED, "revoked_at": None,
            "approval_operations": [], "approval_revision": 1,
        }
        self.allowed = {(USER, ORG)}
        self.grants, self.calls, self.timeline = {}, [], []
        self.transactions = 0
        self.on_load = None
        self.on_resolve = None
        self.on_admit = None

    def acquire(self):
        return _Scope(self)

    def transaction(self):
        self.transactions += 1
        return _Scope(self)

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "SELECT c.credential" in sql:
            assert credential_access_predicate() in sql
            self.timeline.append("current-row")
            if self.on_load:
                self.on_load()
            if self.on_resolve and "SELECT c.credential, c.revoked_at, c.credential_type" in sql:
                self.on_resolve()
            cid, actor, org = args
            return deepcopy(self.row) if cid == CID and (actor, org) in self.allowed else None
        if "SELECT name,owner_id,approval_operations" in sql:
            assert args == (CID,) and "FOR UPDATE" in sql
            self.timeline.append("admission")
            if self.on_admit:
                self.on_admit()
            return deepcopy(self.row)
        if "SELECT id,status,consumed_at,expires_at" in sql:
            grant = self.grants.get(args[1])
            return grant if grant and grant["consumed_at"] is None and not grant["expired"] else None
        if "INSERT INTO approval_requests" in sql:
            fingerprint, payload = args[-2:]
            grant = {"id": UUID(int=100 + len(self.grants)), "status": "pending",
                "consumed_at": None, "expires_at": UPDATED, "expired": False,
                "payload": deepcopy(payload)}
            self.grants[fingerprint] = grant
            self.timeline.append("approval-created")
            return grant
        raise AssertionError(f"Unexpected synthetic query: {sql}")

    async def fetchval(self, sql, *args):
        assert "SELECT count(*) FROM approval_requests" in sql and args == (CID,)
        return sum(g["status"] == "pending" and not g["expired"] for g in self.grants.values())

    async def execute(self, sql, identifier):
        assert sql == "UPDATE approval_requests SET consumed_at=now() WHERE id=$1"
        for grant in self.grants.values():
            if grant["id"] == identifier:
                grant["consumed_at"] = UPDATED
                self.timeline.append("approval-consumed")
                return "UPDATE 1"
        raise AssertionError("Unknown approval")


@pytest.fixture
def native(monkeypatch):
    from nodes.affinity_node import AffinityNode
    from utils import credentials
    from wss.handlers import credentials_handler, workflow_handler
    from wss.receiver.chunk_reassembly import ChunkReassemblyManager
    from wss.receiver.event_routing import EVENT_ROUTING, Handler
    from wss.receiver.receiver import SocketIOProxy
    from wss.receiver.rate_limiter import RateLimiter
    from wss.receiver.rate_limits import get_rate_limit_config

    state = SimpleNamespace(storage=_Storage(), blob={"api_key": "synthetic-key", "credential_type": "foreign-blob"},
        contexts=[], hooked=[], responses=[], notifications=[], requests=[], provider_callback=None,
        provider_status=200, provider_error=None, hook_mode="operation")
    crypto = MagicMock()
    def decrypt(_ciphertext):
        state.storage.timeline.append("decrypt")
        return deepcopy(state.blob)
    crypto.decrypt_credential.side_effect = decrypt
    state.crypto = crypto
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials_handler, "get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    state.org = AsyncMock(return_value=ORG)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", state.org)

    async def hook(cls, data, *, validation_context):
        state.contexts.append(validation_context)
        state.hooked.append(deepcopy(data))
        if state.hook_mode == "evidence":
            evidence = await validation_context.collect_evidence()
            return {"valid": evidence.reachable is True, "label": evidence.samples[0].label}
        if state.hook_mode == "catch-pending":
            try:
                await validation_context.run_operation("list_lists")
            except ValueError:
                return {"valid": True, "label": "provider cannot authorize a parked call"}
        result = await validation_context.run_operation("list_lists")
        return {"valid": result.get("status") == "success"}
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(hook), raising=False)

    async def provider(request):
        state.requests.append(request)
        state.storage.timeline.append("provider")
        if state.provider_callback:
            state.provider_callback()
        if state.provider_error is not None:
            raise state.provider_error
        return httpx.Response(state.provider_status, json={"lists": [{"id": 42, "name": "Owned fixture"}]})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs))

    async def capture(_sio, sid, event, **kwargs):
        if kwargs.get("user_id"):
            state.notifications.append(event.model_dump())
        else:
            assert sid == "fixture-sid"
            state.responses.append(event.model_dump())
    monkeypatch.setattr(credentials_handler, "send_event", capture)
    monkeypatch.setattr("wss.sender.send_event", capture)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: sio)
    monkeypatch.setattr("utils.user_presence.touch_user_presence", lambda _user: None)
    handler = credentials_handler.CredentialsHandler(sio)
    handler.get_pool = AsyncMock(return_value=state.storage)
    proxy = SocketIOProxy.__new__(SocketIOProxy)
    proxy.sio, proxy.SOCKET_PROXY_ENV = sio, "API"
    proxy.chunk_manager = ChunkReassemblyManager()
    proxy.rate_limiter = RateLimiter(get_rate_limit_config())
    assert EVENT_ROUTING["API"][EVENT] == Handler.CREDENTIALS
    proxy.config = SimpleNamespace(event_handlers={"API": {EVENT: [handler]}})
    proxy.frontend_request_pydantic_models = {EVENT: CredentialValidateAccessRequest}
    proxy._last_heavy_completion = {}
    state.proxy, state.handler = proxy, handler
    return state


async def _validate(state, **extras):
    count = len(state.responses)
    await state.proxy._route_event_impl(EVENT, "fixture-sid", {
        "request_id": "fixture-request", "credential_id": CID, "node_type": NODE, **extras,
    })
    assert len(state.responses) == count + 1
    return state.responses[-1]["data"]


@pytest.mark.asyncio
async def test_actual_registered_handler_factory_resolver_and_provider_keep_trusted_context(native):
    result = await _validate(native, user_id=OWNER, organization_id=OWNER, workflow_id="forged-workflow",
        validation_context={"credential_id": "forged", "approved": True})
    assert result == {"valid": True}
    context = native.contexts[0]
    assert isinstance(context, CredentialValidationContext)
    assert (context.credential_id, context.user_id, context.organization_id, context.workflow_id) == (CID, USER, ORG, None)
    assert context.pool is native.storage and context.node_type == NODE
    assert native.hooked[0]["credential_type"] == "affinity_api_key"
    assert native.hooked[0]["token_version"] == 7
    assert len(native.requests) == 1 and native.requests[0].method == "GET"
    assert native.requests[0].url.path == "/lists"
    assert native.requests[0].headers["authorization"].startswith("Basic ")
    assert native.storage.transactions == 2
    assert all(args == (CID, USER, ORG) for sql, args in native.storage.calls if "SELECT c.credential" in sql)
    assert native.storage.timeline.index("admission") < native.storage.timeline.index("decrypt")
    assert "synthetic-key" not in repr(context) and "synthetic-ciphertext" not in repr(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["foreign", "null-type", "revoked", "denied"])
async def test_current_row_refuses_before_decrypt_policy_or_native_factory_provider(native, unavailable):
    if unavailable == "foreign":
        native.storage.row["credential_type"] = "google_business_profile_oauth"
    elif unavailable == "null-type":
        native.storage.row["credential_type"] = None
        native.blob["credential_type"] = "affinity_api_key"
    elif unavailable == "revoked":
        native.storage.row["revoked_at"] = UPDATED
    else:
        native.storage.allowed.clear()
    assert (await _validate(native))["valid"] is False
    native.crypto.decrypt_credential.assert_not_called()
    assert native.hooked == [] and native.requests == [] and native.storage.transactions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_context,allowed", [(None, {(USER, None)}), (ORG, {(USER, ORG)}), (None, {(USER, ORG)}), (ORG, {(OWNER, ORG)})])
async def test_current_direct_share_and_org_acl_positive_negative(native, actor_context, allowed):
    native.org.return_value = actor_context
    native.storage.allowed = allowed
    permitted = (USER, actor_context) in allowed
    assert (await _validate(native))["valid"] is permitted
    assert bool(native.requests) is permitted
    assert all(args == (CID, USER, actor_context) for sql, args in native.storage.calls if "SELECT c.credential" in sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["pending", "rejected", "approved"])
async def test_exact_hook_approval_is_secret_free_single_use_and_precedes_decryption(native, decision):
    native.storage.row["approval_operations"] = ["*"]
    initial = await _validate(native)
    assert initial["valid"] is False and initial["executed"] is False
    assert native.requests == [] and native.hooked == []
    native.crypto.decrypt_credential.assert_not_called()
    grant = next(iter(native.storage.grants.values()))
    payload = grant["payload"]
    assert payload["operation"] == "__lookup__" and payload["caller_user_id"] == USER
    assert payload["organization_id"] == ORG and payload["workflow_id"] is None
    authority = payload["arguments"]["context"]
    assert authority == {"owner_id": OWNER, "credential_type": "affinity_api_key", "token_version": 7,
        "updated_at": UPDATED.isoformat(), "approval_revision": 1}
    assert "synthetic-key" not in repr(payload) and "synthetic-ciphertext" not in repr(payload)
    grant["status"] = decision
    result = await _validate(native)
    assert result["valid"] is False and result["executed"] is False
    if decision == "approved":
        # The actual native operation has its own exact policy decision.
        assert grant["consumed_at"] is not None and len(native.storage.grants) == 2
        operation_grant = next(reversed(native.storage.grants.values()))
        assert operation_grant["payload"]["operation"] == "list_lists"
        operation_grant["status"] = "approved"
        # A fresh outer approval is also required; no grant is silently reused.
        third = await _validate(native)
        assert third["valid"] is False and native.requests == []
    else:
        assert grant["consumed_at"] is None and native.hooked == []
    assert native.requests == []


@pytest.mark.asyncio
async def test_restricted_native_hook_and_operation_both_admit_exact_grants_before_provider(native):
    native.storage.row["approval_operations"] = ["*"]
    await _validate(native)
    first = next(iter(native.storage.grants.values()))
    first["status"] = "approved"
    await _validate(native)
    operation = next(reversed(native.storage.grants.values()))
    operation["status"] = "approved"
    await _validate(native)
    outer = next(grant for grant in native.storage.grants.values()
        if grant["payload"]["operation"] == "__lookup__" and grant["consumed_at"] is None)
    outer["status"] = "approved"
    assert await _validate(native) == {"valid": True}
    assert first["consumed_at"] is not None and operation["consumed_at"] is not None and outer["consumed_at"] is not None
    assert len(native.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "version", "ciphertext", "policy"])
async def test_old_hook_grant_cannot_authorize_changed_row_even_if_access_still_exists(native, change):
    native.storage.row["approval_operations"] = ["*"]
    await _validate(native)
    old = next(iter(native.storage.grants.values()))
    old["status"] = "approved"
    key, value = {"owner": ("owner_id", USER), "version": ("token_version", 8),
        "ciphertext": ("credential", b"rotated-ciphertext"), "policy": ("approval_revision", 2)}[change]
    native.storage.row[key] = value
    if change == "ciphertext":
        native.storage.row["updated_at"] = UPDATED.replace(second=1)
    result = await _validate(native)
    assert result["valid"] is False and result["status"] == "pending_approval"
    assert old["consumed_at"] is None and len(native.storage.grants) == 2
    assert native.requests == [] and native.hooked == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "foreign", "owner", "version", "ciphertext", "policy", "acl", "org"])
async def test_provider_success_cannot_accept_changed_authority_or_current_access(native, change):
    def mutate():
        if change == "acl":
            native.storage.allowed.clear()
        elif change == "org":
            native.org.return_value = None
        else:
            key, value = {"revoked": ("revoked_at", UPDATED), "foreign": ("credential_type", "slack_oauth"),
                "owner": ("owner_id", USER), "version": ("token_version", 8),
                "ciphertext": ("credential", b"new-ciphertext"), "policy": ("approval_revision", 2)}[change]
            native.storage.row[key] = value
    native.provider_callback = mutate
    result = await _validate(native)
    assert result["valid"] is False and len(native.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "foreign", "owner", "version", "ciphertext", "policy", "acl"])
async def test_authority_changed_before_decryption_cannot_reach_hook(native, change):
    loads = 0
    def mutate_before_decrypt():
        nonlocal loads
        loads += 1
        if loads != 4:
            return
        if change == "acl":
            native.storage.allowed.clear()
        else:
            key, value = {"revoked": ("revoked_at", UPDATED), "foreign": ("credential_type", "slack_oauth"),
                "owner": ("owner_id", USER), "version": ("token_version", 8),
                "ciphertext": ("credential", b"new-ciphertext"), "policy": ("approval_revision", 2)}[change]
            native.storage.row[key] = value
    native.storage.on_load = mutate_before_decrypt
    assert (await _validate(native))["valid"] is False
    native.crypto.decrypt_credential.assert_not_called()
    assert native.hooked == [] and native.requests == []


@pytest.mark.asyncio
async def test_foreign_current_resolver_result_is_refused_before_inherited_factory_coercion(native):
    def change_family_during_resolve():
        native.storage.row["credential_type"] = "foreign_service"
    native.storage.on_resolve = change_family_during_resolve
    assert (await _validate(native))["valid"] is False
    assert len(native.hooked) == 1 and native.requests == []


@pytest.mark.asyncio
async def test_hook_cannot_catch_native_pending_and_claim_acceptance(native):
    native.storage.row["approval_operations"] = [f"{NODE}.list_lists"]
    native.hook_mode = "catch-pending"
    await _validate(native)
    first = next(iter(native.storage.grants.values()))
    first["status"] = "approved"
    result = await _validate(native)
    assert result["valid"] is False and result["executed"] is False
    assert result["status"] == "pending_approval" and native.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_status", [200, 403])
async def test_actual_operation_evidence_collector_preserves_unverified_refusal(native, provider_status):
    native.hook_mode, native.provider_status = "evidence", provider_status
    result = await _validate(native)
    assert result["valid"] is (True if provider_status == 200 else None)
    if provider_status == 200:
        assert result["label"] == "Owned fixture"
    assert len(native.requests) == 1


def test_context_opt_in_is_explicit_and_legacy_one_argument_hook_remains_supported():
    async def legacy(data):
        return {"valid": True}
    async def generic(data, **kwargs):
        return {"valid": True}
    async def typed(data, *, validation_context: CredentialValidationContext):
        return {"valid": True}
    assert not accepts_validation_context(legacy)
    assert not accepts_validation_context(generic)
    assert accepts_validation_context(typed)


@pytest.mark.asyncio
async def test_registered_legacy_hook_has_original_call_shape_and_final_authority_guard(native, monkeypatch):
    from nodes.affinity_node import AffinityNode
    calls = []
    async def legacy(cls, data):
        calls.append(data)
        native.storage.row["owner_id"] = USER
        return {"valid": True, "account": "provider labels confer no authority"}
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(legacy))
    assert (await _validate(native))["valid"] is False
    assert len(calls) == 1 and calls[0]["credential_type"] == "affinity_api_key"
    assert native.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["write-operation", "field-evidence"])
async def test_context_cannot_route_a_write_or_uncomposed_stored_field_collector(native, monkeypatch, boundary):
    from nodes.affinity_node import AffinityNode
    from nodes.core.connection_evidence import ConnectionEvidence
    async def hook(cls, data, *, validation_context):
        if boundary == "write-operation":
            await validation_context.run_operation("create_person", {"first_name": "No mutation"})
        else:
            await validation_context.collect_evidence()
        return {"valid": True}
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(hook))
    if boundary == "field-evidence":
        monkeypatch.setattr(AffinityNode, "connection_evidence", ConnectionEvidence(field="list_id", noun="lists"))
    assert (await _validate(native))["valid"] is None
    assert native.requests == [] and native.storage.transactions == 1


@pytest.mark.asyncio
async def test_gbp_opt_in_rechecks_after_refresh_before_account_api(native, monkeypatch):
    from nodes.oauth import google_oauth
    native.storage.row["credential_type"] = "google_business_profile_oauth"
    native.blob = {"refresh_token": "synthetic-refresh", "access_token": "synthetic-access",
        "expires_at": "2099-01-01T00:00:00Z", "client_id": "fixture-client", "client_secret": "fixture-secret"}
    async def refresh(*args, **kwargs):
        native.storage.row["revoked_at"] = UPDATED
        return SimpleNamespace(access_token="minted-old-token")
    refreshed = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(google_oauth, "refresh_access_token", refreshed)
    result = await _validate(native, node_type=GBP)
    assert result["valid"] is False
    refreshed.assert_awaited_once()
    assert native.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 500, 503])
async def test_actual_gbp_hook_never_accepts_refusal_or_outage_as_access(native, monkeypatch, status):
    from nodes.oauth import google_oauth
    native.storage.row["credential_type"] = "google_business_profile_oauth"
    native.blob = {"refresh_token": "synthetic-refresh", "access_token": "synthetic-access",
        "expires_at": "2099-01-01T00:00:00Z"}
    monkeypatch.setattr(google_oauth, "refresh_access_token", AsyncMock(return_value=SimpleNamespace(access_token="minted-token")))
    native.provider_status = status
    result = await _validate(native, node_type=GBP)
    assert result["valid"] is False and f"HTTP {status}" in result["error"]
    assert len(native.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False, None])
@pytest.mark.parametrize("typed", [False, True], ids=["legacy-hook", "context-hook"])
async def test_registered_native_hook_preserves_explicit_tri_state_and_only_true_accepts(native, monkeypatch, valid, typed):
    from nodes.affinity_node import AffinityNode
    accepted, hooked = [], []
    original_accept = CredentialValidationContext.accept

    async def accept(context, result):
        accepted.append((context, deepcopy(result)))
        await original_accept(context, result)

    async def legacy(cls, data):
        hooked.append(data)
        return {"valid": valid, "error": "Static fixture guidance", "help_url": "https://example.com/help"}

    async def with_context(cls, data, *, validation_context):
        assert (validation_context.user_id, validation_context.organization_id, validation_context.workflow_id) == (USER, ORG, None)
        await validation_context.run_operation("list_lists")
        return await legacy(cls, data)

    monkeypatch.setattr(CredentialValidationContext, "accept", accept)
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(with_context if typed else legacy))
    result = await _validate(native, organization_id=OWNER, workflow_id="forged", valid=True)
    assert result == {"valid": valid, "error": "Static fixture guidance", "help_url": "https://example.com/help"}
    assert len(accepted) == (1 if valid is True else 0)
    assert hooked[0]["credential_type"] == "affinity_api_key" and hooked[0]["token_version"] == 7
    assert len(native.requests) == (1 if typed else 0)
    assert native.storage.transactions == (2 if typed else 1)
    assert native.storage.timeline.index("admission") < native.storage.timeline.index("decrypt")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], {}, {"error": "synthetic-private-error"},
    {"valid": 1}, {"valid": 0}, {"valid": "true"}, {"valid": []}, {"valid": {}}])
async def test_registered_native_hook_malformed_result_is_unknown_without_acceptance(native, monkeypatch, payload):
    from nodes.affinity_node import AffinityNode
    accepted = AsyncMock()
    async def hook(cls, data, *, validation_context):
        assert data["credential_type"] == "affinity_api_key"
        return deepcopy(payload)
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(hook))
    monkeypatch.setattr(CredentialValidationContext, "accept", accepted)
    assert await _validate(native) == {"valid": None, "error": "Invalid credential validation response"}
    accepted.assert_not_awaited()
    assert native.storage.transactions == 1 and native.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("synthetic-private-auth"), httpx.ReadTimeout("synthetic-private-auth")], ids=["provider-error", "transport-error"])
async def test_registered_hook_failure_is_unknown_and_does_not_disclose_exception(native, monkeypatch, failure):
    from nodes.affinity_node import AffinityNode
    from wss.handlers import credentials_handler
    log = MagicMock()
    accepted = AsyncMock()
    async def hook(cls, data, *, validation_context):
        raise failure
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(hook))
    monkeypatch.setattr(CredentialValidationContext, "accept", accepted)
    monkeypatch.setattr(credentials_handler, "logger", log)
    assert await _validate(native) == {"valid": None, "error": "Credential access could not be verified. Retry validation."}
    log.error.assert_called_once_with("[CredentialsHandler] credential access probe failed")
    accepted.assert_not_awaited()
    assert native.requests == [] and native.storage.transactions == 1


@pytest.mark.asyncio
async def test_registered_handler_setup_failure_is_unknown_with_static_error(native, monkeypatch):
    from wss.handlers import credentials_handler
    log = MagicMock()
    monkeypatch.setattr(credentials_handler, "logger", log)
    native.handler.get_pool.side_effect = RuntimeError("synthetic-private-auth")
    assert await _validate(native) == {"valid": None, "error": "Credential access could not be verified. Retry validation."}
    log.error.assert_called_once_with("[CredentialsHandler] credential access validation failed")
    assert native.storage.calls == [] and native.requests == [] and native.hooked == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["operation", "evidence"])
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_actual_native_factory_probe_error_is_unverified_not_invalid(native, mode, status):
    native.hook_mode, native.provider_status = mode, status
    assert await _validate(native) == {"valid": None, "error": "The credential access probe did not complete successfully"}
    assert len(native.requests) == 1 and native.requests[0].url.path == "/lists"
    assert native.storage.transactions == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["operation", "evidence"])
async def test_actual_native_transport_timeout_is_unverified(native, mode):
    native.hook_mode = mode
    native.provider_error = httpx.ReadTimeout("synthetic-private-auth")
    result = await _validate(native)
    assert result == {"valid": None, "error": "The credential access probe did not complete successfully"}
    assert "synthetic-private-auth" not in str(native.responses)
    assert len(native.requests) == 1 and native.storage.transactions == 2


@pytest.mark.asyncio
async def test_hook_cannot_catch_native_error_and_claim_acceptance(native, monkeypatch):
    from nodes.affinity_node import AffinityNode
    async def hook(cls, data, *, validation_context):
        try:
            await validation_context.run_operation("list_lists")
        except ValueError:
            return {"valid": True, "label": "A caught failure is not provider evidence"}
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(hook))
    native.provider_status = 403
    assert await _validate(native) == {"valid": None, "error": "The credential access probe did not complete successfully"}
    assert len(native.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("control", [{"status": "error"}, {"success": False}, {"executed": False}])
async def test_explicit_true_with_failed_outer_probe_control_is_unverified_and_sanitized(native, monkeypatch, control):
    from nodes.affinity_node import AffinityNode
    async def hook(cls, data, *, validation_context):
        return {"valid": True, "error": "synthetic-private-auth", **control}
    monkeypatch.setattr(AffinityNode, "validate_credential_access", classmethod(hook))
    assert await _validate(native) == {"valid": None, "error": "The credential access probe did not complete successfully"}
    assert native.requests == [] and native.storage.transactions == 1


@pytest.mark.asyncio
async def test_current_revocation_is_definite_even_when_native_probe_is_unverified(native):
    native.provider_status = 403
    native.provider_callback = lambda: native.storage.row.update(revoked_at=UPDATED)
    assert await _validate(native) == {"valid": False, "error": "Credential is unavailable or access denied"}
    assert len(native.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["hook-admission", "native-admission"])
@pytest.mark.parametrize("change", ["revoked", "deleted"])
async def test_actual_admission_failure_keeps_definite_current_row_denial(native, stage, change):
    def mutate():
        expected_transactions = 1 if stage == "hook-admission" else 2
        if native.storage.transactions != expected_transactions:
            return
        if change == "deleted":
            native.storage.row = None
        else:
            native.storage.row["revoked_at"] = UPDATED
    native.storage.on_admit = mutate
    assert await _validate(native) == {"valid": False, "error": "Credential is unavailable or access denied"}
    assert native.requests == []
    if stage == "hook-admission":
        native.crypto.decrypt_credential.assert_not_called()
        assert native.hooked == []
    else:
        assert len(native.hooked) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "acl"])
async def test_actual_current_resolver_failure_keeps_definite_denial_before_factory(native, change):
    def mutate():
        if change == "acl":
            native.storage.allowed.clear()
        else:
            native.storage.row["revoked_at"] = UPDATED
    native.storage.on_resolve = mutate
    assert await _validate(native) == {"valid": False, "error": "Credential is unavailable or access denied"}
    assert len(native.hooked) == 1 and native.requests == []


@pytest.mark.asyncio
async def test_actual_admission_storage_error_with_unchanged_authority_is_unknown(native):
    def fail():
        raise RuntimeError("synthetic-private-auth")
    native.storage.on_admit = fail
    assert await _validate(native) == {"valid": None, "error": "Credential access could not be verified. Retry validation."}
    assert native.requests == [] and native.hooked == []
    native.crypto.decrypt_credential.assert_not_called()
