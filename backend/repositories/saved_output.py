"""SavedOutputRepo — SQL for workflow_saved_output reads and writes.

Owns the visibility SELECT (self-owned + public + user-share + org-share),
edit-permission check, INSERT, dynamic UPDATE (allowlisted columns), and
the delete-with-shares cleanup. Handlers instantiate a repo with the pool,
open one `pool.acquire()` block, then call typed methods that share the
pinned connection with billing-side helpers (``check_saved_output_limit``,
``get_user_org_context``) which continue to take ``conn``.

The visibility SQL is intentionally identical to the historical inline query
in ``saved_output_handler`` — the DISTINCT ON + LEFT JOIN pattern lets one
row satisfy multiple visibility branches without duplication, and the
``sort_order`` field is returned so the handler can preserve the
"own-first then shared" ordering that the UI relies on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SavedOutputRow:
    """One workflow_saved_output row as returned across the repo boundary.

    Fields mirror the DB columns the handler needs to render a
    ``SavedOutputInfo``. ``output`` is a JSONB column — asyncpg's registered
    jsonb codec decodes it to a Python dict directly (may be None if the
    row was written pre-schema).
    """
    id: Any
    owner_id: Any
    node_type: str
    name: str
    output: Optional[Dict[str, Any]]
    is_public: bool
    created_at: datetime
    updated_at: datetime


class SavedOutputRepo:
    """Read/write SQL for workflow_saved_output.

    Constructor takes a pool proxy — currently unused by the methods because
    every method takes an externally-managed ``conn`` (the handler holds the
    acquire so billing checks like ``check_saved_output_limit`` and helpers
    like ``get_user_org_context`` can share the same pinned connection).
    Keeping ``pool`` in the constructor matches the repository pattern and
    leaves room for standalone read methods later.
    """

    # Columns the update method is allowed to set. Defense-in-depth against a
    # caller passing an attacker-controlled key: interpolating column names
    # into SQL requires an allowlist because Postgres doesn't parametrize
    # identifiers. ``updated_at`` is appended by the method itself.
    _ALLOWED_UPDATE_COLUMNS = frozenset({"name", "is_public"})

    _INSERT_SQL = """
        INSERT INTO workflow_saved_output (
            owner_id, organization_id, node_type, name, output,
            is_public, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        RETURNING id, owner_id, organization_id, node_type, name, output,
                  is_public, created_at, updated_at
    """

    # Visibility SELECT: own row, public, user share, org share in the
    # caller's current org context. DISTINCT ON collapses a row that matches
    # multiple visibility branches to one; sort_order lets the caller sort
    # own-first without a second query.
    _LIST_VISIBLE_SQL = """
        SELECT DISTINCT ON (so.id)
            so.id, so.owner_id, so.node_type, so.name, so.output, so.is_public,
            so.created_at, so.updated_at,
            CASE WHEN so.owner_id = $2 THEN 0 ELSE 1 END as sort_order
        FROM workflow_saved_output so
        LEFT JOIN resource_shares us
            ON us.resource_type = 'saved_output'
            AND us.resource_id = so.id
            AND us.target_type = 'user'
            AND us.target_user_id = $2
        LEFT JOIN resource_shares os
            ON os.resource_type = 'saved_output'
            AND os.resource_id = so.id
            AND os.target_type = 'organization'
            AND os.target_org_id = $3
        WHERE so.node_type = $1
          AND (
              so.owner_id = $2
              OR so.is_public = true
              OR us.id IS NOT NULL
              OR ($3::uuid IS NOT NULL AND os.id IS NOT NULL)
          )
        ORDER BY so.id, sort_order, so.updated_at DESC
    """

    _GET_VISIBLE_SQL = """
        SELECT so.id, so.owner_id, so.node_type, so.name, so.output, so.is_public,
               so.created_at, so.updated_at
        FROM workflow_saved_output so
        WHERE so.id = $1
          AND (
              so.owner_id = $2
              OR so.is_public = true
              OR EXISTS (
                SELECT 1 FROM resource_shares
                WHERE resource_type = 'saved_output'
                  AND resource_id = $1
                  AND target_type = 'user'
                  AND target_user_id = $2
              )
              OR ($3::uuid IS NOT NULL AND EXISTS (
                SELECT 1 FROM resource_shares
                WHERE resource_type = 'saved_output'
                  AND resource_id = $1
                  AND target_type = 'organization'
                  AND target_org_id = $3
              ))
          )
    """

    _HAS_EDIT_SQL = """
        SELECT 1
        FROM workflow_saved_output so
        WHERE so.id = $1
          AND (
            so.owner_id = $2
            OR EXISTS (
              SELECT 1 FROM resource_shares
              WHERE resource_type = 'saved_output'
                AND resource_id = $1
                AND target_type = 'user'
                AND target_user_id = $2
                AND permission = 'edit'
            )
            OR ($3::uuid IS NOT NULL AND EXISTS (
              SELECT 1 FROM resource_shares
              WHERE resource_type = 'saved_output'
                AND resource_id = $1
                AND target_type = 'organization'
                AND target_org_id = $3
                AND permission = 'edit'
            ))
          )
    """

    _DELETE_ROW_SQL = "DELETE FROM workflow_saved_output WHERE id = $1"
    _DELETE_SHARES_SQL = (
        "DELETE FROM resource_shares "
        "WHERE resource_type = 'saved_output' AND resource_id = $1"
    )

    def __init__(self, pool):
        self._pool = pool

    @staticmethod
    def _row_to_dc(row) -> SavedOutputRow:
        return SavedOutputRow(
            id=row["id"],
            owner_id=row["owner_id"],
            node_type=row["node_type"],
            name=row["name"],
            output=row["output"],
            is_public=row["is_public"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def create(
        self,
        conn,
        *,
        owner_id: str,
        organization_id: Optional[str],
        node_type: str,
        name: str,
        output: Dict[str, Any],
        is_public: bool,
    ) -> Optional[SavedOutputRow]:
        """Insert a new saved output. Returns the created row, or None if the
        INSERT failed to produce a row (should not happen in practice)."""
        row = await conn.fetchrow(
            self._INSERT_SQL,
            owner_id, organization_id, node_type, name, output, is_public,
        )
        return self._row_to_dc(row) if row else None

    async def list_visible(
        self,
        conn,
        *,
        node_type: str,
        user_id: str,
        org_id: Optional[str],
    ) -> List[Tuple[SavedOutputRow, int]]:
        """Return (row, sort_order) tuples for outputs of ``node_type`` that
        the user can see (own, public, shared to user, shared to current org).
        The handler applies the final own-first/updated-at-desc sort using
        the returned ``sort_order``."""
        rows = await conn.fetch(self._LIST_VISIBLE_SQL, node_type, user_id, org_id)
        return [(self._row_to_dc(r), r["sort_order"]) for r in rows]

    async def get_visible(
        self,
        conn,
        *,
        saved_output_id: str,
        user_id: str,
        org_id: Optional[str],
    ) -> Optional[SavedOutputRow]:
        """Fetch a saved output if the user can see it, else None."""
        row = await conn.fetchrow(self._GET_VISIBLE_SQL, saved_output_id, user_id, org_id)
        return self._row_to_dc(row) if row else None

    async def user_has_edit(
        self,
        conn,
        *,
        saved_output_id: str,
        user_id: str,
        org_id: Optional[str],
    ) -> bool:
        """True iff the user can edit — owner, user-share with edit, or
        org-share with edit in the user's current org context."""
        row = await conn.fetchrow(self._HAS_EDIT_SQL, saved_output_id, user_id, org_id)
        return row is not None

    async def update(
        self,
        conn,
        *,
        saved_output_id: str,
        updates: Dict[str, Any],
    ) -> Optional[SavedOutputRow]:
        """Dynamic UPDATE against ``_ALLOWED_UPDATE_COLUMNS``.

        Interpolating column names into the SET clause is required because
        Postgres doesn't allow identifiers as parameters; every key in
        ``updates`` MUST be in the allowlist or this raises ValueError before
        any SQL runs. ``updated_at = NOW()`` is always set.
        """
        if not updates:
            raise ValueError("update called with no fields")
        for k in updates:
            if k not in self._ALLOWED_UPDATE_COLUMNS:
                raise ValueError(
                    f"Column not allowed for update: {k!r} "
                    f"(allowed: {sorted(self._ALLOWED_UPDATE_COLUMNS)})"
                )

        set_parts: List[str] = []
        params: List[Any] = [saved_output_id]
        idx = 2
        for col, value in updates.items():
            set_parts.append(f"{col} = ${idx}")
            params.append(value)
            idx += 1
        set_parts.append("updated_at = NOW()")
        set_clause = ", ".join(set_parts)

        sql = (
            f"UPDATE workflow_saved_output SET {set_clause} "
            f"WHERE id = $1 "
            f"RETURNING id, owner_id, node_type, name, output, is_public, "
            f"          created_at, updated_at"
        )
        row = await conn.fetchrow(sql, *params)
        return self._row_to_dc(row) if row else None

    async def delete(self, conn, *, saved_output_id: str) -> None:
        """Delete the row and all its resource_shares in one transaction.

        The historical handler ran these as two autocommit statements; wrapping
        them in a real transaction (post-2026-07-01 proxy fix) closes the
        window where a crash between the two would leave orphaned share rows.
        """
        async with conn.transaction():
            await conn.execute(self._DELETE_ROW_SQL, saved_output_id)
            await conn.execute(self._DELETE_SHARES_SQL, saved_output_id)
