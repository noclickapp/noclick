"""The coordinator's own email address and how it reaches its owner, against
real Postgres: the address shares the inbound namespace with trigger nodes;
only the owner's authenticated mail becomes a turn; its email goes out on one
thread (kept on the coordinator conversation) and is billed; ``auto`` is the
last-used channel, then the web — a stated preference is a memory the
coordinator acts on by naming the channel."""

import uuid
from unittest.mock import AsyncMock

import pytest

from billing.usage_tracker import usage_tracker
from coder.coordinator import email_channel, reach
from coder.coordinator.email_channel import CoordinatorEmailError, set_coordinator_address

pytestmark = pytest.mark.asyncio
DOMAIN = "noclick.app"


@pytest.fixture
async def owner(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", DOMAIN)
    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=4, init=setup_asyncpg_codecs,
    )
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    user_id = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id", email))
    try:
        yield pool, user_id, email
    finally:
        await pool.close()


async def test_the_address_shares_one_namespace_and_renames(owner):
    pool, user_id, _ = owner
    name = f"ada-{uuid.uuid4().hex[:6]}"
    assert await set_coordinator_address(pool, user_id, f"  {name.upper()}  ") == f"{name}@{DOMAIN}"
    assert await email_channel.coordinator_address(pool, user_id) == f"{name}@{DOMAIN}"
    renamed = f"{name}-assistant"
    await set_coordinator_address(pool, user_id, renamed)
    assert await email_channel.coordinator_address(pool, user_id) == f"{renamed}@{DOMAIN}"
    assert await email_channel.owner_for_address(pool, name, DOMAIN) is None  # the old name is free again

    # A trigger node's address and a coordinator's can't collide.
    workflow = await pool.fetchval("INSERT INTO workflows (owner_id, name) VALUES ($1::uuid, 'w') RETURNING id", user_id)
    taken = f"orders-{uuid.uuid4().hex[:6]}"
    await pool.execute("INSERT INTO email_reservations (user_id, workflow_id, node_id, local_part, domain) "
                       "VALUES ($1::uuid, $2, 'trigger', $3, $4)", user_id, workflow, taken, DOMAIN)
    with pytest.raises(CoordinatorEmailError, match="taken"):
        await set_coordinator_address(pool, user_id, taken)
    for bad in ("support", "agent-reply-abc", "no spaces"):
        with pytest.raises(CoordinatorEmailError):
            await set_coordinator_address(pool, user_id, bad)
    assert await email_channel.coordinator_address(pool, user_id) == f"{renamed}@{DOMAIN}"


async def test_only_the_owners_authenticated_mail_becomes_a_turn(owner, monkeypatch):
    pool, user_id, email = owner
    name = f"bo-{uuid.uuid4().hex[:6]}"
    await set_coordinator_address(pool, user_id, name)
    turns = AsyncMock()
    monkeypatch.setattr(email_channel, "run_email_turn", turns)
    seen = set()
    monkeypatch.setattr("utils.app_event_dedup.was_delivered", AsyncMock(side_effect=lambda p, i: i in seen))
    monkeypatch.setattr("utils.app_event_dedup.mark_delivered", AsyncMock(side_effect=lambda p, i: seen.add(i)))
    body = "Can you pause the digest?\n\nOn Tue, the coordinator wrote:\n> earlier text"
    mail = {"from": f"Owner <{email.upper()}>", "subject": "Digest", "dkimPass": True,
            "headers": {"message-id": "<m1@example.com>"}}

    assert await email_channel.receive(pool, name, DOMAIN, {**mail, "from": "x@evil.example"}, body) == "sender is not the owner"
    assert await email_channel.receive(pool, name, DOMAIN, {**mail, "dkimPass": False, "spfPass": False}, body) \
        == "sender not authenticated"
    assert await email_channel.receive(pool, "nobody", DOMAIN, mail, body) == "unknown address"
    turns.assert_not_awaited()

    assert await email_channel.receive(pool, name, DOMAIN, mail, body) == "delivered"
    kwargs = turns.await_args.kwargs
    assert kwargs["text"] == "Can you pause the digest?" and kwargs["subject"] == "Digest" and kwargs["user_id"] == user_id
    assert kwargs["message_id"] == "<m1@example.com>"
    assert await email_channel.receive(pool, name, DOMAIN, mail, body) == "duplicate"
    assert turns.await_count == 1






async def test_auto_is_the_last_used_channel_and_a_named_channel_wins(owner, monkeypatch):
    pool, user_id, _ = owner
    assert await reach.resolve_channel(pool, user_id) == "web"
    await pool.execute(
        "INSERT INTO conversations (conversation_id, user_id, events) VALUES ($1, $2::uuid, $3)",
        f"coordinator:{user_id}", user_id,
        [{"role": "user", "message": "hi", "channel": "web"}, {"role": "assistant", "message": "hello"},
         {"role": "user", "message": "from my phone", "channel": "whatsapp_text"}])
    assert await reach.resolve_channel(pool, user_id) == "whatsapp"
    assert await reach.resolve_channel(pool, user_id, "email") == "email"

    monkeypatch.setattr("utils.task_notifications.emit_notification", AsyncMock())
    out = await reach.reach_owner(pool, user_id, "Heads up", channel="web")
    assert out == {"success": True, "channel": "web"}
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id = $1", f"coordinator:{user_id}")
    assert events[-1]["message"] == "Heads up" and events[-1]["notification"] is True
