"""CAS store: write + read for graph snapshots and node outputs.

Write path (idempotent, crash-safe ordering — see docs/design/execution-log-viewer.md):
  1. decompose() — chunk + hash (pure; in chunking.py)
  2. probe cas_blobs receipts
  3. PUT owed chunks to R2 (compressed), awaited BEFORE the commit
  4. one transaction: receipts (ON CONFLICT DO NOTHING) + un-condemn + manifest
     upsert + cas_refs delta

Step 4 is a separable awaited call (`_commit_node`), so a test can run 1–3 and
abort before commit to prove the accepted crash window is "missing manifest",
never "ref → missing blob".

R2 helpers are reached via the ``r2_cloudflare`` module (attribute access) so a
test can patch them at the source with a stateful fake.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid as uuid_module
from typing import Any, Dict, List, Optional

import httpx
import zstandard as zstd

from utils import r2_cloudflare
from utils.cas.canonical import canonicalize, hash_bytes
from utils.cas.chunking import (
    DEFAULT_CHUNK_THRESHOLD_BYTES,
    PRUNED_PLACEHOLDER,
    decompose,
    reassemble,
    referenced_hashes,
)

logger = logging.getLogger(__name__)

R2_CAS_BUCKET = "workflow-cas"
GRAPH_NODE_ID = "__graph__"  # reserved cas_refs.node_id for the graph snapshot
_ZSTD_CONTENT_TYPE = "application/zstd"

_compressor = zstd.ZstdCompressor(level=3)
_decompressor = zstd.ZstdDecompressor()


def _compress(data: bytes) -> bytes:
    return _compressor.compress(data)


def _decompress(data: bytes) -> bytes:
    return _decompressor.decompress(data)


def _as_uuid(value) -> uuid_module.UUID:
    return value if isinstance(value, uuid_module.UUID) else uuid_module.UUID(str(value))


def _decode_jsonb(value: Any) -> Any:
    """Decode a JSONB column whether or not the connection has the jsonb codec
    registered."""
    return json.loads(value) if isinstance(value, str) else value


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def _put_owed(chunks: Dict[str, bytes], owed: List[str]) -> Dict[str, int]:
    """Compress + PUT the owed chunks to R2 concurrently. Returns hash→compressed
    size. Raises (before any DB write) if any PUT fails."""
    compressed = {h: _compress(chunks[h]) for h in owed}
    await asyncio.gather(*[
        r2_cloudflare.upload_bytes_to_r2_async(
            bucket=R2_CAS_BUCKET, key=h, body=compressed[h],
            content_type=_ZSTD_CONTENT_TYPE,
        )
        for h in owed
    ])
    return {h: len(compressed[h]) for h in owed}


_UNSET = object()  # "this node produced no output" (distinct from a JSON null output)


async def _commit_node(
    pool, *, workflow_id, execution_id, node_id: str, manifest_json: Optional[str],
    referenced: List[str], owed_sizes: Dict[str, int],
    status: Optional[str] = None, error: Optional[str] = None,
) -> bool:
    """Step 4: one transaction — receipts, un-condemn, manifest+status upsert, ref
    delta. Separable so the crash window (abort before this) is testable.
    ``manifest_json`` is None for a status-only node (manifest stored as SQL NULL)."""
    wf, ex = _as_uuid(workflow_id), _as_uuid(execution_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Lock both FK parents for the duration of the commit. A concurrent
            # workflow hard-delete either waits for this transaction, or wins
            # first and makes this late fire-and-forget persist a clean no-op.
            parents_exist = await conn.fetchval(
                """SELECT 1
                   FROM workflows w
                   JOIN workflow_executions e ON e.workflow_id = w.id
                   WHERE w.id = $1 AND e.id = $2
                   FOR KEY SHARE OF w, e""",
                wf, ex,
            )
            if not parents_exist:
                logger.info(
                    "[CAS] Skipping late persist for deleted workflow/execution "
                    "%s/%s", workflow_id, execution_id,
                )
                return False
            if owed_sizes:
                await conn.executemany(
                    "INSERT INTO cas_blobs (hash, size_bytes) VALUES ($1, $2) "
                    "ON CONFLICT (hash) DO NOTHING",
                    list(owed_sizes.items()),
                )
            if referenced:
                await conn.execute(
                    "UPDATE cas_blobs SET orphaned_at = NULL "
                    "WHERE hash = ANY($1) AND orphaned_at IS NOT NULL",
                    referenced,
                )
            await conn.execute(
                "INSERT INTO cas_manifests "
                "(workflow_id, execution_id, node_id, manifest, last_run_status, last_run_error) "
                "VALUES ($1, $2, $3, $4::jsonb, $5, $6) "
                "ON CONFLICT (execution_id, node_id) DO UPDATE "
                "SET manifest = EXCLUDED.manifest, workflow_id = EXCLUDED.workflow_id, "
                "last_run_status = EXCLUDED.last_run_status, last_run_error = EXCLUDED.last_run_error",
                wf, ex, node_id, manifest_json, status, error,
            )
            # Reconcile refs for this (execution, node) as a delta.
            await conn.execute(
                "DELETE FROM cas_refs WHERE execution_id = $1 AND node_id = $2 "
                "AND NOT (chunk_hash = ANY($3::text[]))",
                ex, node_id, referenced,
            )
            if referenced:
                await conn.executemany(
                    "INSERT INTO cas_refs (workflow_id, execution_id, node_id, chunk_hash) "
                    "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                    [(wf, ex, node_id, h) for h in referenced],
                )
    return True


async def _execution_parent_exists(pool, workflow_id, execution_id) -> bool:
    """Cheap preflight that avoids chunking/R2 uploads after cascade deletion.

    The locked check in _commit_node remains authoritative for deletion that
    races after this read.
    """
    wf, ex = _as_uuid(workflow_id), _as_uuid(execution_id)
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            """SELECT 1
               FROM workflows w
               JOIN workflow_executions e ON e.workflow_id = w.id
               WHERE w.id = $1 AND e.id = $2""",
            wf, ex,
        ))


async def persist_node_result(
    pool, *, workflow_id, execution_id, node_id: str, output: Any = _UNSET,
    status: Optional[str] = None, error: Optional[str] = None,
    threshold: int = DEFAULT_CHUNK_THRESHOLD_BYTES,
    _parent_prechecked: bool = False,
) -> bool:
    """Persist one node's output (optional) + terminal status to the CAS.
    Idempotent; re-persist overwrites the manifest and reconciles refs."""
    if not _parent_prechecked and not await _execution_parent_exists(
        pool, workflow_id, execution_id
    ):
        logger.info(
            "[CAS] Skipping persist for deleted workflow/execution %s/%s",
            workflow_id, execution_id,
        )
        return False
    if output is _UNSET:
        manifest_json, referenced, owed_sizes = None, [], {}      # status-only row
    else:
        manifest, chunks = decompose(output, threshold)          # step 1
        manifest_json = json.dumps(manifest)
        # Ref the FULL emitted chunk set (incl. placeholders nested inside chunk
        # bytes, which referenced_hashes(manifest) cannot see) — else GC Phase B
        # would orphan a still-referenced nested chunk.
        referenced = list(chunks)
        owed = await _owed_hashes(pool, referenced)              # step 2
        owed_sizes = await _put_owed(chunks, owed)               # step 3
    return await _commit_node(                                   # step 4
        pool, workflow_id=workflow_id, execution_id=execution_id, node_id=node_id,
        manifest_json=manifest_json, referenced=referenced, owed_sizes=owed_sizes,
        status=status, error=error,
    )


async def persist_node_output(
    pool, *, workflow_id, execution_id, node_id: str, output: Any,
    threshold: int = DEFAULT_CHUNK_THRESHOLD_BYTES,
) -> bool:
    """Output-only convenience wrapper over persist_node_result."""
    return await persist_node_result(
        pool, workflow_id=workflow_id, execution_id=execution_id,
        node_id=node_id, output=output, threshold=threshold)


async def persist_run_outputs(
    pool, *, workflow_id, execution_id,
    node_outputs: Dict[str, Any],
    node_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
    threshold: int = DEFAULT_CHUNK_THRESHOLD_BYTES,
) -> int:
    """Persist all of a run's node outputs + statuses to the CAS (the sole
    node-output store). Returns the number of node rows written."""
    node_statuses = node_statuses or {}
    node_ids = set(node_outputs) | set(node_statuses)
    if not node_ids:
        return 0
    if not await _execution_parent_exists(pool, workflow_id, execution_id):
        logger.info(
            "[CAS] Skipping output batch for deleted workflow/execution %s/%s",
            workflow_id, execution_id,
        )
        return 0
    written = 0
    for node_id in node_ids:
        st = node_statuses.get(node_id) or {}
        committed = await persist_node_result(
            pool, workflow_id=workflow_id, execution_id=execution_id, node_id=node_id,
            output=node_outputs[node_id] if node_id in node_outputs else _UNSET,
            status=st.get("status"), error=st.get("error"), threshold=threshold,
            _parent_prechecked=True,
        )
        if not committed:
            break
        written += 1
    return written


# Node-data fields baked in by the frontend at runtime — outputs from prior
# runs, executionState, the cached _lastRunStatus / _lastRunAt / _lastRunError,
# in-flight progress, etc. They vary every run even when the workflow's
# structure is identical, so leaving them in the snapshot bytes defeats the
# CAS dedup: same workflow run twice → two distinct chunks. Strip before
# canonicalize so identical workflows share a single blob.
#
# Kept in sync with the persist:false / restore:false fields in
# frontend/app/lib/applyNodeUpdate.ts TOP_LEVEL_FIELDS — those are exactly the
# fields the FE itself treats as runtime-only and drops on persist.
_VOLATILE_NODE_DATA_KEYS = frozenset({
    'output', 'outputTimestamp', '_outputStoredLocally', '_outputSizeBytes',
    'executionState', 'error',
    '_lastRunStatus', '_lastRunAt', '_lastRunError',
    'progress',
    'configValid',
    'workflowAnimating',
    '_hasPresetPosition',
    '_executionId',
    '_timeToFillMs',
})

# Inside data.config the codebase's convention is `_`-prefixed key = internal /
# runtime, NOT user-set configuration. The webhook router writes
# `_triggerPayload` (full HTTP headers + cron schedule id + triggered_at) into
# the trigger node's config on every fire, and the execution handler writes
# `_error_inputs` when error-output handles are wired. Both mutate per run and
# tank graph dedup (the Newsletter cron flow accumulated 1914 distinct chunks
# from `_triggerPayload` alone — cf-ray + schedule_id + triggered_at change
# every invocation).
#
# Strip every `_`-prefixed config key on the snapshot side EXCEPT the
# user-set exceptions in this allowlist. New internal `_*` fields added later
# are stripped automatically; new user-meaningful ones must be added here.
_CONFIG_UNDERSCORE_KEEP = frozenset({
    '_settings',  # per-node user settings (onError handling, etc.) — user-set, structural
})


def _strip_internal_config_keys(config: Any) -> Any:
    """Drop the `_`-prefixed runtime keys (`_triggerPayload`, `_error_inputs`,
    etc.) from a node's config, keeping the explicit allowlist."""
    if not isinstance(config, dict):
        return config
    return {
        k: v for k, v in config.items()
        if not (k.startswith('_') and k not in _CONFIG_UNDERSCORE_KEEP)
    }


