"""SQL for the nightly trigger resync (``WebhookManager.resync_trigger_registrations``):
the workflows it may visit, and its one row in ``trigger_resync_state``: whether it
may act, and where its lap of them stands.

No row means nobody has turned it on and no lap has started."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, Sequence, Set
from uuid import UUID


@dataclass(frozen=True)
class State:
    registers: bool = False
    registers_set_at: Optional[datetime] = None
    after_workflow_id: Optional[UUID] = None
    lap_finished_at: Optional[datetime] = None


async def read_state(pool) -> State:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT registers, registers_set_at, after_workflow_id, lap_finished_at FROM trigger_resync_state"
        )
    return State(**dict(row)) if row else State()


async def set_registers(pool, on: bool) -> None:
    """The switch a person throws. A pass under way sees it at its next workflow (``advance``)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO trigger_resync_state (registers, registers_set_at) VALUES ($1, now())
            ON CONFLICT (singleton) DO UPDATE
            SET registers = EXCLUDED.registers, registers_set_at = now(), updated_at = now()
            """,
            on,
        )


async def advance(pool, *, expected: Optional[UUID], to: Optional[UUID], lap_finished: bool = False) -> bool:
    """Move the lap on, only while the pass may act and the lap is where it left it:
    False says it was turned off, or another pass has taken the lap over."""
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            """
            UPDATE trigger_resync_state
            SET after_workflow_id = $2,
                lap_finished_at = CASE WHEN $3 THEN now() ELSE lap_finished_at END,
                updated_at = now()
            WHERE singleton AND registers AND after_workflow_id IS NOT DISTINCT FROM $1
            RETURNING true
            """,
            expected, to, lap_finished,
        ))


async def candidates(
    pool, registerable_types: Sequence[str], *, after: Optional[UUID] = None, limit: Optional[int] = None,
) -> List[Any]:
    """Every live workflow whose saved graph holds a trigger of ``registerable_types``,
    or that holds an active registered ``webhooks`` row or any ``webhook_subscriptions``
    row (an orphan whose step left the graph), past ``after`` in id order. Ids never
    change, so a lap isn't reordered by the writes it makes. ``has_graph`` says the
    blob holds a list of steps at all."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            WITH candidates AS (
                SELECT wf.id, wf.updated_at, jsonb_typeof(wf.workflow->'nodes') = 'array' AS has_graph
                FROM workflows wf
                WHERE wf.deleted_at IS NULL
                  AND jsonb_typeof(wf.workflow->'nodes') = 'array'
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(wf.workflow->'nodes') AS n
                      WHERE n->>'type' = ANY($1::text[])
                  )
                UNION
                SELECT wf.id, wf.updated_at, jsonb_typeof(wf.workflow->'nodes') = 'array' AS has_graph
                FROM webhooks w
                JOIN workflows wf ON wf.id = w.workflow_id
                WHERE w.is_active AND w.registered_operation IS NOT NULL
                  AND wf.deleted_at IS NULL
                UNION
                SELECT wf.id, wf.updated_at, jsonb_typeof(wf.workflow->'nodes') = 'array' AS has_graph
                FROM webhook_subscriptions s
                JOIN workflows wf ON wf.id = s.workflow_id
                WHERE wf.deleted_at IS NULL
            )
            SELECT c.id, c.updated_at, COALESCE(c.has_graph, false) AS has_graph
            FROM candidates c
            WHERE ($2::uuid IS NULL OR c.id > $2)
            ORDER BY c.id
            LIMIT $3
            """,
            list(registerable_types), after, limit,
        )


async def registered_nodes(pool, workflow_id: UUID) -> Set[str]:
    """The steps a workflow's rows say are registered, whatever its graph says now."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT node_id FROM webhooks
            WHERE workflow_id = $1 AND is_active AND registered_operation IS NOT NULL
            UNION
            SELECT node_id FROM webhook_subscriptions WHERE workflow_id = $1
            """,
            workflow_id,
        )
    return {r["node_id"] for r in rows}
