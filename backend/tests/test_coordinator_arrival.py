"""Arriving from a public page: the workflow's setup note lands in the owner's coordinator thread once, carries the
reference its card draws from, reaches an open chat as the same frame the chat applies, and joins the coordinator's
own history so a follow-up like "now ask it to…" is understood."""

import uuid
from contextlib import asynccontextmanager

import pytest

from coder.coordinator import arrival
from utils import task_notifications

OWNER = "00000000-0000-0000-0000-000000000001"  # seeded by the fixtures
STRANGER = "00000000-0000-0000-0000-0000000000a2"

MCP_GRAPH = {
    "nodes": [
        {"id": "mcp-server", "type": "mcp-server", "config": {"label": "MCP Server"}},
        {"id": "slack-1", "type": "automation-slack", "config": {"label": "Slack", "agent_tool_operations": ["send_message_to_channel"]}},
    ],
    "edges": [{"id": "e_slack-1_mcp-server", "source": "slack-1", "target": "mcp-server", "sourceHandle": "top", "targetHandle": "bottom"}],
}
AGENT_GRAPH = {
    "nodes": [
        {"id": "agent", "type": "agent", "config": {"label": "OpenCode", "model": "opencode"}},
        {"id": "slack-1", "type": "automation-slack", "config": {"label": "Slack"}},
    ],
    "edges": [{"id": "e_slack-1_agent", "source": "slack-1", "target": "agent", "sourceHandle": "top", "targetHandle": "bottom"}],
}


def test_setup_kind_reads_the_graph():
    assert arrival.setup_kind(MCP_GRAPH) == "mcp"
    assert arrival.setup_kind(AGENT_GRAPH) == "agent"
    # An MCP node pointed at an external server serves nothing of the owner's: an agent beside it is what's set up.
    external = {"nodes": [{"id": "m", "type": "mcp-server", "config": {"server_url": "https://x.example/mcp"}}, *AGENT_GRAPH["nodes"]],
                "edges": AGENT_GRAPH["edges"]}
    assert arrival.setup_kind(external) == "agent"
    assert arrival.setup_kind({"nodes": [{"id": "m", "type": "mcp-server", "config": {}}], "edges": []}) is None
    assert arrival.setup_kind({"nodes": [], "edges": []}) is None


@pytest.fixture
async def arrival_db(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password,
        database=postgres_container.dbname, min_size=1, max_size=5, init=setup_asyncpg_codecs,
    )
    created = []

    async def workflow(graph, name="Slack for OpenCode"):
        workflow_id = str(uuid.uuid4())
        await pool.execute("INSERT INTO workflows(id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, $3, $4)",
                           workflow_id, OWNER, name, graph)
        created.append(workflow_id)
        return workflow_id

    emitted, spawned, remembered = [], [], []

    async def emit(_sio, user_id, conversation_id, event):
        emitted.append((user_id, conversation_id, event))

    class Session:
        def __init__(self, conversation_id, **_):
            self.conversation_id = conversation_id

        async def add_items(self, items):
            remembered.append((self.conversation_id, items))

    @asynccontextmanager
    async def lock(_pool, user_id):
        remembered.append(("locked", user_id))
        yield

    monkeypatch.setattr(task_notifications, "emit_notification", emit)
    monkeypatch.setattr("utils.async_helpers.spawn", lambda coro, name=None: spawned.append(coro))
    monkeypatch.setattr("coder.openai_agent.session.PostgresSession", Session)
    monkeypatch.setattr("repositories.coordinator_lease.coordinator_lock", lock)
    try:
        yield pool, workflow, emitted, spawned, remembered
    finally:
        for workflow_id in created:
            await pool.execute("DELETE FROM workflows WHERE id = $1::uuid", workflow_id)
        await pool.execute("DELETE FROM conversations WHERE conversation_id = $1", f"coordinator:{OWNER}")
        await pool.close()


async def _setup_events(pool):
    events = await pool.fetchval("SELECT events FROM conversations WHERE conversation_id = $1", f"coordinator:{OWNER}")
    return [e for e in events or [] if e.get("setup")]