def _strip_volatile_for_snapshot(graph: Any) -> Any:
    """Return a copy of ``graph`` with per-run runtime fields removed from
    each node's data + config. The snapshot is for replay — it needs the
    graph's STRUCTURE (id, type, position, config, credentials, disabled flag,
    label), not the runtime state baked in by the FE / webhook routes between
    runs."""
    if not isinstance(graph, dict):
        return graph
    nodes = graph.get('nodes')
    if not isinstance(nodes, list):
        return graph
    cleaned_nodes = []
    for n in nodes:
        if not isinstance(n, dict):
            cleaned_nodes.append(n)
            continue
        out = dict(n)
        data = out.get('data')
        if isinstance(data, dict):
            cleaned_data = {k: v for k, v in data.items() if k not in _VOLATILE_NODE_DATA_KEYS}
            # Strip runtime `_*` keys inside data.config (the FE shape).
            if isinstance(cleaned_data.get('config'), dict):
                cleaned_data['config'] = _strip_internal_config_keys(cleaned_data['config'])
            out['data'] = cleaned_data
        # Some snapshot shapes flatten the runtime fields onto the node itself
        # (older save-blob format). Strip there too — both the top-level
        # volatile keys and any `_*` config at n.config.
        out = {k: v for k, v in out.items() if k not in _VOLATILE_NODE_DATA_KEYS}
        if isinstance(out.get('config'), dict):
            out['config'] = _strip_internal_config_keys(out['config'])
        cleaned_nodes.append(out)
    return {**graph, 'nodes': cleaned_nodes}


