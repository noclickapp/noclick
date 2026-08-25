"""Unit tests for the CAS-backed read API (the legacy node_output_store
replacements): latest/history/execution outputs + statuses. Uses the rolled-back
postgres_db with explicit created_at values so recency ordering is deterministic.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.mocks.mock_r2 import FakeR2, patch_r2
from utils.cas import store
from utils.cas.canonical import canonicalize, hash_bytes
from utils.cas.chunking import PRUNED_PLACEHOLDER

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


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
        "INSERT INTO workflows (id, owner_id, name) VALUES ($1,$2,'r')",
        wid, TEST_USER_ID)
    return wid


async def _exec(conn, wid):
    eid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status) VALUES ($1,$2,$3,'completed')",
        eid, wid, TEST_USER_ID)
    return eid


async def _set_created(conn, eid, node_id, ts):
    await conn.execute(
        "UPDATE cas_manifests SET created_at=$1 WHERE execution_id=$2 AND node_id=$3",
        ts, eid, node_id)


@pytest.mark.asyncio
class TestCasReads:
    async def test_execution_outputs(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)
        with patch_r2(FakeR2()):
            await store.persist_node_result(pool, workflow_id=wid, execution_id=eid, node_id="a", output={"x": 1})
            await store.persist_node_result(pool, workflow_id=wid, execution_id=eid, node_id="b", output={"y": 2})
            got = await store.read_execution_outputs(pool, eid)
        assert got == {"a": {"x": 1}, "b": {"y": 2}}

    async def test_latest_node_outputs_picks_newest(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        e1, e2 = await _exec(postgres_db, wid), await _exec(postgres_db, wid)
        with patch_r2(FakeR2()):
            await store.persist_node_result(pool, workflow_id=wid, execution_id=e1, node_id="n1", output={"v": "old"})
            await store.persist_node_result(pool, workflow_id=wid, execution_id=e2, node_id="n1", output={"v": "new"})
            await _set_created(postgres_db, e1, "n1", T0)
            await _set_created(postgres_db, e2, "n1", T0 + timedelta(minutes=5))
            latest = await store.read_latest_node_outputs(pool, wid)
            single = await store.read_latest_node_output(pool, wid, "n1")
        assert latest == {"n1": {"v": "new"}}
        assert single == {"v": "new"}

    async def test_latest_node_statuses(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        e1, e2 = await _exec(postgres_db, wid), await _exec(postgres_db, wid)
        with patch_r2(FakeR2()):
            await store.persist_node_result(pool, workflow_id=wid, execution_id=e1, node_id="n1", status="completed")
            await store.persist_node_result(pool, workflow_id=wid, execution_id=e2, node_id="n1", status="error", error="boom")
            await _set_created(postgres_db, e1, "n1", T0)
            await _set_created(postgres_db, e2, "n1", T0 + timedelta(minutes=5))
            statuses = await store.read_latest_node_statuses(pool, wid)
        assert statuses["n1"]["status"] == "error"
        assert statuses["n1"]["error"] == "boom"
        assert isinstance(statuses["n1"]["finishedAt"], int)  # epoch ms from created_at

    async def test_node_output_history_newest_first_and_limit(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        execs = [await _exec(postgres_db, wid) for _ in range(3)]
        with patch_r2(FakeR2()):
            for i, eid in enumerate(execs):
                await store.persist_node_result(pool, workflow_id=wid, execution_id=eid, node_id="n1", output={"i": i})
                await _set_created(postgres_db, eid, "n1", T0 + timedelta(minutes=i))
            hist = await store.read_node_output_history(pool, wid, "n1", limit=2)
        assert [h["output"] for h in hist] == [{"i": 2}, {"i": 1}]  # newest first, limited to 2
        assert hist[0]["execution_id"] == str(execs[2])

    async def test_iteration_composite_outputs_carousel_and_latest(self, postgres_db):
        """Iteration sub-outputs are stored under composite '<node>#iter:N' keys
        on the REAL execution_id. The carousel (history) surfaces them under the
        body node; the canvas-latest read excludes them (they aren't canvas nodes)."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)
        with patch_r2(FakeR2()):
            # body node "b" runs 3 iterations on a single execution
            for i in range(3):
                await store.persist_node_result(
                    pool, workflow_id=wid, execution_id=eid, node_id=f"b#iter:{i}", output={"iter": i})
                await _set_created(postgres_db, eid, f"b#iter:{i}", T0 + timedelta(minutes=i))
            # a normal sibling node "c" with one output
            await store.persist_node_result(pool, workflow_id=wid, execution_id=eid, node_id="c", output={"v": 1})
            await _set_created(postgres_db, eid, "c", T0)

            hist = await store.read_node_output_history(pool, wid, "b")
            latest = await store.read_latest_node_outputs(pool, wid)

        # carousel under body node "b" shows each iteration, newest first
        assert [h["output"] for h in hist] == [{"iter": 2}, {"iter": 1}, {"iter": 0}]
        # canvas-latest excludes composite iteration keys, keeps real nodes
        assert latest == {"c": {"v": 1}}

    async def test_history_merges_base_and_iter_rows_across_keys(self, postgres_db):
        """History interleaves base-node rows and '#iter:' sub-rows by recency
        with the limit applied across the union (the per-key top-N + global
        top-N rewrite must match the old single-query global ORDER BY), and
        key matching stays exact: a sibling 'bx' never bleeds into 'b'."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        e1, e2, e3 = [await _exec(postgres_db, wid) for _ in range(3)]
        rows = [(e1, "b", 0), (e2, "b#iter:0", 1), (e2, "b#iter:1", 2),
                (e3, "b", 3), (e3, "bx", 9)]
        with patch_r2(FakeR2()):
            for i, (eid, nid, minutes) in enumerate(rows):
                await store.persist_node_result(
                    pool, workflow_id=wid, execution_id=eid, node_id=nid, output={"t": minutes})
                await _set_created(postgres_db, eid, nid, T0 + timedelta(minutes=minutes))
            hist = await store.read_node_output_history(pool, wid, "b", limit=3)
        # newest-first across base + iter keys; limit spans the union; "bx" (newest
        # row overall) is excluded despite sharing the "b" prefix
        assert [h["output"] for h in hist] == [{"t": 3}, {"t": 2}, {"t": 1}]
        assert hist[0]["execution_id"] == str(e3)

    async def test_latest_outputs_fans_out_r2_reads(self, postgres_db):
        """read_latest_node_outputs reassembles rows concurrently (asyncio.gather):
        4 nodes, each a >threshold output → one R2 chunk, with a 25ms read latency
        must resolve in ~25ms (parallel), not ~100ms (sequential). Guards the
        2026-05-13 cascade for the CAS read path."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)

        class _SlowReadR2(FakeR2):
            async def download_bytes_from_r2_async_native(self, bucket, key):
                await asyncio.sleep(0.025)  # simulate a 25ms R2 round-trip
                return await super().download_bytes_from_r2_async_native(bucket, key)

        outputs = {f"n{i}": {"blob": list(range(2000)), "n": i} for i in range(4)}
        with patch_r2(_SlowReadR2()):
            for nid, out in outputs.items():
                await store.persist_node_result(pool, workflow_id=wid, execution_id=eid, node_id=nid, output=out)
            start = time.monotonic()
            latest = await store.read_latest_node_outputs(pool, wid)
            elapsed = time.monotonic() - start
        assert latest == outputs
        assert elapsed < 0.07, (
            f"CAS read appears sequential ({elapsed * 1000:.0f}ms for 4 x 25ms "
            "chunks — should parallelize via asyncio.gather)"
        )

    async def test_history_single_flights_shared_chunks(self, postgres_db):
        """History entries of one node share chunks under content addressing.
        Reassembling 3 entries whose outputs embed the same >threshold value
        must download that chunk from R2 exactly ONCE across the gather, not
        once per entry — the duplicate-GET fan-out behind the 2026-07-13
        carousel cascade."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        shared = list(range(2000))  # >4KB → its own content-addressed chunk
        fake = FakeR2()
        with patch_r2(fake):
            for i in range(3):
                eid = await _exec(postgres_db, wid)
                await store.persist_node_result(
                    pool, workflow_id=wid, execution_id=eid, node_id="n1",
                    output={"shared": shared, "i": i})
                await _set_created(postgres_db, eid, "n1", T0 + timedelta(minutes=i))
            fake.get_counts.clear()
            hist = await store.read_node_output_history(pool, wid, "n1", limit=3)
        assert [h["output"]["i"] for h in hist] == [2, 1, 0]
        assert all(h["output"]["shared"] == shared for h in hist)
        shared_hash = hash_bytes(canonicalize(shared))
        assert fake.get_counts.get(shared_hash) == 1, (
            f"shared chunk fetched {fake.get_counts.get(shared_hash)}x — "
            "expected single-flight dedup across concurrent reassemblies")
        assert all(c == 1 for c in fake.get_counts.values())

    async def test_nested_structural_output_roundtrips_and_refs_full_set(self, postgres_db):
        """A >T output whose reduced skeleton is itself >T produces NESTED chunks
        (placeholders inside chunk bytes). Persist must ref the FULL transitive set
        (not just the manifest's top-level refs) so GC can't orphan a nested chunk,
        and read must BFS the closure to reassemble exactly."""
        import json as _json
        from utils.cas.chunking import referenced_hashes
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)
        inner = list(range(2000))                     # ~9KB → its own chunk
        output = {f"k{i}": inner for i in range(60)}  # reduced skeleton also >4KB → nested
        with patch_r2(FakeR2()):
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output=output)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
            rows = await postgres_db.fetch(
                "SELECT chunk_hash FROM cas_refs WHERE execution_id=$1 AND node_id='n1'", eid)
            manifest = await postgres_db.fetchval(
                "SELECT manifest FROM cas_manifests WHERE execution_id=$1 AND node_id='n1'", eid)
        assert got == output                          # BFS reassembly resolves nesting
        ref_hashes = {r["chunk_hash"] for r in rows}
        top_refs = referenced_hashes(_json.loads(manifest) if isinstance(manifest, str) else manifest)
        # safeguard A: cas_refs holds chunks beyond the manifest's top-level refs
        assert top_refs < ref_hashes and len(ref_hashes) >= 2

    async def test_latest_node_output_meta_and_presence(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)
        with patch_r2(FakeR2()):
            await store.persist_node_result(pool, workflow_id=wid, execution_id=eid, node_id="n1", output={"v": 1})
            await store.persist_node_result(pool, workflow_id=wid, execution_id=eid, node_id="n2", status="error", error="x")
            meta = await store.read_latest_node_output_meta(pool, wid, "n1")
            present = await store.read_nodes_with_output(pool, wid, ["n1", "n2", "missing"])
        assert meta["output"] == {"v": 1}
        assert isinstance(meta["created_at"], str)  # isoformat timestamp
        assert await store.read_latest_node_output_meta(pool, wid, "missing") is None
        # n2 is status-only (no manifest) → not "with output"; n1 is
        assert present == {"n1"}

    async def test_missing_nested_chunk_degrades_with_sibling_survival(self, postgres_db):
        """A >T output whose reduced skeleton is itself >T nests TWO distinct
        chunks under the top chunk (30 'a*' slots share one list value, 30 'b*'
        slots share another). Full read round-trips. Deleting exactly ONE nested
        chunk (keeping the top + the sibling) degrades only the slots backed by
        the deleted chunk to the pruned placeholder via the store's BFS; the
        sibling slots keep real data and no exception is raised."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)
        a_val, b_val = list(range(2000)), list(range(2000, 4000))
        output = {**{f"a{i}": a_val for i in range(30)},
                  **{f"b{i}": b_val for i in range(30)}}
        with patch_r2(FakeR2()) as fake:
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output=output)
            assert await store.read_node_output(pool, execution_id=eid, node_id="n1") == output
            # delete exactly ONE nested chunk (the 'a*' list value), keep top + sibling
            a_hash = hash_bytes(canonicalize(a_val))
            assert a_hash in fake.objects
            del fake.objects[a_hash]
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert all(got[f"a{i}"] == PRUNED_PLACEHOLDER for i in range(30))  # backed by deleted chunk
        assert all(got[f"b{i}"] == b_val for i in range(30))              # sibling survives

    async def test_read_node_output_cross_workflow_scoping(self, postgres_db):
        """read_node_output(workflow_id=...) is defense-in-depth scoping: a
        manifest persisted under wid1 reads back for wid1, is invisible to wid2
        (a different workflow that happens to probe the same execution_id), and
        is returned when the read is unscoped."""
        pool = _SingleConnPool(postgres_db)
        wid1, wid2 = await _wf(postgres_db), await _wf(postgres_db)
        eid = await _exec(postgres_db, wid1)
        output = {"v": 42}
        with patch_r2(FakeR2()):
            await store.persist_node_result(
                pool, workflow_id=wid1, execution_id=eid, node_id="n1", output=output)
            scoped = await store.read_node_output(
                pool, execution_id=eid, node_id="n1", workflow_id=wid1)
            wrong_wf = await store.read_node_output(
                pool, execution_id=eid, node_id="n1", workflow_id=wid2)
            unscoped = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert scoped == output
        assert wrong_wf is None
        assert unscoped == output

    async def test_read_graph_roundtrip_degradation_and_absence(self, postgres_db):
        """read_graph round-trips a snapshot; degrades to the pruned placeholder
        when the snapshot blob is gone (never raises); returns None for an
        execution that was never snapshotted."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)
        never = await _exec(postgres_db, wid)
        graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"from": "a", "to": "b"}]}
        with patch_r2(FakeR2()) as fake:
            await store.persist_graph_snapshot(pool, workflow_id=wid, execution_id=eid, graph=graph)
            assert await store.read_graph(pool, execution_id=eid) == graph
            fake.objects.clear()  # snapshot blob GC'd
            degraded = await store.read_graph(pool, execution_id=eid)
            absent = await store.read_graph(pool, execution_id=never)
        assert degraded == PRUNED_PLACEHOLDER
        assert absent is None

    async def test_cas_placeholder_collision_degrades_to_pruned(self, postgres_db):
        """ACCEPTED, DOCUMENTED limitation (astronomically unlikely): a genuine
        output value literally shaped like a CAS pointer ({"$cas": <64-hex>}) is
        misread as a placeholder on reassemble and degrades to the pruned marker
        (a fetch miss → "not retained"), never to corruption. This PINS the
        current behavior; do NOT change production code to 'fix' it."""
        pool = _SingleConnPool(postgres_db)
        wid = await _wf(postgres_db)
        eid = await _exec(postgres_db, wid)
        collide = {"$cas": "a" * 64}  # small → inlined verbatim into the manifest
        with patch_r2(FakeR2()):
            await store.persist_node_result(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output=collide)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert got == PRUNED_PLACEHOLDER
