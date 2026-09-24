"""The ledger of work the account coordinator starts and waits on
(``coordinator_jobs``). Each kind's runner owns its own transitions; this is
what every kind shares."""

ACTIVE = "('queued','running','waiting')"
TERMINAL = "('completed','failed','cancelled')"


class CoordinatorJobRepo:
    def __init__(self, pool):
        self.pool = pool

    async def list_for_user(self, user_id, *, job_id=None, kind=None, limit=20):
        rows = await self.pool.fetch(
            f"""SELECT * FROM coordinator_jobs WHERE user_id=$1::uuid
               AND ($2::uuid IS NULL OR id=$2::uuid) AND ($3::text IS NULL OR kind=$3)
               ORDER BY (status IN {ACTIVE}) DESC, created_at DESC LIMIT $4""",
            user_id, job_id, kind, limit,
        )
        return [dict(r) for r in rows]
