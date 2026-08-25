"""
Tests for AgentShareHandler (public agent chat links) and the receiver's
restricted-session gate.

Covers the security contract:
  • manage events are OWNER-only (edit-collaborators can't mint a spend
    capability billed to the owner) and require a real agent node;
  • an anonymous share-scope session can invoke ONLY shared_agent:send /
    shared_agent:resume — every other event is permission_denied at the
    receiver choke point;
  • visitor sends execute server-side as the owner (caller_user_id) with the
    one-shot message/conversation_key override baked in, mockedOutput
    neutralized, and NO graph or model taken from the visitor;
  • resume only ever resolves the visitor's own scope-derived thread.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.utils.base_handler_test import BaseHandlerTest
from wss.receiver.client_events import (
    AgentShareGetOrCreateRequest,
    AgentShareRotateRequest,
    AgentShareSetActiveRequest,
    SharedAgentResumeRequest,
    SharedAgentSendRequest,
)
from wss.receiver.event_routing import EVENT_ROUTING, Handler
from wss.receiver.receiver import SHARED_VISITOR_ALLOWED_EVENTS
from wss.sender import send_event

OWNER_ID = "uuid-test-user"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
LINK_ID = "33333333-3333-3333-3333-333333333333"
WORKFLOW_ID = "44444444-4444-4444-4444-444444444444"
VISITOR_ID = "55555555-5555-5555-5555-555555555555"
NODE_ID = "agent-1"

GRAPH = {
    "nodes": [
        {"id": NODE_ID, "type": "agent", "data": {"label": "Support Bot"},
         "config": {"model": "opencode", "mockedOutput": {"stale": True}}},
        {"id": "http-1", "type": "automation-http", "config": {}},
    ],
    "edges": [],
}


def _link_row(**overrides):
    row = {
        "id": LINK_ID,
        "user_id": OWNER_ID,
        "workflow_id": WORKFLOW_ID,
        "node_id": NODE_ID,
        "is_active": True,
        "workflow_config": GRAPH,
        "organization_id": None,
        "workflow_name": "Agent Flow",
        "owner_id": OWNER_ID,
    }
    row.update(overrides)
    return row


class FakeLinkRepo:
    """Configurable stand-in for SharedAgentLinkRepo (class-level knobs)."""
    visit_row = None
    touched = []

    def __init__(self, pool):
        pass

    async def load_for_visit(self, link_id):
        return type(self).visit_row

    async def get_or_create(self, user_id, workflow_id, node_id):
        return {"link_id": LINK_ID, "is_active": True}

    async def rotate(self, user_id, workflow_id, node_id):
        return {"link_id": "66666666-6666-6666-6666-666666666666", "is_active": True}

    async def set_active(self, workflow_id, node_id, is_active):
        return True

    async def touch_usage(self, link_id):
        type(self).touched.append(link_id)


class FakeWorkflowRepo:
    """Owner + stored-graph stand-in for the manage-path authorization."""
    owner_id = OWNER_ID
    graph = GRAPH

    def __init__(self, pool):
        pass

    async def get_owner_id(self, workflow_id, **kwargs):
        return type(self).owner_id

    async def get_workflow_org_and_data(self, conn, workflow_id):
        return {"workflow": type(self).graph, "organization_id": None, "settings": {}}


class FakeConversationRepo:
    resume_calls = []
    resume_row = {"events": [{"role": "user", "message": "hi"}], "workflow_id": WORKFLOW_ID}

    def __init__(self, pool):
        pass

    async def get_for_resume(self, conversation_id, user_id):
        type(self).resume_calls.append((conversation_id, user_id))
        return type(self).resume_row


class FakeInflightRedis:
    """set(nx)/delete double for the per-thread in-flight dispatch lock."""

    def __init__(self):
        self.store = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture(autouse=True)
def _patch_agent_share_deps(monkeypatch):
    """Route the handler's repo/redis/pool seams to configurable fakes."""
    from tests.mocks.mock_asyncpg import MockNativePool

    FakeLinkRepo.visit_row = _link_row()
    FakeLinkRepo.touched = []
    FakeWorkflowRepo.owner_id = OWNER_ID
    FakeWorkflowRepo.graph = GRAPH
    FakeConversationRepo.resume_calls = []
    monkeypatch.setattr("wss.handlers.agent_share_handler.SharedAgentLinkRepo", FakeLinkRepo)
    monkeypatch.setattr("wss.handlers.agent_share_handler.WorkflowRepo", FakeWorkflowRepo)
    monkeypatch.setattr("wss.handlers.agent_share_handler.ConversationRepo", FakeConversationRepo)
    # All SQL goes through the fake repos; the pool itself is a constructible
    # double so these tests never depend on a live/initialized DB pool (CI
    # runs without lifespan startup — a real get_pool() raises there).
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: MockNativePool({}))
    # No Redis in unit tests — the in-flight lock fails open by design.
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: None)
    yield


