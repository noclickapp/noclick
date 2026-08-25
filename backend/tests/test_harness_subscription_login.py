"""Signing in with a Claude or ChatGPT subscription, on a self-hosted install.

Two things are specific to this edition and neither is covered by the flow and
refresh tests next door:

* Redis is optional here, and the PKCE verifier — written by `start`, read by
  `complete` minutes later, never sent to the browser — has to survive without
  it.
* The CLIs authenticate from a file in their config directory, not from an
  environment variable. A token that never becomes a file leaves the CLI
  reporting itself logged out and the turn comes back blank, which is exactly
  what the sign-in was for.
"""

import json
import pathlib

import pytest

from nodes.agent import harness_oauth_flows as flows
from nodes.agent.config.providers import (
    agent_credential_requirement,
    agent_credential_types,
    validate_provider_credentials,
)
from nodes.agent.local_harness import _apply_subscription_login


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """No Redis, which is the default install."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(flows, "_redis_client", None)
    monkeypatch.setattr(flows, "_local_pkce", {})


@pytest.mark.asyncio
async def test_pkce_verifier_survives_without_redis():
    await flows._pkce_put("session-1", "verifier-1")
    assert await flows._pkce_take("session-1") == "verifier-1"


@pytest.mark.asyncio
async def test_pkce_verifier_is_single_use():
    """A verifier that has been exchanged must not be exchangeable again."""
    await flows._pkce_put("session-2", "verifier-2")
    assert await flows._pkce_take("session-2") == "verifier-2"
    assert await flows._pkce_take("session-2") is None


@pytest.mark.asyncio
async def test_expired_verifier_is_gone():
    import time

    flows._local_pkce["session-3"] = ("verifier-3", time.time() - 1)
    assert await flows._pkce_take("session-3") is None


@pytest.mark.asyncio
async def test_claude_sign_in_round_trips_without_redis(monkeypatch):
    """The authorize URL and the exchange are one flow: the code challenge the
    provider saw must still verify when the pasted code comes back."""
    respx = pytest.importorskip("respx")
    import httpx

    from nodes.agent.harness_oauth import CLAUDE_CODE_TOKEN_URL

    start = await flows.claude_code_start()
    session_id = start["poll"]["auth_session_id"]
    assert "code_challenge=" in start["display"]["authorize_url"]

    with respx.mock:
        route = respx.post(CLAUDE_CODE_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={
                "access_token": "acc", "refresh_token": "ref", "expires_in": 28800,
            })
        )
        done = await flows.claude_code_complete(
            {"auth_session_id": session_id, "code": "the-code#the-state"}
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent["code_verifier"], "the stashed verifier must reach the token endpoint"
    assert done["credential_data"]["credentials"]["CLAUDE_CODE_ACCESS_TOKEN"] == "acc"


def test_claude_token_becomes_the_file_the_cli_reads(tmp_path: pathlib.Path):
    env = {
        "CLAUDE_CODE_ACCESS_TOKEN": "acc",
        "CLAUDE_CODE_REFRESH_TOKEN": "ref",
        "CLAUDE_CODE_EXPIRES_AT": "2030-01-01T00:00:00+00:00",
    }
    _apply_subscription_login("claude_code", tmp_path, env)

    creds = pathlib.Path(env["CLAUDE_CONFIG_DIR"]) / ".credentials.json"
    payload = json.loads(creds.read_text())["claudeAiOauth"]
    assert payload["accessToken"] == "acc"
    assert payload["refreshToken"] == "ref"
    # The real expiry, not one fabricated at launch: a fabricated one tells the
    # CLI a stale token is fresh and suppresses its own refresh.
    assert payload["expiresAt"] == 1893456000000
    assert creds.stat().st_mode & 0o777 == 0o600, "a token file must not be world-readable"


def test_chatgpt_token_becomes_the_file_the_cli_reads(tmp_path: pathlib.Path):
    env = {"CODEX_ACCESS_TOKEN": "acc", "CODEX_ID_TOKEN": "idt", "CODEX_REFRESH_TOKEN": "ref"}
    _apply_subscription_login("codex", tmp_path, env)

    auth = pathlib.Path(env["CODEX_HOME"]) / "auth.json"
    payload = json.loads(auth.read_text())
    assert payload["tokens"] == {"id_token": "idt", "access_token": "acc", "refresh_token": "ref"}
    assert payload["OPENAI_API_KEY"] is None
    assert auth.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("model_type", ["claude_code", "codex"])
def test_no_sign_in_leaves_the_operators_own_cli_login_alone(model_type, tmp_path):
    """Running the CLI you are already signed into on this machine is the point
    of running it locally; an unattached node must not redirect its config."""
    env: dict = {}
    _apply_subscription_login(model_type, tmp_path, env)
    assert env == {}
    assert not list(tmp_path.iterdir())


def test_subscription_credential_is_an_accepted_agent_credential():
    """A sign-in is a credential the node can be attached to — otherwise the
    picker refuses the row the sign-in just created."""
    types = agent_credential_types()
    assert {"agent_codex_oauth", "agent_claude_code_oauth"} <= types

    claude = agent_credential_requirement({"model_type": "claude_code"})
    assert "agent_claude_code_oauth" in claude.accepted_types
    codex = agent_credential_requirement({"model_type": "codex"})
    assert "agent_codex_oauth" in codex.accepted_types


def test_a_subscription_is_not_accepted_for_the_direct_api_path():
    """The token authenticates the CLI, not the provider's HTTP API: an agent
    calling the API directly needs a real API key, and offering the sign-in
    there would attach a credential that cannot work."""
    direct = agent_credential_requirement({"model": "anthropic/claude-sonnet-4.5"})
    assert "agent_claude_code_oauth" not in direct.accepted_types


def test_subscription_token_satisfies_the_provider_gate():
    """Otherwise the pre-flight refuses to dispatch an agent that is in fact
    signed in, which is the failure the whole flow exists to prevent."""
    validate_provider_credentials("anthropic/claude-sonnet-4.5", {"CLAUDE_CODE_ACCESS_TOKEN": "x"})
    validate_provider_credentials("openai/gpt-5.6", {"CODEX_ACCESS_TOKEN": "x"})
    with pytest.raises(ValueError, match="Claude subscription"):
        validate_provider_credentials("anthropic/claude-sonnet-4.5", {})
