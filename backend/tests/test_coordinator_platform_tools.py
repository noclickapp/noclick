"""The coordinator's seam for a platform's tools (``COORDINATOR_PLATFORM_TOOLS``), with a fake provider.

Without a provider (the open edition), or when the provider gives a turn none (its rollout off, its grant
revoked), the coordinator has exactly its own tools. With one, judged once at the turn's start: its core joins
them, what it supersedes leaves, its calls carry the model's call id and are audited as the provider shows them,
and what it installs mid-turn lives in the turn's one discovered-tools registry, beside connections' operations,
gone the next turn. The base tool list is pinned: anything new goes behind loading."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from coder.coordinator import agent as coordinator
from coder.coordinator import tools as coordinator_tools
from coder.coordinator.tools import CoordinatorTools
from coder.openai_agent.agent import CURRENT_TOOL_CALL_ID
from tests.mocks.mock_asyncpg import MockNativePool
from tests.test_coordinator import CID, ORG, USER, turn_seams  # noqa: F401
from utils import capabilities, feature_gates
from utils.capabilities import (
    AUTO_TOPUP, COORDINATOR_PLATFORM_TOOLS, INTERFACE_PUBLISH, OWNER_MESSAGE, PHONE_NUMBERS, PURCHASES,
)
from utils.discovered_tools import MAX_VISIBLE_INSTALLED, MAX_VISIBLE_TOOLS, DiscoveredTools
from wss.sender.events import ChatMessageEvent

# The coordinator's own tools on a web turn: the open edition's, and with every capability the hosted edition has.
OPEN_EDITION_TOOLS = 42
HOSTED_TOOLS = 47


def param(name):
    return {"type": "function", "function": {"name": name, "description": name,
                                             "parameters": {"type": "object", "properties": {}}}}


class FakeTurn:
    supersedes = frozenset({"web_search"})
    instructions = "PLATFORM: p_find and p_load."
    status = {"balance": {"remaining_usd": 12.5}, "approvals_pending": []}

    def __init__(self, discovered):
        self.discovered, self.calls = discovered, []

    def tool_params(self):
        return [param("p_find"), param("p_load")]

    async def call(self, name, arguments, *, call_id):
        self.calls.append((name, arguments, call_id))
        if name == "p_load":
            return {"success": True, "loaded": self.discovered.install([param("p_installed")], self)}
        return {"success": True, "found": arguments.get("q")}

    def shown_arguments(self, arguments, result):
        return {k: "[sealed]" if k == "secret" else v for k, v in arguments.items()}

    async def overview(self):
        return self.status


@pytest.fixture
def provider(monkeypatch):
    """A platform giving every turn its tools; ``opened`` records how each turn was judged."""
    opened, turns = [], []

    async def open_turn(pool, *, discovered, **turn):
        opened.append(turn)
        turns.append(FakeTurn(discovered))
        return turns[-1]

    monkeypatch.setitem(capabilities._providers, COORDINATOR_PLATFORM_TOOLS, open_turn)
    return SimpleNamespace(opened=opened, turns=turns)


CONTINUATION = {"epoch": "", "depth": 0, "request": "hi", "channel": "web", "turn_id": "turn-1"}


def tools():
    return CoordinatorTools(pool=MockNativePool(), sio=object(), user_id=USER, organization_id=ORG,
                            conversation_id=CID, email="a@b.c", continuation=CONTINUATION)


def names(t):
    return [p["function"]["name"] for p in t.tool_params()]


def job_kinds(t):
    status = next(p for p in t.tool_params() if p["function"]["name"] == "job_status")["function"]
    return status["parameters"]["properties"]["kind"]["enum"]


async def test_without_a_provider_or_with_none_this_turn_the_tools_are_exactly_its_own(monkeypatch):
    monkeypatch.delitem(capabilities._providers, COORDINATOR_PLATFORM_TOOLS, raising=False)
    t = tools()
    before, dispatch = names(t), set(t._tools)
    await t.open_platform(turn_id="t", untrusted=False, voice=False, cards=False)
    assert t.platform is None and names(t) == before and set(t._tools) == dispatch

    monkeypatch.setitem(capabilities._providers, COORDINATOR_PLATFORM_TOOLS, AsyncMock(return_value=None))
    await t.open_platform(turn_id="t", untrusted=False, voice=False, cards=False)
    assert t.platform is None and names(t) == before and set(t._tools) == dispatch
    assert (await t.execute("p_find", {}, call_id="c"))["error"] == "unknown tool: p_find"


async def test_a_platforms_core_joins_and_what_it_supersedes_leaves(provider, monkeypatch):
    t = tools()
    before = names(t)
    assert "platform" not in job_kinds(t)
    await t.open_platform(turn_id="turn-1", untrusted=True, voice=True, cards=False)
    # The turn's continuation goes with it: what its tools wait on wakes this conversation.
    assert provider.opened == [{"user_id": USER, "turn_id": "turn-1", "untrusted": True, "voice": True,
                                "cards": False, "continuation": CONTINUATION}]
    assert names(t) == [n for n in before if n != "web_search"] + ["p_find", "p_load"]
    assert "platform" in job_kinds(t)
    assert set(t._tools) == set(before) - {"web_search"}
    assert (await t.execute("web_search", {"query": "x"}, call_id="c"))["error"] == "unknown tool: web_search"

    recorded = []
    monkeypatch.setattr(coordinator_tools, "record_tool_call", lambda **kw: recorded.append(kw))
    found = await t.execute("p_find", {"q": "numbers", "secret": "hunter2"}, call_id="call_9")
    assert found == {"success": True, "found": "numbers"}
    assert provider.turns[0].calls == [("p_find", {"q": "numbers", "secret": "hunter2"}, "call_9")]
    # The audit keeps what the platform shows of a call, never more.
    assert recorded[-1]["arguments"] == {"q": "numbers", "secret": "[sealed]"}
    assert recorded[-1]["tool_type"] == "coordinator" and recorded[-1]["result_status"] == "success"


async def test_installed_tools_share_the_turns_one_registry_and_last_one_turn(provider):
    t = tools()
    await t.open_platform(turn_id="t", untrusted=False, voice=False, cards=False)
    assert (await t.execute("p_load", {}, call_id="c1"))["loaded"] == ["p_installed"]
    assert t.discovered is t.credential_tools.registry
    assert [p["function"]["name"] for p in t.discovered.tool_params()] == ["p_installed"]
    assert (await t.execute("p_installed", {"q": "x"}, call_id="c2")) == {"success": True, "found": "x"}
    assert provider.turns[0].calls[-1] == ("p_installed", {"q": "x"}, "c2")

    later = tools()
    await later.open_platform(turn_id="t2", untrusted=False, voice=False, cards=False)
    assert later.discovered.tool_params() == []
    assert (await later.execute("p_installed", {}, call_id="c3"))["error"] == "unknown tool: p_installed"


async def test_the_overview_gains_the_platforms_section_on_a_turn_with_it(provider, monkeypatch):
    """account_overview is the Dashboard's aggregate; a platform adds its own section (balance, approvals, what's
    failing there), which one that can't say how it stands reports beside the rest without blanking it."""
    dashboard = {"workspace": {"name": "W"}, "generatedAt": "t", "errors": {}, "attention": [{"id": 1}]}
    monkeypatch.setattr("wss.handlers.dashboard_handler.build_overview",
                        AsyncMock(side_effect=lambda *a, **kw: copy.deepcopy(dashboard)))
    t = tools()

    def sections():
        overview = next(p for p in t.tool_params() if p["function"]["name"] == "account_overview")["function"]
        return overview["parameters"]["properties"]["section"]["enum"]

    assert "platform" not in sections() and (await t.account_overview(section="platform"))["success"] is False
    assert "platform" not in (await t.account_overview())["overview"]
    await t.open_platform(turn_id="t", untrusted=False, voice=False, cards=False)
    assert "platform" in sections()
    full = (await t.account_overview())["overview"]
    assert full["platform"] == FakeTurn.status and full["attention"] == [{"id": 1}]
    assert (await t.account_overview(section="platform"))["overview"] == {"platform": FakeTurn.status, "errors": {}}
    assert "platform" not in (await t.account_overview(section="attention"))["overview"]
    monkeypatch.setattr(FakeTurn, "overview", AsyncMock(side_effect=RuntimeError("status unreadable")))
    broken = (await t.account_overview())["overview"]
    assert broken["errors"] == {"platform": "status unreadable"} and broken["attention"] == [{"id": 1}]


