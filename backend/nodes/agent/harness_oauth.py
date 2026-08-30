"""Server-side token freshness for harness subscription-OAuth credentials.

The Claude Code / Codex OAuth handlers mint short-lived access tokens (Claude:
~8h, ChatGPT: JWT exp) with refresh tokens, stored as ``{"credentials":
{ENV_VAR: value}}`` blobs (credential types ``agent_claude_code_oauth`` /
``agent_codex_oauth``). Runners receive a *snapshot* of those environment
variables and cannot persist a rotation back, so the credential row must be
the chain of record: ``ensure_fresh_harness_tokens`` refreshes it HERE, at
env-build time in ``AgentNode.execute()``, before every dispatch — the one
choke point all execution paths (canvas run, trigger, MCP, chat) converge on.

All lock / re-read / CAS-persist / audit semantics come from
``nodes.core.oauth_refresh.ensure_fresh_oauth_token``; this module only adapts
it to the env-var blob shape (``HarnessCredentialsStore``) and supplies the
two provider token-endpoint calls. Refreshes emit the standard ``oauth.refresh``
span + ``operator refresh audit`` row (provider ``claude_code`` /
``codex_chatgpt``).

This module is also the single source for the harness OAuth client constants —
the wss auth handlers import them from here.
"""

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from nodes.core.oauth_refresh import (
    CredentialsTableStore,
    ensure_fresh_oauth_token,
    is_token_expired,
)

logger = logging.getLogger(__name__)

# Anthropic Claude Code OAuth client (same client the official CLI uses).
# Subscription accounts authorize on claude.com/cai — the CLI's
# CLAUDE_AI_AUTHORIZE_URL as of Claude Code 2.1.205; claude.ai/oauth/authorize
# is the legacy host.
CLAUDE_CODE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_CODE_AUTH_URL = "https://claude.com/cai/oauth/authorize"
CLAUDE_CODE_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLAUDE_CODE_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"

# OpenAI Codex OAuth client (shared with the official codex CLI; opencode's
# vendored plugin reuses the same credential).
CODEX_ISSUER = "https://auth.openai.com"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_TOKEN_URL = f"{CODEX_ISSUER}/oauth/token"

# Row-level bookkeeping keys the flat env view carries for the refresh
# machinery (CAS + audit); never env vars, always stripped before dispatch.
_BOOKKEEPING_KEYS = ("token_version", "updated_at")

_TOKEN_TIMEOUT_S = 30.0

# Refresh when less than this remains. Wider than the integration-node default
# because an agent turn may run for a while before the CLI refreshes its token.
_EXPIRY_BUFFER_MINUTES = 30


@dataclass
class HarnessTokens:
    """Token model consumed by ``oauth_refresh._adopt_keys`` (attribute access).

    ``scope``/``token_type`` stay ``None`` deliberately — adopting them would
    write non-env keys into the env dict and leak into sandbox env vars.
    """

    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[str]
    scope: None = None
    token_type: None = None


def _jwt_exp_iso(token: Optional[str]) -> Optional[str]:
    """Best-effort ISO-8601 expiry from a JWT's ``exp`` claim (no verification)."""
    if not token or token.count(".") != 2:
        return None
    payload = token.split(".")[1]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        exp = json.loads(raw).get("exp")
        if not exp:
            return None
        return datetime.fromtimestamp(int(exp), tz=timezone.utc).isoformat()
    except (ValueError, binascii.Error, json.JSONDecodeError):
        return None


def compute_expires_at_iso(
    expires_in: Any, access_token: Optional[str] = None
) -> Optional[str]:
    """ISO-8601 expiry from a token response's ``expires_in`` (seconds), falling
    back to the access token's JWT ``exp`` claim (ChatGPT tokens carry one)."""
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        seconds = 0
    if seconds > 0:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    return _jwt_exp_iso(access_token)