class TestAgentShareManage(BaseHandlerTest):
    """Owner-side mint / rotate / toggle (normal authenticated session)."""

    def _responses(self):
        return [e[1] for e in self.get_main_api_emitted_events("response")]

    @pytest.mark.asyncio
    async def test_owner_can_mint_link(self, frontend_sio, sid):
        await send_event(frontend_sio, sid, AgentShareGetOrCreateRequest(
            request_id="r1", workflow_id=WORKFLOW_ID, node_id=NODE_ID))
        await asyncio.sleep(0.05)
        data = self._responses()[0]["data"]
        assert data["success"] is True
        assert data["link_id"] == LINK_ID
        assert data["url"].endswith(f"/a/{LINK_ID}")
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_non_owner_denied(self, frontend_sio, sid):
        """A session that is NOT the workflow owner (e.g. an edit collaborator)
        must not be able to publish a link billed to the owner."""
        FakeWorkflowRepo.owner_id = OTHER_USER_ID
        await send_event(frontend_sio, sid, AgentShareGetOrCreateRequest(
            request_id="r2", workflow_id=WORKFLOW_ID, node_id=NODE_ID))
        await asyncio.sleep(0.05)
        data = self._responses()[0]["data"]
        assert data["success"] is False
        assert "owner" in (data["error"] or "").lower()
        assert data["link_id"] is None

    @pytest.mark.asyncio
    async def test_non_agent_node_denied(self, frontend_sio, sid):
        await send_event(frontend_sio, sid, AgentShareGetOrCreateRequest(
            request_id="r3", workflow_id=WORKFLOW_ID, node_id="http-1"))
        await asyncio.sleep(0.05)
        data = self._responses()[0]["data"]
        assert data["success"] is False
        assert "agent" in (data["error"] or "").lower()

    @pytest.mark.asyncio
    async def test_rotate_returns_fresh_capability(self, frontend_sio, sid):
        await send_event(frontend_sio, sid, AgentShareRotateRequest(
            request_id="r4", workflow_id=WORKFLOW_ID, node_id=NODE_ID))
        await asyncio.sleep(0.05)
        data = self._responses()[0]["data"]
        assert data["success"] is True
        assert data["link_id"] != LINK_ID

    @pytest.mark.asyncio
    async def test_set_active_round_trips(self, frontend_sio, sid):
        await send_event(frontend_sio, sid, AgentShareSetActiveRequest(
            request_id="r5", workflow_id=WORKFLOW_ID, node_id=NODE_ID, is_active=False))
        await asyncio.sleep(0.05)
        data = self._responses()[0]["data"]
        assert data["success"] is True


