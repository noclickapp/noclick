"""Repository for builder input bridge links (public ask-answering capability).

A link row is minted when an agent-initiated headless builder run parks on an
<ask/>; the row id is the capability an anonymous visitor presents to read the
questions and submit answers. Backend-only table (RLS on, no policies).
"""
import logging
import uuid as uuid_module
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BuilderBridgeRepo:
    def __init__(self, pool):
        self._pool = pool

    async def create_link(
        self,
        *,
        user_id: str,
        workflow_id: str,
        builder_conversation_id: str,
        ask_id: str,
        agent_conversation_id: Optional[str],
        agent_node_id: Optional[str],
        inputs: List[Dict[str, Any]],
        workflow_name: Optional[str],
    ) -> str:
        """Insert a pending link and return its id (the capability)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO builder_input_links (
                    user_id, workflow_id, builder_conversation_id, ask_id,
                    agent_conversation_id, agent_node_id, inputs, workflow_name
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                uuid_module.UUID(user_id), uuid_module.UUID(workflow_id),
                builder_conversation_id, ask_id,
                agent_conversation_id, agent_node_id, inputs, workflow_name,
            )
        return str(row["id"])

    async def load_pending(self, link_id: str) -> Optional[Dict[str, Any]]:
        """The link row iff it is pending and unexpired — the ONLY resolution
        rule for visitor reads and submits (mirrors SharedAgentLinkRepo)."""
        try:
            lid = uuid_module.UUID(link_id)
        except ValueError:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, workflow_id, builder_conversation_id, ask_id,
                       agent_conversation_id, agent_node_id, inputs, workflow_name,
                       created_at, expires_at
                FROM builder_input_links
                WHERE id = $1 AND status = 'pending' AND expires_at > NOW()
                """,
                lid,
            )
        return dict(row) if row else None

    async def find_pending_for_ask(
        self, builder_conversation_id: str, ask_id: str
    ) -> Optional[str]:
        """An existing pending link for this exact ask, if any — the share
        button is idempotent (clicking twice hands out the SAME url)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM builder_input_links
                WHERE builder_conversation_id = $1 AND ask_id = $2
                  AND status = 'pending' AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1
                """,
                builder_conversation_id, ask_id,
            )
        return str(row["id"]) if row else None

    async def update_inputs(self, link_id: str, inputs: List[Dict[str, Any]]) -> None:
        """Persist a healed inputs snapshot (see utils.builder_bridge.heal_link_inputs)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE builder_input_links SET inputs = $2 WHERE id = $1::uuid",
                uuid_module.UUID(link_id), inputs,
            )

    async def void_pending_links_for_ask(
        self, builder_conversation_id: str, ask_id: str
    ) -> None:
        """Expire every still-pending link for an ask that just got consumed —
        the owner answered in the drawer (or a bridge submit on another link
        resumed the run), so the shared page must stop resolving. Without this
        a stale link kept loading and a late submit consumed it while firing
        nothing (2026-07-19)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE builder_input_links
                SET status = 'expired'
                WHERE builder_conversation_id = $1 AND ask_id = $2 AND status = 'pending'
                """,
                builder_conversation_id, ask_id,
            )

    async def load_origin(
        self, builder_conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """The agent origin of a builder conversation, from its newest bridge
        link (any status) — the durable record that survives resume cycles.
        The resume path rebuilds user_context from scratch, so without this a
        bridge-answered run would lose its agent return address and never
        notify the agent of its result (or mint a link for a second ask)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT agent_conversation_id, agent_node_id
                FROM builder_input_links
                WHERE builder_conversation_id = $1 AND agent_conversation_id IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                builder_conversation_id,
            )
        return dict(row) if row else None

    async def mark_answered(self, link_id: str) -> bool:
        """Consume the link (exactly-once submit). True iff THIS call flipped
        it — a concurrent second submit loses and must not resume the run."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE builder_input_links
                SET status = 'answered', answered_at = NOW()
                WHERE id = $1 AND status = 'pending' AND expires_at > NOW()
                """,
                uuid_module.UUID(link_id),
            )
        return result.endswith("1")
