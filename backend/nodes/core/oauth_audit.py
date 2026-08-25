"""Structured telemetry for OAuth credential refreshes.

``CredentialRefreshAuditBuilder`` accumulates one attempt and emits both
OpenTelemetry attributes and an optional installation-local audit record.
The outcome vocabulary is provider-independent so operators can alert without
matching provider error-message text.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from utils.runtime_identity import instance_id, process_pid

logger = logging.getLogger(__name__)

# Ambient caller_path. Entry points (mcp_server, workflow dropdown loader,
# trigger-test lifecycle, slack hydrate/propagate) set this via the
# ``caller_path_scope`` context manager so refreshes triggered inside their
# call tree carry the right tag without threading a kwarg through every
# freshen_credential override.
_caller_path_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "oauth_caller_path", default="unknown"
)


def current_caller_path() -> str:
    """Return the ambient caller_path, falling back to ``'unknown'``."""
    return _caller_path_var.get()


@contextmanager
def caller_path_scope(value: str) -> Iterator[None]:
    """Set the ambient caller_path for the duration of a ``with`` block.

    Use at every entry point that initiates a credential load + freshen:

        with caller_path_scope("trigger_test"):
            await ensure_fresh_oauth_token(...)

    Nested scopes restore the previous value on exit.
    """
    token = _caller_path_var.set(value)
    try:
        yield
    finally:
        _caller_path_var.reset(token)


class PhaseOutcome:
    """Terminal classification of a refresh attempt. Set on EVERY exit site."""

    # Success paths.
    REFRESHED = "refreshed"
    IN_LOCK_NOOP_FRESH = "in_lock_noop_fresh"
    REUSED_DB_VALUE_AFTER_FAILURE = "reused_db_value_after_failure"

    # Provider-response failures.
    PROVIDER_4XX = "provider_4xx"
    PROVIDER_5XX = "provider_5xx"
    PROVIDER_429 = "provider_429"
    PROVIDER_200_OK_FALSE = "provider_200_ok_false"
    PROVIDER_200_MISSING_FIELD = "provider_200_missing_field"
    ENDPOINT_404 = "endpoint_404"

    # Network failures.
    NETWORK_ERROR = "network_error"

    # Persistence failures.
    PERSIST_FAILED = "persist_failed"
    PERSIST_ZERO_ROWS = "persist_zero_rows"
    # CAS guard lost twice in a row — a concurrent writer kept winning between
    # our re-read and persist. The refreshed token was NOT saved (same severity
    # as persist_failed: a rotated single-use successor may be lost).
    PERSIST_VERSION_CONFLICT = "persist_version_conflict"

    # Caller / state failures.
    NO_REFRESH_TOKEN = "no_refresh_token"
    UNPERSISTED_NO_IDS = "unpersisted_no_ids"
    CLOCK_PARSE_ERROR = "clock_parse_error"
    CLIENT_CONFIG_MISSING = "client_config_missing"
    DECRYPT_FAILED = "decrypt_failed"
    SCOPE_DOWNGRADE = "scope_downgrade"

    # Slack sibling-installation token movement — NOT an OAuth refresh (no
    # refresh-token exchange), but a structurally similar credential mutation
    # that must be visible in the same audit for cross-credential race
    # detection (F15 hydrate-then-rotated, F16 propagate race).
    SIBLING_HYDRATED = "sibling_hydrated"      # this credential adopted a sibling's token
    SIBLING_PROPAGATED = "sibling_propagated"  # this credential pushed its token to a sibling
    SIBLING_HYDRATE_FAILED = "sibling_hydrate_failed"
    SIBLING_PROPAGATE_FAILED = "sibling_propagate_failed"

    # Outcomes we don't bother writing audit rows for (success no-ops).
    SKIP_AUDIT = frozenset({IN_LOCK_NOOP_FRESH})


class NetworkFailureKind:
    """Structured network-failure classification, set at the raise site so
    Honeycomb queries never need to regex ``error.message``."""

    TIMEOUT = "timeout"
    DNS = "dns"
    TLS = "tls"
    CONNECTION_REFUSED = "connection_refused"
    IP_BLOCKED = "ip_blocked"
    OTHER = "other"


# Caller-path tags — closed set, threaded as a kwarg from each entry point.
CALLER_PATHS = frozenset({
    "execute",          # workflow node execute path (user clicks Run, agent tool downstream, setup flow)
    "mcp_execute",      # MCP run_workflow / run_nodes — AI-builder-initiated execute
    "freshen",          # WorkflowNode.freshen_credential default (no caller sub-tag)
    "dropdown",         # dynamic options / dropdown load
    "manual_refresh",   # user clicks "Refresh token" on a credential detail page
    "trigger_register", # trigger registration at save time
    "trigger_renew",    # hourly cron renewing watch channels / webhook subscriptions
    "trigger_test",     # Debug trigger test (force_refresh=True path AND oauth_refresh category)
    "mcp",              # MCP dropdown / autoselect / dynamic option load
    "hydrate",          # Slack sibling hydrate (workspace bot-token rotation pull-from-sibling)
    "propagate",        # Slack sibling propagate (workspace bot-token rotation push-to-sibling)
    "unknown",          # default — emits a WARNING so we can hunt down the caller
})


def fingerprint_token(token: Optional[str]) -> Optional[str]:
    """Return a non-reversible token fingerprint suitable for logs / audit.

    Format: ``{first 8 chars}:{first 8 hex of sha256}``. Long enough to chain
    rotations across rows; short enough that an accidental log scrape doesn't
    leak token material. Never returns the raw token. Returns ``None`` for
    falsy input so callers can pass token-or-None freely.
    """
    if not token:
        return None
    try:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
        return f"{token[:8]}:{digest}"
    except Exception:
        return None


def _parse_iso8601(value: Any) -> Optional[datetime]:
    """Best-effort ISO-8601 parse for audit columns. Returns ``None`` on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _truncate(value: Optional[str], limit: int = 500) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= limit else s[:limit]