def test_each_kind_of_discovered_tool_keeps_its_own_most_recent():
    found = DiscoveredTools()
    owner = object()
    found.install([param(f"op_{i}") for i in range(MAX_VISIBLE_INSTALLED + 5)], owner)
    for i in range(MAX_VISIBLE_TOOLS + 3):
        found.load("automation-x", f"op{i}", [param(f"t{i}")], {f"t{i}": {"tool_type": "node_op"}})
    shown = [p["function"]["name"] for p in found.tool_params()]
    assert len([n for n in shown if n.startswith("op_")]) == MAX_VISIBLE_INSTALLED
    assert len([n for n in shown if n.startswith("credential_")]) == MAX_VISIBLE_TOOLS
    assert "op_0" not in shown and f"op_{MAX_VISIBLE_INSTALLED + 4}" in shown
    # Dispatch keeps what left the model's view, for calls already in flight.
    assert found.installed["op_0"] is owner and len(found.routes) == MAX_VISIBLE_TOOLS + 3
    with pytest.raises(ValueError):
        found.install([param(next(iter(found.routes)))], owner)


def test_the_base_tool_list_is_pinned(monkeypatch):
    monkeypatch.setattr(capabilities, "_providers", {})
    assert len(names(tools())) == OPEN_EDITION_TOOLS
    catalog = {"plans": [{"plan": "member", "label": "Member", "monthly_usd": 25, "yearly_usd": None,
                          "description": "More."}],
               "funds": {"min_usd": 5, "max_usd": 500, "presets_usd": [10, 25]}, "checkout_note": ""}
    monkeypatch.setenv("SENDBLUE_NUMBER", "+15550000000")
    for name, provided in ((OWNER_MESSAGE, object()), (INTERFACE_PUBLISH, object()), (PHONE_NUMBERS, object()),
                           (PURCHASES, SimpleNamespace(catalog=lambda email=None: catalog)), (AUTO_TOPUP, object())):
        capabilities._providers[name] = provided
    monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "auto_topup", feature_gates.EVERYONE)
    assert len(names(tools())) == HOSTED_TOOLS


