"""Who may use a conversation, part two: a run's conversation, an agent's
thread shared by a workflow's collaborators, and stopping a run before its
conversation exists.

Real socket entry (``workflow:execute``, ``agent:builder_decision``,
``agent:pause``) and the agent's own server-side writers, against real
Postgres; only the model is faked.
"""

import asyncio
import json
import logging
import uuid

import pytest

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.cancellation import CancelScope, register_builder_scope, unregister_builder_scope
from wss.receiver.client_events import WorkflowExecuteRequest
from wss.sender import send_event

CALLER = "00000000-0000-4000-8000-0000000001a1"
OTHER = "00000000-0000-4000-8000-0000000001b2"
STRANGER = "00000000-0000-4000-8000-0000000001c3"
PRIVATE = [{"role": "user", "message": "the private thing"}]


@pytest.fixture(autouse=True)
def _fake_model():
    from tests.mocks.mock_litellm import configure_mock_llm_responses

    configure_mock_llm_responses(default="Mock agent reply")


def _agent(node_id="agent-1"):
    return {"id": node_id, "type": "agent", "position": {"x": 0, "y": 0},
            "config": {"config": {"system_prompt": "Be brief", "message": "Say hi", "temperature": 0.5},
                       "credentials": {"api_key": "sk-test-openai-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}}}


@pytest.mark.asyncio
class TestConversationAccessFollowups(BaseHandlerTest):

    def get_session_data(self, sid: str):
        return {"sid": sid, "user_id": CALLER, "user_data": {"email": "caller@example.com"}}

    async def _users(self, db):
        for user_id in (CALLER, OTHER, STRANGER):
            await db.execute(
                "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                user_id, f"{user_id[-3:]}@example.com",
            )

    async def _workflow(self, db, owner):
        workflow_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Flow', $3)",
            workflow_id, owner, {"nodes": [_agent("agent")], "edges": []},
        )
        return workflow_id

    async def _share(self, db, workflow_id, user_id, permission="edit"):
        await db.execute(
            "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
            "VALUES ('workflow', $1::uuid, 'user', $2::uuid, $3, $4::uuid)", workflow_id, user_id, permission, OTHER,
        )

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

    async def _run(self, frontend_sio, sid, workflow_id, *, conversation_id=None, nodes=None):
        self.main_api_sio.emitted_events.clear()
        await send_event(frontend_sio, sid, WorkflowExecuteRequest(
            request_id=f"req-{uuid.uuid4().hex[:8]}", workflow_id=workflow_id,
            nodes=nodes or [_agent()], edges=[], conversation_id=conversation_id,
        ))
        await asyncio.sleep(0.2)
        [(_e, done, _t)] = self.get_main_api_emitted_events("workflow:complete")
        return done

    # ── a run's conversation (workflow:execute) ──────────────────────────

    async def test_a_run_names_no_other_accounts_conversation(self, real_database, frontend_sio, sid):
        """With no conversation key, an agent keeps its memory in the run's
        conversation: reading its history, writing each turn back."""
        await self._users(real_database)
        mine = await self._workflow(real_database, CALLER)
        theirs = f"coordinator:{OTHER}"
        await self._conversation(real_database, theirs, OTHER, metadata={"sdk_history": PRIVATE})
        before = await self._row(real_database, theirs)

        done = await self._run(frontend_sio, sid, mine, conversation_id=theirs)

        assert done["success"] is False and done["error"] == "This conversation can't be used for this run"
        assert await self._row(real_database, theirs) == before

    async def test_a_run_uses_a_new_conversation_or_one_of_its_workflow(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        mine = await self._workflow(real_database, CALLER)
        for conversation_id in (str(uuid.uuid4()), f"ck:{mine}:agent-1:main"):
            done = await self._run(frontend_sio, sid, mine, conversation_id=conversation_id)
            assert done["success"] is True, done
            assert (await self._row(real_database, conversation_id))["user_id"] == CALLER

    async def test_a_client_graph_runs_only_as_a_workflow_it_can_run(self, real_database, frontend_sio, sid):
        """Nodes sent with the request run as the named workflow: its
        organization pays and its owner's authorized credentials resolve."""
        await self._users(real_database)
        theirs = await self._workflow(real_database, OTHER)

        done = await self._run(frontend_sio, sid, theirs)

        assert done["success"] is False and done["error"] == "Workflow not found or access denied"
        assert await real_database.fetchval(
            "SELECT count(*) FROM workflow_executions WHERE workflow_id = $1::uuid", theirs,
        ) == 0

    # ── an agent thread its workflow's collaborators share ───────────────

    async def test_collaborators_write_a_shared_agent_thread_strangers_dont(
        self, real_database, frontend_sio, sid, caplog,
    ):
        """The default chat key gives every collaborator one thread, owned by
        whoever wrote first. A collaborator's proposal card, verdict and
        builder relay land in it; a stranger's are refused, and said so."""
        from nodes.agent.platform_tools import prompt_builder_impl
        from utils.builder_bridge import append_agent_builder_event

        await self._users(real_database)
        workflow = await self._workflow(real_database, OTHER)
        await self._share(real_database, workflow, CALLER)
        thread = f"ck:{workflow}:agent:__interface_chat__"
        await self._conversation(real_database, thread, OTHER, workflow_id=workflow)
        pool = real_database.pool

        async def card(user_id):
            return await prompt_builder_impl(
                pool=pool, user_id=user_id, workflow_id=workflow, node_id="agent", conversation_id=thread,
                conversation_key="__interface_chat__", prompt="Add a summary step",
            )

        async def relay(user_id, relay_id):
            await append_agent_builder_event(
                pool, agent_conversation_id=thread, user_id=user_id, workflow_id=workflow, node_id="agent",
                kind="builder_result", payload={"relay_id": relay_id, "summary": "Done", "success": True},
            )

        def kinds():
            return [next(iter(k for k in e if k != "timestamp")) for e in events[len(PRIVATE):]]

        # The collaborator: card, verdict on it, relay.
        assert (await card(CALLER))["status"] == "approval_requested"
        events = (await self._row(real_database, thread))["events"]
        proposal_id = events[-1]["builder_prompt"]["proposal_id"]
        self.main_api_sio.emitted_events.clear()
        await frontend_sio.emit("agent:builder_decision", {
            "request_id": "r1", "workflow_id": workflow, "node_id": "agent", "conversation_id": thread,
            "proposal_id": proposal_id, "decision": "approved",
        }, to=sid)
        [(_e, reply, _t)] = self.get_main_api_emitted_events("response")
        assert reply["data"] == {"success": True}
        await relay(CALLER, "r-collab")
        events = (await self._row(real_database, thread))["events"]
        assert kinds() == ["builder_prompt", "builder_decision", "builder_result"]

        # A stranger: nothing lands, and each refused write is logged.
        before = await self._row(real_database, thread)
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="repositories.conversation"):
            await card(STRANGER)
            await relay(STRANGER, "r-stranger")
        stranger_sid = self.main_api_sio.create_session("stranger-sid", user_id=STRANGER)
        self.main_api_sio.emitted_events.clear()
        await frontend_sio.emit("agent:builder_decision", {
            "request_id": "r2", "workflow_id": workflow, "node_id": "agent", "conversation_id": thread,
            "proposal_id": proposal_id, "decision": "dismissed",
        }, to=stranger_sid)
        [(_e, reply, _t)] = self.get_main_api_emitted_events("response")
        assert reply["data"]["success"] is False
        assert await self._row(real_database, thread) == before
        refused = [r for r in caplog.records if "changed nothing" in r.getMessage()]
        assert len(refused) == 2 and all(thread in r.getMessage() for r in refused)

    # ── stopping a run before its conversation exists ────────────────────

    async def test_a_runs_own_user_stops_it_before_its_conversation_exists(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        conversation_id = str(uuid.uuid4())  # the run registered its scope; its row isn't written yet
        run = CancelScope()
        register_builder_scope(conversation_id, run, CALLER)
        try:
            stranger_sid = self.main_api_sio.create_session("stranger-pause-sid", user_id=STRANGER)
            await frontend_sio.emit("agent:pause", {"conversation_id": conversation_id}, to=stranger_sid)
            assert not run.cancelled

            await frontend_sio.emit("agent:pause", {"conversation_id": conversation_id}, to=sid)
            assert run.cancelled
        finally:
            unregister_builder_scope(conversation_id, run)
