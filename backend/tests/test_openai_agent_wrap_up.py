"""A run that makes every model call it may (``AGENT_MAX_TURNS``), through the real streamed SDK and PostgreSQL: with
``wrap_up`` (the coordinator's) the model answers once more, allowed no tool, and that answer is the turn's reply,
streamed and stored; a model that calls a tool there anyway runs nothing, and the run fails as it would have;
without it the run fails as before."""

from unittest.mock import AsyncMock

import pytest

from tests.test_builder_requests import USER, builder_request_db  # noqa: F401

pytestmark = pytest.mark.asyncio

CONVERSATION = "coordinator:wrap-up"
WRAP_UP = "You're out of steps: say where things stand."
STANDING = "Found it: the app needs a package.json. Its fix is deploying; I'll report when it's live."


async def _run(pool, monkeypatch, *, wrap_up, closing_calls_a_tool=False):
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
    monkeypatch.setattr("coder.openai_agent.agent.AGENT_MAX_TURNS", 3)
    monkeypatch.setattr(BillingHooks, "on_llm_start", AsyncMock())
    monkeypatch.setattr(BillingHooks, "_record_usage", AsyncMock())
    await pool.execute("INSERT INTO conversations(conversation_id, user_id, metadata) VALUES ($1, $2::uuid, '{}') "
                       "ON CONFLICT DO NOTHING", CONVERSATION, USER)
    calls, looked, emitted = [], [], []

    async def look(name, arguments):
        looked.append(name)
        return {"lines": ["A nextjs app needs a package.json."]}

    class ModelDouble(Model):
        """Calls a tool whenever it may; answers only when it may not."""

        async def get_response(self, system_instructions, input, model_settings, *args, **kwargs):
            calls.append((model_settings.tool_choice, list(input)))
            if closing_calls_a_tool:  # a provider that ignores tool_choice
                call = ResponseFunctionToolCall(type="function_call", name="look", call_id="c-close", arguments="{}")
                return ModelResponse(output=[call], usage=Usage(), response_id="r-close")
            reply = ResponseOutputMessage(id="m-close", type="message", role="assistant", status="completed",
                                          content=[ResponseOutputText(type="output_text", text=STANDING,
                                                                      annotations=[])])
            return ModelResponse(output=[reply], usage=Usage(), response_id="r-close")

        async def stream_response(self, system_instructions, input, model_settings, *args, **kwargs):
            calls.append((model_settings.tool_choice, list(input)))
            n = len(calls)
            call = ResponseFunctionToolCall(type="function_call", name="look", call_id=f"c{n}", arguments="{}")
            response = Response.model_construct(id=f"r{n}", created_at=0, model="test", object="response",
                                                output=[call], status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    async def emit(event):
        emitted.append(event)

    tool = {"type": "function", "function": {"name": "look", "description": "Read the logs",
                                             "parameters": {"type": "object", "properties": {}}}}
    instance = await Agent.create(emit_message=emit, conversation_id=CONVERSATION, enable_persistence=True,
                                  user_id=USER, custom_tool_executor=look, wrap_up=wrap_up,
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt="Fix it.",
                                                                        custom_tools=[tool]))
    instance._sdk_agent.model = ModelDouble()
    try:
        await instance({"content_items": [ContentItem(type="text", text="Why did the deploy fail?")]})
    finally:
        await instance.cleanup()
    return calls, looked, emitted


async def test_a_run_out_of_model_calls_says_where_the_work_stands(builder_request_db, monkeypatch):
    pool = builder_request_db[0]
    calls, looked, emitted = await _run(pool, monkeypatch, wrap_up=WRAP_UP)

    # Three calls that each called a tool, then one more that may call none, told why.
    assert [choice for choice, _ in calls] == [None, None, None, "none"] and len(looked) == 3
    assert calls[-1][1][-1] == {"role": "developer", "content": WRAP_UP}
    assert sum(1 for item in calls[-1][1] if item.get("type") == "function_call_output") == 3
    # Its answer is the turn's reply, streamed once, and the turn ends without an error.
    text = [e.message for e in emitted if getattr(e, "message", None)]
    assert text == [STANDING]
    assert not [e for e in emitted if getattr(e, "status", None) == "error" or getattr(e, "state", None) == "error"]
    assert emitted[-1].finished is True and emitted[-1].message is None
    stored = await pool.fetchval("SELECT metadata->'sdk_history' FROM conversations WHERE conversation_id = $1",
                                 CONVERSATION)
    assert stored[-1]["role"] == "assistant" and stored[-1]["content"][0]["text"] == STANDING


async def test_without_a_wrap_up_a_run_out_of_model_calls_fails_as_before(builder_request_db, monkeypatch):
    calls, looked, emitted = await _run(builder_request_db[0], monkeypatch, wrap_up=None)

    assert [choice for choice, _ in calls] == [None, None, None] and len(looked) == 3
    failed = [e for e in emitted if getattr(e, "status", None) == "error"]
    assert len(failed) == 1 and "Max turns (3) exceeded" in failed[0].message


async def test_a_wrap_up_that_calls_a_tool_runs_nothing_and_the_run_fails(builder_request_db, monkeypatch):
    calls, looked, emitted = await _run(builder_request_db[0], monkeypatch, wrap_up=WRAP_UP, closing_calls_a_tool=True)

    # The closing call asked for a tool: it never ran, and nothing was said as if the turn had ended well.
    assert [choice for choice, _ in calls] == [None, None, None, "none"] and len(looked) == 3
    assert not [e for e in emitted if getattr(e, "message", None) and getattr(e, "status", None) != "error"]
    failed = [e for e in emitted if getattr(e, "status", None) == "error"]
    assert len(failed) == 1 and "Max turns (3) exceeded" in failed[0].message
