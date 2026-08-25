"""The fabricated world a rehearsal runs against.

Most of these pin restraint rather than function. A rehearsal is a screen that
looks exactly like proof, so the dangerous failures are the quiet ones: a mocked
run that reaches a real account, or a mock model that fails and hands the agent
an empty object to reason over confidently.
"""

from __future__ import annotations

import json

import pytest

from nodes.agent import rehearsal as rh
from nodes.agent.rehearsal import RehearsalScenario, RehearsalUnavailable


class FakeRedis:
    """Enough of redis.asyncio for this module, with byte values like the real one."""

    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value.encode() if isinstance(value, str) else value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


SCENARIO = RehearsalScenario(
    scenario="A customer emails about a refund that never arrived.",
    trigger_node_id="automation-gmail-1",
    trigger_payload={"from": "casey@sender.example", "subject": "Where is my refund?"},
)


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: fake)
    return fake


def _reply(content: str):
    """A litellm-shaped response."""

    class Msg:
        def __init__(self, c):
            self.content = c

    class Choice:
        def __init__(self, c):
            self.message = Msg(c)

    class Resp:
        def __init__(self, c):
            self.choices = [Choice(c)]

    async def _f(*a, **kw):
        return Resp(content)

    return _f


# ----------------------------------------------------------------- the gate


@pytest.mark.asyncio
async def test_a_conversation_is_not_rehearsing_by_default(redis):
    """The gate every tool call consults must default to 'this is real'."""
    assert await rh.is_rehearsing("conv-1") is False
    assert await rh.load_rehearsal("conv-1") is None
    assert await rh.load_rehearsal(None) is None


@pytest.mark.asyncio
async def test_rehearsing_is_recognised_once_started(redis):
    await rh.start_rehearsal("conv-1", SCENARIO)
    assert await rh.is_rehearsing("conv-1") is True
    await rh.end_rehearsal("conv-1")
    assert await rh.is_rehearsing("conv-1") is False


@pytest.mark.asyncio
async def test_a_redis_blip_reads_as_not_rehearsing(monkeypatch):
    """Fail closed. 'Unknown' must never mean 'rehearsing'.

    The inverse would be catastrophic: a run believed to be rehearsing that is
    actually executing against a real account.
    """

    class Broken(FakeRedis):
        async def get(self, key):
            raise ConnectionError("redis down")

    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: Broken())
    assert await rh.is_rehearsing("conv-1") is False


@pytest.mark.asyncio
async def test_a_rehearsal_refuses_to_start_without_redis(monkeypatch):
    """No Redis means the tool-call mirrors cannot be told this run is staged.

    Starting anyway would produce a run the user believes is a rehearsal while
    every tool call executes for real.
    """
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: None)
    with pytest.raises(RehearsalUnavailable, match="Redis unavailable"):
        await rh.start_rehearsal("conv-1", SCENARIO)


# ------------------------------------------------------------ the ledger


@pytest.mark.asyncio
async def test_the_session_remembers_what_it_already_fabricated(redis, monkeypatch):
    """The transcript IS the ledger — this is the design's load-bearing property.

    An agent that creates a ticket and reads it back must get the same ticket,
    and that only works if prior exchanges are replayed to the mock model.
    """
    await rh.start_rehearsal("conv-1", SCENARIO)

    seen = []

    async def capture(*a, **kw):
        seen.append(kw["messages"])

        class M:
            content = json.dumps({"id": 4471})

        class C:
            message = M()

        class R:
            choices = [C()]

        return R()

    monkeypatch.setattr("litellm.acompletion", capture)

    await rh.mock_tool_call(
        conversation_id="conv-1", tool_name="zendesk__create_ticket", arguments={}
    )
    await rh.mock_tool_call(
        conversation_id="conv-1", tool_name="zendesk__get_ticket", arguments={"id": 4471}
    )

    second_call_messages = seen[1]
    replayed = json.dumps(second_call_messages)
    assert "create_ticket" in replayed, (
        "the second call must see the first — without the prior exchange the mock "
        "cannot know ticket 4471 exists and the trace contradicts itself"
    )
    assert "4471" in replayed


