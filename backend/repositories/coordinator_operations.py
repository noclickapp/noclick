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

    @staticmethod
    async def enqueue_related(conn, *, parent_id, user_id, key, outcome):
        """Join an unclaimed result, or enqueue an artifact AFTER its parent.

        The parent row lock serializes this with completion/claim. Once claimed,
        its input is immutable; the artifact gets a dependent inbox event instead.
        A merged artifact is also a receipt, so replay cannot create a late event.
        """
        parent = await conn.fetchrow(
            "SELECT * FROM coordinator_wakeups WHERE id=$1::uuid AND user_id=$2::uuid "
            "AND source='operation' FOR UPDATE", parent_id, user_id)
        if not parent or parent["status"] == "skipped" or key in parent["payload"].get("artifacts", {}):
            return None
        event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"operation-artifact:{parent_id}:{key}")
        if parent["status"] in ("waiting", "queued") and parent["started_at"] is None:
            # An earlier claim may have been deferred after creating the child.
            # Never merge its replay into the parent as well as delivering it late.
            if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM coordinator_wakeups WHERE id=$1)", event_id):
                return None
            row = await conn.fetchrow(
                "UPDATE coordinator_wakeups SET payload=jsonb_set(payload,'{artifacts}',"
                "COALESCE(payload->'artifacts','{}'::jsonb) || $2::jsonb) WHERE id=$1 RETURNING *",
                parent["id"], {key: outcome})
            return dict(row) if row["status"] == "queued" else None
        row = await conn.fetchrow(
            "INSERT INTO coordinator_wakeups(id,user_id,source,source_id,context,payload,send_to_phone,status) "
            "SELECT $1,user_id,'operation',$1,context,$4,send_to_phone,'queued' FROM coordinator_wakeups "
            "WHERE id=$2::uuid AND user_id=$3::uuid AND source='operation' AND status<>'skipped' "
            "ON CONFLICT(id) DO NOTHING RETURNING *", event_id, parent_id, user_id,
            {**outcome, "parent_operation_id": str(parent_id)})
        return dict(row) if row else None
