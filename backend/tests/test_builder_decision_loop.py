"""The prompt_builder approval-card decision loop (2026-07-19).

The card's approve/dismiss verdict must (a) persist as a conversation event
(agent:builder_decision), (b) restore the card's decided state, and (c) reach
the agent exactly once as a platform note on its next turn — without this the
agent only ever knew 'awaiting approval' and answered wrongly after the
builder had already run.

Repo SQL runs against the LOCAL postgres (skipped when unreachable); the
handler and relay composition are unit-tested with fakes.
"""
import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

LOCAL_DSN = os.environ.get(
    "NC_TEST_POSTGRES_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


# ── repo SQL (real local DB) ─────────────────────────────────────────────────


@pytest.fixture
async def local_pool():
    import asyncpg

    from utils.database_pool import setup_asyncpg_codecs

    try:
        pool = await asyncpg.create_pool(
            LOCAL_DSN, min_size=1, max_size=2, timeout=5, init=setup_asyncpg_codecs,
        )
    except Exception:
        pytest.skip("local postgres unavailable")
    try:
        yield pool
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_fetch_and_mark_builder_decisions_roundtrip(local_pool):
    from repositories.conversation import ConversationRepo

    repo = ConversationRepo(local_pool)
    cid = f"ck:test:{uuid.uuid4().hex[:8]}:__interface_chat__"
    # conversations.user_id FKs auth.users — use any real local user.
    async with local_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM auth.users LIMIT 1")
    if not row:
        pytest.skip("no local users to satisfy the conversations FK")
    user_id = str(row["id"])
    try:
        # A proposal card, its verdict, and normal chat traffic around them.
        for event in (
            {"role": "user", "message": "add slack"},
            {"builder_prompt": {"prompt": "Add Slack", "proposal_id": "p1"}},
            {"role": "assistant", "message": "proposed"},
            {"builder_decision": {"proposal_id": "p1", "decision": "approved"}},
            {"builder_decision": {"proposal_id": "p2", "decision": "dismissed"}},
        ):
            await repo.append_chat_event(
                conversation_id=cid, user_id=user_id, workflow_id=None,
                node_id=None, event=event, label=None, model=None,
            )

        # Later kinds: a parked-ask bridge link and a run result.
        for event in (
            {"builder_ask": {"relay_id": "l1", "questions": ["Which channel?"],
                             "bridge_url": "https://x/b/l1"}},
            {"builder_result": {"relay_id": "r1", "summary": "Added Slack."}},
        ):
            await repo.append_chat_event(
                conversation_id=cid, user_id=user_id, workflow_id=None,
                node_id=None, event=event, label=None, model=None,
            )

        pending = await repo.fetch_unrelayed_builder_events(cid)
        assert [(e["kind"], e["payload"].get("proposal_id") or e["payload"].get("relay_id"))
                for e in pending] == [
            ("builder_decision", "p1"), ("builder_decision", "p2"),
            ("builder_ask", "l1"), ("builder_result", "r1"),
        ]

        # Mark a subset — the rest stays pending; then the rest; then nothing.
        await repo.mark_builder_events_relayed(
            cid, [("builder_decision", "p1"), ("builder_ask", "l1")]
        )
        pending = await repo.fetch_unrelayed_builder_events(cid)
        assert [(e["kind"], e["payload"].get("proposal_id") or e["payload"].get("relay_id"))
                for e in pending] == [
            ("builder_decision", "p2"), ("builder_result", "r1"),
        ]
        await repo.mark_builder_events_relayed(
            cid, [("builder_decision", "p2"), ("builder_result", "r1")]
        )
        assert await repo.fetch_unrelayed_builder_events(cid) == []

        # Marking must not disturb the surrounding events (order + content).
        async with local_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT events FROM conversations WHERE conversation_id=$1", cid
            )
        import json

        events = row["events"]
        if isinstance(events, str):
            events = json.loads(events)
        assert [
            ("user" if e.get("role") == "user" else e.get("role") or next(iter(e)))
            for e in events
        ] == ["user", "builder_prompt", "assistant", "builder_decision",
              "builder_decision", "builder_ask", "builder_result"]
    finally:
        async with local_pool.acquire() as conn:
            await conn.execute("DELETE FROM conversations WHERE conversation_id=$1", cid)


