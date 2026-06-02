"""CAS storage observability — the rebuildable size/dedup stats cache + reads.

``cas_storage_stats`` is a CACHE (never truth): ``refresh_storage_stats`` recomputes
it wholesale, piggybacking on the GC cron (one extra aggregate pass over the same
warm cas_refs/cas_blobs/cas_manifests the GC already scans). The dashboard reads
the cache instantly; if it's ever wrong the next refresh fixes it.

The accounting model (dedup makes "size" two numbers):
- physical_bytes = SUM(size_bytes) over the DISTINCT blobs a flow references (a
  chunk shared by 20k runs counts once) — the real footprint.
- logical_bytes  = SUM(size_bytes) over EVERY reference — what the flow would cost
  WITHOUT the CAS.
- dedup ratio = logical / physical — the headline metric proving the CAS pays off
  (and the input that gates Slice 2 / Merkle chunking).

cas_refs.node_id splits a flow's bytes into graph snapshots ('__graph__') vs node
outputs for free. The authoritative GLOBAL physical total is SUM(size_bytes) FROM
cas_blobs (each blob once, including not-yet-collected orphans = real R2 footprint);
per-flow physical attributes a (rare) cross-flow shared blob fully to each flow.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.cas.gc import GLOBAL_TOTALS_ID

logger = logging.getLogger(__name__)

# The three CAS data tables whose on-disk size is the "Postgres bytes" total.
_PG_TABLES = ("cas_blobs", "cas_refs", "cas_manifests")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


async def refresh_storage_stats(pool, *, now: Optional[datetime] = None) -> dict:
    """Recompute cas_storage_stats wholesale (per-flow rows + the global row).
    Atomic: DELETE + INSERT in one transaction so a reader never sees it empty."""
    now = _now(now)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM cas_storage_stats")

            # Per-flow rows. A flow's universe of executions is union(refs, manifests):
            # status-only nodes have a manifest but no chunk ref, and every run that
            # started has a '__graph__' ref, so refs carries the execution count.
            await conn.execute(
                """
                WITH refs AS (
                    SELECT r.workflow_id AS wf, r.chunk_hash, r.execution_id,
                           (r.node_id = '__graph__') AS is_graph, b.size_bytes
                    FROM cas_refs r JOIN cas_blobs b ON b.hash = r.chunk_hash
                ),
                dist AS (SELECT DISTINCT wf, chunk_hash, is_graph, size_bytes FROM refs),
                phys AS (
                    SELECT wf,
                           SUM(size_bytes) AS physical_bytes,
                           COALESCE(SUM(size_bytes) FILTER (WHERE is_graph), 0) AS graph_bytes,
                           COALESCE(SUM(size_bytes) FILTER (WHERE NOT is_graph), 0) AS output_bytes,
                           COUNT(*) FILTER (WHERE is_graph) AS distinct_graphs,
                           COUNT(*) AS chunk_count
                    FROM dist GROUP BY wf
                ),
                logi AS (
                    SELECT wf, SUM(size_bytes) AS logical_bytes,
                           COUNT(DISTINCT execution_id) AS exec_from_refs
                    FROM refs GROUP BY wf
                ),
                manif AS (
                    SELECT workflow_id AS wf,
                           COALESCE(SUM(pg_column_size(manifest)), 0) AS manifest_bytes,
                           COUNT(DISTINCT execution_id) AS exec_from_manifests
                    FROM cas_manifests GROUP BY workflow_id
                ),
                universe AS (SELECT wf FROM phys UNION SELECT wf FROM manif)
                INSERT INTO cas_storage_stats (
                    workflow_id, physical_bytes, logical_bytes, graph_bytes,
                    output_bytes, manifest_bytes, execution_count, distinct_graphs,
                    chunk_count, computed_at)
                SELECT u.wf,
                       COALESCE(phys.physical_bytes, 0), COALESCE(logi.logical_bytes, 0),
                       COALESCE(phys.graph_bytes, 0), COALESCE(phys.output_bytes, 0),
                       COALESCE(manif.manifest_bytes, 0),
                       GREATEST(COALESCE(logi.exec_from_refs, 0),
                                COALESCE(manif.exec_from_manifests, 0)),
                       COALESCE(phys.distinct_graphs, 0), COALESCE(phys.chunk_count, 0), $1
                FROM universe u
                LEFT JOIN phys ON phys.wf = u.wf
                LEFT JOIN logi ON logi.wf = u.wf
                LEFT JOIN manif ON manif.wf = u.wf
                """,
                now,
            )

            # Global row. physical_bytes is authoritative from cas_blobs (each blob
            # once, incl. uncollected orphans = true R2 footprint); the per-flow
            # split is over globally-distinct chunks.
            await conn.execute(
                """
                WITH refs AS (
                    SELECT r.chunk_hash, r.execution_id, (r.node_id = '__graph__') AS is_graph,
                           b.size_bytes
                    FROM cas_refs r JOIN cas_blobs b ON b.hash = r.chunk_hash
                ),
                dist AS (SELECT DISTINCT chunk_hash, is_graph, size_bytes FROM refs)
                INSERT INTO cas_storage_stats (
                    workflow_id, physical_bytes, logical_bytes, graph_bytes,
                    output_bytes, manifest_bytes, execution_count, distinct_graphs,
                    chunk_count, computed_at)
                SELECT
                    $1::uuid,
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM cas_blobs),
                    (SELECT COALESCE(SUM(size_bytes), 0) FROM refs),
                    (SELECT COALESCE(SUM(size_bytes) FILTER (WHERE is_graph), 0) FROM dist),
                    (SELECT COALESCE(SUM(size_bytes) FILTER (WHERE NOT is_graph), 0) FROM dist),
                    (SELECT COALESCE(SUM(pg_column_size(manifest)), 0) FROM cas_manifests),
                    (SELECT COUNT(DISTINCT execution_id) FROM cas_refs),
                    (SELECT COUNT(*) FROM dist WHERE is_graph),
                    (SELECT COUNT(*) FROM cas_blobs),
                    $2
                """,
                GLOBAL_TOTALS_ID, now,
            )

            row = await conn.fetchrow(
                "SELECT physical_bytes, logical_bytes, chunk_count "
                "FROM cas_storage_stats WHERE workflow_id = $1", GLOBAL_TOTALS_ID)
            flows = await conn.fetchval(
                "SELECT count(*) FROM cas_storage_stats WHERE workflow_id <> $1",
                GLOBAL_TOTALS_ID)
    return {
        "flows": int(flows or 0),
        "physical_bytes": int(row["physical_bytes"]) if row else 0,
        "logical_bytes": int(row["logical_bytes"]) if row else 0,
        "chunk_count": int(row["chunk_count"]) if row else 0,
        "dedup_ratio": _ratio(row["logical_bytes"], row["physical_bytes"]) if row else 1.0,
    }


def _ratio(logical, physical) -> float:
    """logical/physical dedup ratio (1.0 = no dedup; higher = more savings)."""
    logical, physical = int(logical or 0), int(physical or 0)
    return round(logical / physical, 4) if physical else 1.0


# ---------------------------------------------------------------------------
# Reads (dashboard) — cas_storage_stats is the cache; these are instant.
# ---------------------------------------------------------------------------

async def read_global_stats(pool) -> Dict[str, Any]:
    """Global view: total CAS footprint (R2 + Postgres), counts, lifetime runs,
    dedup ratio. Lifetime runs = the monotonic ledger (pruned) + live rows."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM cas_storage_stats WHERE workflow_id = $1", GLOBAL_TOTALS_ID)
        pg_bytes = await conn.fetchval(
            "SELECT COALESCE(SUM(pg_total_relation_size(format('public.%I', t))), 0) "
            "FROM unnest($1::text[]) AS t", list(_PG_TABLES))
        pruned = await conn.fetchval(
            "SELECT executions_total FROM workflow_run_totals WHERE workflow_id = $1",
            GLOBAL_TOTALS_ID) or 0
        live = await conn.fetchval("SELECT count(*) FROM workflow_executions") or 0
    physical = int(row["physical_bytes"]) if row else 0
    logical = int(row["logical_bytes"]) if row else 0
    return {
        "physical_bytes": physical,
        "logical_bytes": logical,
        "dedup_ratio": _ratio(logical, physical),
        "bytes_saved": max(0, logical - physical),
        "graph_bytes": int(row["graph_bytes"]) if row else 0,
        "output_bytes": int(row["output_bytes"]) if row else 0,
        "manifest_bytes": int(row["manifest_bytes"]) if row else 0,
        "postgres_bytes": int(pg_bytes or 0),
        "chunk_count": int(row["chunk_count"]) if row else 0,
        "execution_count_live": int(live),
        "executions_pruned": int(pruned),
        "executions_lifetime": int(pruned) + int(live),
        "computed_at": row["computed_at"].isoformat() if row and row["computed_at"] else None,
    }


