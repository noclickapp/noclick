"""ResourceRepo — SQL for workflow_resources + dataset_rows.

Owns the CRUD for `workflow_resources` and the row-level operations on
`dataset_rows`. Reads and writes are typed at the repo boundary: rows
returned to callers are plain ``dict[str, Any]`` mapped from asyncpg
records — handlers never see raw ``asyncpg.Record``.

Cleanup of ALL workflow resources on workflow deletion is intentionally
NOT here — that path lives in ``utils.workflow_resource_manager`` because
it also orchestrates R2 blob deletion + cascade. This repo is scoped to
the per-resource SQL that used to live inline in ``resource_handler``.

Rules recap (see ``utils/DB_MIGRATION.md``):
  - Multi-statement writes go inside ``async with self._pool.acquire()``
    plus ``async with conn.transaction():`` so atomicity is engaged.
  - No column-name interpolation in this repo — every filter is a bind
    parameter — so no allowlist is needed today.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert an asyncpg Record to a plain dict for the repo boundary."""
    return dict(row) if row is not None else None  # type: ignore[return-value]


class ResourceRepo:
    """Read+write SQL for workflow_resources and dataset_rows.

    Constructor takes a pool proxy from ``DatabasePoolMixin.get_pool()``.
    Each method opens its own ``async with self._pool.acquire()`` so
    multi-statement work stays inside a single pinned connection. Access
    control (workflow ownership + shares) is deliberately kept in the
    handler — ``utils.access_control.check_resource_access`` is a
    cross-domain concern that reads workflows / resource_shares /
    organization_members and doesn't belong to a resource repo.
    """

    def __init__(self, pool):
        self._pool = pool

    # ── Resource reads ────────────────────────────────────────────────

    async def get_workflow_organization_id(self, workflow_id: str) -> Optional[str]:
        """Return the parent workflow's ``organization_id``, or None if the
        workflow row is missing / has no org tag. Used by create_resource to
        stamp the org context onto the new resource row.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT organization_id FROM workflows WHERE id = $1", workflow_id,
            )
        if not row:
            return None
        org_id = row["organization_id"]
        return str(org_id) if org_id is not None else None

    async def get_resource(self, resource_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single resource row by id. Returns the row as a plain
        dict, or None if not found. Access checks happen in the handler
        against the row's ``workflow_id``.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_resources WHERE id = $1", resource_id,
            )
        return _row_to_dict(row) if row is not None else None

    async def list_accessible_resources(
        self,
        *,
        user_id: str,
        workflow_id: Optional[str],
        resource_type: Optional[str],
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """List resources the user can access, with optional workflow/type
        filters. The access scope is: workflows the user owns, OR workflows
        directly shared with the user, OR workflows shared with an org the
        user is a member of. Mirrors the resource-shares access model in
        ``utils.access_control``.
        """
        # user_id is $1 and is referenced three times in the access sub-query
        # (owner_id, target_user_id, org member's user_id). Additional
        # filters append params starting at $2.
        conditions: List[str] = [
            """(
                wr.workflow_id IN (SELECT id FROM workflows WHERE owner_id = $1)
                OR wr.workflow_id IN (
                    SELECT rs.resource_id::uuid FROM resource_shares rs
                    LEFT JOIN organization_members om ON rs.target_org_id = om.organization_id
                    WHERE rs.resource_type = 'workflow'
                      AND (
                          (rs.target_type = 'user' AND rs.target_user_id = $1)
                          OR (rs.target_type = 'organization' AND om.user_id = $1)
                      )
                )
            )"""
        ]
        params: List[Any] = [user_id]
        idx = 2

        if workflow_id is not None:
            conditions.append(f"wr.workflow_id = ${idx}")
            params.append(workflow_id)
            idx += 1

        if resource_type is not None:
            conditions.append(f"wr.resource_type = ${idx}")
            params.append(resource_type)
            idx += 1

        where_clause = " AND ".join(conditions)
        query = (
            f"SELECT * FROM workflow_resources wr WHERE {where_clause} "
            f"ORDER BY wr.updated_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
        )
        params.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    # ── Resource writes ───────────────────────────────────────────────

    async def create_resource(
        self,
        *,
        owner_id: str,
        organization_id: Optional[str],
        workflow_id: str,
        node_id: Optional[str],
        resource_type: str,
        name: str,
        mime_type: Optional[str],
        size_bytes: int,
        storage_ref: Optional[str],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """INSERT and return the new row as a plain dict."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO workflow_resources
                    (owner_id, organization_id, workflow_id, node_id, resource_type,
                     name, mime_type, size_bytes, storage_ref, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING *
                """,
                owner_id, organization_id, workflow_id, node_id, resource_type,
                name, mime_type, size_bytes, storage_ref, metadata,
            )
        return dict(row)

    async def delete_resource(self, resource_id: str) -> None:
        """DELETE a resource row. dataset_rows cascade at the DB level."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM workflow_resources WHERE id = $1", resource_id,
            )

    async def update_storage_ref(
        self, resource_id: str, storage_ref: str, mime_type: str,
    ) -> None:
        """Persist the R2 storage key + content type after a presigned URL
        is minted. Bumps ``updated_at``.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflow_resources
                SET storage_ref = $1, mime_type = $2, updated_at = NOW()
                WHERE id = $3
                """,
                storage_ref, mime_type, resource_id,
            )

    # ── Dataset row reads ─────────────────────────────────────────────

    async def list_dataset_rows_with_count(
        self, resource_id: str, limit: int, offset: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return (page_rows, total_count) in a single pinned acquire so
        the two reads see a consistent snapshot of the dataset.
        """
        async with self._pool.acquire() as conn:
            total_count = await conn.fetchval(
                "SELECT COUNT(*) FROM dataset_rows WHERE resource_id = $1",
                resource_id,
            )
            rows = await conn.fetch(
                """
                SELECT id, row_index, data, created_at
                FROM dataset_rows
                WHERE resource_id = $1
                ORDER BY row_index
                LIMIT $2 OFFSET $3
                """,
                resource_id, limit, offset,
            )
        return [dict(r) for r in rows], int(total_count or 0)

    # ── Dataset row writes ────────────────────────────────────────────

    async def append_dataset_rows(
        self,
        resource_id: str,
        rows_data: List[Any],
        existing_metadata: Dict[str, Any],
    ) -> int:
        """Append rows to a dataset atomically: MAX(row_index) probe →
        multi-VALUES INSERT → metadata.row_count update.

        Returns the number of rows inserted (== len(rows_data)). The
        metadata update always runs — matches the handler's prior behavior
        of bumping ``updated_at`` even for a zero-row append.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                max_index = await conn.fetchval(
                    "SELECT COALESCE(MAX(row_index), -1) FROM dataset_rows "
                    "WHERE resource_id = $1",
                    resource_id,
                )

                if rows_data:
                    # $1 = resource_id; each row uses two positional params
                    # (row_index, data) starting at $2.
                    values_sql: List[str] = []
                    params: List[Any] = [resource_id]
                    idx = 2
                    for i, row_data in enumerate(rows_data):
                        values_sql.append(f"($1, ${idx}, ${idx + 1})")
                        params.extend([max_index + 1 + i, row_data])
                        idx += 2
                    await conn.execute(
                        "INSERT INTO dataset_rows (resource_id, row_index, data) "
                        f"VALUES {', '.join(values_sql)}",
                        *params,
                    )

                new_count = int(max_index) + 1 + len(rows_data)
                metadata = dict(existing_metadata or {})
                metadata["row_count"] = new_count
                await conn.execute(
                    """
                    UPDATE workflow_resources
                    SET metadata = $1, updated_at = NOW()
                    WHERE id = $2
                    """,
                    metadata, resource_id,
                )

        return len(rows_data)

    async def update_dataset_row_and_touch(
        self, row_id: str, resource_id: str, data: Any,
    ) -> bool:
        """UPDATE a single dataset row + touch the parent resource's
        ``updated_at``. Returns False when the row_id/resource_id pair
        doesn't match a row (handler surfaces "Row not found").

        The touch and the update ride the same transaction — the parent
        row's ``updated_at`` should only advance if the child update
        actually landed.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    UPDATE dataset_rows SET data = $1
                    WHERE id = $2 AND resource_id = $3
                    """,
                    data, row_id, resource_id,
                )
                if result == "UPDATE 0":
                    return False
                await conn.execute(
                    "UPDATE workflow_resources SET updated_at = NOW() WHERE id = $1",
                    resource_id,
                )
        return True

    async def delete_dataset_rows(
        self,
        resource_id: str,
        row_ids: List[str],
        existing_metadata: Dict[str, Any],
    ) -> int:
        """Delete rows and refresh metadata.row_count atomically. Returns
        the number of rows actually removed (parsed from the DELETE tag).
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    """
                    DELETE FROM dataset_rows
                    WHERE id = ANY($1::uuid[]) AND resource_id = $2
                    """,
                    row_ids, resource_id,
                )
                # asyncpg returns "DELETE N".
                try:
                    deleted_count = int(result.split()[-1])
                except (ValueError, IndexError):
                    deleted_count = 0

                new_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM dataset_rows WHERE resource_id = $1",
                    resource_id,
                )
                metadata = dict(existing_metadata or {})
                metadata["row_count"] = int(new_count or 0)
                await conn.execute(
                    """
                    UPDATE workflow_resources
                    SET metadata = $1, updated_at = NOW()
                    WHERE id = $2
                    """,
                    metadata, resource_id,
                )

        return deleted_count
