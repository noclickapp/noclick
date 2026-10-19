"""What a builder request from a client can reach beyond its workflow.

A socket request names a conversation, and its user_context could name where
the run's outcome goes (an agent's thread, the coordinator, a build request).
These drive the real ``workflow:builder:edit`` entry against real Postgres,
stubbing only the brain's LLM stream: a client routes no outcome anywhere,
starts no thread the server mints, stops no other run, moves only the
workflows it may edit, and names no file outside the session logs.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_builder_workflow_access import _brain, _brain_key  # noqa: F401 (autouse)
from tests.utils.base_handler_test import BaseHandlerTest
from tests.utils.task_helpers import drain_spawned_tasks
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.cancellation import CancelScope, get_builder_scope, register_builder_scope, unregister_builder_scope
from wss.handlers.workflow_builder_handler import (
    BUILDER_FOREIGN_CONVERSATION, BUILDER_INVALID_CONVERSATION, WorkflowBuilderHandler,
)
from wss.receiver.client_events import WorkflowBuilderEditRequest
from wss.sender import send_event

CALLER = "00000000-0000-4000-8000-0000000000e1"
OTHER = "00000000-0000-4000-8000-0000000000f2"
GRAPH = {"nodes": [{"id": "hook", "type": "trigger-webhook", "config": {"label": "Hook"},
                    "position": {"x": 0, "y": 0}}], "edges": []}


@pytest.mark.asyncio
class TestBuilderConversationAccess(BaseHandlerTest):

    def get_session_data(self, sid: str):
        return {"sid": sid, "user_id": CALLER, "user_data": {"email": "caller@example.com"}}

    async def _users(self, db):
        for user_id, email in ((CALLER, "caller@example.com"), (OTHER, "other@example.com")):
            await db.execute(
                "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", user_id, email,
            )
            await db.execute(
                "INSERT INTO user_billing (id, subscription_tier) VALUES ($1, 'enterprise') "
                "ON CONFLICT (id) DO UPDATE SET subscription_tier = 'enterprise'", user_id,
            )

    async def _workflow(self, db, owner):
        workflow_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Flow', $3)",
            workflow_id, owner, GRAPH,
        )
        return workflow_id

    async def _thread(self, db, conversation_id, user_id, workflow_id=None):
        await db.execute(
            "INSERT INTO conversations (conversation_id, user_id, workflow_id, title, preview, events) "
            "VALUES ($1, $2::uuid, $3, 'Thread', '', $4::jsonb)",
            conversation_id, user_id, workflow_id, [{"role": "user", "message": "hello"}],
        )

    async def _row(self, db, conversation_id):
        row = await db.fetchrow(
            "SELECT user_id::text AS user_id, events FROM conversations WHERE conversation_id = $1", conversation_id,
        )
        if row is None:
            return None
        events = json.loads(row["events"]) if isinstance(row["events"], str) else row["events"]
        return {"user_id": row["user_id"], "events": events}

    async def _edit(self, frontend_sio, sid, workflow_id, *, conversation_id=None, user_context=None,
                    replies=("Done.\n<done/>",)):
        request = WorkflowBuilderEditRequest(
            request_id=f"req-{uuid.uuid4().hex[:8]}", current_graph=GRAPH, edit_prompt="Tidy this up",
            conversation_id=conversation_id or str(uuid.uuid4()),
            user_context={"workflow_id": workflow_id, "workflow_name": "Flow", **(user_context or {})},
        )
        brain = _brain(*replies)
        with patch("litellm.acompletion", side_effect=brain):
            await send_event(frontend_sio, sid, request)
        return request, brain

    def _errors(self, request_id):
        return [d.get("error") for _e, d, _t in self.get_main_api_emitted_events("response")
                if isinstance(d, dict) and d.get("request_id") == request_id and d.get("error")]

    # ── where a run's outcome goes ───────────────────────────────────────

    async def test_a_client_routes_no_outcome_to_an_agents_thread(self, real_database, frontend_sio, sid):
        """The agent relay keys (set when an agent's prompt_builder starts a
        run) would post the run's result into that agent's thread and wake it."""
        await self._users(real_database)
        mine, theirs = await self._workflow(real_database, CALLER), await self._workflow(real_database, OTHER)
        their_thread = f"ck:{theirs}:agent:main"
        await self._thread(real_database, their_thread, OTHER, theirs)
        before = await self._row(real_database, their_thread)

        with patch("utils.builder_bridge.fire_agent_wake_turn", AsyncMock()) as wake:
            request, brain = await self._edit(frontend_sio, sid, mine, user_context={
                "source": "agent_prompt_builder", "agent_conversation_id": their_thread, "agent_node_id": "agent",
            })
            await drain_spawned_tasks()

        assert self._errors(request.request_id) == [] and brain.calls  # the edit itself ran
        assert wake.await_count == 0
        assert await self._row(real_database, their_thread) == before
        # Nor did the keys reach the brain.
        assert not any(their_thread in json.dumps(c.get("messages"), default=str) for c in brain.calls)

    async def test_a_server_caller_still_routes_its_outcome_to_its_agent(self, real_database, frontend_sio, sid):
        """The agent's own prompt_builder run (headless, as the run's user) keeps its return address."""
        await self._users(real_database)
        mine = await self._workflow(real_database, CALLER)
        my_thread = f"ck:{mine}:agent:main"
        await self._thread(real_database, my_thread, CALLER, mine)
        request = WorkflowBuilderEditRequest(
            request_id="r1", current_graph=GRAPH, edit_prompt="Tidy this up",
            conversation_id=f"agent-builder:{mine}:agent:{uuid.uuid4().hex[:8]}",
            user_context={"workflow_id": mine, "workflow_name": "Flow", "source": "agent_prompt_builder",
                          "agent_conversation_id": my_thread, "agent_node_id": "agent"},
        )

        with patch("utils.builder_bridge.fire_agent_wake_turn", AsyncMock()) as wake, \
                patch("litellm.acompletion", side_effect=_brain("Done.\n<done/>")):
            await WorkflowBuilderHandler(self.main_api_sio).edit_workflow("", request, caller_user_id=CALLER)
            await drain_spawned_tasks()

        assert wake.await_count == 1
        assert "builder_result" in (await self._row(real_database, my_thread))["events"][-1]

    # ── threads the server mints ─────────────────────────────────────────

    @pytest.mark.parametrize("kind", ["agent_thread", "coordinator"])
    async def test_a_client_cannot_start_a_thread_the_server_mints(self, real_database, frontend_sio, sid, kind):
        """An agent's thread for a caller (keyed by their phone number) or an
        account's coordinator: claimed first, the owner's writes would land in
        the claimant's row."""
        await self._users(real_database)
        mine, theirs = await self._workflow(real_database, CALLER), await self._workflow(real_database, OTHER)
        thread = {"agent_thread": f"ck:{theirs}:agent:+15551234567", "coordinator": f"coordinator:{OTHER}"}[kind]

        request, brain = await self._edit(frontend_sio, sid, mine, conversation_id=thread)

        assert self._errors(request.request_id) == [BUILDER_INVALID_CONVERSATION] and brain.calls == []
        assert await self._row(real_database, thread) is None
        # The rightful owner's first write makes the thread theirs.
        from repositories.conversation import ConversationRepo

        await ConversationRepo(real_database.pool).append_chat_event(
            conversation_id=thread, user_id=OTHER, workflow_id=None, node_id=None,
            event={"role": "user", "message": "first"}, label="first", model=None,
        )
        assert (await self._row(real_database, thread))["user_id"] == OTHER

    # ── stopping a run ───────────────────────────────────────────────────

    async def test_a_refused_request_leaves_the_owners_run_stoppable(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        mine = await self._workflow(real_database, CALLER)
        theirs = str(uuid.uuid4())
        await self._thread(real_database, theirs, OTHER)
        their_run = CancelScope()
        register_builder_scope(theirs, their_run)
        try:
            request, _ = await self._edit(frontend_sio, sid, mine, conversation_id=theirs)

            assert self._errors(request.request_id) == [BUILDER_FOREIGN_CONVERSATION]
            assert get_builder_scope(theirs) is their_run and not their_run.cancelled
        finally:
            unregister_builder_scope(theirs, their_run)

    # ── moving a workflow ────────────────────────────────────────────────

    async def _folder(self, db, owner):
        folder_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workflow_folders (id, owner_id, name, path) VALUES ($1::uuid, $2::uuid, $3, $4)",
            folder_id, owner, f"Folder {folder_id[:8]}", f"/{folder_id}",
        )
        return folder_id

    async def _share(self, db, workflow_id, permission):
        await db.execute(
            "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
            "VALUES ('workflow', $1::uuid, 'user', $2::uuid, $3, $4::uuid)", workflow_id, CALLER, permission, OTHER,
        )

    async def _folders(self, db, workflow_id):
        row = await db.fetchrow(
            "SELECT w.folder_id::text AS folder, rs.target_folder_id::text AS share_folder FROM workflows w "
            "LEFT JOIN resource_shares rs ON rs.resource_id = w.id AND rs.target_user_id = $2::uuid "
            "WHERE w.id = $1::uuid", workflow_id, CALLER,
        )
        return row["folder"], row["share_folder"]

    @pytest.mark.parametrize("permission,moves", [("view", None), ("edit", "share"), ("owner", "workflow")])
    async def test_the_builder_moves_a_workflow_by_the_folder_rule(self, real_database, frontend_sio, sid,
                                                                   permission, moves):
        """As workflow_folder:move_workflow: a viewer moves nothing, a person it
        was shared with files their own share, the owner moves the workflow."""
        await self._users(real_database)
        mine = await self._workflow(real_database, CALLER)
        target = await self._workflow(real_database, CALLER if permission == "owner" else OTHER)
        if permission != "owner":
            await self._share(real_database, target, permission)
        folder = await self._folder(real_database, CALLER)

        await self._edit(frontend_sio, sid, mine,
                         replies=(f'<move_workflow id="{target}" folder="{folder}" />', "Done.\n<done/>"))

        assert await self._folders(real_database, target) == {
            None: (None, None), "share": (None, folder), "workflow": (folder, None),
        }[moves]

    # ── session log file names ───────────────────────────────────────────
    # (the open edition's session logger writes no files)
