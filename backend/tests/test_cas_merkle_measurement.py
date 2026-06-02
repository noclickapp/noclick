"""Synthetic dedup measurement for Slice 2 (structural Merkle chunking).

Gates the S2 build decision. Implements the candidate structural `decompose` as a
PURE reference (NOT wired into the live store/GC), verifies it round-trips through
the existing `reassemble`, and measures the R2 footprint of whole-blob (Slice 1)
vs structural (Slice 2) across N simulated poller runs — for the two volatility
patterns that decide whether Merkle pays off:

  - LOCALIZED: volatile fields at the top (fetched_at / execution_ms), stable body.
    The body chunk dedups across every run → Merkle wins big.
  - SPREAD: a volatile field inside every row, so every row differs each run.
    Nothing dedups → Merkle gives ~no win (honest negative case).

Run with output:  pytest tests/test_cas_merkle_measurement.py -s
"""

import json

import pytest

from utils.cas.canonical import canonicalize, hash_bytes
from utils.cas.chunking import (
    DEFAULT_CHUNK_THRESHOLD_BYTES as T,
    decompose,
    reassemble,
)

_PLACEHOLDER_KEY = "$cas"


def decompose_structural(output, threshold=T):
    """Candidate Slice-2 decompose: chunk any subtree whose canonical size >= T,
    storing the subtree with its own >=T children replaced by placeholders
    (recurse), inline smaller subtrees. Returns (manifest, {hash: canonical bytes})
    with ALL chunks (incl. nested) in the flat dict — so the store would ref the
    full set (the GC-refcount fix noted for S2)."""
    data = canonicalize(output)
    if len(data) < threshold:
        return output, {}

    chunks: dict = {}
    if isinstance(output, dict):
        reduced = {}
        for k, v in output.items():
            cm, cc = decompose_structural(v, threshold)
            reduced[k] = cm
            chunks.update(cc)
        body = canonicalize(reduced)
    elif isinstance(output, list):
        reduced_list = []
        for v in output:
            cm, cc = decompose_structural(v, threshold)
            reduced_list.append(cm)
            chunks.update(cc)
        body = canonicalize(reduced_list)
    else:
        body = data  # scalar >= T: can't subdivide

    digest = hash_bytes(body)
    chunks[digest] = body
    return {_PLACEHOLDER_KEY: digest}, chunks


def _fetch_from(chunks):
    return lambda h: chunks.get(h)


# ── Output generators (a ~50KB google-sheet-style poller output) ──────────────

def _stable_rows(k):
    return [{"id": j, "name": f"item-{j}", "value": round(j * 1.5, 2), "active": j % 2 == 0}
            for j in range(k)]


def _localized(i, k):
    """Volatile fields only at the top; the rows body is byte-identical each run."""
    return {"fetched_at": f"2026-06-02T00:{i % 60:02d}:00Z", "execution_ms": 100 + i,
            "rows": _stable_rows(k)}


def _spread(i, k):
    """A volatile field inside every row → the whole body changes each run."""
    return {"fetched_at": f"2026-06-02T00:{i % 60:02d}:00Z",
            "rows": [{**r, "ts": i} for r in _stable_rows(k)]}


def _measure(make_output, n_runs, k):
    s1_unique, s2_unique = {}, {}
    s1_logical = s2_logical = 0
    for i in range(n_runs):
        out = make_output(i, k)
        _m1, c1 = decompose(out, T)                 # Slice 1 (whole-blob)
        _m2, c2 = decompose_structural(out, T)      # Slice 2 (structural)
        for h, b in c1.items():
            s1_unique[h] = len(b)
        for h, b in c2.items():
            s2_unique[h] = len(b)
        s1_logical += sum(len(b) for b in c1.values())
        s2_logical += sum(len(b) for b in c2.values())
    s1_phys, s2_phys = sum(s1_unique.values()), sum(s2_unique.values())
    return {
        "full_bytes": len(canonicalize(make_output(0, k))),
        "s1_physical": s1_phys, "s2_physical": s2_phys,
        "s1_dedup": round(s1_logical / s1_phys, 2) if s1_phys else 1.0,
        "s2_dedup": round(s2_logical / s2_phys, 2) if s2_phys else 1.0,
        "merkle_vs_wholeblob": round(s1_phys / s2_phys, 1) if s2_phys else 1.0,
    }


class TestStructuralDecompose:
    def test_round_trips_localized_and_spread(self):
        """The candidate algorithm must reassemble byte-exactly (correctness gate)."""
        for make in (_localized, _spread):
            out = make(7, 800)
            manifest, chunks = decompose_structural(out, T)
            back = reassemble(manifest, _fetch_from(chunks))
            assert back == out
            # manifest must be JSON-serializable (it's stored in cas_manifests)
            json.dumps(manifest)

    def test_small_output_inlines_like_slice1(self):
        out = {"a": 1, "b": "small"}
        manifest, chunks = decompose_structural(out, T)
        assert manifest == out and chunks == {}  # below T → inline, no chunk


@pytest.mark.asyncio
class TestDedupMeasurement:
    async def test_localized_volatility_merkle_wins(self, capsys):
        """Localized volatility: structural dedup must massively beat whole-blob."""
        k = 1200  # ~50KB output
        loc = _measure(_localized, n_runs=100, k=k)
        spread = _measure(_spread, n_runs=100, k=k)

        with capsys.disabled():
            print("\n=== Slice 2 (Merkle) synthetic dedup measurement — 100 poller runs ===")
            for name, m in (("LOCALIZED volatility", loc), ("SPREAD volatility", spread)):
                print(f"\n{name}: output={m['full_bytes']/1024:.1f}KB/run")
                print(f"  Slice 1 (whole-blob)  physical R2 = {m['s1_physical']/1024:8.1f}KB  dedup={m['s1_dedup']}x")
                print(f"  Slice 2 (structural)  physical R2 = {m['s2_physical']/1024:8.1f}KB  dedup={m['s2_dedup']}x")
                print(f"  → Merkle stores {m['merkle_vs_wholeblob']}x less than whole-blob")

        # Whole-blob can't dedup volatile output (the original problem).
        assert loc["s1_dedup"] == 1.0
        assert spread["s1_dedup"] == 1.0
        # Localized: Merkle factors out the stable body → order-of-magnitude win.
        assert loc["merkle_vs_wholeblob"] > 10
        # Spread: a per-row volatile field defeats structural dedup → ~no win.
        assert spread["merkle_vs_wholeblob"] < 1.5
