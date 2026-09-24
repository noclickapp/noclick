"""Build jobs: one durable lifecycle for building, editing, and publishing
artifacts, kept in ``coordinator_jobs`` under ``kind='build'``."""

import uuid

from repositories.conversation import ConversationRepo
from repositories.coordinator_jobs import ACTIVE, CoordinatorJobRepo
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

    async def enqueue(self, *, user_id, workflow_id, instructions=None, publish=None, origin=None, continuation=None,
                      reply_conversation_id=None, reply_node_id=None, send_to_phone=False):
        await self.accessible_workflow(user_id, workflow_id, publishing=publish is not None)
        job_id = uuid.uuid4()
        spec = {k: v for k, v in (("instructions", instructions), ("publish", publish)) if v is not None}
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"builder-requests:{user_id}")
                if await conn.fetchval(
                    f"SELECT count(*) FROM coordinator_jobs WHERE kind='build' AND user_id=$1::uuid AND status IN {ACTIVE}",
                    user_id,
                ) >= 10:
                    raise ValueError("Ten builds are already pending. Check job_status before starting more.")
                if await conn.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM coordinator_jobs WHERE kind='build' AND workflow_id=$1::uuid "
                    f"AND status IN {ACTIVE})", workflow_id,
                ):
                    raise ValueError("A build is already pending for this workflow. Check job_status.")
                row = await conn.fetchrow(
                    """INSERT INTO coordinator_jobs
                       (id, user_id, kind, workflow_id, conversation_key, spec, origin, continuation, phase,
                        reply_conversation_id, reply_node_id, send_to_phone)
                       VALUES ($1,$2::uuid,'build',$3::uuid,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8,$9,$10,$11) RETURNING *""",
                    job_id, user_id, workflow_id, f"{BUILDER_REQUEST_PREFIX}{job_id}", spec, origin or {}, continuation,
                    "building" if instructions else "publishing", reply_conversation_id, reply_node_id, send_to_phone,
                )
        return dict(row)

    async def list_for_user(self, user_id, *, job_id=None):
        return await CoordinatorJobRepo(self.pool).list_for_user(user_id, job_id=job_id, kind="build")

    async def for_conversation(self, user_id, conversation_id):
        row = await self.pool.fetchrow(
            "SELECT * FROM coordinator_jobs WHERE kind='build' AND user_id=$1::uuid AND conversation_key=$2",
            user_id, conversation_id,
        )
        return dict(row) if row else None

    async def cancel(self, user_id, job_id):
        row = await self.pool.fetchrow(
            """UPDATE coordinator_jobs SET status='cancelled', pending_ask=NULL, lease_until=NULL, updated_at=now()
               WHERE kind='build' AND id=$1::uuid AND user_id=$2::uuid AND (status IN ('queued','waiting')
                 OR (status='running' AND phase='building')) RETURNING *""", job_id, user_id,
        )
        if row is None:
            raise ValueError("No cancellable build was found. Publishing cannot be cancelled once started.")
        return dict(row)

    async def claim(self):
        row = await self.pool.fetchrow(
            """WITH next AS (SELECT id FROM coordinator_jobs WHERE kind='build' AND status='queued'
                 ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
               UPDATE coordinator_jobs r SET status='running', attempt_id=$1,
                 lease_until=now()+interval '2 minutes', updated_at=now()
               FROM next WHERE r.id=next.id RETURNING r.*""", uuid.uuid4(),
        )
        return dict(row) if row else None

    async def claim_resume(self, user_id, conversation_id, ask_id):
        row = await self.pool.fetchrow(
            """UPDATE coordinator_jobs SET status='running', attempt_id=$4,
                 lease_until=now()+interval '2 minutes', updated_at=now()
               WHERE kind='build' AND user_id=$1::uuid AND conversation_key=$2 AND status='waiting'
                 AND ($3::text IS NULL OR pending_ask->>'ask_id'=$3) RETURNING *""",
            user_id, conversation_id, ask_id, uuid.uuid4(),
        )
        if row is None:
            raise ValueError("This build is not waiting for that answer, or has already resumed.")
        return dict(row)

    async def heartbeat(self, job_id, attempt_id):
        await self.pool.execute(
            "UPDATE coordinator_jobs SET lease_until=now()+interval '2 minutes' "
            "WHERE id=$1::uuid AND attempt_id=$2::uuid AND status='running'", job_id, attempt_id,
        )

    async def waiting(self, user_id, job_id, attempt_id, pending_ask):
        row = await self.pool.fetchrow(
            """UPDATE coordinator_jobs SET status='waiting', pending_ask=$4::jsonb,
               updated_at=now(), lease_until=now()+interval '7 days'
               WHERE kind='build' AND id=$1::uuid AND user_id=$2::uuid AND attempt_id=$3::uuid
                 AND status='running' AND phase='building' RETURNING id""", job_id, user_id, attempt_id, pending_ask,
        )
        return row is not None

    async def build_finished(self, user_id, job_id, attempt_id, *, success, summary, error=None):
        await self.pool.execute(
            """UPDATE coordinator_jobs SET
               status=CASE WHEN NOT $4 THEN 'failed' WHEN spec ? 'publish' THEN 'queued' ELSE 'completed' END,
               phase=CASE WHEN $4 AND spec ? 'publish' THEN 'publishing' ELSE phase END,
               result=$5::jsonb, error=$6, pending_ask=NULL, lease_until=NULL, updated_at=now()
               WHERE kind='build' AND id=$1::uuid AND user_id=$2::uuid AND attempt_id=$3::uuid
                 AND status='running' AND phase='building'""",
            job_id, user_id, attempt_id, success, {"summary": summary},
            None if success else (error or "The build did not complete."),
        )

    async def finish(self, job_id, attempt_id, *, result=None, error=None):
        failed = error is not None
        await self.pool.execute(
            """UPDATE coordinator_jobs SET status=$3, result=COALESCE($4::jsonb, result), error=$5,
               lease_until=NULL, pending_ask=NULL, updated_at=now()
               WHERE kind='build' AND id=$1::uuid AND attempt_id=$2::uuid AND status='running'""",
            job_id, attempt_id, "failed" if failed else "completed", result,
            (error or "The build failed without an error message.") if failed else None,
        )

    async def reap_stalled(self):
        await self.pool.execute(
            """UPDATE coordinator_jobs SET status='failed', pending_ask=NULL, lease_until=NULL, updated_at=now(),
               error=CASE WHEN phase='publishing' THEN
                 'The publication operation was interrupted and may have taken effect. Check the app before retrying; an unfinished rename can be resumed with the same target or unpublished.'
                 ELSE 'The build was interrupted or waited seven days for input. Check it before starting another request.' END
               WHERE kind='build' AND status IN ('running','waiting') AND lease_until < now()""",
        )

    async def claim_notification(self):
        """A finished build with no continuation is posted to its reply conversation."""
        row = await self.pool.fetchrow(
            """WITH next AS (SELECT id FROM coordinator_jobs
                 WHERE kind='build' AND status IN ('completed','failed','cancelled') AND notified_at IS NULL
                 AND reply_conversation_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM coordinator_wakeups w
                   WHERE w.source='job' AND w.source_id=coordinator_jobs.id)
                 AND (notification_lease_until IS NULL OR notification_lease_until < now())
                 ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1)
               UPDATE coordinator_jobs r SET notification_token=$1,
                 notification_lease_until=now()+interval '2 minutes',
                 delivery_error=CASE WHEN phone_state='sending' THEN
                   'Phone delivery was interrupted; receipt could not be confirmed. The result is saved here.' ELSE delivery_error END,
                 phone_state=CASE WHEN phone_state='sending' THEN 'uncertain'
                   WHEN phone_state IS NULL AND send_to_phone AND continuation IS NULL THEN 'sending' ELSE phone_state END
               FROM next WHERE r.id=next.id RETURNING r.*""", uuid.uuid4(),
        )
        return dict(row) if row else None

    async def complete_notification(self, job, event, *, phone_state, delivery_error):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE coordinator_jobs SET notified_at=now(), notification_lease_until=NULL,
                       phone_state=$3, delivery_error=$4 WHERE id=$1 AND notification_token=$2 AND notified_at IS NULL
                       RETURNING user_id""", job["id"], job["notification_token"], phone_state, delivery_error,
                )
                if row is None:
                    return False
                await conn.execute(
                    ConversationRepo._UPSERT_CHAT_EVENT_SQL,
                    job["reply_conversation_id"], row["user_id"], None, job["reply_node_id"], [event], None, None,
                )
        return True
