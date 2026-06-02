"""Head-to-head dedup comparison: whole-blob vs structural Merkle vs content-
defined chunking (gear-based CDC) — to decide whether to skip Slice-2 structural
Merkle and go straight to CDC.

DECISION-GRADE (post-adversarial-review): physical bytes are measured AFTER zstd-3
per chunk, matching the prod store (store.py compresses each chunk before R2 and
records the COMPRESSED size). Raw-byte ratios overstate every dedup win because a
whole 50KB JSON blob itself compresses ~16x. CDC is matched to structural's 4KB
granularity (avg=T) for a fair comparison — finer CDC chunks inflate both its win
and its overhead.

All three are PURE reference impls (not wired into the store), identical accounting:
  - R2 physical bytes  : sum of UNIQUE chunk COMPRESSED sizes across N runs
  - R2 objects         : count of unique chunks
  - ref rows           : sum over runs of chunks-referenced (cas_refs rows; per-run
                         even for deduped chunks — CDC's hidden cost)
  - manifest bytes (PG): sum over runs of the reassembly manifest size (cas_manifests;
                         per-run, NOT deduped — CDC's other hidden cost)

Workloads map to real node-output shapes (verified against backend/nodes): localized
(poller: volatile fields over a stable body — the dominant read/poll shape), dense/
sparse spread, append-only growth, middle insertion (shift), and binary_drift (a
high-entropy opaque scalar that drifts — the one real case where ONLY CDC helps,
because structural can't subdivide a scalar).

Run with output:  pytest tests/test_cas_cdc_comparison.py -s
"""

import base64
import random

import pytest
import zstandard as zstd

from utils.cas.canonical import canonicalize, hash_bytes
from utils.cas.chunking import DEFAULT_CHUNK_THRESHOLD_BYTES as T
from tests.test_cas_merkle_measurement import decompose_structural

# Matches store.py: every chunk is zstd-3 compressed before R2; the authoritative
# footprint (stats.py SUM(size_bytes)) is the compressed size.
_ZC = zstd.ZstdCompressor(level=3)


def _zsize(data: bytes) -> int:
    return len(_ZC.compress(data))

_MASK64 = (1 << 64) - 1
# Deterministic gear table: 256 DISTINCT random values from ONE seeded RNG.
# (One Random() per element would repeat the same first draw 256x → all-equal
# gear → position-aligned, not content-defined, boundaries.)
_GEAR_RNG = random.Random(0xCD0FFEE)
_GEAR = [_GEAR_RNG.getrandbits(64) for _ in range(256)]