class TestSharedAgentVisitor(BaseHandlerTest):
    """Visitor events on a restricted share-scope session (no user_id)."""

    def get_session_data(self, sid):
        return {
            "sid": sid,
            "share_scope": {
                "link_id": LINK_ID,
                "workflow_id": WORKFLOW_ID,
                "node_id": NODE_ID,
                "owner_id": OWNER_ID,
                "organization_id": None,
                "visitor_id": VISITOR_ID,
            },
        }

    def _responses(self):
        return [e[1] for e in self.get_main_api_emitted_events("response")]

    def _capture_execute(self):
        fake_exec = MagicMock()
        fake_exec.handle_execute = AsyncMock(return_value=MagicMock())
        handler = self.handlers[Handler.AGENT_SHARE]
        handler._get_execution_handler = lambda: fake_exec
        return fake_exec

    @pytest.mark.asyncio
    async def test_send_executes_as_owner_with_server_built_override(self, frontend_sio, sid):
        fake_exec = self._capture_execute()
        await send_event(frontend_sio, sid, SharedAgentSendRequest(
            request_id="v1", text="hello there"))
        await asyncio.sleep(0.05)

        ack = self._responses()[0]["data"]
        expected_ck = f"share:{LINK_ID}:{VISITOR_ID}:main"
        expected_cid = f"ck:{WORKFLOW_ID}:{NODE_ID}:{expected_ck}"
        assert ack["accepted"] is True
        assert ack["conversation_id"] == expected_cid

        assert fake_exec.handle_execute.await_count == 1
        kwargs = fake_exec.handle_execute.await_args.kwargs
        # Billing + credentials + credit gates all key off the OWNER.
        assert kwargs["caller_user_id"] == OWNER_ID
        # Chat frames stream direct to the visitor's sid.
        assert kwargs["sid"] == sid
        request = kwargs["request"]
        assert request.trigger_source == "shared_agent"
        assert request.start_node_id == NODE_ID
        # DB-fetch mode: the visitor supplies NO graph.
        assert request.nodes is None and request.edges is None
        override = request.config_overrides[NODE_ID]
        assert override["message"] == "hello there"
        assert override["conversation_key"] == expected_ck
        # A stale canvas mock must never replay to a visitor.
        assert override["mockedOutput"] is None
        assert "model" not in override
        assert FakeLinkRepo.touched == [LINK_ID]

    @pytest.mark.asyncio
    async def test_send_rejected_when_link_revoked(self, frontend_sio, sid):
        """Rotate/deactivate applies to already-connected sockets on next send."""
        FakeLinkRepo.visit_row = None
        fake_exec = self._capture_execute()
        await send_event(frontend_sio, sid, SharedAgentSendRequest(request_id="v2", text="hi"))
        await asyncio.sleep(0.05)
        ack = self._responses()[0]["data"]
        assert ack["accepted"] is False
        assert ack["error"] == "link_inactive"
        assert fake_exec.handle_execute.await_count == 0

    @pytest.mark.asyncio
    async def test_send_rejected_when_agent_disabled(self, frontend_sio, sid):
        disabled_graph = {
            "nodes": [{"id": NODE_ID, "type": "agent", "config": {"disabled": True}}],
            "edges": [],
        }
        FakeLinkRepo.visit_row = _link_row(workflow_config=disabled_graph)
        fake_exec = self._capture_execute()
        await send_event(frontend_sio, sid, SharedAgentSendRequest(request_id="v3", text="hi"))
        await asyncio.sleep(0.05)
        ack = self._responses()[0]["data"]
        assert ack["accepted"] is False
        assert ack["error"] == "agent_unavailable"
        assert fake_exec.handle_execute.await_count == 0

    @pytest.mark.asyncio
    async def test_send_waits_for_inflight_lock_instead_of_instant_busy(
        self, frontend_sio, sid, monkeypatch,
    ):
        """The lock only covers the previous send's DISPATCH tail — a visitor who
        reads the reply and sends again lands inside it. The handler must wait
        the lock out (bounded), not reject (2026-07-18 spurious-busy incident)."""
        redis = FakeInflightRedis()
        lock_key = f"nc:shared:inflight:ck:{WORKFLOW_ID}:{NODE_ID}:share:{LINK_ID}:{VISITOR_ID}:main"
        await redis.set(lock_key, "1", nx=True)
        monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
        monkeypatch.setattr("wss.handlers.agent_share_handler._INFLIGHT_POLL_SECONDS", 0.02)
        monkeypatch.setattr("wss.handlers.agent_share_handler._INFLIGHT_WAIT_SECONDS", 1.0)
        fake_exec = self._capture_execute()

        async def release_soon():
            await asyncio.sleep(0.15)
            await redis.delete(lock_key)

        release = asyncio.ensure_future(release_soon())
        await send_event(frontend_sio, sid, SharedAgentSendRequest(request_id="v5", text="again"))
        await asyncio.sleep(0.5)
        await release
        ack = self._responses()[0]["data"]
        assert ack["accepted"] is True
        assert fake_exec.handle_execute.await_count == 1
        # The handler's finally released its own acquisition.
        assert lock_key not in redis.store

    @pytest.mark.asyncio
    async def test_send_busy_only_after_bounded_wait(self, frontend_sio, sid, monkeypatch):
        """A lock that never frees (genuinely overlapping dispatch) still gets a
        busy ack — after the wait window, never instantly."""
        redis = FakeInflightRedis()
        lock_key = f"nc:shared:inflight:ck:{WORKFLOW_ID}:{NODE_ID}:share:{LINK_ID}:{VISITOR_ID}:main"
        await redis.set(lock_key, "1", nx=True)
        monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
        monkeypatch.setattr("wss.handlers.agent_share_handler._INFLIGHT_POLL_SECONDS", 0.02)
        monkeypatch.setattr("wss.handlers.agent_share_handler._INFLIGHT_WAIT_SECONDS", 0.3)
        fake_exec = self._capture_execute()

        await send_event(frontend_sio, sid, SharedAgentSendRequest(request_id="v6", text="hi"))
        await asyncio.sleep(0.6)
        ack = self._responses()[0]["data"]
        assert ack["accepted"] is False
        assert ack["error"] == "busy"
        assert fake_exec.handle_execute.await_count == 0
        # The foreign lock is left alone — only the acquirer releases.
        assert lock_key in redis.store

    @pytest.mark.asyncio
    async def test_resume_is_scope_derived_and_owner_scoped(self, frontend_sio, sid):
        """The visitor can only ever read the thread derived from their own
        session scope — a client-supplied conversation id has no channel in."""
        await send_event(frontend_sio, sid, SharedAgentResumeRequest(
            request_id="v4", chat_key="abc123"))
        await asyncio.sleep(0.05)
        data = self._responses()[0]["data"]
        expected_cid = f"ck:{WORKFLOW_ID}:{NODE_ID}:share:{LINK_ID}:{VISITOR_ID}:abc123"
        assert data["conversation_id"] == expected_cid
        assert data["messages"] == FakeConversationRepo.resume_row["events"]
        assert FakeConversationRepo.resume_calls == [(expected_cid, OWNER_ID)]


