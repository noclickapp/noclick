"""Durable build → publish requests and their result notifications."""

import uuid

from repositories.conversation import ConversationRepo


class CoordinatorPublicationRepo:
    def __init__(self, pool):
        self.pool = pool

    async def get_owned_graph(self, user_id, workflow_id):
        return await self.pool.fetchval(
            "SELECT workflow FROM workflows WHERE id=$1::uuid AND owner_id=$2::uuid AND deleted_at IS NULL",
            workflow_id, user_id,
        )

    async def enqueue(self, *, user_id, workflow_id, options, send_to_phone=False,
                      builder_conversation_id=None, instructions=None):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"publications:{user_id}")
                if await conn.fetchval(
                    "SELECT count(*) FROM coordinator_publications WHERE user_id=$1::uuid "
                    "AND status IN ('queued','building','waiting','ready','publishing')", user_id,
                ) >= 10:
                    raise ValueError("Ten publications are already pending. Check their status before starting more.")
                if await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM coordinator_publications WHERE workflow_id=$1::uuid "
                    "AND status IN ('queued','building','waiting','ready','publishing'))", workflow_id,
                ):
                    raise ValueError("A publication is already pending for this workflow. Check publication_status.")
                row = await conn.fetchrow(
                    """INSERT INTO coordinator_publications
                       (user_id, workflow_id, options, send_to_phone, builder_conversation_id, instructions, status)
                       SELECT $1::uuid, id, $3::jsonb, $4, $5, $6, $7 FROM workflows
                       WHERE id=$2::uuid AND owner_id=$1::uuid AND deleted_at IS NULL RETURNING *""",
                    user_id, workflow_id, options, send_to_phone, builder_conversation_id, instructions,
                    "queued" if instructions else "ready",
                )
                if row is None:
                    raise ValueError("Workflow not found or not owned by this account.")
        return dict(row)

    async def list_for_user(self, user_id, publication_id=None):
        rows = await self.pool.fetch(
            """SELECT * FROM coordinator_publications WHERE user_id=$1::uuid
               AND ($2::uuid IS NULL OR id=$2::uuid)
               ORDER BY (status NOT IN ('completed','failed','cancelled')) DESC, created_at DESC LIMIT 20""",
            user_id, publication_id,
        )
        return [dict(r) for r in rows]

    async def cancel(self, user_id, publication_id):
        row = await self.pool.fetchrow(
            """UPDATE coordinator_publications SET status='cancelled', lease_until=NULL, updated_at=now()
               WHERE id=$1::uuid AND user_id=$2::uuid AND status IN ('queued','building','waiting','ready') RETURNING *""",
            publication_id, user_id,
        )
        if row is None:
            raise ValueError("No cancellable publication was found. A publication that has started cannot be cancelled here.")
        return dict(row)

    async def claim(self):
        row = await self.pool.fetchrow(
            """WITH next AS (SELECT id FROM coordinator_publications WHERE status IN ('queued','ready')
                 ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
               UPDATE coordinator_publications p SET status=CASE WHEN status='queued' THEN 'building' ELSE 'publishing' END,
                 lease_until=now()+interval '2 minutes', updated_at=now()
               FROM next WHERE p.id=next.id RETURNING p.*""",
        )
        return dict(row) if row else None

    async def heartbeat(self, publication_id):
        await self.pool.execute(
            "UPDATE coordinator_publications SET lease_until=now()+interval '2 minutes' "
            "WHERE id=$1::uuid AND status IN ('building','publishing')", publication_id,
        )

    async def waiting(self, user_id, builder_conversation_id):
        await self.pool.execute(
            """UPDATE coordinator_publications SET status='waiting', updated_at=now(),
               lease_until=now()+interval '7 days' WHERE user_id=$1::uuid AND builder_conversation_id=$2
               AND status IN ('building','waiting')""", user_id, builder_conversation_id,
        )

    async def build_finished(self, user_id, builder_conversation_id, *, success, error=None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE coordinator_publications SET status=$3, error=$4, lease_until=NULL, updated_at=now()
                   WHERE user_id=$1::uuid AND builder_conversation_id=$2 AND status IN ('building','waiting')""",
                user_id, builder_conversation_id, "ready" if success else "failed",
                None if success else (error or "The build did not complete."),
            )
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM coordinator_publications WHERE user_id=$1::uuid AND builder_conversation_id=$2)",
                user_id, builder_conversation_id,
            )

    async def finish(self, publication_id, *, result=None, error=None, expected_status="publishing"):
        failed = error is not None
        await self.pool.execute(
            """UPDATE coordinator_publications SET status=$2, result=$3::jsonb, error=$4, lease_until=NULL, updated_at=now()
               WHERE id=$1::uuid AND status=$5""",
            publication_id, "failed" if failed else "completed", result,
            (error or "Publication failed without an error message.") if failed else None, expected_status,
        )

    async def reap_stalled(self):
        await self.pool.execute(
            """UPDATE coordinator_publications SET status='failed', lease_until=NULL, updated_at=now(),
               error=CASE WHEN status='publishing' THEN
                 'Publishing was interrupted. The app may already be live; check it before requesting publication again.'
                 ELSE 'The build was interrupted or waited seven days for input. Check the build before requesting publication again.' END
               WHERE status IN ('building','waiting','publishing') AND lease_until < now()""",
        )

    async def claim_notification(self):
        row = await self.pool.fetchrow(
            """WITH next AS (SELECT id FROM coordinator_publications
                 WHERE status IN ('completed','failed','cancelled') AND notified_at IS NULL
                 AND (notification_lease_until IS NULL OR notification_lease_until < now())
                 ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1)
               UPDATE coordinator_publications p SET notification_token=$1,
                 notification_lease_until=now()+interval '2 minutes',
                 delivery_error=CASE WHEN phone_state='sending' THEN
                   'Phone delivery was interrupted; receipt could not be confirmed. The result is saved here.' ELSE delivery_error END,
                 phone_state=CASE WHEN phone_state='sending' THEN 'uncertain'
                   WHEN phone_state IS NULL AND send_to_phone THEN 'sending' ELSE phone_state END
               FROM next WHERE p.id=next.id RETURNING p.*""", uuid.uuid4(),
        )
        return dict(row) if row else None

    async def complete_notification(self, task, event, *, phone_state, delivery_error):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE coordinator_publications SET notified_at=now(), notification_lease_until=NULL,
                       phone_state=$3, delivery_error=$4 WHERE id=$1 AND notification_token=$2 AND notified_at IS NULL
                       RETURNING user_id""", task["id"], task["notification_token"], phone_state, delivery_error,
                )
                if row is None:
                    return False
                await conn.execute(
                    ConversationRepo._UPSERT_CHAT_EVENT_SQL,
                    f"coordinator:{row['user_id']}", row["user_id"], None, "__coordinator__", [event], "Coordinator", None,
                )
        return True
