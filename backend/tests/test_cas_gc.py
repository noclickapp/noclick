"""Unit/integration tests for backend/utils/cas/gc.py.

GC spans connections (writer vs GC), so these use a COMMITTED pool (not the
rolled-back postgres_db fixture) with TRUNCATE teardown. Time is controlled by
passing ``now`` into the workers (the injectable retention clock).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.fixtures.cas_fixtures import cas_pool, TEST_USER_ID  # noqa: F401
from tests.mocks.mock_r2 import FakeR2, patch_r2
from utils.cas import gc, store

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


async def _workflow(pool):
    wid = uuid.uuid4()
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO workflows (id, owner_id, name) VALUES ($1,$2,'gc')",
            wid, TEST_USER_ID)
    return wid


async def _execution(pool, wid, *, status="completed", started_at=NOW):
    eid = uuid.uuid4()
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO workflow_executions (id, workflow_id, user_id, status, started_at) "
            "VALUES ($1,$2,$3,$4,$5)", eid, wid, TEST_USER_ID, status, started_at)
    return eid


async def _scalar(pool, sql, *args):
    async with pool.acquire() as c:
        return await c.fetchval(sql, *args)


async def _fetchall(pool, sql, *args):
    async with pool.acquire() as c:
        return await c.fetch(sql, *args)


@pytest.mark.asyncio
class TestPhaseA:
    async def test_prunes_by_age_and_increments_ledger(self, cas_pool):
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        old = await _execution(cas_pool, wid, started_at=NOW - timedelta(days=20))
        recent = await _execution(cas_pool, wid, started_at=NOW)
        with patch_r2(fake):
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=old,
                                            node_id="n1", output={"v": list(range(2000))}, threshold=16)
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=recent,
                                            node_id="n1", output={"v": list(range(2000))}, threshold=16)
            res = await gc.phase_a_retention(cas_pool, now=NOW)
        assert res["pruned_executions"] == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM workflow_executions WHERE id=$1", old) == 0
        assert await _scalar(cas_pool, "SELECT count(*) FROM workflow_executions WHERE id=$1", recent) == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_refs WHERE execution_id=$1", old) == 0
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_manifests WHERE execution_id=$1", old) == 0
        # ledger: per-workflow + global both incremented by 1
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", wid) == 1
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", gc.GLOBAL_TOTALS_ID) == 1

    async def test_prunes_by_count(self, cas_pool):
        wid = await _workflow(cas_pool)
        for i in range(5):
            await _execution(cas_pool, wid, started_at=NOW - timedelta(minutes=5 - i))
        res = await gc.phase_a_retention(cas_pool, now=NOW, max_per_workflow=3)
        assert res["pruned_executions"] == 2
        assert await _scalar(cas_pool, "SELECT count(*) FROM workflow_executions WHERE workflow_id=$1", wid) == 3

    async def test_exempts_non_terminal(self, cas_pool):
        wid = await _workflow(cas_pool)
        for st in ("running", "awaiting_approval", "awaiting_delay"):
            await _execution(cas_pool, wid, status=st, started_at=NOW - timedelta(days=30))
        res = await gc.phase_a_retention(cas_pool, now=NOW)
        assert res["pruned_executions"] == 0
        assert await _scalar(cas_pool, "SELECT count(*) FROM workflow_executions WHERE workflow_id=$1", wid) == 3

    async def test_exempts_pending_approval(self, cas_pool):
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid, status="completed", started_at=NOW - timedelta(days=30))
        async with cas_pool.acquire() as c:
            await c.execute(
                "INSERT INTO approval_requests (id, workflow_id, execution_id, node_id, user_id, title, content, status) "
                "VALUES ($1,$2,$3,'n',$4,'t','c','pending')",
                uuid.uuid4(), wid, eid, TEST_USER_ID)
        res = await gc.phase_a_retention(cas_pool, now=NOW)
        assert res["pruned_executions"] == 0

    async def test_idempotent_overlap_no_double_count(self, cas_pool):
        wid = await _workflow(cas_pool)
        await _execution(cas_pool, wid, started_at=NOW - timedelta(days=20))
        await gc.phase_a_retention(cas_pool, now=NOW)
        await gc.phase_a_retention(cas_pool, now=NOW)  # second run is a no-op
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", gc.GLOBAL_TOTALS_ID) == 1

    async def test_ledger_conservation(self, cas_pool):
        # total = ledger + live is invariant across a prune
        wid = await _workflow(cas_pool)
        await _execution(cas_pool, wid, started_at=NOW - timedelta(days=20))
        await _execution(cas_pool, wid, started_at=NOW)
        before = await _scalar(cas_pool, "SELECT count(*) FROM workflow_executions WHERE workflow_id=$1", wid)
        await gc.phase_a_retention(cas_pool, now=NOW)
        ledger = await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", wid)
        live = await _scalar(cas_pool, "SELECT count(*) FROM workflow_executions WHERE workflow_id=$1", wid)
        assert ledger + live == before

    async def test_multi_batch_drain(self, cas_pool):
        # backlog larger than the batch size drains over multiple iterations,
        # counting each pruned run exactly once (no statement-timeout blowup).
        wid = await _workflow(cas_pool)
        for i in range(5):
            await _execution(cas_pool, wid, started_at=NOW - timedelta(days=20, minutes=i))
        res = await gc.phase_a_retention(cas_pool, now=NOW, batch=2)
        assert res["pruned_executions"] == 5
        assert await _scalar(cas_pool, "SELECT count(*) FROM workflow_executions WHERE workflow_id=$1", wid) == 0
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", wid) == 5
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", gc.GLOBAL_TOTALS_ID) == 5

    async def test_shared_nested_chunk_survives_partial_prune(self, cas_pool):
        # GAP 1 (CRITICAL): a nested chunk shared across two runs must survive
        # pruning of one run, and the still-live run must still reassemble whole.
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        execA = await _execution(cas_pool, wid, started_at=NOW - timedelta(days=20))  # old -> pruned
        execB = await _execution(cas_pool, wid, started_at=NOW)                        # recent -> kept
        shared = {"big": list(range(2000))}
        outA = {"shared": shared, "a": list(range(2000, 4000))}
        outB = {"shared": shared, "b": list(range(4000, 6000))}
        with patch_r2(fake):
            # Default threshold (4096): 'big' is its own nested chunk, distinct
            # from each run's exclusive per-key chunk.
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=execA,
                                            node_id="loop", output=outA)
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=execB,
                                            node_id="loop", output=outB)

            # The shared chunk = the hash present in BOTH executions' cas_refs.
            shared_hashes = [r["chunk_hash"] for r in await _fetchall(
                cas_pool,
                "SELECT chunk_hash FROM cas_refs WHERE execution_id=$1 "
                "INTERSECT SELECT chunk_hash FROM cas_refs WHERE execution_id=$2",
                execA, execB)]
            assert len(shared_hashes) == 1
            shared_hash = shared_hashes[0]
            a_exclusive = [r["chunk_hash"] for r in await _fetchall(
                cas_pool,
                "SELECT chunk_hash FROM cas_refs WHERE execution_id=$1 "
                "EXCEPT SELECT chunk_hash FROM cas_refs WHERE execution_id=$2",
                execA, execB)]
            assert len(a_exclusive) == 1
            a_hash = a_exclusive[0]

            # Prune A only, then sweep (condemn) + sweep past grace (collect).
            res = await gc.phase_a_retention(cas_pool, now=NOW)
            assert res["pruned_executions"] == 1
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))

            # Shared chunk survives (still referenced by execB); A's exclusive gone.
            assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", shared_hash) == 1
            assert fake.exists(shared_hash) is True
            assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", a_hash) == 0
            assert not fake.exists(a_hash)

            # execB still reassembles to the FULL value (no pruned placeholder).
            reassembled = await store.read_node_output(
                cas_pool, execution_id=execB, node_id="loop", workflow_id=wid)
            assert reassembled == outB

            # Now prune B too, then sweep -> the shared chunk is finally collected.
            await gc.phase_a_retention(cas_pool, now=NOW + timedelta(days=20))
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(days=20))
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(days=20, hours=2))
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", shared_hash) == 0
        assert not fake.exists(shared_hash)

    async def test_composite_iteration_node_pruned_with_execution(self, cas_pool):
        # GAP 2 (HIGH): iteration sub-outputs use a composite node_id under the
        # REAL execution_id, so pruning by execution_id reaches them all.
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid, started_at=NOW - timedelta(days=20))
        with patch_r2(fake):
            for node_id in ("loop", "loop#iter:0", "loop#iter:1"):
                await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid,
                                                node_id=node_id, output={"v": list(range(2000))})
            res = await gc.phase_a_retention(cas_pool, now=NOW)
        assert res["pruned_executions"] == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_manifests WHERE execution_id=$1", eid) == 0
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_refs WHERE execution_id=$1", eid) == 0

    async def test_multi_workflow_ledger_fan_out(self, cas_pool):
        # GAP 5 (MED): Phase A reports across workflows and the per-flow + global
        # ledgers fan out correctly (global summed once).
        wfA = await _workflow(cas_pool)
        wfB = await _workflow(cas_pool)
        for _ in range(2):
            await _execution(cas_pool, wfA, started_at=NOW - timedelta(days=20))
        for _ in range(3):
            await _execution(cas_pool, wfB, started_at=NOW - timedelta(days=20))
        res = await gc.phase_a_retention(cas_pool, now=NOW)
        assert res["pruned_executions"] == 5
        assert res["workflows_affected"] == 2
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", wfA) == 2
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", wfB) == 3
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", gc.GLOBAL_TOTALS_ID) == 5

    async def test_cas_collision_degrades_to_pruned_placeholder(self, cas_pool):
        # PINNED LIMITATION (accepted, documented): a genuine output value literally
        # shaped like {"$cas": <64-hex>} is indistinguishable from a chunk pointer.
        # On reassemble it is treated as a pointer to a (nonexistent) chunk and
        # degrades to PRUNED_PLACEHOLDER. This is an astronomically-unlikely
        # collision; we PIN the current behavior, we do NOT "fix" production code.
        from utils.cas.chunking import PRUNED_PLACEHOLDER
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        colliding = {"$cas": "a" * 64}  # valid 64-hex shape -> read as a pointer
        with patch_r2(fake):
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=colliding)
            reassembled = await store.read_node_output(
                cas_pool, execution_id=eid, node_id="n1", workflow_id=wid)
        assert reassembled == PRUNED_PLACEHOLDER


@pytest.mark.asyncio
class TestPhaseB:
    async def test_grace_then_collect_r2_before_row(self, cas_pool):
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        with patch_r2(fake):
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output={"v": list(range(2000))}, threshold=16)
            digest = await _scalar(cas_pool, "SELECT hash FROM cas_blobs LIMIT 1")
            # orphan it (simulate Phase A removing the ref)
            await cas_pool.execute("DELETE FROM cas_refs WHERE chunk_hash=$1", digest)

            # first sweep condemns but does not collect (within grace)
            r1 = await gc.phase_b_orphan_sweep(cas_pool, now=NOW)
            assert r1["deleted_blobs"] == 0
            assert await _scalar(cas_pool, "SELECT orphaned_at FROM cas_blobs WHERE hash=$1", digest) is not None
            assert fake.exists(digest)

            # second sweep, past grace → collected (R2 then row)
            r2 = await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))
        assert r2["deleted_blobs"] == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", digest) == 0
        assert fake.delete_counts.get(digest) == 1
        assert not fake.exists(digest)

    async def test_uncondemns_rereferenced(self, cas_pool):
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        with patch_r2(fake):
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output={"v": list(range(2000))}, threshold=16)
            digest = await _scalar(cas_pool, "SELECT hash FROM cas_blobs LIMIT 1")
            await cas_pool.execute("DELETE FROM cas_refs WHERE chunk_hash=$1", digest)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW)  # condemn
            # re-reference (identical content recurs on another execution)
            eid2 = await _execution(cas_pool, wid)
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid2,
                                            node_id="n1", output={"v": list(range(2000))}, threshold=16)
            r = await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))
        assert r["deleted_blobs"] == 0
        assert await _scalar(cas_pool, "SELECT orphaned_at FROM cas_blobs WHERE hash=$1", digest) is None

    async def test_r2_before_rows_crash_window(self, cas_pool):
        # GAP 3 (HIGH): R2 delete happens BEFORE the row delete; if the R2 delete
        # crashes the transaction rolls back, leaving a re-collectible orphan (row
        # + orphaned_at intact), never an invisible R2 leak / missing-blob ref.
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        with patch_r2(fake):
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output={"v": list(range(2000))})
            digest = await _scalar(cas_pool, "SELECT hash FROM cas_blobs LIMIT 1")
            await cas_pool.execute("DELETE FROM cas_refs WHERE chunk_hash=$1", digest)
            # condemn at NOW (stamps orphaned_at, committed before the drain loop)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW)

            fake.fail_delete_keys = {digest}
            with pytest.raises(RuntimeError):
                await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))
            # Row survives with orphaned_at still set (transaction rolled back).
            assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", digest) == 1
            assert await _scalar(cas_pool, "SELECT orphaned_at FROM cas_blobs WHERE hash=$1", digest) is not None

            # Recover: clear fault, re-run -> now collected for real.
            fake.fail_delete_keys = set()
            r = await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))
        assert r["deleted_blobs"] == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", digest) == 0
        assert not fake.exists(digest)
        assert fake.delete_counts.get(digest) == 2  # failed attempt + successful one

    async def test_multi_batch_drain_and_bytes_ledger(self, cas_pool):
        # GAP 4 (HIGH): the drain loop runs until under-LIMIT, bytes_reclaimed sums
        # collected blob sizes, and the global ledger accumulates (adds, not sets).
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        with patch_r2(fake):
            for i in range(3):
                await store.persist_node_output(
                    cas_pool, workflow_id=wid, execution_id=eid,
                    node_id=f"n{i}", output={"v": list(range(2000 * (i + 1), 2000 * (i + 2)))})
            digests = [r["hash"] for r in await _fetchall(cas_pool, "SELECT hash FROM cas_blobs")]
            assert len(digests) == 3
            total_bytes = await _scalar(cas_pool, "SELECT sum(size_bytes) FROM cas_blobs")
            # Orphan all refs, condemn.
            await cas_pool.execute("DELETE FROM cas_refs WHERE chunk_hash = ANY($1)", digests)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW)

            # batch=2 over 3 blobs -> drain loop iterates twice.
            res = await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2), batch=2)
        assert res["deleted_blobs"] == 3
        assert res["bytes_reclaimed"] == total_bytes
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs") == 0
        for d in digests:
            assert not fake.exists(d)
        assert await _scalar(
            cas_pool, "SELECT bytes_reclaimed FROM workflow_run_totals WHERE workflow_id=$1",
            gc.GLOBAL_TOTALS_ID) == total_bytes

        # A second sweep with a fresh reclaim ADDS to the ledger (not overwrites).
        fake2 = FakeR2()
        eid2 = await _execution(cas_pool, wid)
        with patch_r2(fake2):
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid2,
                                            node_id="m", output={"v": list(range(9000, 11000))})
            d2 = await _scalar(cas_pool, "SELECT hash FROM cas_blobs LIMIT 1")
            extra = await _scalar(cas_pool, "SELECT size_bytes FROM cas_blobs WHERE hash=$1", d2)
            await cas_pool.execute("DELETE FROM cas_refs WHERE chunk_hash=$1", d2)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))
        assert await _scalar(
            cas_pool, "SELECT bytes_reclaimed FROM workflow_run_totals WHERE workflow_id=$1",
            gc.GLOBAL_TOTALS_ID) == total_bytes + extra

    async def test_born_orphan_receipt_collected(self, cas_pool):
        # GAP 6 (MED): a cas_blobs row + R2 object with NO refs (crash-after-PUT,
        # before any ref was written) is condemned then collected like any orphan.
        fake = FakeR2()
        digest = "b" * 64
        body = b"orphan-payload"
        with patch_r2(fake):
            await fake.upload_bytes_to_r2_async(
                bucket=store.R2_CAS_BUCKET, key=digest, body=body, content_type="application/zstd")
            await cas_pool.execute(
                "INSERT INTO cas_blobs (hash, size_bytes) VALUES ($1, $2)", digest, len(body))
            assert fake.exists(digest)

            # condemn (no refs at all)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW)
            assert await _scalar(cas_pool, "SELECT orphaned_at FROM cas_blobs WHERE hash=$1", digest) is not None

            # collect past grace
            r = await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))
        assert r["deleted_blobs"] == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", digest) == 0
        assert not fake.exists(digest)


@pytest.mark.asyncio
class TestIntegrityAndDeletion:
    async def test_integrity_sweep_prunes_dangling_refs(self, cas_pool):
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        # a ref whose blob never existed (the benign race casualty)
        await cas_pool.execute(
            "INSERT INTO cas_refs (workflow_id, execution_id, node_id, chunk_hash) "
            "VALUES ($1,$2,'n1',$3)", wid, eid, "f" * 64)
        res = await gc.integrity_sweep(cas_pool)
        assert res["pruned_dangling_refs"] == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_refs WHERE execution_id=$1", eid) == 0

    async def test_rollup_on_delete_preserves_global(self, cas_pool):
        wid = await _workflow(cas_pool)
        await _execution(cas_pool, wid)
        await _execution(cas_pool, wid)
        # pretend 3 were already pruned earlier
        await cas_pool.execute(
            "INSERT INTO workflow_run_totals (workflow_id, executions_total) VALUES ($1, 3)", wid)
        await gc.rollup_workflow_totals(cas_pool, wid)
        # global = prior 3 + 2 live = 5; per-flow row gone
        assert await _scalar(cas_pool, "SELECT executions_total FROM workflow_run_totals WHERE workflow_id=$1", gc.GLOBAL_TOTALS_ID) == 5
        assert await _scalar(cas_pool, "SELECT count(*) FROM workflow_run_totals WHERE workflow_id=$1", wid) == 0

    async def test_deletion_reclaim_via_cascade_then_sweep(self, cas_pool):
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        with patch_r2(fake):
            await store.persist_node_output(cas_pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output={"v": list(range(2000))}, threshold=16)
            digest = await _scalar(cas_pool, "SELECT hash FROM cas_blobs LIMIT 1")
            # deleting the workflow cascades refs/manifests
            await cas_pool.execute("DELETE FROM workflows WHERE id=$1", wid)
            assert await _scalar(cas_pool, "SELECT count(*) FROM cas_refs WHERE chunk_hash=$1", digest) == 0
            # Phase B reclaims the now-orphaned blob + R2 object
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW)
            await gc.phase_b_orphan_sweep(cas_pool, now=NOW + timedelta(hours=2))
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", digest) == 0
        assert not fake.exists(digest)

    async def test_integrity_sweep_partial_dangling(self, cas_pool):
        # A multi-chunk output where ONE chunk's blob receipt is deleted out from
        # under the refs. integrity_sweep prunes only the dangling ref; the other
        # ref + its blob are untouched.
        fake = FakeR2()
        wid = await _workflow(cas_pool)
        eid = await _execution(cas_pool, wid)
        with patch_r2(fake):
            # Two distinct big lists at sibling keys -> two separate chunks.
            await store.persist_node_output(
                cas_pool, workflow_id=wid, execution_id=eid, node_id="n1",
                output={"a": list(range(2000)), "b": list(range(2000, 4000))})
        hashes = [r["hash"] for r in await _fetchall(
            cas_pool, "SELECT hash FROM cas_blobs ORDER BY hash")]
        assert len(hashes) >= 2
        gone, kept = hashes[0], hashes[1]
        # Drop one chunk's receipt -> its ref is now dangling.
        await cas_pool.execute("DELETE FROM cas_blobs WHERE hash=$1", gone)

        res = await gc.integrity_sweep(cas_pool)

        assert res["pruned_dangling_refs"] == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_refs WHERE chunk_hash=$1", gone) == 0
        # The OTHER ref + blob survive.
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_refs WHERE chunk_hash=$1", kept) == 1
        assert await _scalar(cas_pool, "SELECT count(*) FROM cas_blobs WHERE hash=$1", kept) == 1