class TestRestrictedSessionGate(BaseHandlerTest):
    """The receiver-level allowlist for share-scope sessions."""

    def get_session_data(self, sid):
        return {
            "sid": sid,
            "share_scope": {
                "link_id": LINK_ID,
                "workflow_id": WORKFLOW_ID,
                "node_id": NODE_ID,
                "owner_id": OWNER_ID,
                "organization_id": None,
                "visitor_id": VISITOR_ID,
            },
        }

    @pytest.mark.asyncio
    async def test_every_non_allowlisted_event_is_denied(self, frontend_sio, sid):
        """Loop the ENTIRE routing table: a restricted session may reach only
        the two shared_agent events. Everything else — workflow execute/save,
        credentials, billing, yjs, org admin — is permission_denied before any
        handler sees it."""
        denied, leaked = 0, []
        for event in EVENT_ROUTING["API"]:
            if event in SHARED_VISITOR_ALLOWED_EVENTS:
                continue
            result = await self.proxy._route_event_impl(event, sid, {"request_id": "g"})
            if isinstance(result, dict) and result.get("error") == "permission_denied":
                denied += 1
            else:
                leaked.append(event)
        assert not leaked, f"events reachable from a restricted session: {leaked}"
        assert denied == len(EVENT_ROUTING["API"]) - len(SHARED_VISITOR_ALLOWED_EVENTS)

    @pytest.mark.asyncio
    async def test_allowlisted_events_pass_the_gate(self, frontend_sio, sid):
        """The two shared_agent events reach validation/dispatch (a payload
        failing Pydantic proves the gate let it through)."""
        result = await self.proxy._route_event_impl("shared_agent:send", sid, {"text": ""})
        assert isinstance(result, dict) and result.get("error") == "validation_error"
        result = await self.proxy._route_event_impl(
            "shared_agent:send", sid, {"text": "hi", "chat_key": "bad key!"})
        assert isinstance(result, dict) and result.get("error") == "validation_error"
        # A valid resume dispatches to the handler (returns None, not a gate error).
        result = await self.proxy._route_event_impl("shared_agent:resume", sid, {"request_id": "g2"})
        assert not (isinstance(result, dict) and result.get("error") == "permission_denied")


class TestNormalSessionUnaffected(BaseHandlerTest):
    """A regular authenticated session must NOT trip the share gate."""

    @pytest.mark.asyncio
    async def test_normal_session_passes_gate(self, frontend_sio, sid):
        result = await self.proxy._route_event_impl(
            "conversation:resume", sid, {"session_id": "ck:x:y:z", "request_id": "n1"})
        assert not (isinstance(result, dict) and (result or {}).get("error") == "permission_denied")
