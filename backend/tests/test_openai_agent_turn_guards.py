"""The guards that end an SDK agent turn before its model answers, through the real streamed SDK and PostgreSQL: the
step and time limits end it after the calls in hand, wrapped up the same way (one more model call, allowed no tool,
and the guard's line after it), or, given no wrap-up, on that line alone; each records which guard it was. A call
repeated with the same arguments and the same result is nudged the third time and refused after that, while a poll
whose result changes never is. The spend ceiling, which reads what the hosted billing hooks priced, is
``cloud/tests/test_openai_agent_spend_ceiling.py``'s."""

import json

import pytest

from tests.test_builder_requests import USER, builder_request_db  # noqa: F401

pytestmark = pytest.mark.asyncio

CONVERSATION = "coordinator:turn-guards"
STANDING = "Read three pages of logs: the deploy needs a package.json. The fix isn't committed yet."
WRAP_UP = {reason: {"prompt": f"Out of {reason}: say where things stand.", "line": f"Stopped on {reason}."}
           for reason in ("steps", "spend", "time")}


class _Spans:
    """A tracer that keeps the spans it starts."""

    def __init__(self):
        self.spans = []

    def start_span(self, name, start_time=None):
        spans = self.spans

        class Span:
            def __init__(self):
                self.name, self.attributes, self.ended = name, {}, False
                spans.append(self)

            def set_attribute(self, key, value):
                self.attributes[key] = value

            def end(self):
                self.ended = True

        return Span()


async def _run(pool, monkeypatch, *, limits, wrap_up=WRAP_UP, call=None, results=None, cost=None, tick_s=0.0,
               answer_after=None, hang_at=None, wrap_up_hangs=False, so_far=None):
    """One turn of an agent whose model calls ``look`` with ``call(n)``'s arguments (by default a new page each
    time) until it's allowed no tool, or until ``answer_after(input)`` says it's seen enough. ``results(n)`` is
    what the tool's nth call returns; each tool call moves the turn's clock ``tick_s`` on. With a ``cost``, each
    model call reports it to the run's billing hooks (whose own work the caller fakes); without, there are none.
    The ``hang_at``th model call, and the wrap-up with ``wrap_up_hangs``, never answer. ``so_far``: how far the turn
    had gone before this run of it (another process's, on a wall clock 49,000s ahead of the turn's).
    Returns (model calls as (tool_choice, input), tool calls, emitted frames, agent, spans)."""
    import asyncio
    from agents.items import ModelResponse
    from agents.models.interface import Model
    from agents.usage import Usage
    from openai.types.responses import (
        Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
    )
    from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails, ResponseUsage

    from coder.openai_agent import Agent, guards
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    if cost is None:
        monkeypatch.setattr(Agent, "_build_billing_hooks", lambda self: None)
    clock = {"now": 1000.0}
    monkeypatch.setattr(guards, "_now", lambda: clock["now"])
    monkeypatch.setattr(guards, "_wall", lambda: clock["now"] + 49_000.0)
    spans = _Spans()
    monkeypatch.setattr("utils.otel.get_tracer", lambda name: spans)
    await pool.execute("DELETE FROM conversations WHERE conversation_id = $1", CONVERSATION)
    await pool.execute("INSERT INTO conversations(conversation_id, user_id, metadata) VALUES ($1, $2::uuid, '{}')",
                       CONVERSATION, USER)
    calls, looked, emitted = [], [], []
    call = call or (lambda n: {"page": n})
    results = results or (lambda n: {"lines": [f"page {n} of the logs"]})

    async def look(name, arguments):
        looked.append(arguments)
        clock["now"] += tick_s
        return results(len(looked))

    usage = ResponseUsage(input_tokens=100, output_tokens=10, total_tokens=110,
                          input_tokens_details=InputTokensDetails(cached_tokens=0),
                          output_tokens_details=OutputTokensDetails(reasoning_tokens=0))

    def message(text):
        return ResponseOutputMessage(id="m", type="message", role="assistant", status="completed",
                                     content=[ResponseOutputText(type="output_text", text=text, annotations=[])])

    class ModelDouble(Model):
        """Calls ``look`` whenever it may, until it has seen enough; answers only when it may not."""

        async def get_response(self, system_instructions, input, model_settings, *args, **kwargs):
            calls.append((model_settings.tool_choice, list(input)))
            if wrap_up_hangs:
                await asyncio.Event().wait()
            return ModelResponse(output=[message(STANDING)], usage=Usage(), response_id="r-close")

        async def stream_response(self, system_instructions, input, model_settings, *args, **kwargs):
            calls.append((model_settings.tool_choice, list(input)))
            n = len(calls)
            if n == hang_at:
                await asyncio.Event().wait()
            if answer_after and answer_after(list(input)):
                output = [message("Done: nothing else to look at.")]
            else:
                output = [ResponseFunctionToolCall(type="function_call", name="look", call_id=f"c{n}",
                                                   arguments=json.dumps(call(n)))]
            response = Response.model_construct(id=f"r{n}", created_at=0, model="test", object="response",
                                                output=output, status="completed", usage=usage)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    async def emit(event):
        emitted.append(event)

    tool = {"type": "function", "function": {"name": "look", "description": "Read the logs",
                                             "parameters": {"type": "object", "properties": {}}}}
    instance = await Agent.create(emit_message=emit, conversation_id=CONVERSATION, enable_persistence=True,
                                  user_id=USER, custom_tool_executor=look, wrap_up=wrap_up, limits=limits,
                                  so_far=so_far,
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt="Fix it.",
                                                                        custom_tools=[tool]))
    instance._sdk_agent.model = ModelDouble()
    if cost is not None:
        instance._sdk_model._call_cost, instance._sdk_model._call_cost_reported = cost, True
    try:
        await instance({"content_items": [ContentItem(type="text", text="Why did the deploy fail?")]})
    finally:
        await instance.cleanup()
    return calls, looked, emitted, instance, spans.spans