async def persist_graph_snapshot(pool, *, workflow_id, execution_id, graph: Any) -> str:
    """Persist the run's graph snapshot whole-blob, written ONCE per execution.
    Returns the graph hash. Idempotent + resume-safe: if the execution already
    has a graph_hash, returns it without touching the store (resume must not
    re-snapshot a post-edit graph)."""
    wf, ex = _as_uuid(workflow_id), _as_uuid(execution_id)
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT graph_hash FROM workflow_executions WHERE id = $1", ex)
    if existing:
        return existing

    data = canonicalize(_strip_volatile_for_snapshot(graph))
    digest = hash_bytes(data)
    owed = await _owed_hashes(pool, [digest])
    owed_sizes = await _put_owed({digest: data}, owed)

    async with pool.acquire() as conn:
        async with conn.transaction():
            if owed_sizes:
                await conn.execute(
                    "INSERT INTO cas_blobs (hash, size_bytes) VALUES ($1, $2) "
                    "ON CONFLICT (hash) DO NOTHING", digest, owed_sizes[digest])
            await conn.execute(
                "UPDATE cas_blobs SET orphaned_at = NULL "
                "WHERE hash = $1 AND orphaned_at IS NOT NULL", digest)
            await conn.execute(
                "INSERT INTO cas_refs (workflow_id, execution_id, node_id, chunk_hash) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                wf, ex, GRAPH_NODE_ID, digest)
            await conn.execute(
                "UPDATE workflow_executions SET graph_hash = $1 "
                "WHERE id = $2 AND graph_hash IS NULL", digest, ex)
    return digest


async def _owed_hashes(pool, hashes: List[str]) -> List[str]:
    """Step 2: which hashes have no durable receipt yet."""
    if not hashes:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT hash FROM cas_blobs WHERE hash = ANY($1)", hashes)
    have = {r["hash"] for r in rows}
    return [h for h in hashes if h not in have]


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def _fetch_chunk(digest: str) -> Optional[bytes]:
    """Download + decompress one chunk; None if the object is gone (404 → the
    benign race casualty / pruned chunk)."""
    try:
        compressed, _ct = await r2_cloudflare.download_bytes_from_r2_async_native(
            R2_CAS_BUCKET, digest)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise
    return _decompress(compressed)


def _singleflight_fetch():
    """Per-read-call chunk fetcher deduping across CONCURRENT reassemblies.
    Content-defined chunking means one node's history entries (and often
    sibling nodes) share most chunks; without this, N gathered _reassemble
    calls fetch every shared digest N times (the 2026-07-13 carousel burst
    put 200+ duplicate GETs on the R2 pool in one call)."""
    tasks: Dict[str, asyncio.Task] = {}

    async def fetch(digest: str) -> Optional[bytes]:
        task = tasks.get(digest)
        if task is None:
            task = tasks[digest] = asyncio.create_task(_fetch_chunk(digest))
            # If every awaiter is cancelled the task still runs to completion;
            # consume its exception so it can't log "never retrieved".
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None)
        return await task

    return fetch