def oauth_expires_ms(
    env: Dict[str, str],
    expires_at_key: str,
    expires_in_key: str,
    *,
    default_expires_in: int = 0,
) -> int:
    """Unix-ms expiry for a harness OAuth token in an env dict.

    Prefers the absolute ``*_EXPIRES_AT`` (mint-time truth, kept fresh
    server-side by ``ensure_fresh_harness_tokens``). The launch-time
    ``now + *_EXPIRES_IN`` fabrication survives only as the fallback for blobs
    minted before ``*_EXPIRES_AT`` existed; 0 means "unknown — refresh on
    first use" for consumers that treat it as such (opencode/openclaw)."""
    expires_at_iso = env.get(expires_at_key)
    if expires_at_iso:
        try:
            return int(datetime.fromisoformat(expires_at_iso).timestamp() * 1000)
        except ValueError:
            logger.warning("[harness_oauth] unparseable %s=%r", expires_at_key, expires_at_iso)
    try:
        expires_in_s = int(env.get(expires_in_key) or default_expires_in)
    except (TypeError, ValueError):
        expires_in_s = default_expires_in
    if expires_in_s <= 0:
        return 0
    return int(datetime.now(timezone.utc).timestamp() * 1000) + expires_in_s * 1000


def _raise_for_token_error(resp: httpx.Response, provider: str) -> None:
    """Provider 4xx/5xx → ValueError so oauth_refresh classifies it provider_4xx
    (deterministic — never retried) rather than a transient network error."""
    if resp.is_success:
        return
    body = resp.text[:300]
    raise ValueError(f"{provider} token endpoint returned {resp.status_code}: {body}")


async def _refresh_claude_code(refresh_token: str) -> HarnessTokens:
    async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S) as client:
        resp = await client.post(
            CLAUDE_CODE_TOKEN_URL,
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLAUDE_CODE_CLIENT_ID,
            },
        )
    _raise_for_token_error(resp, "claude_code")
    tokens = resp.json()
    access = tokens.get("access_token")
    if not access:
        raise ValueError("claude_code token refresh response had no access_token")
    return HarnessTokens(
        access_token=access,
        refresh_token=tokens.get("refresh_token"),
        expires_at=compute_expires_at_iso(tokens.get("expires_in"), access),
    )


def _make_codex_refresh(env: Dict[str, str]):
    """Codex refresh closure over the flat env dict: the response's rotated
    ``id_token`` must ride along into the persisted blob, but the shared
    ``_adopt_keys`` only carries access/refresh/expires — so the closure writes
    it into ``env`` directly (``env`` IS the dict the store persists)."""

    async def _refresh(refresh_token: str) -> HarnessTokens:
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S) as client:
            resp = await client.post(
                CODEX_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CODEX_CLIENT_ID,
                    "scope": "openid profile email",
                },
            )
        _raise_for_token_error(resp, "codex_chatgpt")
        tokens = resp.json()
        access = tokens.get("access_token")
        if not access:
            raise ValueError("codex_chatgpt token refresh response had no access_token")
        if tokens.get("id_token"):
            env["CODEX_ID_TOKEN"] = tokens["id_token"]
        return HarnessTokens(
            access_token=access,
            refresh_token=tokens.get("refresh_token"),
            expires_at=compute_expires_at_iso(tokens.get("expires_in"), access),
        )

    return _refresh


class HarnessCredentialsStore(CredentialsTableStore):
    """Flattened row-of-record view over the ``{"credentials": {ENV: value}}``
    blob, so ``ensure_fresh_oauth_token``'s re-read/CAS machinery operates on
    the same flat env dict the agent runtime consumes.

    ``load()`` returns the inner env dict with ``token_version``/``updated_at``
    injected (mirroring ``load_credential``'s row-level extras); ``persist()``
    re-nests the env keys and submits the CAS guard from the flat view.
    """

    async def load(self) -> Optional[Dict[str, Any]]:
        blob = await super().load()
        if not blob:
            return None
        flat = dict(blob.get("credentials") or {})
        for key in _BOOKKEEPING_KEYS:
            if blob.get(key) is not None:
                flat[key] = blob[key]
        return flat

    async def persist(
        self,
        new_data: Dict[str, Any],
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Optional[str]]:
        from utils.credentials import update_credential_data_detailed

        env = {
            k: v
            for k, v in new_data.items()
            if k not in _BOOKKEEPING_KEYS and isinstance(v, str)
        }
        return await update_credential_data_detailed(
            credential_id=self.credential_id,
            user_id=self.user_id,
            new_data={"credentials": env},
            metadata_updates=metadata_updates,
            pool=self.pool,
            expected_token_version=new_data.get("token_version"),
        )


