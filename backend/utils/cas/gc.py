"""CAS garbage collection — importable, phase-separable, overlap-safe workers.

Each worker is a plain ``async (pool, *, now=...) -> dict`` so tests invoke it
directly with a test pool and a controlled ``now`` (the injectable retention
clock — §6 of the Testing Plan). The scheduled worker is a thin shell over these.

- phase_a_retention: the ONLY thing that removes a reference. Prunes terminal
  runs past (14d OR 25k/workflow), exempting non-terminal + pending-approval
  runs; deletes cas_refs/cas_manifests then workflow_executions, and increments
  the monotonic workflow_run_totals ledger atomically with the delete.
- phase_b_orphan_sweep: condemns newly-unreferenced blobs (stamps orphaned_at),
  un-condemns re-referenced ones, and collects blobs orphaned past the grace
  window — deleting R2 objects BEFORE the cas_blobs rows (a crash leaves a
  re-collectible orphan, not an invisible R2 leak). Drain-loops to LIMIT.
- integrity_sweep: prunes dangling cas_refs (ref whose chunk_hash has no
  cas_blobs row) — the benign delete-race casualty cleanup.
- rollup_workflow_totals: folds a workflow's lifetime+live run counts into the
  global ledger row before the workflow is permanently deleted, so platform
  totals survive deletion.

Overlap-safe: Phase A's DELETE … RETURNING counts only rows it actually deletes,
so two concurrent runs never double-count; Phase B uses FOR UPDATE SKIP LOCKED so
concurrent runs don't fight over the same blobs. No advisory lock needed.
"""

from __future__ import annotations

import logging
import uuid as uuid_module
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils import r2_cloudflare
from utils.cas.store import R2_CAS_BUCKET

logger = logging.getLogger(__name__)

GLOBAL_TOTALS_ID = uuid_module.UUID(int=0)  # 0...0 row = platform totals
DEFAULT_MAX_AGE_DAYS = 14
DEFAULT_MAX_PER_WORKFLOW = 25_000
DEFAULT_ORPHAN_GRACE = timedelta(hours=1)
DEFAULT_SWEEP_BATCH = 5_000
DEFAULT_RETENTION_BATCH = 2_000

_TERMINAL = ("completed", "error")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _rowcount(status: str) -> int:
    """Parse asyncpg command tag like 'DELETE 3' / 'UPDATE 2'."""
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


async def phase_a_retention(
    pool, *, now: Optional[datetime] = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_per_workflow: int = DEFAULT_MAX_PER_WORKFLOW,
    batch: int = DEFAULT_RETENTION_BATCH,
) -> dict:
    """Prune terminal runs past retention; the sole reference-removal path.

    Drain-loops in bounded batches (each its own transaction) so a backlog can't
    push a single DELETE past the statement timeout. The batch SELECT re-derives
    the per-workflow ROW_NUMBER each iteration, so deleting the oldest excess
    converges; the age predicate is monotonic. Still overlap-safe: the
    workflow_executions DELETE … RETURNING counts only rows this txn deletes."""
    now = _now(now)
    cutoff = now - timedelta(days=max_age_days)

    total_pruned = 0
    affected: set = set()
    while True:
        async with pool.acquire() as conn:
            async with conn.transaction():
                prunable = await conn.fetch(
                    """
                    WITH terminal AS (
                        SELECT id, workflow_id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY workflow_id ORDER BY started_at DESC
                               ) AS rn,
                               started_at
                        FROM workflow_executions we
                        WHERE status = ANY($1)
                          AND NOT EXISTS (
                              SELECT 1 FROM approval_requests a
                              WHERE a.execution_id = we.id AND a.status = 'pending')
                    )
                    SELECT id, workflow_id FROM terminal
                    WHERE started_at < $2 OR rn > $3
                    LIMIT $4
                    """,
                    list(_TERMINAL), cutoff, max_per_workflow, batch,
                )
                if not prunable:
                    break

                ids = [r["id"] for r in prunable]
                # CAS keys by the REAL execution_id (iteration sub-outputs use a
                # composite node_id, never a synthetic execution_id), so pruning by
                # execution_id reaches all of a run's refs/manifests.
                await conn.execute("DELETE FROM cas_refs WHERE execution_id = ANY($1)", ids)
                await conn.execute("DELETE FROM cas_manifests WHERE execution_id = ANY($1)", ids)
                deleted = await conn.fetch(
                    "DELETE FROM workflow_executions WHERE id = ANY($1) RETURNING workflow_id",
                    ids,
                )
                per_wf = Counter(r["workflow_id"] for r in deleted)
                if per_wf:
                    await conn.executemany(
                        """
                        INSERT INTO workflow_run_totals
                            (workflow_id, executions_total, last_cleanup_at)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (workflow_id) DO UPDATE
                            SET executions_total =
                                workflow_run_totals.executions_total + EXCLUDED.executions_total,
                                last_cleanup_at = EXCLUDED.last_cleanup_at
                        """,
                        [(wf, n, now) for wf, n in per_wf.items()],
                    )
                    total = sum(per_wf.values())
                    await conn.execute(
                        """
                        INSERT INTO workflow_run_totals
                            (workflow_id, executions_total, last_cleanup_at)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (workflow_id) DO UPDATE
                            SET executions_total =
                                workflow_run_totals.executions_total + EXCLUDED.executions_total,
                                last_cleanup_at = EXCLUDED.last_cleanup_at
                        """,
                        GLOBAL_TOTALS_ID, total, now,
                    )
                total_pruned += len(ids)
                affected.update(per_wf)
        if len(prunable) < batch:
            break
    return {"pruned_executions": total_pruned, "workflows_affected": len(affected)}


