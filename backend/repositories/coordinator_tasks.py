"""Durable agent requests owned by the account coordinator.
Claims serialize each agent conversation; terminal outcomes and their chat
notifications survive the process that dispatched the request.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from repositories.conversation import ConversationRepo
from repositories.workflow import WorkflowRepo


class CoordinatorTaskRepo:
    def __init__(self, pool):
        self.pool = pool

    async def enqueue(self, *, user_id: str, workflow_id: str, node_id: str, agent_name: str,
                      message: str, channel: str, parent_task_id: Optional[str] = None, continuation=None) -> Dict[str, Any]:
        task_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Bound fan-out across containers, including simultaneous model tool calls.
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"coordinator-tasks:{user_id}")
                parent = None
                if parent_task_id:
                    parent = await conn.fetchrow(
                        "SELECT * FROM coordinator_agent_tasks WHERE id = $1::uuid AND user_id = $2::uuid",
                        parent_task_id, user_id,
                    )
                    if not parent or str(parent["workflow_id"]) != workflow_id or parent["node_id"] != node_id:
                        raise ValueError("The prior task does not belong to this agent and account.")
                count = await conn.fetchval(
                    "SELECT count(*) FROM coordinator_agent_tasks WHERE user_id = $1::uuid "
                    "AND status IN ('queued', 'running', 'waiting')", user_id,
                )
                if count >= 10:
                    raise ValueError("Ten agent requests are already pending. Check their status before starting more.")
                key = parent["conversation_key"] if parent else f"coordinator-{user_id}-{task_id}"
                row = await conn.fetchrow(
                    """INSERT INTO coordinator_agent_tasks
                       (id, user_id, workflow_id, node_id, agent_name, conversation_key, parent_task_id, message, channel, continuation)
                       VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6, $7::uuid, $8, $9, $10) RETURNING *""",
                    task_id, user_id, workflow_id, node_id, agent_name, key, parent_task_id, message, channel, continuation,
                )
        return dict(row)

    async def list_for_user(self, user_id: str, task_id: Optional[str] = None, *, limit: int = 20):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM coordinator_agent_tasks
                   WHERE user_id = $1::uuid AND ($2::uuid IS NULL OR id = $2::uuid)
                   ORDER BY (status IN ('queued', 'running', 'waiting')) DESC, created_at DESC LIMIT $3""",
                user_id, task_id, limit,
            )
        return [dict(row) for row in rows]

    async def claim(self) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """SELECT t.* FROM coordinator_agent_tasks t WHERE t.status = 'queued'
                       AND NOT EXISTS (
                           SELECT 1 FROM coordinator_agent_tasks earlier
                           WHERE earlier.conversation_key = t.conversation_key
                           AND earlier.status IN ('queued', 'running', 'waiting')
                           AND (earlier.created_at, earlier.id) < (t.created_at, t.id)
                       ) ORDER BY t.created_at, t.id FOR UPDATE OF t SKIP LOCKED LIMIT 1""",
                )
                if not row:
                    return None
                execution_id = await WorkflowRepo(self.pool).create_execution(
                    conn, workflow_id=row["workflow_id"], user_id=row["user_id"], trigger_source="coordinator",
                )
                claimed = await conn.fetchrow(
                    """UPDATE coordinator_agent_tasks SET status = 'running', execution_id = $2::uuid,
                       lease_until = now() + interval '2 minutes', updated_at = now() WHERE id = $1 RETURNING *""",
                    row["id"], execution_id,
                )
        return dict(claimed)

    async def heartbeat(self, task_id: str) -> None:
        await self.pool.execute(
            "UPDATE coordinator_agent_tasks SET lease_until = now() + interval '2 minutes' "
            "WHERE id = $1::uuid AND status = 'running'", task_id,
        )

    async def wait_for_reply(self, task_id: str) -> None:
        await self.pool.execute(
            """UPDATE coordinator_agent_tasks SET status = 'waiting', updated_at = now(),
               lease_until = now() + interval '4 hours' WHERE id = $1::uuid AND status = 'running'""", task_id,
        )

    async def finish(self, task_id: str, *, result: Optional[dict] = None, error: Optional[str] = None) -> bool:
        status = "failed" if error else "completed"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE coordinator_agent_tasks SET status = $2, result = $3::jsonb, error = $4,
                       updated_at = now(), lease_until = NULL
                       WHERE id = $1::uuid AND status IN ('running', 'waiting') RETURNING execution_id""",
                    task_id, status, result, error,
                )
                if row and error:
                    # Access may have been revoked before handle_execute started;
                    # don't leave its pre-created execution running forever.
                    await conn.execute(
                        """UPDATE workflow_executions SET status = 'error', error = $2, finished_at = now()
                           WHERE id = $1 AND status IN ('running', 'delivered')""", row["execution_id"], error,
                    )
        return row is not None

    async def find_deliveries(self, *, workflow_id: str, node_id: str, conversation_key: str, execution_ids: list[str]):
        rows = await self.pool.fetch(
            """SELECT id FROM coordinator_agent_tasks WHERE workflow_id = $1::uuid AND node_id = $2
               AND conversation_key = $3 AND execution_id = ANY($4::uuid[])
               AND status IN ('running', 'waiting')""",
            workflow_id, node_id, conversation_key, [uuid.UUID(i) for i in execution_ids],
        )
        return [str(row["id"]) for row in rows]

    async def reap_stalled(self) -> None:
        await self.pool.execute(
            """WITH expired AS (UPDATE coordinator_agent_tasks t SET status = 'failed', updated_at = now(),
               error = COALESCE((SELECT NULLIF(e.error, '') FROM workflow_executions e
                                 WHERE e.id = t.execution_id AND e.status = 'error'),
                   'The agent request was interrupted or its reply did not arrive. Check the agent before retrying.'),
               lease_until = NULL
               WHERE t.status IN ('running', 'waiting') AND (t.lease_until < now() OR
                   EXISTS (SELECT 1 FROM workflow_executions e WHERE e.id = t.execution_id AND e.status = 'error'))
               RETURNING t.execution_id, t.error)
               UPDATE workflow_executions e SET status = 'error', finished_at = now(), error = expired.error
               FROM expired WHERE e.id = expired.execution_id AND e.status IN ('running', 'delivered')""",
        )

    async def pending_notifications(self):
        return [dict(r) for r in await self.pool.fetch(
            """SELECT * FROM coordinator_agent_tasks WHERE status IN ('completed', 'failed')
               AND notified_at IS NULL AND NOT EXISTS (SELECT 1 FROM coordinator_wakeups w
                 WHERE w.source='agent' AND w.source_id=coordinator_agent_tasks.id)
               ORDER BY updated_at LIMIT 20""",
        )]

    async def persist_notification(self, task_id: str, event: dict) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE coordinator_agent_tasks SET notified_at = now()
                       WHERE id = $1::uuid AND notified_at IS NULL AND status IN ('completed', 'failed')
                       RETURNING user_id""", task_id,
                )
                if not row:
                    return False
                await conn.execute(
                    ConversationRepo._UPSERT_CHAT_EVENT_SQL,
                    f"coordinator:{row['user_id']}", row["user_id"], None, "__coordinator__",
                    [event], "Coordinator", None,
                )
        return True

    async def record_delivery_error(self, task_id: str, error: str) -> None:
        await self.pool.execute(
            "UPDATE coordinator_agent_tasks SET delivery_error = $2 WHERE id = $1::uuid", task_id, error[:1000],
        )
