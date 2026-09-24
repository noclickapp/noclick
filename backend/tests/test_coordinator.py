"""
The account coordinator: one agent per account over existing seams.

Tools are judged on what they hand the seams (the builder request carries the
owner as caller_user_id, describe refuses a workflow the user cannot see, a
parked ask reuses its pending link) and on what they return; the turn runner
on serialization and persistence; the handler through the real receiver
routing, gated on the coordinator rollout.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from coder.coordinator import agent as coordinator
from coder.coordinator import tools as coordinator_tools
from coder.coordinator.tools import (
    COORDINATOR_NODE_ID, CoordinatorTools, bounded, coordinator_tool_params,
)
from tests.mocks.mock_asyncpg import MockNativePool
from utils import capabilities
from utils.account_link import Verified
from utils.capabilities import OWNER_MESSAGE
from tests.utils.base_handler_test import BaseHandlerTest
from utils import feature_gates
from wss.receiver.client_events import (
    CoordinatorOpenRequest, CoordinatorResetRequest, CoordinatorSendRequest,
    CoordinatorMemoriesListRequest, CoordinatorMemoryGetRequest, CoordinatorMemorySaveRequest,
    CoordinatorMemoryDeleteRequest,
)
from wss.sender import send_event
from wss.sender.events import ChatMessageEvent

USER = "11111111-1111-1111-1111-111111111111"
ORG = "22222222-2222-2222-2222-222222222222"
WORKFLOW = "33333333-3333-3333-3333-333333333333"
CID = f"coordinator:{USER}"


def tools(pool=None, org=ORG):
    return CoordinatorTools(pool=pool or MockNativePool(), sio=object(), user_id=USER, organization_id=org, conversation_id=CID)


# ── tool surface ─────────────────────────────────────────────────────────────

def test_tool_params_are_the_sdk_shape_and_match_the_dispatcher():
    t = tools()
    params = t.tool_params()
    names = {p["function"]["name"] for p in params}
    assert names == set(t._tools)
    assert {"trash_workflow", "restore_workflow"} <= names
    for p in params:
        assert p["type"] == "function" and p["function"]["description"]
        schema = p["function"]["parameters"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])


def test_bounded_caps_lists_clips_strings_and_keeps_keys():
    payload = {"runs": [{"id": f"r{i}", "note": "x" * 1000} for i in range(30)], "deep": {"a": {"b": {"c": {"d": 1}}}}}
    out = bounded(payload, max_items=3, max_chars=20, depth=4)
    assert len(out["runs"]) == 4 and out["runs"][-1] == "… 27 more"
    assert out["runs"][0]["id"] == "r0" and len(out["runs"][0]["note"]) == 20
    assert out["deep"]["a"]["b"]["c"] == "…"


async def test_execute_dispatches_never_raises_and_audits():
    t = tools()
    with patch("coder.coordinator.tools.record_tool_call") as audit:
        unknown = await t.execute("nope", {})
        assert unknown == {"success": False, "error": "unknown tool: nope"}
        bad_args = await t.execute("describe_workflow", {"nonsense": 1})
        assert bad_args["success"] is False and "bad arguments" in bad_args["error"]
        t._tools["account_overview"] = AsyncMock(side_effect=RuntimeError("boom"))
        failed = await t.execute("account_overview", {"section": "all"})
        assert failed == {"success": False, "error": "boom"}
    kinds = [(c.kwargs["tool_name"], c.kwargs["result_status"], c.kwargs["agent_node_id"], c.kwargs["conversation_id"])
             for c in audit.call_args_list]
    assert kinds == [("nope", "error", COORDINATOR_NODE_ID, CID), ("describe_workflow", "error", COORDINATOR_NODE_ID, CID),
                     ("account_overview", "error", COORDINATOR_NODE_ID, CID)]


async def test_find_agents_reads_both_graph_shapes_and_filters_by_purpose():
    rows = [{"id": WORKFLOW, "name": "Operations", "workflow": {"nodes": [
        {"id": "a", "type": "agent", "config": {"label": "Researcher", "goal": "Market research", "model": "codex"}},
        {"id": "b", "type": "agent", "data": {"label": "Writer", "goal": "Market briefs", "config": {"model": "claude-code"}}},
        {"id": "c", "type": "trigger-run", "config": {"label": "Market event"}},
    ]}}]
    with patch("repositories.dashboard.DashboardRepo.list_workflows", AsyncMock(return_value=rows)):
        out = await tools().find_agents("market")
        assert [a["node_id"] for a in out["agents"]] == ["a", "b"]
        assert out["agents"][1]["purpose"] == "Market briefs"
        assert (await tools().find_agents("unknown"))["agents"] == []


async def test_agent_message_preserves_followup_and_reply_channel():
    t = tools()
    t.reply_channel = "whatsapp_text"
    request = AsyncMock(return_value={"success": True, "job": {"status": "queued"}})
    with patch("coder.coordinator.tasks.request_agent_message", request):
        out = await t.message_agent(WORKFLOW, "agent", "Continue", reply_to_job_id="previous")
    assert out["job"]["status"] == "queued"
    assert request.call_args.kwargs == dict(user_id=USER, workflow_id=WORKFLOW, node_id="agent", message="Continue",
                                           send_to_phone=True, reply_to_job_id="previous", continuation=None)


async def test_account_overview_is_the_dashboard_aggregate_bounded():
    big = {"workspace": {"name": "W"}, "generatedAt": "t", "errors": {},
           "attention": [{"id": i, "title": "x" * 500} for i in range(40)], "runs": {"recent": [1, 2, 3]}}
    with patch("wss.handlers.dashboard_handler.build_overview", AsyncMock(return_value=big)) as build:
        full = await tools().account_overview()
        only = await tools().account_overview(section="attention")
        bad = await tools().account_overview(section="nope")
    build.assert_awaited()
    assert build.await_args.args[1] == USER
    assert len(full["overview"]["attention"]) == 11 and len(full["overview"]["attention"][0]["title"]) == 280
    assert set(only["overview"]) == {"attention", "workspace", "generatedAt", "errors"}
    assert bad["success"] is False


async def test_list_workflows_is_the_builders_listing_in_org_context():
    rows = [{"id": WORKFLOW, "name": "Inbox", "description": None, "updated_at": datetime(2026, 9, 17, tzinfo=timezone.utc)}]
    with patch("coder.coordinator.tools.WorkflowRepo.list_workflows_builder", AsyncMock(return_value=rows)) as listing:
        result = await tools().list_workflows(query="in")
    assert result["workflows"] == [{"id": WORKFLOW, "name": "Inbox", "description": None, "updated_at": "2026-09-17T00:00:00+00:00"}]
    kwargs = listing.await_args.kwargs
    assert str(kwargs["user_id"]) == USER and str(kwargs["organization_id"]) == ORG and kwargs["query"] == "in"


async def test_describe_refuses_what_the_user_cannot_see_then_delegates():
    t = tools()
    with patch("wss.handlers.workflow_execution_handler.WorkflowExecutionHandler._fetch_workflow", AsyncMock(return_value=None)):
        assert (await t.describe_workflow(WORKFLOW))["success"] is False
    assert (await t.describe_workflow("not-a-uuid"))["success"] is False
    described = {"success": True, "workflow_name": "Inbox", "your_node_id": None, "snapshot": "<w/>"}
    with patch("wss.handlers.workflow_execution_handler.WorkflowExecutionHandler._fetch_workflow", AsyncMock(return_value=([], [], None, {}, {}))), \
         patch("nodes.agent.platform_tools.describe_workflow_impl", AsyncMock(return_value=dict(described))) as impl:
        result = await t.describe_workflow(WORKFLOW, focus="n1")
    assert result == {"success": True, "workflow_name": "Inbox", "snapshot": "<w/>"}
    assert impl.await_args.kwargs["node_id"] is None and impl.await_args.kwargs["focus"] == "n1"


async def test_request_build_delegates_to_the_builder_service():
    t = tools()
    row = {"id": "req", "kind": "build", "workflow_id": WORKFLOW, "conversation_key": "builder-request:req",
           "status": "queued", "phase": "building", "pending_ask": None, "result": None, "error": None,
           "send_to_phone": False, "phone_state": None, "delivery_error": None,
           "spec": {"instructions": "Add a Slack alert"}}
    with patch("coder.workflow.requests.submit_request", AsyncMock(return_value=row)) as submit:
        result = await t.request_build("Add a Slack alert", workflow_id=WORKFLOW)
    assert result["status"] == "queued" and result["job_id"] == "req"
    assert result["publication_status"] == "not_requested"
    assert submit.await_args.kwargs["instructions"] == "Add a Slack alert"
    assert submit.await_args.kwargs["reply_conversation_id"] == CID
    assert submit.await_args.kwargs["origin"] == {"source": "coordinator", "coordinator_conversation_id": CID}


async def test_job_status_reports_durable_state_and_reuses_the_answer_link():
    ask = {"ask_id": "ask-1", "inputs": [{"id": "q1", "label": "Which channel?", "type": "text"}]}
    row = {"id": "req", "kind": "build", "workflow_id": WORKFLOW, "conversation_key": "builder-request:req",
           "status": "waiting", "phase": "building", "pending_ask": ask, "result": None, "error": None,
           "send_to_phone": False, "phone_state": None, "delivery_error": None, "spec": {"instructions": "x"}}
    t = tools()
    with patch("repositories.coordinator_jobs.CoordinatorJobRepo.list_for_user", AsyncMock(return_value=[row])) as listing, \
         patch("coder.coordinator.tools.BuilderBridgeRepo.find_pending_for_ask", AsyncMock(return_value="link-1")), \
         patch("coder.coordinator.tools.create_bridge_link_for_ask", AsyncMock()) as mint:
        result = await t.job_status(kind="build")
    assert listing.await_args.kwargs["kind"] == "build"
    build = result["jobs"][0]
    assert build["kind"] == "build" and build["status"] == "waiting" and build["phase"] == "building"
    assert build["waiting_for"]["questions"] == ["Which channel?"]
    assert build["waiting_for"]["answer_url"].endswith("/b/link-1")
    mint.assert_not_awaited()
    with patch("repositories.coordinator_jobs.CoordinatorJobRepo.list_for_user", AsyncMock(return_value=[row])), \
         patch("coder.coordinator.tools.BuilderBridgeRepo.find_pending_for_ask", AsyncMock(return_value=None)), \
         patch("coder.coordinator.tools.create_bridge_link_for_ask",
               AsyncMock(return_value={"link_id": "new", "url": "https://x/b/new", "questions": ["Which channel?"], "inputs": []})) as mint:
        result = await t.job_status()
    assert result["jobs"][0]["waiting_for"]["answer_url"] == "https://x/b/new"
    assert mint.await_args.kwargs["ask_id"] == "ask-1" and mint.await_args.kwargs["user_id"] == USER


# ── the turn runner ──────────────────────────────────────────────────────────

class FakeAgent:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @classmethod
    async def create(cls, **kwargs):
        return cls(**kwargs)

    async def __call__(self, message):
        FakeAgent.calls.append(("start", self.kwargs["user_id"], message["content_items"][0].text))
        await asyncio.sleep(0.01)
        await self.kwargs["emit_message"](ChatMessageEvent(
            conversation_id=self.kwargs["conversation_id"],
            message=f"reply:{message['content_items'][0].text}", finished=True,
        ))
        FakeAgent.calls.append(("end", self.kwargs["user_id"]))

    async def cleanup(self):
        FakeAgent.calls.append(("cleanup", self.kwargs["user_id"]))


class FakeChat:
    persisted = []

    def __init__(self, sio):
        pass

    async def _create_emit_callback(self, sid, model, *, conversation_id, user_id, workflow_id, node_id=None, extra=None):
        async def emit(event):
            FakeChat.persisted.append(("emit", conversation_id, node_id, event, extra))
        return emit

    async def _persist_chat_event(self, **kw):
        FakeChat.persisted.append(("user", kw["conversation_id"], kw["node_id"], kw["content"], kw.get("extra")))


@asynccontextmanager
async def fake_coordinator_lock(pool, user_id, **kwargs):
    yield AsyncMock()


@pytest.fixture
def turn_seams(monkeypatch):
    monkeypatch.setattr(coordinator, "coordinator_lock", fake_coordinator_lock)
    monkeypatch.setattr(coordinator.CoordinatorWakeupRepo, "epoch", AsyncMock(return_value=""))
    FakeAgent.calls.clear()
    FakeChat.persisted.clear()
    monkeypatch.setattr(coordinator, "Agent", FakeAgent)
    monkeypatch.setattr(coordinator, "AgentHandler", FakeChat)
    monkeypatch.setattr(coordinator, "get_native_pool", lambda: MockNativePool())
    monkeypatch.setattr(coordinator, "get_user_org_context", AsyncMock(return_value=ORG))


async def test_turn_builds_the_agent_on_the_account_and_persists_both_sides(turn_seams):
    await coordinator.run_coordinator_turn(sio=object(), sid="sid-1", user_id=USER, user_email="a@b.c", text="hi")
    assert FakeAgent.calls == [("start", USER, "hi"), ("end", USER), ("cleanup", USER)]
    persisted = FakeChat.persisted  # persisted in order: user turn first, then the emitted reply
    assert persisted[0] == ("user", CID, COORDINATOR_NODE_ID, "hi", None)
    assert persisted[1][:3] == ("emit", CID, COORDINATOR_NODE_ID) and persisted[1][3].message == "reply:hi"


async def test_turn_wires_persistence_tools_and_billing_identity(turn_seams, monkeypatch):
    captured = {}
    orig_create = FakeAgent.create

    async def create(cls, **kwargs):
        captured.update(kwargs)
        return await orig_create(**kwargs)
    monkeypatch.setattr(FakeAgent, "create", classmethod(create))
    await coordinator.run_coordinator_turn(sio="SIO", sid="sid-1", user_id=USER, user_email=None, text="hi")
    assert captured["conversation_id"] == CID and captured["enable_persistence"] is True
    assert captured["user_id"] == USER and captured["organization_id"] == ORG and captured["sio"] == "SIO"
    assert callable(captured["custom_tool_executor"])
    config = captured["config"]
    assert config.llm.model == coordinator.COORDINATOR_MODEL
    assert config.settings.system_prompt.startswith(coordinator.SYSTEM_PROMPT)
    assert "Current UTC time:" in config.settings.system_prompt
    assert callable(captured["call_model_input_filter"])
    assert captured.get("history_limit") is None
    # An account with no email (made by a WhatsApp first contact) can connect one.
    names = config.capabilities.custom_tool_names
    assert names == [t["function"]["name"] for t in tools().tool_params()] + ["connect_account", "confirm_connect_code"]
    assert not config.capabilities.enable_cmd and not config.capabilities.enable_mcp

    await coordinator.run_coordinator_turn(sio="SIO", sid="sid-1", user_id=USER, user_email="a@b.c", text="hi")
    assert captured["config"].capabilities.custom_tool_names == [t["function"]["name"] for t in tools().tool_params()]


async def test_a_verified_connect_code_moves_the_account_after_the_turn_is_saved(turn_seams, monkeypatch):
    order = []

    class FakeLink:
        def __init__(self, pool):
            pass

        async def verify(self, user_id, code):
            order.append(("verify", user_id, code))
            return Verified(email="ada@example.com", merges=True)

        async def complete(self, user_id):
            order.append(("complete", user_id, [p[0] for p in FakeChat.persisted]))
            return "target-user"
    monkeypatch.setattr(coordinator_tools, "AccountLink", FakeLink)
    monkeypatch.setattr(coordinator, "AccountLink", FakeLink)

    class ConnectingAgent(FakeAgent):
        async def __call__(self, message):
            result = await self.kwargs["custom_tool_executor"]("confirm_connect_code", {"code": "123456"})
            assert result["joins_existing_account"] is True and "ada@example.com" in result["outcome"]
            await super().__call__(message)
    monkeypatch.setattr(coordinator, "Agent", ConnectingAgent)
    await coordinator.run_coordinator_turn(sio=None, sid="", user_id=USER, user_email=None, text="it's 123456")
    # The reply was persisted into this account's thread before the thread moved.
    assert order == [("verify", USER, "123456"), ("complete", USER, ["user", "emit"])]

    order.clear()
    monkeypatch.setattr(coordinator, "Agent", FakeAgent)
    await coordinator.run_coordinator_turn(sio=None, sid="", user_id=USER, user_email=None, text="hi")
    assert order == []  # no code, no move


@pytest.mark.parametrize("channel", ["web", "voice", "whatsapp_text"])
async def test_each_transport_loads_retrieval_headers_into_the_turn(turn_seams, monkeypatch, channel):
    captured = {}
    original = FakeAgent.create

    async def create(cls, **kwargs):
        captured.update(kwargs)
        return await original(**kwargs)

    monkeypatch.setattr(FakeAgent, "create", classmethod(create))
    monkeypatch.setattr("repositories.coordinator_memories.CoordinatorMemoryRepo.list_headers", AsyncMock(return_value={
        "memories": [{"id": WORKFLOW, "name": "release-process", "description": "Consult before preparing a release.",
                      "memory_type": "feedback", "origin_conversation_id": CID}], "has_more": False,
    }))
    await coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email=None,
                                           text="What next?", extra={"channel": channel})
    prompt = captured["config"].settings.system_prompt
    assert "Consult before preparing a release." in prompt
    assert "read_memory" in prompt and CID in prompt
    assert "voice" != channel or "phone call" in prompt


async def test_turns_of_one_account_never_interleave(turn_seams):
    await asyncio.gather(
        coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email=None, text="one"),
        coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email=None, text="two"),
    )
    starts_ends = [c[0] for c in FakeAgent.calls if c[0] in ("start", "end")]
    assert starts_ends == ["start", "end", "start", "end"]


async def test_turn_failure_is_reported_as_a_finished_frame(turn_seams, monkeypatch):
    class Exploding(FakeAgent):
        async def __call__(self, message):
            raise RuntimeError("model down")
    monkeypatch.setattr(coordinator, "Agent", Exploding)
    heard = []

    async def sink(event):
        heard.append(event)
    await coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email=None, text="hi", sink=sink)
    # The failure rides the same emit path as a reply: persisted for the thread and handed to the sink,
    # as one plain line — the exception text belongs in the log, not in a caller's ear.
    last = FakeChat.persisted[-1]
    assert last[0] == "emit" and last[3].finished is True and last[3].message == coordinator.TURN_FAILED_LINE
    assert heard[-1] is last[3] and heard[-1].conversation_id == CID
    assert FakeAgent.calls[-1] == ("cleanup", USER)


async def test_the_wrappers_failure_frame_is_spoken_as_one_plain_line(turn_seams, monkeypatch, caplog):
    class ProviderDown(FakeAgent):
        async def __call__(self, message):
            await self.kwargs["emit_message"](ChatMessageEvent(
                conversation_id=self.kwargs["conversation_id"], finished=True, status="error",
                message="Error: litellm.BadRequestError: OpenrouterException - {'error': {'code': 400}}",
            ))
    monkeypatch.setattr(coordinator, "Agent", ProviderDown)
    heard = []

    async def sink(event):
        heard.append(event)
    await coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email=None, text="hi", sink=sink)
    assert [e.message for e in heard] == [coordinator.TURN_FAILED_LINE] and heard[0].status is None
    assert FakeChat.persisted[-1][3].message == coordinator.TURN_FAILED_LINE
    assert "OpenrouterException" in caplog.text  # the detail is kept where an operator reads it


async def test_turn_sink_hears_every_frame_and_extra_stamps_both_persisted_events(turn_seams):
    heard = []

    async def sink(event):
        heard.append(event)
    await coordinator.run_coordinator_turn(
        sio=object(), sid="", user_id=USER, user_email=None, text="hi", sink=sink,
        extra={"channel": "voice", "call_sid": "CA1"},
    )
    assert [e.message for e in heard] == ["reply:hi"] and heard[0].finished is True
    assert FakeChat.persisted[0][4] == {"channel": "voice", "call_sid": "CA1"}  # the user turn
    assert FakeChat.persisted[1][4] == {"channel": "voice", "call_sid": "CA1"}  # the reply's emit callback


# ── the socket handler ───────────────────────────────────────────────────────

class TestCoordinatorHandler(BaseHandlerTest):

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": "uuid-test-user", "user_data": {"email": "someone@example.com"}}

    @pytest.fixture(autouse=True)
    def seams(self, monkeypatch):
        # CI runs without lifespan startup, where the real get_pool() raises.
        monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: MockNativePool({}))
        monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "coordinator", feature_gates.EVERYONE)
        self.turn = AsyncMock()
        monkeypatch.setattr(coordinator, "run_coordinator_turn", self.turn)
        monkeypatch.setattr("wss.handlers.coordinator_handler.plan_allows_turn", AsyncMock(return_value=(True, None)))

    async def _send(self, frontend_sio, sid, request):
        await send_event(frontend_sio, sid, request)
        responses = [e[1] for e in self.get_main_api_emitted_events("response") if e[1]["request_id"] == request.request_id]
        assert len(responses) == 1, responses
        return responses[0]

    @pytest.mark.asyncio
    async def test_open_send_and_reset_over_the_socket(self, frontend_sio, sid, monkeypatch):
        opened = await self._send(frontend_sio, sid, CoordinatorOpenRequest(request_id="o1"))
        assert opened["data"] == {"conversation_id": "coordinator:uuid-test-user", "model": coordinator.COORDINATOR_MODEL}

        sent = await self._send(frontend_sio, sid, CoordinatorSendRequest(request_id="s1", text="  what's failing?  "))
        assert sent["data"] == {"ok": True}
        assert self.turn.await_args.kwargs["user_id"] == "uuid-test-user"
        assert self.turn.await_args.kwargs["text"] == "what's failing?"
        assert self.turn.await_args.kwargs["user_email"] == "someone@example.com"
        assert self.turn.await_args.kwargs["sid"] == sid

        monkeypatch.setattr("repositories.coordinator_wakeups.coordinator_lock", fake_coordinator_lock)
        monkeypatch.setattr("repositories.coordinator_wakeups.CoordinatorWakeupRepo.reset", AsyncMock(return_value=True))
        reset = await self._send(frontend_sio, sid, CoordinatorResetRequest(request_id="r1"))
        assert reset["data"] == {"reset": True}

    @pytest.mark.asyncio
    async def test_plan_cap_blocks_a_send_before_the_turn(self, frontend_sio, sid, monkeypatch):
        monkeypatch.setattr("wss.handlers.coordinator_handler.plan_allows_turn", AsyncMock(return_value=(False, "Daily AI limit reached")))
        sent = await self._send(frontend_sio, sid, CoordinatorSendRequest(request_id="s2", text="hi"))
        assert sent["error"] == "Daily AI limit reached"
        self.turn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_every_event_is_gated_on_the_rollout(self, frontend_sio, sid, monkeypatch):
        monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "coordinator", feature_gates.INTERNAL)
        monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: False)
        for request in (CoordinatorOpenRequest(request_id="g0"), CoordinatorSendRequest(request_id="g1", text="hi"),
                        CoordinatorResetRequest(request_id="g2"),
                        CoordinatorMemoriesListRequest(request_id="g3"),
                        CoordinatorMemoryGetRequest(request_id="g4", memory_id=WORKFLOW),
                        CoordinatorMemorySaveRequest(request_id="g5", memory={
                            "name": "pref", "description": "When to read", "memory_type": "user", "content": "Details"}),
                        CoordinatorMemoryDeleteRequest(request_id="g6", memory_id=WORKFLOW, expected_version=1)):
            response = await self._send(frontend_sio, sid, request)
            assert response["data"] == {"kind": "gated"} and "available on your account" in response["error"], request
        self.turn.assert_not_awaited()

    async def test_memory_api_uses_session_owner_and_returns_conflicts(self, frontend_sio, sid, monkeypatch):
        from repositories.coordinator_memories import MemoryConflict
        listing = AsyncMock(return_value={"memories": [], "has_more": False})
        monkeypatch.setattr("repositories.coordinator_memories.CoordinatorMemoryRepo.list_headers", listing)
        response = await self._send(frontend_sio, sid, CoordinatorMemoriesListRequest(
            request_id="ml", query="preferences", user_id="someone-else"))
        assert response["data"] == {"memories": [], "has_more": False}
        assert listing.await_args.args == ("uuid-test-user",)
        monkeypatch.setattr("repositories.coordinator_memories.CoordinatorMemoryRepo.delete",
                            AsyncMock(side_effect=MemoryConflict("Memory changed")))
        conflict = await self._send(frontend_sio, sid, CoordinatorMemoryDeleteRequest(
            request_id="md", memory_id=WORKFLOW, expected_version=1))
        assert conflict["data"] == {"kind": "conflict"} and conflict["error"] == "Memory changed"


def test_voice_turns_get_the_spoken_style_and_the_callers_note():
    web = coordinator.system_prompt_for({"channel": "web"}, None)
    assert web == coordinator.SYSTEM_PROMPT
    voice = coordinator.system_prompt_for({"channel": "whatsapp", "call_sid": "CA1"}, "The caller is Dhruv.")
    assert voice.startswith(coordinator.SYSTEM_PROMPT) and "phone call" in voice and voice.endswith("The caller is Dhruv.")
    assert coordinator.system_prompt_for(None, "note only").endswith("note only")


async def test_turn_composes_the_prompt_for_its_channel(turn_seams, monkeypatch):
    captured = {}
    orig_create = FakeAgent.create

    async def create(cls, **kwargs):
        captured.update(kwargs)
        return await orig_create(**kwargs)
    monkeypatch.setattr(FakeAgent, "create", classmethod(create))
    await coordinator.run_coordinator_turn(
        sio=object(), sid="", user_id=USER, user_email=None, text="hi",
        extra={"channel": "phone", "call_sid": "CA1"}, note="The caller is Dhruv. Their account has 2 workflows: A, B.",
    )
    prompt = captured["config"].settings.system_prompt
    assert "no markdown" in prompt and "Their account has 2 workflows: A, B.\n\n" in prompt
    # How to reach the owner rides every turn: here, no address yet.
    assert "Your email address: none yet (set_email_address when email is first needed)." in prompt
    assert prompt.endswith("How the owner likes to be reached is a memory: save it when they say, and pass that "
                           "channel to message_owner.")


# ── trash, restore, message_owner ────────────────────────────────────────────

@pytest.fixture
def own_capabilities():
    saved = dict(capabilities._providers)
    capabilities.clear()
    yield
    capabilities.clear()
    capabilities._providers.update(saved)


async def test_trash_and_restore_run_the_shared_owner_seams(monkeypatch):
    trash = AsyncMock(return_value={"success": True, "workflow_id": WORKFLOW, "message": "Workflow moved to trash"})
    restore = AsyncMock(return_value={"success": False, "error": "Workflow not found in trash"})
    monkeypatch.setattr("wss.handlers.workflow_handler.trash_workflow_as_owner", trash)
    monkeypatch.setattr("wss.handlers.workflow_handler.restore_workflow_as_owner", restore)
    t = tools()
    assert (await t.execute("trash_workflow", {"workflow_id": WORKFLOW}))["success"] is True
    assert trash.await_args.args[1:] == (WORKFLOW, USER)  # the owner, never a collaborator
    out = await t.execute("restore_workflow", {"workflow_id": WORKFLOW})
    assert out == {"success": False, "error": "Workflow not found in trash"}
    assert restore.await_args.args[1:] == (WORKFLOW, USER)


async def test_message_owner_reaches_the_owner_on_the_channel_it_resolves(own_capabilities, monkeypatch):
    from coder.coordinator import reach

    bare = tools()
    names = {p["function"]["name"] for p in bare.tool_params()}
    assert {"message_owner", "set_email_address", "submit_feedback"} <= names and "set_contact_preference" not in names
    channel_enum = next(p for p in bare.tool_params() if p["function"]["name"] == "message_owner")[
        "function"]["parameters"]["properties"]["channel"]["enum"]
    assert channel_enum == ["auto", "email", "web"]  # no WhatsApp where the instance can't send it
    monkeypatch.setattr(reach, "resolve_channel", AsyncMock(return_value="whatsapp"))
    out = await bare.execute("message_owner", {"text": "hi"})
    assert out == {"success": False, "channel": "whatsapp", "error": "WhatsApp isn't available on this instance."}

    send = AsyncMock(return_value={"success": True, "message_id": "wamid.9"})
    capabilities.provide(OWNER_MESSAGE, send)
    t = tools()
    out = await t.execute("message_owner", {"text": "  Your link  ", "link": "https://noclick.com/b/abc"})
    assert out["success"] is True and out["channel"] == "whatsapp"
    send.assert_awaited_once_with(t.pool, USER, "Your link", link="https://noclick.com/b/abc")
    assert (await t.execute("message_owner", {"text": "   "}))["success"] is False


async def test_media_tools_answer_the_model_with_results_or_the_gate_reason(monkeypatch):
    from billing.gates import GateDenied

    monkeypatch.setattr(coordinator_tools, "generate_image", AsyncMock(return_value={
        "model": "openai/gpt-image-2.5-sunburst", "images": [{"url": "https://f.example/image-1.png"}]}))
    made = await tools().execute("generate_image", {"prompt": "a fern"})
    assert made == {"success": True, "model": "openai/gpt-image-2.5-sunburst", "images": ["https://f.example/image-1.png"]}

    monkeypatch.setattr(coordinator_tools, "start_video", AsyncMock(
        side_effect=GateDenied("plan", "Video generation is available on the Plus and Pro plans.")))
    refused = await tools().execute("generate_video", {"prompt": "waves"})
    assert refused == {"success": False, "error": "Video generation is available on the Plus and Pro plans."}
    monkeypatch.setattr(coordinator_tools, "start_video", AsyncMock(return_value={"job_id": "j1", "projected_credits": 9.6}))
    started = await tools().execute("generate_video", {"prompt": "waves", "seconds": 8})
    assert started["success"] is True and started["job_id"] == "j1" and "woken" in started["next"]
    assert coordinator_tools.start_video.await_args.kwargs["continuation"] is None