async def phase_b_orphan_sweep(
    pool, *, now: Optional[datetime] = None,
    grace: timedelta = DEFAULT_ORPHAN_GRACE,
    batch: int = DEFAULT_SWEEP_BATCH,
) -> dict:
    """Condemn/un-condemn blobs by reference state, then collect those orphaned
    past the grace window (R2 objects deleted before rows)."""
    now = _now(now)
    grace_cutoff = now - grace

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE cas_blobs SET orphaned_at = $1 "
            "WHERE orphaned_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM cas_refs r WHERE r.chunk_hash = cas_blobs.hash)",
            now,
        )
        await conn.execute(
            "UPDATE cas_blobs SET orphaned_at = NULL "
            "WHERE orphaned_at IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM cas_refs r WHERE r.chunk_hash = cas_blobs.hash)"
        )

    deleted_blobs = 0
    bytes_reclaimed = 0
    while True:
        async with pool.acquire() as conn:
            async with conn.transaction():
                dead = await conn.fetch(
                    "SELECT hash, size_bytes FROM cas_blobs "
                    "WHERE orphaned_at < $1 "
                    "AND NOT EXISTS (SELECT 1 FROM cas_refs r WHERE r.chunk_hash = cas_blobs.hash) "
                    "LIMIT $2 FOR UPDATE SKIP LOCKED",
                    grace_cutoff, batch,
                )
                if not dead:
                    break
                keys = [r["hash"] for r in dead]
                # R2 objects FIRST, then rows (crash → re-collectible orphan).
                # The R2 delete deliberately runs INSIDE the row-locked
                # transaction: a concurrent same-content writer's blob INSERT
                # blocks on the FOR UPDATE lock, so it can't dedupe-hit (skip
                # its R2 upload) against a row we're about to delete, and we
                # can't delete an object it just re-uploaded. Moving this HTTP
                # call out of the transaction reintroduces that data-loss race.
                # Holding a conn across HTTP is contained here: the sweep runs
                # only in the daily_maintenance cron on its own small pool.
                await r2_cloudflare.delete_files_from_r2_async_native(R2_CAS_BUCKET, keys)
                await conn.execute("DELETE FROM cas_blobs WHERE hash = ANY($1)", keys)
        deleted_blobs += len(keys)
        bytes_reclaimed += sum(r["size_bytes"] for r in dead)
        if len(keys) < batch:
            break

    if bytes_reclaimed:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO workflow_run_totals (workflow_id, bytes_reclaimed, last_cleanup_at) "
                "VALUES ($1, $2, $3) ON CONFLICT (workflow_id) DO UPDATE "
                "SET bytes_reclaimed = workflow_run_totals.bytes_reclaimed + EXCLUDED.bytes_reclaimed, "
                "last_cleanup_at = EXCLUDED.last_cleanup_at",
                GLOBAL_TOTALS_ID, bytes_reclaimed, now,
            )
    return {"deleted_blobs": deleted_blobs, "bytes_reclaimed": bytes_reclaimed}


async def integrity_sweep(pool) -> dict:
    """Prune dangling refs (chunk_hash with no cas_blobs row) — the benign
    delete-race casualties. Their reads already degrade to 'not retained'."""
    async with pool.acquire() as conn:
        status = await conn.execute(
            "DELETE FROM cas_refs WHERE NOT EXISTS "
            "(SELECT 1 FROM cas_blobs b WHERE b.hash = cas_refs.chunk_hash)"
        )
    return {"pruned_dangling_refs": _rowcount(status)}


async def rollup_workflow_totals(pool, workflow_id) -> None:
    """Fold a workflow's lifetime + live run counts into the global ledger row
    before the workflow is permanently deleted (call from the deletion path,
    before the cascade removes its executions)."""
    wf = workflow_id if isinstance(workflow_id, uuid_module.UUID) else uuid_module.UUID(str(workflow_id))
    async with pool.acquire() as conn:
        async with conn.transaction():
            live = await conn.fetchval(
                "SELECT count(*) FROM workflow_executions WHERE workflow_id = $1", wf)
            prior = await conn.fetchval(
                "SELECT executions_total FROM workflow_run_totals WHERE workflow_id = $1", wf) or 0
            total = int(live) + int(prior)
            if total:
                await conn.execute(
                    "INSERT INTO workflow_run_totals (workflow_id, executions_total) "
                    "VALUES ($1, $2) ON CONFLICT (workflow_id) DO UPDATE "
                    "SET executions_total = workflow_run_totals.executions_total + EXCLUDED.executions_total",
                    GLOBAL_TOTALS_ID, total,
                )
            await conn.execute(
                "DELETE FROM workflow_run_totals WHERE workflow_id = $1", wf)