@dataclass(frozen=True)
class _HarnessOAuthSpec:
    provider: str
    access_key: str
    refresh_key: str
    expires_at_key: str

    def build_refresh(self, env: Dict[str, str]):
        if self.provider == "claude_code":
            return lambda token: _refresh_claude_code(token)
        return _make_codex_refresh(env)


HARNESS_OAUTH_SPECS = (
    _HarnessOAuthSpec(
        provider="claude_code",
        access_key="CLAUDE_CODE_ACCESS_TOKEN",
        refresh_key="CLAUDE_CODE_REFRESH_TOKEN",
        expires_at_key="CLAUDE_CODE_EXPIRES_AT",
    ),
    _HarnessOAuthSpec(
        provider="codex_chatgpt",
        access_key="CODEX_ACCESS_TOKEN",
        refresh_key="CODEX_REFRESH_TOKEN",
        expires_at_key="CODEX_EXPIRES_AT",
    ),
)


async def ensure_fresh_harness_tokens(
    env: Optional[Dict[str, str]],
    *,
    user_id: Optional[str],
    credential_id: Optional[str],
    pool=None,
    caller_path: str = "execute",
) -> Optional[Dict[str, str]]:
    """Refresh any harness subscription-OAuth tokens in *env* that are expiring.

    Mutates and returns *env*. No-op for API-key credentials (no refresh token
    present). A blob minted before ``*_EXPIRES_AT`` existed is refreshed
    immediately (``force_refresh``) — the persist upgrades it in place, so the
    force fires once per legacy credential, not per run. Raises
    ``OAuthRefreshError`` (a ``ValueError``) when the provider rejects the
    refresh — fail loud with "reconnect" guidance rather than dispatching a
    sandbox that 401s mid-turn.
    """
    if not env:
        return env
    for spec in HARNESS_OAUTH_SPECS:
        if not env.get(spec.access_key) or not env.get(spec.refresh_key):
            continue
        store = (
            HarnessCredentialsStore(pool, user_id, credential_id)
            if user_id and credential_id
            else None
        )
        await ensure_fresh_oauth_token(
            pool=pool,
            credential_id=credential_id,
            user_id=user_id,
            credential=env,
            refresh=spec.build_refresh(env),
            access_token_key=spec.access_key,
            refresh_token_key=spec.refresh_key,
            expires_at_key=spec.expires_at_key,
            is_expired=lambda expires_at: is_token_expired(
                expires_at, buffer_minutes=_EXPIRY_BUFFER_MINUTES
            ),
            force_refresh=not env.get(spec.expires_at_key),
            provider=spec.provider,
            caller_path=caller_path,
            store=store,
        )
    for key in _BOOKKEEPING_KEYS:
        env.pop(key, None)
    env.pop("credential_type", None)
    return env


# Codex is not part of ChatGPT Free: the service answers a Free-plan sign-in by
# telling codex to use an API key instead, and with none connected the turn
# dies with a bare 401 from api.openai.com. Read the plan up front and say so.
CODEX_FREE_PLAN_MESSAGE = (
    "This ChatGPT account is on the Free plan, which doesn't include Codex. "
    "Sign in with a plan that does (Plus, Pro, Business, Edu or Enterprise), "
    "or connect an OpenAI API key instead."
)


def chatgpt_plan_type(id_token: Optional[str]) -> Optional[str]:
    """``chatgpt_plan_type`` from a ChatGPT id token's claims (unverified —
    the claim only steers a message, never authorization); None when unknown."""
    import base64
    import json

    if not id_token or id_token.count(".") != 2:
        return None
    payload = id_token.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, UnicodeDecodeError):
        return None
    auth = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else None
    plan = auth.get("chatgpt_plan_type") if isinstance(auth, dict) else None
    return plan.lower() if isinstance(plan, str) and plan else None


def codex_chatgpt_ineligible(id_token: Optional[str]) -> Optional[str]:
    """The reason a ChatGPT sign-in cannot drive Codex, else None."""
    return CODEX_FREE_PLAN_MESSAGE if chatgpt_plan_type(id_token) == "free" else None