def _said(emitted):
    return "".join(e.message for e in emitted if getattr(e, "message", None) and getattr(e, "status", None) != "error")


def _failed(emitted):
    return [e for e in emitted if getattr(e, "status", None) == "error" or getattr(e, "state", None) == "error"]


def _outputs(model_input):
    return [item["output"] for item in model_input if item.get("type") == "function_call_output"]


async def _stored(pool):
    return await pool.fetchval("SELECT metadata->'sdk_history' FROM conversations WHERE conversation_id = $1",
                               CONVERSATION)


async def test_the_time_limit_ends_the_turn_after_the_call_that_ran_it_out(builder_request_db, monkeypatch):
    from coder.openai_agent.guards import TurnLimits

    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(pool, monkeypatch, tick_s=400.0,
                                                      limits=TurnLimits(steps=10, minutes=15))

    # The third tool call takes the turn to 20 minutes: no model call after it but the closing one, which reads
    # all three results.
    assert [choice for choice, _ in calls] == [None, None, None, "none"] and len(looked) == 3
    assert calls[-1][1][-1] == {"role": "developer", "content": WRAP_UP["time"]["prompt"]}
    assert len(_outputs(calls[-1][1])) == 3
    assert _said(emitted) == f"{STANDING}\n\nStopped on time." and not _failed(emitted)
    assert emitted[-1].finished is True and agent.turn_ended_by == "time"
    # The reply is stored as the person read it, the line included.
    stored = await _stored(pool)
    assert stored[-1]["role"] == "assistant" and stored[-1]["content"][0]["text"] == f"{STANDING}\n\nStopped on time."
    [span] = spans
    assert span.name == "agent.turn" and span.ended
    assert span.attributes["agent.turn.ended_by"] == "time" and span.attributes["agent.turn.model_calls"] == 4


async def test_the_step_limit_ends_the_turn_the_same_way(builder_request_db, monkeypatch):
    from coder.openai_agent.guards import TurnLimits

    pool = builder_request_db[0]
    calls, looked, emitted, agent, _ = await _run(pool, monkeypatch, limits=TurnLimits(steps=2))

    assert [choice for choice, _ in calls] == [None, None, "none"] and len(looked) == 2
    assert calls[-1][1][-1] == {"role": "developer", "content": WRAP_UP["steps"]["prompt"]}
    assert _said(emitted) == f"{STANDING}\n\nStopped on steps." and agent.turn_ended_by == "steps"


async def test_without_a_wrap_up_a_guard_ends_the_turn_on_one_plain_line(builder_request_db, monkeypatch):
    from coder.openai_agent.guards import TurnLimits

    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(pool, monkeypatch, wrap_up=None, tick_s=400.0,
                                                      limits=TurnLimits(steps=10, minutes=15))

    # No closing call: the turn fails on the line, never the run's raw error.
    assert [choice for choice, _ in calls] == [None, None, None] and len(looked) == 3
    line = "I stopped here: this turn ran for 15 minutes, its time limit."
    [message, state] = _failed(emitted)
    assert (message.message, message.finished, state.reason) == (line, True, line)
    assert not _said(emitted) and agent.turn_ended_by == "time"
    assert spans[0].attributes["agent.turn.ended_by"] == "time"


