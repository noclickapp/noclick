"""SharedRunLinkRepo — SQL for shared Test Run result links.

One row per shared run; the row id is the capability (webhook security
model). Unlike agent links a run link is a STATIC snapshot — nothing
executes through it — so mint is per-share, not idempotent per node.

``load_for_view`` mirrors SharedAgentLinkRepo.load_for_visit: bad UUID,
missing row, inactive link, deleted workflow, or a link whose minting user
no longer owns the workflow (ownership-transfer defense) all read as
not-found.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class SharedRunLinkRepo:
    """Constructor takes the pool proxy; each method acquires per call."""

    def __init__(self, pool):
        self._pool = pool

    async def create(
        self, user_id: str, workflow_id, title: str, snapshot: Dict[str, Any]
    ) -> str:
        async with self._pool.acquire() as conn:
            # Codec'd main pool: jsonb params take the RAW dict (json.dumps
            # here double-encodes into a string scalar — the structured-value regression fix class).
            row = await conn.fetchrow(
                """
                INSERT INTO shared_run_links (user_id, workflow_id, title, snapshot)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                _as_uuid(user_id), _as_uuid(workflow_id), title, snapshot,
            )
        return str(row["id"])

    async def load_for_view(self, link_id: str) -> Optional[Dict[str, Any]]:
        try:
            link_uuid = uuid.UUID(str(link_id))
        except (ValueError, AttributeError, TypeError):
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT l.id, l.user_id, l.title, l.snapshot, l.is_active,
                       l.created_at, wf.name AS workflow_name, wf.owner_id
                FROM shared_run_links l
                JOIN workflows wf ON l.workflow_id = wf.id
                WHERE l.id = $1 AND wf.deleted_at IS NULL
                """,
                link_uuid,
            )
        if not row or not row["is_active"] or str(row["user_id"]) != str(row["owner_id"]):
            return None
        return dict(row)
