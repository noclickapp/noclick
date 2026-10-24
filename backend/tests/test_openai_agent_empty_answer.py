"""A model answer with nothing in it (no words, no call) is final to the SDK, so it ended the turn where it stood. The
coordinator wrote "I'll update the menu price and the order total, then redeploy" beside its first reads, answered
the reads with nothing, and nothing was ever updated (2026-10-24); a turn that had said nothing yet ended with no
reply at all. With ``empty_answer`` (the platform's note) the run is told so once and runs on, through the real
streamed SDK and PostgreSQL: its tools run, its words follow the earlier ones as a paragraph of their own, the note
stays in the conversation's history, and a second empty answer ends the turn as before. Without it, an empty answer
ends the turn."""

from unittest.mock import AsyncMock

import pytest

from tests.test_builder_requests import USER, builder_request_db  # noqa: F401

pytestmark = pytest.mark.asyncio

CONVERSATION = "coordinator:empty-answer"
NOTE = "Your last response was empty. Carry on, or end without a word."
FIRST = "I'll update the price on the menu and in each order's total, then redeploy."
LAST = "Done: horchata is $3.75 on the menu and in every order's total."


def _deltas(text: str, item: str):
    from openai.types.responses import ResponseTextDeltaEvent

    return [ResponseTextDeltaEvent.model_construct(type="response.output_text.delta", delta=text[i:i + 9], item_id=item,
                                                   output_index=0, content_index=0, sequence_number=i, logprobs=[])
            for i in range(0, len(text), 9)]


async def _run(pool, monkeypatch, script, *, empty_answer, first_call_effort=None):
    """One turn whose model answers with ``script``'s responses in order, each ``(text, tool or None)``: ``("", None)``
    is an answer with nothing in it. The model calls made (their settings and input), the tools run and what the
    turn emitted."""
    from agents.models.interface import Model
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
        return {"ok": True}

    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, model_settings, *args, **kwargs):
            calls.append((model_settings, list(input)))
            text, tool = script[len(calls) - 1]
            item = f"m{len(calls)}"
            # An empty answer is an assistant message with no text, as production's model sends it.
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
             for name in ("read_file", "commit")]
    instance = await Agent.create(emit_message=emit, conversation_id=CONVERSATION, enable_persistence=True,
                                  user_id=USER, custom_tool_executor=run_tool, empty_answer=empty_answer,
                                  first_call_effort=first_call_effort,
                                  config=AgentConfiguration.from_kwargs(model="openrouter/openai/gpt-4o",
                                                                        system_prompt="Run the site.",
                                                                        custom_tools=tools))
    instance._sdk_agent.model = ModelDouble()
    try:
        await instance({"content_items": [ContentItem(type="text", text="Horchata is $3.75 now.")]})
    finally:
        await instance.cleanup()
    assert not [e for e in emitted if getattr(e, "status", None) == "error" or getattr(e, "state", None) == "error"]
    assert emitted[-1].finished is True
    return calls, ran, "".join(e.message for e in emitted if getattr(e, "message", None))


async def test_a_turn_whose_model_answers_with_nothing_is_told_so_and_carries_on(builder_request_db, monkeypatch):
    pool = builder_request_db[0]
    script = [(FIRST, "read_file"), ("", None), ("", "commit"), (LAST, None)]
    calls, ran, said = await _run(pool, monkeypatch, script, empty_answer=NOTE, first_call_effort="low")

    # Its empty answer to the read got the note, last in the next call's input; then the commit ran and it answered.
    assert len(calls) == 4 and ran == ["read_file", "commit"]
    assert calls[2][1][-1] == {"role": "developer", "content": NOTE}
    assert not any(item == {"role": "developer", "content": NOTE} for _, sent in calls[:2] for item in sent)
    # Its words follow the earlier line as a paragraph of their own.
    assert said == f"{FIRST}\n\n{LAST}"
    # Only the turn's first call reasons at the effort someone waiting gets; carrying on reasons as the model does.
    efforts = [(settings.extra_body or {}).get("reasoning") for settings, _ in calls]
    assert efforts == [{"effort": "low"}, None, None, None]
    # The note is in the conversation's history, where the turn's later calls (and the next turn) read it.
    stored = await pool.fetchval("SELECT metadata->'sdk_history' FROM conversations WHERE conversation_id = $1",
                                 CONVERSATION)
    assert {"role": "developer", "content": NOTE} in stored
    assert stored[-1]["role"] == "assistant" and stored[-1]["content"][0]["text"] == LAST


async def test_it_carries_on_once_and_a_second_empty_answer_ends_the_turn(builder_request_db, monkeypatch):
    calls, ran, said = await _run(builder_request_db[0], monkeypatch, [(FIRST, "read_file"), ("", None), ("", None)],
                                  empty_answer=NOTE)

    assert len(calls) == 3 and ran == ["read_file"] and said == FIRST


async def test_a_turn_that_said_nothing_yet_gets_its_reply(builder_request_db, monkeypatch):
    """A turn whose first answer was empty ended with no reply at all ("The agent finished without a reply")."""
    calls, ran, said = await _run(builder_request_db[0], monkeypatch, [("", None), (LAST, None)], empty_answer=NOTE)

    assert len(calls) == 2 and ran == [] and said == LAST


async def test_without_the_note_an_empty_answer_ends_the_turn(builder_request_db, monkeypatch):
    calls, ran, said = await _run(builder_request_db[0], monkeypatch, [(FIRST, "read_file"), ("", None)],
                                  empty_answer=None)

    assert len(calls) == 2 and ran == ["read_file"] and said == FIRST
