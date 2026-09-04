"""Provider communication for the agent CLI OAuth sign-in flows — Codex
(ChatGPT) and Claude Code (Anthropic).

Single source of truth for the device-code / PKCE mechanics, shared by the
authenticated socket handlers (``wss/handlers/oauth/*_auth_handler.py``) and the
public credential-provide endpoints (``utils/credential_request_routes.py``) so
the two can't drift. The token-minting side lives here; token REFRESH lives in
``harness_oauth.py`` (the refresh choke point).

Two flow kinds:
  - ``"device_code"``: ``start()`` returns a verification URL + user code the
    person enters on the provider's site; ``complete(poll)`` polls the token
    endpoint until approval and mints tokens.
  - ``"pkce"``: ``start()`` returns an authorize URL (verifier stashed in Redis);
    the person signs in and pastes the returned code back; ``complete(poll)``
    exchanges it for tokens.

``start()`` returns ``{"display": {...}, "poll": {...}}`` where ``display`` is
shown to the user and ``poll`` is opaque state echoed back to ``complete()``.
``complete(poll)`` returns one of:
  - ``{"status": "pending"}`` / ``{"status": "slow_down"}`` (device_code — keep polling)
  - ``{"status": "completed", "credential_data": {...}}`` (tokens minted)
and raises ``OAuthFlowError`` on a hard failure (expired, denied, provider error).
"""

import hashlib
import json
import logging
import secrets
import time
import uuid
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
import redis.asyncio as redis

from nodes.agent.harness_oauth import (
    CLAUDE_CODE_AUTH_URL,
    CLAUDE_CODE_CLIENT_ID,
    CLAUDE_CODE_REDIRECT_URI,
    CLAUDE_CODE_TOKEN_URL,
    CODEX_CLIENT_ID,
    CODEX_ISSUER,
    compute_expires_at_iso,
)

logger = logging.getLogger(__name__)

_TIMEOUT_S = 30.0


class OAuthFlowError(Exception):
    """A hard failure in an agent OAuth flow (expired code, denial, provider error).
    Distinct from the soft 'pending'/'slow_down' poll states."""


# --- PKCE verifier stash --------------------------------------------------------
# The verifier is written by `start` and read by `complete`, minutes later, and
# must never reach the browser. Redis holds it wherever there is one — which is
# required for a deployment running more than one backend, since `start` and
# `complete` are separate requests that need not land on the same process. With
# no Redis configured, this process holds it: a single-backend installation has
# nowhere else for the request to go, and refusing to sign in at all was the
# alternative.
_PKCE_TTL_S = 600
_local_pkce: Dict[str, tuple] = {}
_redis_client: Optional[redis.Redis] = None


def _get_redis() -> Optional[redis.Redis]:
    from utils.redis_client import RESILIENCE_KWARGS, redis_url_or_none

    global _redis_client
    if _redis_client is None:
        url = redis_url_or_none()
        if not url:
            return None
        try:
            _redis_client = redis.from_url(url, **RESILIENCE_KWARGS)
        except Exception as e:
            logger.error(f"[harness_oauth_flows] Redis unavailable: {e}")
            return None
    return _redis_client


async def _pkce_put(session_id: str, verifier: str) -> None:
    r = _get_redis()
    if r is not None:
        await r.set(
            f"claude_code_pkce:{session_id}",
            json.dumps({"code_verifier": verifier}),
            ex=_PKCE_TTL_S,
        )
        return
    _local_pkce[session_id] = (verifier, time.time() + _PKCE_TTL_S)


async def _pkce_take(session_id: str) -> Optional[str]:
    """Single-use: a verifier that has been read is gone, whichever store held it."""
    r = _get_redis()
    if r is not None:
        stored = await r.get(f"claude_code_pkce:{session_id}")
        if not stored:
            return None
        await r.delete(f"claude_code_pkce:{session_id}")
        return json.loads(stored)["code_verifier"]
    now = time.time()
    for key, (_, expiry) in list(_local_pkce.items()):
        if expiry < now:
            _local_pkce.pop(key, None)
    entry = _local_pkce.pop(session_id, None)
    return entry[0] if entry else None


# ==============================================================================
# Codex (ChatGPT) — device code
# ==============================================================================

