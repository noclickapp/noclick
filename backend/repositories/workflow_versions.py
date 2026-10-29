"""SQL for ``workflow_versions``: each write of a workflow's definition (its
graph, name, description and client settings) as a version of its history
(``coder/workflow/graph_service.py`` decides when a write starts a version and
when it joins one).

A version has two numbers: ``history_version``, its own, given when its row is
made (the ``graph_version`` its first write produced) and never changed, which
reads and restores name it by; and ``version``, the ``graph_version`` its latest
write produced, which moves as later writes join it and orders the history.

A workflow's newest version is open: it holds no state of its own (``graph``
NULL), being the workflow as it stands, so an autosave joining it writes its
number and lines alone, never the graph a second time. The write that starts
the next version closes it with the definition as it was just before
(``close``)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from utils.runtime_keys import graph_without_runtime_keys

# How long a version is kept; a workflow's newest is kept whatever its age.
KEEP_DAYS = 90
_LISTED = ("workflow_id, history_version, version, source, author_user_id, author_key_id, changes, restored_from, "
           "created_at, updated_at")
_STATE = "graph, name, description, settings"


async def newest(conn, workflow_id) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow(f"SELECT {_LISTED} FROM workflow_versions WHERE workflow_id = $1::uuid "
                              "ORDER BY version DESC LIMIT 1", str(workflow_id))
    return dict(row) if row else None


async def newest_by(conn, workflow_id, *, source: str, author_user_id: Optional[str],
                    author_key_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The newest version one author wrote from one source, with ``age``: how long since its first write."""
    row = await conn.fetchrow(
        f"""SELECT {_LISTED}, now() - created_at AS age FROM workflow_versions
            WHERE workflow_id = $1::uuid AND source = $2 AND author_user_id IS NOT DISTINCT FROM $3::uuid
              AND author_key_id IS NOT DISTINCT FROM $4
            ORDER BY version DESC LIMIT 1""", str(workflow_id), source, author_user_id, author_key_id)
    return dict(row) if row else None


async def close(conn, workflow_id, state: Mapping[str, Any]) -> None:
    """Give the open version (the newest, if it's open) ``state``: the definition as it was when it ended."""
    await conn.execute(
        """UPDATE workflow_versions SET graph = $2, name = $3, description = $4, settings = $5
           WHERE workflow_id = $1::uuid AND graph IS NULL""",
        str(workflow_id), graph_without_runtime_keys(state["graph"]), state["name"], state["description"],
        state["settings"])


async def insert(conn, *, workflow_id, version: int, source: str, author_user_id: Optional[str],
                 author_key_id: Optional[str], changes: Sequence[str], restored_from: Optional[int] = None,
                 state: Optional[Mapping[str, Any]] = None) -> int:
    """A version, numbered by the ``version`` its write produced; open unless given its ``state``
    (``{graph, name, description, settings}``). Returns its ``history_version``."""
    state = state or {}
    graph = state.get("graph")
    await conn.execute(
        """INSERT INTO workflow_versions (workflow_id, history_version, version, graph, name, description, settings,
                                          source, author_user_id, author_key_id, changes, restored_from)
           VALUES ($1::uuid, $2, $2, $3, $4, $5, $6, $7, $8::uuid, $9, $10::text[], $11)""",
        str(workflow_id), version, graph_without_runtime_keys(graph) if graph is not None else None,
        state.get("name"), state.get("description"), state.get("settings"), source, author_user_id, author_key_id,
        list(changes), restored_from)
    return version


async def join(conn, *, workflow_id, history_version: int, version: int, changes: Sequence[str]) -> None:
    """A write that joins version ``history_version``: it takes the write's ``version`` and changes, and is open
    (the newest)."""
    await conn.execute(
        """UPDATE workflow_versions SET version = $3, changes = $4::text[], updated_at = now(),
                  graph = NULL, name = NULL, description = NULL, settings = NULL
           WHERE workflow_id = $1::uuid AND history_version = $2""",
        str(workflow_id), history_version, version, list(changes))


async def page(conn, workflow_id, *, limit: int, before: Optional[int]) -> List[Dict[str, Any]]:
    """Newest first (by their latest write), ``limit + 1`` rows (the extra one says there's more), without their
    state; ``before``: those whose latest write came before that ``version``."""
    rows = await conn.fetch(
        f"""SELECT {_LISTED} FROM workflow_versions WHERE workflow_id = $1::uuid AND ($2::bigint IS NULL OR version < $2)
            ORDER BY version DESC LIMIT $3""", str(workflow_id), before, limit + 1)
    return [dict(r) for r in rows]


async def get(conn, workflow_id, history_version: int) -> Optional[Dict[str, Any]]:
    """One version with its state (``graph`` None: it's open, the workflow as it stands)."""
    row = await conn.fetchrow(f"SELECT {_LISTED}, {_STATE} FROM workflow_versions WHERE workflow_id = $1::uuid "
                              "AND history_version = $2", str(workflow_id), history_version)
    return dict(row) if row else None


async def prune(pool, *, days: int = KEEP_DAYS) -> int:
    """Drop versions older than ``days``, never a workflow's newest."""
    result = await pool.execute(
        """DELETE FROM workflow_versions v WHERE v.updated_at < now() - make_interval(days => $1)
           AND EXISTS (SELECT 1 FROM workflow_versions n WHERE n.workflow_id = v.workflow_id AND n.version > v.version)""",
        days)
    return int(result.split()[-1])