@pytest.mark.asyncio
async def test_progress_frames_carry_the_call_and_the_answer(redis, monkeypatch):
    """The trace UI's inspector opens on frame.args and labels frame.result as
    stand-in data — a frame without them renders an unexpandable row."""
    await rh.start_rehearsal("conv-1", SCENARIO)

    async def fabricate(*a, **kw):
        class M:
            content = json.dumps({"ok": True, "ts": "1700000000.000001"})

        class C:
            message = M()

        class R:
            choices = [C()]

        return R()

    monkeypatch.setattr("litellm.acompletion", fabricate)

    frames = []

    async def capture(state, conversation_id, **fields):
        frames.append(fields)

    monkeypatch.setattr(rh, "_emit_progress", capture)

    arguments = {
        "channel": "#inbound-leads",
        "text": "New qualified lead: Casey at Example Manufacturing.",
    }
    await rh.mock_tool_call(
        conversation_id="conv-1",
        tool_name="slack__send_message_to_channel",
        arguments=arguments,
    )

    in_progress, completed = frames
    assert in_progress["status"] == "in_progress"
    assert in_progress["args"] == arguments
    assert completed["status"] == "completed"
    assert completed["args"] == arguments
    assert completed["result"] == {"ok": True, "ts": "1700000000.000001"}
    assert completed["outbound"] == arguments["text"]


def test_a_rehearsal_never_adopts_the_fixtures_chat_identity():
    """Found live (2026-08-10): the staged Telegram event's conversation_key —
    the fixture's chat id — beat the rehearsal's isolation stamp, so the
    fabricated exchange persisted into the history a REAL chat with that id
    resumes, and repeat runs of one scenario interleaved into one session. In a
    rehearsal the config key must win; on real deliveries the event key must
    keep winning (the channels story depends on it)."""
    from nodes.agent.rehearsal import effective_conversation_key

    # rehearsal: config's isolation stamp wins over the fixture's chat id
    assert (
        effective_conversation_key("rehearsal:wf:abc", "100000001", "rehearsal:wf:abc")
        == "rehearsal:wf:abc"
    )
    # real delivery: the medium's native thread identity wins
    assert effective_conversation_key("conv-1", "100000001", "configured") == "100000001"
    assert effective_conversation_key(None, "100000001", None) == "100000001"
    # fallbacks on both sides
    assert effective_conversation_key("rehearsal:wf:abc", "100000001", None) == "100000001"
    assert effective_conversation_key("conv-1", None, "configured") == "configured"


@pytest.mark.asyncio
async def test_the_scenario_briefs_every_call(redis, monkeypatch):
    await rh.start_rehearsal("conv-1", SCENARIO)
    seen = []

    async def capture(*a, **kw):
        seen.append(kw["messages"])

        class M:
            content = "{}"

        class C:
            message = M()

        class R:
            choices = [C()]

        return R()

    monkeypatch.setattr("litellm.acompletion", capture)
    await rh.mock_tool_call(conversation_id="conv-1", tool_name="x", arguments={})

    system = seen[0][0]
    assert system["role"] == "system"
    assert "refund that never arrived" in system["content"]


@pytest.mark.asyncio
async def test_the_call_arguments_reach_the_mock(redis, monkeypatch):
    """A fixture cannot answer a query it never saw; a session can.

    This is the difference between a rehearsal that demonstrates judgment and one
    that returns unrelated records while the agent reasons confidently over them.
    """
    await rh.start_rehearsal("conv-1", SCENARIO)
    seen = []

    async def capture(*a, **kw):
        seen.append(kw["messages"])

        class M:
            content = "{}"

        class C:
            message = M()

        class R:
            choices = [C()]

        return R()

    monkeypatch.setattr("litellm.acompletion", capture)
    await rh.mock_tool_call(
        conversation_id="conv-1",
        tool_name="zendesk__search_tickets",
        arguments={"query": "refund not received"},
    )
    assert "refund not received" in json.dumps(seen[0])


# ------------------------------------------------------------- failure