async def test_a_turn_opens_the_platform_once_and_its_calls_carry_their_id(turn_seams, provider, monkeypatch):
    captured = {}

    class CallingAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @classmethod
        async def create(cls, **kwargs):
            captured.update(kwargs)
            return cls(**kwargs)

        def set_discovered_tools(self, definitions):
            captured["discovered"] = [d["function"]["name"] for d in definitions]

        async def __call__(self, message):
            # The SDK runs each tool call with the model's id for it in context.
            called = CURRENT_TOOL_CALL_ID.set("call_abc")
            try:
                captured["result"] = await self.kwargs["custom_tool_executor"]("p_load", {})
            finally:
                CURRENT_TOOL_CALL_ID.reset(called)
            await self.kwargs["emit_message"](ChatMessageEvent(conversation_id=CID, message="done", finished=True))

        async def cleanup(self):
            pass

    monkeypatch.setattr(coordinator, "Agent", CallingAgent)
    monkeypatch.setattr(coordinator, "bills_on_old_plans", AsyncMock(return_value=False))
    await coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email="a@b.c", text="hi",
                                           extra={"channel": "voice"})
    [opened] = provider.opened
    assert opened["untrusted"] is False and opened["voice"] is True and opened["cards"] is False
    assert opened["continuation"] == {"epoch": "", "depth": 0, "request": "hi", "channel": "voice",
                                      "turn_id": opened["turn_id"]}
    config = captured["config"]
    assert "p_find" in config.capabilities.custom_tool_names
    assert "web_search" not in config.capabilities.custom_tool_names
    assert FakeTurn.instructions in config.settings.system_prompt
    assert provider.turns[0].calls == [("p_load", {}, "call_abc")]
    assert captured["discovered"] == ["p_installed"] and captured["result"]["success"] is True


@pytest.mark.parametrize("supersedes, kept", [(frozenset({"web_search"}), True),
                                               (frozenset({"request_phone_number", "find_phone_numbers"}), False)])
