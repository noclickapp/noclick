"""ResourceRepo — SQL for workflow_resources.

Owns the CRUD for `workflow_resources`; a table's rows go through
``utils.dataset_store`` (in Postgres, ``repositories.datasets``). Reads and writes are typed at the repo boundary: rows
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

import uuid
from typing import Any, Dict, List, Optional, Tuple

from repositories.workflow import WorkflowRepo


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert an asyncpg Record to a plain dict for the repo boundary."""
    return dict(row) if row is not None else None  # type: ignore[return-value]


class ResourceRepo:
    """Read+write SQL for workflow_resources.

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
            return await WorkflowRepo(self._pool).get_organization_id(conn, workflow_id)

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
        filters. Includes the user's account files and resources from owned
        workflows or workflows shared with the user or their organization.
        Mirrors the resource-shares access model in
        ``utils.access_control``.
        """
        # user_id is $1 and is referenced three times in the access sub-query
        # (owner_id, target_user_id, org member's user_id). Additional
        # filters append params starting at $2.
        conditions: List[str] = [
            # A reserved chat upload whose bytes may never have landed isn't a file yet.
            "NOT COALESCE(wr.metadata ? 'pending', false)",
            """(
                (wr.workflow_id IS NULL AND wr.owner_id = $1)
                OR wr.workflow_id IN (SELECT id FROM workflows WHERE owner_id = $1)
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

    async def list_account_attachments(
        self, owner_id: str, sources, *, query: str, limit: int,
    ) -> List[Dict[str, Any]]:
        """The owner's account-level files (no workflow) from ``sources``,
        newest first, name containing ``query``; a reserved upload that no
        turn has read yet (``metadata.pending``) isn't listed."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, mime_type, size_bytes, storage_ref, created_at
                FROM workflow_resources
                WHERE owner_id = $1 AND workflow_id IS NULL
                  AND metadata->>'source' = ANY($2::text[])
                  AND NOT metadata ? 'pending'
                  AND ($3 = '' OR strpos(lower(name), lower($3)) > 0)
                ORDER BY created_at DESC
                LIMIT $4
                """,
                owner_id, list(sources), query, limit,
            )
        return [dict(r) for r in rows]

    # ── Resource writes ───────────────────────────────────────────────

    async def create_resource(
        self,
        *,
        owner_id: str,
        organization_id: Optional[str],
        workflow_id: Optional[str],
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
        """DELETE a resource row (a table's rows in Postgres cascade with it)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM workflow_resources WHERE id = $1", resource_id,
            )

    async def set_metadata(self, resource_id: str, metadata: Dict[str, Any]) -> None:
        """Replace a resource's metadata (e.g. a file's saved reading)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE workflow_resources SET metadata = $1, updated_at = NOW() WHERE id = $2",
                metadata, resource_id,
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

    async def dataset_for_run(self, resource_id: str, workflow_id: Optional[str],
                              user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """The table a run of ``workflow_id`` reads, or None: one of its own, or
        (a picker offers them) one in another workflow ``user_id`` may view. A
        UUID alone never discloses a table."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT wr.* FROM workflow_resources wr
                WHERE wr.id = $1 AND wr.resource_type = 'dataset'
                  AND (
                      wr.workflow_id = $2
                      OR (
                          $3::uuid IS NOT NULL
                          AND (
                              wr.workflow_id IN (SELECT id FROM workflows WHERE owner_id = $3)
                              OR wr.workflow_id IN (
                                  SELECT rs.resource_id::uuid
                                  FROM resource_shares rs
                                  LEFT JOIN organization_members om ON rs.target_org_id = om.organization_id
                                  WHERE rs.resource_type = 'workflow'
                                    AND (
                                        (rs.target_type = 'user' AND rs.target_user_id = $3)
                                        OR (rs.target_type = 'organization' AND om.user_id = $3)
                                    )
                              )
                          )
                      )
                  )
                """,
                resource_id, workflow_id, user_id,
            )
        return _row_to_dict(row) if row is not None else None


class ResourceReadings:
    """What the media digest read from an owner's stored files (a transcript,
    a document's text), kept on each file's metadata under the keys account
    attachments already use (``extracted_text``, ``extraction_method``), so a
    file read in one agent's turn is reused by every turn after it: one paid
    read. ``reading_until`` (database epoch seconds) leases the read to one
    reader at a time; ``extraction_truncated`` records a clipped document.
    The pool resolves on first use (``None``: the runtime pool)."""

    def __init__(self, owner_id: str, pool=None):
        self._owner_id = owner_id
        self._pool = pool

    def _db(self):
        if self._pool is None:
            from utils.database_pool import get_native_pool

            self._pool = get_native_pool()
        return self._pool

    async def take(self, resource_id: str, *, lease_s: float) -> Tuple[str, Optional[Dict[str, Any]]]:
        """``("read", metadata)`` when a reading is kept; ``("claimed", None)``
        when this reader should read it (it holds the lease now); ``("busy",
        None)`` while another reader's lease runs; ``("absent", None)`` for a
        file that isn't the owner's (nothing is kept for it)."""
        try:
            uuid.UUID(str(resource_id))
        except ValueError:
            return "absent", None
        async with self._db().acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT metadata, extract(epoch FROM clock_timestamp())::float8 AS now FROM workflow_resources
                   WHERE id = $1::uuid AND owner_id = $2::uuid FOR UPDATE""",
                str(resource_id), self._owner_id,
            )
            if row is None:
                return "absent", None
            metadata = row["metadata"] or {}
            if metadata.get("extracted_text"):
                return "read", metadata
            if float(metadata.get("reading_until") or 0) > row["now"]:
                return "busy", None
            await conn.execute(
                """UPDATE workflow_resources SET metadata = metadata || jsonb_build_object('reading_until', $2::float8)
                   WHERE id = $1::uuid""",
                str(resource_id), row["now"] + lease_s,
            )
        return "claimed", None

    async def keep(self, resource_id: str, reading: Optional[Dict[str, Any]]) -> None:
        """Save ``reading`` (None: nothing worth keeping) and end the lease."""
        await self._db().execute(
            """UPDATE workflow_resources SET metadata = (metadata - 'reading_until') || $3::jsonb, updated_at = NOW()
               WHERE id = $1::uuid AND owner_id = $2::uuid""",
            str(resource_id), self._owner_id, reading or {},
        )
