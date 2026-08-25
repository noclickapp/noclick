"""Unit tests for backend/utils/cas/store.py — CAS write + read.

Real Postgres (testcontainer, rolled-back per test) + the stateful R2 fake, so
write→read is genuinely exercised. Asserts the ordering/idempotency/dedup
invariants and the benign crash-before-commit window.
"""

import uuid
from unittest.mock import patch

import pytest

from tests.mocks.mock_r2 import FakeR2, patch_r2
from utils.cas import store
from utils.cas.chunking import PRUNED_PLACEHOLDER

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _SingleConnPool:
    """Pool shim returning one real asyncpg connection; store's inner
    transaction() nests as a savepoint inside the fixture's rolled-back txn."""

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


async def _make_workflow_execution(conn, workflow_id=None):
    """Create a workflow + one execution for it. Pass workflow_id to attach
    a new execution to an existing workflow (e.g. for multi-run dedup tests)."""
    eid = uuid.uuid4()
    if workflow_id is None:
        wid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO workflows (id, owner_id, name) VALUES ($1,$2,'cas')",
            wid, TEST_USER_ID)
    else:
        wid = workflow_id
    await conn.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status) "
        "VALUES ($1,$2,$3,'completed')", eid, wid, TEST_USER_ID)
    return wid, eid


async def _counts(conn, eid):
    blobs = await conn.fetchval("SELECT count(*) FROM cas_blobs")
    refs = await conn.fetchval("SELECT count(*) FROM cas_refs WHERE execution_id=$1", eid)
    mans = await conn.fetchval("SELECT count(*) FROM cas_manifests WHERE execution_id=$1", eid)
    return blobs, refs, mans