@pytest.mark.asyncio
async def test_a_failed_simulation_stops_rather_than_returning_nothing(
    redis, monkeypatch
):
    """Never hand the agent `{}` and let it carry on.

    An agent reasoning over an empty response produces a confident, plausible,
    entirely misleading trace — worse than an honest failure, because it looks
    like the product working.
    """
    await rh.start_rehearsal("conv-1", SCENARIO)

    async def boom(*a, **kw):
        raise TimeoutError("model unreachable")

    monkeypatch.setattr("litellm.acompletion", boom)

    with pytest.raises(RehearsalUnavailable, match="could not simulate"):
        await rh.mock_tool_call(
            conversation_id="conv-1", tool_name="zendesk__search", arguments={}
        )


@pytest.mark.asyncio
async def test_unparseable_output_is_a_failure_not_a_shrug(redis, monkeypatch):
    await rh.start_rehearsal("conv-1", SCENARIO)
    monkeypatch.setattr("litellm.acompletion", _reply("I'm sorry, I can't do that."))
    with pytest.raises(RehearsalUnavailable):
        await rh.mock_tool_call(
            conversation_id="conv-1", tool_name="x", arguments={}
        )


@pytest.mark.asyncio
async def test_mocking_a_conversation_that_is_not_rehearsing_is_refused(redis):
    """Guards against a stale session id quietly fabricating data on a real run."""
    with pytest.raises(RehearsalUnavailable, match="not rehearsing"):
        await rh.mock_tool_call(
            conversation_id="conv-never-started", tool_name="x", arguments={}
        )


@pytest.mark.asyncio
async def test_fenced_json_is_tolerated(redis, monkeypatch):
    """Small models fence their JSON; that is not worth failing a rehearsal over."""
    await rh.start_rehearsal("conv-1", SCENARIO)
    monkeypatch.setattr(
        "litellm.acompletion", _reply('```json\n{"ok": true, "id": 7}\n```')
    )
    out = await rh.mock_tool_call(
        conversation_id="conv-1", tool_name="x", arguments={}
    )
    assert out == {"ok": True, "id": 7}


# ------------------------------------------------------ prompt contract


def test_the_mock_is_told_not_to_invent_failures():
    """A random fabricated outage misrepresents the agent's behaviour, and the
    user cannot distinguish it from a scripted one."""
    assert "Never invent a failure" in rh._SYSTEM


def test_the_mock_is_told_to_avoid_placeholder_output():
    assert "Example Customer" in rh._SYSTEM


def test_the_mock_is_told_to_stay_consistent():
    assert "consistent with everything you have already returned" in rh._SYSTEM


# ------------------------------------------------------- the artifact


def test_the_composed_message_is_pulled_from_the_call_not_the_narration():
    """The payoff panel must show the work, not a report of the work.

    Live e2e caught this: under "what it would have posted" the screen showed
    "I have posted the briefing to Slack regarding the new lead..." — the agent's
    closing summary addressed to the user, rather than the briefing it actually
    composed. The artifact lives in the tool call's arguments.
    """
    from nodes.agent.rehearsal import outbound_text

    briefing = (
        "New lead — Casey Example at Example Manufacturing. Wants approval requests "
        "routed into Slack automatically. Asked about pricing for twelve teammates."
    )
    assert outbound_text({"channel": "#inbound-leads", "text": briefing}) == briefing


def test_short_arguments_are_not_mistaken_for_the_message():
    """A channel name or an id is not the artifact."""
    from nodes.agent.rehearsal import outbound_text

    assert outbound_text({"channel": "#sales", "ts": "1700000000.000001"}) is None
    assert outbound_text({"text": "ok"}) is None


def test_the_body_wins_over_the_subject():
    """A call carrying both should surface the part worth reading."""
    from nodes.agent.rehearsal import outbound_text

    picked = outbound_text(
        {
            "subject": "Example Manufacturing — inbound lead worth a call",
            "body": "Casey manages operations at a fictional manufacturer and wants "
            "approval requests in Slack. Clear need and timeline; worth a call this week.",
        }
    )
    assert picked.startswith("Casey manages operations")


def test_no_arguments_is_not_an_error():
    from nodes.agent.rehearsal import outbound_text

    assert outbound_text(None) is None
    assert outbound_text({}) is None


# ------------------------------------------------------- the offer list


def _wired_graph(*trigger_specs: dict):
    """Nodes + edges: each spec becomes a node wired into one agent's input —
    the shape a stageable trigger actually has on a real canvas."""
    nodes = [{"id": "agent-1", "type": "agent"}]
    edges = []
    for i, spec in enumerate(trigger_specs):
        n = {"id": f"t{i}", **spec}
        nodes.append(n)
        edges.append({"source": n["id"], "target": "agent-1", "targetHandle": "left"})
    return nodes, edges


