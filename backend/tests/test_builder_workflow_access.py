"""The AI builder runs only on a workflow its caller may edit.

A builder request names its workflow in ``user_context.workflow_id`` (an edit)
or through its conversation (a resume). Everything the run does is keyed on
what it names: the graph it saves, the conversation it writes, the workflow's
stored outputs and settings it reads, and the org-shared workspace and org pool
its shell runs in. These drive the real socket entry (``workflow:builder:edit``
/ ``workflow:builder:input_response``) against real Postgres, stubbing only the
brain's LLM stream and the sandbox it would boot.
"""

import contextlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices, Usage

from billing.exceptions import OwnerLookupFailed
from billing.plan_limits import NO_OWNER_TO_BILL
from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from wss.handlers.workflow_builder_handler import (
    BUILDER_FOREIGN_CONVERSATION, BUILDER_GATE_UNAVAILABLE, BUILDER_NO_EDIT_ACCESS,
)
from wss.receiver.client_events import WorkflowBuilderEditRequest
from wss.sender import send_event

CALLER = "00000000-0000-4000-8000-0000000000a1"
OTHER = "00000000-0000-4000-8000-0000000000b2"

STORED_GRAPH = {
    "nodes": [{
        "id": "stored_webhook", "type": "trigger-webhook",
        "config": {"label": "Stored webhook"}, "position": {"x": 0, "y": 0},
    }],
    "edges": [],
}
SENT_GRAPH = {
    "nodes": [{
        "id": "sent_webhook", "type": "trigger-webhook",
        "config": {"label": "Sent webhook"}, "position": {"x": 0, "y": 0},
    }],
    "edges": [],
}


@pytest.fixture(autouse=True)
def _brain_key(monkeypatch):
    """The brain's stream is stubbed; an edition that checks for its key before
    a run finds one."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")


def _brain(*replies):
    """The brain's LLM stream: one scripted reply per turn, every call recorded."""
    pending = list(replies)
    calls = []

    async def acompletion(*args, **kwargs):
        calls.append(kwargs)
        text = pending.pop(0) if pending else "<done/>"

        async def stream():
            yield ModelResponseStream(model="test/brain", choices=[
                StreamingChoices(delta=Delta(content=text, role="assistant"))])
            yield ModelResponseStream(
                model="test/brain", choices=[StreamingChoices(delta=Delta(content=None), finish_reason="stop")],
                usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2, cost=0.0))

        return stream()

    acompletion.calls = calls
    return acompletion


