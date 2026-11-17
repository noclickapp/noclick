"""Token freshness for harness subscription-OAuth credentials (plan sign-ins).

The Claude Code / Codex OAuth handlers mint short-lived access tokens (Claude:
~8h, ChatGPT: JWT exp) with refresh tokens that rotate, stored as
``{"credentials": {ENV_VAR: value}}`` blobs (credential types
``agent_claude_code_oauth`` / ``agent_codex_oauth``). The credential row is the
chain of record, and a sign-in has one writer at a time:

- Where a harness renews the sign-in itself, from its own container
  (``renewed_in_container``; hosted, through the container's refresh gate,
  ``cloud.agent.sign_in``), NoClick never refreshes it at dispatch: the harness
  does, on its own timing, and its refresh is written back to the row.
- Everywhere else NoClick refreshes it here (``ensure_fresh_harness_tokens``):
  at dispatch for a harness given no refresh token (OpenClaw; the open edition's
  local CLIs), the credential proxy's subscription upstreams, a connection's
  check. Each such refresh runs under the sign-in's one refresh lease
  (``register_refresh_lease``; the open edition's single process needs none), so
  it never races a container's.

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
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncContextManager, Callable, Dict, List, Optional, Tuple

import httpx

from utils.async_helpers import spawn
from nodes.core.oauth_refresh import (
    CLIENT_SETUP_CODES,
    CredentialsTableStore,
    OAuthRefreshError,
    TokenEndpointError,
    ensure_fresh_oauth_token,
    is_token_expired,
    request_never_sent,
)

# Whether a harness renews a plan's sign-in itself, from its own container: (model type, credential type) -> bool. The
# hosted runtime registers its refresh gate's harnesses; unregistered (the open edition), NoClick refreshes before
# every dispatch and the harness is given no refresh token.
_renewed_in_container: Callable[[str, str], bool] = lambda model_type, credential_type: False
# The lease every refresh NoClick makes of a plan's sign-in runs under: ``lease(pool, credential_id, caller_path=...)``
# -> an async context manager yielding a ``RefreshAttempt``. None: the open edition, whose one process the in-process
# lock serializes.
_refresh_lease: Optional[Callable[..., AsyncContextManager["RefreshAttempt"]]] = None


def register_container_renewal(predicate: Callable[[str, str], bool]) -> None:
    global _renewed_in_container
    _renewed_in_container = predicate


def renewed_in_container(model_type: str, credential_type: Optional[str]) -> bool:
    """Whether the harness renews this plan's sign-in itself, so NoClick must not refresh it at dispatch."""
    return bool(credential_type) and _renewed_in_container(model_type, credential_type)


def register_refresh_lease(lease: Callable[..., AsyncContextManager["RefreshAttempt"]]) -> None:
    global _refresh_lease
    _refresh_lease = lease


class LeaseMoved(RuntimeError):
    """The refresh would present a token other than its lease's: the sign-in moved on since the lease was granted."""


class RefreshAttempt:
    """What a refresh under the lease did, for the lease to judge whether the refresh token may have been presented:
    whether the token endpoint was called, and what it failed with. ``refresh_token`` is the leased version's: no
    other is presented under the lease."""

    def __init__(self, refresh_token: Optional[str] = None) -> None:
        self.refresh_token = refresh_token
        self.attempted = False
        self.failure: Optional[BaseException] = None

    def watch(self, refresh):
        async def watched(token: str):
            if self.refresh_token is not None and token != self.refresh_token:
                raise LeaseMoved("the sign-in moved on since its refresh lease was granted")
            self.attempted = True
            try:
                return await refresh(token)
            except Exception as exc:
                self.failure = exc
                raise
        return watched

    @property
    def presented(self) -> bool:
        """Whether the provider may have taken the refresh token: called, and not failed in a way that says it
        wasn't (never sent; or refused as NoClick's own client, before the grant is looked at). A 5xx says nothing
        either way, so it counts, as does a refresh that succeeded but whose successor wasn't kept."""
        if not self.attempted:
            return False
        failure = self.failure
        if failure is None:
            return True
        if request_never_sent(failure):
            return False
        return not any(code in str(failure) for code in CLIENT_SETUP_CODES)

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

# Where ChatGPT lists the models a sign-in runs, read as Codex reads it for a
# ChatGPT account. Its picker list is the CLI's own and can name a model ChatGPT
# no longer serves its accounts ("The 'gpt-5.5' model is not supported when using
# Codex with a ChatGPT account", 2026-11-11), so a plan is judged by this.
CHATGPT_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
# A ChatGPT sign-in's credential metadata: the models ChatGPT lists for it, and when it said so.
PLAN_MODELS_KEY = "chatgpt_models"
PLAN_MODELS_AT_KEY = "chatgpt_models_at"
# The email a sign-in is for, in its credential's metadata: what Connect reads as the connection's ``account``, so two
# plans of one kind are told apart.
SIGNED_IN_AS_KEY = "verified_as"
# When a Claude sign-in was made, in its credential's metadata. Claude ends a sign-in a fixed time after it was made,
# however often its token is refreshed, and a reconnect updates the row in place, so ``created_at`` can't say it.
SIGNED_IN_AT_KEY = "signed_in_at"

