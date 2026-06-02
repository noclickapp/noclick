"""Deterministic canonical serialization + content hashing for the CAS.

Every CAS blob is keyed by sha256 over a canonical byte encoding of its content,
so identical content always hashes identically regardless of dict key order —
that identity is the whole basis of deduplication. The canonical form is JSON:

  - object keys sorted lexicographically (deterministic ordering)
  - compact separators (no insignificant whitespace)
  - non-ASCII emitted as raw UTF-8 (``ensure_ascii=False``)
  - NaN / Infinity rejected (not valid JSON)
  - non-JSON-native values rejected — there is NO ``default=str`` fallback,
    because a ``<object at 0x…>`` repr is non-deterministic and would silently
    churn the hash. A node output that isn't JSON-serializable is a node bug to
    surface (per the repo's no-silent-fallback rule), not to paper over.

This is the single choke point for the canonical form: change it here and the
whole CAS stays consistent. It targets internal determinism (same content → same
hash), not byte-for-byte RFC 8785 interop, which we never need.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class NonCanonicalizableError(TypeError):
    """Raised when a value cannot be deterministically canonicalized to JSON."""


def canonicalize(value: Any) -> bytes:
    """Return the canonical UTF-8 byte encoding of ``value``.

    Raises NonCanonicalizableError for non-JSON-native values (no fallback) and
    for non-finite numbers (NaN/Infinity).
    """
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise NonCanonicalizableError(
            f"value is not canonicalizable as JSON: {exc}"
        ) from exc
    return text.encode("utf-8")


def hash_bytes(data: bytes) -> str:
    """sha256 hex of already-canonical bytes (the CAS key / R2 object key)."""
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """sha256 hex of ``value``'s canonical encoding."""
    return hash_bytes(canonicalize(value))
