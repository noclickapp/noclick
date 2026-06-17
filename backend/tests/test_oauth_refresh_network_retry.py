"""Refresh choke-point: bounded per-attempt timeout + transient-network retry.

2026-06-17 incident: a Google Sheets agent tool failed with
``OAuth token expired and refresh failed:`` (empty detail). The refresh token
was healthy — the access-token refresh HTTP call to Google's token endpoint
just timed out (6s then 16s) and succeeded in 81ms two hours later on the SAME
token. The old code (a) didn't retry the blip and (b) collapsed a network
timeout into a "token expired" message that mis-blamed a working credential.

These tests pin the fix:
- a transient transport failure is retried with backoff (bounded attempts);
- once exhausted it surfaces as a TRANSIENT error ("not a credential problem"),
  classified network_error / F08 in the audit;
- a provider HTTP rejection (4xx ValueError) is NOT retried and surfaces as a
  non-transient credential error;
- a refresh that hangs is bounded by the per-attempt timeout (asyncio.wait_for)
  and that timeout is itself a retryable transport failure.
"""

import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nodes.core import oauth_refresh
from nodes.core.oauth_refresh import OAuthRefreshError, ensure_fresh_oauth_token


def _expired():
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _fresh_tokens():
    """A provider token model (attribute access, like GoogleTokens)."""
    return SimpleNamespace(
        access_token="fresh-access",
        refresh_token="r1",  # Google is non-rotating — same token comes back
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        scope="a b",
        token_type="Bearer",
    )


def _choke_point_patches(audit_rows, stack, *, persist=(1, None), no_revoke=False):
    """Enter the standard choke-point test patches on *stack*; return nothing.

    Patches the row-of-record load + persist + audit sink so the in-lock refresh
    path runs without a real database, and zeroes the retry backoff so exhaustion
    tests don't actually sleep.
    """
    async def capture(row):
        audit_rows.append(row)

    cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _expired()}
    stack.enter_context(patch(
        "utils.credential_loader.load_credential",
        new=AsyncMock(return_value=dict(cred)),
    ))
    stack.enter_context(patch(
        "utils.credentials.update_credential_data_detailed",
        new=AsyncMock(return_value=persist),
    ))
    stack.enter_context(patch("nodes.core.oauth_refresh.record_refresh_event", new=capture))
    stack.enter_context(patch.object(oauth_refresh, "_REFRESH_RETRY_BACKOFF_S", (0.0, 0.0)))
    if no_revoke:
        stack.enter_context(patch.object(
            oauth_refresh, "_maybe_auto_revoke", new=AsyncMock(return_value=None)
        ))
    return cred


async def _refresh(cred, refresh_fn, *, credential_id):
    return await ensure_fresh_oauth_token(
        pool=object(),
        credential_id=credential_id,
        user_id="uid",
        credential=cred,
        provider="google",
        refresh=refresh_fn,
    )


async def test_transient_timeout_is_retried_then_succeeds():
    """One transient timeout, then success — the run never sees a failure, and
    the audit records that it took 2 attempts."""
    audit = []
    calls = {"n": 0}

    async def flaky(token):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError()
        return _fresh_tokens()

    with ExitStack() as stack:
        cred = _choke_point_patches(audit, stack)
        token = await _refresh(cred, flaky, credential_id="cid-retry-success")

    assert token == "fresh-access"
    assert calls["n"] == 2
    assert len(audit) == 1
    assert audit[0]["phase_outcome"] == "refreshed"
    assert audit[0]["metadata"].get("refresh_attempts") == 2


async def test_transient_failure_exhausted_raises_transient_error():
    """Every attempt times out — surfaces as a TRANSIENT error that explicitly
    does NOT blame the credential, classified network_error / F08."""
    audit = []
    calls = {"n": 0}

    async def always_timeout(token):
        calls["n"] += 1
        raise asyncio.TimeoutError()

    with ExitStack() as stack:
        cred = _choke_point_patches(audit, stack)
        with pytest.raises(OAuthRefreshError) as ei:
            await _refresh(cred, always_timeout, credential_id="cid-exhausted")

    err = ei.value
    assert err.transient is True
    assert err.network_failure_kind == "timeout"
    assert err.attempts == 3
    assert "transient network error" in str(err)
    # The whole point: a network blip must not read as a credential problem.
    assert "expired" not in str(err).lower()
    assert calls["n"] == 3  # 1 + 2 retries
    assert audit[0]["phase_outcome"] == "network_error"
    assert audit[0]["failure_mode_id"] == "F08"
    assert audit[0]["metadata"].get("refresh_attempts") == 3


async def test_provider_4xx_is_not_retried():
    """A provider HTTP rejection (ValueError) is deterministic — one attempt,
    surfaced as a non-transient credential error, classified provider_4xx / F01."""
    audit = []
    calls = {"n": 0}

    async def reject(token):
        calls["n"] += 1
        raise ValueError("invalid_grant: Token has been expired or revoked")

    with ExitStack() as stack:
        cred = _choke_point_patches(audit, stack, no_revoke=True)
        with pytest.raises(OAuthRefreshError) as ei:
            await _refresh(cred, reject, credential_id="cid-4xx")

    err = ei.value
    assert err.transient is False
    assert err.provider_error_code == "invalid_grant"
    assert "refresh failed" in str(err)  # keeps the grep-able phrasing
    assert "reconnected" in str(err)  # credential-level guidance
    assert calls["n"] == 1  # NOT retried
    assert audit[0]["phase_outcome"] == "provider_4xx"
    assert audit[0]["failure_mode_id"] == "F01"


async def test_hung_refresh_is_bounded_by_attempt_timeout():
    """A refresh that hangs longer than the per-attempt timeout is cancelled by
    asyncio.wait_for, treated as a retryable timeout, and the retry succeeds."""
    audit = []
    calls = {"n": 0}

    async def hang_then_ok(token):
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(5)  # far exceeds the patched per-attempt timeout
            return _fresh_tokens()
        return _fresh_tokens()

    with ExitStack() as stack:
        cred = _choke_point_patches(audit, stack)
        stack.enter_context(patch.object(oauth_refresh, "_REFRESH_ATTEMPT_TIMEOUT_S", 0.05))
        token = await _refresh(cred, hang_then_ok, credential_id="cid-hang")

    assert token == "fresh-access"
    assert calls["n"] == 2
    assert audit[0]["phase_outcome"] == "refreshed"
    assert audit[0]["metadata"].get("refresh_attempts") == 2