async def read_flow_ranking(pool, *, limit: int = 50) -> List[Dict[str, Any]]:
    """Flows ranked by physical footprint, with owner + per-flow breakdown."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.workflow_id, s.physical_bytes, s.logical_bytes, s.graph_bytes,
                   s.output_bytes, s.manifest_bytes, s.execution_count,
                   s.distinct_graphs, s.chunk_count,
                   w.name, w.owner_id, u.email AS owner_email
            FROM cas_storage_stats s
            JOIN workflows w ON w.id = s.workflow_id
            LEFT JOIN auth.users u ON u.id = w.owner_id
            WHERE s.workflow_id <> $1
            ORDER BY s.physical_bytes DESC
            LIMIT $2
            """,
            GLOBAL_TOTALS_ID, limit)
    return [
        {
            "workflow_id": str(r["workflow_id"]),
            "name": r["name"],
            "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
            "owner_email": r["owner_email"],
            "physical_bytes": int(r["physical_bytes"]),
            "logical_bytes": int(r["logical_bytes"]),
            "dedup_ratio": _ratio(r["logical_bytes"], r["physical_bytes"]),
            "graph_bytes": int(r["graph_bytes"]),
            "output_bytes": int(r["output_bytes"]),
            "manifest_bytes": int(r["manifest_bytes"]),
            "execution_count": int(r["execution_count"]),
            "distinct_graphs": int(r["distinct_graphs"]),
            "chunk_count": int(r["chunk_count"]),
        }
        for r in rows
    ]