# Row-level bookkeeping keys the flat env view carries for the refresh
# machinery (CAS + audit); never env vars, always stripped before dispatch.
_BOOKKEEPING_KEYS = ("token_version", "updated_at")

_TOKEN_TIMEOUT_S = 30.0
# A sign-in or refresh waits this long for ChatGPT's model list, then goes on without it.
_MODELS_TIMEOUT_S = 10.0

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
    # The account the response names (Claude's ``account.email_address``); never adopted into the env.
    email: Optional[str] = None
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
    first use"."""
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
    """Provider 4xx/5xx → a ``TokenEndpointError`` (a ValueError: never retried) carrying the status, which
    ``oauth_refresh.grant_ended`` judges by."""
    if resp.is_success:
        return
    body = resp.text[:300]
    raise TokenEndpointError(f"{provider} token endpoint returned {resp.status_code}: {body}",
                             status=resp.status_code)


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
        email=claude_account_email(tokens),
    )


def claude_account_email(tokens: Dict[str, Any]) -> Optional[str]:
    """The email of the Claude account a token response (a sign-in's or a refresh's) is for, as Claude Code reads it
    (``account.email_address``); None when it names none."""
    account = tokens.get("account")
    email = account.get("email_address") if isinstance(account, dict) else None
    return email if isinstance(email, str) and email else None


def signed_in_as(email: Optional[str]) -> Dict[str, str]:
    """The credential metadata naming the account a sign-in is for (``SIGNED_IN_AS_KEY``), or nothing."""
    return {SIGNED_IN_AS_KEY: email} if email else {}


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
    credential_type: str
    access_key: str
    refresh_key: str
    expires_at_key: str
    # Token fields a refresh rotates alongside access/refresh/expires.
    companion_keys: Tuple[str, ...] = ()

    def build_refresh(self, env: Dict[str, str], said: Dict[str, Optional[str]]):
        """The refresh call; a Claude refresh's response also names its account, kept in ``said`` for the caller
        to store after the refresh, never inside it."""
        if self.provider == "claude_code":
            async def refresh(token: str) -> HarnessTokens:
                tokens = await _refresh_claude_code(token)
                said["email"] = getattr(tokens, "email", None)
                return tokens
            return refresh
        return _make_codex_refresh(env)

    def stale(self, row: Dict[str, Any]) -> bool:
        """Refresh even though the access token is fine: a legacy blob with no expiry (the persist upgrades it in
        place, once), or a ChatGPT sign-in with no id token, which Codex reads its mode and account from (the refresh
        grant requests ``openid`` and mints one). An id token past its hourly end still names them (Codex never
        judges its expiry), so that alone is no reason to rotate the sign-in."""
        if not row.get(self.expires_at_key):
            return True
        return self.provider == "codex_chatgpt" and codex_id_token_missing(row.get("CODEX_ID_TOKEN"))


HARNESS_OAUTH_SPECS = (
    _HarnessOAuthSpec(
        provider="claude_code",
        credential_type="agent_claude_code_oauth",
        access_key="CLAUDE_CODE_ACCESS_TOKEN",
        refresh_key="CLAUDE_CODE_REFRESH_TOKEN",
        expires_at_key="CLAUDE_CODE_EXPIRES_AT",
    ),
    _HarnessOAuthSpec(
        provider="codex_chatgpt",
        credential_type="agent_codex_oauth",
        access_key="CODEX_ACCESS_TOKEN",
        refresh_key="CODEX_REFRESH_TOKEN",
        expires_at_key="CODEX_EXPIRES_AT",
        companion_keys=("CODEX_ID_TOKEN",),
    ),
)
# A plan's env keys, by its credential type.
PLAN_SPECS = {spec.credential_type: spec for spec in HARNESS_OAUTH_SPECS}
# Every env key a plan's sign-in holds that changes as it's renewed: never what a warm container is keyed on.
PLAN_TOKEN_KEYS = frozenset(
    key for spec in HARNESS_OAUTH_SPECS
    for key in (spec.access_key, spec.refresh_key, spec.expires_at_key, *spec.companion_keys)
) | {"CLAUDE_CODE_EXPIRES_IN"}