def test_situations_are_offered_only_where_their_trigger_exists():
    """A menu of runs that would fail on click is worse than no menu.

    The listing derives from the saved graph: a Gmail situation is offered only
    to a workflow that actually wires a Gmail trigger toward an agent.
    """
    from nodes.agent.rehearsal_scenarios import staged_for_graph

    nodes, edges = _wired_graph({"type": "automation-gmail"}, {"type": "automation-slack"})
    offered = staged_for_graph(nodes, edges)
    assert sorted(t["node_type"] for t in offered) == [
        "automation-gmail",
        "automation-slack",
    ], "each wired trigger type is offered; absent ones (whatsapp, telegram) are not"
    gmail = next(t for t in offered if t["node_type"] == "automation-gmail")
    keys = [s["key"] for s in gmail["situations"]]
    assert "sales-inbound-lead" in keys and "thin-inquiry" in keys and "newsletter" in keys

    assert staged_for_graph([{"id": "a", "type": "agent"}], []) == []
    assert staged_for_graph([], []) == []
    assert staged_for_graph(None, None) == []


def test_offered_triggers_carry_their_selected_operation():
    """The FE frames respond to the trigger OPERATION (a PR trigger renders a
    PR card, invoice.paid an invoice), so the offer must say which operation
    the stageable node has selected — for authored types and generics alike.
    A node with no operation simply omits the key."""
    from nodes.agent.rehearsal_scenarios import staged_for_graph

    nodes, edges = _wired_graph(
        {"type": "automation-gmail", "config": {"operation": "on_new_email"}},
        {"type": "trigger-webhook", "config": {"operation": "on_request"}},
    )
    offered = {t["node_type"]: t for t in staged_for_graph(nodes, edges)}
    assert offered["automation-gmail"]["operation"] == "on_new_email"
    assert offered["trigger-webhook"]["operation"] == "on_request"

    plain_nodes, plain_edges = _wired_graph({"type": "trigger-cron"})
    plain = staged_for_graph(plain_nodes, plain_edges)
    assert plain and "operation" not in plain[0]


@pytest.mark.asyncio
async def test_wiring_decides_what_is_stageable_not_type_presence():
    """The 2026-08-10 case: a Telegram node wired as the agent's TOOL was
    offered as a trigger; the staged event landed on it and the runner dropped
    it (provider mode wins) — a test that ran and showed nothing. An unwired
    trigger node is the same lie by another route: no agent is reachable from
    it, so its rehearsal has no story to tell. Both must vanish from the offer,
    and the run-time resolver must skip them for a stageable sibling."""
    from nodes.agent.rehearsal import resolve_trigger_node_id
    from nodes.agent.rehearsal_scenarios import staged_for_graph

    agent = {"id": "agent-1", "type": "agent"}

    provider_wired_nodes = [agent, {"id": "tg-tool", "type": "automation-telegram"}]
    provider_wired_edges = [
        {"source": "tg-tool", "target": "agent-1", "targetHandle": "bottom"}
    ]
    assert staged_for_graph(provider_wired_nodes, provider_wired_edges) == []
    assert (
        await resolve_trigger_node_id(
            provider_wired_nodes, provider_wired_edges, "automation-telegram"
        )
        is None
    )

    assert staged_for_graph([agent, {"id": "tg-x", "type": "automation-telegram"}], []) == []

    # Indirect wiring still counts — trigger → transform → agent is a real shape.
    chained_nodes = [
        agent,
        {"id": "tg", "type": "automation-telegram"},
        {"id": "fx", "type": "automation-serverless-function"},
    ]
    chained_edges = [
        {"source": "tg", "target": "fx"},
        {"source": "fx", "target": "agent-1", "targetHandle": "left"},
    ]
    assert [t["node_type"] for t in staged_for_graph(chained_nodes, chained_edges)] == [
        "automation-telegram"
    ]

    # With both wirings present, the trigger sibling wins and the tool never
    # swallows the event.
    both_nodes = [
        agent,
        {"id": "tg-tool", "type": "automation-telegram"},
        {"id": "tg-trig", "type": "automation-telegram"},
    ]
    both_edges = [
        {"source": "tg-tool", "target": "agent-1", "targetHandle": "bottom"},
        {"source": "tg-trig", "target": "agent-1", "targetHandle": "left"},
    ]
    assert [t["node_type"] for t in staged_for_graph(both_nodes, both_edges)] == [
        "automation-telegram"
    ]
    assert (
        await resolve_trigger_node_id(both_nodes, both_edges, "automation-telegram")
        == "tg-trig"
    )


