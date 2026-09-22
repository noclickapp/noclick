"""One durable lifecycle for building, editing, and publishing artifacts."""

import uuid

from repositories.conversation import ConversationRepo
from utils.access_control import Permission, check_resource_access
from utils.builder_request import BUILDER_REQUEST_PREFIX


class BuilderRequestRepo:
    def __init__(self, pool):
        self.pool = pool

    async def accessible_workflow(self, user_id, workflow_id, *, publishing=False):
        async with self.pool.acquire() as conn:
            access = await check_resource_access(conn, user_id, "workflow", workflow_id)
            allowed = (Permission.OWNER,) if publishing else (Permission.OWNER, Permission.EDIT)
            if not access.has_access or access.permission not in allowed:
                raise ValueError("Workflow not found or insufficient permission for this request.")
            row = await conn.fetchrow(
                "SELECT name, workflow FROM workflows WHERE id=$1::uuid AND deleted_at IS NULL", workflow_id,
            )
            if row is None:
                raise ValueError("Workflow not found or has been trashed.")
            return dict(row)

    async def enqueue(self, *, user_id, workflow_id, instructions=None, publish=None, origin=None,
                      reply_conversation_id=None, reply_node_id=None, send_to_phone=False):
        await self.accessible_workflow(user_id, workflow_id, publishing=publish is not None)
        request_id = uuid.uuid4()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"builder-requests:{user_id}")
                if await conn.fetchval(
                    "SELECT count(*) FROM builder_requests WHERE user_id=$1::uuid "
                    "AND status IN ('queued','running','waiting_for_input')", user_id,
                ) >= 10:
                    raise ValueError("Ten builder requests are already pending. Check build_status before starting more.")
                if await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM builder_requests WHERE workflow_id=$1::uuid "
                    "AND status IN ('queued','running','waiting_for_input'))", workflow_id,
                ):
                    raise ValueError("A builder request is already pending for this workflow. Check build_status.")
                row = await conn.fetchrow(
                    """INSERT INTO builder_requests
                       (id, user_id, workflow_id, conversation_id, instructions, publish, origin, phase,
                        reply_conversation_id, reply_node_id, send_to_phone)
                       VALUES ($1,$2::uuid,$3::uuid,$4,$5,$6::jsonb,$7::jsonb,$8,$9,$10,$11) RETURNING *""",
                    request_id, user_id, workflow_id, f"{BUILDER_REQUEST_PREFIX}{request_id}", instructions,
                    publish, origin or {}, "building" if instructions else "publishing",
                    reply_conversation_id, reply_node_id, send_to_phone,
                )
        return dict(row)

    async def list_for_user(self, user_id, *, request_id=None, conversation_id=None, source=None):
        rows = await self.pool.fetch(
            """SELECT * FROM builder_requests WHERE user_id=$1::uuid
               AND ($2::uuid IS NULL OR id=$2::uuid) AND ($3::text IS NULL OR conversation_id=$3)
               AND ($4::text IS NULL OR origin->>'source'=$4)
               ORDER BY (status IN ('queued','running','waiting_for_input')) DESC, created_at DESC LIMIT 20""",
            user_id, request_id, conversation_id, source,
        )
        return [dict(r) for r in rows]

    async def for_conversation(self, user_id, conversation_id):
        row = await self.pool.fetchrow(
            "SELECT * FROM builder_requests WHERE user_id=$1::uuid AND conversation_id=$2", user_id, conversation_id,
        )
        return dict(row) if row else None

    async def cancel(self, user_id, request_id):
        row = await self.pool.fetchrow(
            """UPDATE builder_requests SET status='cancelled', pending_ask=NULL, lease_until=NULL, updated_at=now()
               WHERE id=$1::uuid AND user_id=$2::uuid AND (status IN ('queued','waiting_for_input')
                 OR (status='running' AND phase='building')) RETURNING *""", request_id, user_id,
        )
        if row is None:
            raise ValueError("No cancellable builder request was found. Publishing cannot be cancelled once started.")
        return dict(row)

    async def claim(self):
        row = await self.pool.fetchrow(
            """WITH next AS (SELECT id FROM builder_requests WHERE status='queued'
                 ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
               UPDATE builder_requests r SET status='running', attempt_id=$1,
                 lease_until=now()+interval '2 minutes', updated_at=now()
               FROM next WHERE r.id=next.id RETURNING r.*""", uuid.uuid4(),
        )
        return dict(row) if row else None

    async def claim_resume(self, user_id, conversation_id, ask_id):
        row = await self.pool.fetchrow(
            """UPDATE builder_requests SET status='running', attempt_id=$4,
                 lease_until=now()+interval '2 minutes', updated_at=now()
               WHERE user_id=$1::uuid AND conversation_id=$2 AND status='waiting_for_input'
                 AND ($3::text IS NULL OR pending_ask->>'ask_id'=$3) RETURNING *""",
            user_id, conversation_id, ask_id, uuid.uuid4(),
        )
        if row is None:
            raise ValueError("This builder request is not waiting for that answer, or has already resumed.")
        return dict(row)

    async def heartbeat(self, request_id, attempt_id):
        await self.pool.execute(
            "UPDATE builder_requests SET lease_until=now()+interval '2 minutes' "
            "WHERE id=$1::uuid AND attempt_id=$2::uuid AND status='running'", request_id, attempt_id,
        )

    async def waiting(self, user_id, request_id, attempt_id, pending_ask):
        row = await self.pool.fetchrow(
            """UPDATE builder_requests SET status='waiting_for_input', pending_ask=$4::jsonb,
               updated_at=now(), lease_until=now()+interval '7 days'
               WHERE id=$1::uuid AND user_id=$2::uuid AND attempt_id=$3::uuid
                 AND status='running' AND phase='building' RETURNING id""", request_id, user_id, attempt_id, pending_ask,
        )
        return row is not None

    async def build_finished(self, user_id, request_id, attempt_id, *, success, summary, error=None):
        await self.pool.execute(
            """UPDATE builder_requests SET
               status=CASE WHEN NOT $4 THEN 'failed' WHEN publish IS NOT NULL THEN 'queued' ELSE 'completed' END,
               phase=CASE WHEN $4 AND publish IS NOT NULL THEN 'publishing' ELSE phase END,
               result=$5::jsonb, error=$6, pending_ask=NULL, lease_until=NULL, updated_at=now()
               WHERE id=$1::uuid AND user_id=$2::uuid AND attempt_id=$3::uuid
                 AND status='running' AND phase='building'""",
            request_id, user_id, attempt_id, success, {"summary": summary},
            None if success else (error or "The build did not complete."),
        )

    async def finish(self, request_id, attempt_id, *, result=None, error=None):
        failed = error is not None
        await self.pool.execute(
            """UPDATE builder_requests SET status=$3, result=COALESCE($4::jsonb, result), error=$5,
               lease_until=NULL, pending_ask=NULL, updated_at=now()
               WHERE id=$1::uuid AND attempt_id=$2::uuid AND status='running'""",
            request_id, attempt_id, "failed" if failed else "completed", result,
            (error or "The builder request failed without an error message.") if failed else None,
        )

    async def reap_stalled(self):
        await self.pool.execute(
            """UPDATE builder_requests SET status='failed', pending_ask=NULL, lease_until=NULL, updated_at=now(),
               error=CASE WHEN phase='publishing' THEN
                 'Publishing was interrupted. The app may already be live; check it before requesting publication again.'
                 ELSE 'The build was interrupted or waited seven days for input. Check it before starting another request.' END
               WHERE status IN ('running','waiting_for_input') AND lease_until < now()""",
        )

    async def claim_notification(self):
        row = await self.pool.fetchrow(
            """WITH next AS (SELECT id FROM builder_requests
                 WHERE status IN ('completed','failed','cancelled') AND notified_at IS NULL
                 AND reply_conversation_id IS NOT NULL
                 AND (notification_lease_until IS NULL OR notification_lease_until < now())
                 ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1)
               UPDATE builder_requests r SET notification_token=$1,
                 notification_lease_until=now()+interval '2 minutes',
                 delivery_error=CASE WHEN phone_state='sending' THEN
                   'Phone delivery was interrupted; receipt could not be confirmed. The result is saved here.' ELSE delivery_error END,
                 phone_state=CASE WHEN phone_state='sending' THEN 'uncertain'
                   WHEN phone_state IS NULL AND send_to_phone THEN 'sending' ELSE phone_state END
               FROM next WHERE r.id=next.id RETURNING r.*""", uuid.uuid4(),
        )
        return dict(row) if row else None

    async def complete_notification(self, task, event, *, phone_state, delivery_error):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE builder_requests SET notified_at=now(), notification_lease_until=NULL,
                       phone_state=$3, delivery_error=$4 WHERE id=$1 AND notification_token=$2 AND notified_at IS NULL
                       RETURNING user_id""", task["id"], task["notification_token"], phone_state, delivery_error,
                )
                if row is None:
                    return False
                await conn.execute(
                    ConversationRepo._UPSERT_CHAT_EVENT_SQL,
                    task["reply_conversation_id"], row["user_id"], None, task["reply_node_id"], [event], None, None,
                )
        return True
