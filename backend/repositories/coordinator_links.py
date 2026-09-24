"""Await human links in the coordinator's existing durable inbox.

Register while holding the resource row lock, before returning its link. Resource
completion queues the same row transactionally; dispatch is only a latency hint.
"""
import uuid


class CoordinatorLinkRepo:
    def __init__(self, pool):
        self.pool = pool

    @staticmethod
    async def wait(conn, *, user_id, kind, resource_id, context, expires_at):
        if context is None:
            return
        # Only trusted coordinator tools supply this context, never browser input.
        if not all(key in context for key in ("epoch", "depth", "request", "channel")):
            raise ValueError("A link continuation needs the originating coordinator context.")
        if kind not in ("credential_request", "credential_policy"):
            raise ValueError("Unsupported coordinator link lifecycle.")
        key = f"{kind}:{resource_id}"
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"coordinator-links:{user_id}")
        count = await conn.fetchval(
            "SELECT count(*) FROM coordinator_wakeups WHERE user_id=$1::uuid AND status='waiting' "
            "AND await_expires_at>now() AND await_key<>$2", user_id, key,
        )
        if count >= 100:
            raise ValueError("Too many outstanding coordinator links. Complete an existing request first.")
        await conn.execute(
            "INSERT INTO coordinator_wakeups(user_id,source,source_id,context,payload,send_to_phone,"
            "status,await_key,await_expires_at) VALUES($1::uuid,'link',$2,$3,$4,$5,'waiting',$6,$7) "
            "ON CONFLICT(user_id,await_key) WHERE status='waiting' DO UPDATE SET "
            "context=EXCLUDED.context,send_to_phone=EXCLUDED.send_to_phone,await_expires_at=EXCLUDED.await_expires_at",
            user_id, uuid.uuid4(), context, {"kind": kind, "resource_id": str(resource_id), "status": "pending"},
            context["channel"] != "web", key, expires_at,
        )

    @staticmethod
    async def complete(conn, *, kind, resource_id, outcome):
        await conn.execute("SELECT complete_coordinator_link($1,$2::jsonb)", f"{kind}:{resource_id}", outcome)

    async def dispatch(self, kind, resource_id):
        from utils.coordinator_dispatch import dispatch_event
        rows = await self.pool.fetch(
            "SELECT * FROM coordinator_wakeups WHERE source='link' AND status='queued' AND await_key=$1",
            f"{kind}:{resource_id}",
        )
        for row in rows:
            await dispatch_event(self.pool, dict(row))

    async def pending(self, kind, resource_id, user_id):
        return await self.pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM coordinator_wakeups WHERE user_id=$1::uuid "
            "AND await_key=$2 AND status='waiting' AND await_expires_at>now())", user_id, f"{kind}:{resource_id}",
        )

    async def expire(self):
        # Expiry is a result, never permission to retry a paid or external action.
        await self.pool.execute(
            "WITH due AS (SELECT id FROM coordinator_wakeups WHERE status='waiting' "
            "AND await_expires_at<=now() ORDER BY await_expires_at LIMIT 100 FOR UPDATE SKIP LOCKED) "
            "UPDATE coordinator_wakeups w SET status='queued',payload=payload || '{\"status\":\"expired\"}'::jsonb,"
            "dispatch_after=now(),not_before=now() FROM due WHERE w.id=due.id",
        )
