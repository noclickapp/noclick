"""SQL for the nightly trigger resync (``WebhookManager.resync_trigger_registrations``):
the workflows it may visit, and its one row in ``trigger_resync_state``: whether it
may act, and where its lap of them stands.

No row means nobody has turned it on and no lap has started."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
    blob holds a list of steps at all.

    Each row says when the workflow was last in use, which ``updated_at`` can't
    (NoClick's own mirror writes move it): ``last_run_at``, ``person_edit_at``
    (a version a person authored) and ``owner_seen_at`` (the owner's last
    sign-in or text to NoClick)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
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
        # Keyed by id, apart: folded into the walk above, it ran past the pool's time limit.
        used = {
            r["id"]: r for r in await conn.fetch(
                """
                SELECT wf.id,
                       (SELECT e.started_at FROM workflow_executions e WHERE e.workflow_id = wf.id
                        ORDER BY e.started_at DESC LIMIT 1) AS last_run_at,
                       (SELECT max(v.updated_at) FROM workflow_versions v
                        WHERE v.workflow_id = wf.id AND v.author_user_id IS NOT NULL AND v.source <> 'baseline'
                       ) AS person_edit_at,
                       (SELECT GREATEST(u.last_sign_in_at,
                                        (SELECT max(p.last_seen_at) FROM user_phones p WHERE p.user_id = u.id))
                        FROM auth.users u WHERE u.id = wf.owner_id) AS owner_seen_at
                FROM workflows wf WHERE wf.id = ANY($1::uuid[])
                """,
                [r["id"] for r in rows],
            )
        }
    return [{**dict(r), **{k: used[r["id"]][k] if r["id"] in used else None
                           for k in ("last_run_at", "person_edit_at", "owner_seen_at")}} for r in rows]


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


def last_active(row) -> Optional[datetime]:
    """When a candidate was last in use: run, edited by a person, or its owner back."""
    seen = [row[key] for key in ("last_run_at", "person_edit_at", "owner_seen_at") if row[key] is not None]
    return max(seen) if seen else None


def is_active(row, now: datetime, within: timedelta) -> bool:
    last = last_active(row)
    return last is not None and now - last <= within
