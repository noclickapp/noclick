"""A tool NoClick's credit gate turned down (``guards.credit_refusal``) ends the turn after that round of calls, through
the real streamed SDK and PostgreSQL, for a run whose caller says how to wrap such a turn up (a ``FUNDS`` wrap-up): its
one wrap-up call, allowed no tool, says what the turn got done (``turn_closing``, never streamed), and the turn fails on
the gate's words, which its platform turns into its own refusal. Left running, a coordinator whose shell the gate
refused tried other tools and told its person it couldn't confirm the work, never that the account had run out
(2026-10-25). A run with no such wrap-up, and a command that only prints the gate's words, carry on as before."""

import json
from unittest.mock import AsyncMock

import pytest

from billing.exceptions import InsufficientBalanceError, insufficient_credits_message
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from tests.test_openai_agent_empty_answer import _deltas

pytestmark = pytest.mark.asyncio

CONVERSATION = "coordinator:out-of-funds"
GATE = insufficient_credits_message(0.9, 1.0)
REFUSED = {"error": f"Sandbox unavailable: {GATE} (what's left of the account's $1 of included usage today isn't "
                    "enough; it comes back at midnight UTC, in 45 minutes, or sooner once funds are added)"}
LINE = "Saving the bridge fix, then I'll check it in the browser."
CLOSING = "I saved the bridge fix, but couldn't check it in the browser."
PROMPT = "NoClick turned down a step: say what this turn got done."
WRAP_UP = {"funds": {"prompt": PROMPT}}


async def _run(pool, monkeypatch, script, results, *, wrap_up=WRAP_UP, closing=CLOSING, wrap_up_refused=False):
    """One turn whose model streams ``script``'s ``(text, tool or None)`` in order, each tool answering with
    ``results[tool]``, and whose wrap-up answers ``closing`` (or meets the gate itself, ``wrap_up_refused``): the
    streamed calls, the wrap-up calls (tool_choice, input), the tools run, what the turn emitted, the history it kept
    and the agent."""
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
    model_calls = []

    async def gate(*args, **kwargs):
        model_calls.append(1)
        if wrap_up_refused and len(model_calls) > len(script):
            raise InsufficientBalanceError(insufficient_credits_message(0.1, 0.2))

    monkeypatch.setattr(BillingHooks, "on_llm_start", gate)
    monkeypatch.setattr(BillingHooks, "_record_usage", AsyncMock())
    await pool.execute("DELETE FROM conversations WHERE conversation_id = $1", CONVERSATION)
    await pool.execute("INSERT INTO conversations(conversation_id, user_id, metadata) VALUES ($1, $2::uuid, '{}')",
                       CONVERSATION, USER)
    streamed, closings, ran, emitted = [], [], [], []

    def message(text, item):
        return ResponseOutputMessage(id=item, type="message", role="assistant", status="completed",
                                     content=[ResponseOutputText(type="output_text", text=text, annotations=[])])

    async def run_tool(name, arguments):
        ran.append(name)
        return results[name]

    class ModelDouble(Model):
        async def get_response(self, system_instructions, input, model_settings, *args, **kwargs):
            closings.append((model_settings.tool_choice, list(input)))
            return ModelResponse(output=[message(closing, "m-close")], usage=Usage(), response_id="r-close")

        async def stream_response(self, system_instructions, input, model_settings, *args, **kwargs):
            streamed.append(list(input))
            text, tool = script[len(streamed) - 1]
            item = f"m{len(streamed)}"
            output = [message(text, item)] if text else []
            if tool:
                output.append(ResponseFunctionToolCall(type="function_call", name=tool, call_id=f"c{len(streamed)}",
                                                       arguments="{}"))
            for event in _deltas(text, item):
                yield event
            response = Response.model_construct(id=f"r{len(streamed)}", created_at=0, model="test",
                                                object="response", output=output, status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=999)

    async def emit(event):
        emitted.append(event)

    tools = [{"type": "function", "function": {"name": name, "description": name,
                                               "parameters": {"type": "object", "properties": {}}}}
             for name in results]
    instance = await Agent.create(emit_message=emit, conversation_id=CONVERSATION, enable_persistence=True,
                                  user_id=USER, custom_tool_executor=run_tool, wrap_up=wrap_up,
                                  config=AgentConfiguration.from_kwargs(model="openrouter/openai/gpt-4o",
                                                                        system_prompt="Fix the game.",
                                                                        custom_tools=tools))
    instance._sdk_agent.model = ModelDouble()
    try:
        await instance({"content_items": [ContentItem(type="text", text="Make the bridge entry work.")]})
    finally:
        await instance.cleanup()
    stored = await pool.fetchval("SELECT metadata->'sdk_history' FROM conversations WHERE conversation_id = $1",
                                 CONVERSATION)
    return streamed, closings, ran, emitted, stored, instance