async def read_flow_breakdown(pool, workflow_id) -> Dict[str, Any]:
    """Per-flow drill-down: the cached totals + a live per-node physical split and
    the largest blobs the flow references. Computed live (scoped, indexed)."""
    import uuid as uuid_module
    wf = workflow_id if isinstance(workflow_id, uuid_module.UUID) else uuid_module.UUID(str(workflow_id))
    async with pool.acquire() as conn:
        stats = await conn.fetchrow(
            "SELECT * FROM cas_storage_stats WHERE workflow_id = $1", wf)
        # Physical bytes per node (distinct blob per node), top 20.
        per_node = await conn.fetch(
            """
            SELECT node_id, SUM(size_bytes) AS physical_bytes, COUNT(*) AS chunk_count
            FROM (
                SELECT DISTINCT r.node_id, r.chunk_hash, b.size_bytes
                FROM cas_refs r JOIN cas_blobs b ON b.hash = r.chunk_hash
                WHERE r.workflow_id = $1
            ) d
            GROUP BY node_id ORDER BY physical_bytes DESC LIMIT 20
            """,
            wf)
        largest = await conn.fetch(
            """
            SELECT DISTINCT b.hash, b.size_bytes
            FROM cas_refs r JOIN cas_blobs b ON b.hash = r.chunk_hash
            WHERE r.workflow_id = $1
            ORDER BY b.size_bytes DESC LIMIT 10
            """,
            wf)
        pruned = await conn.fetchval(
            "SELECT executions_total FROM workflow_run_totals WHERE workflow_id = $1", wf) or 0
        live = await conn.fetchval(
            "SELECT count(*) FROM workflow_executions WHERE workflow_id = $1", wf) or 0
    return {
        "workflow_id": str(wf),
        "physical_bytes": int(stats["physical_bytes"]) if stats else 0,
        "logical_bytes": int(stats["logical_bytes"]) if stats else 0,
        "dedup_ratio": _ratio(stats["logical_bytes"], stats["physical_bytes"]) if stats else 1.0,
        "graph_bytes": int(stats["graph_bytes"]) if stats else 0,
        "output_bytes": int(stats["output_bytes"]) if stats else 0,
        "manifest_bytes": int(stats["manifest_bytes"]) if stats else 0,
        "distinct_graphs": int(stats["distinct_graphs"]) if stats else 0,
        "chunk_count": int(stats["chunk_count"]) if stats else 0,
        "executions_live": int(live),
        "executions_lifetime": int(pruned) + int(live),
        "by_node": [
            {"node_id": r["node_id"], "physical_bytes": int(r["physical_bytes"]),
             "chunk_count": int(r["chunk_count"])}
            for r in per_node
        ],
        "largest_blobs": [
            {"hash": r["hash"], "size_bytes": int(r["size_bytes"])} for r in largest
        ],
    }