@pytest.mark.asyncio
class TestCasStore:
    async def test_small_output_inlined(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        fake = FakeR2()
        output = {"msg": "hi", "n": 3}
        with patch_r2(fake):
            await store.persist_node_output(
                pool, workflow_id=wid, execution_id=eid, node_id="n1", output=output)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert got == output
        blobs, refs, mans = await _counts(postgres_db, eid)
        assert (blobs, refs, mans) == (0, 0, 1)   # inline: manifest only
        assert fake.objects == {}                  # no R2 PUT for inline

    async def test_large_output_roundtrip(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        fake = FakeR2()
        output = {"values": list(range(2000))}
        with patch_r2(fake):
            await store.persist_node_output(
                pool, workflow_id=wid, execution_id=eid, node_id="n1",
                output=output, threshold=4096)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert got == output
        blobs, refs, mans = await _counts(postgres_db, eid)
        assert (blobs, refs, mans) == (1, 1, 1)
        assert len(fake.objects) == 1

    async def test_idempotent_repersist(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        fake = FakeR2()
        output = {"values": list(range(2000))}
        with patch_r2(fake):
            await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=output, threshold=4096)
            await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=output, threshold=4096)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert got == output
        blobs, refs, mans = await _counts(postgres_db, eid)
        assert (blobs, refs, mans) == (1, 1, 1)
        # second persist saw the receipt and skipped the PUT
        assert all(c == 1 for c in fake.put_counts.values())

    async def test_dedup_identical_content_across_executions(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid, e1 = await _make_workflow_execution(postgres_db)
        e2 = uuid.uuid4()
        await postgres_db.execute(
            "INSERT INTO workflow_executions (id, workflow_id, user_id, status) "
            "VALUES ($1,$2,$3,'completed')", e2, wid, TEST_USER_ID)
        fake = FakeR2()
        output = {"values": list(range(2000))}
        with patch_r2(fake):
            await store.persist_node_output(pool, workflow_id=wid, execution_id=e1,
                                            node_id="n1", output=output, threshold=4096)
            await store.persist_node_output(pool, workflow_id=wid, execution_id=e2,
                                            node_id="n1", output=output, threshold=4096)
        assert await postgres_db.fetchval("SELECT count(*) FROM cas_blobs") == 1  # one chunk
        assert len(fake.objects) == 1                                            # one R2 object
        assert await postgres_db.fetchval("SELECT count(*) FROM cas_refs") == 2  # two refs
        assert await postgres_db.fetchval("SELECT count(*) FROM cas_manifests") == 2

    async def test_crash_before_commit_is_benign(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        fake = FakeR2()
        output = {"values": list(range(2000))}
        with patch_r2(fake), patch.object(
            store, "_commit_node", side_effect=RuntimeError("crash before commit")
        ):
            with pytest.raises(RuntimeError):
                await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                                node_id="n1", output=output, threshold=4096)
            # DB has no manifest/ref/receipt → read is None (run shows not-replayable)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert got is None
        blobs, refs, mans = await _counts(postgres_db, eid)
        assert (blobs, refs, mans) == (0, 0, 0)
        # The R2 object WAS written (PUT precedes commit). It is an untracked
        # orphan (no receipt) — a benign storage leak, not a dangling ref;
        # reclaimed when the content recurs or by a periodic R2 reconcile.
        assert len(fake.objects) == 1

    async def test_graph_snapshot_written_once(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        fake = FakeR2()
        original = {"nodes": [{"id": "a"}], "edges": []}
        edited = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
        with patch_r2(fake):
            h1 = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid, graph=original)
            # simulate resume re-snapshotting a post-edit graph
            h2 = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid, graph=edited)
            got = await store.read_graph(pool, execution_id=eid)
        assert h1 == h2          # second call short-circuits
        assert got == original   # snapshot is the run-start graph, not the edit

    async def test_graph_snapshot_strips_volatile_fields_so_dedup_holds(self, postgres_db):
        """Two runs of the SAME workflow must produce ONE blob, even when the
        FE bakes per-run runtime fields (output, executionState, _lastRunStatus,
        _lastRunAt, error) into node.data between runs.

        This is the bug the Newsletter workflow surfaced: 1914 runs → 1914
        distinct graph chunks (~51 MB) because executionState / output /
        _lastRunStatus differed every snapshot. Stripping the persist:false
        runtime fields before canonicalize restores per-workflow dedup."""
        pool = _SingleConnPool(postgres_db)
        wid, eid1 = await _make_workflow_execution(postgres_db)
        _wid2, eid2 = await _make_workflow_execution(postgres_db, workflow_id=wid)
        # Same structure, different per-run runtime state on each node.
        run_a = {"nodes": [{
            "id": "a", "type": "automation-slack",
            "position": {"x": 0, "y": 0},
            "data": {
                "config": {"channel": "#dev"},
                "output": {"sent": 1},
                "executionState": "completed",
                "_lastRunStatus": "completed",
                "_lastRunAt": 1717420000000,
            },
        }], "edges": []}
        run_b = {"nodes": [{
            "id": "a", "type": "automation-slack",
            "position": {"x": 0, "y": 0},
            "data": {
                "config": {"channel": "#dev"},
                "output": {"sent": 2},                 # different
                "executionState": "error",             # different
                "_lastRunStatus": "error",             # different
                "_lastRunAt": 1717430000000,           # different
                "error": "rate limited",               # different
            },
        }], "edges": []}
        with patch_r2(FakeR2()):
            h_a = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid1, graph=run_a)
            h_b = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid2, graph=run_b)
        assert h_a == h_b, "identical workflow structure must hash identically across runs"
        async with pool.acquire() as conn:
            blob_count = await conn.fetchval(
                "SELECT count(*) FROM cas_blobs WHERE hash = $1", h_a)
            ref_count = await conn.fetchval(
                "SELECT count(*) FROM cas_refs WHERE chunk_hash = $1", h_a)
        assert blob_count == 1, "only one blob for the shared graph"
        assert ref_count == 2, "each run holds its own ref to the shared blob"

    async def test_graph_snapshot_strip_preserves_structural_fields(self, postgres_db):
        """Stripping must NOT remove fields the replay needs to render: config,
        credentials, label, disabled, mockedOutput. Two graphs that differ in
        those fields MUST hash differently."""
        pool = _SingleConnPool(postgres_db)
        wid, eid1 = await _make_workflow_execution(postgres_db)
        _wid2, eid2 = await _make_workflow_execution(postgres_db, workflow_id=wid)
        run_a = {"nodes": [{"id": "a", "type": "x", "data": {
            "config": {"channel": "#dev"}, "label": "Send", "disabled": False,
            "credentialIds": {"slack": "cred-1"},
        }}], "edges": []}
        run_b = {"nodes": [{"id": "a", "type": "x", "data": {
            "config": {"channel": "#prod"},                # different config
            "label": "Send", "disabled": False,
            "credentialIds": {"slack": "cred-1"},
        }}], "edges": []}
        with patch_r2(FakeR2()):
            h_a = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid1, graph=run_a)
            h_b = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid2, graph=run_b)
        assert h_a != h_b, "config differences MUST change the snapshot hash"

    async def test_graph_snapshot_strips_trigger_payload_so_cron_dedups(self, postgres_db):
        """Webhook routes write the live trigger payload (HTTP headers, cron
        schedule_id, triggered_at, ...) into the trigger node's config as
        ``_triggerPayload`` on every fire. Newsletter showed this single field
        producing 1914 distinct graph chunks (~51 MB).

        The strip drops `_`-prefixed config keys (codebase convention =
        internal/runtime), keeping the explicit allowlist (`_settings`)."""
        pool = _SingleConnPool(postgres_db)
        wid, eid1 = await _make_workflow_execution(postgres_db)
        _wid2, eid2 = await _make_workflow_execution(postgres_db, workflow_id=wid)

        # Same trigger node config across runs — only the per-fire payload differs.
        def trigger_node(payload):
            return {"id": "tg", "type": "gmail-trigger", "data": {
                "config": {
                    "interval_ms": 60000,
                    "_settings": {"onError": "fail"},  # user-set, MUST survive
                    "_triggerPayload": payload,        # runtime, MUST be stripped
                    "_error_inputs": {"upstream_n1": "missing"},  # runtime, MUST be stripped
                },
                "label": "Gmail Trigger",
            }}
        run_a = {"nodes": [trigger_node({
            "_webhook": {"headers": {"cf-ray": "abc-IAD"}},
            "schedule_id": "f721eaf3-ada2-42dd-9e0e-373eb4fe4bba",
            "triggered_at": "2026-06-04T06:50:00.173Z",
        })], "edges": []}
        run_b = {"nodes": [trigger_node({
            "_webhook": {"headers": {"cf-ray": "xyz-IAD"}},  # new ray id
            "schedule_id": "68dba2f6-0f1e-476c-b22f-772c7a34e305",  # new schedule fire
            "triggered_at": "2026-06-04T06:51:00.182Z",      # new ts
        })], "edges": []}

        with patch_r2(FakeR2()):
            h_a = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid1, graph=run_a)
            h_b = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid2, graph=run_b)
        assert h_a == h_b, (
            "two cron fires of the same workflow must hash identically — "
            "_triggerPayload is runtime, not config"
        )

    async def test_graph_snapshot_strip_keeps_user_settings(self, postgres_db):
        """`_settings` is the one `_`-prefixed config field that's USER-set
        (per-node behaviour: onError handling, etc.). It MUST survive the
        strip — changing it has to change the snapshot hash."""
        pool = _SingleConnPool(postgres_db)
        wid, eid1 = await _make_workflow_execution(postgres_db)
        _wid2, eid2 = await _make_workflow_execution(postgres_db, workflow_id=wid)
        run_a = {"nodes": [{"id": "n", "type": "x", "data": {
            "config": {"channel": "#dev", "_settings": {"onError": "fail"}},
        }}], "edges": []}
        run_b = {"nodes": [{"id": "n", "type": "x", "data": {
            "config": {"channel": "#dev",
                       "_settings": {"onError": "continueErrorOutput"}},  # user changed setting
        }}], "edges": []}
        with patch_r2(FakeR2()):
            h_a = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid1, graph=run_a)
            h_b = await store.persist_graph_snapshot(
                pool, workflow_id=wid, execution_id=eid2, graph=run_b)
        assert h_a != h_b, "_settings is user config — must change the hash"

    async def test_read_missing_chunk_degrades(self, postgres_db):
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        fake = FakeR2()
        output = {"values": list(range(2000))}
        with patch_r2(fake):
            await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=output, threshold=4096)
            fake.objects.clear()  # simulate the chunk having been GC'd
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
        assert got == {"values": PRUNED_PLACEHOLDER}

    async def test_changed_output_refs_reconcile_as_delta(self, postgres_db):
        """Re-persisting the SAME node with a different >T output reconciles
        cas_refs as a delta: the old chunk ref is DELETED and the new one
        inserted (so GC can reclaim the now-unreferenced old chunk), while the
        manifest row is upserted in place (still exactly one row)."""
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        a = {"v": list(range(2000))}            # chunks → hA
        b = {"v": list(range(2000, 4000))}      # chunks → hB (hA != hB)
        with patch_r2(FakeR2()):
            await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=a, threshold=4096)
            refs_a = {r["chunk_hash"] for r in await postgres_db.fetch(
                "SELECT chunk_hash FROM cas_refs WHERE execution_id=$1 AND node_id='n1'", eid)}
            await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=b, threshold=4096)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
            refs_b = {r["chunk_hash"] for r in await postgres_db.fetch(
                "SELECT chunk_hash FROM cas_refs WHERE execution_id=$1 AND node_id='n1'", eid)}
        assert got == b
        assert len(refs_a) == 1 and len(refs_b) == 1
        assert refs_b.isdisjoint(refs_a)        # old ref deleted, new ref inserted
        mans = await postgres_db.fetchval(
            "SELECT count(*) FROM cas_manifests WHERE execution_id=$1 AND node_id='n1'", eid)
        assert mans == 1                         # manifest upserted in place

    async def test_status_output_transition_clears_then_reappears(self, postgres_db):
        """A node that had a >T output, then re-persisted as status-only
        (output omitted), drops its manifest to SQL NULL and deletes all its
        refs; read returns None. Persisting a fresh output revives both."""
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        output = {"v": list(range(2000))}
        with patch_r2(FakeR2()):
            await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=output, threshold=4096)
            blobs, refs, mans = await _counts(postgres_db, eid)
            assert (refs, mans) == (1, 1)
            manifest = await postgres_db.fetchval(
                "SELECT manifest FROM cas_manifests WHERE execution_id=$1 AND node_id='n1'", eid)
            assert manifest is not None

            # re-persist status-only (output left _UNSET) → manifest NULL, refs gone
            await store.persist_node_result(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=store._UNSET, status="skipped")
            manifest = await postgres_db.fetchval(
                "SELECT manifest FROM cas_manifests WHERE execution_id=$1 AND node_id='n1'", eid)
            status = await postgres_db.fetchval(
                "SELECT last_run_status FROM cas_manifests WHERE execution_id=$1 AND node_id='n1'", eid)
            refs = await postgres_db.fetchval(
                "SELECT count(*) FROM cas_refs WHERE execution_id=$1 AND node_id='n1'", eid)
            got = await store.read_node_output(pool, execution_id=eid, node_id="n1")
            assert manifest is None
            assert status == "skipped"
            assert refs == 0
            assert got is None

            # a fresh output revives the manifest + refs
            await store.persist_node_output(pool, workflow_id=wid, execution_id=eid,
                                            node_id="n1", output=output, threshold=4096)
            got2 = await store.read_node_output(pool, execution_id=eid, node_id="n1")
            _, refs2, mans2 = await _counts(postgres_db, eid)
        assert got2 == output
        assert (refs2, mans2) == (1, 1)

    async def test_persist_run_outputs_routes_outputs_and_statuses(self, postgres_db):
        """persist_run_outputs writes the union of node_outputs and node_statuses:
        an output-only node (no status), an output+status node, and a status-only
        node (no output → manifest NULL, read None). Returns the row count."""
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        node_outputs = {"a": {"x": 1}, "b": {"big": list(range(2000))}}
        node_statuses = {"b": {"status": "completed"}, "c": {"status": "skipped", "error": None}}
        with patch_r2(FakeR2()):
            n = await store.persist_run_outputs(
                pool, workflow_id=wid, execution_id=eid,
                node_outputs=node_outputs, node_statuses=node_statuses, threshold=4096)
            out_a = await store.read_node_output(pool, execution_id=eid, node_id="a")
            out_b = await store.read_node_output(pool, execution_id=eid, node_id="b")
            out_c = await store.read_node_output(pool, execution_id=eid, node_id="c")
        assert n == 3
        assert out_a == {"x": 1}
        assert out_b == {"big": list(range(2000))}
        assert out_c is None                     # status-only → no manifest
        # b has a manifest + 'completed' status; c is manifest-NULL 'skipped';
        # a is an output with no status (NULL last_run_status).
        rows = {r["node_id"]: r for r in await postgres_db.fetch(
            "SELECT node_id, last_run_status, manifest FROM cas_manifests WHERE execution_id=$1", eid)}
        assert rows["b"]["last_run_status"] == "completed" and rows["b"]["manifest"] is not None
        assert rows["c"]["last_run_status"] == "skipped" and rows["c"]["manifest"] is None
        assert rows["a"]["last_run_status"] is None and rows["a"]["manifest"] is not None

    async def test_late_persist_after_workflow_delete_is_clean_noop(self, postgres_db):
        """A fire-and-forget output persist can start after permanent deletion.
        It must neither raise an FK violation nor upload unreferenced chunks."""
        pool = _SingleConnPool(postgres_db)
        wid, eid = await _make_workflow_execution(postgres_db)
        await postgres_db.execute("DELETE FROM workflows WHERE id = $1", wid)
        fake = FakeR2()

        with patch_r2(fake):
            written = await store.persist_run_outputs(
                pool,
                workflow_id=wid,
                execution_id=eid,
                node_outputs={"a": {"big": list(range(2000))}},
                threshold=4096,
            )

        assert written == 0
        assert fake.objects == {}
        assert await postgres_db.fetchval(
            "SELECT count(*) FROM cas_manifests WHERE workflow_id = $1", wid
        ) == 0
