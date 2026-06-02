"""Unit tests for backend/utils/cas/chunking.py — decompose / reassemble.

Slice 1 is whole-output (no Merkle). Tests also exercise the forward-compatible
nested-placeholder reassembly + missing-chunk degradation that Slice 2 relies on.
"""

import json

from utils.cas.canonical import canonicalize
from utils.cas.chunking import (
    PRUNED_PLACEHOLDER,
    decompose,
    reassemble,
    referenced_hashes,
)


def _store_fetch(chunks):
    """Build a fetch_chunk(hash) -> bytes|None from a {hash: bytes} dict."""
    return lambda h: chunks.get(h)


class TestDecompose:
    def test_small_output_inlined_no_chunks(self):
        output = {"msg": "hi", "n": 3}
        manifest, chunks = decompose(output, threshold=4096)
        assert manifest == output
        assert chunks == {}

    def test_large_output_becomes_one_chunk(self):
        output = {"values": list(range(1000))}  # well over a tiny threshold
        manifest, chunks = decompose(output, threshold=16)
        assert list(manifest.keys()) == ["$cas"]
        digest = manifest["$cas"]
        assert len(chunks) == 1 and digest in chunks
        assert chunks[digest] == canonicalize(output)

    def test_identical_content_same_hash(self):
        a, _ = decompose({"values": list(range(500))}, threshold=16)
        b, _ = decompose({"values": list(range(500))}, threshold=16)
        assert a["$cas"] == b["$cas"]  # dedup: same content → same chunk hash


class TestReassemble:
    def test_inline_roundtrip_needs_no_fetch(self):
        output = {"a": 1, "b": [1, 2, 3]}
        manifest, chunks = decompose(output, threshold=4096)
        # fetch that explodes if called proves inline needs no chunk fetch
        def boom(_h):
            raise AssertionError("should not fetch for an inline manifest")
        assert reassemble(manifest, boom) == output

    def test_chunked_roundtrip(self):
        output = {"values": list(range(1000)), "stable": "x"}
        manifest, chunks = decompose(output, threshold=16)
        assert reassemble(manifest, _store_fetch(chunks)) == output

    def test_missing_chunk_degrades_to_pruned_placeholder(self):
        output = {"values": list(range(1000))}
        manifest, _chunks = decompose(output, threshold=16)
        # empty store → fetch returns None
        assert reassemble(manifest, _store_fetch({})) == PRUNED_PLACEHOLDER

    def test_missing_nested_chunk_keeps_siblings(self):
        # Hand-built manifest with one resolvable + one missing placeholder
        # (the shape Slice 2 produces); siblings must survive a miss.
        good = {"kept": True}
        good_bytes = canonicalize(good)
        good_hash = __import__("hashlib").sha256(good_bytes).hexdigest()
        missing_hash = "0" * 64
        manifest = {
            "alive": {"$cas": good_hash},
            "dead": {"$cas": missing_hash},
            "inline": 7,
        }
        result = reassemble(manifest, _store_fetch({good_hash: good_bytes}))
        assert result == {"alive": good, "dead": PRUNED_PLACEHOLDER, "inline": 7}

    def test_non_hash_cas_value_not_treated_as_pointer(self):
        # A real output literally containing a $cas key whose value is not a
        # 64-hex hash must NOT be resolved (collision guard).
        output = {"$cas": "not-a-real-hash"}
        manifest, chunks = decompose(output, threshold=4096)  # inlined
        assert reassemble(manifest, _store_fetch({})) == output


class TestReferencedHashes:
    def test_inline_has_none(self):
        manifest, _ = decompose({"a": 1}, threshold=4096)
        assert referenced_hashes(manifest) == set()

    def test_collects_nested(self):
        h1, h2 = "a" * 64, "b" * 64
        manifest = {"x": {"$cas": h1}, "y": [{"$cas": h2}, 1]}
        assert referenced_hashes(manifest) == {h1, h2}
