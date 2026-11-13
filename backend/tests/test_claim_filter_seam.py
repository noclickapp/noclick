"""The claim filter a deployment can register (``utils.claims``): with none, the engine's queue claims read exactly
as they always did; with one, they take only the rows it lets through, judged on the real schema."""

import uuid

import pytest

from repositories.builder_requests import BuilderRequestRepo
from repositories.coordinator_tasks import CoordinatorTaskRepo
from utils import capabilities
from utils.capabilities import CLAIM_FILTER
from utils.claims import claimable


@pytest.fixture
def no_filter(monkeypatch):
    monkeypatch.delitem(capabilities._providers, CLAIM_FILTER, raising=False)


@pytest.fixture
async def queues(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=3, init=setup_asyncpg_codecs,
    )
    owners = [str(await pool.fetchval("INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
                                      f"claims-{uuid.uuid4().hex[:10]}@example.com")) for _ in range(2)]
    await pool.execute("DELETE FROM coordinator_jobs")

    async def workflow(owner):
        return str(await pool.fetchval("INSERT INTO workflows (owner_id, name, workflow) VALUES ($1::uuid, 'w', $2) "
                                       "RETURNING id", owner, {"nodes": [], "edges": []}))

    async def jobs(owner):
        agent = await CoordinatorTaskRepo(pool).enqueue(
            user_id=owner, workflow_id=await workflow(owner), node_id="agent", agent_name="Helper", message="hi",
            send_to_phone=False)
        build = await pool.fetchval(
            """INSERT INTO coordinator_jobs (user_id, kind, workflow_id, conversation_key, spec, phase)
               VALUES ($1::uuid, 'build', $2::uuid, $3, '{"instructions": "x"}'::jsonb, 'building') RETURNING id""",
            owner, await workflow(owner), f"builder-request:{uuid.uuid4()}")
        return agent["id"], build

    try:
        yield pool, owners, jobs
    finally:
        await pool.close()


async def _claim_all(pool):
    tasks, builds = CoordinatorTaskRepo(pool), BuilderRequestRepo(pool)
    claimed_tasks, claimed_builds = [], []
    while (task := await tasks.claim()) is not None:
        claimed_tasks.append(task["id"])
    while (build := await builds.claim()) is not None:
        claimed_builds.append(build["id"])
    return claimed_tasks, claimed_builds


def test_no_filter_adds_nothing_to_a_claim(no_filter):
    assert claimable("t.owner", "t.created_at") == ""


def test_a_registered_filter_narrows_with_its_own_predicate(monkeypatch):
    monkeypatch.setitem(capabilities._providers, CLAIM_FILTER, lambda owner, since: f"{owner} = 1 AND {since} > 0")
    assert claimable("t.owner", "t.created_at") == " AND (t.owner = 1 AND t.created_at > 0)"


async def test_without_a_filter_every_queued_job_is_claimed(queues, no_filter):
    pool, owners, jobs = queues
    first, second = await jobs(owners[0]), await jobs(owners[1])
    assert await _claim_all(pool) == ([first[0], second[0]], [first[1], second[1]])


async def test_a_filter_decides_which_jobs_a_claim_takes(queues, monkeypatch):
    pool, owners, jobs = queues
    kept, taken = await jobs(owners[0]), await jobs(owners[1])
    # The rows of the first owner wait until they're an hour old: their readiness is valid SQL in every claim.
    monkeypatch.setitem(capabilities._providers, CLAIM_FILTER, lambda owner, since: (
        f"({owner})::text <> '{owners[0]}' OR ({since}) <= clock_timestamp() - interval '1 hour'"))
    assert await _claim_all(pool) == ([taken[0]], [taken[1]])

    await pool.execute("UPDATE coordinator_jobs SET created_at = created_at - interval '2 hours', "
                       "updated_at = updated_at - interval '2 hours' WHERE user_id = $1::uuid", owners[0])
    assert await _claim_all(pool) == ([kept[0]], [kept[1]])
    tasks, builds = CoordinatorTaskRepo(pool), BuilderRequestRepo(pool)
    await tasks.reap_stalled()
    assert await tasks.pending_notifications() == []
    await builds.reap_stalled()
    assert await builds.claim_notification() is None