async def test_a_call_that_never_answers_is_ended_by_the_clock(builder_request_db, monkeypatch):
    """A site build's turn ran a shell call, then its next model call never answered: with its limits checked only
    as a call ends, the turn hung, holding the conversation, and never told the owner the site was live
    (2026-10-25). The time limit is kept by the clock: a call still holding the run past it is cancelled, and the
    turn wraps up as any guard ends it."""
    from coder.openai_agent import guards
    from coder.openai_agent.guards import TurnLimits

    monkeypatch.setattr(guards, "OVERDUE_S", 0.05)
    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(pool, monkeypatch, hang_at=2,
                                                      limits=TurnLimits(steps=10, minutes=0.001))

    assert [choice for choice, _ in calls] == [None, None, "none"] and len(looked) == 1
    assert _said(emitted) == f"{STANDING}\n\nStopped on time." and not _failed(emitted)
    assert emitted[-1].finished is True and agent.turn_ended_by == "time"
    assert spans[0].attributes["agent.turn.ended_by"] == "time"
    # Its clock stops with it.
    assert agent._turn_guard._timers == []


async def test_a_wrap_up_that_never_answers_ends_the_turn_on_its_line(builder_request_db, monkeypatch):
    from coder.openai_agent import guards
    from coder.openai_agent.guards import TurnLimits

    monkeypatch.setattr(guards, "OVERDUE_S", 0.05)
    monkeypatch.setattr(guards, "WRAP_UP_S", 0.1)
    pool = builder_request_db[0]
    calls, looked, emitted, agent, _ = await _run(pool, monkeypatch, hang_at=2, wrap_up_hangs=True,
                                                  limits=TurnLimits(steps=10, minutes=0.001))

    assert [choice for choice, _ in calls] == [None, None, "none"]
    # As a turn with no wrap-up ends: on its one plain line.
    [message, state] = _failed(emitted)
    assert message.message == guards.stopped_line("time", TurnLimits(steps=10, minutes=0.001)) == state.reason
    assert message.finished is True and agent.turn_ended_by == "time"


async def test_a_guard_that_trips_on_the_answer_ends_nothing(builder_request_db, monkeypatch):
    from coder.openai_agent.guards import TurnLimits

    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(
        pool, monkeypatch, limits=TurnLimits(steps=3),
        answer_after=lambda model_input: len(_outputs(model_input)) == 2)

    # The third call is the answer: the turn ended because the model did, not the limit.
    assert [choice for choice, _ in calls] == [None, None, None] and len(looked) == 2
    assert _said(emitted) == "Done: nothing else to look at." and agent.turn_ended_by is None
    assert "agent.turn.ended_by" not in spans[0].attributes


async def test_a_call_repeated_with_the_same_result_is_nudged_then_refused(builder_request_db, monkeypatch):
    from coder.openai_agent.guards import TurnLimits

    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(
        pool, monkeypatch, limits=TurnLimits(steps=10), call=lambda n: {"page": 1},
        results=lambda n: {"lines": ["the same page"]},
        answer_after=lambda model_input: any(o.startswith("Not run") for o in _outputs(model_input)))

    # The tool ran three times; the third result carried the nudge, the fourth call never ran, then the answer.
    assert len(looked) == 3 and len(calls) == 5
    outputs = _outputs(calls[-1][1])
    assert '"the same page"' in outputs[0] and "Calling it again" not in outputs[1]
    assert outputs[2].startswith("You've called look with these same arguments 3 times this turn")
    assert '"the same page"' in outputs[2] and "do something different, or answer" in outputs[2]
    assert outputs[3].startswith("Not run: look already returned the same result 3 times")
    assert _said(emitted) == "Done: nothing else to look at." and agent.turn_ended_by is None
    assert (spans[0].attributes["agent.turn.loop_nudges"], spans[0].attributes["agent.turn.loop_refusals"]) == (1, 1)


async def test_a_poll_whose_result_changes_is_never_nudged(builder_request_db, monkeypatch):
    from coder.openai_agent.guards import TurnLimits

    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(
        pool, monkeypatch, limits=TurnLimits(steps=10), call=lambda n: {"operation": "op_1"},
        results=lambda n: {"status": "running" if n < 5 else "succeeded", "progress": n},
        answer_after=lambda model_input: len(_outputs(model_input)) == 5)

    assert len(looked) == 5 and _said(emitted) == "Done: nothing else to look at."
    assert not any(o.startswith(("You've called", "Not run")) for o in _outputs(calls[-1][1]))
    assert (spans[0].attributes["agent.turn.loop_nudges"], spans[0].attributes["agent.turn.loop_refusals"]) == (0, 0)