@pytest.mark.asyncio
class TestBuilderWorkflowAccess(BaseHandlerTest):

    def get_session_data(self, sid: str):
        return {"sid": sid, "user_id": CALLER, "user_data": {"email": "caller@example.com"}}

    async def _users(self, db):
        for user_id, email in ((CALLER, "caller@example.com"), (OTHER, "other@example.com")):
            await db.execute(
                "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                user_id, email,
            )
            await db.execute(
                "INSERT INTO user_billing (id, subscription_tier) VALUES ($1, 'enterprise') "
                "ON CONFLICT (id) DO UPDATE SET subscription_tier = 'enterprise'",
                user_id,
            )

    async def _workflow(self, db, *, owner=OTHER, organization_id=None):
        await self._users(db)
        workflow_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workflows (id, owner_id, organization_id, name, workflow) "
            "VALUES ($1::uuid, $2::uuid, $3, 'Stored workflow', $4)",
            workflow_id, owner, organization_id, STORED_GRAPH,
        )
        return workflow_id

    async def _org(self, db):
        await self._users(db)
        org_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1::uuid, 'Other org', $2)",
            org_id, f"other-org-{org_id[:8]}",
        )
        await db.execute(
            "INSERT INTO organization_members (organization_id, user_id, role) VALUES ($1::uuid, $2::uuid, 'owner')",
            org_id, OTHER,
        )
        return org_id

    async def _org_share(self, db, workflow_id, org_id):
        """The org share a workflow made in an org gets, and the caller as a member."""
        await db.execute(
            "INSERT INTO organization_members (organization_id, user_id, role) VALUES ($1::uuid, $2::uuid, 'member')",
            org_id, CALLER,
        )
        await db.execute(
            "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by) "
            "VALUES ('workflow', $1::uuid, 'organization', $2::uuid, 'edit', $3::uuid)",
            workflow_id, org_id, OTHER,
        )

    async def _share(self, db, workflow_id, permission):
        await db.execute(
            "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
            "VALUES ('workflow', $1::uuid, 'user', $2::uuid, $3, $4::uuid)",
            workflow_id, CALLER, permission, OTHER,
        )

    async def _paused_conversation(self, db, workflow_id, *, user_id=CALLER):
        conversation_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO conversations (conversation_id, user_id, workflow_id, title, preview, events, pending_ask) "
            "VALUES ($1, $2::uuid, $3::uuid, 'Paused', '', $4::jsonb, $5::jsonb)",
            conversation_id, user_id, workflow_id,
            [{"role": "user", "message": "Tidy this up"},
             {"role": "assistant", "message": "Which channel?", "pending_ask": {"ask_id": "a1", "inputs": []}}],
            {"ask_id": "a1", "inputs": []},
        )
        return conversation_id

    async def _stored_graph(self, db, workflow_id):
        graph = await db.fetchval("SELECT workflow FROM workflows WHERE id = $1::uuid", workflow_id)
        return json.loads(graph) if isinstance(graph, str) else graph

    async def _edit(self, frontend_sio, sid, workflow_id, *, conversation_id=None, replies=("Done.\n<done/>",)):
        request = WorkflowBuilderEditRequest(
            request_id=f"req-{uuid.uuid4().hex[:8]}",
            current_graph=SENT_GRAPH,
            edit_prompt="Tidy this up",
            conversation_id=conversation_id or str(uuid.uuid4()),
            user_context={"workflow_id": workflow_id, "workflow_name": "Named workflow"},
        )
        brain = _brain(*replies)
        with patch("litellm.acompletion", side_effect=brain):
            await send_event(frontend_sio, sid, request)
        return request, brain

    async def _resume(self, frontend_sio, sid, conversation_id):
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        brain = _brain("Done.\n<done/>")
        with patch("litellm.acompletion", side_effect=brain):
            await frontend_sio.emit("workflow:builder:input_response", {
                "request_id": request_id, "conversation_id": conversation_id, "ask_id": "a1",
                "values": {"x": "general"},
            }, to=sid)
        return request_id, brain

    async def _headless_resume(self, conversation_id):
        """A resume with no socket and no request id, as the bridge page, the
        platform API and an agent's builder_respond send one."""
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        brain = _brain("Done.\n<done/>")
        with patch("litellm.acompletion", side_effect=brain):
            await WorkflowBuilderHandler(self.main_api_sio).handle_input_response(
                "", {"conversation_id": conversation_id, "ask_id": "a1", "values": {"x": "general"}},
                caller_user_id=CALLER,
            )
        return brain

    async def _still_waiting(self, db, conversation_id):
        return await db.fetchval(
            "SELECT pending_ask IS NOT NULL FROM conversations WHERE conversation_id = $1", conversation_id,
        )

    def _errors(self, request_id):
        return [
            d.get("error") for _e, d, _t in self.get_main_api_emitted_events("response")
            if isinstance(d, dict) and d.get("request_id") == request_id and d.get("error")
        ]

    # ── whose workflow ───────────────────────────────────────────────────

    async def test_a_stranger_cannot_build_on_another_users_workflow(self, real_database, frontend_sio, sid):
        workflow_id = await self._workflow(real_database)

        request, brain = await self._edit(frontend_sio, sid, workflow_id)

        assert self._errors(request.request_id) == [BUILDER_NO_EDIT_ACCESS]
        assert await self._stored_graph(real_database, workflow_id) == STORED_GRAPH
        # No turn ran, so nothing of the workflow (outputs, settings) reached the brain.
        assert brain.calls == []
        # Nor does the caller's conversation now name the workflow for a later resume or share.
        assert await real_database.fetchval(
            "SELECT workflow_id FROM conversations WHERE conversation_id = $1", request.conversation_id,
        ) is None

    async def test_view_access_is_not_edit_access(self, real_database, frontend_sio, sid):
        workflow_id = await self._workflow(real_database)
        await self._share(real_database, workflow_id, "view")

        request, brain = await self._edit(frontend_sio, sid, workflow_id)

        assert self._errors(request.request_id) == [BUILDER_NO_EDIT_ACCESS]
        assert await self._stored_graph(real_database, workflow_id) == STORED_GRAPH
        assert brain.calls == []

    async def test_not_even_its_owner_builds_on_a_workflow_noclick_runs_itself(self, real_database, frontend_sio, sid):
        workflow_id = await self._workflow(real_database, owner=CALLER)
        await real_database.execute(
            """UPDATE workflows SET settings = '{"system": "your NoClick assistant"}' WHERE id = $1::uuid""",
            workflow_id)

        request, brain = await self._edit(frontend_sio, sid, workflow_id)

        assert self._errors(request.request_id) == [
            "This automation runs your NoClick assistant, so NoClick keeps it: it can't be edited, renamed or deleted."]
        assert await self._stored_graph(real_database, workflow_id) == STORED_GRAPH
        assert brain.calls == []

    async def test_an_editor_builds_and_the_graph_is_saved(self, real_database, frontend_sio, sid):
        workflow_id = await self._workflow(real_database)
        await self._share(real_database, workflow_id, "edit")

        request, brain = await self._edit(frontend_sio, sid, workflow_id)

        assert self._errors(request.request_id) == []
        assert brain.calls
        stored = await self._stored_graph(real_database, workflow_id)
        assert [n["id"] for n in stored["nodes"]] == ["sent_webhook"]

    async def test_the_owner_builds_and_the_graph_is_saved(self, real_database, frontend_sio, sid):
        workflow_id = await self._workflow(real_database, owner=CALLER)

        request, _brain_ = await self._edit(frontend_sio, sid, workflow_id)

        assert self._errors(request.request_id) == []
        stored = await self._stored_graph(real_database, workflow_id)
        assert [n["id"] for n in stored["nodes"]] == ["sent_webhook"]

    async def _edit_with_shell(self, frontend_sio, sid, workflow_id):
        opened = []

        def create_sandbox_runtime(**kwargs):
            opened.append(kwargs)

            async def run_bash(command):
                return {"exit_code": 0, "stdout": "notes.txt\n", "stderr": ""}

            async def close():
                return None

            return SimpleNamespace(run_bash=run_bash, close=close)

        with patch("coder.openai_agent.sandbox.create_sandbox_runtime", side_effect=create_sandbox_runtime):
            request, _brain_ = await self._edit(
                frontend_sio, sid, workflow_id,
                replies=("<bash>ls /workspace</bash>", "Done.\n<done/>"),
            )
        return request, opened

    async def test_the_shell_never_opens_in_another_orgs_workspace(self, real_database, frontend_sio, sid):
        org_id = await self._org(real_database)
        workflow_id = await self._workflow(real_database, organization_id=org_id)

        request, opened = await self._edit_with_shell(frontend_sio, sid, workflow_id)

        assert self._errors(request.request_id) == [BUILDER_NO_EDIT_ACCESS]
        # Neither the org's shared workspace nor its pool (Owner Pays) was reached.
        assert opened == []


    async def test_a_resume_rechecks_the_conversations_workflow(self, real_database, frontend_sio, sid):
        """A paused conversation whose workflow its caller can no longer edit
        (access revoked while it waited on a question) resumes nothing."""
        workflow_id = await self._workflow(real_database)
        conversation_id = await self._paused_conversation(real_database, workflow_id)

        request_id, brain = await self._resume(frontend_sio, sid, conversation_id)

        assert self._errors(request_id) == [BUILDER_NO_EDIT_ACCESS]
        # The resume would have seeded the brain with the stored graph.
        assert brain.calls == []
        assert await self._stored_graph(real_database, workflow_id) == STORED_GRAPH

    async def test_a_headless_resume_rechecks_the_conversations_workflow(self, real_database, frontend_sio, sid):
        workflow_id = await self._workflow(real_database)
        conversation_id = await self._paused_conversation(real_database, workflow_id)

        brain = await self._headless_resume(conversation_id)

        assert brain.calls == []
        assert await self._stored_graph(real_database, workflow_id) == STORED_GRAPH
        assert await self._still_waiting(real_database, conversation_id)

    # ── whose conversation ───────────────────────────────────────────────

    async def test_an_edit_cannot_write_another_users_conversation(self, real_database, frontend_sio, sid):
        workflow_id = await self._workflow(real_database, owner=CALLER)
        theirs = await self._paused_conversation(real_database, None, user_id=OTHER)
        before = await real_database.fetchval("SELECT events FROM conversations WHERE conversation_id = $1", theirs)

        request, brain = await self._edit(frontend_sio, sid, workflow_id, conversation_id=theirs)

        assert self._errors(request.request_id) == [BUILDER_FOREIGN_CONVERSATION]
        assert brain.calls == []
        assert await real_database.fetchval(
            "SELECT events FROM conversations WHERE conversation_id = $1", theirs,
        ) == before

    # ── the credit gate fails closed ─────────────────────────────────────

    # Each way a turn's gate can fail to say yes: it can't read the workflow's
    # organization, its owner, or the payer's usage.
    GATE_FAILURES = ["unreadable_org", "unreadable_owner", "unreadable_usage"]

    async def _gate_failure(self, db, failure):
        """A workflow the caller owns, the context its turn's gate fails in, and
        the refusal the caller gets."""
        if failure in ("unreadable_owner", "ownerless_org"):
            await self._users(db)
            org_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO organizations (id, name, slug) VALUES ($1::uuid, 'Team', $2)", org_id, f"team-{org_id[:8]}",
            )
            workflow_id = await self._workflow(db, owner=CALLER, organization_id=org_id)
            if failure == "ownerless_org":
                # Its owner's account is gone, and with it their membership.
                return workflow_id, contextlib.nullcontext(), NO_OWNER_TO_BILL
            await db.execute(
                "INSERT INTO organization_members (organization_id, user_id, role) VALUES ($1::uuid, $2::uuid, 'owner')",
                org_id, OTHER,
            )
            target = "billing.usage_tracker.usage_tracker.resolve_billing_user_id_strict"
            error = OwnerLookupFailed("Cannot read the owner of organization: pool timeout")
        else:
            workflow_id = await self._workflow(db, owner=CALLER)
            target = {"unreadable_org": "repositories.workflow.WorkflowRepo.get_organization_id",
                      "unreadable_usage": "billing.plan_limits.check_ai_builder_limit"}[failure]
            error = ConnectionError("pool timeout")
        return workflow_id, patch(target, AsyncMock(side_effect=error)), BUILDER_GATE_UNAVAILABLE


    @pytest.mark.parametrize("failure", GATE_FAILURES)
    async def test_a_gate_that_cant_say_yes_refuses_the_edit(self, real_database, frontend_sio, sid, failure):
        workflow_id, failing, refusal = await self._gate_failure(real_database, failure)

        with failing:
            request, brain = await self._edit(frontend_sio, sid, workflow_id)

        assert self._errors(request.request_id) == [refusal]
        assert brain.calls == []
        assert await self._stored_graph(real_database, workflow_id) == STORED_GRAPH

    @pytest.mark.parametrize("failure", GATE_FAILURES)
    async def test_a_gate_that_cant_say_yes_refuses_the_resume(self, real_database, frontend_sio, sid, failure):
        workflow_id, failing, refusal = await self._gate_failure(real_database, failure)
        conversation_id = await self._paused_conversation(real_database, workflow_id)

        with failing:
            request_id, brain = await self._resume(frontend_sio, sid, conversation_id)

        assert self._errors(request_id) == [refusal]
        assert brain.calls == []
        # Still waiting on its question: a later answer resumes it.
        assert await self._still_waiting(real_database, conversation_id)

    @pytest.mark.parametrize("failure", GATE_FAILURES)
    async def test_a_gate_that_cant_say_yes_refuses_a_headless_resume(self, real_database, frontend_sio, sid, failure):
        workflow_id, failing, _refusal = await self._gate_failure(real_database, failure)
        conversation_id = await self._paused_conversation(real_database, workflow_id)

        with failing:
            brain = await self._headless_resume(conversation_id)

        assert brain.calls == []
        assert await self._still_waiting(real_database, conversation_id)


@pytest.mark.asyncio
async def test_a_failed_headless_resume_ends_quietly(monkeypatch):
    """A headless resume has no request to answer, so its failure is logged,
    not raised again from the reply it can't build."""
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(SimpleNamespace())
    monkeypatch.setattr(handler, "_handle_input_response_impl", AsyncMock(side_effect=ConnectionError("pool timeout")))

    await handler.handle_input_response("", {"conversation_id": "c1", "ask_id": "a1"}, caller_user_id=CALLER)