async def _fetch_chunks(hashes, fetch=_fetch_chunk) -> Dict[str, Optional[bytes]]:
    hashes = list(hashes)
    results = await asyncio.gather(*[fetch(h) for h in hashes])
    return dict(zip(hashes, results))


async def read_node_output(pool, *, execution_id, node_id: str, workflow_id=None) -> Optional[Any]:
    """Reassemble a node's output for a run. Returns None if nothing was
    persisted; a missing chunk degrades to the 'output no longer retained'
    placeholder (never raises). Pass workflow_id to scope the read (defense in
    depth against cross-workflow execution_id access)."""
    ex = _as_uuid(execution_id)
    async with pool.acquire() as conn:
        if workflow_id is not None:
            row = await conn.fetchrow(
                "SELECT manifest FROM cas_manifests "
                "WHERE execution_id = $1 AND node_id = $2 AND workflow_id = $3",
                ex, node_id, _as_uuid(workflow_id))
        else:
            row = await conn.fetchrow(
                "SELECT manifest FROM cas_manifests WHERE execution_id = $1 AND node_id = $2",
                ex, node_id)
    if row is None:
        return None
    return await _reassemble(row["manifest"])


async def _reassemble(manifest_raw, fetch=_fetch_chunk) -> Optional[Any]:
    """Decode a cas_manifests.manifest JSONB and reassemble it (None if NULL =
    status-only node). Fetches the FULL transitive chunk closure — structural
    Merkle nests placeholders inside chunk bytes, so a single prefetch of the
    manifest's top-level refs is not enough; we BFS until no new refs appear. A
    missing chunk degrades to the pruned placeholder (never raises). Multi-row
    readers pass a shared _singleflight_fetch() so common chunks fetch once."""
    if manifest_raw is None:
        return None
    manifest = _decode_jsonb(manifest_raw)
    chunk_bytes: Dict[str, Optional[bytes]] = {}
    frontier = referenced_hashes(manifest)
    while frontier:
        fetched = await _fetch_chunks(
            [h for h in frontier if h not in chunk_bytes], fetch)
        frontier = set()
        for digest, data in fetched.items():
            chunk_bytes[digest] = data
            if data is not None:
                for nested in referenced_hashes(json.loads(data)):
                    if nested not in chunk_bytes:
                        frontier.add(nested)
    return reassemble(manifest, lambda h: chunk_bytes.get(h), on_missing=PRUNED_PLACEHOLDER)


