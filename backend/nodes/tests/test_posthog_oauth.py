"""Tests for the PostHog OAuth utility (PKCE exchange, rotating refresh, auth URL)."""

import pytest

from nodes.oauth import posthog_oauth
from nodes.oauth.posthog_oauth import (
    exchange_code_for_tokens, refresh_access_token, is_token_expired,
    get_posthog_auth_url, normalize_posthog_oauth_base_url,
    POSTHOG_DEFAULT_SCOPES,
)
from utils.ssrf import SSRFError


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._p = payload
        self.text = str(payload)

    def json(self):
        return self._p


class _Client:
    def __init__(self, responses):
        self._r = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, data=None, headers=None):
        self.calls.append(("POST", url, data))
        return self._r.pop(0)

    async def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        return self._r.pop(0)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("POSTHOG_CLIENT_ID", "https://noclick.com/.well-known/posthog-oauth-client.json")


@pytest.mark.asyncio
async def test_exchange_with_pkce(monkeypatch):
    token = _Resp(200, {"access_token": "pha_AT", "refresh_token": "phr_RT", "expires_in": 36000, "scope": "openid query:read"})
    userinfo = _Resp(200, {"sub": "u1", "email": "a@b.com", "posthog_base_url": "https://eu.posthog.com", "posthog_region": "eu"})
    client = _Client([token, userinfo])
    monkeypatch.setattr(posthog_oauth.httpx, "AsyncClient", lambda *a, **k: client)

    tokens, user = await exchange_code_for_tokens("code", "https://noclick.com/cb", "verifier123")
    assert tokens.access_token == "pha_AT"
    assert tokens.refresh_token == "phr_RT"
    assert user.email == "a@b.com"
    assert user.base_url == "https://eu.posthog.com"
    assert user.region == "eu"
    # verifier + client_id sent in the token POST body (public client, no secret)
    body = client.calls[0][2]
    assert body["code_verifier"] == "verifier123"
    assert body["client_id"] == "https://noclick.com/.well-known/posthog-oauth-client.json"
    assert "client_secret" not in body


@pytest.mark.asyncio
async def test_refresh_rotates(monkeypatch):
    client = _Client([_Resp(200, {"access_token": "pha_AT2", "refresh_token": "phr_RT2", "expires_in": 36000})])
    monkeypatch.setattr(posthog_oauth.httpx, "AsyncClient", lambda *a, **k: client)
    tokens = await refresh_access_token("phr_RT1")
    assert tokens.access_token == "pha_AT2"
    assert tokens.refresh_token == "phr_RT2"


@pytest.mark.asyncio
async def test_refresh_raises_without_rotation(monkeypatch):
    client = _Client([_Resp(200, {"access_token": "pha_AT2", "expires_in": 36000})])
    monkeypatch.setattr(posthog_oauth.httpx, "AsyncClient", lambda *a, **k: client)
    with pytest.raises(ValueError):
        await refresh_access_token("phr_RT1")


@pytest.mark.asyncio
async def test_refresh_error_raises(monkeypatch):
    client = _Client([_Resp(400, {"error": "invalid_grant", "error_description": "stale"})])
    monkeypatch.setattr(posthog_oauth.httpx, "AsyncClient", lambda *a, **k: client)
    with pytest.raises(ValueError, match="refresh failed"):
        await refresh_access_token("phr_RT1")


def test_is_token_expired():
    assert is_token_expired("2000-01-01T00:00:00+00:00") is True
    assert is_token_expired("2999-01-01T00:00:00+00:00") is False
    assert is_token_expired(None) is False


def test_auth_url_pkce(monkeypatch):
    url = get_posthog_auth_url(POSTHOG_DEFAULT_SCOPES, "state1", "https://noclick.com/cb", "challengeXYZ")
    assert url.startswith("https://oauth.posthog.com/oauth/authorize/?")
    assert "code_challenge=challengeXYZ" in url
    assert "code_challenge_method=S256" in url
    assert "response_type=code" in url
    assert "openid" in url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://us.posthog.com", "https://us.posthog.com"),
        ("https://eu.posthog.com/", "https://eu.posthog.com"),
    ],
)
def test_oauth_data_origin_is_canonical(value, expected):
    assert normalize_posthog_oauth_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://169.254.169.254",
        "https://posthog.attacker.example",
        "https://us.posthog.com.attacker.example",
        "https://us.posthog.com/api",
        "https://us.posthog.com:8443",
    ],
)
def test_oauth_data_origin_rejects_bearer_exfiltration(value):
    with pytest.raises(SSRFError):
        normalize_posthog_oauth_base_url(value)


@pytest.mark.asyncio
async def test_default_project_rejects_untrusted_origin_before_http(monkeypatch):
    from wss.handlers.oauth import posthog_oauth_handler

    monkeypatch.setattr(
        posthog_oauth_handler,
        "guarded_async_client",
        lambda **_kwargs: pytest.fail("HTTP client must not be constructed"),
    )
    with pytest.raises(SSRFError):
        await posthog_oauth_handler._resolve_default_project(
            "https://attacker.example", "secret-bearer"
        )
