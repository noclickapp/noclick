"""Shared OAuth access-token refresh.

Many integration nodes hold OAuth credentials whose access tokens expire. A
refreshed token must be persisted back to the ``credentials`` table, and — for
providers that rotate the refresh token on every use (Slack, Twitter/X, …) —
concurrent refreshes must not both fire, or the loser refreshes with an
already-consumed refresh token and fails.

``ensure_fresh_oauth_token`` is the one correct implementation:

- per-credential lock serializes refreshes within a process;
- the lock holder **re-reads the credential from the database** before
  refreshing, so a concurrent refresh elsewhere in the process is a true no-op;
- if the refresh call fails (a rotating token consumed by another container),
  it re-reads once and adopts whatever that container persisted.

It is provider-agnostic: the caller supplies its provider's ``is_expired`` and
``refresh`` callables and the decrypted credential dict (which is mutated in
place with the fresh tokens).

Every invocation emits one provider-agnostic ``oauth.refresh`` OTel span.
The optional audit hook defaults to a non-persisting implementation; operators
can supply a sink that matches their own retention and privacy policy.
"""

import asyncio
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from opentelemetry import trace

from nodes.core.oauth_audit import (
    CredentialRefreshAuditBuilder,
    NetworkFailureKind,
    PhaseOutcome,
    _parse_iso8601,
    _sorted_scope,
    classify_httpx_exception,
    current_caller_path,
    is_retryable_network_exception,
)
from utils.audit_pool import record_refresh_event
from utils.otel import get_tracer

logger = logging.getLogger(__name__)
_tracer = get_tracer(__name__)

# Locks are keyed by the store's lock_key (credential_id for the default
# credentials-table store), which is globally unique, so a single process-wide
# registry is safe to share across every provider.
_refresh_locks: Dict[str, asyncio.Lock] = {}

# Bounded per-attempt timeout + retry for the provider token-endpoint call.
# A transient provider-endpoint failure can otherwise surface as a misleading
# token-expired error. The retry handles short-lived network failures; the
# timeout is the deterministic backstop. Most blips are a single
# dropped packet / momentary DNS hiccup that a second attempt clears. The
# wait_for is a deterministic BACKSTOP applied at the one choke point (no
# per-provider httpx-timeout edits): 15s is ~5x the p99 of a healthy refresh, so
# it only fires on a genuine stall and never preempts a slow-but-successful
# refresh — including the 4 rotating providers (HubSpot/Twitter/Supabase/TikTok)
# that set their own 30s client timeout, where an external cancel mid-rotation
# would drop a freshly minted single-use token. Worst-case per-credential lock
# hold is MAX_ATTEMPTS * ATTEMPT_TIMEOUT + sum(backoffs) ≈ 46s, only reached when
# every attempt stalls — i.e. the credential was going to fail this run anyway.
_REFRESH_ATTEMPT_TIMEOUT_S = 15.0
_REFRESH_MAX_ATTEMPTS = 3
_REFRESH_RETRY_BACKOFF_S = (0.5, 1.0)

# Per-scope dedupe of force_refresh (see force_refresh_once_scope). None when
# no scope is active — force_refresh then behaves as requested every time.
_FORCE_REFRESH_SEEN: ContextVar[Optional[set]] = ContextVar(
    "oauth_force_refresh_seen", default=None
)


@contextmanager
def force_refresh_once_scope():
    """Honor ``force_refresh=True`` once per token chain within this scope.

    Trigger-test batches run several tests against the same credential, each
    forcing a refresh. On providers with single-use rotating refresh tokens
    every forced rotation consumes a single-use token. Inside this scope, the
    first force per
    ``(lock_key, refresh_token_key)`` proceeds; repeats downgrade to a normal
    expiry-gated refresh (which the in-lock no-op then short-circuits).
    """
    token = _FORCE_REFRESH_SEEN.set(set())
    try:
        yield
    finally:
        _FORCE_REFRESH_SEEN.reset(token)