# --- CAS-backed replacements for the legacy node_output_store read API.
# Signatures mirror the legacy functions for near drop-in re-pointing. ---

async def read_execution_outputs(pool, execution_id, node_ids=None) -> Dict[str, Any]:
    """All node outputs for one execution (resume seeding / MCP execution view)."""
    ex = _as_uuid(execution_id)
    async with pool.acquire() as conn:
        if node_ids:
            rows = await conn.fetch(
                "SELECT node_id, manifest FROM cas_manifests "
                "WHERE execution_id = $1 AND node_id = ANY($2)", ex, list(node_ids))
        else:
            rows = await conn.fetch(
                "SELECT node_id, manifest FROM cas_manifests WHERE execution_id = $1", ex)
    # Fan out R2 reassembly across rows (sequential awaits would serialize one
    # R2 round-trip per node — the 2026-05-13 cascade shape).
    fetch = _singleflight_fetch()
    values = await asyncio.gather(*[_reassemble(row["manifest"], fetch) for row in rows])
    return {row["node_id"]: v for row, v in zip(rows, values) if v is not None}


async def _distinct_node_ids(conn, wf, *, exclude_iter=False, with_status=False) -> List[str]:
    """Enumerate a workflow's distinct node_ids via a recursive loose index
    scan: each step is one descent of idx_cas_manifests_node_recency to the
    next distinct key, so cost is O(distinct nodes) — a plain SELECT DISTINCT
    (or DISTINCT ON) scans every historical row and becomes prohibitive on a
    large workflow. exclude_iter drops composite '<node>#iter:N' keys; with_status
    restricts to status-bearing rows (rides the partial status index)."""
    filters = ""
    if with_status:
        filters += " AND {a}last_run_status IS NOT NULL"
    if exclude_iter:
        filters += " AND {a}node_id NOT LIKE '%#iter:%'"
    rows = await conn.fetch(
        "WITH RECURSIVE distinct_nodes AS ("
        "  (SELECT node_id FROM cas_manifests"
        f"   WHERE workflow_id = $1{filters.format(a='')}"
        "   ORDER BY node_id LIMIT 1)"
        "  UNION ALL"
        "  SELECT (SELECT m.node_id FROM cas_manifests m"
        f"          WHERE m.workflow_id = $1 AND m.node_id > dn.node_id{filters.format(a='m.')}"
        "          ORDER BY m.node_id LIMIT 1)"
        "  FROM distinct_nodes dn WHERE dn.node_id IS NOT NULL"
        ") "
        "SELECT node_id FROM distinct_nodes WHERE node_id IS NOT NULL", wf)
    return [row["node_id"] for row in rows]