# ── handler (fakes) ──────────────────────────────────────────────────────────


def _make_handler(user_id="u-1"):
    from wss.handlers.agent_handler import AgentHandler

    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": user_id})
    handler = AgentHandler(sio)
    handler.get_pool = AsyncMock(return_value=MagicMock())
    return handler


def _decision_request(**overrides):
    from wss.receiver.client_events import AgentBuilderDecisionRequest

    base = dict(
        request_id="r1", workflow_id=str(uuid.uuid4()), node_id="agent_1",
        conversation_id="ck:wf:agent_1:__interface_chat__",
        proposal_id="p1", decision="approved",
    )
    base.update(overrides)
    return AgentBuilderDecisionRequest(**base)


@pytest.mark.asyncio
async def test_handle_builder_decision_appends_and_acks(monkeypatch):
    handler = _make_handler()
    appended = {}

    async def fake_append(self, **kw):
        appended.update(kw)

    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.append_chat_event", fake_append
    )
    monkeypatch.setattr(
        "utils.access_control.check_resource_access",
        AsyncMock(return_value=SimpleNamespace(has_access=True)),
    )
    handler.get_pool = AsyncMock(return_value=MagicMock(acquire=MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))))
    sent = []
    monkeypatch.setattr(
        "wss.handlers.agent_handler.send_event",
        AsyncMock(side_effect=lambda sio, sid, ev: sent.append(ev)),
    )

    await handler.handle_builder_decision("sid-1", _decision_request())
    assert sent and sent[-1].data == {"success": True}
    assert appended["event"]["builder_decision"]["proposal_id"] == "p1"
    assert appended["event"]["builder_decision"]["decision"] == "approved"
    assert appended["event"]["timestamp"]


@pytest.mark.asyncio
async def test_handle_builder_decision_rejects_bad_decision_and_no_access(monkeypatch):
    handler = _make_handler()
    append = AsyncMock()
    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.append_chat_event", append
    )
    sent = []
    monkeypatch.setattr(
        "wss.handlers.agent_handler.send_event",
        AsyncMock(side_effect=lambda sio, sid, ev: sent.append(ev)),
    )

    await handler.handle_builder_decision("sid-1", _decision_request(decision="maybe"))
    assert sent[-1].data["success"] is False
    assert append.await_count == 0

    monkeypatch.setattr(
        "utils.access_control.check_resource_access",
        AsyncMock(return_value=SimpleNamespace(has_access=False)),
    )
    handler.get_pool = AsyncMock(return_value=MagicMock(acquire=MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))))
    await handler.handle_builder_decision("sid-1", _decision_request())
    assert sent[-1].data["success"] is False
    assert append.await_count == 0


# ── agent-side relay note ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relay_builder_updates_composes_note_and_marks_once(monkeypatch):
    from nodes.agent_node import AgentNode

    fetched = [
        {"kind": "builder_decision", "payload": {"proposal_id": "p1", "decision": "approved"}},
        {"kind": "builder_decision", "payload": {"proposal_id": "p2", "decision": "dismissed"}},
        {"kind": "builder_ask", "payload": {
            "relay_id": "l1", "questions": ["Which channel?", "Connect Slack"],
            "inputs": [
                {"id": "ask_0", "label": "Which channel?", "type": "config",
                 "required": True,
                 "options": [{"label": "#alerts"}, {"label": "#general"}]},
                {"id": "ask_1", "label": "Connect Slack", "type": "credential",
                 "required": True},
            ],
            "bridge_url": "https://noclick.com/b/l1",
        }},
        {"kind": "builder_result", "payload": {"relay_id": "r1", "summary": "Added a Slack provider."}},
    ]
    marked = []

    async def fake_fetch(self, cid):
        return fetched

    async def fake_mark(self, cid, keys):
        marked.extend(keys)

    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.fetch_unrelayed_builder_events",
        fake_fetch,
    )
    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.mark_builder_events_relayed",
        fake_mark,
    )
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: MagicMock())

    note = await AgentNode._relay_builder_updates(SimpleNamespace(), "cid-1")
    assert note and "Platform note" in note
    assert "p1: APPROVED" in note and "p2: DISMISSED" in note
    # The parked ask lists inputs BY ID (builder_respond answers key on them),
    # with options, plus the answer-vs-share guidance and the no-login link.
    assert "[ask_0] Which channel? (config, required; options: #alerts | #general)" in note
    assert "[ask_1] Connect Slack (credential, required)" in note
    assert "builder_respond" in note
    assert "ONLY be connected by a human" in note
    assert "https://noclick.com/b/l1" in note
    assert "FINISHED: Added a Slack provider." in note
    assert marked == [
        ("builder_decision", "p1"), ("builder_decision", "p2"),
        ("builder_ask", "l1"), ("builder_result", "r1"),
    ]

    fetched.clear()
    assert await AgentNode._relay_builder_updates(SimpleNamespace(), "cid-1") is None