async def ensure_fresh_harness_tokens(
    env: Optional[Dict[str, str]],
    *,
    user_id: Optional[str],
    credential_id: Optional[str],
    pool=None,
    caller_path: str = "execute",
    force_refresh: bool = False,
) -> Optional[Dict[str, str]]:
    """Refresh any harness subscription-OAuth tokens in *env* that are expiring.

    Mutates and returns *env*. No-op for API-key credentials (no refresh token
    present). A blob minted before ``*_EXPIRES_AT`` existed, or a codex sign-in
    whose 1h id token has lapsed, is refreshed via the row-level ``stale``
    predicate — re-judged against the in-lock re-read, so concurrent runs share
    one refresh instead of each minting a token. Raises ``OAuthRefreshError``
    (a ``ValueError``) when the provider rejects the refresh — fail loud with
    "reconnect" guidance rather than dispatching a sandbox that 401s mid-turn.
    ``force_refresh`` refreshes a token the provider just rejected although its
    expiry says it is fine, for a caller that replays the rejected request.
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
        before = env.get(spec.access_key)
        said: Dict[str, Optional[str]] = {}
        due = force_refresh or spec.stale(env) or is_token_expired(
            env.get(spec.expires_at_key), buffer_minutes=_EXPIRY_BUFFER_MINUTES)
        if due and _refresh_lease is not None and store is None:
            raise ValueError(f"A {spec.provider} sign-in is refreshed only against its credential row.")
        lease = (_refresh_lease(pool, credential_id, caller_path=caller_path)
                 if due and _refresh_lease is not None else contextlib.nullcontext(None))
        try:
            async with lease as attempt:
                refresh = spec.build_refresh(env, said)
                await ensure_fresh_oauth_token(
                    pool=pool,
                    credential_id=credential_id,
                    user_id=user_id,
                    credential=env,
                    refresh=attempt.watch(refresh) if attempt is not None else refresh,
                    access_token_key=spec.access_key,
                    refresh_token_key=spec.refresh_key,
                    expires_at_key=spec.expires_at_key,
                    is_expired=lambda expires_at: is_token_expired(
                        expires_at, buffer_minutes=_EXPIRY_BUFFER_MINUTES
                    ),
                    stale=spec.stale,
                    # A refresh rotates the id token too; adopting a sibling's row must carry it.
                    additional_token_fields=spec.companion_keys,
                    force_refresh=force_refresh,
                    provider=spec.provider,
                    caller_path=caller_path,
                    store=store,
                    # The refresh token rotates: a request that may have reached the provider is never sent again
                    # (a second presentation can end the sign-in).
                    retry_unsent_only=True,
                )
        except OAuthRefreshError as e:
            if e.provider_error_code in CLIENT_SETUP_CODES:
                # The client is NoClick's (the CLI's own), so this is our setup, never the person's sign-in.
                logger.error("[harness_oauth] %s refused NoClick's client (%s, HTTP %s) refreshing credential %s",
                             spec.provider, e.provider_error_code, e.status, credential_id)
            raise
        if store is not None and env.get(spec.access_key) != before:
            # After the refresh, never inside it: the refresh attempt is bounded, and the rotated token it minted
            # must persist whatever ChatGPT's list takes. Off the dispatch too: nothing waits on it. So a sign-in
            # made before its account was kept gets it at its next refresh.
            codex = spec.provider == "codex_chatgpt"
            email = chatgpt_email(env.get("CODEX_ID_TOKEN")) if codex else said.get("email")
            if codex or email:
                spawn(store_sign_in(pool, credential_id, spec.provider, dict(env), email),
                      name="harness_oauth.sign_in")
    return without_bookkeeping(env)


def without_bookkeeping(env: Dict[str, Any]) -> Dict[str, Any]:
    """The env a runtime receives: the row-level keys the refresh machinery reads stripped (in place)."""
    for key in (*_BOOKKEEPING_KEYS, "credential_type"):
        env.pop(key, None)
    return env


# Codex is not part of ChatGPT Free: the service answers a Free-plan sign-in by
# telling codex to use an API key instead, and with none connected the turn
# dies with a bare 401 from api.openai.com. Read the plan up front and say so.
CODEX_FREE_PLAN_MESSAGE = (
    "This ChatGPT account is on the Free plan, which doesn't include Codex. "
    "Sign in with a plan that does (Plus, Pro, Business, Edu or Enterprise), "
    "or connect a ChatGPT API key instead."
)


def _chatgpt_id_token_claims(id_token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Decoded claims of a ChatGPT id token (unverified — claims only steer
    messages and refresh timing, never authorization); None when unparseable."""
    import base64
    import json

    if not id_token or id_token.count(".") != 2:
        return None
    payload = id_token.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, UnicodeDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def _chatgpt_auth_claim(id_token: Optional[str], name: str) -> Optional[str]:
    claims = _chatgpt_id_token_claims(id_token)
    auth = claims.get("https://api.openai.com/auth") if claims else None
    value = auth.get(name) if isinstance(auth, dict) else None
    return value if isinstance(value, str) and value else None