def test_the_flat_runner_contract_derives_from_the_grouped_registry():
    """The runner and the picker must never disagree about what exists."""
    from nodes.agent.rehearsal_scenarios import (
        SCENARIOS,
        SCENARIO_TRIGGER_NODE_TYPES,
        STAGED_SITUATIONS,
    )

    grouped = {
        s["key"]: node_type
        for node_type, situations in STAGED_SITUATIONS.items()
        for s in situations
    }
    assert set(SCENARIOS) == set(grouped)
    assert SCENARIO_TRIGGER_NODE_TYPES == grouped


def test_every_offered_situation_is_runnable():
    """Everything the picker offers, the runner can start: a real scenario,
    shaped for the trigger type it is grouped under."""
    from nodes.agent.rehearsal import RehearsalScenario
    from nodes.agent.rehearsal_scenarios import SCENARIOS, STAGED_SITUATIONS

    for node_type, situations in STAGED_SITUATIONS.items():
        for s in situations:
            assert isinstance(s["scenario"], RehearsalScenario)
            assert SCENARIOS[s["key"]] is s["scenario"]
            # the display lead must agree with the injected payload where they
            # overlap — showing one email and injecting another is a lie
            payload = s["scenario"].trigger_payload
            if node_type == "automation-gmail":
                assert s["lead"]["title"] == payload["subject"]
                assert s["lead"]["handle"] in payload["from"]
            elif node_type == "automation-slack":
                assert s["lead"]["body"] == payload["data"]["event"]["text"]
            elif node_type == "automation-whatsapp":
                assert s["lead"]["body"] == payload["payload"]["body"]
            elif node_type == "automation-telegram":
                assert s["lead"]["body"] == payload["message"]["text"]


def test_channel_payloads_survive_their_nodes_own_readers():
    """The payload only counts if the node's resolve_agent_event turns it into a
    message-shaped turn. An almost-right payload falls through to the raw-JSON
    default and the agent gets a dump instead of a message — the failure nothing
    on screen explains."""
    from nodes.agent.rehearsal_scenarios import STAGED_SITUATIONS
    from nodes.core.registry import NODE_REGISTRY

    for node_type, situations in STAGED_SITUATIONS.items():
        node_cls = NODE_REGISTRY[node_type]
        if node_type == "automation-gmail":
            continue  # gmail's poll trigger delivers differently; covered above
        for s in situations:
            resolved = node_cls.resolve_agent_event(s["scenario"].trigger_payload)
            assert resolved and resolved.get("text"), f"{s['key']}: no turn text"
            assert not resolved["text"].lstrip().startswith("{"), (
                f"{s['key']}: fell through to the raw-JSON default — the payload "
                f"does not satisfy {node_type}'s reader"
            )
            assert resolved.get("conversation_key"), f"{s['key']}: no conversation key"


def test_every_trigger_in_the_registry_is_stageable_when_wired():
    """'Support every trigger': anything the platform recognises as one —
    dedicated trigger-* types, and provider nodes on an x-is-trigger operation
    — must appear in the offer when wired toward an agent. Fixtures use the
    FETCHED-graph shape (operation in the flat config blob): the cal.com
    report (2026-08-10) came from reading data.operation, a shape live graphs
    never have, so the generic fallback had never fired outside unit tests —
    the authored four masked it because presence needs no operation read."""
    from nodes.agent.node_op_tools import _trigger_operations
    from nodes.agent.rehearsal_scenarios import staged_for_graph
    from nodes.core.registry import NODE_REGISTRY

    missing = []
    checked = 0
    for node_type in NODE_REGISTRY:
        if node_type.startswith("trigger-"):
            op = None
        else:
            ops = sorted(_trigger_operations(node_type))
            if not ops:
                continue
            op = ops[0]  # the offer branch is identical per op of one type
        node: dict = {"id": "t1", "type": node_type}
        if op:
            node["config"] = {"operation": op}
        offered = {
            t["node_type"]
            for t in staged_for_graph(
                [{"id": "agent-1", "type": "agent"}, node],
                [{"source": "t1", "target": "agent-1", "targetHandle": "left"}],
            )
        }
        checked += 1
        if node_type not in offered:
            missing.append((node_type, op))
    assert checked > 20, "the registry sweep found suspiciously few trigger types"
    assert not missing, f"trigger types the picker cannot stage: {missing}"


