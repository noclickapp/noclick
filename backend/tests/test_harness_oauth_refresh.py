"""Server-side refresh for harness subscription-OAuth credentials.

Subscription credential blobs were once minted and injected into sandboxes as-is —
no backend path ever refreshed them, and both adapters fabricated freshness at
sandbox launch (expiresAt = launch + expires_in), so a days-old token was
presented to the CLI as fresh. ``ensure_fresh_harness_tokens`` makes the
credential row the chain of record: it refreshes at env-build time in
AgentNode.execute() through the shared oauth_refresh choke point.

These tests pin:
- fresh tokens are a no-op (no HTTP, no persist);
- stale tokens refresh against the provider and CAS-persist the nested
  ``{"credentials": {...}}`` blob shape;
- legacy blobs without ``*_EXPIRES_AT`` force-refresh once (the upgrade path);
- provider rejections surface as non-transient OAuthRefreshError;
- codex id_token rotation rides along into the persisted blob;
- bookkeeping keys never leak into the sandbox env;
- ``oauth_expires_ms`` prefers the absolute expiry over launch-time fabrication.
"""

import json
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nodes.agent import harness_oauth
from nodes.agent.harness_oauth import (
    compute_expires_at_iso,
    ensure_fresh_harness_tokens,
    oauth_expires_ms,
)
from nodes.core.oauth_refresh import OAuthRefreshError


def _iso(delta_hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).isoformat()


