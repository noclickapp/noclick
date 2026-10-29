"""A tool whose result hands the turn's work on (``guards.ENDS_TURN``: a wake-up set on work still running) ends the
turn after that round of calls, through the real streamed SDK and PostgreSQL. Left running, a site build's turns
polled the deploy, set the wake-up they already had again after each look and closed on one more line about work
their person already knew was under way ("The site is underway.", 2026-10-25). A turn that hasn't said anything yet
still gets to say its line, unless the result lets it end with nothing (``SILENTLY``: nobody waits on its words); and
a turn ended this way is no guard's: no wrap-up, no stopped line, no empty-answer note.

Left to say that line by itself, a texted "Ok" turn that set wake_me on its site's check before writing a word made one
more call and answered with nothing twice, and ended with no reply (2026-10-28). Given a ``HANDED_ON`` wrap-up (its
caller's: someone waits on the turn's words), such a turn ends at the round that handed its work on and says its line
in one closing call, tools off."""

import json
from unittest.mock import AsyncMock

import pytest

from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from tests.test_openai_agent_empty_answer import _deltas

pytestmark = pytest.mark.asyncio

CONVERSATION = "coordinator:handed-on"
LINE = "I'm building your bakery's site now; it should take about 5 minutes."
CLOSING = "The site is underway."
NOTE = "Your last response was empty."
WRAP_UP = {reason: {"prompt": "Say where the work stands."} for reason in ("steps", "spend", "time")}


async def _run(pool, monkeypatch, script, results, *, wrap_up=None, closing=None, closes=None):
    """One turn whose model answers with ``script``'s ``(text, tool or None)`` in order, each tool answering with
    ``results[tool]``: the model calls made, the tools run, what the turn said and the history it kept. ``wrap_up``
    replaces the limits' (``WRAP_UP``); a closing call (tools off) answers ``closing``, its settings and input kept in
    ``closes``."""
    from agents.items import ModelResponse
    from agents.models.interface import Model
    from agents.usage import Usage
    from openai.types.responses import (
        Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
    )

    from coder.openai_agent import Agent
    from coder.openai_agent.billing import BillingHooks
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    monkeypatch.setattr(BillingHooks, "on_llm_start", AsyncMock())
    monkeypatch.setattr(BillingHooks, "_record_usage", AsyncMock())
    await pool.execute("INSERT INTO conversations(conversation_id, user_id, metadata) VALUES ($1, $2::uuid, '{}') "
                       "ON CONFLICT DO NOTHING", CONVERSATION, USER)
    calls, ran, emitted = [], [], []

    async def run_tool(name, arguments):
        ran.append(name)
        return results[name]

    class ModelDouble(Model):
        async def get_response(self, system_instructions, input, model_settings, *args, **kwargs):
            assert closing is not None, "Expected streaming"
            closes.append((model_settings.tool_choice, list(input)))
            reply = ResponseOutputMessage(id="closing", type="message", role="assistant", status="completed",
                                          content=[ResponseOutputText(type="output_text", text=closing,
                                                                      annotations=[])])
            return ModelResponse(output=[reply], usage=Usage(), response_id="r-closing")

        async def stream_response(self, system_instructions, input, model_settings, *args, **kwargs):
            calls.append(list(input))
            text, tool = script[len(calls) - 1]
            item = f"m{len(calls)}"
            output = [ResponseOutputMessage(id=item, type="message", role="assistant", status="completed",
                                            content=[ResponseOutputText(type="output_text", text=text,
                                                                        annotations=[])])]
            if tool:
                output.append(ResponseFunctionToolCall(type="function_call", name=tool, call_id=f"c{len(calls)}",
                                                       arguments="{}"))
            for event in _deltas(text, item):
                yield event
            response = Response.model_construct(id=f"r{len(calls)}", created_at=0, model="test", object="response",
                                                output=output, status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=999)

    async def emit(event):
        emitted.append(event)

    tools = [{"type": "function", "function": {"name": name, "description": name,
                                               "parameters": {"type": "object", "properties": {}}}}
             for name in results]
    instance = await Agent.create(emit_message=emit, conversation_id=CONVERSATION, enable_persistence=True,
                                  user_id=USER, custom_tool_executor=run_tool, empty_answer=NOTE,
                                  wrap_up=wrap_up or WRAP_UP,
                                  config=AgentConfiguration.from_kwargs(model="openrouter/openai/gpt-4o",
                                                                        system_prompt="Build the site.",
                                                                        custom_tools=tools))
    instance._sdk_agent.model = ModelDouble()
    try:
        await instance({"content_items": [ContentItem(type="text", text="Make me a bakery site.")]})
    finally:
        await instance.cleanup()
    assert not [e for e in emitted if getattr(e, "status", None) == "error" or getattr(e, "state", None) == "error"]
    assert emitted[-1].finished is True and instance.turn_ended_by is None
    stored = await pool.fetchval("SELECT metadata->'sdk_history' FROM conversations WHERE conversation_id = $1",
                                 CONVERSATION)
    return calls, ran, "".join(e.message for e in emitted if getattr(e, "message", None)), stored, instance


