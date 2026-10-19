"""A conversation is read and written only by the account it belongs to.

Conversation ids reach the server from clients (a builder chat, a proposal
verdict, a pause) and from the server's own callers (an agent's
``ck:{workflow}:{node}:{key}`` thread, ``coordinator:{user}``). These drive the
real socket entry against real Postgres: no client event writes into, reads
from or stops another account's conversation, and the conversation upserts
change only the writer's own row.
"""

import json
import uuid

import pytest

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from repositories.conversation import ConversationRepo
from utils.cancellation import CancelScope, get_builder_scope, register_builder_scope, unregister_builder_scope

CALLER = "00000000-0000-4000-8000-0000000000c1"
OTHER = "00000000-0000-4000-8000-0000000000d2"
PRIVATE = [{"role": "user", "message": "the private thing"}]


@pytest.mark.asyncio
class TestConversationAccess(BaseHandlerTest):

    def get_session_data(self, sid: str):
        return {"sid": sid, "user_id": CALLER, "user_data": {"email": "caller@example.com"}}

    async def _users(self, db):
        for user_id, email in ((CALLER, "caller@example.com"), (OTHER, "other@example.com")):
            await db.execute(
                "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", user_id, email,
            )

    async def _workflow(self, db, owner):
        workflow_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Flow', $3)",
            workflow_id, owner, {"nodes": [], "edges": []},
        )
        return workflow_id

    async def _conversation(self, db, conversation_id, user_id, *, workflow_id=None, events=PRIVATE, metadata=None):
        await db.execute(
            "INSERT INTO conversations (conversation_id, user_id, workflow_id, title, preview, events, metadata) "
            "VALUES ($1, $2::uuid, $3, 'Thread', '', $4::jsonb, $5::jsonb)",
            conversation_id, user_id, workflow_id, events, metadata or {},
        )

    async def _row(self, db, conversation_id):
        row = await db.fetchrow(
            "SELECT user_id::text AS user_id, events, metadata FROM conversations WHERE conversation_id = $1",
            conversation_id,
        )
        if row is None:
            return None
        decode = lambda v: json.loads(v) if isinstance(v, str) else v  # noqa: E731
        return {"user_id": row["user_id"], "events": decode(row["events"]), "metadata": decode(row["metadata"])}

    def _responses(self):
        return [d for _e, d, _t in self.get_main_api_emitted_events("response") if isinstance(d, dict)]

    # ── chat:message ─────────────────────────────────────────────────────

    async def test_a_client_cannot_chat_in_any_conversation_by_its_id(self, real_database, frontend_sio, sid):
        """The in-process chat agent took any conversation id and ran on its
        stored history, writing back into it. No client sends it any more."""
        await self._users(real_database)
        theirs = f"coordinator:{OTHER}"
        await self._conversation(real_database, theirs, OTHER, metadata={"sdk_history": PRIVATE})
        before = await self._row(real_database, theirs)

        result = await self.proxy.route_event("chat:message", sid, {
            "conversation_id": theirs, "model": "gpt-4o", "content": [{"type": "text", "text": "what did they say?"}],
        })

        assert result["error"] == "unknown_event"
        assert await self._row(real_database, theirs) == before

    # ── agent:builder_decision ───────────────────────────────────────────

    async def _decide(self, frontend_sio, sid, workflow_id, conversation_id, proposal_id):
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        await frontend_sio.emit("agent:builder_decision", {
            "request_id": request_id, "workflow_id": workflow_id, "node_id": "agent",
            "conversation_id": conversation_id, "proposal_id": proposal_id, "decision": "approved",
        }, to=sid)
        [reply] = [d for d in self._responses() if d.get("request_id") == request_id]
        return reply["data"]

    @staticmethod
    def _proposal(proposal_id):
        return {"builder_prompt": {"proposal_id": proposal_id, "node_id": "agent", "prompt": "Add a step"}}

    async def test_a_verdict_lands_only_on_a_proposal_in_the_callers_conversation(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        mine, theirs = await self._workflow(real_database, CALLER), await self._workflow(real_database, OTHER)
        their_thread = f"ck:{theirs}:agent:main"
        await self._conversation(real_database, their_thread, OTHER, workflow_id=theirs,
                                 events=[self._proposal("p1")])
        my_thread = f"ck:{mine}:agent:main"
        await self._conversation(real_database, my_thread, CALLER, workflow_id=mine, events=[self._proposal("p1")])

        # Another account's conversation, named beside a workflow the caller can open.
        before = await self._row(real_database, their_thread)
        assert (await self._decide(frontend_sio, sid, mine, their_thread, "p1"))["success"] is False
        assert await self._row(real_database, their_thread) == before

        # The caller's own conversation, but no proposal of that id: nothing to relay to the agent.
        before = await self._row(real_database, my_thread)
        assert (await self._decide(frontend_sio, sid, mine, my_thread, "x" * 5000))["success"] is False
        assert await self._row(real_database, my_thread) == before

        # The proposal the agent made: recorded.
        assert (await self._decide(frontend_sio, sid, mine, my_thread, "p1"))["success"] is True
        events = (await self._row(real_database, my_thread))["events"]
        assert events[-1]["builder_decision"] == {"proposal_id": "p1", "decision": "approved", "node_id": "agent"}

    # ── agent:pause ──────────────────────────────────────────────────────

    async def test_a_pause_stops_only_the_callers_own_run(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        theirs, mine = str(uuid.uuid4()), str(uuid.uuid4())
        await self._conversation(real_database, theirs, OTHER)
        await self._conversation(real_database, mine, CALLER)
        their_run, my_run = CancelScope(), CancelScope()
        register_builder_scope(theirs, their_run)
        register_builder_scope(mine, my_run)
        try:
            await frontend_sio.emit("agent:pause", {"conversation_id": theirs}, to=sid)
            await frontend_sio.emit("agent:pause", {"conversation_id": mine}, to=sid)

            assert not their_run.cancelled and get_builder_scope(theirs) is their_run
            assert my_run.cancelled
        finally:
            unregister_builder_scope(theirs, their_run)
            unregister_builder_scope(mine, my_run)

    # ── the conversation upserts ─────────────────────────────────────────

    async def test_conversation_writes_change_only_the_writers_own_row(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        theirs = f"ck:{uuid.uuid4()}:agent:main"
        await self._conversation(real_database, theirs, OTHER)
        before = await self._row(real_database, theirs)
        repo = ConversationRepo(real_database.pool)

        await repo.append_chat_event(conversation_id=theirs, user_id=CALLER, workflow_id=None, node_id=None,
                                     event={"role": "user", "message": "injected"}, label="x", model=None)
        assert not await repo.append_chat_event_once(
            conversation_id=theirs, user_id=CALLER, node_id=None,
            event={"role": "assistant", "message": "injected", "turn_id": "t1"}, label=None)
        await repo.ensure_stub(theirs, CALLER, "injected", str(uuid.uuid4()))
        await repo.upsert_events(theirs, CALLER, None, "x", "x", [{"role": "user", "message": "injected"}],
                                 None, 1.0, 1, 1)
        assert await self._row(real_database, theirs) == before

        # The rightful owner's own write still lands.
        await repo.append_chat_event(conversation_id=theirs, user_id=OTHER, workflow_id=None, node_id=None,
                                     event={"role": "assistant", "message": "reply"}, label=None, model=None)
        after = await self._row(real_database, theirs)
        assert after["user_id"] == OTHER and after["events"] == PRIVATE + [{"role": "assistant", "message": "reply"}]
