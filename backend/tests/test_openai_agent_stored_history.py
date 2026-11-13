"""A thread stored under an older openai-agents reads back under the installed one, and its replay reaches the model
as it did then.

``fixtures/sdk_history_0_17.json`` holds what openai-agents 0.17.3 wrote to ``sdk_history`` for two streamed turns over
LiteLLM (reasoning, words with two tool calls at once, a picture the person sent), as ``PostgresSession.add_items``
keeps it, ids stripped; and ``sent``, the messages 0.17.3 sent LiteLLM for a third turn over it. From 0.19 the SDK
refuses an assistant message stored that way ("Unhandled item type or structure"), which would fail every stored
thread's next turn."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coder.openai_agent.session import PostgresSession, readable

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sdk_history_0_17.json").read_text())
MODEL = "openrouter/anthropic/claude-sonnet-4.6"


def _session(monkeypatch, history):
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"metadata": {"sdk_history": history}})
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    return PostgresSession("coordinator:u1", user_id="u1", read_only=True)


@pytest.mark.asyncio
async def test_stored_replies_read_back_with_the_placeholder_id_and_nothing_else_changes(monkeypatch):
    from agents.models.fake_id import FAKE_RESPONSES_ID

    history = FIXTURE["history"]
    items = await _session(monkeypatch, history).get_items()
    replies = [i for i, item in enumerate(history) if item.get("role") == "assistant"]
    assert len(replies) == 3 and all("id" not in history[i] for i in replies)
    assert [item.get("id") for item in items] == [FAKE_RESPONSES_ID if i in replies else None
                                                  for i in range(len(history))]
    assert [{k: v for k, v in item.items() if k != "id"} for item in items] == history
    # A message the SDK reads as an easy input message keeps its shape.
    easy = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}
    assert readable(easy) is easy and readable({"role": "user", "content": "Hi"}) == {"role": "user", "content": "Hi"}


@pytest.mark.asyncio
async def test_a_turn_over_the_stored_thread_sends_the_model_what_0_17_sent(monkeypatch):
    """Through the real streamed SDK and ``CostCapturingLitellmModel``: the stored thread converts, and the messages
    LiteLLM gets are the ones 0.17.3 sent, so the provider's cached prompt for the thread still holds."""
    import litellm
    from agents import Agent, FunctionTool, ModelSettings, Runner, RunConfig
    from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices, Usage

    from coder.openai_agent.litellm_model import CostCapturingLitellmModel

    sent = {}

    class Stream:
        def __aiter__(self):
            async def chunks():
                yield ModelResponseStream(id="gen-r", model=MODEL, choices=[StreamingChoices(
                    index=0, delta=Delta(content="Noted."), finish_reason=None)])
                last = ModelResponseStream(id="gen-r", model=MODEL, choices=[StreamingChoices(
                    index=0, delta=Delta(), finish_reason="stop")])
                last.usage = Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12)
                yield last
            return chunks()

    async def acompletion(**kwargs):
        sent.update(kwargs)
        return Stream()

    async def lookup(ctx, args):
        raise AssertionError("The model called no tool")

    tool = FunctionTool(name="lookup", description="Look something up",
                        params_json_schema={"type": "object", "properties": {"what": {"type": "string"}}},
                        on_invoke_tool=lookup, strict_json_schema=False)
    agent = Agent(name="stored", instructions="Answer briefly.", tools=[tool],
                  model=CostCapturingLitellmModel(model=MODEL),
                  model_settings=ModelSettings(include_usage=True, extra_body={"usage": {"include": True}}))
    with patch.object(litellm, "acompletion", acompletion):
        result = Runner.run_streamed(agent, "Thanks.", session=_session(monkeypatch, FIXTURE["history"]),
                                     run_config=RunConfig())
        async for _ in result.stream_events():
            pass
    assert result.final_output == "Noted."
    assert json.loads(json.dumps(sent["messages"])) == FIXTURE["sent"]