async def read_latest_node_outputs(pool, workflow_id, node_ids=None) -> Dict[str, Any]:
    """Latest output per node across executions (canvas hydrate on load).
    Excludes composite iteration sub-output keys ('<node>#iter:N') — those don't
    map to a canvas node and are surfaced only through the carousel
    (read_node_output_history's prefix match).

    Latest-per-node is one index descent per node (unnest + LATERAL LIMIT 1),
    never DISTINCT ON — DISTINCT ON can't stop at the newest row per group, so
    it re-reads the node's entire run history and can sustain database-pool
    saturation on large workflows."""
    wf = _as_uuid(workflow_id)
    async with pool.acquire() as conn:
        if not node_ids:
            node_ids = await _distinct_node_ids(conn, wf, exclude_iter=True)
        rows = await conn.fetch(
            "SELECT l.node_id, l.manifest "
            "FROM unnest($2::text[]) AS n(node_id) "
            "JOIN LATERAL ("
            "  SELECT node_id, manifest FROM cas_manifests"
            "  WHERE workflow_id = $1 AND node_id = n.node_id"
            "  ORDER BY created_at DESC LIMIT 1"
            ") l ON true", wf, list(node_ids))
    # Fan out R2 reassembly across rows (sequential awaits would serialize one
    # R2 round-trip per node — the 2026-05-13 cascade shape).
    fetch = _singleflight_fetch()
    values = await asyncio.gather(*[_reassemble(row["manifest"], fetch) for row in rows])
    return {row["node_id"]: v for row, v in zip(rows, values) if v is not None}


async def read_latest_node_output(pool, workflow_id, node_id) -> Optional[Any]:
    """Latest output for a single node across executions."""
    result = await read_latest_node_outputs(pool, workflow_id, [node_id])
    return result.get(node_id)


async def read_latest_node_statuses(pool, workflow_id) -> Dict[str, Dict[str, Any]]:
    """Latest per-node terminal status/error across executions (status chips).
    Shape matches the legacy store: {status, finishedAt (epoch ms), error}, with
    created_at doubling as the finish time (the row is written right after the run)."""
    wf = _as_uuid(workflow_id)
    async with pool.acquire() as conn:
        node_ids = await _distinct_node_ids(conn, wf, with_status=True)
        rows = await conn.fetch(
            "SELECT l.node_id, l.last_run_status, l.last_run_error, l.created_at "
            "FROM unnest($2::text[]) AS n(node_id) "
            "JOIN LATERAL ("
            "  SELECT node_id, last_run_status, last_run_error, created_at FROM cas_manifests"
            "  WHERE workflow_id = $1 AND node_id = n.node_id AND last_run_status IS NOT NULL"
            "  ORDER BY created_at DESC LIMIT 1"
            ") l ON true", wf, node_ids)
    return {
        row["node_id"]: {
            "status": row["last_run_status"],
            "finishedAt": int(row["created_at"].timestamp() * 1000) if row["created_at"] else None,
            "error": row["last_run_error"],
        }
        for row in rows
    }


