"""Tests for the CAS storage-stats cache (utils/cas/stats.py): the size/dedup
aggregation that backs the admin dashboard and the Slice-2 dedup decision.

Uses the rolled-back postgres_db (real schema) + the stateful R2 fake. The
headline assertion is the dedup measurement: the same output persisted across N
executions stores ONE physical blob but counts N logical references.
"""

import uuid

import pytest

from tests.mocks.mock_r2 import FakeR2, patch_r2
from utils import node_outputs as no
from utils.cas import store, stats
from utils.cas.gc import GLOBAL_TOTALS_ID

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
BIG = {"blob": list(range(2000))}  # > 4KB threshold → one R2 chunk


class _SingleConnPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


async def _wf(conn):
    wid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflows (id, owner_id, name) VALUES ($1,$2,'stats')", wid, TEST_USER_ID)
    return wid


async def _exec(conn, wid):
    eid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status) "
        "VALUES ($1,$2,$3,'completed')", eid, wid, TEST_USER_ID)
    return eid


@pytest.mark.asyncio
class TestCasStats:
    async def test_dedup_ratio_same_output_across_runs(self, postgres_db):
        """Same large output persisted across 3 runs → 1 physical blob, 3 logical
        refs → dedup_ratio == 3.0. This is the Slice-2-gating measurement."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            for _ in range(3):
                eid = await _exec(postgres_db, wid)
                await store.persist_node_result(
                    pool, workflow_id=wid, execution_id=eid, node_id="n1", output=BIG)
            await stats.refresh_storage_stats(pool)
            flow = await stats.read_flow_breakdown(pool, wid)
            glob = await stats.read_global_stats(pool)

        # one physical blob, three logical references
        assert flow["chunk_count"] == 1
        assert flow["logical_bytes"] == 3 * flow["physical_bytes"]
        assert flow["dedup_ratio"] == 3.0
        # global mirrors it (single flow); bytes_saved = 2x the one chunk
        assert glob["dedup_ratio"] == 3.0
        assert glob["bytes_saved"] == 2 * flow["physical_bytes"]
        assert glob["chunk_count"] == 1  # cas_blobs holds the single deduped blob

    async def test_graph_vs_output_split_and_counts(self, postgres_db):
        """Graph snapshot bytes and node-output bytes are attributed separately;
        counts (executions, distinct graphs, chunks) are populated."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            eid = await _exec(postgres_db, wid)
            await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid,
                graph={"nodes": [{"id": "n1", "config": {"x": list(range(2000))}}], "edges": []})
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output=BIG)
            await stats.refresh_storage_stats(pool)
            flow = await stats.read_flow_breakdown(pool, wid)

        assert flow["graph_bytes"] > 0
        assert flow["output_bytes"] > 0
        assert flow["physical_bytes"] == flow["graph_bytes"] + flow["output_bytes"]
        assert flow["distinct_graphs"] == 1
        assert flow["executions_live"] == 1
        # per-node split surfaces the output node (graph is keyed under __graph__)
        node_ids = {n["node_id"] for n in flow["by_node"]}
        assert "n1" in node_ids

    async def test_ranking_orders_by_physical_and_carries_owner(self, postgres_db):
        """read_flow_ranking ranks flows by physical footprint with owner info."""
        pool = _SingleConnPool(postgres_db)
        big_wf = await _wf(postgres_db)
        small_wf = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            e1 = await _exec(postgres_db, big_wf)
            await store.persist_node_result(
                pool, workflow_id=big_wf, execution_id=e1, node_id="n1",
                output={"blob": list(range(5000))})  # larger
            e2 = await _exec(postgres_db, small_wf)
            await store.persist_node_result(
                pool, workflow_id=small_wf, execution_id=e2, node_id="n1", output=BIG)
            await stats.refresh_storage_stats(pool)
            ranking = await stats.read_flow_ranking(pool, limit=10)

        ids = [r["workflow_id"] for r in ranking]
        assert str(big_wf) in ids and str(small_wf) in ids
        # big flow ranks first; owner is carried through
        assert ids.index(str(big_wf)) < ids.index(str(small_wf))
        big_row = next(r for r in ranking if r["workflow_id"] == str(big_wf))
        assert big_row["owner_id"] == str(TEST_USER_ID)

    async def test_status_only_node_counted_no_bytes(self, postgres_db):
        """A status-only node (no output) contributes a manifest + execution but no
        chunk bytes — refresh must still count its execution."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            eid = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1",
                status="skipped", error=None)
            await stats.refresh_storage_stats(pool)
            flow = await stats.read_flow_breakdown(pool, wid)
        assert flow["physical_bytes"] == 0
        assert flow["chunk_count"] == 0
        assert flow["executions_live"] == 1

    async def test_small_inline_output_counts_as_manifest_not_physical(self, postgres_db):
        """A small (<4KB) output is stored inline in the manifest JSONB, not as an
        R2 chunk — so it lands in manifest_bytes (Postgres), with zero physical
        (R2) bytes. Pins the dashboard semantic that physical_bytes = R2 only."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            eid = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output={"small": 1})
            await stats.refresh_storage_stats(pool)
            flow = await stats.read_flow_breakdown(pool, wid)
            glob = await stats.read_global_stats(pool)
        assert flow["physical_bytes"] == 0     # no R2 chunk
        assert flow["chunk_count"] == 0
        assert glob["manifest_bytes"] > 0      # inline value lives in the manifest

    async def test_refresh_is_idempotent(self, postgres_db):
        """Re-running refresh recomputes the cache wholesale (no double-counting)."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            eid = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output=BIG)
            first = await stats.refresh_storage_stats(pool)
            second = await stats.refresh_storage_stats(pool)
        assert first["physical_bytes"] == second["physical_bytes"]
        assert first["logical_bytes"] == second["logical_bytes"]
        assert second["flows"] == 1

    async def test_partial_shared_subtree_dedup_across_runs(self, postgres_db):
        """Structural-Merkle nesting: one flow whose two runs share a big subtree
        but each carry a distinct per-run subtree → 3 DISTINCT blobs (1 shared).
        Physical counts the shared blob once; logical counts it twice → the dedup
        ratio lands strictly between 'no dedup' (1.0) and 'fully shared' (2.0)."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        shared = {"shared_key": list(range(2000))}            # identical across runs
        out_a = {"shared": shared, "uniqueA": {"a": list(range(2000, 4000))}}
        out_b = {"shared": shared, "uniqueB": {"b": list(range(5000, 7000))}}
        with patch_r2(FakeR2()):
            ea = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=ea, node_id="n1", output=out_a)
            eb = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eb, node_id="n1", output=out_b)
            # The actual on-disk (compressed) blob sizes — assert against truth,
            # not hardcoded canonical sizes.
            blob_sizes = {
                r["hash"]: r["size_bytes"]
                for r in await postgres_db.fetch("SELECT hash, size_bytes FROM cas_blobs")
            }
            shared_hash = next(iter(
                {r["chunk_hash"] for r in await postgres_db.fetch(
                    "SELECT chunk_hash FROM cas_refs WHERE execution_id = $1", ea)}
                & {r["chunk_hash"] for r in await postgres_db.fetch(
                    "SELECT chunk_hash FROM cas_refs WHERE execution_id = $1", eb)}))
            await stats.refresh_storage_stats(pool)
            flow = await stats.read_flow_breakdown(pool, wid)
            glob = await stats.read_global_stats(pool)

        assert len(blob_sizes) == 3                            # 3 distinct blobs
        assert flow["chunk_count"] == 3
        # physical = each distinct blob once (shared counted ONCE)
        assert flow["physical_bytes"] == sum(blob_sizes.values())
        # logical = every reference; the shared blob is referenced by both runs
        assert flow["logical_bytes"] == sum(blob_sizes.values()) + blob_sizes[shared_hash]
        assert 1.0 < flow["dedup_ratio"] < 2.0
        assert glob["chunk_count"] == 3

    async def test_orphan_blob_in_global_physical_not_in_flow(self, postgres_db):
        """The GLOBAL physical total is authoritative from cas_blobs — it counts a
        not-yet-collected ORPHAN blob (the true R2 footprint). A per-flow breakdown
        only attributes blobs the flow actually references, so it excludes it."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        orphan_hash = "f" * 64
        orphan_size = 7777
        with patch_r2(FakeR2()):
            eid = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output=BIG)
            referenced_size = await postgres_db.fetchval(
                "SELECT size_bytes FROM cas_blobs")
            # An unreferenced, condemned blob (e.g. a node re-persisted with new
            # output that hasn't been swept yet).
            await postgres_db.execute(
                "INSERT INTO cas_blobs (hash, size_bytes, orphaned_at) VALUES ($1, $2, now())",
                orphan_hash, orphan_size)
            await stats.refresh_storage_stats(pool)
            glob = await stats.read_global_stats(pool)
            flow = await stats.read_flow_breakdown(pool, wid)

        # Global = referenced blob + orphan (both rows in cas_blobs).
        assert glob["chunk_count"] == 2
        assert glob["physical_bytes"] == referenced_size + orphan_size
        # The flow only sees the blob it references; the orphan is invisible to it.
        assert flow["chunk_count"] == 1
        assert flow["physical_bytes"] == referenced_size
        orphan_hashes = {b["hash"] for b in flow["largest_blobs"]}
        assert orphan_hash not in orphan_hashes

    async def test_composite_iter_nodes_single_execution(self, postgres_db):
        """Composite #iter sub-outputs persist under synthetic node_ids on ONE real
        execution. Stats count ONE execution (DISTINCT execution_id), surface the
        #iter nodes in the per-node split, and (no graph snapshot) keep graph_bytes
        at zero with all bytes in output_bytes."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            eid = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="c", output=BIG)
            for i in range(3):
                await store.persist_node_result(
                    pool, workflow_id=wid, execution_id=eid, node_id=f"b#iter:{i}",
                    output={"i": i, "blob": list(range(2000))})
            await stats.refresh_storage_stats(pool)
            flow = await stats.read_flow_breakdown(pool, wid)
            ranking = await stats.read_flow_ranking(pool, limit=10)

        # One DISTINCT execution despite 4 node rows.
        assert flow["executions_live"] == 1
        row = next(r for r in ranking if r["workflow_id"] == str(wid))
        assert row["execution_count"] == 1
        # No graph snapshot persisted → all physical bytes are node output.
        assert flow["graph_bytes"] == 0
        assert flow["output_bytes"] == flow["physical_bytes"] > 0
        node_ids = {n["node_id"] for n in flow["by_node"]}
        assert "c" in node_ids
        assert {f"b#iter:{i}" for i in range(3)} <= node_ids

    async def test_facade_bindings_are_store_functions(self):
        """utils.node_outputs is a thin re-export facade: every name in __all__ is a
        callable bound to the corresponding utils.cas.store function. Pins the
        single-interface contract (swapping the backend is a one-file change)."""
        expected = {
            "latest_outputs": store.read_latest_node_outputs,
            "persist_node": store.persist_node_result,
            "snapshot_graph": store.persist_graph_snapshot,
            "read_graph": store.read_graph,
            "persist_outputs": store.persist_run_outputs,
            "execution_outputs": store.read_execution_outputs,
            "latest_output": store.read_latest_node_output,
            "latest_statuses": store.read_latest_node_statuses,
            "output_history": store.read_node_output_history,
            "read_node_output": store.read_node_output,
            "latest_output_meta": store.read_latest_node_output_meta,
            "nodes_with_output": store.read_nodes_with_output,
        }
        for name in no.__all__:
            assert hasattr(no, name), f"facade missing {name}"
            assert callable(getattr(no, name)), f"{name} is not callable"
        for name, target in expected.items():
            assert getattr(no, name) is target, f"{name} not bound to {target.__name__}"

    async def test_cross_flow_shared_blob_attributed_per_flow_counted_once_global(self, postgres_db):
        """A blob shared across TWO flows (identical output, same hash → one R2
        object): each flow's physical footprint attributes it FULLY (so a drill-down
        isn't misleadingly tiny), but the global total counts the single blob ONCE."""
        pool = _SingleConnPool(postgres_db)
        wf_a = await _wf(postgres_db)
        wf_b = await _wf(postgres_db)
        with patch_r2(FakeR2()):
            ea = await _exec(postgres_db, wf_a)
            await store.persist_node_result(
                pool, workflow_id=wf_a, execution_id=ea, node_id="n1", output=BIG)
            eb = await _exec(postgres_db, wf_b)
            await store.persist_node_result(
                pool, workflow_id=wf_b, execution_id=eb, node_id="n1", output=BIG)
            blob_size = await postgres_db.fetchval("SELECT size_bytes FROM cas_blobs")
            blob_count = await postgres_db.fetchval("SELECT count(*) FROM cas_blobs")
            await stats.refresh_storage_stats(pool)
            flow_a = await stats.read_flow_breakdown(pool, wf_a)
            flow_b = await stats.read_flow_breakdown(pool, wf_b)
            glob = await stats.read_global_stats(pool)

        assert blob_count == 1                                 # one physical R2 object
        # Each flow attributed the shared blob in full.
        assert flow_a["physical_bytes"] == blob_size
        assert flow_b["physical_bytes"] == blob_size
        assert flow_a["chunk_count"] == 1 and flow_b["chunk_count"] == 1
        # Global counts it once (no double-attribution at the platform level).
        assert glob["chunk_count"] == 1
        assert glob["physical_bytes"] == blob_size

    async def test_zero_state_no_divide_by_zero(self, postgres_db):
        """Empty / inline-only states never divide by zero: a never-persisted flow
        reads all zeros + dedup 1.0 + empty lists; an inline-only flow has zero
        physical + dedup 1.0; a freshly-refreshed empty store reports global zeros."""
        pool = _SingleConnPool(postgres_db)
        with patch_r2(FakeR2()):
            await stats.refresh_storage_stats(pool)
            # 1) A workflow id that was never persisted.
            missing = await stats.read_flow_breakdown(pool, uuid.uuid4())
            # 2) An inline-only flow (sub-threshold output → manifest, no R2 chunk).
            wid = await _wf(postgres_db)
            eid = await _exec(postgres_db, wid)
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output={"small": 1})
            await stats.refresh_storage_stats(pool)
            inline = await stats.read_flow_breakdown(pool, wid)
            glob = await stats.read_global_stats(pool)

        assert missing["physical_bytes"] == 0
        assert missing["logical_bytes"] == 0
        assert missing["dedup_ratio"] == 1.0
        assert missing["by_node"] == []
        assert missing["largest_blobs"] == []

        assert inline["physical_bytes"] == 0
        assert inline["dedup_ratio"] == 1.0          # no exception on zero physical

        # No R2 chunks anywhere → global physical is zero, dedup degrades to 1.0.
        assert glob["physical_bytes"] == 0
        assert glob["chunk_count"] == 0
        assert glob["dedup_ratio"] == 1.0
