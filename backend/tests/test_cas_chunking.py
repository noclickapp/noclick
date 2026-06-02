"""Unit tests for backend/utils/cas/chunking.py — decompose / reassemble.

Slice 1 is whole-output (no Merkle). Tests also exercise the forward-compatible
nested-placeholder reassembly + missing-chunk degradation that Slice 2 relies on.
"""

import json

from utils.cas.canonical import canonicalize
from utils.cas.chunking import (
    PRUNED_PLACEHOLDER,
    _is_placeholder,
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

    def test_large_output_is_chunked_and_roundtrips(self):
        output = {"values": list(range(1000))}  # well over a tiny threshold
        manifest, chunks = decompose(output, threshold=16)
        assert chunks  # structural produces at least one chunk
        assert reassemble(manifest, _store_fetch(chunks)) == output

    def test_identical_content_same_hash(self):
        a, _ = decompose({"values": list(range(500))}, threshold=16)
        b, _ = decompose({"values": list(range(500))}, threshold=16)
        assert a["$cas"] == b["$cas"]  # dedup: same content → same chunk hash


class TestStructural:
    def test_large_child_factored_skeleton_inlined(self):
        """A node that's only large because of one big child: the child is
        chunked, the small skeleton is INLINED (manifest is a dict, not a
        top-level placeholder) — the no-regression rule (no extra wrapper chunk)."""
        output = {"body": list(range(2000)), "ts": 1}  # body >= 4KB, skeleton tiny
        manifest, chunks = decompose(output, threshold=4096)
        assert isinstance(manifest, dict) and "$cas" not in manifest  # inlined skeleton
        assert _is_placeholder(manifest["body"]) and manifest["ts"] == 1
        assert len(chunks) == 1  # just the body chunk, no wrapper
        assert reassemble(manifest, _store_fetch(chunks)) == output

    def test_shared_subtree_dedups_across_outputs(self):
        """The whole point: two different outputs sharing a large subtree
        reference the SAME chunk hash (cross-run dedup)."""
        body = list(range(2000))
        m1, c1 = decompose({"body": body, "ts": 1}, threshold=4096)
        m2, c2 = decompose({"body": body, "ts": 2}, threshold=4096)
        assert m1["body"]["$cas"] == m2["body"]["$cas"]  # shared chunk
        assert set(c1) == set(c2)  # identical chunk set; only the inline ts differs

    def test_deep_nesting_emits_transitive_chunks(self):
        """A chunk whose own bytes contain nested placeholders: chunks must include
        the nested hashes that referenced_hashes(manifest) cannot see (the reason
        the store refs list(chunks) and reassembly fetches the transitive closure)."""
        inner = list(range(2000))
        output = {f"k{i}": inner for i in range(60)}  # reduced skeleton itself >= 4KB
        manifest, chunks = decompose(output, threshold=4096)
        top_refs = referenced_hashes(manifest)
        assert set(chunks) - top_refs  # nested chunks exist beyond the manifest's refs
        assert reassemble(manifest, _store_fetch(chunks)) == output

    def test_opaque_scalar_is_one_chunk(self):
        """A large scalar can't be subdivided → exactly one chunk (== whole-blob);
        chunking never makes an opaque scalar worse."""
        output = "x" * 5000
        manifest, chunks = decompose(output, threshold=4096)
        assert _is_placeholder(manifest) and len(chunks) == 1
        assert reassemble(manifest, _store_fetch(chunks)) == output


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