class CredentialsTableStore:
    """Row-of-record adapter for ``ensure_fresh_oauth_token``: the
    ``credentials`` table. The Slack workspace bot chain uses
    ``utils.slack_installations.SlackInstallationStore`` instead — same
    interface against ``slack_installations``.

    ``load()`` returns the decrypted dict with ``token_version`` injected;
    ``persist()`` is a compare-and-swap on that version, so a writer holding a
    stale snapshot loses cleanly (0 rows) instead of silently reverting a
    concurrent rotation. Imports stay function-local to match the historical
    patch points in tests.

    ``pool`` may be None: the canonical loaders it delegates to resolve the
    native pool at first actual DB use, never at construction — the
    not-expired short-circuit in ``ensure_fresh_oauth_token`` must stay
    reachable without a database.
    """

    def __init__(self, pool, user_id: str, credential_id: str):
        self.pool = pool
        self.user_id = user_id
        self.credential_id = credential_id

    @property
    def lock_key(self) -> str:
        return self.credential_id

    async def load(self) -> Optional[Dict[str, Any]]:
        from utils.credential_loader import load_credential

        return await load_credential(self.pool, self.user_id, self.credential_id)

    async def persist(
        self,
        new_data: Dict[str, Any],
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Optional[str]]:
        from utils.credentials import update_credential_data_detailed

        return await update_credential_data_detailed(
            credential_id=self.credential_id,
            user_id=self.user_id,
            new_data=new_data,
            metadata_updates=metadata_updates,
            pool=self.pool,
            expected_token_version=new_data.get("token_version"),
        )

    async def mark_revoked(self, conn, reason: str) -> str:
        """Stamp ``revoked_at`` (idempotent) on the row of record; returns the
        UPDATE tag. Runs on the audit pool's connection."""
        return await conn.execute(
            """
            UPDATE public.credentials
            SET revoked_at = NOW(),
                revoked_reason = $2
            WHERE id = $1::uuid AND revoked_at IS NULL
            """,
            self.credential_id,
            reason,
        )


class RotatedRefreshTokenMissing(ValueError):
    """A single-use-rotation provider's refresh response lacked a refresh_token.

    Persisting the just-consumed token would guarantee the NEXT refresh fails
    with invalid_grant (F05 silent rotation loss, surfacing days later as a
    bricked credential). Raising here turns that delayed silent brick into an
    immediate, attributable failure.
    """


