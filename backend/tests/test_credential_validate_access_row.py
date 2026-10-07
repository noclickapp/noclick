"""Post-connect probes use accessible, unrevoked, authoritative credential rows.

Storage, encryption, sockets and provider boundaries are synthetic. The real
handler, canonical loaders, node type registry and GBP access hook execute.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from repositories.credentials import credential_access_predicate
from utils import credentials
from wss.handlers import credentials_handler as handler_module
from wss.receiver.client_events import CredentialValidateAccessRequest

GBP = "automation-google-business-profile"
SHEETS = "automation-google-sheets"
CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
UPDATED = datetime(2026, 10, 5, tzinfo=timezone.utc)


class _Connection:
    def __init__(self, row, allowed_users):
        self.row = row
        self.allowed_users = set(allowed_users)
        self.allowed_contexts = None
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def fetchrow(self, sql, credential_id, user_id, org_id):
        self.calls.append((sql, credential_id, user_id, org_id))
        accessible = user_id in self.allowed_users
        if self.allowed_contexts is not None:
            accessible = (user_id, org_id) in self.allowed_contexts
        return self.row if credential_id == CID and accessible else None


class _Pool:
    def __init__(self, row, allowed_users):
        self.connection = _Connection(row, allowed_users)

    def acquire(self):
        return self.connection


def _row(credential_type="google_business_profile_oauth", *, revoked=False):
    return {
        "id": CID, "name": "Fixture account", "credential_type": credential_type,
        "credential": b"synthetic-encrypted-row", "metadata": {},
        "created_at": UPDATED, "updated_at": UPDATED, "token_version": 7,
        "owner_id": USER, "approval_revision": 0,
        "revoked_at": UPDATED if revoked else None,
    }


def _blob(**updates):
    return {
        "access_token": "synthetic-access-token", "refresh_token": "synthetic-refresh-token",
        "expires_at": "2099-01-01T00:00:00+00:00", "email": "fixture@example.test",
        "client_id": "synthetic-client-id", "client_secret": "synthetic-client-secret",
        **updates,
    }


@pytest.fixture
def harness(monkeypatch):
    from nodes.google_business_profile_node import GoogleBusinessProfileNode
    from nodes.oauth import google_oauth
    from wss.handlers import workflow_handler
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))

    encryption = MagicMock()
    encryption.decrypt_credential.side_effect = lambda _encrypted: deepcopy(state.blob)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: encryption)
    monkeypatch.setattr(handler_module, "get_encryption", lambda: encryption)
    monkeypatch.setattr(credentials, "get_encryption", lambda: encryption)
    org_context = AsyncMock(return_value=ORG)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", org_context)
    monkeypatch.setattr(handler_module, "get_user_org_context", org_context)

    refresh = AsyncMock(return_value=SimpleNamespace(access_token="synthetic-probe-access"))
    monkeypatch.setattr(google_oauth, "refresh_access_token", refresh)
    provider_requests = []

    class LocalClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, **kwargs):
            provider_requests.append((url, kwargs))
            return httpx.Response(200, json={"accounts": []})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: LocalClient())
    probe = AsyncMock(wraps=GoogleBusinessProfileNode.validate_credential_access)
    monkeypatch.setattr(GoogleBusinessProfileNode, "validate_credential_access", probe)
    responses = []

    async def capture(_sio, sid, response):
        assert sid == "fixture-sid" and response.request_id == "fixture-request"
        responses.append(response.model_dump())

    monkeypatch.setattr(handler_module, "send_event", capture)
    sio = AsyncMock()
    sio.get_session.return_value = {"user_id": USER}
    handler = handler_module.CredentialsHandler(sio)
    state = SimpleNamespace(
        blob=_blob(), encryption=encryption, pool=_Pool(_row(), {USER}),
        handler=handler, probe=probe, refresh=refresh, provider_requests=provider_requests,
        responses=responses, org_context=org_context,
    )
    handler.get_pool = AsyncMock(side_effect=lambda: state.pool)
    return state


async def _validate(state, node_type=GBP, credential_id=CID):
    request = CredentialValidateAccessRequest(
        request_id="fixture-request", node_type=node_type, credential_id=credential_id,
    )
    await state.handler.get_events()[request.event_name]("fixture-sid", request)
    assert len(state.responses) == 1
    return state.responses[0]["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blob_type", [None, "slack_oauth"])
async def test_accessible_current_row_supplies_authoritative_type_and_refresh_metadata(harness, blob_type):
    if blob_type:
        harness.blob["credential_type"] = blob_type
    result = await _validate(harness)
    assert result == {"valid": True}
    data = harness.probe.await_args.args[0]
    assert data == {**harness.blob, "credential_type": "google_business_profile_oauth", "token_version": 7, "updated_at": UPDATED.isoformat()}
    harness.refresh.assert_awaited_once_with(
        "synthetic-refresh-token", custom_client_id="synthetic-client-id",
        custom_client_secret="synthetic-client-secret",
    )
    assert len(harness.provider_requests) == 1
    url, kwargs = harness.provider_requests[0]
    assert url == "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
    assert kwargs["headers"] == {"Authorization": "Bearer synthetic-probe-access"}
    sql, cid, user, org = harness.pool.connection.calls[0]
    assert credential_access_predicate() in sql
    assert all(column in sql for column in ("c.credential_type", "c.revoked_at", "c.token_version", "c.updated_at"))
    assert (cid, user, org) == (CID, USER, ORG)


@pytest.mark.asyncio
@pytest.mark.parametrize("org_id", [None, ORG])
async def test_direct_loader_keeps_caller_organization_binding(harness, org_id):
    harness.org_context.return_value = org_id
    assert (await _validate(harness))["valid"] is True
    assert harness.pool.connection.calls[0][1:] == (CID, USER, org_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("access_case,org_id,permitted", [
    ("direct-user-share", None, True),
    ("current-org-share", ORG, True),
    ("wrong-org-share", OWNER, False),
    ("personal-context-org-share", None, False),
    ("transferred-without-share", ORG, False),
])
async def test_current_access_result_and_context_are_respected(harness, access_case, org_id, permitted):
    """Synthetic storage answers model the canonical predicate's access result.

    This pins handler/loader query bindings, not execution of SQL ACL policies.
    """
    harness.org_context.return_value = org_id
    if access_case == "direct-user-share":
        harness.pool.connection.allowed_users = {USER, OWNER}
    elif access_case == "transferred-without-share":
        harness.pool.connection.allowed_users = {OWNER}
    else:
        harness.pool.connection.allowed_contexts = {(USER, ORG)}
    result = await _validate(harness)
    assert result["valid"] is permitted
    sql, cid, user, org = harness.pool.connection.calls[0]
    assert credential_access_predicate() in sql
    assert (cid, user, org) == (CID, USER, org_id)
    if permitted:
        assert harness.refresh.await_count == len(harness.provider_requests) == 1
    else:
        harness.encryption.decrypt_credential.assert_not_called()
        harness.probe.assert_not_awaited()
        harness.refresh.assert_not_awaited()
        assert harness.provider_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["missing", "denied", "revoked"])
@pytest.mark.parametrize("node_type", [GBP, SHEETS])
async def test_unavailable_row_refused_before_decryption_or_any_provider_probe(harness, unavailable, node_type):
    harness.pool.connection.row = _row("google_sheets_oauth" if node_type == SHEETS else "google_business_profile_oauth", revoked=unavailable == "revoked")
    if unavailable == "missing":
        harness.pool.connection.row = None
    elif unavailable == "denied":
        harness.pool.connection.allowed_users.clear()
    result = await _validate(harness, node_type)
    assert result == {"valid": False, "error": "Credential is unavailable or access denied"}
    harness.encryption.decrypt_credential.assert_not_called()
    harness.probe.assert_not_awaited()
    harness.refresh.assert_not_awaited()
    assert harness.provider_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("blob_type", [None, "google_business_profile_oauth"])
@pytest.mark.parametrize("row_type", ["slack_oauth", "google_gmail_oauth"])
async def test_foreign_authoritative_type_cannot_redeem_its_token_at_google(harness, blob_type, row_type):
    harness.pool.connection.row = _row(row_type)
    if blob_type:
        harness.blob["credential_type"] = blob_type
    result = await _validate(harness)
    assert result == {"valid": False, "error": "Credential type is not supported by this node"}
    harness.probe.assert_not_awaited()
    harness.refresh.assert_not_awaited()
    assert harness.provider_requests == []


@pytest.mark.asyncio
async def test_no_hook_success_requires_accessible_matching_row(harness):
    harness.pool.connection.row = _row("google_sheets_oauth")
    assert await _validate(harness, SHEETS) == {"valid": True}
    harness.probe.assert_not_awaited()
    harness.refresh.assert_not_awaited()
    assert harness.provider_requests == []


@pytest.mark.asyncio
async def test_no_hook_foreign_row_is_invalid(harness):
    assert await _validate(harness, SHEETS) == {"valid": False, "error": "Credential type is not supported by this node"}
    harness.refresh.assert_not_awaited()
    assert harness.provider_requests == []


@pytest.mark.asyncio
async def test_unknown_node_and_empty_credential_id_cannot_report_success(harness):
    assert await _validate(harness, "automation-unknown") == {"valid": False, "error": "Unknown node type"}
    assert harness.pool.connection.calls == []
    harness.responses.clear()
    assert (await _validate(harness, credential_id=""))["valid"] is False
    assert harness.pool.connection.calls == []
    harness.refresh.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fetch", "decrypt"])
async def test_storage_failure_is_unverified_and_does_not_probe(harness, failure):
    if failure == "fetch":
        harness.pool.connection.fetchrow = AsyncMock(side_effect=RuntimeError("synthetic storage failure"))
    else:
        harness.encryption.decrypt_credential.side_effect = RuntimeError("synthetic decryption failure")
    assert await _validate(harness) == {"valid": None, "error": "Credential access could not be verified. Retry validation."}
    harness.probe.assert_not_awaited()
    harness.refresh.assert_not_awaited()
    assert harness.provider_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized,revoked,expected", [(True, False, True), (False, False, False), (True, True, False)])
async def test_separate_authorized_owner_fallback_policy_remains_scoped_and_revocation_aware(harness, monkeypatch, authorized, revoked, expected):
    harness.pool.connection.row = _row(revoked=revoked)
    harness.pool.connection.allowed_users = {OWNER}
    gate = AsyncMock(return_value=authorized)
    owner = AsyncMock(return_value=OWNER)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", gate)
    result = await credentials.resolve_credential_with_owner_fallback(
        CID, USER, harness.pool, org_id=ORG, workflow_id="fixture-workflow", get_owner_id=owner,
    )
    assert bool(result) is expected
    assert [call[2] for call in harness.pool.connection.calls] == ([USER, OWNER] if authorized else [USER])
    gate.assert_awaited_once_with(harness.pool, "fixture-workflow", CID)
    if result:
        assert result["credential_type"] == "google_business_profile_oauth"
    else:
        harness.encryption.decrypt_credential.assert_not_called()
    harness.pool.connection.calls.clear()
    harness.encryption.decrypt_credential.reset_mock()
    harness.responses.clear()
    # The post-connect event has no workflow context: even an owner-authorized
    # workflow credential cannot be borrowed for this separate user request.
    assert (await _validate(harness))["valid"] is False
    assert [call[2] for call in harness.pool.connection.calls] == [USER]
    harness.encryption.decrypt_credential.assert_not_called()
    harness.refresh.assert_not_awaited()
    assert harness.provider_requests == []
