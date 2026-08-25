"""Tests for the Calendly OAuth utility (exchange, rotating refresh, auth URL)."""

import httpx
import pytest

from nodes.oauth import calendly_oauth
from nodes.oauth.calendly_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
    get_calendly_auth_url,
    CALENDLY_DEFAULT_SCOPES,
)


class _MockResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _MockClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, data=None, headers=None):
        self.calls.append(("POST", url, data))
        return self._responses.pop(0)

    async def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CALENDLY_CLIENT_ID", "cid")
    monkeypatch.setenv("CALENDLY_CLIENT_SECRET", "csecret")


@pytest.mark.asyncio
async def test_exchange_code_for_tokens(monkeypatch):
    token_resp = _MockResponse(200, {
        "access_token": "AT", "refresh_token": "RT", "expires_in": 7200,
        "token_type": "Bearer", "owner": "https://api.calendly.com/users/U1",
        "organization": "https://api.calendly.com/organizations/O1",
    })
    me_resp = _MockResponse(200, {"resource": {
        "uri": "https://api.calendly.com/users/U1", "name": "Ada", "email": "ada@x.com",
        "current_organization": "https://api.calendly.com/organizations/O1"}})
    client = _MockClient([token_resp, me_resp])
    monkeypatch.setattr(calendly_oauth.httpx, "AsyncClient", lambda *a, **k: client)

    tokens, user = await exchange_code_for_tokens("code", "https://noclick.com/cb")
    assert tokens.access_token == "AT"
    assert tokens.refresh_token == "RT"
    assert tokens.owner == "https://api.calendly.com/users/U1"
    assert tokens.organization == "https://api.calendly.com/organizations/O1"
    assert user.name == "Ada"
    assert user.email == "ada@x.com"


@pytest.mark.asyncio
async def test_refresh_rotates_and_requires_new_token(monkeypatch):
    resp = _MockResponse(200, {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 7200})
    client = _MockClient([resp])
    monkeypatch.setattr(calendly_oauth.httpx, "AsyncClient", lambda *a, **k: client)

    tokens = await refresh_access_token("RT1")
    assert tokens.access_token == "AT2"
    assert tokens.refresh_token == "RT2"  # rotated


@pytest.mark.asyncio
async def test_refresh_raises_when_rotation_missing(monkeypatch):
    # Single-use rotation: a refresh response WITHOUT a new refresh_token must raise
    # (require_rotated_refresh_token), never silently reuse the consumed token.
    resp = _MockResponse(200, {"access_token": "AT2", "expires_in": 7200})
    client = _MockClient([resp])
    monkeypatch.setattr(calendly_oauth.httpx, "AsyncClient", lambda *a, **k: client)

    with pytest.raises(ValueError):
        await refresh_access_token("RT1")


@pytest.mark.asyncio
async def test_refresh_error_response_raises(monkeypatch):
    resp = _MockResponse(400, {"error": "invalid_grant", "error_description": "expired"})
    client = _MockClient([resp])
    monkeypatch.setattr(calendly_oauth.httpx, "AsyncClient", lambda *a, **k: client)
    with pytest.raises(ValueError, match="refresh failed"):
        await refresh_access_token("RT1")


def test_is_token_expired():
    assert is_token_expired("2000-01-01T00:00:00+00:00") is True
    assert is_token_expired("2999-01-01T00:00:00+00:00") is False
    assert is_token_expired(None) is False  # no expiry → not expired


def test_auth_url_omits_scope_by_default():
    url = get_calendly_auth_url(CALENDLY_DEFAULT_SCOPES, "state1", "https://noclick.com/cb", client_id="cid")
    assert url.startswith("https://auth.calendly.com/oauth/authorize?")
    assert "scope=" not in url
    assert "client_id=cid" in url
    assert "response_type=code" in url
    assert "state=state1" in url


def test_auth_url_includes_scope_when_supplied():
    url = get_calendly_auth_url(["default"], "state1", "https://noclick.com/cb", client_id="cid")
    assert "scope=default" in url
