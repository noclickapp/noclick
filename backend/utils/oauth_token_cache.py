"""Secret-safe primitives for process-local OAuth access-token caches."""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any


DEFAULT_MISSING_EXPIRY_TTL_SECONDS = 300.0


def oauth_authority_digest(**authority: object) -> str:
    """Hash every input that determines a token's authority.

    Callers must include secrets as well as public identity fields. Only the
    canonical SHA-256 digest is retained as the cache key, so cache metadata
    never contains raw client secrets or user passwords.
    """
    canonical = json.dumps(
        authority,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class OAuthTokenCache:
    """Small process-local LRU cache that refreshes safely before expiry."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
        refresh_skew_seconds: float = 60.0,
        missing_expiry_ttl_seconds: float = DEFAULT_MISSING_EXPIRY_TTL_SECONDS,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if refresh_skew_seconds < 0:
            raise ValueError("refresh_skew_seconds must be non-negative")
        if missing_expiry_ttl_seconds <= 0:
            raise ValueError("missing_expiry_ttl_seconds must be positive")
        self._max_entries = max_entries
        self._refresh_skew_seconds = float(refresh_skew_seconds)
        self._missing_expiry_ttl_seconds = float(missing_expiry_ttl_seconds)
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def get(self, key: str, *, now: float) -> str | None:
        self._purge_stale(now)
        cached = self._entries.get(key)
        if cached is None:
            return None
        token, _refresh_at = cached
        self._entries.move_to_end(key)
        return token

    def put(
        self,
        key: str,
        token: str,
        *,
        expires_in: object,
        now: float,
    ) -> None:
        self._purge_stale(now)
        ttl = self._ttl_seconds(expires_in)
        if ttl is None:
            self._entries.pop(key, None)
            return

        # Retain the configured skew for normal long-lived tokens. For very
        # short or fallback lifetimes, refresh halfway through rather than
        # making the cache immediately unusable.
        skew = min(self._refresh_skew_seconds, ttl / 2)
        refresh_at = now + ttl - skew
        if refresh_at <= now:
            self._entries.pop(key, None)
            return

        self._entries[key] = (token, refresh_at)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def keys(self) -> tuple[str, ...]:
        """Expose only the digested cache keys for diagnostics and tests."""
        return tuple(self._entries.keys())

    def __len__(self) -> int:
        return len(self._entries)

    def _ttl_seconds(self, expires_in: object) -> float | None:
        if expires_in is None:
            return self._missing_expiry_ttl_seconds
        if isinstance(expires_in, bool):
            return None
        try:
            ttl = float(expires_in)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(ttl) or ttl <= 0:
            return None
        return ttl

    def _purge_stale(self, now: float) -> None:
        stale = [
            key
            for key, (_token, refresh_at) in self._entries.items()
            if now >= refresh_at
        ]
        for key in stale:
            self._entries.pop(key, None)


def token_expiry_input(payload: Mapping[str, Any]) -> object:
    """Return provider expiry metadata, or ``None`` for the safe fallback TTL."""
    return payload.get("expires_in")
