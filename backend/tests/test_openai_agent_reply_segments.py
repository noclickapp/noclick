"""A reply whose text comes in segments around tool calls reads as paragraphs, through the real streamed SDK: the
model's text after a tool round starts a paragraph of its own in the text the turn streams, which is both what a
chat shows live and what the reply adds up to and is saved as (``agent_node`` keeps the sum of the same pieces). The
coordinator's chat showed "...before calling this done.Google sign-in setup is running." (2026-10-16)."""

from unittest.mock import AsyncMock

from coder.openai_agent.agent import _segment_break

FIRST = "I'll verify it and the live page before calling this done."
SECOND = "Google sign-in setup is running."


def _deltas(text: str, item: str):
    from openai.types.responses import ResponseTextDeltaEvent

    return [ResponseTextDeltaEvent.model_construct(type="response.output_text.delta", delta=text[i:i + 9], item_id=item,
                                                   output_index=0, content_index=0, sequence_number=i, logprobs=[])
            for i in range(0, len(text), 9)]


async def _turn(first: str, second: str):
    """One turn: ``first`` beside a tool call, then ``second`` once the tool answered. The text it streamed."""
    from agents.models.interface import Model
    from openai.types.responses import (Response, ResponseCompletedEvent, ResponseFunctionToolCall,
                                        ResponseOutputMessage, ResponseOutputText)

    from coder.openai_agent import Agent
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender import ChatMessageEvent
    from wss.sender.schema import ContentItem

    calls = []

    def message(text: str, item: str):
        return ResponseOutputMessage(id=item, type="message", role="assistant", status="completed",
                                     content=[ResponseOutputText(type="output_text", text=text, annotations=[])])

    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *args, **kwargs):
            calls.append(input)
            if len(calls) == 1:
                text, output = first, [message(first, "m1"), ResponseFunctionToolCall(
                    type="function_call", name="start_sign_in", call_id="c1", arguments="{}")]
            else:
                text, output = second, [message(second, "m2")]
            for event in _deltas(text, f"m{len(calls)}"):
                yield event
            response = Response.model_construct(id=f"r{len(calls)}", created_at=0, model="test", object="response",
                                                output=output, status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=999)

    emitted = []

    async def emit(event):
        emitted.append(event)

    tool = {"type": "function", "function": {"name": "start_sign_in", "description": "Start sign-in",
                                             "parameters": {"type": "object", "properties": {}}}}
    instance = await Agent.create(emit_message=emit, conversation_id="segments", enable_persistence=False,
                                  custom_tool_executor=AsyncMock(return_value={"status": "running"}),
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt="Help.",
                                                                        custom_tools=[tool]))
    instance._sdk_agent.model = ModelDouble()
    instance._billing_hooks = None
    try:
        await instance({"content_items": [ContentItem(type="text", text="Add Sign in with Google")]})
    finally:
        await instance.cleanup()
    assert len(calls) == 2
    assert not [e for e in emitted if getattr(e, "status", None) == "error"]
    return [e.message for e in emitted if isinstance(e, ChatMessageEvent) and e.message]


async def test_text_after_a_tool_round_is_a_paragraph_of_its_own():
    pieces = await _turn(FIRST, SECOND)
    assert "".join(pieces) == f"{FIRST}\n\n{SECOND}"
    # The break arrives with the second segment's first piece, so a chat drawing the pieces as they come agrees.
    assert pieces[len(_deltas(FIRST, "m1"))].startswith("\n\nGoogle")


async def test_a_segment_that_already_breaks_the_line_gets_only_what_it_lacks():
    assert "".join(await _turn(FIRST + "\n", SECOND)) == f"{FIRST}\n\n{SECOND}"


def test_the_break_counts_the_newlines_either_side_has():
    assert _segment_break("", SECOND) == ""  # nothing before it: no break
    assert _segment_break("  \n", SECOND) == ""
    assert _segment_break(FIRST, SECOND) == "\n\n"
    assert _segment_break(FIRST + "\n", SECOND) == "\n"
    assert _segment_break(FIRST, "\n" + SECOND) == "\n"
    assert _segment_break(FIRST + "\n\n", SECOND) == _segment_break(FIRST, "\n\n" + SECOND) == ""