async def codex_start() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        resp = await client.post(
            f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode",
            headers={"Content-Type": "application/json"},
            json={"client_id": CODEX_CLIENT_ID},
        )
        if resp.status_code == 404:
            raise OAuthFlowError("Device-code login is not available. Use an API key instead.")
        if not resp.is_success:
            logger.error(f"[codex_start] device code request failed: HTTP {resp.status_code}")
            raise OAuthFlowError(f"Failed to request device code (status {resp.status_code})")
        data = resp.json()

    user_code = data.get("user_code") or data.get("usercode", "")
    device_auth_id = data.get("device_auth_id", "")
    interval = int(data.get("interval", 5))
    return {
        "display": {
            "verification_url": f"{CODEX_ISSUER}/codex/device",
            "user_code": user_code,
            "interval": interval,
        },
        "poll": {"device_auth_id": device_auth_id, "user_code": user_code},
    }


async def codex_complete(poll: Dict[str, Any]) -> Dict[str, Any]:
    device_auth_id = poll.get("device_auth_id", "")
    user_code = poll.get("user_code", "")
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        resp = await client.post(
            f"{CODEX_ISSUER}/api/accounts/deviceauth/token",
            headers={"Content-Type": "application/json"},
            json={"device_auth_id": device_auth_id, "user_code": user_code},
        )
        if resp.status_code in (403, 404):
            return {"status": "pending"}
        if not resp.is_success:
            logger.error(f"[codex_complete] poll failed: HTTP {resp.status_code}")
            raise OAuthFlowError(f"Device code poll failed (status {resp.status_code})")
        code_data = resp.json()

        token_resp = await client.post(
            f"{CODEX_ISSUER}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code_data.get("authorization_code", ""),
                "redirect_uri": f"{CODEX_ISSUER}/deviceauth/callback",
                "client_id": CODEX_CLIENT_ID,
                "code_verifier": code_data.get("code_verifier", ""),
            },
        )
        if not token_resp.is_success:
            logger.error(f"[codex_complete] token exchange failed: HTTP {token_resp.status_code}")
            raise OAuthFlowError("Failed to exchange device code for tokens")
        tokens = token_resp.json()

        if not tokens.get("id_token") and tokens.get("refresh_token"):
            # The device-auth exchange doesn't always mint an id token, and codex
            # needs one to reach the ChatGPT backend — without it the CLI silently
            # falls back to API-key auth. The refresh grant requests ``openid``.
            minted_resp = await client.post(
                f"{CODEX_ISSUER}/oauth/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": CODEX_CLIENT_ID,
                    "scope": "openid profile email",
                },
            )
            if minted_resp.is_success:
                minted = minted_resp.json()
                tokens = {**tokens, **{k: v for k, v in minted.items() if v}}
            if not tokens.get("id_token"):
                raise OAuthFlowError(
                    "The ChatGPT sign-in did not include an identity token, "
                    "which Codex needs. Try signing in again."
                )

    access_token = tokens.get("access_token", "")
    if not access_token:
        raise OAuthFlowError("No access token received from token exchange")
    from nodes.agent.harness_oauth import codex_chatgpt_ineligible

    ineligible = codex_chatgpt_ineligible(tokens.get("id_token"))
    if ineligible:
        raise OAuthFlowError(ineligible)
    return {
        "status": "completed",
        "credential_data": {
            "credentials": {
                "CODEX_ACCESS_TOKEN": access_token,
                "CODEX_REFRESH_TOKEN": tokens.get("refresh_token", ""),
                "CODEX_ID_TOKEN": tokens.get("id_token", ""),
                "CODEX_EXPIRES_AT": compute_expires_at_iso(tokens.get("expires_in"), access_token) or "",
            }
        },
    }


# ==============================================================================
# Claude Code (Anthropic) — PKCE paste
# ==============================================================================

async def claude_code_start() -> Dict[str, Any]:
    code_verifier = urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")[:43]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    auth_session_id = str(uuid.uuid4())

    await _pkce_put(auth_session_id, code_verifier)

    auth_url = (
        f"{CLAUDE_CODE_AUTH_URL}"
        f"?code=true"
        f"&client_id={CLAUDE_CODE_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={CLAUDE_CODE_REDIRECT_URI}"
        f"&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference+user%3Asessions%3Aclaude_code+user%3Amcp_servers+user%3Afile_upload"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&state={auth_session_id}"
    )
    return {
        "display": {"authorize_url": auth_url},
        "poll": {"auth_session_id": auth_session_id},
    }


