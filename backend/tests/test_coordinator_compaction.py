"""Real checkpoint/memory transactions; deterministic summaries for protocol tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agents.run_config import ModelInputData

from coder.coordinator import compaction
from repositories.coordinator_context import CoordinatorContextRepo
from repositories.coordinator_memories import CoordinatorMemoryRepo
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from utils.coordinator_memory import CoordinatorMemoryWrite

pytestmark = pytest.mark.asyncio


def model_data(items):
    return SimpleNamespace(model_data=ModelInputData(input=items, instructions="System instructions"),
                           agent=SimpleNamespace(tools=[]))


@pytest.fixture
async def context_db(builder_request_db, monkeypatch):
    pool = builder_request_db[0]
    raw = []
    for i in range(30):
        raw.extend([{"role": "user", "content": f"Request {i}: " + "old context " * 120},
                    {"type": "function_call", "name": "lookup", "call_id": f"c{i}", "arguments": "{}"},
                    {"type": "function_call_output", "call_id": f"c{i}", "output": "result " * 100},
                    {"role": "assistant", "content": "Saved result."}])
    raw.append({"role": "user", "content": "Cancel publication of workflow exact-id-123. Keep it offline."})
    await pool.execute("INSERT INTO conversations(conversation_id,user_id,metadata) VALUES($1,$2::uuid,$3)",
                       f"coordinator:{USER}", USER, {"sdk_history": raw})
    summary = AsyncMock(return_value=compaction.Summary(
        description="Working context and unresolved requests from the coordinator conversation.",
        content="## Current request\nRetain the user's requested work and respect subsequent cancellations.\n## Exact references\nworkflow exact-id-123",
    ))
    monkeypatch.setattr(compaction, "summarize", summary)
    # Fast deterministic accounting, including overhead, no provider dependency.
    monkeypatch.setattr(compaction, "token_count", lambda value, model: len(str(value)) // 4)
    budget = compaction.Budget(trigger=13000, target=9500, hard=18000, chunk=5000, recent=2000)
    try:
        yield pool, raw, summary, budget
    finally:
        await pool.execute("DELETE FROM coordinator_memories WHERE user_id=$1::uuid", USER)


def check_pairs(items):
    pending = set()
    for item in items:
        if item.get("type") == "function_call":
            pending.add(item["call_id"])
        elif item.get("type") == "function_call_output":
            assert item["call_id"] in pending
            pending.remove(item["call_id"])
    assert not pending


async def test_compaction_is_visible_preserves_raw_history_and_tool_pairs(context_db):
    pool, raw, summary, budget = context_db
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    result = await compact(model_data(raw))
    assert len(result.input) < len(raw)
    assert raw[-1] in result.input
    check_pairs(result.input)
    for call in summary.await_args_list:
        check_pairs(call.args[1])
    checkpoint, stored = await CoordinatorContextRepo(pool, USER).load()
    assert stored == raw
    assert set(checkpoint) == {"memory_id", "covered", "fingerprint", "version"}
    memory = await CoordinatorMemoryRepo(pool).get(USER, checkpoint["memory_id"])
    assert memory["content"] in result.input[0]["content"]
    assert memory["description"] != memory["content"][:len(memory["description"])]
    headers = await CoordinatorMemoryRepo(pool).list_headers(USER)
    assert memory["id"] in [m["id"] for m in headers["memories"]]
    # Restart: checkpoint reuse is independent of a warm Agent or in-memory cache.
    calls = summary.await_count
    second = await compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)(model_data(raw))
    assert second.input == result.input and summary.await_count == calls


async def test_user_edit_and_forget_checkpoint_take_effect(context_db):
    pool, raw, summary, budget = context_db
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    await compact(model_data(raw))
    checkpoint, _ = await compact.repo.load()
    memories = CoordinatorMemoryRepo(pool)
    memory = await memories.get(USER, checkpoint["memory_id"])
    edited = await memories.save(USER, CoordinatorMemoryWrite(
        name=memory["name"], description="User corrected the coordinator context.", memory_type="project",
        content="Never publish exact-id-123; the user cancelled this request.",
        memory_id=memory["id"], expected_version=memory["version"],
    ))
    result = await compact(model_data(raw))
    assert edited["content"] in result.input[0]["content"]
    await memories.delete(USER, edited["id"], edited["version"])
    result = await compact(model_data(raw))
    assert result.input == raw[checkpoint["covered"]:]
    assert not (await memories.list_headers(USER))["memories"]


async def test_failed_summary_preserves_context_and_stops_at_hard_budget(context_db):
    pool, raw, summary, budget = context_db
    summary.side_effect = RuntimeError("Provider unavailable")
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    with pytest.raises(compaction.ContextBudgetError):
        await compact(model_data(raw))
    assert await compact.repo.load() == ({}, raw)
    assert not (await CoordinatorMemoryRepo(pool).list_headers(USER))["memories"]
    with pytest.raises(compaction.ContextBudgetError):
        await compact(model_data(raw))
    assert summary.await_count == 1  # no repeated billing/summary retry loop


async def test_prefix_mismatch_never_discards_history(context_db):
    pool, raw, _, budget = context_db
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    await compact(model_data(raw))
    changed = [{"role": "user", "content": "Different history"}, *raw[1:]]
    with pytest.raises(compaction.ContextBudgetError, match="no longer matches"):
        await compact(model_data(changed))


async def test_repeated_compaction_does_not_replay_covered_prefix(context_db):
    pool, raw, summary, budget = context_db
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    await compact(model_data(raw))
    checkpoint, _ = await compact.repo.load()
    before = summary.await_count
    extended = raw + [{"role": "user", "content": f"new {i} " + "details " * 200} for i in range(35)]
    await pool.execute("UPDATE conversations SET metadata=jsonb_set(metadata,'{sdk_history}',$2) WHERE conversation_id=$1",
                       f"coordinator:{USER}", extended)
    await compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)(model_data(extended))
    new_calls = summary.await_args_list[before:]
    assert new_calls and new_calls[0].args[1][0] == raw[checkpoint["covered"]]
    assert new_calls[0].args[0]  # incremental prior summary, not a fresh topic recap


async def test_parallel_call_group_is_indivisible():
    items = [{"type": "function_call", "call_id": "a"}, {"type": "function_call", "call_id": "b"},
             {"type": "function_call_output", "call_id": "b"}, {"type": "function_call_output", "call_id": "a"}]
    assert compaction.safe_boundaries(items) == [0, 4]
    assert compaction.safe_boundaries([{"type": "reasoning", "summary": []}, *items]) == [0, 5]


async def test_concurrent_memory_edit_wins_checkpoint_cas(context_db):
    pool, raw, summary, budget = context_db
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    await compact(model_data(raw))
    checkpoint, _ = await compact.repo.load()
    memory = await compact.memories.get(USER, checkpoint["memory_id"])
    extended = raw + [{"role": "user", "content": "new detail " * 1000} for _ in range(8)]
    await pool.execute("UPDATE conversations SET metadata=jsonb_set(metadata,'{sdk_history}',$2) WHERE conversation_id=$1",
                       f"coordinator:{USER}", extended)

    async def user_edits_during_summary(*args, **kwargs):
        await compact.memories.save(USER, CoordinatorMemoryWrite(
            name=memory["name"], description="User correction wins over an in-flight automatic summary.",
            memory_type="project", content="Do not proceed. Wait for my next instruction.",
            memory_id=memory["id"], expected_version=memory["version"],
        ))
        return compaction.Summary(description="A stale generated summary that must not replace the user's edit.",
                                  content="Continue the earlier request; this is a stale generated summary.")

    summary.side_effect = user_edits_during_summary
    fresh = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    with pytest.raises(compaction.ContextBudgetError):
        await fresh(model_data(extended))
    assert (await compact.memories.get(USER, memory["id"]))["content"] == "Do not proceed. Wait for my next instruction."
    assert await compact.repo.load() == (checkpoint, extended)


async def test_real_streamed_sdk_compacts_between_tool_rounds(context_db, monkeypatch):
    from agents.models.interface import Model
    from openai.types.responses import Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
    from coder.openai_agent import Agent
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    pool, _, summary, _ = context_db
    await pool.execute("UPDATE conversations SET metadata='{}' WHERE conversation_id=$1", f"coordinator:{USER}")
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    seen = []

    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *args, **kwargs):
            seen.append(input)
            check_pairs(input)
            assert any(i.get("content") == "Keep working on request exact-123" for i in input)
            n = len(seen)
            output = ([ResponseFunctionToolCall(type="function_call", name="lookup", call_id=f"live-{n}", arguments="{}")]
                      if n < 3 else [ResponseOutputMessage(id="final", type="message", role="assistant", status="completed",
                                                         content=[ResponseOutputText(type="output_text", text="Done", annotations=[])])])
            response = Response.model_construct(id=f"r{n}", created_at=0, model="test", object="response", output=output,
                                                status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test",
                                             budget=compaction.Budget(trigger=9000, target=8000, hard=24000, chunk=12000, recent=2000))
    instance = await Agent.create(emit_message=AsyncMock(), conversation_id=f"coordinator:{USER}",
                                  enable_persistence=True, user_id=USER,
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt="Continue the task.", custom_tools=[
                                      {"type": "function", "function": {"name": "lookup", "description": "Look up context", "parameters": {"type": "object", "properties": {}}}}]),
                                  custom_tool_executor=AsyncMock(return_value={"text": "result " * 4000}),
                                  call_model_input_filter=compact)
    instance._sdk_agent.model = ModelDouble()
    instance._billing_hooks = None
    try:
        await instance({"content_items": [ContentItem(type="text", text="Keep working on request exact-123")]})
    finally:
        await instance.cleanup()
    assert len(seen) == 3 and summary.await_count > 0
    assert not any(i.get("call_id") == "live-1" for i in seen[-1])
    checkpoint, stored = await compact.repo.load()
    assert checkpoint["covered"] > 0
    assert any(i.get("call_id") == "live-1" for i in stored)
    assert stored[-1]["content"][0]["text"] == "Done"