async def read_node_output_history(pool, workflow_id, node_id, limit=20) -> List[Dict[str, Any]]:
    """Last N outputs for a node across executions, newest first (carousel).
    Also surfaces a node's iteration sub-outputs (composite keys
    '<node>#iter:N') so the carousel shows each iteration of an iteration-body
    node, matching the legacy synthetic-execution behavior.

    The iter keys are resolved by enumerating the workflow's distinct node_ids
    and prefix-matching in Python, NOT with a SQL LIKE: under this collation a
    LIKE prefix cannot use the btree and can force a full-table sequential
    scan. Top-N
    per key + a global top-N is equivalent to the old global ORDER BY."""
    wf = _as_uuid(workflow_id)
    prefix = f"{node_id}#iter:"
    async with pool.acquire() as conn:
        keys = [k for k in await _distinct_node_ids(conn, wf)
                if k == node_id or k.startswith(prefix)]
        if not keys:
            return []
        rows = await conn.fetch(
            "SELECT l.execution_id, l.node_id, l.created_at, l.manifest "
            "FROM unnest($2::text[]) AS n(node_id) "
            "JOIN LATERAL ("
            "  SELECT execution_id, node_id, created_at, manifest FROM cas_manifests"
            "  WHERE workflow_id = $1 AND node_id = n.node_id"
            "  ORDER BY created_at DESC LIMIT $3"
            ") l ON true "
            "ORDER BY l.created_at DESC LIMIT $3",
            wf, keys, limit)
    # Fan out R2 reassembly across history rows (sequential awaits would serialize
    # one R2 round-trip per entry — the 2026-05-13 cascade shape). History entries
    # of one node share most chunks, so fetches are single-flighted across rows.
    fetch = _singleflight_fetch()
    values = await asyncio.gather(*[_reassemble(row["manifest"], fetch) for row in rows])
    return [
        {
            "execution_id": str(row["execution_id"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "output": value,
        }
        for row, value in zip(rows, values)
    ]


async def read_latest_node_output_meta(pool, workflow_id, node_id) -> Optional[Dict[str, Any]]:
    """Latest output for a node plus its store row identity, as
    {output, created_at(isoformat), execution_id}. None if nothing was persisted.
    Used by callers that need both the output and its persistence identity."""
    wf = _as_uuid(workflow_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT execution_id, manifest, created_at FROM cas_manifests "
            "WHERE workflow_id = $1 AND node_id = $2 ORDER BY created_at DESC LIMIT 1",
            wf, node_id)
    if row is None:
        return None
    output = await _reassemble(row["manifest"])
    if output is None:
        return None
    return {
        "output": output,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "execution_id": str(row["execution_id"]) if row["execution_id"] else None,
    }


async def read_nodes_with_output(pool, workflow_id, node_ids) -> set:
    """The subset of node_ids that have at least one stored output (manifest)."""
    wf = _as_uuid(workflow_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT node_id FROM cas_manifests "
            "WHERE workflow_id = $1 AND node_id = ANY($2) AND manifest IS NOT NULL",
            wf, list(node_ids))
    return {row["node_id"] for row in rows}


async def read_graph(pool, *, execution_id) -> Optional[Any]:
    """Reassemble the run's graph snapshot. None if not snapshotted; the pruned
    placeholder if the blob is gone."""
    ex = _as_uuid(execution_id)
    async with pool.acquire() as conn:
        digest = await conn.fetchval(
            "SELECT graph_hash FROM workflow_executions WHERE id = $1", ex)
    if not digest:
        return None
    data = await _fetch_chunk(digest)
    if data is None:
        return PRUNED_PLACEHOLDER
    return json.loads(data)
