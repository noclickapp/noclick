"""An agent's model history in its own rows (repositories/conversation_history.py), on real Postgres.

While the move from ``conversations.metadata.sdk_history`` is under way, every write of a history lands in
both places, and the backfill (scripts/backfill_conversation_history.py) copies what was written before.
These pin that the two never drift: after each write, the rows are the key's history, item for item.
"""
import uuid

import pytest

from repositories import conversation_history
from scripts import backfill_conversation_history as backfill

pytestmark = pytest.mark.asyncio

USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def pool(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=4, init=setup_asyncpg_codecs)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    made = []
    try:
        yield pool, made
    finally:
        await pool.execute("DELETE FROM conversations WHERE conversation_id = ANY($1::text[])", made)
        await pool.close()


def _thread(made, prefix="ck:history") -> str:
    made.append(f"{prefix}:{uuid.uuid4().hex}")
    return made[-1]


async def _key(pool, conversation_id):
    metadata = await pool.fetchval("SELECT metadata FROM conversations WHERE conversation_id = $1", conversation_id)
    return (metadata or {}).get("sdk_history") or []


async def _in_step(pool, conversation_id):
    rows = await conversation_history.read(pool, conversation_id)
    assert rows == await _key(pool, conversation_id)
    return rows


async def test_every_session_write_lands_in_both(pool):
    from coder.openai_agent.session import PostgresSession

    pool, made = pool
    session = PostgresSession(_thread(made), user_id=USER)
    await session.add_items([{"role": "user", "content": "Where's my invoice?"},
                             {"type": "function_call", "call_id": "c1", "name": "invoices", "arguments": "{}",
                              "id": "fc_1", "provider_data": {"x": 1}}])
    await session.add_items([{"type": "function_call_output", "call_id": "c1", "output": "inv-7"},
                             {"role": "assistant", "content": "Attached."}])
    rows = await _in_step(pool, session.session_id)
    assert [r.get("content") or r.get("type") for r in rows] == [
        "Where's my invoice?", "function_call", "function_call_output", "Attached."]
    assert "id" not in rows[1] and "provider_data" not in rows[1]

    assert (await session.pop_item())["content"] == "Attached."
    assert len(await _in_step(pool, session.session_id)) == 3
    await session.clear_session()
    assert await _in_step(pool, session.session_id) == []
    await session.add_items([{"role": "user", "content": "again"}])
    assert len(await _in_step(pool, session.session_id)) == 1


async def test_two_appends_at_once_keep_their_own_order(pool):
    import asyncio

    from coder.openai_agent.session import PostgresSession

    pool, made = pool
    conversation_id = _thread(made)
    await PostgresSession(conversation_id, user_id=USER).add_items([{"role": "user", "content": "start"}])
    batches = [[{"role": "user", "content": f"{n}-{i}"} for i in range(5)] for n in range(4)]
    await asyncio.gather(*(PostgresSession(conversation_id, user_id=USER).add_items(b) for b in batches))
    rows = await _in_step(pool, conversation_id)
    # Each batch stays whole and in order, whichever landed first.
    contents = [r["content"] for r in rows[1:]]
    assert sorted(contents[i:i + 5] for i in range(0, 20, 5)) == sorted([[r["content"] for r in b] for b in batches])


async def test_starting_a_thread_over_clears_both(pool):
    from repositories.conversation import ConversationRepo
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo
    from coder.openai_agent.session import PostgresSession

    pool, made = pool
    chat = _thread(made)
    await PostgresSession(chat, user_id=USER).add_items([{"role": "user", "content": "hi"}])
    assert await ConversationRepo(pool).reset_conversation(chat, USER)
    assert await _in_step(pool, chat) == []

    coordinator = f"coordinator:{USER}"
    made.append(coordinator)
    await PostgresSession(coordinator, user_id=USER).add_items([{"role": "user", "content": "hi"}])
    assert await CoordinatorWakeupRepo(pool).reset(USER)
    assert await _in_step(pool, coordinator) == []


async def test_its_rows_follow_the_conversation_renamed_or_deleted(pool):
    from coder.openai_agent.session import PostgresSession

    pool, made = pool
    old, new = _thread(made), _thread(made)
    await PostgresSession(old, user_id=USER).add_items([{"role": "user", "content": "kept"}])
    await pool.execute("UPDATE conversations SET conversation_id = $2 WHERE conversation_id = $1", old, new)
    assert [r["content"] for r in await conversation_history.read(pool, new)] == ["kept"]
    await pool.execute("DELETE FROM conversations WHERE conversation_id = $1", new)
    assert await conversation_history.read(pool, new) == []


async def test_the_backfill_copies_each_history_once_and_verifies_it(pool):
    pool, made = pool
    written_before = _thread(made)
    half = _thread(made)
    history = [{"role": "user", "content": f"turn {i}"} for i in range(7)]
    for conversation_id in (written_before, half):
        await pool.execute("INSERT INTO conversations (conversation_id, user_id, metadata) VALUES ($1, $2::uuid, $3)",
                           conversation_id, USER, {"sdk_history": history, "other": "kept"})
    # A history whose newest items were written after the dual-write deploy: the rows hold only those.
    await conversation_history.append(pool, half, history[5:])

    async with pool.acquire() as conn:
        mine = [c for page in [p async for p in backfill.pages(conn)] for c in page if c in made]
        assert sorted(mine) == sorted([written_before, half])
        assert (await backfill.run(conn, apply=False, verify=True))["differ"] >= 2
        dry = await backfill.run(conn, apply=False, verify=False)
        assert await conversation_history.read(pool, written_before) == []
        assert dry["items"] >= 14
        await backfill.run(conn, apply=True, verify=False)
        await backfill.run(conn, apply=True, verify=False)  # again: still one copy
        checked = await backfill.run(conn, apply=False, verify=True)
    assert await _in_step(pool, written_before) == history
    assert await _in_step(pool, half) == history
    assert checked["differ"] == 0 and checked["stray"] == 0


async def test_verify_names_rows_whose_conversation_has_no_history(pool):
    pool, made = pool
    conversation_id = _thread(made)
    await pool.execute("INSERT INTO conversations (conversation_id, user_id, metadata) VALUES ($1, $2::uuid, '{}')",
                       conversation_id, USER)
    await conversation_history.append(pool, conversation_id, [{"role": "user", "content": "orphan"}])
    async with pool.acquire() as conn:
        assert (await backfill.run(conn, apply=False, verify=True))["stray"] >= 1