class OAuthRefreshError(ValueError):
    """A token refresh could not be completed.

    Subclasses ``ValueError`` so every existing ``except ValueError`` /
    ``except Exception`` catch site (which stringify it into the tool/run error
    shown to the user) keeps working unchanged. The ``transient`` flag is the
    meaningful new signal: a transient network/transport failure means the
    saved credential is still valid and the run should simply be retried — NOT
    that the credential is broken. The old message ("OAuth token expired and
    refresh failed: ") collapsed both cases and routinely mis-blamed a healthy
    credential for a network blip.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str = "unknown",
        transient: bool = False,
        network_failure_kind: Optional[str] = None,
        provider_error_code: Optional[str] = None,
        attempts: int = 1,
    ):
        super().__init__(message)
        self.provider = provider
        self.transient = transient
        self.network_failure_kind = network_failure_kind
        self.provider_error_code = provider_error_code
        self.attempts = attempts


def require_rotated_refresh_token(token_data: Dict[str, Any], *, provider: str) -> str:
    """Extract the rotated refresh token from a rotation provider's response.

    Use in the ``refresh_access_token`` of providers whose refresh tokens are
    single-use (Slack, Twitter, Linear, Typeform, Supabase, TikTok, Canva) in
    place of the ``token_data.get("refresh_token", <consumed token>)`` fallback.
    Non-rotating providers (Google, GitHub, …) legitimately omit the field and
    must NOT use this.
    """
    new_token = token_data.get("refresh_token")
    if not new_token:
        raise RotatedRefreshTokenMissing(
            f"{provider} token-rotation response did not include a refresh_token; "
            f"refusing to keep the consumed single-use token"
        )
    return new_token


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """Return True if an ISO-8601 token expiry is within *buffer_minutes* of now.

    The per-provider ``is_token_expired`` functions are all this same check;
    nodes can pass their own, but this is the shared default.
    """
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True  # unparseable expiry — treat as expired
    return datetime.now(timezone.utc) >= expiry - timedelta(minutes=buffer_minutes)


def _adopt(credential: Dict[str, Any], tokens: Any) -> str:
    """Copy refreshed tokens into the credential dict; return the access token.

    *tokens* may be a provider token model (attributes) or a credential dict
    re-read from the database (keys)."""
    if isinstance(tokens, dict):
        access_token = tokens.get("access_token")
        expires_at = tokens.get("expires_at")
        refresh_token = tokens.get("refresh_token")
        scope = tokens.get("scope")
        token_type = tokens.get("token_type")
    else:
        access_token = tokens.access_token
        expires_at = getattr(tokens, "expires_at", None)
        refresh_token = getattr(tokens, "refresh_token", None)
        scope = getattr(tokens, "scope", None)
        token_type = getattr(tokens, "token_type", None)
    credential["access_token"] = access_token
    credential["expires_at"] = expires_at
    if refresh_token:
        credential["refresh_token"] = refresh_token
    if scope:
        credential["scope"] = scope
    if token_type:
        credential["token_type"] = token_type
    return access_token


def _adopt_keys(
    credential: Dict[str, Any],
    tokens: Any,
    *,
    access_token_key: str,
    refresh_token_key: str,
    expires_at_key: str,
    additional_token_fields: Tuple[str, ...] = (),
) -> str:
    """Copy token-model fields into provider-specific credential keys."""
    if isinstance(tokens, dict):
        # A DB re-read dict carries the SAME key names as the credential being
        # updated, so read STRICTLY by the provided key. The old
        # ``or tokens.get("access_token")`` fallback cross-contaminated a custom
        # key (Slack's user_access_token) with the bot token whenever the
        # custom field was empty in the re-read row.
        access_token = tokens.get(access_token_key)
        expires_at = tokens.get(expires_at_key)
        refresh_token = tokens.get(refresh_token_key)
        scope = tokens.get("scope")
        token_type = tokens.get("token_type")
    else:
        access_token = tokens.access_token
        expires_at = getattr(tokens, "expires_at", None)
        refresh_token = getattr(tokens, "refresh_token", None)
        scope = getattr(tokens, "scope", None)
        token_type = getattr(tokens, "token_type", None)

    credential[access_token_key] = access_token
    credential[expires_at_key] = expires_at
    if refresh_token:
        credential[refresh_token_key] = refresh_token
    if scope:
        credential["scope"] = scope
    if token_type:
        credential["token_type"] = token_type
    for field in additional_token_fields:
        if isinstance(tokens, dict):
            value = tokens.get(field) if field in tokens else None
        else:
            value = getattr(tokens, field, None)
        if value is not None:
            credential[field] = value
    return access_token


async def freshen_oauth_credential(
    credential_data: Optional[Dict[str, Any]],
    *,
    pool=None,
    user_id: Optional[str] = None,
    credential_id: Optional[str] = None,
    refresh: Callable[[str], Awaitable[Any]],
    is_expired: Callable[[str], bool] = is_token_expired,
    access_token_key: str = "access_token",
    refresh_token_key: str = "refresh_token",
    expires_at_key: str = "expires_at",
    additional_token_fields: Tuple[str, ...] = (),
    provider: str = "unknown",
    caller_path: str = "freshen",
) -> Optional[Dict[str, Any]]:
    """Refresh a single-token OAuth credential dict in place if it's expiring.

    The standard body for an OAuth node's ``freshen_credential`` override: it
    short-circuits to a no-op for credentials without a rotating refresh token
    (manual bot tokens, PATs, non-expiring tokens), so it's safe to call on any
    credential the node might hold. A None ``pool`` resolves lazily inside the
    store at first DB use. Mutates and returns the dict.
    """
    if not credential_data or not credential_data.get(refresh_token_key):
        return credential_data
    await ensure_fresh_oauth_token(
        pool=pool,
        credential_id=credential_id,
        user_id=user_id,
        credential=credential_data,
        refresh=refresh,
        is_expired=is_expired,
        access_token_key=access_token_key,
        refresh_token_key=refresh_token_key,
        expires_at_key=expires_at_key,
        additional_token_fields=additional_token_fields,
        provider=provider,
        caller_path=caller_path,
    )
    return credential_data


async def ensure_fresh_oauth_token(
    *,
    pool=None,
    credential_id: Optional[str],
    user_id: Optional[str],
    credential: Dict[str, Any],
    refresh: Callable[[str], Awaitable[Any]],
    is_expired: Callable[[str], bool] = is_token_expired,
    access_token_key: str = "access_token",
    refresh_token_key: str = "refresh_token",
    expires_at_key: str = "expires_at",
    additional_token_fields: Tuple[str, ...] = (),
    force_refresh: bool = False,
    provider: str = "unknown",
    caller_path: str = "unknown",
    store=None,
) -> str:
    """Return a valid OAuth access token, refreshing + persisting if expired.

    Args:
        pool: database pool (asyncpg-compatible).
        credential_id / user_id: identify the row to re-read and persist to;
            when either is missing the token is refreshed in memory only.
        credential: the decrypted credential dict — mutated in place with the
            refreshed tokens.
        is_expired: provider's ``is_token_expired(expires_at) -> bool``.
        refresh: provider's ``async refresh(refresh_token) -> token model`` with
            ``.access_token`` / ``.refresh_token`` / ``.expires_at``.
        additional_token_fields: explicitly approved provider metadata returned
            with a refresh (for example a rotated API/instance origin) that must
            be adopted and persisted with the token.
        force_refresh: refresh even if the current token is still valid. Used by
            Debug trigger tests to detect revoked/rotated refresh tokens before
            natural expiry. Skips both the not-expired short-circuit and the
            in-lock concurrent-refresh no-op. Inside a
            ``force_refresh_once_scope`` only the first force per token chain
            is honored.
        provider: tag emitted on the audit row / span (slack, google, ...).
        caller_path: where the refresh was initiated from (execute, freshen,
            dropdown, trigger_register, trigger_test, mcp, hydrate, propagate).
            Defaults to 'unknown' with a WARNING log so we can hunt callers.
        store: row-of-record adapter (load / persist / mark_revoked /
            lock_key). Defaults to the credentials table; the Slack workspace
            bot chain passes a ``SlackInstallationStore`` so the shared
            installation row is the single chain of record.
    """
    started_at = datetime.now(timezone.utc)
    if store is None and credential_id and user_id:
        store = CredentialsTableStore(pool, user_id, credential_id)
    if force_refresh and store is not None:
        seen = _FORCE_REFRESH_SEEN.get()
        if seen is not None:
            chain_key = (store.lock_key, refresh_token_key)
            if chain_key in seen:
                force_refresh = False
            else:
                seen.add(chain_key)
    # Fall back to the ambient caller_path set by an entry-point context
    # manager (trigger_test, mcp, hydrate, propagate, dropdown, ...) — saves
    # threading the kwarg through every freshen_credential override.
    if caller_path == "unknown":
        caller_path = current_caller_path()
    if caller_path == "unknown":
        logger.warning(
            "[oauth_refresh] caller_path='unknown' for provider=%s credential_id=%s "
            "— wrap the entry point in caller_path_scope(...) or pass caller_path explicitly",
            provider, credential_id,
        )

    builder = CredentialRefreshAuditBuilder(
        provider=provider,
        caller_path=caller_path,
        credential_id=credential_id,
        user_id=user_id,
        force_refresh=force_refresh,
        started_at=started_at,
    )
    builder.set_before_token(credential.get(refresh_token_key))
    builder.expires_at_before = _parse_iso8601(credential.get(expires_at_key))
    builder.scope_before = _sorted_scope(credential.get("scope"))

    with _tracer.start_as_current_span("oauth.refresh") as span:
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            builder.trace_id = format(ctx.trace_id, "032x")
            builder.span_id = format(ctx.span_id, "016x")
        try:
            return await _run_refresh(
                builder=builder,
                credential_id=credential_id,
                user_id=user_id,
                credential=credential,
                refresh=refresh,
                is_expired=is_expired,
                access_token_key=access_token_key,
                refresh_token_key=refresh_token_key,
                expires_at_key=expires_at_key,
                additional_token_fields=additional_token_fields,
                force_refresh=force_refresh,
                store=store,
            )
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            builder.finalise()
            for k, v in builder.to_span_attributes().items():
                try:
                    span.set_attribute(k, v)
                except Exception:
                    pass
            if builder.phase_outcome not in PhaseOutcome.SKIP_AUDIT and builder.credential_id:
                # Fire and forget — audit insert must NEVER raise back into the
                # caller, and the helper itself swallows. We still await so the
                # row lands before the span flushes, but bound the wait.
                try:
                    await asyncio.wait_for(
                        record_refresh_event(builder.to_audit_row()),
                        timeout=2.5,
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning("[oauth_refresh] audit insert skipped: %s", e)



async def _maybe_auto_revoke(**_kwargs: Any) -> None:
    """Compatibility hook; community installs do not auto-revoke from audit rows."""
    return None


async def _call_refresh(
    refresh: Callable[[str], Awaitable[Any]],
    token: str,
    builder: CredentialRefreshAuditBuilder,
) -> Any:
    """Call the provider's ``refresh(token)`` with a bounded per-attempt timeout,
    retrying transient transport failures with backoff.

    Records ``request_duration_ms`` (last attempt) and ``refresh_attempts`` on
    the builder. Re-raises the FINAL exception with its real type preserved, so
    the caller's classifier (``_classify_refresh_exception``) tags the audit row
    by the genuine failure mode. Never retries a ``ValueError`` (an HTTP-level
    provider rejection — deterministic, and for rotating providers a retry would
    only burn time, not rotations).
    """
    attempt = 0
    while True:
        attempt += 1
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                refresh(token), timeout=_REFRESH_ATTEMPT_TIMEOUT_S
            )
            builder.request_duration_ms = int((time.monotonic() - t0) * 1000)
            builder.refresh_attempts = attempt
            return result
        except Exception as exc:
            builder.request_duration_ms = int((time.monotonic() - t0) * 1000)
            builder.refresh_attempts = attempt
            if attempt < _REFRESH_MAX_ATTEMPTS and is_retryable_network_exception(exc):
                backoff = _REFRESH_RETRY_BACKOFF_S[
                    min(attempt - 1, len(_REFRESH_RETRY_BACKOFF_S) - 1)
                ]
                logger.warning(
                    "[oauth_refresh] transient refresh failure provider=%s "
                    "credential_id=%s attempt=%d/%d kind=%s — retrying in %.1fs",
                    builder.provider, builder.credential_id, attempt,
                    _REFRESH_MAX_ATTEMPTS, classify_httpx_exception(exc), backoff,
                )
                await asyncio.sleep(backoff)
                continue
            raise


def _classify_refresh_exception(
    builder: CredentialRefreshAuditBuilder, exc: Exception
) -> None:
    """Tag the audit builder by the genuine failure mode of a refresh exception.

    Shared by both refresh call sites so the store-less path classifies a
    provider 4xx as ``provider_4xx`` (it used to mislabel everything as
    ``network_error``). Provider modules raise ``ValueError`` for HTTP-level
    failures and let transport failures propagate as raw httpx/asyncio errors.
    """
    builder.provider_error_description = str(exc)
    if isinstance(exc, RotatedRefreshTokenMissing):
        builder.set_outcome(PhaseOutcome.PROVIDER_200_MISSING_FIELD, "F04")
    elif isinstance(exc, ValueError):
        builder.provider_error_code = _extract_provider_error_code(str(exc))
        builder.set_outcome(PhaseOutcome.PROVIDER_4XX, "F01")
    else:
        builder.network_failure_kind = classify_httpx_exception(exc)
        builder.set_outcome(
            PhaseOutcome.NETWORK_ERROR,
            "F08" if builder.network_failure_kind == NetworkFailureKind.TIMEOUT else "F09",
        )


def _build_refresh_failure(
    builder: CredentialRefreshAuditBuilder, exc: Exception
) -> OAuthRefreshError:
    """Build the user-facing refresh error from the classified outcome.

    A NETWORK_ERROR is transient (credential still valid — retry); anything else
    is a provider/credential rejection. The non-transient message keeps the
    "refresh failed" phrasing so log/alert greps still match.
    """
    provider = builder.provider or "the provider"
    if builder.phase_outcome == PhaseOutcome.NETWORK_ERROR:
        kind = builder.network_failure_kind or "network error"
        return OAuthRefreshError(
            f"Could not reach {provider}'s OAuth token endpoint to refresh the "
            f"access token after {builder.refresh_attempts} attempt(s) ({kind}). "
            f"This is a transient network error, not a credential problem — the "
            f"saved credential is still valid. Please retry.",
            provider=provider,
            transient=True,
            network_failure_kind=kind,
            attempts=builder.refresh_attempts,
        )
    detail = str(exc).strip()
    suffix = (
        " The credential may need to be reconnected."
        if builder.provider_error_code
        else ""
    )
    return OAuthRefreshError(
        f"{provider} OAuth token refresh failed" + (f": {detail}" if detail else "") + suffix,
        provider=provider,
        transient=False,
        provider_error_code=builder.provider_error_code,
        attempts=builder.refresh_attempts,
    )


async def _run_refresh(
    *,
    builder: CredentialRefreshAuditBuilder,
    credential_id: Optional[str],
    user_id: Optional[str],
    credential: Dict[str, Any],
    refresh: Callable[[str], Awaitable[Any]],
    is_expired: Callable[[str], bool],
    access_token_key: str,
    refresh_token_key: str,
    expires_at_key: str,
    additional_token_fields: Tuple[str, ...],
    force_refresh: bool,
    store,
) -> str:
    """Core refresh logic with the builder threaded through every branch.

    Split out from ``ensure_fresh_oauth_token`` so the span / audit ``finally``
    block stays small and we don't need a try-around-the-whole-function in
    Python's exception-eating ``async with`` style.
    """
    expires_at = credential.get(expires_at_key)
    access_token = credential.get(access_token_key)
    if not force_refresh and (not expires_at or not is_expired(expires_at)):
        # Token still valid — no refresh happens, no audit row emitted.
        builder.set_outcome(PhaseOutcome.IN_LOCK_NOOP_FRESH)
        return access_token

    refresh_token = credential.get(refresh_token_key)
    if not refresh_token:
        builder.set_outcome(PhaseOutcome.NO_REFRESH_TOKEN, "F24")
        raise ValueError("OAuth token expired and no refresh token is available")

    # Without a store we can't lock, re-read, or persist — refresh in
    # memory for this execution only. NOTE: for a rotating provider this
    # consumes a single-use refresh token whose successor is never saved; it is
    # only safe because every production caller (execute via node_data, every
    # load path) supplies credential_id + user_id. See the audit follow-up.
    if store is None:
        logger.warning(
            "[oauth_refresh] refreshed token not persisted (missing credential_id/user_id)"
        )
        try:
            tokens = await _call_refresh(refresh, refresh_token, builder)
        except Exception as e:
            _classify_refresh_exception(builder, e)
            raise _build_refresh_failure(builder, e) from e
        builder.set_outcome(PhaseOutcome.UNPERSISTED_NO_IDS, "F18")
        return _adopt_keys(
            credential, tokens,
            access_token_key=access_token_key,
            refresh_token_key=refresh_token_key,
            expires_at_key=expires_at_key,
            additional_token_fields=additional_token_fields,
        )

    lock = _refresh_locks.setdefault(store.lock_key, asyncio.Lock())
    t_lock_wait = time.monotonic()
    async with lock:
        builder.lock_wait_ms = int((time.monotonic() - t_lock_wait) * 1000)

        # Another execution in this process may have just refreshed — trust the
        # database row of record before deciding to refresh again.
        fresh = await store.load()
        if fresh:
            builder.in_lock_reread_updated_at = _parse_iso8601(fresh.get("updated_at"))
            if not builder.loaded_updated_at:
                builder.loaded_updated_at = builder.in_lock_reread_updated_at
        if (
            not force_refresh
            and fresh
            and fresh.get(expires_at_key)
            and not is_expired(fresh[expires_at_key])
        ):
            builder.set_outcome(PhaseOutcome.IN_LOCK_NOOP_FRESH, "F11")
            builder.set_after_token(fresh.get(refresh_token_key))
            builder.expires_at_after = _parse_iso8601(fresh.get(expires_at_key))
            return _adopt_keys(
                credential, fresh,
                access_token_key=access_token_key,
                refresh_token_key=refresh_token_key,
                expires_at_key=expires_at_key,
                additional_token_fields=additional_token_fields,
            )

        # Adopt the DB row of record before refreshing so we submit the latest
        # rotated refresh token (another container may have rotated it).
        if fresh:
            credential.update(fresh)
        current_refresh = credential.get(refresh_token_key) or refresh_token
        builder.set_before_token(current_refresh)
        # Bounded per-attempt timeout + retry of transient transport failures
        # (see _call_refresh). The classification below sees the FINAL exception
        # with its real type, so a retried-then-still-failing timeout is tagged
        # network_error / F08, not provider_4xx.
        try:
            tokens = await _call_refresh(refresh, current_refresh, builder)
        except Exception as e:
            _classify_refresh_exception(builder, e)

            # A concurrent refresh on another container may have consumed this
            # rotating refresh token — re-read once and use what it persisted.
            retry = await store.load()
            if retry:
                builder.retry_reread_updated_at = _parse_iso8601(retry.get("updated_at"))
            if (
                retry
                and (
                    retry.get(access_token_key) != access_token
                    or retry.get(refresh_token_key) != current_refresh
                )
                and retry.get(expires_at_key)
                and not is_expired(retry[expires_at_key])
            ):
                builder.set_outcome(PhaseOutcome.REUSED_DB_VALUE_AFTER_FAILURE, "F12")
                builder.set_after_token(retry.get(refresh_token_key))
                builder.expires_at_after = _parse_iso8601(retry.get(expires_at_key))
                return _adopt_keys(
                    credential, retry,
                    access_token_key=access_token_key,
                    refresh_token_key=refresh_token_key,
                    expires_at_key=expires_at_key,
                    additional_token_fields=additional_token_fields,
                )
            raise _build_refresh_failure(builder, e) from e

        token = _adopt_keys(
            credential, tokens,
            access_token_key=access_token_key,
            refresh_token_key=refresh_token_key,
            expires_at_key=expires_at_key,
            additional_token_fields=additional_token_fields,
        )
        builder.set_after_token(credential.get(refresh_token_key))
        builder.expires_at_after = _parse_iso8601(credential.get(expires_at_key))
        builder.scope_after = _sorted_scope(credential.get("scope"))
        # Best-effort expires_in derivation — most provider models don't expose
        # it directly post-adopt, but it's recoverable from expires_at.
        if builder.expires_at_after:
            delta = (builder.expires_at_after - datetime.now(timezone.utc)).total_seconds()
            builder.expires_in_seconds = max(0, int(delta))

        metadata_updates = {
            expires_at_key: credential.get(expires_at_key),
            "last_refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        rows_affected, error_class = await store.persist(
            {**credential}, metadata_updates
        )
        if rows_affected <= 0 and error_class is None:
            # CAS guard lost (or row deleted). A concurrent writer landed
            # between our in-lock re-read and the persist — but OUR refresh
            # already consumed a single-use rotating token, so its successor
            # must not be dropped. Re-read the winner's row, overlay only the
            # token fields we just minted, and retry once against the new
            # version. Any non-token fields the winner wrote (e.g. Slack
            # user_* keys from a user-chain refresh) survive the merge.
            conflict_row = await store.load()
            if conflict_row is not None:
                merged = dict(conflict_row)
                merged[access_token_key] = credential.get(access_token_key)
                merged[expires_at_key] = credential.get(expires_at_key)
                if credential.get(refresh_token_key):
                    merged[refresh_token_key] = credential.get(refresh_token_key)
                for k in ("scope", "token_type"):
                    if credential.get(k):
                        merged[k] = credential[k]
                for field in additional_token_fields:
                    if credential.get(field) is not None:
                        merged[field] = credential[field]
                rows_affected, error_class = await store.persist(
                    merged, metadata_updates
                )
                if rows_affected > 0:
                    credential.update(merged)
                else:
                    builder.set_outcome(PhaseOutcome.PERSIST_VERSION_CONFLICT, "F17")
                    logger.error(
                        "[oauth_refresh.bricked] credential_id=%s provider=%s "
                        "prefix_before=%s prefix_after=%s persist_error=version_conflict_twice",
                        credential_id, builder.provider,
                        builder.refresh_token_prefix_before, builder.refresh_token_prefix_after,
                    )
                    raise ValueError(
                        f"OAuth token refreshed but a concurrent writer kept winning "
                        f"the persist for credential {credential_id}; aborting so the "
                        f"consumed refresh token isn't silently lost"
                    )
        builder.persist_rows_affected = rows_affected
        builder.persist_error_class = error_class
        if rows_affected <= 0:
            # The refresh just consumed a single-use rotating refresh token. If
            # the rotated successor isn't saved, the next refresh submits the
            # already-revoked token and bricks the credential. Fail loudly
            # rather than hand back a token whose successor was lost. The
            # ERROR log here is the SIGKILL/OTel-down backstop — survives even
            # if the audit pool can't flush.
            if error_class:
                builder.set_outcome(PhaseOutcome.PERSIST_FAILED, "F17")
            else:
                builder.set_outcome(PhaseOutcome.PERSIST_ZERO_ROWS, "F39")
            logger.error(
                "[oauth_refresh.bricked] credential_id=%s provider=%s "
                "prefix_before=%s prefix_after=%s persist_error=%s rows_affected=%d",
                credential_id, builder.provider,
                builder.refresh_token_prefix_before, builder.refresh_token_prefix_after,
                error_class, rows_affected,
            )
            raise ValueError(
                f"OAuth token refreshed but the rotated credential could not be "
                f"persisted (credential {credential_id}); aborting so the "
                f"consumed refresh token isn't silently lost"
            )

        builder.set_outcome(PhaseOutcome.REFRESHED)
        if builder.expires_in_seconds is not None and builder.expires_in_seconds <= 60:
            # Provider returned an already-expired (or about-to-expire) token —
            # caller will refresh again on the very next call (F28).
            builder.failure_mode_id = "F28"
        if builder.scope_downgraded:
            builder.failure_mode_id = "F35"
        return token


# Best-effort extraction of a provider error code from the ValueError message
# raised by per-provider refresh modules. Each provider's refresh_access_token
# already includes the upstream error string verbatim, so a simple keyword
# search is enough for the common cases and degrades gracefully to None.
_PROVIDER_ERROR_TOKENS = (
    "invalid_grant",
    "invalid_refresh_token",
    "invalid_client",
    "unauthorized_client",
    "invalid_request",
    "invalid_scope",
    "unsupported_grant_type",
    "token_revoked",
    "account_inactive",
    "org_login_required",
    "user_not_found",
    "account_disabled",
    "account_deleted",
)


def _extract_provider_error_code(message: str) -> Optional[str]:
    if not message:
        return None
    lower = message.lower()
    for token in _PROVIDER_ERROR_TOKENS:
        if token in lower:
            return token
    return None