def cdc_chunks(data: bytes, min_size: int = T // 4, avg_size: int = T, max_size: int = T * 4):
    """Gear-based content-defined chunking (the FastCDC core): a boundary is cut
    where the rolling gear hash has `bits` low zero bits, bounded by min/max.
    Boundaries are content-defined, so a local edit only re-chunks locally
    (shift-resistant). Chunks partition `data` exactly (concat == data)."""
    n = len(data)
    if n <= min_size:
        return [data]
    bits = avg_size.bit_length() - 1
    mask = (1 << bits) - 1
    chunks = []
    start, h, pos = 0, 0, 0
    while pos < n:
        h = ((h << 1) + _GEAR[data[pos]]) & _MASK64
        size = pos - start + 1
        if (size >= min_size and (h & mask) == 0) or size >= max_size:
            chunks.append(data[start:pos + 1])
            start, h = pos + 1, 0
        pos += 1
    if start < n:
        chunks.append(data[start:])
    return chunks


# ── Accounting ────────────────────────────────────────────────────────────────

def _measure(outputs, kind):
    unique: dict = {}          # chunk hash -> COMPRESSED size (deduped physical R2)
    ref_rows = 0               # cas_refs rows (per run, per chunk)
    manifest_bytes = 0         # cas_manifests PG bytes (per run, not deduped)
    for out in outputs:
        data = canonicalize(out)
        if kind == "whole":
            chs = [data]
            manifest = {"$cas": hash_bytes(data)}
        elif kind == "structural":
            m, chunk_map = decompose_structural(out, T)
            chs = list(chunk_map.values())
            manifest = m
        elif kind == "cdc":
            chs = cdc_chunks(data)
            manifest = {"$cas_seq": [hash_bytes(c) for c in chs]}
        else:
            raise ValueError(kind)
        ref_rows += len(chs)
        for b in chs:
            h = hash_bytes(b)
            if h not in unique:
                unique[h] = _zsize(b)   # prod stores the zstd-compressed chunk
        manifest_bytes += len(canonicalize(manifest))
    return {
        "physical": sum(unique.values()),
        "objects": len(unique),
        "ref_rows": ref_rows,
        "manifest_bytes": manifest_bytes,
    }


# ── Workloads (N runs each) ─────────────────────────────────────────────────────

def _rows(k, mutate=None):
    out = []
    for j in range(k):
        r = {"id": j, "name": f"item-{j}", "value": round(j * 1.5, 2), "active": j % 2 == 0}
        if mutate:
            mutate(j, r)
        out.append(r)
    return out


_TS = lambda i: f"2026-06-02T{i // 60:02d}:{i % 60:02d}:00Z"

WORKLOADS = {
    # volatile fields at the top; stable body
    "localized": lambda i, k: {"fetched_at": _TS(i), "execution_ms": 100 + i, "rows": _rows(k)},
    # a changing field in EVERY row (dense)
    "spread_dense": lambda i, k: {"fetched_at": _TS(i), "rows": _rows(k, lambda j, r: r.__setitem__("ts", i))},
    # a changing field in only 2 rows, far apart (sparser than the chunk size, so
    # whole chunks survive between them — CDC recovers them, structural can't)
    "spread_sparse": lambda i, k: {"fetched_at": _TS(i), "rows": _rows(k, lambda j, r: r.__setitem__("ts", i) if j in (0, k // 2) else None)},
    # append-only growth (prefix stable, tail grows)
    "append": lambda i, k: {"run": i, "rows": _rows(k) + [{"id": k + i * 10 + m, "name": f"new-{i}-{m}", "value": 0.0, "active": True} for m in range(10)]},
    # a big HIGH-ENTROPY opaque scalar (base64 blob, e.g. an HTTP binary download)
    # that drifts in the middle each run. structural can't subdivide a scalar →
    # whole chunk re-hashes (1x); only CDC dedups the stable bytes. zstd barely
    # helps high-entropy data, so this is the real "only CDC wins" case.
    "binary_drift": lambda i, k: {"run": i, "data": _BLOB[:len(_BLOB) // 2] + f"DRIFT{i:04d}" + _BLOB[len(_BLOB) // 2 + 9:]},
    # insert an item in the MIDDLE (boundary-shift stress)
    "middle_insert": lambda i, k: {"rows": _rows(k)[:k // 2] + [{"id": -i, "name": f"ins-{i}", "value": 1.0, "active": True}] + _rows(k)[k // 2:]},
}

# A ~50KB high-entropy base64 blob (stable base; binary_drift mutates the middle).
_BLOB = base64.b64encode(random.Random(99).randbytes(38000)).decode()


def _run_all(n_runs=100, k=1000):
    table = {}
    for name, gen in WORKLOADS.items():
        outputs = [gen(i, k) for i in range(n_runs)]
        full = len(canonicalize(outputs[0]))
        table[name] = {
            "full_kb": full / 1024,
            "whole": _measure(outputs, "whole"),
            "structural": _measure(outputs, "structural"),
            "cdc": _measure(outputs, "cdc"),
        }
    return table


def _reduction(row, algo):
    """Whole-blob physical / algo physical (higher = more R2 saved)."""
    w = row["whole"]["physical"]
    a = row[algo]["physical"]
    return round(w / a, 1) if a else 1.0


# ── Tests ───────────────────────────────────────────────────────────────────────

class TestCdcCorrectness:
    def test_cdc_round_trips_and_is_shift_resistant(self):
        data = canonicalize({"rows": _rows(1000), "x": 1})
        chunks = cdc_chunks(data)
        assert b"".join(chunks) == data                      # partitions exactly
        # insert a byte near the front → only a bounded number of chunks change
        edited = data[:50] + b"X" + data[50:]
        ec = cdc_chunks(edited)
        before = {hash_bytes(c) for c in chunks}
        after = {hash_bytes(c) for c in ec}
        shared = before & after
        # most chunks survive the shift (content-defined boundaries re-sync)
        assert len(shared) >= 0.7 * len(before)


@pytest.mark.asyncio
class TestCdcVsStructural:
    async def test_compare(self, capsys):
        table = _run_all(n_runs=100, k=1000)

        with capsys.disabled():
            print("\n=== whole-blob vs structural Merkle vs CDC — 100 runs, ~50KB/run ===")
            print(f"{'workload':<14} {'algo':<11} {'R2 KB':>8} {'objs':>6} {'refRows':>8} {'manifestKB':>10} {'vsWhole':>8}")
            for name, row in table.items():
                for algo in ("whole", "structural", "cdc"):
                    m = row[algo]
                    red = '' if algo == 'whole' else f"{_reduction(row, algo)}x"
                    print(f"{name:<14} {algo:<11} {m['physical']/1024:>8.1f} {m['objects']:>6} "
                          f"{m['ref_rows']:>8} {m['manifest_bytes']/1024:>10.1f} {red:>8}")
                print()

        # Post-zstd, matched 4KB granularity. Localized (the dominant real poller
        # shape): structural wins decisively and far beats CDC there.
        assert _reduction(table["localized"], "structural") > 8
        assert _reduction(table["localized"], "structural") > 2 * _reduction(table["localized"], "cdc")
        # Shift/append/binary: CDC wins; structural is stuck at ~whole-blob.
        for wl in ("append", "middle_insert", "binary_drift"):
            assert _reduction(table[wl], "cdc") > 2, wl
            assert _reduction(table[wl], "structural") < 1.5, wl
        # Dense spread defeats BOTH.
        assert _reduction(table["spread_dense"], "cdc") < 1.5
        assert _reduction(table["spread_dense"], "structural") < 1.5
        # Sparse spread: CDC recovers untouched chunks; structural can't.
        assert _reduction(table["spread_sparse"], "cdc") > _reduction(table["spread_sparse"], "structural")
        # CDC's ongoing cost on the dominant localized shape: more ref rows + bigger
        # manifests than structural (per-chunk Postgres tax), even at matched 4KB.
        assert table["localized"]["cdc"]["ref_rows"] > 1.5 * table["localized"]["structural"]["ref_rows"]
        assert table["localized"]["cdc"]["manifest_bytes"] > 2 * table["localized"]["structural"]["manifest_bytes"]
