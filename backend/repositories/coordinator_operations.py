"""Await long-running tools in the coordinator's existing completion inbox.

Register BEFORE external I/O. A lost/ambiguous callback expires through the
existing recovery worker, waking the owner without automatically retrying I/O.
Only trusted runtime code supplies context; tool arguments cannot manufacture it.
"""
import uuid


class CoordinatorOperationRepo:
    def __init__(self, pool):
        self.pool = pool

    async def start(self, *, user_id, context, operation, payload):
        if not context or not all(k in context for k in ("epoch", "depth", "request", "channel")):
            raise ValueError("This long-running operation needs a coordinator completion context.")
        operation_id = uuid.uuid4()
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"coordinator-operations:{user_id}")
            count = await conn.fetchval(
                "SELECT count(*) FROM coordinator_wakeups WHERE user_id=$1::uuid AND source='operation' "
                "AND status='waiting' AND await_expires_at>now()", user_id)
            if count >= 10:
                raise ValueError("Too many operations are still running. Wait for one to finish.")
            await conn.execute(
                "INSERT INTO coordinator_wakeups(id,user_id,source,source_id,context,payload,send_to_phone,"
                "status,await_key,await_expires_at) VALUES($1,$2::uuid,'operation',$1,$3,$4,$5,'waiting',$6,now()+interval '2 hours')",
                operation_id, user_id, context, {**payload, "operation": operation, "status": "pending"},
                context["channel"] != "web", f"operation:{operation_id}")
        return str(operation_id)

    async def get(self, operation_id, user_id):
        row = await self.pool.fetchrow(
            "SELECT * FROM coordinator_wakeups WHERE id=$1::uuid AND user_id=$2::uuid AND source='operation'",
            operation_id, user_id)
        return dict(row) if row else None

    async def complete(self, operation_id, user_id, outcome):
        # Callback retries cannot overwrite an outcome or re-wake a consumed
        # turn. Reset's skipped rows also remain fenced.
        await self.pool.execute(
            "UPDATE coordinator_wakeups SET status='queued',payload=payload || $3::jsonb,"
            "not_before=now(),dispatch_after=now() WHERE id=$1::uuid AND user_id=$2::uuid "
            "AND source='operation' AND status='waiting'", operation_id, user_id, outcome)
        row = await self.get(operation_id, user_id)
        if row and row["status"] == "queued":
            from utils.coordinator_dispatch import dispatch_event
            await dispatch_event(self.pool, row)