def _wake(ends):
    return {"success": True, "wakeup_id": "w1", "operation_id": "op1", "message": "You'll take a turn here once it "
            "finishes.", "ends_turn": ends}


async def test_a_turn_that_said_what_its_doing_ends_once_it_waits_on_the_work(builder_request_db, monkeypatch):
    pool = builder_request_db[0]
    script = [(LINE, "deploy"), ("", "wake_me"), (CLOSING, None)]
    calls, ran, said, stored, instance = await _run(pool, monkeypatch, script, {
        "deploy": {"success": True, "operation_id": "op1", "status": "queued"}, "wake_me": _wake(True)})

    # The round that set the wake-up was its last: no model call after it, so no closing line and no note.
    assert len(calls) == 2 and ran == ["deploy", "wake_me"] and said == LINE
    assert instance._turn_guard.handed_on is True
    # The conversation keeps the call and its result, for the turn the wake-up starts.
    assert stored[-1]["type"] == "function_call_output" and json.loads(stored[-1]["output"])["ends_turn"] is True
    assert not any(item == {"role": "developer", "content": NOTE} for item in stored)


async def test_a_turn_that_has_said_nothing_still_says_its_line(builder_request_db, monkeypatch):
    calls, ran, said, _, instance = await _run(builder_request_db[0], monkeypatch,
                                               [("", "deploy"), ("", "wake_me"), (LINE, None)],
                                               {"deploy": {"success": True}, "wake_me": _wake(True)})

    assert len(calls) == 3 and ran == ["deploy", "wake_me"] and said == LINE
    assert instance._turn_guard.handed_on is False


HANDED_ON_WRAP_UP = {**WRAP_UP, "handed_on": {"prompt": "Say in one line what's under way."}}


async def test_a_turn_someone_waits_on_says_its_line_in_one_closing_call(builder_request_db, monkeypatch):
    """The texted "Ok" turn: its work handed on before it said a word, it ends at that round, and its one closing call
    (tools off, told why) says the line; a model left to it made another call and answered with nothing."""
    pool, closes = builder_request_db[0], []
    calls, ran, said, stored, instance = await _run(
        pool, monkeypatch, [("", "check"), ("", "wake_me"), ("", "search")],
        {"check": {"success": True}, "wake_me": _wake(True), "search": {"success": True}},
        wrap_up=HANDED_ON_WRAP_UP, closing=LINE, closes=closes)

    assert len(calls) == 2 and ran == ["check", "wake_me"]
    [(tool_choice, closing_input)] = closes
    assert tool_choice == "none"
    assert closing_input[-1] == {"role": "developer", "content": "Say in one line what's under way."}
    assert said == LINE and instance.turn_handed_on is True and instance.turn_ended_by is None
    # The line is the turn's reply in its history, with no empty-answer note beside it.
    assert stored[-1]["role"] == "assistant" and stored[-1]["content"][0]["text"] == LINE
    assert not any(item == {"role": "developer", "content": NOTE} for item in stored)


async def test_a_closing_call_that_says_nothing_ends_the_turn_without_a_line(builder_request_db, monkeypatch):
    """Nothing is made up for it: the turn ends with no words, handed on, never failed."""
    calls, ran, said, _, instance = await _run(
        builder_request_db[0], monkeypatch, [("", "wake_me")], {"wake_me": _wake(True)},
        wrap_up=HANDED_ON_WRAP_UP, closing="", closes=[])

    assert len(calls) == 1 and ran == ["wake_me"] and said == ""
    assert instance.turn_handed_on is True and instance.turn_ended_by is None