def _sorted_scope(scope: Optional[str]) -> Optional[str]:
    """Comma-joined sorted scope list — comparable across rows for downgrade
    detection (F35) without caring about provider-specific ordering."""
    if not scope:
        return None
    parts = [p.strip() for p in scope.replace(",", " ").split() if p.strip()]
    if not parts:
        return None
    return ",".join(sorted(set(parts)))


@dataclass
class CredentialRefreshAuditBuilder:
    """Mutable builder accumulated through one ``ensure_fresh_oauth_token`` call.

    Only ``provider`` + ``credential_id`` + ``caller_path`` are required up
    front; everything else is filled in as state is learned. ``finalise``
    stamps ``ended_at`` and is idempotent so multiple terminal sites can call
    it safely.
    """

    # Required at construction.
    provider: str
    caller_path: str
    credential_id: Optional[str]
    user_id: Optional[str]
    force_refresh: bool
    started_at: datetime

    # Honeycomb correlation — filled by oauth_refresh from the active span.
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    # Filled progressively.
    phase_outcome: str = "unknown"
    failure_mode_id: Optional[str] = None
    ended_at: Optional[datetime] = None
    lock_wait_ms: Optional[int] = None

    loaded_updated_at: Optional[datetime] = None
    in_lock_reread_updated_at: Optional[datetime] = None
    retry_reread_updated_at: Optional[datetime] = None

    refresh_token_prefix_before: Optional[str] = None
    refresh_token_prefix_after: Optional[str] = None

    expires_at_before: Optional[datetime] = None
    expires_at_after: Optional[datetime] = None
    expires_in_seconds: Optional[int] = None

    scope_before: Optional[str] = None
    scope_after: Optional[str] = None

    token_kind_refreshed: Optional[str] = None
    user_expires_at_after: Optional[datetime] = None

    http_status: Optional[int] = None
    http_response_ok_flag: Optional[bool] = None
    provider_error_code: Optional[str] = None
    provider_error_description: Optional[str] = None
    response_body_kind: Optional[str] = None

    network_failure_kind: Optional[str] = None
    request_duration_ms: Optional[int] = None
    # Number of times the provider refresh call was attempted (>1 means a
    # transient transport failure was retried). Surfaced for "how often does
    # retry save us" analysis; folded into the audit row's metadata.
    refresh_attempts: int = 1

    client_id_fingerprint: Optional[str] = None
    instance_url: Optional[str] = None

    persist_rows_affected: Optional[int] = None
    persist_error_class: Optional[str] = None

    concurrent_writer_credential_id: Optional[str] = None
    sibling_team_id: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience setters — keep the call sites in oauth_refresh.py terse.
    # ------------------------------------------------------------------

    def set_outcome(self, outcome: str, failure_mode_id: Optional[str] = None) -> None:
        """Set ``phase_outcome`` + optional F-id. Last write wins."""
        self.phase_outcome = outcome
        if failure_mode_id is not None:
            self.failure_mode_id = failure_mode_id

    def set_before_token(self, token: Optional[str]) -> None:
        self.refresh_token_prefix_before = fingerprint_token(token)

    def set_after_token(self, token: Optional[str]) -> None:
        self.refresh_token_prefix_after = fingerprint_token(token)

    @property
    def rotation_observed(self) -> Optional[bool]:
        if self.refresh_token_prefix_before is None or self.refresh_token_prefix_after is None:
            return None
        return self.refresh_token_prefix_before != self.refresh_token_prefix_after

    @property
    def scope_downgraded(self) -> Optional[bool]:
        if self.scope_before is None or self.scope_after is None:
            return None
        before = set(self.scope_before.split(",")) if self.scope_before else set()
        after = set(self.scope_after.split(",")) if self.scope_after else set()
        return bool(after) and after < before  # strict subset

    def finalise(self) -> None:
        """Stamp ``ended_at`` if unset. Idempotent."""
        if self.ended_at is None:
            self.ended_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Output shapes.
    # ------------------------------------------------------------------

    def to_span_attributes(self) -> Dict[str, Any]:
        """Span attribute dict for the ``oauth.refresh`` span.

        Only non-None values are emitted — OTel attribute values must be
        non-None primitives (str/int/float/bool/seq). Datetimes are stringified
        as ISO-8601.
        """
        def _iso(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt is not None else None

        attrs: Dict[str, Any] = {
            "oauth.provider": self.provider,
            "oauth.caller_path": self.caller_path,
            "oauth.credential_id": self.credential_id,
            "oauth.user_id": self.user_id,
            "oauth.force_refresh": self.force_refresh,
            "service.instance.id": instance_id(),
            "process.pid": process_pid(),
            "oauth.refresh.outcome": self.phase_outcome,
            "oauth.failure_mode_id": self.failure_mode_id,
            "oauth.lock.wait_ms": self.lock_wait_ms,
            "oauth.lock.contended": (self.lock_wait_ms or 0) > 0 if self.lock_wait_ms is not None else None,
            "oauth.refresh_token.prefix_before": self.refresh_token_prefix_before,
            "oauth.refresh_token.prefix_after": self.refresh_token_prefix_after,
            "oauth.rotation_observed": self.rotation_observed,
            "oauth.expires_at_before": _iso(self.expires_at_before),
            "oauth.expires_at_after": _iso(self.expires_at_after),
            "oauth.expires_in_seconds": self.expires_in_seconds,
            "oauth.scope_before": self.scope_before,
            "oauth.scope_after": self.scope_after,
            "oauth.scope_downgraded": self.scope_downgraded,
            "oauth.token_kind_refreshed": self.token_kind_refreshed,
            "oauth.user_expires_at_after": _iso(self.user_expires_at_after),
            "oauth.client_id_fingerprint": self.client_id_fingerprint,
            "oauth.instance_url": self.instance_url,
            "http.status_code": self.http_status,
            "http.response_ok_flag": self.http_response_ok_flag,
            "http.response_body_kind": self.response_body_kind,
            "oauth.provider_error_code": self.provider_error_code,
            "oauth.provider_error_description": self.provider_error_description,
            "oauth.network_failure_kind": self.network_failure_kind,
            "oauth.refresh.attempts": self.refresh_attempts if self.refresh_attempts > 1 else None,
            "http.request.duration_ms": self.request_duration_ms,
            "oauth.db.loaded_updated_at": _iso(self.loaded_updated_at),
            "oauth.db.in_lock_reread_updated_at": _iso(self.in_lock_reread_updated_at),
            "oauth.db.retry_reread_updated_at": _iso(self.retry_reread_updated_at),
            "oauth.db.persist_rows_affected": self.persist_rows_affected,
            "oauth.db.persist_error_class": self.persist_error_class,
            "oauth.sibling_team_id": self.sibling_team_id,
            "oauth.concurrent_writer_credential_id": self.concurrent_writer_credential_id,
        }
        return {k: v for k, v in attrs.items() if v is not None}

    def to_audit_row(self) -> Dict[str, Any]:
        """Return the optional installation-local refresh audit record."""
        rotation = self.rotation_observed
        return {
            "ts": datetime.now(timezone.utc),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "credential_id": self.credential_id,
            "user_id": self.user_id,
            "provider": self.provider,
            "container_id": instance_id(),
            "process_pid": process_pid(),
            "caller_path": self.caller_path,
            "force_refresh": self.force_refresh,
            "phase_outcome": self.phase_outcome,
            "failure_mode_id": self.failure_mode_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at or datetime.now(timezone.utc),
            "lock_wait_ms": self.lock_wait_ms,
            "loaded_updated_at": self.loaded_updated_at,
            "in_lock_reread_updated_at": self.in_lock_reread_updated_at,
            "retry_reread_updated_at": self.retry_reread_updated_at,
            "refresh_token_prefix_before": self.refresh_token_prefix_before,
            "refresh_token_prefix_after": self.refresh_token_prefix_after,
            "rotation_observed": rotation,
            "expires_at_before": self.expires_at_before,
            "expires_at_after": self.expires_at_after,
            "expires_in_seconds": self.expires_in_seconds,
            "scope_before": self.scope_before,
            "scope_after": self.scope_after,
            "token_kind_refreshed": self.token_kind_refreshed,
            "user_expires_at_after": self.user_expires_at_after,
            "http_status": self.http_status,
            "http_response_ok_flag": self.http_response_ok_flag,
            "provider_error_code": self.provider_error_code,
            "provider_error_description": _truncate(self.provider_error_description),
            "response_body_kind": self.response_body_kind,
            "network_failure_kind": self.network_failure_kind,
            "request_duration_ms": self.request_duration_ms,
            "client_id_fingerprint": self.client_id_fingerprint,
            "instance_url": self.instance_url,
            "persist_rows_affected": self.persist_rows_affected,
            "persist_error_class": self.persist_error_class,
            "concurrent_writer_credential_id": self.concurrent_writer_credential_id,
            "sibling_team_id": self.sibling_team_id,
            "metadata": {
                **(self.metadata or {}),
                **({"refresh_attempts": self.refresh_attempts} if self.refresh_attempts > 1 else {}),
            },
        }


def classify_httpx_exception(exc: BaseException) -> str:
    """Map an httpx / asyncio exception to a ``NetworkFailureKind`` tag.

    Done at the raise site so Honeycomb queries can filter on
    ``oauth.network_failure_kind`` without regex-matching ``error.message``.
    """
    name = exc.__class__.__name__
    msg = str(exc).lower()
    # httpx exceptions — avoid importing httpx to keep this importable from
    # contexts where httpx may not be available.
    if name in {"TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"}:
        return NetworkFailureKind.TIMEOUT
    if "timeout" in name.lower() or "timed out" in msg:
        return NetworkFailureKind.TIMEOUT
    if "ssl" in name.lower() or "tls" in name.lower() or "certificate" in msg:
        return NetworkFailureKind.TLS
    if "name or service not known" in msg or "nodename nor servname" in msg or "dns" in name.lower():
        return NetworkFailureKind.DNS
    if "connection refused" in msg:
        return NetworkFailureKind.CONNECTION_REFUSED
    return NetworkFailureKind.OTHER


# Transport-layer exception class names safe to retry: the request either never
# reached the provider or its response was lost, so re-issuing it is harmless
# (non-rotating providers) or no worse than the original failure (rotating
# providers — a lost rotation already bricks the credential whether or not we
# retry, and a re-submitted dead token just yields a deterministic 4xx). Matched
# by class name to avoid importing httpx here (see classify_httpx_exception).
_RETRYABLE_TRANSPORT_EXC_NAMES = frozenset({
    "TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
    "ConnectError", "ReadError", "WriteError", "NetworkError", "TransportError",
    "RemoteProtocolError", "ProxyError",
    "TimeoutError",  # builtin / asyncio.TimeoutError (raised by asyncio.wait_for)
    # Raw OS-level connection errors (httpx normally wraps these in ConnectError,
    # but cover them in case one propagates unwrapped).
    "ConnectionError", "ConnectionResetError", "ConnectionRefusedError", "ConnectionAbortedError",
})


def is_retryable_network_exception(exc: BaseException) -> bool:
    """True if *exc* is a transient transport failure worth retrying.

    The per-provider ``refresh_access_token`` modules raise ``ValueError`` for
    every HTTP-level failure (4xx/5xx, missing rotation field) — those are
    deterministic provider responses, never retried. Genuine transport failures
    (timeouts, connect/read errors) propagate as raw httpx / asyncio exceptions
    and ARE retried with backoff by the refresh choke point.
    """
    if isinstance(exc, ValueError):
        return False
    if exc.__class__.__name__ in _RETRYABLE_TRANSPORT_EXC_NAMES:
        return True
    return classify_httpx_exception(exc) in {
        NetworkFailureKind.TIMEOUT,
        NetworkFailureKind.DNS,
        NetworkFailureKind.CONNECTION_REFUSED,
    }