# ── a turn a restart handed to another process ──────────────────────────────


async def test_the_running_turns_guard_says_how_far_it_has_gone(builder_request_db, monkeypatch):
    """What a platform reads of a turn as a shutdown stops it, to hand it on (``gone_so_far``): its first run's start
    on the clock processes share, and the steps it has used."""
    from coder.openai_agent import guards
    from coder.openai_agent.guards import TurnLimits, TurnSoFar

    pool = builder_request_db[0]
    seen = []

    def results(n):
        seen.append(guards.gone_so_far(CONVERSATION))
        return {"lines": [f"page {n} of the logs"]}

    await _run(pool, monkeypatch, limits=TurnLimits(steps=2), results=results, tick_s=30.0)
    assert seen == [TurnSoFar(started_at=50_000.0, steps=1), TurnSoFar(started_at=50_000.0, steps=2)]
    assert guards.gone_so_far(CONVERSATION) is None  # over: nothing runs there


async def test_a_run_a_restart_handed_over_meets_the_turns_limits_where_it_stood(builder_request_db, monkeypatch):
    """A deploy hands a running turn to another process, which runs it on from what its thread kept. Run afresh, its
    guard gave it a whole new time limit and step budget, and turns crossing a deploy ran well past their limits
    (2026-10-26): seeded with how far the turn had gone (``TurnSoFar``), the run's guard counts on from there."""
    from coder.openai_agent.guards import TurnLimits, TurnSoFar

    pool = builder_request_db[0]
    # Three of its five steps used: two are left, then it wraps up.
    calls, looked, emitted, agent, spans = await _run(pool, monkeypatch, limits=TurnLimits(steps=5),
                                                      so_far=TurnSoFar(started_at=50_000.0, steps=3))
    assert [choice for choice, _ in calls] == [None, None, "none"] and len(looked) == 2
    assert _said(emitted) == f"{STANDING}\n\nStopped on steps." and agent.turn_ended_by == "steps"
    assert spans[0].attributes["agent.turn.model_calls"] == 6

    # Begun 14 of its 15 minutes before this run: the first two-minute call runs it out.
    calls, looked, emitted, agent, spans = await _run(pool, monkeypatch, tick_s=120.0,
                                                      limits=TurnLimits(steps=10, minutes=15),
                                                      so_far=TurnSoFar(started_at=50_000.0 - 14 * 60))
    assert [choice for choice, _ in calls] == [None, "none"] and len(looked) == 1
    assert _said(emitted) == f"{STANDING}\n\nStopped on time." and agent.turn_ended_by == "time"


async def test_a_later_turn_of_the_same_agent_starts_fresh(builder_request_db, monkeypatch):
    """How far a handed-over turn had gone seeds that turn's run alone."""
    from coder.openai_agent.guards import TurnLimits, TurnSoFar

    pool = builder_request_db[0]
    *_, agent, _ = await _run(pool, monkeypatch, limits=TurnLimits(steps=5),
                              so_far=TurnSoFar(started_at=50_000.0, steps=3),
                              answer_after=lambda model_input: True)
    assert agent._so_far is None and agent._turn_guard.model_calls == 4


async def test_a_run_a_restart_handed_over_keeps_its_read_streak(builder_request_db, monkeypatch):
    """Calls in a row that only read count on across a restart too (``guards.STALLED``): run afresh, a turn reading
    on through a deploy got a whole new stretch of reads."""
    from coder.openai_agent import guards, progress
    from coder.openai_agent.guards import TurnLimits, TurnSoFar

    monkeypatch.setattr(progress, "_JUDGES", [lambda tool, args: True if tool == "look" else None])
    monkeypatch.setattr(guards, "QUIET_STOP", 5)
    stalled = {**WRAP_UP, "stalled": {"prompt": "Out of stalled: say what blocks you.", "line": "Stopped on stalled."}}
    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(pool, monkeypatch, wrap_up=stalled, limits=TurnLimits(steps=20),
                                                      so_far=TurnSoFar(started_at=50_000.0, steps=4, quiet=4))
    # Four reads in a row before the restart: the next is the fifth, which stops it.
    assert len(looked) == 1 and agent.turn_ended_by == "stalled"
    assert spans[0].attributes["agent.turn.longest_read_streak"] == 5
