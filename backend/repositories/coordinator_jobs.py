"""The ledger of work the account coordinator starts and waits on
(``coordinator_jobs``). Each kind's runner owns its own transitions; this is
what every kind shares."""

from typing import List

ACTIVE = "('queued','running','waiting')"
TERMINAL = "('completed','failed','cancelled')"
# An agent node's video rides this ledger for its poller and its single
# charge, but the coordinator never started it, so its reads leave it out.
AGENT_NODE_SOURCE = "agent_node"
# Sources of the other jobs the coordinator never started: another surface's
# agent turns on this ledger (``coder.coordinator.tasks.register_agent_job_source``).
_OUTSIDE_SOURCES: List[str] = [AGENT_NODE_SOURCE]


def register_outside_source(source: str) -> None:
    if source not in _OUTSIDE_SOURCES:
        _OUTSIDE_SOURCES.append(source)


def outside_sources() -> List[str]:
    return list(_OUTSIDE_SOURCES)


def started_by_coordinator(param: int, alias: str = "") -> str:
    """The SQL that keeps jobs the coordinator started, given ``outside_sources()`` as ``$param``."""
    return f"COALESCE({alias}origin->>'source', '') <> ALL(${param}::text[])"


class CoordinatorJobRepo:
    def __init__(self, pool):
        self.pool = pool

    async def list_for_user(self, user_id, *, job_id=None, kind=None, limit=20):
        rows = await self.pool.fetch(
            f"""SELECT * FROM coordinator_jobs WHERE user_id=$1::uuid
               AND ($2::uuid IS NULL OR id=$2::uuid) AND ($3::text IS NULL OR kind=$3)
               AND {started_by_coordinator(5)}
               ORDER BY (status IN {ACTIVE}) DESC, created_at DESC LIMIT $4""",
            user_id, job_id, kind, limit, outside_sources(),
        )
        return [dict(r) for r in rows]

    async def list_by_ids(self, user_id, job_ids):
        """The account's own jobs among ``job_ids``; an id that isn't one of them is simply absent."""
        rows = await self.pool.fetch(
            "SELECT * FROM coordinator_jobs WHERE user_id=$1::uuid AND id = ANY($2::uuid[])", user_id, job_ids,
        )
        return [dict(r) for r in rows]
