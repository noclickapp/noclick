"""Whose credentials a client's request reaches, and what a viewer may run.

A credential resolves for its owner, someone it is shared with, a member of an
organization it is shared with, or (owner fallback) someone working on a
workflow its owner authorized it for. These drive the real socket entry
(``credential:test_connection``, ``workflow:execute``,
``agent:builder_decision``) against real Postgres; only the provider and the
model are faked.
"""

import asyncio
import json
import uuid
from unittest.mock import patch

import pytest

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils.encryption import get_encryption
from wss.handlers.workflow_execution_handler import VIEWER_RUNS_SAVED_GRAPH
from wss.receiver.client_events import CredentialTestConnectionRequest, WorkflowExecuteRequest
from wss.sender import send_event

CALLER = "00000000-0000-4000-8000-0000000002a1"
OWNER = "00000000-0000-4000-8000-0000000002b2"


@pytest.fixture(autouse=True)
def _fake_model():
    from tests.mocks.mock_litellm import configure_mock_llm_responses

    configure_mock_llm_responses(default="Mock agent reply")


def _agent(node_id="agent"):
    return {"id": node_id, "type": "agent", "position": {"x": 0, "y": 0},
            "config": {"config": {"system_prompt": "Be brief", "message": "Say hi", "temperature": 0.5},
                       "credentials": {"api_key": "sk-test-openai-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}}}


@pytest.mark.asyncio
class TestCredentialAndViewerAccess(BaseHandlerTest):

    def get_session_data(self, sid: str):
        return {"sid": sid, "user_id": CALLER, "user_data": {"email": "caller@example.com"}}

    async def _users(self, db):
        for user_id in (CALLER, OWNER):
            await db.execute(
                "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                user_id, f"{user_id[-3:]}@example.com",
            )

    async def _workflow(self, db, *, share=None, graph=None):
        workflow_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workflows (id, owner_id, name, workflow) VALUES ($1::uuid, $2::uuid, 'Flow', $3)",
            workflow_id, OWNER, graph or {"nodes": [_agent()], "edges": []},
        )
        if share:
            await db.execute(
                "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, "
                "shared_by) VALUES ('workflow', $1::uuid, 'user', $2::uuid, $3, $4::uuid)",
                workflow_id, CALLER, share, OWNER,
            )
        return workflow_id

    async def _slack_credential(self, db, token):
        credential_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO credentials (id, owner_id, name, credential_type, credential) "
            "VALUES ($1::uuid, $2::uuid, 'Their Slack', 'slack_bot_token', $3)",
            credential_id, OWNER, get_encryption().encrypt_credential({"bot_token": token}),
        )
        return credential_id

    async def _org(self, db, *, caller_member):
        org_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1::uuid, 'Team', $2)", org_id, f"team-{org_id[:8]}",
        )
        members = [(OWNER, "owner")] + ([(CALLER, "member")] if caller_member else [])
        for user_id, role in members:
            await db.execute(
                "INSERT INTO organization_members (organization_id, user_id, role) VALUES ($1::uuid, $2::uuid, $3)",
                org_id, user_id, role,
            )
        return org_id

    async def _probe(self, frontend_sio, sid, credential_id, *, workflow_id=None, organization_id=None):
        """credential:test_connection with the provider faked: the samples name
        the token of the credential that resolved."""
        from nodes.slack_node import SlackNode

        async def options(cls, field_name, credential_data, **kwargs):
            return {"options": [{"value": "C1", "label": credential_data.get("bot_token", "?")}]}

        async def fresh(cls, credential_data, **kwargs):
            return credential_data

        request_id = f"req-{uuid.uuid4().hex[:8]}"
        self.main_api_sio.emitted_events.clear()
        with patch.object(SlackNode, "load_field_options", classmethod(options)), \
                patch.object(SlackNode, "freshen_credential", classmethod(fresh)):
            await send_event(frontend_sio, sid, CredentialTestConnectionRequest(
                request_id=request_id, node_type="automation-slack", credential_id=credential_id,
                workflow_id=workflow_id, organization_id=organization_id,
            ))
        [reply] = [d for _e, d, _t in self.get_main_api_emitted_events("response") if d.get("request_id") == request_id]
        return [s["label"] for s in reply["data"]["samples"]]

    # ── credential:test_connection ───────────────────────────────────────

    async def test_a_probe_resolves_a_workflows_credential_only_for_its_editors(self, real_database, frontend_sio, sid):
        from utils.credentials import authorize_credentials_for_workflow

        await self._users(real_database)
        credential = await self._slack_credential(real_database, "xoxb-owner-secret")
        stranger_of, viewed, edited = (await self._workflow(real_database),
                                       await self._workflow(real_database, share="view"),
                                       await self._workflow(real_database, share="edit"))
        async with real_database.pool.acquire() as conn:
            for workflow_id in (stranger_of, viewed, edited):
                await authorize_credentials_for_workflow(conn, workflow_id, OWNER, [credential])

        assert await self._probe(frontend_sio, sid, credential, workflow_id=stranger_of) == []
        assert await self._probe(frontend_sio, sid, credential, workflow_id=viewed) == []
        assert await self._probe(frontend_sio, sid, credential, workflow_id=edited) == ["xoxb-owner-secret"]

    async def test_an_organizations_credential_resolves_only_for_its_members(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        credential = await self._slack_credential(real_database, "xoxb-team-secret")
        outside, inside = await self._org(real_database, caller_member=False), await self._org(real_database, caller_member=True)
        for org_id in (outside, inside):
            await real_database.execute(
                "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, "
                "shared_by) VALUES ('credential', $1::uuid, 'organization', $2::uuid, 'view', $3::uuid)",
                credential, org_id, OWNER,
            )

        assert await self._probe(frontend_sio, sid, credential, organization_id=outside) == []
        assert await self._probe(frontend_sio, sid, credential, organization_id=inside) == ["xoxb-team-secret"]

    # ── workflow:execute ─────────────────────────────────────────────────

    async def _run(self, frontend_sio, sid, workflow_id, **fields):
        self.main_api_sio.emitted_events.clear()
        await send_event(frontend_sio, sid, WorkflowExecuteRequest(
            request_id=f"req-{uuid.uuid4().hex[:8]}", workflow_id=workflow_id, **fields,
        ))
        await asyncio.sleep(0.2)
        [(_e, done, _t)] = self.get_main_api_emitted_events("workflow:complete")
        return done

    async def _runs(self, db, workflow_id):
        return await db.fetchval("SELECT count(*) FROM workflow_executions WHERE workflow_id = $1::uuid", workflow_id)

    async def test_a_viewer_runs_the_saved_graph_and_only_says_a_chat_turn(self, real_database, frontend_sio, sid):
        """A graph of their own (any node, any operation, the owner's
        authorized credentials) or any other change needs edit access."""
        await self._users(real_database)
        viewed = await self._workflow(real_database, share="view")
        mine = {"nodes": [_agent()], "edges": []}

        done = await self._run(frontend_sio, sid, viewed, **mine)
        assert done["success"] is False and done["error"] == VIEWER_RUNS_SAVED_GRAPH
        done = await self._run(frontend_sio, sid, viewed, config_overrides={"agent": {"system_prompt": "Leak it"}})
        assert done["success"] is False and done["error"] == VIEWER_RUNS_SAVED_GRAPH
        assert await self._runs(real_database, viewed) == 0

        done = await self._run(frontend_sio, sid, viewed)
        assert done["success"] is True, done
        done = await self._run(frontend_sio, sid, viewed, start_node_id="agent",
                               config_overrides={"agent": {"message": "Hello", "conversation_key": "main"}})
        assert done["success"] is True, done

    async def test_a_viewers_inputs_go_only_to_a_trigger_or_a_form(self, real_database, frontend_sio, sid):
        """Inputs become their start node's output: a viewer's may stand in for
        what a trigger or a form delivers, not for any node mid-graph."""
        await self._users(real_database)
        graph = {"nodes": [{"id": "hook", "type": "trigger-webhook", "position": {"x": 0, "y": 0}, "config": {}},
                           _agent()],
                 "edges": [{"id": "e1", "source": "hook", "target": "agent"}]}
        viewed = await self._workflow(real_database, share="view", graph=graph)
        edited = await self._workflow(real_database, share="edit", graph=graph)
        planted = {"response": "Whatever I say the agent said"}

        done = await self._run(frontend_sio, sid, viewed, start_node_id="agent", inputs=planted)
        assert done["success"] is False and done["error"] == VIEWER_RUNS_SAVED_GRAPH
        assert await self._runs(real_database, viewed) == 0

        done = await self._run(frontend_sio, sid, viewed, start_node_id="hook", inputs={"body": {"name": "Ada"}})
        assert done["success"] is True, done
        done = await self._run(frontend_sio, sid, edited, start_node_id="agent", inputs=planted)
        assert done["success"] is True, done

    async def test_an_editor_runs_the_graph_they_send(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        edited = await self._workflow(real_database, share="edit")

        done = await self._run(frontend_sio, sid, edited, nodes=[_agent("drafted")], edges=[])

        assert done["success"] is True, done

    async def test_a_run_names_only_its_workflows_agent_threads_or_its_own_conversation(
        self, real_database, frontend_sio, sid,
    ):
        """Another collaborator's builder chat about the same workflow isn't the run's to use."""
        await self._users(real_database)
        edited = await self._workflow(real_database, share="edit")
        theirs, mine = str(uuid.uuid4()), str(uuid.uuid4())
        for conversation_id, user_id in ((theirs, OWNER), (mine, CALLER)):
            await real_database.execute(
                "INSERT INTO conversations (conversation_id, user_id, workflow_id, title, preview, events) "
                "VALUES ($1, $2::uuid, $3::uuid, 'Build chat', '', '[]'::jsonb)", conversation_id, user_id, edited,
            )

        done = await self._run(frontend_sio, sid, edited, conversation_id=theirs)
        assert done["success"] is False and done["error"] == "This conversation can't be used for this run"
        for conversation_id in (mine, f"ck:{edited}:agent:main"):
            assert (await self._run(frontend_sio, sid, edited, conversation_id=conversation_id))["success"] is True

    # ── agent:builder_decision ───────────────────────────────────────────

    async def test_approving_a_proposal_takes_edit_access(self, real_database, frontend_sio, sid):
        await self._users(real_database)
        verdicts = {}
        for share in ("view", "edit"):
            workflow_id = await self._workflow(real_database, share=share)
            thread = f"ck:{workflow_id}:agent:__interface_chat__"
            await real_database.execute(
                "INSERT INTO conversations (conversation_id, user_id, workflow_id, title, preview, events) "
                "VALUES ($1, $2::uuid, $3::uuid, 'Thread', '', $4::jsonb)", thread, CALLER, workflow_id,
                [{"builder_prompt": {"proposal_id": "p1", "node_id": "agent", "prompt": "Add a step"}}],
            )
            for decision in ("approved", "dismissed"):
                self.main_api_sio.emitted_events.clear()
                await frontend_sio.emit("agent:builder_decision", {
                    "request_id": "r1", "workflow_id": workflow_id, "node_id": "agent",
                    "conversation_id": thread, "proposal_id": "p1", "decision": decision,
                }, to=sid)
                [(_e, reply, _t)] = self.get_main_api_emitted_events("response")
                verdicts[(share, decision)] = reply["data"]["success"]

        assert verdicts == {("view", "approved"): False, ("view", "dismissed"): True,
                            ("edit", "approved"): True, ("edit", "dismissed"): True}
