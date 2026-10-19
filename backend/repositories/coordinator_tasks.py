"""Agent jobs: durable messages to agents, kept in ``coordinator_jobs`` under
``kind='agent'``: the account coordinator's, and the turns another surface asks
of an agent on its own conversation (``enqueue_turn``). Claims serialize each
agent conversation; terminal outcomes and their deliveries survive the process
that dispatched the request.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from repositories.conversation import ConversationRepo
from repositories.coordinator_jobs import ACTIVE, CoordinatorJobRepo, outside_sources, started_by_coordinator
from repositories.workflow import WorkflowRepo

COORDINATOR_SOURCE = "coordinator"
# The coordinator's own threads with an agent.
COORDINATOR_KEY_PREFIX = "coordinator-"
_INSERT = """INSERT INTO coordinator_jobs
    (id, user_id, kind, workflow_id, node_id, conversation_key, parent_job_id, spec, origin, continuation, send_to_phone)
    VALUES ($1, $2::uuid, 'agent', $3::uuid, $4, $5, $6::uuid, $7::jsonb, $8::jsonb, $9::jsonb, $10) RETURNING *"""


class CoordinatorTaskRepo:
    def __init__(self, pool):
        self.pool = pool

    async def enqueue(self, *, user_id: str, workflow_id: str, node_id: str, agent_name: str,
                      message: str, send_to_phone: bool, parent_job_id: Optional[str] = None,
                      continuation=None) -> Dict[str, Any]:
        job_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Bound fan-out across containers, including simultaneous model tool calls.
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"coordinator-tasks:{user_id}")
                parent = None
                if parent_job_id:
                    parent = await conn.fetchrow(
                        "SELECT * FROM coordinator_jobs WHERE kind='agent' AND id = $1::uuid AND user_id = $2::uuid "
                        f"AND {started_by_coordinator(3)}", parent_job_id, user_id, outside_sources(),
                    )
                    if not parent or str(parent["workflow_id"]) != workflow_id or parent["node_id"] != node_id:
                        raise ValueError("The prior job does not belong to this agent and account.")
                count = await conn.fetchval(
                    f"SELECT count(*) FROM coordinator_jobs WHERE kind='agent' AND user_id = $1::uuid AND status IN {ACTIVE} "
                    f"AND {started_by_coordinator(2)}", user_id, outside_sources(),
                )
                if count >= 10:
                    raise ValueError("Ten agent requests are already pending. Check job_status before starting more.")
                key = parent["conversation_key"] if parent else f"{COORDINATOR_KEY_PREFIX}{user_id}-{job_id}"
                row = await conn.fetchrow(
                    _INSERT, job_id, user_id, workflow_id, node_id, key, parent_job_id,
                    {"agent_name": agent_name, "message": message}, {"source": COORDINATOR_SOURCE}, continuation,
                    send_to_phone,
                )
        return dict(row)

    @staticmethod
    async def enqueue_turn(conn, *, source: str, user_id: str, workflow_id: str, node_id: str, conversation_key: str,
                           agent_name: str, message: str, context: Dict[str, Any],
                           attachments: Optional[list] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """A turn another surface asks of an agent, inside that surface's own
        transaction: it runs on ``conversation_key`` (the surface's thread with
        the agent), with ``attachments`` (the agent node's
        ``message_attachments``) and ``config`` baked into the node's config,
        and its outcome goes back to ``source`` with ``context``
        (``coder.coordinator.tasks.register_agent_job_source``)."""
        spec = {"agent_name": agent_name, "message": message,
                **({"attachments": attachments} if attachments else {}), **({"config": config} if config else {})}
        return dict(await conn.fetchrow(_INSERT, uuid.uuid4(), user_id, workflow_id, node_id, conversation_key, None,
                                        spec, {**context, "source": source}, None, False))

    async def list_for_user(self, user_id: str, job_id: Optional[str] = None, *, limit: int = 20):
        return await CoordinatorJobRepo(self.pool).list_for_user(user_id, job_id=job_id, kind="agent", limit=limit)

    async def claim(self, job_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The next queued job (``job_id``: that one) whose agent conversation is free."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""SELECT t.* FROM coordinator_jobs t WHERE t.kind = 'agent' AND t.status = 'queued'
                       AND ($1::uuid IS NULL OR t.id = $1::uuid)
                       AND NOT EXISTS (
                           SELECT 1 FROM coordinator_jobs earlier
                           WHERE earlier.kind = 'agent' AND earlier.conversation_key = t.conversation_key
                           AND earlier.workflow_id = t.workflow_id AND earlier.node_id = t.node_id
                           AND earlier.status IN {ACTIVE}
                           AND (earlier.created_at, earlier.id) < (t.created_at, t.id)
                       ) ORDER BY t.created_at, t.id FOR UPDATE OF t SKIP LOCKED LIMIT 1""",
                    job_id,
                )
                if not row:
                    return None
                execution_id = await WorkflowRepo(self.pool).create_execution(
                    conn, workflow_id=row["workflow_id"], user_id=row["user_id"], trigger_source="coordinator",
                )
                claimed = await conn.fetchrow(
                    """UPDATE coordinator_jobs SET status = 'running', execution_id = $2::uuid,
                       lease_until = now() + interval '2 minutes', updated_at = now() WHERE id = $1 RETURNING *""",
                    row["id"], execution_id,
                )
        return dict(claimed)

    async def heartbeat(self, job_id: str) -> None:
        await self.pool.execute(
            "UPDATE coordinator_jobs SET lease_until = now() + interval '2 minutes' "
            "WHERE id = $1::uuid AND status = 'running'", job_id,
        )

    async def wait_for_reply(self, job_id: str) -> None:
        await self.pool.execute(
            """UPDATE coordinator_jobs SET status = 'waiting', updated_at = now(),
               lease_until = now() + interval '4 hours' WHERE id = $1::uuid AND status = 'running'""", job_id,
        )

    async def finish(self, job_id: str, *, result: Optional[dict] = None,
                     error: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The job as it finished, or None when it already had."""
        status = "failed" if error else "completed"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE coordinator_jobs SET status = $2, result = $3::jsonb, error = $4,
                       updated_at = now(), lease_until = NULL
                       WHERE kind = 'agent' AND id = $1::uuid AND status IN ('running', 'waiting') RETURNING *""",
                    job_id, status, result, error,
                )
                if row and error:
                    # Access may have been revoked before handle_execute started;
                    # don't leave its pre-created execution running forever.
                    await conn.execute(
                        """UPDATE workflow_executions SET status = 'error', error = $2, finished_at = now()
                           WHERE id = $1 AND status IN ('running', 'delivered')""", row["execution_id"], error,
                    )
        return dict(row) if row else None

    async def drop_queued(self, job_ids: list, error: str) -> None:
        """Fail the ``job_ids`` still queued, which no one will read now; one
        already running runs on. Nothing is delivered for them."""
        await self.pool.execute(
            """UPDATE coordinator_jobs SET status = 'failed', error = $2, notified_at = now(), updated_at = now()
               WHERE kind = 'agent' AND id = ANY($1::uuid[]) AND status = 'queued'""",
            [uuid.UUID(str(i)) for i in job_ids], error,
        )

    async def mark_notified(self, job_id: str) -> None:
        await self.pool.execute(
            "UPDATE coordinator_jobs SET notified_at = now() WHERE id = $1::uuid AND notified_at IS NULL", job_id,
        )

    async def find_deliveries(self, *, workflow_id: str, node_id: str, conversation_key: str, execution_ids: list[str]):
        rows = await self.pool.fetch(
            """SELECT id FROM coordinator_jobs WHERE kind = 'agent' AND workflow_id = $1::uuid AND node_id = $2
               AND conversation_key = $3 AND execution_id = ANY($4::uuid[])
               AND status IN ('running', 'waiting')""",
            workflow_id, node_id, conversation_key, [uuid.UUID(i) for i in execution_ids],
        )
        return [str(row["id"]) for row in rows]

    async def reap_stalled(self) -> None:
        await self.pool.execute(
            """WITH expired AS (UPDATE coordinator_jobs t SET status = 'failed', updated_at = now(),
               error = COALESCE((SELECT NULLIF(e.error, '') FROM workflow_executions e
                                 WHERE e.id = t.execution_id AND e.status = 'error'),
                   'The agent request was interrupted or its reply did not arrive. Check the agent before retrying.'),
               lease_until = NULL
               WHERE t.kind = 'agent' AND t.status IN ('running', 'waiting') AND (t.lease_until < now() OR
                   EXISTS (SELECT 1 FROM workflow_executions e WHERE e.id = t.execution_id AND e.status = 'error'))
               RETURNING t.execution_id, t.error)
               UPDATE workflow_executions e SET status = 'error', finished_at = now(), error = expired.error
               FROM expired WHERE e.id = expired.execution_id AND e.status IN ('running', 'delivered')""",
        )

    async def pending_notifications(self):
        return [dict(r) for r in await self.pool.fetch(
            """SELECT * FROM coordinator_jobs WHERE kind = 'agent' AND status IN ('completed', 'failed')
               AND notified_at IS NULL AND NOT EXISTS (SELECT 1 FROM coordinator_wakeups w
                 WHERE w.source='job' AND w.source_id=coordinator_jobs.id)
               ORDER BY updated_at LIMIT 20""",
        )]

    async def persist_notification(self, job_id: str, event: dict) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE coordinator_jobs SET notified_at = now()
                       WHERE id = $1::uuid AND notified_at IS NULL AND status IN ('completed', 'failed')
                       RETURNING user_id""", job_id,
                )
                if not row:
                    return False
                await ConversationRepo.write_chat_event(
                    conn, f"coordinator:{row['user_id']}", row["user_id"], None, "__coordinator__",
                    [event], "Coordinator", None,
                )
        return True

    async def record_delivery_error(self, job_id: str, error: str) -> None:
        await self.pool.execute(
            "UPDATE coordinator_jobs SET delivery_error = $2 WHERE id = $1::uuid", job_id, error[:1000],
        )