def test_edited_staged_events_stay_real_and_survive_their_readers():
    """The card's pencil must edit the RUN, not just the display — and the
    edited payload must still parse through the node's own resolve_agent_event,
    or the edit trades a lying control for a broken turn."""
    from nodes.agent.rehearsal_scenarios import STAGED_SITUATIONS, apply_lead_patch
    from nodes.core.registry import NODE_REGISTRY

    edited_body = "We need SOC2 evidence collection automated. 200 seats. Budget approved."

    for node_type, situations in STAGED_SITUATIONS.items():
        original = situations[0]["scenario"]
        before = json.dumps(original.trigger_payload, sort_keys=True)
        patched = apply_lead_patch(node_type, original, {"body": edited_body})
        assert json.dumps(original.trigger_payload, sort_keys=True) == before, (
            f"{node_type}: the authored scenario was mutated — it is a module "
            f"singleton and the next rehearsal would inherit this edit"
        )
        assert edited_body in patched.scenario, "the mock world must know what was delivered"
        if node_type == "automation-gmail":
            assert patched.trigger_payload["body"] == edited_body
        else:
            resolved = NODE_REGISTRY[node_type].resolve_agent_event(patched.trigger_payload)
            assert edited_body in (resolved or {}).get("text", ""), (
                f"{node_type}: the edited body did not survive resolve_agent_event"
            )

    gmail = STAGED_SITUATIONS["automation-gmail"][0]["scenario"]
    g = apply_lead_patch(
        "automation-gmail",
        gmail,
        {
            "title": "Renewal question",
            "author": "Jordan Example",
            "handle": "jordan@sender.example",
        },
    )
    assert g.trigger_payload["subject"] == "Renewal question"
    assert g.trigger_payload["from"] == "Jordan Example <jordan@sender.example>"

    tg = apply_lead_patch(
        "automation-telegram",
        STAGED_SITUATIONS["automation-telegram"][0]["scenario"],
        {"author": "Jordan", "handle": "@jordanexample"},
    )
    assert tg.trigger_payload["message"]["from"]["first_name"] == "Jordan"
    assert tg.trigger_payload["message"]["from"]["username"] == "jordanexample"

    with pytest.raises(ValueError):
        apply_lead_patch("automation-gmail", gmail, {"subject": "wrong-namespace"})
    assert apply_lead_patch("automation-gmail", gmail, {"body": "  "}) is gmail

    # Generic samples ARE editable — the edit becomes the event, every field a
    # payload key delivered verbatim (the cal.com "can't edit" report).
    from nodes.agent.rehearsal_scenarios import make_generic_scenario

    generic = make_generic_scenario("automation-cal-com")
    ge = apply_lead_patch(
        "automation-cal-com",
        generic,
        {
            "body": edited_body,
            "title": "Booking rescheduled",
            "author": "Casey Example",
        },
    )
    assert ge.trigger_payload["content"] == edited_body
    assert ge.trigger_payload["subject"] == "Booking rescheduled"
    assert ge.trigger_payload["author"] == "Casey Example"
    assert ge.trigger_payload["staged"] is True
    assert edited_body in ge.scenario

    # ...but a provider-SHAPED payload with no mapping still refuses loudly —
    # flat keys stuffed into a shape its reader ignores would be a silent no-op.
    with pytest.raises(ValueError):
        apply_lead_patch("trigger-webhook", gmail, {"body": "x"})