# ── SDK persist attaches the turn's tool timeline ────────────────────────────


@pytest.mark.asyncio
async def test_workflow_execute_persist_attaches_tool_timeline(monkeypatch):
    """Interface-chat sends ride the WORKFLOW-EXECUTE path, whose assistant
    events persist via AgentNode._persist_interface_chat_event — the #1773 fix
    only patched the AgentHandler path, so remounts still lost the step rows
    for these turns (2026-07-19 second report)."""
    from nodes.agent_node import AgentNode

    executed = []

    class FakePool:
        async def execute(self, sql, *args):
            executed.append(args)

    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: FakePool())
    gather = AsyncMock(return_value=[
        {"tool_name": "email_user", "arguments": {"subject": "s"}},
    ])
    monkeypatch.setattr("utils.tool_call_log.gather_turn_tool_calls", gather)

    fake = SimpleNamespace(
        user_id="u-1", workflow_id="wf-1", node_id="agent_1",
        _UPSERT_INTERFACE_EVENT_SQL=AgentNode._UPSERT_INTERFACE_EVENT_SQL,
    )
    await AgentNode._persist_interface_chat_event(
        fake, conversation_id="cid-1", role="assistant",
        message="done", model="gpt-x",
    )
    [event] = executed[-1][4]
    assert event["role"] == "assistant"
    assert event["tool_calls"] and event["tool_calls"][0]["tool_name"] == "email_user"

    # User events never gather (must not consume the turn boundary).
    gather.reset_mock()
    await AgentNode._persist_interface_chat_event(
        fake, conversation_id="cid-1", role="user",
        message="hi", model="gpt-x",
    )
    assert executed[-1][4][0]["role"] == "user"
    assert "tool_calls" not in executed[-1][4][0]
    assert gather.await_count == 0


@pytest.mark.asyncio
async def test_sdk_persist_attaches_tool_timeline(monkeypatch):
    """The in-process SDK chat persist must attach the audited tool timeline to
    the assistant event — skipping it left every refreshed transcript stepless
    while the CLI path persisted steps correctly (2026-07-19)."""
    handler = _make_handler()
    appended = []

    async def fake_append(self, **kw):
        appended.append(kw)

    monkeypatch.setattr(
        "repositories.conversation.ConversationRepo.append_chat_event", fake_append
    )
    monkeypatch.setattr(
        "utils.tool_call_log.gather_turn_tool_calls",
        AsyncMock(return_value=[{"tool_name": "submit_feedback", "arguments": {"feedback": "x"}}]),
    )

    await handler._persist_chat_event(
        conversation_id="cid-1", user_id="u-1", workflow_id="wf-1",
        node_id="agent_1", source="agent", content="done", model="gpt-x",
    )
    event = appended[-1]["event"]
    assert event["role"] == "assistant"
    assert event["tool_calls"] and event["tool_calls"][0]["tool_name"] == "submit_feedback"

    # User events never carry a timeline (and must not consume the boundary).
    gather = AsyncMock(return_value=[{"tool_name": "should_not_run"}])
    monkeypatch.setattr("utils.tool_call_log.gather_turn_tool_calls", gather)
    await handler._persist_chat_event(
        conversation_id="cid-1", user_id="u-1", workflow_id="wf-1",
        node_id="agent_1", source="user", content="hi", model="gpt-x",
    )
    assert appended[-1]["event"]["role"] == "user"
    assert "tool_calls" not in appended[-1]["event"]
    assert gather.await_count == 0
