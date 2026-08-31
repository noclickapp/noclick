"""Unit tests for the shared agent OAuth flow module (nodes/agent/harness_oauth_flows).

Mocks the shipped provider HTTP endpoints (respx) so the device-code / PKCE mechanics and
the minted credential_data blobs are pinned — these are the single source of truth
for both the socket handlers and the public credential-provide endpoints.
"""

import httpx
import pytest

# respx is a test-only dep (declared in the backend-tests workflow). importorskip so a
# missing optional dep skips THIS module instead of aborting collection of the whole suite.
respx = pytest.importorskip("respx")

from nodes.agent import harness_oauth_flows as flows
from nodes.agent.harness_oauth_flows import (
    codex_start, codex_complete,
    claude_code_start, claude_code_complete,
    OAuthFlowError, CODEX_ISSUER,
)


class _FakeRedis:
    """Minimal async Redis stand-in for the PKCE verifier stash."""
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.mark.asyncio
class TestCodexFlow:
    @respx.mock
    async def test_start_returns_display_and_poll(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode").mock(
            return_value=httpx.Response(200, json={
                "user_code": "ABCD-1234", "device_auth_id": "dev-123", "interval": 7,
            })
        )
        result = await codex_start()
        assert result["display"]["user_code"] == "ABCD-1234"
        assert result["display"]["verification_url"] == f"{CODEX_ISSUER}/codex/device"
        assert result["display"]["interval"] == 7
        assert result["poll"] == {"device_auth_id": "dev-123", "user_code": "ABCD-1234"}

    @respx.mock
    async def test_complete_pending_on_403(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(
            return_value=httpx.Response(403, json={})
        )
        result = await codex_complete({"device_auth_id": "d", "user_code": "c"})
        assert result == {"status": "pending"}

    @respx.mock
    async def test_complete_mints_credential(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(
            return_value=httpx.Response(200, json={"authorization_code": "authz", "code_verifier": "ver"})
        )
        respx.post(f"{CODEX_ISSUER}/oauth/token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "acc", "refresh_token": "ref", "id_token": "idt", "expires_in": 3600,
            })
        )
        result = await codex_complete({"device_auth_id": "d", "user_code": "c"})
        assert result["status"] == "completed"
        creds = result["credential_data"]["credentials"]
        assert creds["CODEX_ACCESS_TOKEN"] == "acc"
        assert creds["CODEX_REFRESH_TOKEN"] == "ref"
        assert creds["CODEX_ID_TOKEN"] == "idt"

    @respx.mock
    async def test_complete_raises_without_access_token(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(
            return_value=httpx.Response(200, json={"authorization_code": "authz", "code_verifier": "ver"})
        )
        respx.post(f"{CODEX_ISSUER}/oauth/token").mock(
            return_value=httpx.Response(200, json={"refresh_token": "ref"})
        )
        with pytest.raises(OAuthFlowError):
            await codex_complete({"device_auth_id": "d", "user_code": "c"})






@pytest.mark.asyncio
class TestClaudeCodePkceFlow:
    @respx.mock
    async def test_start_stashes_verifier_and_complete_exchanges(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(flows, "_redis_client", fake)

        start = await claude_code_start()
        session_id = start["poll"]["auth_session_id"]
        assert "code_challenge=" in start["display"]["authorize_url"]
        assert f"claude_code_pkce:{session_id}" in fake.store  # verifier stashed

        from nodes.agent.harness_oauth import CLAUDE_CODE_TOKEN_URL
        respx.post(CLAUDE_CODE_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={
                "access_token": "cacc", "refresh_token": "cref", "expires_in": 3600,
            })
        )
        done = await claude_code_complete({"auth_session_id": session_id, "code": "the-code#the-state"})
        assert done["status"] == "completed"
        creds = done["credential_data"]["credentials"]
        assert creds["CLAUDE_CODE_ACCESS_TOKEN"] == "cacc"
        assert creds["CLAUDE_CODE_REFRESH_TOKEN"] == "cref"
        # verifier is one-time — deleted after exchange
        assert f"claude_code_pkce:{session_id}" not in fake.store

    async def test_complete_with_expired_session_raises(self, monkeypatch):
        monkeypatch.setattr(flows, "_redis_client", _FakeRedis())
        with pytest.raises(OAuthFlowError):
            await claude_code_complete({"auth_session_id": "missing", "code": "x#y"})


def _id_token(plan):
    import base64, json
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return b64({"alg": "RS256"}) + "." + b64({"https://api.openai.com/auth": {"chatgpt_account_id": "acct", "chatgpt_plan_type": plan}}) + ".sig"


class TestCodexPlanEligibility:
    """Codex is not part of ChatGPT Free: the service later tells codex to use
    an API key, and with none connected the turn dies with a bare 401. Refuse
    the sign-in with the reason instead."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_free_plan_sign_in_is_refused_with_the_reason(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(
            return_value=httpx.Response(200, json={"authorization_code": "ac", "code_verifier": "cv"}))
        respx.post(f"{CODEX_ISSUER}/oauth/token").mock(return_value=httpx.Response(200, json={
            "access_token": "acc", "refresh_token": "ref", "id_token": _id_token("free"), "expires_in": 3600,
        }))
        with pytest.raises(OAuthFlowError, match="Free plan, which doesn't include Codex"):
            await codex_complete({"device_auth_id": "d", "user_code": "c"})

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_paid_plan_sign_in_completes(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(
            return_value=httpx.Response(200, json={"authorization_code": "ac", "code_verifier": "cv"}))
        respx.post(f"{CODEX_ISSUER}/oauth/token").mock(return_value=httpx.Response(200, json={
            "access_token": "acc", "refresh_token": "ref", "id_token": _id_token("plus"), "expires_in": 3600,
        }))
        result = await codex_complete({"device_auth_id": "d", "user_code": "c"})
        assert result["status"] == "completed"
        assert result["credential_data"]["credentials"]["CODEX_ID_TOKEN"] == _id_token("plus")



def _minted_id_token(plan):
    import base64, json
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": "acct", "chatgpt_plan_type": plan}}
    return b64({"alg": "RS256"}) + "." + b64(claims) + ".sig"


@pytest.mark.asyncio
class TestCodexIdTokenRepair:
    """Codex picks the ChatGPT backend from the id token's claims; a sign-in
    stored without one strands the CLI in API-key mode (a Pro user was told
    their account was Free, 2026-08-31). The device-auth exchange doesn't
    always mint one — the refresh grant requests ``openid`` and does."""

    @respx.mock
    async def test_an_exchange_without_an_id_token_mints_one_via_the_refresh_grant(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(
            return_value=httpx.Response(200, json={"authorization_code": "ac", "code_verifier": "cv"}))
        token_route = respx.post(f"{CODEX_ISSUER}/oauth/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}),
            httpx.Response(200, json={
                "access_token": "acc2", "refresh_token": "ref2",
                "id_token": _minted_id_token("pro"), "expires_in": 3600,
            }),
        ])
        result = await codex_complete({"device_auth_id": "d", "user_code": "c"})
        assert result["status"] == "completed"
        creds = result["credential_data"]["credentials"]
        assert creds["CODEX_ID_TOKEN"] == _minted_id_token("pro")
        # The repair's rotated tokens win — the originals are consumed.
        assert creds["CODEX_ACCESS_TOKEN"] == "acc2"
        assert creds["CODEX_REFRESH_TOKEN"] == "ref2"
        repair_call = token_route.calls[1]
        assert b"scope=openid+profile+email" in repair_call.request.content

    @respx.mock
    async def test_a_sign_in_that_cannot_mint_an_id_token_is_refused(self):
        respx.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token").mock(
            return_value=httpx.Response(200, json={"authorization_code": "ac", "code_verifier": "cv"}))
        respx.post(f"{CODEX_ISSUER}/oauth/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "acc", "refresh_token": "ref"}),
            httpx.Response(200, json={"access_token": "acc2"}),
        ])
        with pytest.raises(OAuthFlowError, match="identity token"):
            await codex_complete({"device_auth_id": "d", "user_code": "c"})