async def test_the_phone_steps_leave_the_prompt_with_the_tools_they_describe(turn_seams, provider, monkeypatch,
                                                                          supersedes, kept):
    """A platform that buys numbers itself says how in its instructions: the coordinator's own phone steps stay only
    while its own phone tools do. What a call may never be set up for stays whatever buys the number."""
    from utils.call_safety import OWNER_EMERGENCY_STEP

    prompts = []
    monkeypatch.setattr(FakeTurn, "supersedes", supersedes)
    monkeypatch.setattr(coordinator, "bills_on_old_plans", AsyncMock(return_value=False))
    real = coordinator.system_prompt_for
    monkeypatch.setattr(coordinator, "system_prompt_for",
                        lambda *a, **kw: prompts.append((real(*a, **kw), kw["phone_steps"])) or "")
    await coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email="a@b.c", text="hi")
    [(prompt, phone_steps)] = prompts
    assert phone_steps is kept
    assert prompt.startswith(coordinator.PROMPTS.system_prompt(in_credits=False, phone_steps=kept))
    assert FakeTurn.instructions in prompt and OWNER_EMERGENCY_STEP in prompt


@pytest.mark.parametrize("channel, cards", [("web", True), ("whatsapp_text", False), ("email", False)])
async def test_only_a_live_web_turn_has_its_tools_drawn_as_cards(turn_seams, provider, monkeypatch, channel, cards):
    """The platform words its links as the turn's prompt does: on the card below on the web, written out elsewhere."""
    prompts = []
    monkeypatch.setattr(coordinator, "bills_on_old_plans", AsyncMock(return_value=False))
    monkeypatch.setattr(coordinator, "system_prompt_for", lambda *a, **kw: prompts.append(kw["cards"]) or "")
    await coordinator.run_coordinator_turn(sio=object(), sid="s", user_id=USER, user_email="a@b.c", text="hi",
                                           extra={"channel": channel})
    assert [opened["cards"] for opened in provider.opened] == prompts == [cards]


@pytest.mark.parametrize("source, untrusted", [("signal", True), ("job", True), ("operation", True),
                                               ("alarm", False), ("credential_approval", False), ("link", False)])
async def test_a_completion_turn_is_its_own_turn_and_outside_text_is_untrusted(turn_seams, provider, monkeypatch,
                                                                              source, untrusted):
    class Agent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @classmethod
        async def create(cls, **kwargs):
            return cls(**kwargs)

        async def __call__(self, message):
            await self.kwargs["emit_message"](ChatMessageEvent(conversation_id=CID, message="ok", finished=True))

        async def cleanup(self):
            pass

    monkeypatch.setattr(coordinator, "Agent", Agent)
    monkeypatch.setattr(coordinator, "bills_on_old_plans", AsyncMock(return_value=False))
    monkeypatch.setattr(coordinator.CoordinatorWakeupRepo, "start", AsyncMock(return_value=True))
    monkeypatch.setattr(coordinator.CoordinatorWakeupRepo, "heartbeat", AsyncMock(return_value=True))
    completion = {"id": "wake-7", "source": source, "source_id": "s1", "payload": {},
                  "context": {"epoch": "", "depth": 0, "request": "earlier", "channel": "web", "turn_id": "first"}}
    await coordinator.run_coordinator_turn(sio=object(), sid="", user_id=USER, user_email="a@b.c", text="",
                                           extra={"channel": "web"}, completion=completion)
    # A follow-up's own waits wake the same request, one step further down its chain.
    continuation = {**completion["context"], "depth": 1,
                    **({"origin": "background"} if source in ("alarm", "signal") else {})}
    # A follow-up lands as a note, which draws no cards.
    assert provider.opened == [{"user_id": USER, "turn_id": "wake-7", "untrusted": untrusted, "voice": False,
                                "cards": False, "continuation": continuation}]


async def test_the_sdk_hands_each_tool_call_its_id():
    from coder.openai_agent.agent import Agent

    seen = []

    async def executor(name, arguments):
        seen.append((name, CURRENT_TOOL_CALL_ID.get()))
        return {"ok": True}

    agent = Agent.__new__(Agent)
    agent._custom_tool_executor = executor
    tool = agent._make_function_tool("p_find", "", {"type": "object", "properties": {}})
    assert await tool.on_invoke_tool(SimpleNamespace(tool_call_id="call_77"), "{}") == '{"ok": true}'
    assert seen == [("p_find", "call_77")] and CURRENT_TOOL_CALL_ID.get() is None
