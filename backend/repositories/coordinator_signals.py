"""Admission of agent messages into the existing coordinator signal inbox."""

import uuid

from repositories.coordinator_wakeups import CoordinatorWakeupRepo


class CoordinatorSignalRepo:
    def __init__(self, pool):
        self.pool = pool

    async def agent_message(self, *, user_id, workflow_id, node_id, payload, node_cap, account_cap):
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"agent-msg:{user_id}")
            workflow = await conn.fetchrow(
                "SELECT name FROM workflows WHERE id=$1::uuid AND owner_id=$2::uuid AND deleted_at IS NULL",
                workflow_id, user_id,
            )
            if workflow is None:
                raise ValueError("Workflow not found or not owned by this account.")
            counts = await conn.fetchrow(
                """SELECT count(*) FILTER (WHERE workflow_id=$2::uuid AND node_id=$3) AS node,
                          count(*) AS account
                   FROM coordinator_signals WHERE user_id=$1::uuid AND kind='agent_message'
                     AND created_at>now()-interval '24 hours'""",
                user_id, workflow_id, node_id,
            )
            if counts["node"] >= node_cap or counts["account"] >= account_cap:
                raise ValueError(
                    "You've messaged the coordinator as often as allowed today "
                    f"({node_cap}/agent, {account_cap}/account). This message was not queued. "
                    "Batch further information for a later run; do not retry in a loop or report this as a platform bug."
                )
            row = await conn.fetchrow(
                """INSERT INTO coordinator_signals (user_id,kind,workflow_id,node_id,payload,woke)
                   VALUES ($1::uuid,'agent_message',$2::uuid,$3,$4,true) RETURNING *""",
                user_id, workflow_id, node_id,
                {**payload, "workflow_id": workflow_id, "workflow_name": workflow["name"] or "Untitled", "node_id": node_id},
            )
            epoch = await CoordinatorWakeupRepo(conn).epoch(user_id)
            return await CoordinatorWakeupRepo(self.pool).enqueue_signal(
                signal=dict(row), conn=conn, payload={"kind": "agent_message", **row["payload"]},
                context={"epoch": epoch, "depth": 0, "turn_id": str(uuid.uuid4()),
                         "channel": "web",
                         "request": f"An agent in “{row['payload']['workflow_name']}” messaged you"},
            )