def _claude_env(**over):
    env = {
        "CLAUDE_CODE_ACCESS_TOKEN": "stale-access",
        "CLAUDE_CODE_REFRESH_TOKEN": "refresh-1",
        "CLAUDE_CODE_EXPIRES_AT": _iso(-1),
    }
    env.update(over)
    return env


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient inside harness_oauth."""

    responses: list = []
    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        _FakeAsyncClient.calls.append((url, kwargs))
        return _FakeAsyncClient.responses.pop(0)


def _patches(stack, *, db_blob, responses, persist=(1, None)):
    """Standard seams: DB row-of-record load/persist, audit sink, HTTP."""
    _FakeAsyncClient.responses = list(responses)
    _FakeAsyncClient.calls = []
    persist_calls = []

    async def _persist(**kwargs):
        persist_calls.append(kwargs)
        return persist

    stack.enter_context(patch(
        "utils.credential_loader.load_credential",
        new=AsyncMock(return_value=dict(db_blob) if db_blob is not None else None),
    ))
    stack.enter_context(patch(
        "utils.credentials.update_credential_data_detailed", new=_persist,
    ))
    stack.enter_context(patch(
        "nodes.core.oauth_refresh.record_refresh_event",
        new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch.object(harness_oauth.httpx, "AsyncClient", _FakeAsyncClient))
    return persist_calls


async def test_fresh_token_is_noop():
    env = _claude_env(CLAUDE_CODE_EXPIRES_AT=_iso(+4))
    with ExitStack() as stack:
        persist_calls = _patches(stack, db_blob=None, responses=[])
        out = await ensure_fresh_harness_tokens(
            dict(env), user_id="uid", credential_id="cid-fresh"
        )
    assert out["CLAUDE_CODE_ACCESS_TOKEN"] == "stale-access"
    assert not _FakeAsyncClient.calls
    assert not persist_calls


async def test_stale_token_refreshes_and_persists_nested_blob():
    env = _claude_env()
    db_blob = {"credentials": dict(env), "token_version": 7}
    with ExitStack() as stack:
        persist_calls = _patches(
            stack,
            db_blob=db_blob,
            responses=[_FakeResponse({
                "access_token": "fresh-access",
                "refresh_token": "refresh-2",
                "expires_in": 28800,
            })],
        )
        out = await ensure_fresh_harness_tokens(
            env, user_id="uid", credential_id="cid-stale"
        )

    url, kwargs = _FakeAsyncClient.calls[0]
    assert url == harness_oauth.CLAUDE_CODE_TOKEN_URL
    assert kwargs["json"]["grant_type"] == "refresh_token"

    assert out["CLAUDE_CODE_ACCESS_TOKEN"] == "fresh-access"
    assert out["CLAUDE_CODE_REFRESH_TOKEN"] == "refresh-2"
    assert out["CLAUDE_CODE_EXPIRES_AT"] > _iso(+7)

    (persisted,) = persist_calls
    blob = persisted["new_data"]
    assert set(blob) == {"credentials"}, "must persist the nested blob shape"
    assert blob["credentials"]["CLAUDE_CODE_ACCESS_TOKEN"] == "fresh-access"
    assert blob["credentials"]["CLAUDE_CODE_REFRESH_TOKEN"] == "refresh-2"
    assert "token_version" not in blob["credentials"]
    assert persisted["expected_token_version"] == 7, "CAS guard from the re-read row"


async def test_legacy_blob_without_expires_at_forces_refresh():
    """Pre-EXPIRES_AT credentials must upgrade on first use, not sit stale."""
    env = _claude_env()
    del env["CLAUDE_CODE_EXPIRES_AT"]
    db_blob = {"credentials": dict(env), "token_version": 1}
    with ExitStack() as stack:
        persist_calls = _patches(
            stack,
            db_blob=db_blob,
            responses=[_FakeResponse({
                "access_token": "fresh-access", "expires_in": 28800,
            })],
        )
        out = await ensure_fresh_harness_tokens(
            env, user_id="uid", credential_id="cid-legacy"
        )
    assert out["CLAUDE_CODE_ACCESS_TOKEN"] == "fresh-access"
    assert out["CLAUDE_CODE_EXPIRES_AT"]
    # Non-rotating response keeps the submitted refresh token.
    assert persist_calls[0]["new_data"]["credentials"]["CLAUDE_CODE_REFRESH_TOKEN"] == "refresh-1"


async def test_provider_rejection_raises_non_transient_reconnect_error():
    env = _claude_env()
    db_blob = {"credentials": dict(env), "token_version": 3}
    with ExitStack() as stack:
        _patches(
            stack,
            db_blob=db_blob,
            responses=[
                _FakeResponse({"error": "invalid_grant"}, status_code=400),
            ],
        )
        stack.enter_context(patch(
            "nodes.core.oauth_refresh._maybe_auto_revoke",
            new=AsyncMock(return_value=None),
        ))
        with pytest.raises(OAuthRefreshError) as exc_info:
            await ensure_fresh_harness_tokens(
                env, user_id="uid", credential_id="cid-reject"
            )
    assert not exc_info.value.transient
    assert exc_info.value.provider_error_code == "invalid_grant"


async def test_api_key_credential_is_untouched():
    env = {"ANTHROPIC_API_KEY": "sk-ant-xyz"}
    with ExitStack() as stack:
        _patches(stack, db_blob=None, responses=[])
        out = await ensure_fresh_harness_tokens(
            dict(env), user_id="uid", credential_id="cid-key"
        )
    assert out == env
    assert not _FakeAsyncClient.calls


async def test_codex_id_token_rides_along_into_persisted_blob():
    env = {
        "CODEX_ACCESS_TOKEN": "stale-access",
        "CODEX_REFRESH_TOKEN": "refresh-1",
        "CODEX_ID_TOKEN": "old-id-token",
        "CODEX_EXPIRES_AT": _iso(-1),
    }
    db_blob = {"credentials": dict(env), "token_version": 2}
    with ExitStack() as stack:
        persist_calls = _patches(
            stack,
            db_blob=db_blob,
            responses=[_FakeResponse({
                "access_token": "fresh-access",
                "refresh_token": "refresh-2",
                "id_token": "new-id-token",
                "expires_in": 864000,
            })],
        )
        out = await ensure_fresh_harness_tokens(
            env, user_id="uid", credential_id="cid-codex"
        )

    url, kwargs = _FakeAsyncClient.calls[0]
    assert url == harness_oauth.CODEX_TOKEN_URL
    assert kwargs["data"]["client_id"] == harness_oauth.CODEX_CLIENT_ID

    assert out["CODEX_ID_TOKEN"] == "new-id-token"
    blob = persist_calls[0]["new_data"]["credentials"]
    assert blob["CODEX_ID_TOKEN"] == "new-id-token"
    assert blob["CODEX_REFRESH_TOKEN"] == "refresh-2"


async def test_bookkeeping_keys_never_leak_into_sandbox_env():
    env = _claude_env()
    db_blob = {"credentials": dict(env), "token_version": 9}
    with ExitStack() as stack:
        _patches(
            stack,
            db_blob=db_blob,
            responses=[_FakeResponse({
                "access_token": "fresh-access", "expires_in": 28800,
            })],
        )
        out = await ensure_fresh_harness_tokens(
            env, user_id="uid", credential_id="cid-clean"
        )
    assert "token_version" not in out
    assert "updated_at" not in out
    assert "scope" not in out and "token_type" not in out


def test_oauth_expires_ms_prefers_absolute_expiry():
    at = datetime.now(timezone.utc) + timedelta(hours=2)
    env = {
        "CLAUDE_CODE_EXPIRES_AT": at.isoformat(),
        "CLAUDE_CODE_EXPIRES_IN": "60",
    }
    ms = oauth_expires_ms(env, "CLAUDE_CODE_EXPIRES_AT", "CLAUDE_CODE_EXPIRES_IN")
    assert abs(ms - int(at.timestamp() * 1000)) < 1000


def test_oauth_expires_ms_falls_back_to_launch_relative_then_zero():
    env = {"CLAUDE_CODE_EXPIRES_IN": "3600"}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ms = oauth_expires_ms(env, "CLAUDE_CODE_EXPIRES_AT", "CLAUDE_CODE_EXPIRES_IN")
    assert now_ms + 3_500_000 < ms < now_ms + 3_700_000

    assert oauth_expires_ms({}, "CLAUDE_CODE_EXPIRES_AT", "CLAUDE_CODE_EXPIRES_IN") == 0
    assert oauth_expires_ms(
        {}, "CLAUDE_CODE_EXPIRES_AT", "CLAUDE_CODE_EXPIRES_IN", default_expires_in=100
    ) > now_ms


def test_compute_expires_at_iso_from_expires_in_and_jwt():
    iso = compute_expires_at_iso(3600)
    parsed = datetime.fromisoformat(iso)
    assert timedelta(minutes=59) < parsed - datetime.now(timezone.utc) < timedelta(minutes=61)

    # JWT exp fallback (ChatGPT-style token) when expires_in is absent.
    import base64
    exp = int((datetime.now(timezone.utc) + timedelta(days=10)).timestamp())
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=")
    jwt = b"h." + payload + b".s"
    iso = compute_expires_at_iso(None, jwt.decode())
    assert datetime.fromisoformat(iso) == datetime.fromtimestamp(exp, tz=timezone.utc)

    assert compute_expires_at_iso(None, "not-a-jwt") is None
