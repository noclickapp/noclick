"""Unit tests for backend/utils/cas/canonical.py — the CAS canonical form + hash.

Pure functions, no DB/R2. These pin the dedup invariant: identical content →
identical hash regardless of key order, and non-canonicalizable inputs raise.
"""

import hashlib
import math

import pytest

from utils.cas.canonical import (
    NonCanonicalizableError,
    canonicalize,
    content_hash,
    hash_bytes,
)


class TestCanonicalize:
    def test_key_order_invariant(self):
        assert canonicalize({"b": 1, "a": 2}) == canonicalize({"a": 2, "b": 1})

    def test_nested_key_order_invariant(self):
        a = {"x": {"q": 1, "p": 2}, "y": [{"n": 1, "m": 2}]}
        b = {"y": [{"m": 2, "n": 1}], "x": {"p": 2, "q": 1}}
        assert canonicalize(a) == canonicalize(b)
        assert content_hash(a) == content_hash(b)

    def test_compact_no_whitespace(self):
        assert canonicalize({"a": 1, "b": [1, 2]}) == b'{"a":1,"b":[1,2]}'

    def test_unicode_raw_utf8_not_escaped(self):
        out = canonicalize({"k": "héllo 🚀"})
        assert "🚀".encode("utf-8") in out
        assert b"\\u" not in out  # not ASCII-escaped

    def test_list_order_is_significant(self):
        assert canonicalize([1, 2]) != canonicalize([2, 1])

    def test_reject_non_serializable_value(self):
        with pytest.raises(NonCanonicalizableError):
            canonicalize({"k": object()})

    def test_reject_nan(self):
        with pytest.raises(NonCanonicalizableError):
            canonicalize({"k": math.nan})

    def test_reject_infinity(self):
        with pytest.raises(NonCanonicalizableError):
            canonicalize({"k": math.inf})


class TestContentHash:
    def test_is_64_lowercase_hex(self):
        h = content_hash({"a": 1})
        assert len(h) == 64
        assert h == h.lower()
        int(h, 16)  # parses as hex

    def test_matches_sha256_of_canonical_bytes(self):
        value = {"z": [3, 2, 1], "a": "x"}
        assert content_hash(value) == hashlib.sha256(canonicalize(value)).hexdigest()

    def test_hash_bytes_consistent_with_content_hash(self):
        value = {"a": 1, "b": 2}
        assert hash_bytes(canonicalize(value)) == content_hash(value)

    def test_distinct_content_distinct_hash(self):
        assert content_hash({"a": 1}) != content_hash({"a": 2})
