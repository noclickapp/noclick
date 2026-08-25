"""SharedAgentLinkRepo — SQL for shared agent chat links.

One row per agent node whose public chat page has been minted; the row id is
the capability (webhook security model). Mint is idempotent per
(workflow, node); rotate replaces the capability (old URL 404s immediately).

``load_for_visit`` is the single resolution query every consumer shares —
the anonymous socket connect branch, the visitor send/resume handlers, and
the public metadata endpoint. Callers must treat ``is_active = false`` OR
``user_id != owner_id`` (link minted by a since-replaced owner) as not-found.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class SharedAgentLinkRepo:
    """Constructor takes the pool proxy; each method acquires per call."""

    def __init__(self, pool):
        self._pool = pool

    async def get_or_create(
        self, user_id: str, workflow_id, node_id: str
    ) -> Dict[str, Any]:
        """Mint (or fetch) the link for one agent node. Idempotent per
        (workflow, node)."""
        workflow_uuid = _as_uuid(workflow_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, is_active FROM shared_agent_links WHERE workflow_id = $1 AND node_id = $2",
                workflow_uuid, node_id,
            )
            if not row:
                row = await conn.fetchrow(
                    """
                    INSERT INTO shared_agent_links (user_id, workflow_id, node_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (workflow_id, node_id) DO UPDATE SET node_id = EXCLUDED.node_id
                    RETURNING id, is_active
                    """,
                    _as_uuid(user_id), workflow_uuid, node_id,
                )
        return {"link_id": str(row["id"]), "is_active": row["is_active"]}

    async def rotate(
        self, user_id: str, workflow_id, node_id: str
    ) -> Dict[str, Any]:
        """Replace the capability: delete the old row, mint a fresh id. The
        old URL 404s immediately — already-connected visitors are rejected on
        their next send."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM shared_agent_links WHERE workflow_id = $1 AND node_id = $2",
                _as_uuid(workflow_id), node_id,
            )
        return await self.get_or_create(user_id, workflow_id, node_id)

    async def set_active(self, workflow_id, node_id: str, is_active: bool) -> bool:
        """Toggle the link without changing the capability. False if no row."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE shared_agent_links SET is_active = $3 WHERE workflow_id = $1 AND node_id = $2",
                _as_uuid(workflow_id), node_id, is_active,
            )
        return result == "UPDATE 1"

    async def load_for_visit(self, link_id: str) -> Optional[Dict[str, Any]]:
        """Resolve a capability id to link + workflow context. Returns None
        for anything that must read as not-found: bad UUID, missing row,
        inactive link, deleted workflow, or a link whose minting user no
        longer owns the workflow (ownership-transfer defense)."""
        try:
            link_uuid = uuid.UUID(str(link_id))
        except (ValueError, AttributeError, TypeError):
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT l.id, l.user_id, l.workflow_id, l.node_id, l.is_active,
                       wf.workflow AS workflow_config, wf.organization_id,
                       wf.name AS workflow_name, wf.owner_id
                FROM shared_agent_links l
                JOIN workflows wf ON l.workflow_id = wf.id
                WHERE l.id = $1 AND wf.deleted_at IS NULL
                """,
                link_uuid,
            )
        if not row or not row["is_active"] or str(row["user_id"]) != str(row["owner_id"]):
            return None
        return dict(row)

    async def touch_usage(self, link_id: str) -> None:
        """Best-effort usage stamp after a visitor turn is dispatched."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE shared_agent_links SET last_used_at = now(), turn_count = turn_count + 1 WHERE id = $1",
                uuid.UUID(str(link_id)),
            )
