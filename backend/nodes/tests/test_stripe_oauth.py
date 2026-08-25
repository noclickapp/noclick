"""
Tests for the Stripe Connect OAuth mechanism (offline; mocks the Stripe OAuth
token endpoint). Covers the auth-URL builder, code exchange, token refresh,
non-expiry behavior, and the node's OAuth-credential execution path.

Run: pytest nodes/tests/test_stripe_oauth.py
"""

import pytest

import nodes.oauth.stripe_oauth as so
from nodes.oauth.stripe_oauth import (
    STRIPE_AUTH_URL,
    STRIPE_TOKEN_URL,
    exchange_code_for_tokens,
    get_stripe_auth_url,
    is_token_expired,
    refresh_access_token,
)
from nodes.stripe_node import StripeNode, StripeNodeConfig, StripeOAuthCredential


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("STRIPE_CONNECT_CLIENT_ID", "ca_test_123")
    monkeypatch.setenv("STRIPE_CONNECT_CLIENT_SECRET", "sk_test_platform")


class FakeResp:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.content = b"{}"

    def json(self):
        return self._data


class FakeClient:
    posted = []
    response = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None, headers=None):
        FakeClient.posted.append({"url": url, "data": data})
        return FakeClient.response


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    FakeClient.posted = []
    FakeClient.response = None
    monkeypatch.setattr(so.httpx, "AsyncClient", FakeClient)


# --------------------------------------------------------------------------- #
# Auth URL
# --------------------------------------------------------------------------- #


def test_auth_url_is_well_formed():
    url = get_stripe_auth_url(["read_write"], state="xyz", redirect_uri="https://app.example.com/cb")
    assert url.startswith(STRIPE_AUTH_URL + "?")
    assert "response_type=code" in url
    assert "client_id=ca_test_123" in url
    assert "scope=read_write" in url
    assert "state=xyz" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcb" in url  # urlencoded


# --------------------------------------------------------------------------- #
# Code exchange
# --------------------------------------------------------------------------- #


async def test_exchange_code_parses_connect_response():
    FakeClient.response = FakeResp(200, {
        "access_token": "sk_live_connected",
        "refresh_token": "rt_1",
        "scope": "read_write",
        "livemode": True,
        "token_type": "bearer",
        "stripe_user_id": "acct_CONNECTED",
        "stripe_publishable_key": "pk_live_X",
    })
    tokens, info = await exchange_code_for_tokens(code="ac_123", redirect_uri="https://app/cb")

    assert tokens.access_token == "sk_live_connected"
    assert tokens.refresh_token == "rt_1"
    assert tokens.stripe_user_id == "acct_CONNECTED"
    assert tokens.stripe_publishable_key == "pk_live_X"
    assert tokens.livemode is True
    assert tokens.expires_at is None  # Connect tokens don't expire
    assert info.id == "acct_CONNECTED"

    sent = FakeClient.posted[-1]
    assert sent["url"] == STRIPE_TOKEN_URL
    assert sent["data"]["grant_type"] == "authorization_code"
    assert sent["data"]["code"] == "ac_123"
    # token exchange authenticates with the platform secret key as client_secret
    assert sent["data"]["client_secret"] == "sk_test_platform"


async def test_exchange_code_error_raises():
    FakeClient.response = FakeResp(400, {"error": "invalid_grant", "error_description": "authorization code expired"})
    with pytest.raises(ValueError, match="authorization code expired"):
        await exchange_code_for_tokens(code="bad", redirect_uri="https://app/cb")


# --------------------------------------------------------------------------- #
# Refresh + expiry
# --------------------------------------------------------------------------- #


async def test_refresh_access_token():
    FakeClient.response = FakeResp(200, {
        "access_token": "sk_live_new", "scope": "read_write", "token_type": "bearer",
        "stripe_user_id": "acct_CONNECTED",
    })
    tokens = await refresh_access_token("rt_1")
    assert tokens.access_token == "sk_live_new"
    assert tokens.refresh_token == "rt_1"  # falls back to the provided token when not re-sent

    sent = FakeClient.posted[-1]
    assert sent["data"]["grant_type"] == "refresh_token"
    assert sent["data"]["refresh_token"] == "rt_1"
    assert sent["data"]["client_secret"] == "sk_test_platform"


async def test_refresh_error_raises():
    FakeClient.response = FakeResp(401, {"error": "invalid_grant"})
    with pytest.raises(ValueError):
        await refresh_access_token("rt_bad")


def test_connect_tokens_never_expire():
    # Connect access tokens do not expire — is_token_expired is always False.
    assert is_token_expired(None) is False
    assert is_token_expired("2000-01-01T00:00:00+00:00") is False


# --------------------------------------------------------------------------- #
# Node-side OAuth credential execution path
# --------------------------------------------------------------------------- #


def _oauth_node(op_dict):
    cred = {"credential_type": "stripe_oauth", "access_token": "sk_oauth_tok", "stripe_user_id": "acct_X"}
    nc = StripeNodeConfig.model_validate({"config": op_dict, "credentials": cred})
    return StripeNode(
        node_id="t", node_type="automation-stripe", node_data={}, config=nc,
        sio=None, sid=None, workflow_id="w",
    )


def test_oauth_credential_parses_and_supplies_bearer_token():
    node = _oauth_node({"operation": "retrieve_balance"})
    assert isinstance(node.config.credentials, StripeOAuthCredential)
    assert node._token(node.config.credentials) == "sk_oauth_tok"
    # OAuth token is already scoped to the connected account → no Stripe-Account header
    assert node._stripe_account(node.config.credentials) is None


async def test_ensure_fresh_token_returns_oauth_token():
    node = _oauth_node({"operation": "retrieve_balance"})
    token = await node._ensure_fresh_token(node.config.credentials)
    assert token == "sk_oauth_tok"


async def test_freshen_credential_is_noop():
    data = {"access_token": "x", "stripe_user_id": "acct_X"}
    result = await StripeNode.freshen_credential(dict(data))
    assert result == data


def test_oauth_credential_is_visible_and_supported():
    """OAuth ("Connect with Stripe") is surfaced in the credentials UI — not
    hidden — and the credential parses + executes at runtime."""
    schema = StripeNode.get_config_schema()
    defs = schema["$defs"]
    assert "x-credential-hidden" not in defs["StripeOAuthCredential"]  # visible
    assert defs["StripeOAuthCredential"].get("x-credential-type") == "oauth"
    assert defs["StripeOAuthCredential"].get("x-oauth-provider") == "stripe"
    node = _oauth_node({"operation": "retrieve_balance"})
    assert isinstance(node.config.credentials, StripeOAuthCredential)