async def test_a_turn_that_said_its_line_or_nobody_waits_on_gets_no_closing_call(builder_request_db, monkeypatch):
    said_first = await _run(builder_request_db[0], monkeypatch, [(LINE, "deploy"), ("", "wake_me")],
                            {"deploy": {"success": True}, "wake_me": _wake(True)}, wrap_up=HANDED_ON_WRAP_UP)
    nobody = await _run(builder_request_db[0], monkeypatch, [("", "check"), ("", "wake_me")],
                        {"check": {"success": True}, "wake_me": _wake("silently")}, wrap_up=HANDED_ON_WRAP_UP)

    # No closing call was made: the model double refuses one.
    assert said_first[2] == LINE and said_first[4].turn_handed_on is True
    assert nobody[2] == "" and nobody[4].turn_handed_on is True


async def test_a_turn_nobody_waits_on_ends_with_nothing(builder_request_db, monkeypatch):
    calls, ran, said, _, instance = await _run(builder_request_db[0], monkeypatch,
                                               [("", "check"), ("", "wake_me"), (CLOSING, None)],
                                               {"check": {"success": True}, "wake_me": _wake("silently")})

    assert len(calls) == 2 and ran == ["check", "wake_me"] and said == ""
    assert instance._turn_guard.handed_on is True


async def test_a_result_that_hands_nothing_on_lets_the_turn_go_on(builder_request_db, monkeypatch):
    """A wake-up on work already over answers with its outcome, and the turn goes on from it."""
    calls, ran, said, _, instance = await _run(builder_request_db[0], monkeypatch,
                                               [(LINE, "wake_me"), ("It's live.", None)],
                                               {"wake_me": {"success": True, "status": "succeeded"}})

    assert len(calls) == 2 and said == f"{LINE}\n\nIt's live." and instance._turn_guard.handed_on is False


STOPPED_WRAP_UP = {**WRAP_UP, "stopped": {"prompt": "Say where the work stands."}}
STANDS = "The site is live at https://crumb.example.site; its form isn't checked yet."


def _refused():
    return {"success": False, "error": "You've woken yourself 25 times in a row on work you set going.",
            "ends_turn": "stopped"}


async def test_a_result_that_stops_the_work_ends_the_turn_and_its_closing_call_says_where_it_stands(
        builder_request_db, monkeypatch):
    """A woken site build refused its next wake-up was free to end saying nothing, and did; its owner never heard it
    stopped (2026-10-29). A result that stops the work (``STOPPED``) ends the turn at that round, and its one closing
    call, tools off, says where the work stands, whatever the turn said before it."""
    pool, closes = builder_request_db[0], []
    calls, ran, said, stored, instance = await _run(
        pool, monkeypatch, [("Checking the deploy.", "check"), ("", "wake_me"), ("", "check")],
        {"check": {"success": True}, "wake_me": _refused()}, wrap_up=STOPPED_WRAP_UP, closing=STANDS, closes=closes)

    assert len(calls) == 2 and ran == ["check", "wake_me"]
    [(tool_choice, closing_input)] = closes
    assert tool_choice == "none" and closing_input[-1] == {"role": "developer", "content": "Say where the work stands."}
    assert said.endswith(STANDS) and instance._turn_guard.stopped_work is True
    # Neither a limit nor work handed on: the platform reads it as an ordinary reply.
    assert instance.turn_ended_by is None and instance.turn_handed_on is False
    assert stored[-1]["role"] == "assistant" and stored[-1]["content"][0]["text"] == STANDS


async def test_without_a_stopped_wrap_up_the_turn_reads_the_refusal_and_goes_on(builder_request_db, monkeypatch):
    """A caller that gives no ``STOPPED`` wrap-up (a workflow's agent node) keeps its turn: the model reads the
    refusal and answers."""
    calls, ran, said, _, instance = await _run(builder_request_db[0], monkeypatch,
                                               [("", "wake_me"), (STANDS, None)], {"wake_me": _refused()})

    assert len(calls) == 2 and ran == ["wake_me"] and said == STANDS
    assert instance._turn_guard.stopped_work is False
