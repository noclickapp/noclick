"""Short-transaction account leases and a global coordinator concurrency budget."""

import asyncio
import os
import random
import time
import uuid
from contextlib import asynccontextmanager


class CoordinatorBusy(RuntimeError):
    pass


class TurnLease:
    def __init__(self, pool, user_id):
        self.pool, self.user_id = pool, user_id
        self.conversation_id = f"coordinator:{user_id}"
        self.owner = uuid.uuid4()

    async def acquire(self):
        async with self.pool.acquire() as conn, conn.transaction():
            # Admission is briefly serialized; model calls never hold this lock.
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtextextended('coordinator-admission',0))"):
                return False
            active = await conn.fetchval(
                "SELECT count(*) FROM conversations WHERE coordinator_lease_owner IS NOT NULL "
                "AND coordinator_lease_until>now()")
            if active >= int(os.getenv("COORDINATOR_MAX_CONCURRENT_TURNS", "64")):
                return False
            return await conn.fetchval(
                """INSERT INTO conversations(conversation_id,user_id,node_id,coordinator_lease_owner,coordinator_lease_until)
                   VALUES($1,$2::uuid,'__coordinator__',$3,now()+interval '90 seconds')
                   ON CONFLICT(conversation_id) DO UPDATE SET coordinator_lease_owner=$3,
                     coordinator_lease_until=now()+interval '90 seconds'
                   WHERE conversations.user_id=$2::uuid AND
                     (conversations.coordinator_lease_until IS NULL OR conversations.coordinator_lease_until<=now())
                   RETURNING conversation_id""", self.conversation_id, self.user_id, self.owner,
            ) is not None

    async def check(self):
        owned = await self.pool.fetchval(
            "UPDATE conversations SET coordinator_lease_until=now()+interval '90 seconds' "
            "WHERE conversation_id=$1 AND coordinator_lease_owner=$2 AND coordinator_lease_until>now() RETURNING 1",
            self.conversation_id, self.owner,
        )
        if not owned:
            raise RuntimeError("Coordinator turn ownership expired")

    async def release(self):
        await self.pool.execute(
            "UPDATE conversations SET coordinator_lease_owner=NULL,coordinator_lease_until=NULL "
            "WHERE conversation_id=$1 AND coordinator_lease_owner=$2", self.conversation_id, self.owner,
        )


@asynccontextmanager
async def coordinator_lock(pool, user_id, *, wait_seconds=600):
    lease = TurnLease(pool, user_id)
    deadline = time.monotonic() + wait_seconds
    delay = 0.25
    while not await lease.acquire():
        if time.monotonic() >= deadline:
            raise CoordinatorBusy("Coordinator capacity is busy; retry this event later")
        await asyncio.sleep(delay + random.random() * 0.1)
        delay = min(2, delay * 2)
    runner = asyncio.current_task()

    async def renew():
        try:
            while True:
                await asyncio.sleep(20)
                await lease.check()
        except Exception:
            runner.cancel()

    heartbeat = asyncio.create_task(renew())
    try:
        yield lease
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        await lease.release()