def chatgpt_plan_type(id_token: Optional[str]) -> Optional[str]:
    """``chatgpt_plan_type`` from a ChatGPT id token's claims; None when unknown."""
    plan = _chatgpt_auth_claim(id_token, "chatgpt_plan_type")
    return plan.lower() if plan else None


def chatgpt_email(id_token: Optional[str]) -> Optional[str]:
    """The email a ChatGPT sign-in is for, from its id token's claims, as Codex reads it; None when unknown."""
    claims = _chatgpt_id_token_claims(id_token)
    email = claims.get("email") if claims else None
    return email if isinstance(email, str) and email else None


def chatgpt_account_id(id_token: Optional[str]) -> Optional[str]:
    """The ChatGPT account (workspace) a sign-in acts in, from its id token's claims, as Codex reads it; an expired
    token still names it. None when unknown."""
    return _chatgpt_auth_claim(id_token, "chatgpt_account_id")


async def chatgpt_plan_models(env: Dict[str, Any]) -> Optional[List[str]]:
    """The models ChatGPT lists for this sign-in, as the pinned Codex asks for
    them: those it offers, in its order. None when the list can't be read (no
    token, a refusal, an outage): unknown, never empty."""
    from nodes.agent.config._cli_models_loader import codex_version

    token = env.get("CODEX_ACCESS_TOKEN")
    if not token:
        return None
    account = chatgpt_account_of(env)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "originator": "codex_cli_rs",
               **({"ChatGPT-Account-ID": account} if account else {})}
    try:
        async with httpx.AsyncClient(timeout=_MODELS_TIMEOUT_S) as client:
            resp = await client.get(CHATGPT_MODELS_URL, params={"client_version": codex_version()}, headers=headers)
        if not resp.is_success:
            logger.warning("[harness_oauth] ChatGPT's model list answered HTTP %s", resp.status_code)
            return None
        rows = resp.json().get("models")
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        logger.warning("[harness_oauth] ChatGPT's model list couldn't be read: %s", e)
        return None
    if not isinstance(rows, list):
        return None
    return [m["slug"] for m in rows if isinstance(m, dict) and isinstance(m.get("slug"), str)
            and m.get("visibility") == "list"]


def plan_models_metadata(models: List[str]) -> Dict[str, Any]:
    """The credential metadata recording the models ChatGPT listed for a sign-in."""
    return {PLAN_MODELS_KEY: models, PLAN_MODELS_AT_KEY: datetime.now(timezone.utc).isoformat()}


async def store_sign_in(pool, credential_id: str, provider: str, env: Dict[str, Any],
                        email: Optional[str]) -> None:
    """What a refreshed sign-in says of itself, kept in its credential's metadata, never its blob or token version:
    the email it's for, and for a ChatGPT sign-in the models ChatGPT lists for it, read with its fresh token. What
    can't be read changes nothing."""
    from repositories.credentials import merge_credential_metadata
    from utils import database_pool

    patch = signed_in_as(email)
    if provider == "codex_chatgpt":
        models = await chatgpt_plan_models(env)
        if models is not None:
            patch.update(plan_models_metadata(models))
    if patch:
        await merge_credential_metadata(pool or database_pool.get_native_pool(), credential_id, patch)


def chatgpt_account_of(env: Dict[str, Any]) -> Optional[str]:
    """A ChatGPT sign-in's account: the credential's own field where it carries one (the sign-in flow saves none),
    else its id token's."""
    return env.get("CODEX_ACCOUNT_ID") or chatgpt_account_id(env.get("CODEX_ID_TOKEN"))


def codex_id_token_missing(id_token: Optional[str]) -> bool:
    """True when a ChatGPT sign-in has no id token Codex can read its claims from (absent or unparseable): Codex
    then runs signed out. One past its ``exp`` still names its plan and account."""
    return _chatgpt_id_token_claims(id_token) is None


def needs_healing(env: Optional[Dict[str, Any]]) -> bool:
    """Whether a plan's stored sign-in is one a harness can't run on as it is (``_HarnessOAuthSpec.stale``): NoClick
    refreshes it once before handing it over, even to a harness that renews it itself from then on."""
    return any(env and env.get(spec.access_key) and env.get(spec.refresh_key) and spec.stale(env)
               for spec in HARNESS_OAUTH_SPECS)


def codex_chatgpt_ineligible(id_token: Optional[str]) -> Optional[str]:
    """The reason a ChatGPT sign-in cannot drive Codex, else None."""
    return CODEX_FREE_PLAN_MESSAGE if chatgpt_plan_type(id_token) == "free" else None
