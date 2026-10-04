"""Steering a running turn (``coder.openai_agent.steering``) and the reason the
model gave beside a call (``turn_notes``), through the real streamed SDK and
PostgreSQL: steered text joins before the run's next model call (never its
first), is stored where the run had reached, and stays put for the run's
later calls; a tool call sees the text its response carried."""

from unittest.mock import AsyncMock

import pytest

from coder.openai_agent import turn_notes
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from utils import capabilities

pytestmark = pytest.mark.asyncio

CONVERSATION = "ck:wf:agent:sdk:account:agent-1:c1"
STEER = {"role": "user", "content": "Skip the e2e suite."}


async def test_a_steer_joins_the_running_turn_before_its_next_model_call(builder_request_db, monkeypatch):
    from agents.models.interface import Model
    from openai.types.responses import (
        Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText,
    )

    from coder.openai_agent import Agent
    from coder.openai_agent.billing import BillingHooks
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    pool = builder_request_db[0]
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    await pool.execute("INSERT INTO conversations(conversation_id, user_id, metadata) VALUES ($1, $2::uuid, '{}')",
                       CONVERSATION, USER)
    taken = []

    async def take(conversation_id):
        taken.append(conversation_id)
        return [STEER["content"]] if len(taken) == 1 else []

    monkeypatch.setitem(capabilities._providers, capabilities.TURN_STEERING, take)
    # The billing hooks stay (they keep the stated reason); only their metering is stubbed.
    monkeypatch.setattr(BillingHooks, "on_llm_start", AsyncMock())
    monkeypatch.setattr(BillingHooks, "_record_usage", AsyncMock())
    reasons, seen = [], []

    async def run_tests(name, arguments):
        reasons.append(turn_notes.stated_reason())
        return {"passed": 12}

    def message(text):
        return ResponseOutputMessage(id=f"m-{text[:4]}", type="message", role="assistant", status="completed",
                                     content=[ResponseOutputText(type="output_text", text=text, annotations=[])])

    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *args, **kwargs):
            seen.append(list(input))
            n = len(seen)
            call = ResponseFunctionToolCall(type="function_call", name="run_tests", call_id=f"c{n}", arguments="{}")
            output = {1: [message("I'll run the unit tests first."), call], 2: [call]}.get(n, [message("Skipped e2e.")])
            response = Response.model_construct(id=f"r{n}", created_at=0, model="test", object="response",
                                                output=output, status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    tool = {"type": "function", "function": {"name": "run_tests", "description": "Run the tests",
                                             "parameters": {"type": "object", "properties": {}}}}
    instance = await Agent.create(emit_message=AsyncMock(), conversation_id=CONVERSATION, enable_persistence=True,
                                  user_id=USER, custom_tool_executor=run_tests,
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt="Fix it.",
                                                                        custom_tools=[tool]))
    instance._sdk_agent.model = ModelDouble()
    try:
        await instance({"content_items": [ContentItem(type="text", text="Fix the failing build.")]})
    finally:
        await instance.cleanup()

    assert len(seen) == 3 and taken == [CONVERSATION, CONVERSATION]  # asked before the 2nd and 3rd calls only
    assert STEER not in seen[0]
    first_output = next(i for i, item in enumerate(seen[1]) if item.get("call_id") == "c1"
                        and item.get("type") == "function_call_output")
    assert seen[1].index(STEER) == first_output + 1 == len(seen[1]) - 1
    assert seen[2].index(STEER) == first_output + 1  # kept where it joined
    stored = await pool.fetchval("SELECT metadata->'sdk_history' FROM conversations WHERE conversation_id = $1",
                                 CONVERSATION)
    kinds = [item.get("type") or item.get("role") for item in stored]
    steer_at = stored.index(STEER)
    assert kinds[steer_at - 1] == "function_call_output" and stored[steer_at - 1]["call_id"] == "c1"
    assert stored[steer_at + 1]["call_id"] == "c2"
    # Each call saw the text its own response carried: the first a reason, the second none.
    assert reasons == ["I'll run the unit tests first.", None]


async def test_no_steering_without_a_product_that_steers(monkeypatch):
    from coder.openai_agent import steering

    monkeypatch.setitem(capabilities._providers, capabilities.TURN_STEERING, None)
    assert steering.filter_for(CONVERSATION, None) is None
    assert turn_notes.stated_reason() is None  # outside a run
