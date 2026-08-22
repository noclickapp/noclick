"""Security primitives shared by Google service-account integrations."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Sequence

from utils.ssrf import SSRFError


GOOGLE_SERVICE_ACCOUNT_TOKEN_URL = "https://oauth2.googleapis.com/token"


def require_google_service_account_token_uri(token_uri: object) -> str:
    """Return Google's token URL only when the credential contains it exactly.

    Service-account JSON is credential input, not trusted configuration.  A
    caller must run this check before signing a JWT or attaching the assertion
    to an outbound request. Exact equality intentionally rejects alternate
    schemes, ports, paths, queries, userinfo, and lookalike hostnames.
    """
    if token_uri != GOOGLE_SERVICE_ACCOUNT_TOKEN_URL:
        raise SSRFError(
            "Google service-account token_uri must be exactly "
            f"{GOOGLE_SERVICE_ACCOUNT_TOKEN_URL}"
        )
    return GOOGLE_SERVICE_ACCOUNT_TOKEN_URL


def normalize_google_service_account_private_key(private_key: str) -> str:
    """Normalize the two PEM encodings accepted by credential forms."""
    return str(private_key or "").replace("\\n", "\n").strip()


def google_service_account_authority_key(
    *,
    private_key: str,
    client_email: str,
    token_uri: str,
    scopes: Sequence[str],
    project_id: str | None,
    private_key_id: str | None,
) -> str:
    """Hash every field that can change a cached token's authority.

    Only the SHA-256 digest is retained as a cache key; private key material is
    never exposed through cache metadata or logs.
    """
    authority = {
        "client_email": str(client_email),
        "private_key": normalize_google_service_account_private_key(private_key),
        "private_key_id": private_key_id,
        "project_id": project_id,
        "scopes": list(scopes),
        "token_uri": token_uri,
    }
    canonical = json.dumps(
        authority, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BoundedTTLTokenCache:
    """Small process-local LRU cache with an expiry refresh buffer."""

    def __init__(self, *, max_entries: int = 256, refresh_skew_seconds: int = 300):
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._refresh_skew_seconds = refresh_skew_seconds
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def get(self, key: str, *, now: float) -> str | None:
        self._purge_stale(now)
        cached = self._entries.get(key)
        if cached is None:
            return None
        self._entries.move_to_end(key)
        return cached[0]

    def put(self, key: str, token: str, *, expires_at: float, now: float) -> None:
        self._purge_stale(now)
        if now >= expires_at - self._refresh_skew_seconds:
            return
        self._entries[key] = (token, expires_at)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def _purge_stale(self, now: float) -> None:
        stale = [
            key
            for key, (_, expiry) in self._entries.items()
            if now >= expiry - self._refresh_skew_seconds
        ]
        for key in stale:
            self._entries.pop(key, None)
