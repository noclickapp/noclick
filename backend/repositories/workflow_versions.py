"""SQL for ``workflow_versions``: each write of a workflow's graph, keyed by
the ``graph_version`` it produced (``coder/workflow/graph_service.py`` decides
when a write is a version of its own and when it joins the one before)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from utils.runtime_keys import graph_without_runtime_keys

# How long a version is kept; a workflow's newest is kept whatever its age.
KEEP_DAYS = 90
_LISTED = ("workflow_id, version, source, author_user_id, author_key_id, changes, restored_from, created_at, "
           "updated_at")


async def newest(conn, workflow_id) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(
        f"SELECT {_LISTED}, now() - updated_at AS age FROM workflow_versions WHERE workflow_id = $1::uuid "
        "ORDER BY version DESC LIMIT 1", str(workflow_id))
    return dict(row) if row else None


async def insert(conn, *, workflow_id, version: int, graph: Any, source: str, author_user_id: Optional[str],
                 author_key_id: Optional[str], changes: Sequence[str], restored_from: Optional[int] = None) -> None:
    await conn.execute(
        """INSERT INTO workflow_versions (workflow_id, version, graph, source, author_user_id, author_key_id, changes,
                                          restored_from)
           VALUES ($1::uuid, $2, $3, $4, $5::uuid, $6, $7::text[], $8)""",
        str(workflow_id), version, graph_without_runtime_keys(graph), source, author_user_id, author_key_id,
        list(changes), restored_from)


async def join(conn, *, workflow_id, version: int, into: int, graph: Any, changes: Sequence[str]) -> None:
    """A write that joins version ``into``: the row takes its graph, version and changes."""
    await conn.execute(
        """UPDATE workflow_versions SET version = $2, graph = $4, changes = $5::text[], updated_at = now()
           WHERE workflow_id = $1::uuid AND version = $3""",
        str(workflow_id), version, into, graph_without_runtime_keys(graph), list(changes))


async def page(conn, workflow_id, *, limit: int, before: Optional[int]) -> List[Dict[str, Any]]:
    """Newest first, ``limit + 1`` rows (the extra one says there's more), without their graphs."""
    rows = await conn.fetch(
        f"""SELECT {_LISTED} FROM workflow_versions WHERE workflow_id = $1::uuid AND ($2::bigint IS NULL OR version < $2)
            ORDER BY version DESC LIMIT $3""", str(workflow_id), before, limit + 1)
    return [dict(r) for r in rows]


async def get(conn, workflow_id, version: int) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(f"SELECT {_LISTED}, graph FROM workflow_versions WHERE workflow_id = $1::uuid "
                              "AND version = $2", str(workflow_id), version)
    return dict(row) if row else None


async def prune(pool, *, days: int = KEEP_DAYS) -> int:
    """Drop versions older than ``days``, never a workflow's newest."""
    result = await pool.execute(
        """DELETE FROM workflow_versions v WHERE v.updated_at < now() - make_interval(days => $1)
           AND EXISTS (SELECT 1 FROM workflow_versions n WHERE n.workflow_id = v.workflow_id AND n.version > v.version)""",
        days)
    return int(result.split()[-1])