def test_unmodelled_triggers_get_the_generic_sample():
    """"Support everything": a trigger type with no authored situation is still
    rehearsable — a generic staged event, delivered as raw JSON by the base
    resolve_agent_event, works for every trigger by construction."""
    from nodes.agent.rehearsal_scenarios import staged_for_graph

    nodes, edges = _wired_graph(
        {"type": "trigger-webhook"},
        {"type": "automation-github-rest", "config": {"operation": "on_push"}},
        # a provider node on a NON-trigger operation must not be offered
        {"type": "automation-github-rest", "config": {"operation": "list_repositories"}},
        # a provider node with no operation chosen could not fire for real either
        {"type": "automation-linear", "config": {}},
    )
    offered = staged_for_graph(nodes, edges)
    by_type = {t["node_type"]: [s["key"] for s in t["situations"]] for t in offered}
    assert by_type.get("trigger-webhook") == ["generic:trigger-webhook"]
    assert by_type.get("automation-github-rest") == ["generic:automation-github-rest"]
    assert "automation-linear" not in by_type
    assert "agent" not in by_type


def test_authored_situations_shadow_the_generic_fallback():
    """A telegram trigger gets its authored situation, never a duplicate
    generic group beside it."""
    from nodes.agent.rehearsal_scenarios import staged_for_graph

    offered = staged_for_graph(*_wired_graph({"type": "automation-telegram"}))
    assert len(offered) == 1
    assert [s["key"] for s in offered[0]["situations"]] == ["telegram-direct-lead"]


def test_generic_scenarios_are_runnable():
    from nodes.agent.rehearsal_scenarios import GENERIC_KEY_PREFIX, make_generic_scenario
    from nodes.agent.rehearsal import RehearsalScenario

    sc = make_generic_scenario("trigger-webhook")
    assert isinstance(sc, RehearsalScenario)
    assert sc.trigger_payload.get("staged") is True
    assert GENERIC_KEY_PREFIX == "generic:"


def test_empty_world_guard_is_narrow():
    """The fabricated world retries when a read comes back hollow — but a
    write's acknowledgement must pass untouched (the guard exists for the
    empty Slack digest of 2026-08-10, not to reroll every send)."""
    from nodes.agent.rehearsal import _looks_like_empty_world

    assert _looks_like_empty_world(None)
    assert _looks_like_empty_world({})
    assert _looks_like_empty_world([])
    assert _looks_like_empty_world({"status": "success", "data": None})
    assert _looks_like_empty_world({"data": []})
    assert not _looks_like_empty_world({"ok": True, "ts": "1723.4"})
    assert not _looks_like_empty_world({"data": {"messages": [{"text": "hi"}]}})
    assert not _looks_like_empty_world({"messages": []})  # no data envelope — not ours to judge


# ------------------------------------------------------- agent testing billing

RUNNER_ID = "11111111-1111-4111-8111-111111111111"
ORG_ID = "22222222-2222-4222-8222-222222222222"


@pytest.mark.asyncio
async def test_world_model_calls_bill_under_agent_testing(redis, monkeypatch):
    """Every fabricated answer charges the runner as Agent Testing usage:
    provider cost marked up at write time (platform floor), type ai_testing,
    subtype the versioned privacy sentinel — never the world model's name."""
    from decimal import Decimal

    await rh.start_rehearsal(
        "conv-bill", SCENARIO, user_id=RUNNER_ID, organization_id=ORG_ID
    )

    class Usage:
        cost = 0.001
        total_tokens = 500

    class Msg:
        content = json.dumps({"data": {"items": [1, 2, 3]}})

    class Choice:
        message = Msg()

    class Resp:
        choices = [Choice()]
        usage = Usage()

    async def fabricate(*a, **kw):
        # The call must request OpenRouter usage accounting, or cost never
        # rides back on the response.
        assert kw["extra_body"]["usage"] == {"include": True}
        return Resp()

    monkeypatch.setattr("litellm.acompletion", fabricate)

    events = []

    async def capture(event, **kw):
        events.append(event)

    from billing.usage_tracker import usage_tracker

    monkeypatch.setattr(usage_tracker, "track_usage_event", capture)

    await rh.mock_tool_call(
        conversation_id="conv-bill", tool_name="slack__send_message", arguments={}
    )

    assert len(events) == 1
    ev = events[0]
    assert ev.usage_type == "ai_testing"
    assert ev.usage_subtype == "noclick/testing-1"
    assert ev.user_id == RUNNER_ID
    assert ev.organization_id == ORG_ID
    # The floor markup itself is a deployment's commercial setting — 1 where the
    # operator runs on their own keys. What this pins is that it is applied.
    from billing.markup import PLATFORM_MIN_MARKUP

    assert ev.total_cost == Decimal("0.001") * PLATFORM_MIN_MARKUP
    assert ev.quantity == Decimal("500")
    assert "gpt-oss" in ev.metadata["_internal_model"]


