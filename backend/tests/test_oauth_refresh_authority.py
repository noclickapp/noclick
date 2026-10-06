"""Opt-in refresh authority races through real manager/repository contracts.

Synthetic storage evaluates configured access outcomes and expected conditional
write arguments. It is not PostgreSQL ACL/locking execution or provider traffic.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx
from pydantic import BaseModel

from nodes.core import oauth_refresh
from nodes.core.oauth_refresh_authority import AuthorityCredentialsTableStore
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL

CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
NEXT_OWNER = "00000000-0000-4000-8000-000000000003"
ORG = "00000000-0000-4000-8000-000000000004"
WF = "00000000-0000-4000-8000-000000000005"
KIND = "fixture_oauth"


@pytest.fixture
def ensure_native_db_pool():
    yield


def _expiry(fresh=False):
    return (datetime.now(timezone.utc) + timedelta(hours=1 if fresh else -1)).isoformat()


def _grant(*, fresh=False, **updates):
    return {"credential_type": KIND, "access_token": "fixture-old-access",
            "refresh_token": "fixture-old-refresh", "expires_at": _expiry(fresh),
            "client_id": "fixture-client", "account_id": "fixture-account", **updates}


def _validate(data):
    if data.get("credential_type") != KIND or not data.get("access_token") or not data.get("client_id"):
        raise ValueError("Fixture grant binding is invalid")
    keys = ("credential_type", "access_token", "refresh_token", "expires_at", "client_id",
            "account_id", "scope", "token_type", "region")
    return {key: deepcopy(data[key]) for key in keys if key in data}


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Storage:
    def __init__(self):
        self.row = {"owner_id": OWNER, "credential_type": KIND, "token_version": 7,
                    "updated_at": datetime.now(timezone.utc), "revoked_at": None,
                    "credential": b"fixture-opaque"}
        self.grant = _grant()
        self.current_org = ORG
        self.access = {(USER, ORG), (USER, None), (OWNER, ORG), (OWNER, None)}
        self.workflow_owner, self.workflow_authorized = OWNER, True
        self.calls, self.writes, self.revoke_tags = [], [], []
        self.error = None

    def acquire(self):
        return _Context(self)

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if self.error:
            raise self.error
        if sql == PRIMARY_ORG_SQL:
            assert args == (USER,)
            return {"organization_id": self.current_org} if self.current_org else None
        if "SELECT owner_id FROM workflows" in sql:
            assert args == (WF,)
            return {"owner_id": self.workflow_owner} if self.workflow_owner else None
        if "SELECT 1 FROM workflow_authorized_credentials" in sql:
            assert tuple(map(str, args)) == (WF, CID)
            return {"exists": 1} if self.workflow_authorized else None
        assert "SELECT c.credential, c.owner_id" in sql
        assert credential_access_predicate() in sql
        cid, principal, org, caller, current, workflow = args
        assert cid == CID and caller == USER
        allowed = (principal, org) in self.access
        if principal != caller:
            allowed = allowed and workflow == WF and self.workflow_owner == principal and self.workflow_authorized
        if current:
            allowed = allowed and org == self.current_org
        return deepcopy(self.row) if self.row is not None and allowed else None

    def _eligible(self, args):
        cid, principal, org, caller, current, workflow, owner, kind, version = args[:9]
        if self.row is None or cid != CID or (principal, org) not in self.access:
            return False
        if current and org != self.current_org:
            return False
        if principal != caller and not (workflow == WF and self.workflow_owner == principal and self.workflow_authorized):
            return False
        return (self.row["owner_id"] == owner and self.row["credential_type"] == kind
                and self.row["token_version"] == version and self.row["revoked_at"] is None)

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        assert credential_access_predicate() in sql
        assert "workflow_authorized_credentials" in sql and "w.owner_id = $2::uuid" in sql
        assert "c.owner_id = $7::uuid" in sql and "c.credential_type = $8" in sql
        assert "c.token_version = $9" in sql and "c.revoked_at IS NULL" in sql
        eligible = self._eligible(args)
        if "SET credential = $10" in sql:
            assert "revoked_at = NULL" not in sql and "revoked_reason = NULL" not in sql
            self.writes.append((args, eligible))
            if eligible:
                self.grant = json.loads(args[9])
                self.row["token_version"] += 1
        else:
            assert "SET revoked_at = NOW(), revoked_reason = $10" in sql
            if eligible:
                self.row["revoked_at"] = datetime.now(timezone.utc)
            self.revoke_tags.append("UPDATE 1" if eligible else "UPDATE 0")
        return "UPDATE 1" if eligible else "UPDATE 0"


@pytest.fixture
def harness(monkeypatch):
    storage = _Storage()
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _value: deepcopy(storage.grant)
    crypto.encrypt_credential.side_effect = lambda data: json.dumps(data).encode()
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    audit = AsyncMock()
    monkeypatch.setattr(oauth_refresh, "record_refresh_event", audit)
    revoke_checks = []

    async def synthetic_failure_threshold(**kwargs):
        # Audit threshold is an external boundary. Real submitted-anchor
        # conditional revoke executes, without an audit DB or notification.
        revoke_checks.append(kwargs["store"])
        await kwargs["store"].mark_revoked(storage, "fixture-provider-rejection")

    monkeypatch.setattr(oauth_refresh, "_maybe_auto_revoke", synthetic_failure_threshold)
    monkeypatch.setattr(oauth_refresh, "_REFRESH_RETRY_BACKOFF_S", (0, 0))
    store = AuthorityCredentialsTableStore(storage, USER, CID, credential_type=KIND,
                                          validate=_validate, grant_fields=("client_id", "account_id"))
    tokens = SimpleNamespace(access_token="fixture-minted-access", refresh_token="fixture-minted-refresh",
                             expires_at=_expiry(True), scope=None, token_type=None, region=None)
    refresh = AsyncMock(return_value=tokens)
    return SimpleNamespace(storage=storage, crypto=crypto, audit=audit, store=store,
                           refresh=refresh, tokens=tokens, revoke_checks=revoke_checks)


async def _run(harness, credential=None, **kwargs):
    credential = deepcopy(harness.storage.grant) if credential is None else credential
    result = await oauth_refresh.ensure_fresh_oauth_token(
        credential_id=CID, user_id=USER, credential=credential,
        refresh=harness.refresh, store=harness.store, provider="fixture", caller_path="fixture",
        **kwargs,
    )
    return result, credential


@pytest.mark.asyncio
async def test_normal_refresh_uses_actual_shared_owner_anchor_and_conditional_repository(harness):
    token, view = await _run(harness)
    assert token == view["access_token"] == "fixture-minted-access"
    harness.refresh.assert_awaited_once_with("fixture-old-refresh")
    assert harness.store.submitted.owner_id == OWNER
    assert harness.store.submitted.principal_id == USER
    assert harness.storage.writes[0][0][6:9] == (OWNER, KIND, 7)
    assert harness.storage.writes[0][1] is True
    assert "owner_id" not in harness.storage.grant and "token_version" not in harness.storage.grant
    assert harness.storage.row["revoked_at"] is None


@pytest.mark.asyncio
async def test_fresh_noop_reloads_authority_and_replaces_entire_stale_caller_view(harness):
    harness.storage.grant = _grant(fresh=True, access_token="fixture-current-access")
    del harness.storage.grant["account_id"]
    stale = _grant(fresh=True, account_id="stale-caller-account", legacy_secret="fixture-only-stale")
    token, view = await _run(harness, stale)
    assert token == "fixture-current-access"
    assert "account_id" not in view and "legacy_secret" not in view
    harness.refresh.assert_not_awaited()
    assert harness.storage.writes == [] and harness.store.current.owner_id == OWNER


@pytest.mark.asyncio
async def test_stale_predicate_only_sees_admitted_saved_view(harness):
    harness.storage.grant = _grant(fresh=True)
    def stale(data):
        assert data["client_id"] == "fixture-client"
        return False

    token, _view = await _run(harness, {}, stale=stale)
    assert token == "fixture-old-access"
    harness.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_unchanged_current_access_is_not_a_failure_winner_due_to_stale_caller(harness):
    harness.storage.grant = _grant(fresh=True, access_token="fixture-current-access")
    harness.refresh.side_effect = ValueError("invalid_grant: fixture rejected")
    with pytest.raises(oauth_refresh.OAuthRefreshError):
        await _run(harness, _grant(fresh=True, access_token="fixture-stale-caller-access"), force_refresh=True)
    assert harness.storage.revoke_tags == ["UPDATE 1"]


@pytest.mark.asyncio
async def test_decryption_failure_is_sanitized_before_provider(harness):
    harness.crypto.decrypt_credential.side_effect = ValueError("fixture-sensitive-decrypt-detail")
    with pytest.raises(ValueError, match="could not be decrypted") as exc:
        await _run(harness)
    assert "fixture-sensitive" not in str(exc.value)
    harness.refresh.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "denied", "revoked", "foreign_type", "bool_version", "missing_version", "invalid_owner", "fetch_error"])
async def test_raw_saved_authority_denied_before_decrypt_even_for_fresh_caller(harness, invalid):
    if invalid == "missing":
        harness.storage.row = None
    elif invalid == "denied":
        harness.storage.access.clear()
    elif invalid == "revoked":
        harness.storage.row["revoked_at"] = datetime.now(timezone.utc)
    elif invalid == "foreign_type":
        harness.storage.row["credential_type"] = "foreign_oauth"
    elif invalid == "bool_version":
        harness.storage.row["token_version"] = True
    elif invalid == "missing_version":
        harness.storage.row["token_version"] = None
    elif invalid == "invalid_owner":
        harness.storage.row["owner_id"] = None
    else:
        harness.storage.error = RuntimeError("fixture read failure")
    with pytest.raises((ValueError, RuntimeError)):
        await _run(harness, _grant(fresh=True))
    harness.crypto.decrypt_credential.assert_not_called()
    harness.refresh.assert_not_awaited()
    assert harness.storage.writes == [] and harness.revoke_checks == []


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["refresh", "app_equal_refresh", "account_equal_refresh"])
async def test_successful_old_mint_cannot_overwrite_fresh_same_id_reconnect(harness, replacement):
    async def raced(_token):
        changed = {"access_token": "fixture-reconnect-access"}
        changed[{"refresh": "refresh_token", "app_equal_refresh": "client_id", "account_equal_refresh": "account_id"}[replacement]] = "fixture-replacement"
        harness.storage.grant = _grant(fresh=True, **changed)
        harness.storage.row["token_version"] += 1
        return harness.tokens

    harness.refresh.side_effect = raced
    token, view = await _run(harness)
    assert token == view["access_token"] == "fixture-reconnect-access"
    assert len(harness.storage.writes) == 1 and not harness.storage.writes[0][1]
    assert harness.storage.grant["access_token"] == "fixture-reconnect-access"
    assert harness.store.submitted.token_version == 7 and harness.store.current.token_version == 8


@pytest.mark.asyncio
async def test_changed_expired_grant_aborts_without_overlay_retry(harness):
    async def raced(_token):
        harness.storage.grant["client_id"] = "fixture-reconnect-client"
        harness.storage.row["token_version"] += 1
        return harness.tokens

    harness.refresh.side_effect = raced
    with pytest.raises(ValueError, match="connection changed"):
        await _run(harness)
    assert len(harness.storage.writes) == 1 and not harness.storage.writes[0][1]
    assert harness.storage.grant["access_token"] == "fixture-old-access"


@pytest.mark.asyncio
async def test_same_grant_non_token_blob_change_can_retry_without_losing_current_fields(harness):
    async def raced(_token):
        harness.storage.grant["region"] = "fixture-new-region"
        harness.storage.row["token_version"] += 1
        return harness.tokens

    harness.refresh.side_effect = raced
    token, _view = await _run(harness)
    assert token == "fixture-minted-access"
    assert len(harness.storage.writes) == 2 and harness.storage.writes[1][1]
    assert harness.storage.grant["region"] == "fixture-new-region"


@pytest.mark.asyncio
async def test_same_grant_retry_removes_fields_omitted_by_current_winner(harness):
    harness.storage.grant["region"] = "fixture-old-nongrant-region"
    async def raced(_token):
        harness.storage.grant.pop("region")
        harness.storage.row["token_version"] += 1
        return harness.tokens

    harness.refresh.side_effect = raced
    token, view = await _run(harness)
    assert token == "fixture-minted-access"
    assert "region" not in view and "region" not in harness.storage.grant


@pytest.mark.asyncio
async def test_conservative_store_disables_same_grant_overlay(harness):
    harness.store.allow_same_grant_retry = False
    async def raced(_token):
        harness.storage.row["token_version"] += 1
        return harness.tokens

    harness.refresh.side_effect = raced
    with pytest.raises(ValueError, match="connection changed"):
        await _run(harness)
    assert len(harness.storage.writes) == 1 and harness.storage.grant["access_token"] == "fixture-old-access"


@pytest.mark.asyncio
@pytest.mark.parametrize("retains_access", [True, False])
async def test_owner_transfer_uses_current_policy_instead_of_equating_owner_with_runner(harness, retains_access):
    async def transfer(_token):
        harness.storage.row["owner_id"] = NEXT_OWNER
        if not retains_access:
            harness.storage.access.clear()
        return harness.tokens

    harness.refresh.side_effect = transfer
    if retains_access:
        with pytest.raises(ValueError, match="connection changed"):
            await _run(harness)
        assert len(harness.storage.writes) == 1 and not harness.storage.writes[0][1]
        assert harness.storage.grant["access_token"] == "fixture-old-access"
        assert harness.store.submitted.owner_id == OWNER
        assert harness.store.current.owner_id == NEXT_OWNER
    else:
        with pytest.raises(ValueError, match="access denied"):
            await _run(harness)
        assert len(harness.storage.writes) == 1 and not harness.storage.writes[0][1]


@pytest.mark.asyncio
async def test_new_refresh_after_transfer_can_use_current_retained_share(harness):
    harness.storage.row["owner_id"] = NEXT_OWNER
    token, _view = await _run(harness)
    assert token == "fixture-minted-access"
    assert harness.store.submitted.owner_id == NEXT_OWNER
    assert harness.storage.writes[0][0][6] == NEXT_OWNER
    assert len(harness.storage.writes) == 1 and harness.storage.writes[0][1]


@pytest.mark.asyncio
async def test_current_org_change_during_mint_cannot_upgrade_retry_authority(harness):
    async def transfer_policy(_token):
        harness.storage.current_org = NEXT_OWNER
        harness.storage.access.add((USER, NEXT_OWNER))
        return harness.tokens

    harness.refresh.side_effect = transfer_policy
    with pytest.raises(ValueError, match="connection changed"):
        await _run(harness)
    assert len(harness.storage.writes) == 1 and not harness.storage.writes[0][1]
    assert harness.storage.grant["access_token"] == "fixture-old-access"
    assert harness.store.submitted.organization_id == ORG
    assert harness.store.current.organization_id == NEXT_OWNER


@pytest.mark.asyncio
async def test_metadata_only_revocation_cannot_be_cleared_by_successful_mint(harness):
    async def revoke(_token):
        harness.storage.row["revoked_at"] = datetime.now(timezone.utc)
        assert harness.storage.row["token_version"] == 7
        return harness.tokens

    harness.refresh.side_effect = revoke
    with pytest.raises(ValueError, match="authority changed"):
        await _run(harness)
    assert harness.storage.row["revoked_at"] is not None
    assert harness.storage.grant["access_token"] == "fixture-old-access"
    assert len(harness.storage.writes) == 1 and not harness.storage.writes[0][1]


@pytest.mark.asyncio
async def test_postmint_type_change_without_version_bump_denies_persistence(harness):
    async def retype(_token):
        harness.storage.row["credential_type"] = "foreign_oauth"
        return harness.tokens

    harness.refresh.side_effect = retype
    with pytest.raises(ValueError, match="authority changed"):
        await _run(harness)
    assert len(harness.storage.writes) == 1 and not harness.storage.writes[0][1]
    assert harness.storage.grant["access_token"] == "fixture-old-access"


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_winner", [True, False])
async def test_failed_old_submission_never_revokes_reconnect_and_can_adopt_fresh_winner(harness, fresh_winner):
    async def failed(_token):
        harness.storage.grant = _grant(fresh=fresh_winner, access_token="fixture-reconnect-access",
                                       refresh_token="fixture-reconnect-refresh")
        harness.storage.row["token_version"] += 1
        raise ValueError("invalid_grant: fixture rejected")

    harness.refresh.side_effect = failed
    if fresh_winner:
        token, view = await _run(harness)
        assert token == view["access_token"] == "fixture-reconnect-access"
        assert harness.revoke_checks == []
        assert await harness.store.mark_revoked(harness.storage, "fixture-stale") == "UPDATE 0"
    else:
        with pytest.raises(oauth_refresh.OAuthRefreshError):
            await _run(harness)
        assert harness.storage.revoke_tags == ["UPDATE 0"]
    assert harness.storage.row["revoked_at"] is None and harness.storage.writes == []


@pytest.mark.asyncio
async def test_unchanged_failed_submission_can_conditionally_revoke_current_grant(harness):
    harness.refresh.side_effect = ValueError("invalid_grant: fixture rejected")
    with pytest.raises(oauth_refresh.OAuthRefreshError):
        await _run(harness)
    assert harness.storage.revoke_tags == ["UPDATE 1"]
    assert harness.storage.row["revoked_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reached_429", "reached_503", "malformed_rotation", "configuration"])
async def test_opted_in_failure_wording_does_not_invent_reachability_or_grant_validity(harness, failure):
    observations = []
    request = httpx.Request("POST", "https://oauth.example.test/token")

    async def failed(token):
        observations.append(token)
        if failure.startswith("reached_"):
            status = int(failure.rsplit("_", 1)[1])
            response = httpx.Response(status, request=request)
            raise httpx.HTTPStatusError("fixture-private-response-detail", request=request, response=response)
        if failure == "malformed_rotation":
            # The request reached a synthetic successful response and may have
            # consumed a rotating grant; no usable result can be persisted.
            response = httpx.Response(200, json={"refresh_token": "fixture-unsaved-successor"}, request=request)
            assert response.json()["refresh_token"] == "fixture-unsaved-successor"
            raise httpx.DecodingError("fixture-private-malformed-detail", request=request)
        raise RuntimeError("fixture-private-configuration-detail")

    harness.refresh.side_effect = failed
    with pytest.raises(oauth_refresh.OAuthRefreshError) as exc:
        await _run(harness)
    message = str(exc.value)
    assert "refresh could not complete" in message
    assert "validity is unverified" in message
    assert "Could not reach" not in message and "still valid" not in message
    assert "fixture-private" not in message and "unsaved-successor" not in message
    assert exc.value.__suppress_context__ is True
    assert observations == ["fixture-old-refresh"]
    assert harness.revoke_checks == [] and harness.storage.writes == []
    assert harness.storage.row["revoked_at"] is None
    audit = harness.audit.await_args.args[0]
    assert audit["phase_outcome"] == "network_error"
    assert exc.value.attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation_change", ["type", "owner", "access", "organization"])
async def test_failed_submission_revocation_is_bound_to_original_current_authority(harness, revocation_change):
    async def failed(_token):
        if revocation_change == "type":
            harness.storage.row["credential_type"] = "foreign_oauth"
        elif revocation_change == "owner":
            harness.storage.row["owner_id"] = NEXT_OWNER
        elif revocation_change == "access":
            harness.storage.access.clear()
        else:
            harness.storage.current_org = NEXT_OWNER
            harness.storage.access.add((USER, NEXT_OWNER))
        raise ValueError("invalid_grant: fixture rejected")

    harness.refresh.side_effect = failed
    with pytest.raises(ValueError):
        await _run(harness)
    assert harness.storage.revoke_tags == ["UPDATE 0"]
    assert harness.storage.row["revoked_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", ["permitted", "not_authorized", "owner_changed", "direct_runner"])
async def test_real_workflow_owner_fallback_preserves_resolved_principal_and_atomic_grant(harness, fallback):
    harness.store.workflow_id = WF
    if fallback != "direct_runner":
        harness.storage.access = {(OWNER, ORG)}
    if fallback == "not_authorized":
        harness.storage.workflow_authorized = False
    elif fallback == "owner_changed":
        harness.storage.workflow_owner = NEXT_OWNER
    if fallback in ("permitted", "direct_runner"):
        token, _view = await _run(harness)
        assert token == "fixture-minted-access"
        expected = USER if fallback == "direct_runner" else OWNER
        assert harness.store.submitted.principal_id == expected
        assert harness.storage.writes[0][0][1] == expected
    else:
        with pytest.raises(ValueError, match="access denied"):
            await _run(harness)
        harness.refresh.assert_not_awaited()
        assert harness.storage.writes == []


@pytest.mark.asyncio
async def test_workflow_grant_removed_during_mint_denies_atomic_fallback_write_and_revoke(harness):
    harness.store.workflow_id = WF
    harness.storage.access = {(OWNER, ORG)}
    async def remove(_token):
        harness.storage.workflow_authorized = False
        return harness.tokens

    harness.refresh.side_effect = remove
    with pytest.raises(ValueError, match="access denied"):
        await _run(harness)
    assert not harness.storage.writes[0][1]
    # A success is never a revoke candidate, even after fallback authorization loss.
    assert await harness.store.mark_revoked(harness.storage, "fixture") == "UPDATE 0"


@pytest.mark.asyncio
async def test_expired_workflow_fallback_reloads_current_rotation_without_minting(harness):
    harness.store.workflow_id = WF
    harness.storage.access = {(OWNER, ORG)}
    harness.storage.grant = _grant(fresh=True, access_token="fixture-current-owner-access")
    token, view = await _run(harness, _grant())
    assert token == view["access_token"] == "fixture-current-owner-access"
    assert harness.store.current.principal_id == OWNER
    harness.refresh.assert_not_awaited()
    assert harness.storage.writes == []


@pytest.mark.asyncio
async def test_manual_owner_mode_and_forwarded_provider_fields(harness):
    from wss.handlers.oauth.manual_refresh import manual_refresh_credential

    harness.store.require_owner = True
    with pytest.raises(ValueError, match="Only the current credential owner"):
        await manual_refresh_credential(harness.storage, user_id=USER, credential_id=CID,
                                        provider="fixture", refresh=harness.refresh, store=harness.store)
    harness.storage.row["owner_id"] = USER
    harness.tokens.region = "fixture-token-region"
    view = await manual_refresh_credential(harness.storage, user_id=USER, credential_id=CID,
                                          provider="fixture", refresh=harness.refresh,
                                          store=harness.store, additional_token_fields=("region",))
    assert view["region"] == harness.storage.grant["region"] == "fixture-token-region"


@pytest.mark.asyncio
@pytest.mark.parametrize("organization", [None, ORG])
async def test_explicit_organization_none_stays_distinct_from_current_context(harness, organization):
    harness.store.organization_id = organization
    await _run(harness)
    assert harness.store.current.organization_id == organization
    assert harness.store.current.current_organization is False
    assert not any(sql == PRIMARY_ORG_SQL for sql, _args in harness.storage.calls)


@pytest.mark.asyncio
async def test_pydantic_validator_error_is_sanitized(harness):
    class Shape(BaseModel):
        access_token: int

    harness.store.validate = lambda data: Shape.model_validate(data).model_dump()
    with pytest.raises(ValueError, match="grant shape or binding is invalid") as exc:
        await _run(harness)
    assert "fixture-old-access" not in str(exc.value)
    harness.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_reusable_refresh_without_new_token_preserves_submitted_refresh(harness):
    harness.tokens.refresh_token = None
    token, view = await _run(harness)
    assert token == "fixture-minted-access" and view["refresh_token"] == "fixture-old-refresh"
    assert harness.storage.grant["refresh_token"] == "fixture-old-refresh"


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [True, False])
async def test_optin_freshen_does_not_skip_authority_when_refresh_key_is_absent(harness, fresh):
    harness.storage.grant = _grant(fresh=fresh, refresh_token=None)
    data = deepcopy(harness.storage.grant)
    if fresh:
        result = await oauth_refresh.freshen_oauth_credential(
            data, user_id=USER, credential_id=CID, refresh=harness.refresh,
            store=harness.store, provider="fixture", caller_path="fixture",
        )
        assert result["token_version"] == 7 and harness.store.current.owner_id == OWNER
    else:
        with pytest.raises(ValueError, match="no refresh token"):
            await oauth_refresh.freshen_oauth_credential(
                data, user_id=USER, credential_id=CID, refresh=harness.refresh,
                store=harness.store, provider="fixture", caller_path="fixture",
            )
    harness.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_custom_token_keys_anchor_and_update_only_the_selected_chain(harness):
    harness.storage.grant.update(user_access_token="fixture-user-old", user_refresh_token="fixture-user-refresh",
                                 user_expires_at=_expiry())
    harness.store.validate = lambda data: dict(data)
    token, view = await _run(harness, access_token_key="user_access_token",
                            refresh_token_key="user_refresh_token", expires_at_key="user_expires_at")
    harness.refresh.assert_awaited_once_with("fixture-user-refresh")
    assert token == view["user_access_token"] == "fixture-minted-access"
    assert harness.storage.grant["access_token"] == "fixture-old-access"
    assert harness.storage.grant["refresh_token"] == "fixture-old-refresh"