async def claude_code_complete(poll: Dict[str, Any]) -> Dict[str, Any]:
    auth_session_id = poll.get("auth_session_id", "")
    raw_code = poll.get("code", "")
    # The pasted code is "{code}#{state}".
    parts = raw_code.split("#")
    authorization_code = parts[0]
    code_state = parts[1] if len(parts) > 1 else None

    code_verifier = await _pkce_take(auth_session_id)
    if not code_verifier:
        raise OAuthFlowError("Auth session expired or invalid. Please restart the sign-in.")

    token_body: Dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "client_id": CLAUDE_CODE_CLIENT_ID,
        "redirect_uri": CLAUDE_CODE_REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    if code_state:
        token_body["state"] = code_state

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        token_resp = await client.post(
            CLAUDE_CODE_TOKEN_URL,
            headers={"Content-Type": "application/json"},
            json=token_body,
        )
        if not token_resp.is_success:
            logger.error(f"[claude_code_complete] token exchange failed: HTTP {token_resp.status_code}")
            raise OAuthFlowError(
                f"Claude rejected the authorization code ({token_resp.status_code}). "
                f"Codes are single-use and short-lived — restart and paste the new code promptly."
            )
        tokens = token_resp.json()

    access_token = tokens.get("access_token", "")
    if not access_token:
        raise OAuthFlowError("No access token received from token exchange")
    expires_in = tokens.get("expires_in", "")
    return {
        "status": "completed",
        "credential_data": {
            "credentials": {
                "CLAUDE_CODE_ACCESS_TOKEN": access_token,
                "CLAUDE_CODE_REFRESH_TOKEN": tokens.get("refresh_token", ""),
                "CLAUDE_CODE_EXPIRES_IN": str(expires_in),
                "CLAUDE_CODE_EXPIRES_AT": compute_expires_at_iso(expires_in, access_token) or "",
            }
        },
    }


# ==============================================================================
# Registry
# ==============================================================================

@dataclass(frozen=True)
class AgentOAuthFlow:
    credential_type: str
    kind: str  # 'device_code' | 'pkce'
    label: str
    credential_name: str
    metadata: Dict[str, str]
    start: Callable[[], Awaitable[Dict[str, Any]]]
    complete: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


AGENT_OAUTH_FLOWS: Dict[str, AgentOAuthFlow] = {
    "agent_codex_oauth": AgentOAuthFlow(
        "agent_codex_oauth", "device_code", "Sign in with ChatGPT",
        "ChatGPT (Codex)", {"provider": "codex", "auth_mode": "chatgpt"},
        codex_start, codex_complete,
    ),
    "agent_claude_code_oauth": AgentOAuthFlow(
        "agent_claude_code_oauth", "pkce", "Sign in with Claude",
        "Anthropic (Claude Code)", {"provider": "claude_code", "auth_mode": "oauth"},
        claude_code_start, claude_code_complete,
    ),
}

# Base agent provider (agent_<provider>) → the OAuth credential type a person can
# also provide for it. Only providers whose primary/only sensible external auth is
# OAuth are listed; plain agent_openai/agent_anthropic keep API-key-only requests.
AGENT_PROVIDER_OAUTH_TYPE: Dict[str, str] = {
    "codex": "agent_codex_oauth",
    "claude_code": "agent_claude_code_oauth",
}

# Providers with NO API-key path — OAuth sign-in is the only way to provide them.
AGENT_OAUTH_ONLY_PROVIDERS: set = set()


def register_agent_oauth_flow(flow: AgentOAuthFlow, *, provider: str, oauth_only: bool = False) -> None:
    """A sign-in this deployment offers beyond the two above — a provider it
    has an agreement with. Registered before serving traffic; the credential
    provide endpoints, the socket handlers and the instance-status report all
    read these tables at call time."""
    AGENT_OAUTH_FLOWS[flow.credential_type] = flow
    AGENT_PROVIDER_OAUTH_TYPE[provider] = flow.credential_type
    if oauth_only:
        AGENT_OAUTH_ONLY_PROVIDERS.add(provider)


def get_agent_oauth_flow(credential_type: str) -> Optional[AgentOAuthFlow]:
    return AGENT_OAUTH_FLOWS.get(credential_type)