@pytest.mark.asyncio
async def test_world_model_billing_never_kills_the_rehearsal(redis, monkeypatch):
    """A billing write failure logs and moves on — the demo is worth more
    than the fraction of a cent, and a runner-less state (tests, legacy)
    simply charges nobody."""
    await rh.start_rehearsal("conv-nouser", SCENARIO)  # no user_id

    monkeypatch.setattr("litellm.acompletion", _reply(json.dumps({"ok": True})))

    called = []

    async def boom(event, **kw):
        called.append(event)
        raise RuntimeError("billing down")

    from billing.usage_tracker import usage_tracker

    monkeypatch.setattr(usage_tracker, "track_usage_event", boom)

    # No user on the state: nothing attempted, call succeeds.
    result = await rh.mock_tool_call(
        conversation_id="conv-nouser", tool_name="slack__send_message", arguments={}
    )
    assert result == {"ok": True}
    assert called == []

    # With a user, a raising tracker still doesn't break the fabrication.
    await rh.start_rehearsal("conv-throw", SCENARIO, user_id=RUNNER_ID)
    result = await rh.mock_tool_call(
        conversation_id="conv-throw", tool_name="slack__send_message", arguments={}
    )
    assert result == {"ok": True}
    assert len(called) == 1


# ------------------------------------------- the public template-page model pin


def test_public_runs_pin_harness_agents_to_the_default_model():
    """An anonymous template-page run must be credential-free: CLI harnesses are
    strict-BYOK and the template owner ships no harness credential, so
    respecting the harness sent a keyless codex turn to OpenAI (401,
    2026-08-12). Every harness pins to the platform default SDK model."""
    from nodes.agent.config.llm import DEFAULT_LLM_AGENT_MODEL
    from nodes.agent.config.providers import WRAPPER_ID_BY_MODEL_TYPE
    from nodes.agent.rehearsal_launch import public_model_pin

    for model_type, wrapper_id in WRAPPER_ID_BY_MODEL_TYPE.items():
        # As templates store it: an explicit discriminator...
        pin = public_model_pin({"model": wrapper_id, "model_type": model_type})
        assert pin == {"model": DEFAULT_LLM_AGENT_MODEL, "model_type": "llm"}, model_type
        # ...and as legacy configs store it: inferred from the model string.
        pin = public_model_pin({"model": wrapper_id})
        assert pin == {"model": DEFAULT_LLM_AGENT_MODEL, "model_type": "llm"}, wrapper_id


def test_public_runs_pin_byok_sdk_models_but_not_openrouter():
    """A direct-provider SDK model needs the owner's key (ENV_MASK) just like a
    harness; openrouter/* already runs on the cost-captured platform key and
    keeps the template's configured model."""
    from nodes.agent.config.llm import DEFAULT_LLM_AGENT_MODEL
    from nodes.agent.rehearsal_launch import public_model_pin

    assert public_model_pin({"model": "anthropic/claude-sonnet-5"}) == {
        "model": DEFAULT_LLM_AGENT_MODEL,
        "model_type": "llm",
    }
    assert public_model_pin({"model": "openrouter/openai/gpt-5.6-luna"}) == {}
    assert public_model_pin({"model": "openrouter/moonshotai/kimi-k2"}) == {}
    # An unset model falls to the openrouter default — nothing to pin.
    assert public_model_pin({}) == {}


def test_public_runs_leave_media_agents_alone():
    """Media model types are flat-priced and credential-free; rewriting an
    image model to an LLM would produce nonsense, not a rehearsal."""
    from nodes.agent.rehearsal_launch import public_model_pin

    assert public_model_pin({"model": "gpt-image-1", "model_type": "image"}) == {}
    assert public_model_pin({"model": "kling-v2", "model_type": "kling"}) == {}