def _said(emitted):
    return "".join(e.message for e in emitted if getattr(e, "message", None) and getattr(e, "status", None) != "error")


def _failure(emitted):
    """The failure frames a turn ended on: (its chat line, its state's reason)."""
    chat = [e.message for e in emitted if getattr(e, "status", None) == "error"]
    state = [e.reason for e in emitted if getattr(e, "state", None) == "error"]
    return chat, state


async def test_a_tool_the_credit_gate_turns_down_ends_the_turn_on_the_gates_words(builder_request_db, monkeypatch):
    streamed, closings, ran, emitted, stored, instance = await _run(
        builder_request_db[0], monkeypatch, [(LINE, "save"), ("", "shell"), ("I'll try another way.", None)],
        {"save": {"success": True, "commit": "abc123"}, "shell": REFUSED})

    # The round the gate turned down was its last: no model call after it but the wrap-up, which may call no tool and
    # is told why it stops; the line it wrote is the turn's closing, never streamed.
    assert len(streamed) == 2 and ran == ["save", "shell"]
    [(choice, last)] = [(c, i[-1]) for c, i in closings]
    assert choice == "none" and last == {"role": "developer", "content": PROMPT}
    assert json.loads(closings[0][1][-2]["output"]) == REFUSED
    assert _said(emitted) == LINE and instance.turn_closing == CLOSING
    # It fails on the gate's own words, as a turn whose model call the gate refused does.
    assert _failure(emitted) == ([GATE], [GATE]) and emitted[-1].state == "error"
    assert instance.turn_ended_by == "funds" and instance._turn_guard.unfunded == GATE
    # The conversation keeps what it said, for its next turn.
    assert stored[-1]["role"] == "assistant" and stored[-1]["content"][0]["text"] == CLOSING


async def test_a_wrap_up_the_gate_turns_down_too_ends_on_its_words_alone(builder_request_db, monkeypatch):
    streamed, closings, ran, emitted, _, instance = await _run(
        builder_request_db[0], monkeypatch, [("", "shell")], {"shell": REFUSED}, wrap_up_refused=True)

    assert len(streamed) == 1 and closings == [] and instance.turn_closing is None
    assert _failure(emitted) == ([GATE], [GATE]) and instance.turn_ended_by == "funds"


async def test_a_turn_that_got_nothing_done_has_no_closing(builder_request_db, monkeypatch):
    *_, emitted, _, instance = await _run(builder_request_db[0], monkeypatch, [("", "shell")], {"shell": REFUSED},
                                          closing="")

    assert instance.turn_closing is None and _failure(emitted) == ([GATE], [GATE])


async def test_a_run_with_no_word_for_it_carries_on(builder_request_db, monkeypatch):
    """A workflow's agent node says nothing of such a turn: its model reads the refusal and answers, as before."""
    streamed, closings, ran, emitted, _, instance = await _run(
        builder_request_db[0], monkeypatch, [("", "shell"), ("The shell is out of credits.", None)],
        {"shell": REFUSED}, wrap_up={})

    assert len(streamed) == 2 and closings == [] and _said(emitted) == "The shell is out of credits."
    assert _failure(emitted) == ([], []) and instance.turn_ended_by is None


async def test_a_command_that_prints_the_gates_words_carries_on(builder_request_db, monkeypatch):
    """Only the tool's own error is the gate's refusal: a log the command printed may quote it."""
    printed = {"stdout": f"worker.log: {GATE}\n", "stderr": "", "exit_code": 0}
    streamed, _, _, emitted, _, instance = await _run(
        builder_request_db[0], monkeypatch, [("", "shell"), ("The worker logged a refusal yesterday.", None)],
        {"shell": printed})

    assert len(streamed) == 2 and _said(emitted) == "The worker logged a refusal yesterday."
    assert _failure(emitted) == ([], []) and instance.turn_ended_by is None
