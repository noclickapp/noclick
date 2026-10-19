"""SQL for an automation's tables kept in Postgres (``dataset_rows``).

The engine's own store for tables (``utils.dataset_store``'s default): a table
is a ``workflow_resources`` row of type ``dataset``, each of its rows a JSON
object at a position (``row_index``), in order. A platform that keeps tables
elsewhere reads them here once, to move them (``all_rows``).

Every function takes ``db``, a pool or a connection, so a caller holding a
transaction runs them inside it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

_ROW = "id, row_index, data, created_at"
# Two bind parameters a row, under asyncpg's 32,767.
_INSERT_ROWS = 10_000


async def set_row_count(db, resource_id: str, row_count: int) -> None:
    """The table's ``metadata.row_count`` (what pickers and lists show), merged
    into its metadata, and ``updated_at``."""
    await db.execute(
        """UPDATE workflow_resources
           SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('row_count', $2::int),
               updated_at = NOW()
           WHERE id = $1""",
        resource_id, row_count,
    )


async def touch(db, resource_id: str) -> None:
    """A row of the table changed (its ``updated_at``)."""
    await db.execute("UPDATE workflow_resources SET updated_at = NOW() WHERE id = $1", resource_id)


async def page(db, resource_id: str, *, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """``(rows, total)``: ``limit`` rows from ``offset`` in order, and how many it has."""
    total = await db.fetchval("SELECT COUNT(*) FROM dataset_rows WHERE resource_id = $1", resource_id)
    rows = await db.fetch(
        f"SELECT {_ROW} FROM dataset_rows WHERE resource_id = $1 ORDER BY row_index, id LIMIT $2 OFFSET $3",
        resource_id, limit, offset,
    )
    return [dict(r) for r in rows], int(total or 0)


async def all_rows(db, resource_id: str) -> List[Dict[str, Any]]:
    """Every row in order (a move reads them all once)."""
    rows = await db.fetch(f"SELECT {_ROW} FROM dataset_rows WHERE resource_id = $1 ORDER BY row_index, id",
                          resource_id)
    return [dict(r) for r in rows]


async def tables_with_rows(db) -> List[Dict[str, Any]]:
    """Every table, the rows and bytes it keeps here, its automation and that automation's owner."""
    rows = await db.fetch(
        """SELECT wr.*, w.name AS workflow_name, w.owner_id AS workflow_owner_id, u.email AS owner_email,
                  COALESCE(kept.row_count, 0) AS row_count, COALESCE(kept.bytes, 0) AS bytes
           FROM workflow_resources wr
           LEFT JOIN workflows w ON w.id = wr.workflow_id
           LEFT JOIN auth.users u ON u.id = w.owner_id
           LEFT JOIN LATERAL (SELECT COUNT(*) AS row_count, SUM(pg_column_size(dr.data)) AS bytes
                              FROM dataset_rows dr WHERE dr.resource_id = wr.id) kept ON true
           WHERE wr.resource_type = 'dataset' ORDER BY w.owner_id, wr.created_at, wr.id""")
    return [dict(r) for r in rows]


class PostgresDatasets:
    """``utils.dataset_store.DatasetStore`` over ``dataset_rows``. Appends to
    one table are serialized on its resource row, so positions never repeat."""

    def __init__(self, pool):
        self._pool = pool

    async def create(self, resource: Mapping[str, Any]) -> None:
        return None  # rows are keyed by the resource; there is nothing to make

    async def rows(self, resource: Mapping[str, Any], *, limit: int,
                   offset: int) -> Tuple[List[Dict[str, Any]], int]:
        async with self._pool.acquire() as conn:
            return await page(conn, str(resource["id"]), limit=limit, offset=offset)

    async def append(self, resource: Mapping[str, Any], rows: Sequence[Dict[str, Any]]) -> int:
        resource_id = str(resource["id"])
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT 1 FROM workflow_resources WHERE id = $1 FOR UPDATE", resource_id)
            last = await conn.fetchval(
                "SELECT COALESCE(MAX(row_index), -1) FROM dataset_rows WHERE resource_id = $1", resource_id)
            for start in range(0, len(rows), _INSERT_ROWS):
                chunk = rows[start:start + _INSERT_ROWS]
                values = ", ".join(f"($1, ${2 + 2 * i}, ${3 + 2 * i})" for i in range(len(chunk)))
                params: List[Any] = [resource_id]
                for i, data in enumerate(chunk):
                    params += [last + 1 + start + i, data]
                await conn.execute(f"INSERT INTO dataset_rows (resource_id, row_index, data) VALUES {values}",
                                   *params)
            total = await conn.fetchval("SELECT COUNT(*) FROM dataset_rows WHERE resource_id = $1", resource_id)
            await set_row_count(conn, resource_id, total)
        return int(total)

    async def update_row(self, resource: Mapping[str, Any], row_id: str, data: Dict[str, Any]) -> bool:
        resource_id = str(resource["id"])
        async with self._pool.acquire() as conn, conn.transaction():
            result = await conn.execute("UPDATE dataset_rows SET data = $1 WHERE id = $2 AND resource_id = $3",
                                        data, row_id, resource_id)
            if result == "UPDATE 0":
                return False
            await touch(conn, resource_id)
        return True

    async def delete_rows(self, resource: Mapping[str, Any], row_ids: Sequence[str]) -> Tuple[int, int]:
        resource_id = str(resource["id"])
        async with self._pool.acquire() as conn, conn.transaction():
            deleted = await conn.fetchval(
                """WITH gone AS (DELETE FROM dataset_rows WHERE id = ANY($1::uuid[]) AND resource_id = $2
                                 RETURNING 1)
                   SELECT COUNT(*) FROM gone""", list(row_ids), resource_id)
            total = await conn.fetchval("SELECT COUNT(*) FROM dataset_rows WHERE resource_id = $1", resource_id)
            await set_row_count(conn, resource_id, total)
        return int(deleted), int(total)

    async def drop(self, resource: Mapping[str, Any]) -> None:
        return None  # its rows go with its resource row (ON DELETE CASCADE)

    async def drop_workflow(self, workflow_id: str) -> None:
        return None  # its tables' rows go with their resource rows

    async def locations(self, resources: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]:
        return {}  # in the engine's own database, not one of their own