@pytest.mark.asyncio
async def test_the_note_lands_once_with_its_reference_and_joins_history(arrival_db):
    pool, workflow, emitted, spawned, remembered = arrival_db
    workflow_id = await workflow(MCP_GRAPH)

    reply = await arrival.post_arrival(pool, OWNER, workflow_id=workflow_id, client="opencode")
    [note] = await _setup_events(pool)
    # The reply carries the note to the asking tab, which may not have its relay connected yet.
    assert reply == {"turn_id": f"setup:{workflow_id}",
                     "note": {"message": note["message"], "turn_id": note["turn_id"], "setup": note["setup"]}}
    assert note["message"] == "Let’s finish setting up Slack for OpenCode."
    assert note["notification"] is True and note["turn_id"] == f"setup:{workflow_id}"
    assert note["setup"] == {"kind": "mcp", "workflow_id": workflow_id, "client": "opencode"}
    assert emitted == [(OWNER, f"coordinator:{OWNER}", note)]

    # The coordinator's history gets the same line with the ids it acts on, under the turn lease.
    [remember] = spawned
    await remember
    assert remembered[0] == ("locked", OWNER)
    [(conversation_id, [item])] = remembered[1:]
    assert conversation_id == f"coordinator:{OWNER}" and item["role"] == "assistant"
    assert item["content"].startswith("Let’s finish setting up Slack for OpenCode.")
    assert f"workflow_id={workflow_id}" in item["content"] and "hosted MCP link" in item["content"]

    # Asked again (a retried request): nothing new is posted, sent or remembered; the reply still carries the note.
    assert (await arrival.post_arrival(pool, OWNER, workflow_id=workflow_id, client="opencode")) == reply
    assert len(await _setup_events(pool)) == 1 and len(emitted) == 1 and len(spawned) == 1


@pytest.mark.asyncio
async def test_an_agent_names_its_node_for_message_agent(arrival_db):
    pool, workflow, emitted, spawned, remembered = arrival_db
    workflow_id = await workflow(AGENT_GRAPH, name="OpenCode + Slack")
    await arrival.post_arrival(pool, OWNER, workflow_id=workflow_id, client=None)
    [note] = await _setup_events(pool)
    assert note["setup"] == {"kind": "agent", "workflow_id": workflow_id}
    await spawned[0]
    content = remembered[1][1][0]["content"]
    assert "agent node_id=agent" in content and "message_agent" in content


@pytest.mark.asyncio
async def test_only_the_owner_can_post_and_only_what_can_be_set_up(arrival_db):
    pool, workflow, emitted, spawned, _ = arrival_db
    workflow_id = await workflow(MCP_GRAPH)
    with pytest.raises(ValueError, match="isn't yours"):
        await arrival.post_arrival(pool, STRANGER, workflow_id=workflow_id, client=None)
    empty = await workflow({"nodes": [], "edges": []})
    with pytest.raises(ValueError, match="nothing to set up"):
        await arrival.post_arrival(pool, OWNER, workflow_id=empty, client=None)
    assert emitted == [] and spawned == []


@pytest.mark.asyncio
async def test_the_frame_carries_the_reference_the_chat_reads(monkeypatch):
    """The live frame is the real emitter's ChatMessageEvent, setup included, as the chat applies it."""
    sent = []

    async def broadcast(user_id, event):
        sent.append((user_id, event))
    monkeypatch.setattr("utils.event_relay.broadcast_to_user_safe", broadcast)
    event = task_notifications.notification_event(
        "Let’s finish setting up X.", "setup:wf", setup={"kind": "mcp", "workflow_id": "wf", "client": "codex"})
    await task_notifications.emit_notification(None, OWNER, f"coordinator:{OWNER}", event)
    [(user_id, frame)] = sent
    assert user_id == OWNER
    data = frame.model_dump(mode="json", exclude_none=True)
    assert data["notification"] is True and data["finished"] is True and data["turn_id"] == "setup:wf"
    assert data["setup"] == {"kind": "mcp", "workflow_id": "wf", "client": "codex"}
