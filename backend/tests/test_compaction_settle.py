"""Compaction off the reply's path (``Compactor.settle``): once a run is over, a conversation past ``Budget.settle``
folds in the background, so the next turn starts with room and its calls don't wait on a summary. A turn that crossed
the hard ceiling partway used to stop for two summaries back to back before it could answer.

The real streamed SDK, the real checkpoint transactions over PostgreSQL, deterministic summaries. The same guarantees
hold as for a call's fold: the raw history is never replaced, the commit is compare-and-set (a turn that appended
meanwhile keeps its items, a fold or a person's edit that landed first wins and the settle stops), and the summaries
stay within the run's bound."""

import json
from unittest.mock import AsyncMock

import pytest

from coder.coordinator import compaction
from repositories.coordinator_memories import CoordinatorMemoryRepo
from tests.test_coordinator_compaction import (  # noqa: F401 (fixtures)
    USER, builder_request_db, check_pairs, context_db, model_data,
)
from utils.coordinator_memory import CoordinatorMemoryWrite

pytestmark = pytest.mark.asyncio

CONVERSATION = f"coordinator:{USER}"
BUDGET = compaction.Budget(target=8000, hard=16000, chunk=3000, recent=1500, settle=11000)


async def _store(pool, items):
    await pool.execute("UPDATE conversations SET metadata=jsonb_set(metadata,'{sdk_history}',$2) "
                       "WHERE conversation_id=$1", CONVERSATION, items)


def _lookups(n, start=0):
    items = []
    for i in range(start, start + n):
        items += [{"type": "function_call", "name": "lookup", "call_id": f"l{i}", "arguments": "{}"},
                  {"type": "function_call_output", "call_id": f"l{i}", "output": f"Result {i}: " + "fact " * 800}]
    return items


async def _run(pool, summary, compact, text, lookups, monkeypatch):
    """One turn through the real streamed SDK: ``lookups`` tool rounds, then a reply. Returns each model call's view
    with the summaries made before it, and the settle the turn left running in the background (not yet run)."""
    from agents.models.interface import Model
    from openai.types.responses import (Response, ResponseCompletedEvent, ResponseFunctionToolCall,
                                        ResponseOutputMessage, ResponseOutputText)

    from coder.openai_agent import Agent
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    calls, settles = [], []
    monkeypatch.setattr("utils.async_helpers.spawn", lambda coro, name=None: settles.append(coro))

    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *args, **kwargs):
            calls.append((list(input), summary.await_count))
            check_pairs(input)
            n = len(calls)
            output = ([ResponseFunctionToolCall(type="function_call", name="lookup", call_id=f"{text[:4]}-{n}",
                                                arguments=json.dumps({"n": n}))] if n <= lookups else
                      [ResponseOutputMessage(id="final", type="message", role="assistant", status="completed",
                                             content=[ResponseOutputText(type="output_text", text="Done",
                                                                         annotations=[])])])
            response = Response.model_construct(id=f"r{n}", created_at=0, model="test", object="response",
                                                output=output, status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    async def lookup(name, arguments):
        return {"text": f"Result {arguments['n']}: " + "fact " * 800}

    parameters = {"type": "object", "properties": {"n": {"type": "integer"}}}
    tool = {"type": "function", "function": {"name": "lookup", "description": "Look something up",
                                             "parameters": parameters}}
    instance = await Agent.create(emit_message=AsyncMock(), conversation_id=CONVERSATION, enable_persistence=True,
                                  user_id=USER, custom_tool_executor=lookup, call_model_input_filter=compact,
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt="Look things up.",
                                                                        custom_tools=[tool]))
    instance._sdk_agent.model = ModelDouble()
    instance._billing_hooks = None
    try:
        await instance({"content_items": [ContentItem(type="text", text=text)]})
    finally:
        await instance.cleanup()
    return calls, settles


def _waited(calls):
    """The calls that waited on a summary the turn made: more summaries before them than before its first call."""
    first = calls[0][1]
    return [i for i, (_, before) in enumerate(calls) if before > first]


async def _two_turns(pool, summary, budget, monkeypatch):
    await pool.execute("UPDATE conversations SET metadata='{}' WHERE conversation_id=$1", CONVERSATION)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    first = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    calls, settles = await _run(pool, summary, first, "Look up the first six.", 6, monkeypatch)
    assert not _waited(calls)  # the first turn stays under the hard ceiling throughout
    for settle in settles:
        await settle
    second = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    then, later = await _run(pool, summary, second, "Look up six more.", 6, monkeypatch)
    for settle in later:
        settle.close()  # what the second turn leaves for the background isn't this test's
    return calls, then


async def test_the_turn_after_one_that_crossed_the_trigger_never_waits_on_a_summary(context_db, monkeypatch):
    pool, _, summary, _ = context_db
    first, second = await _two_turns(pool, summary, BUDGET, monkeypatch)

    # The first turn ended past the trigger; the fold it needed ran once it was over, before the next turn.
    folded = second[0][1]
    assert folded >= 1
    checkpoint, stored = await compaction.CoordinatorContextRepo(pool, USER).load()
    assert checkpoint["covered"] > 0
    # The next turn opens on the checkpoint and none of its calls waits on a summary, though it grows as much.
    assert second[0][0][0]["role"] == "developer" and not _waited(second)
    assert summary.await_count == folded
    # Raw history is never replaced: both turns' calls and results are all stored, in pairs.
    assert sum(1 for i in stored if i.get("type") == "function_call_output") == 12
    check_pairs(stored)


async def test_without_the_settle_the_next_turn_waits_on_a_summary_partway(context_db, monkeypatch):
    """The control: the same two turns, with nothing folding between them (its trigger at the hard ceiling)."""
    pool, _, summary, _ = context_db
    budget = compaction.Budget(target=BUDGET.target, hard=BUDGET.hard, chunk=BUDGET.chunk, recent=BUDGET.recent,
                               settle=BUDGET.hard)
    first, second = await _two_turns(pool, summary, budget, monkeypatch)
    assert second[0][1] == 0 and _waited(second)


async def test_a_conversation_under_the_trigger_is_left_as_it_is(context_db):
    pool, _, summary, _ = context_db
    raw = [{"role": "user", "content": "Look up two."}, *_lookups(2), {"role": "assistant", "content": "Done."}]
    await _store(pool, raw)
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)
    await compact(model_data(raw))
    await compact.settle()
    assert summary.await_count == 0 and await compact.repo.load() == ({}, raw)


async def test_a_settle_commits_while_the_next_turn_appends(context_db):
    """The next turn's message lands while the settle summarizes: the fold covers what it read, the new items stay
    after it, and the next turn's view checks out against the checkpoint."""
    pool, _, summary, _ = context_db
    raw = [{"role": "user", "content": "Look up eight."}, *_lookups(8), {"role": "assistant", "content": "Done."}]
    await _store(pool, raw)
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)
    await compact(model_data(raw))
    assert summary.await_count == 0  # under the hard ceiling: the run's own calls folded nothing
    following = raw + [{"role": "user", "content": "And the ninth?"}]
    stub = summary.return_value

    async def next_turn_arrives(*args, **kwargs):
        if summary.await_count == 1:
            await _store(pool, following)
        return stub

    summary.side_effect = next_turn_arrives
    await compact.settle()
    checkpoint, stored = await compact.repo.load()
    assert stored == following and 0 < checkpoint["covered"] < len(raw)
    view = (await compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)(
        model_data(following))).input
    assert view[0]["role"] == "developer" and view[-1] == following[-1]
    assert summary.await_count <= compaction.MAX_SUMMARIES


async def test_a_fold_that_lands_first_wins_and_the_settle_stops(context_db):
    """The next turn crossed the hard ceiling and folded while the settle was still summarizing: its checkpoint
    stands, the settle's is never committed and it summarizes no more."""
    pool, _, summary, _ = context_db
    raw = [{"role": "user", "content": "Look up eight."}, *_lookups(8), {"role": "assistant", "content": "Done."}]
    await _store(pool, raw)
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)
    await compact(model_data(raw))
    following = raw + [{"role": "user", "content": "Now twenty more."}, *_lookups(12, start=8)]
    turn = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)
    stub, landed = summary.return_value, {}

    async def the_turn_folds_first(*args, **kwargs):
        if not landed:
            landed["view"] = True
            summary.side_effect = None
            await _store(pool, following)
            await turn(model_data(following))
            landed["checkpoint"] = (await turn.repo.load())[0]
        return stub

    summary.side_effect = the_turn_folds_first
    await compact.settle()
    assert compact.failed and (await compact.repo.load())[0] == landed["checkpoint"]
    made = summary.await_count
    await compact.settle()
    assert summary.await_count == made  # one conflict, then no more


async def test_a_persons_edit_during_the_settle_wins(context_db):
    pool, _, summary, _ = context_db
    raw = [{"role": "user", "content": "Look up eight."}, *_lookups(8), {"role": "assistant", "content": "Done."}]
    await _store(pool, raw)
    first = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test",
                                            budget=compaction.Budget(target=6000, hard=9000, chunk=3000, recent=1500))
    await first(model_data(raw))  # a checkpoint the person can edit
    checkpoint, _ = await first.repo.load()
    memories = CoordinatorMemoryRepo(pool)
    memory = await memories.get(USER, checkpoint["memory_id"])
    # Past the trigger again, short of the hard ceiling: the run's calls fold nothing, the settle does.
    longer = raw + [{"role": "user", "content": "Look up four more."}, *_lookups(4, start=8),
                    {"role": "assistant", "content": "Done."}]
    await _store(pool, longer)
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)
    await compact(model_data(longer))
    stub, made = summary.return_value, summary.await_count

    async def person_edits(*args, **kwargs):
        await memories.save(USER, CoordinatorMemoryWrite(
            name=memory["name"], description="The owner corrected what NoClick keeps of this conversation.",
            memory_type="project", content="Only the first four lookups matter.", memory_id=memory["id"],
            expected_version=memory["version"]))
        return stub

    summary.side_effect = person_edits
    await compact.settle()
    assert summary.await_count == made + 1 and compact.failed
    assert (await memories.get(USER, memory["id"]))["content"] == "Only the first four lookups matter."
    assert (await compact.repo.load())[0] == checkpoint


async def test_a_platform_agents_compactor_settles_too_and_a_run_without_one_leaves_nothing(context_db, monkeypatch):
    """A platform agent's compactor is its ``context_filter`` (after the product's steering), the coordinator's its
    whole input filter: either settles once the run is over; a run with neither spawns nothing."""
    from coder.openai_agent import Agent

    pool, _, _, _ = context_db
    spawned = []
    monkeypatch.setattr("utils.async_helpers.spawn", lambda coro, name=None: spawned.append((coro, name)))
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)
    for filters in ({"_context_filter": compact, "_call_model_input_filter": None},
                    {"_context_filter": None, "_call_model_input_filter": compact},
                    {"_context_filter": None, "_call_model_input_filter": AsyncMock()}):
        agent = Agent.__new__(Agent)
        agent.conversation_id = CONVERSATION
        for name, value in filters.items():
            setattr(agent, name, value)
        agent._settle_context()
    assert [name for _, name in spawned] == [f"compaction.settle:{CONVERSATION}"] * 2
    for coro, _ in spawned:
        assert coro.cr_code is compaction.Compactor.settle.__code__
        coro.close()


async def test_a_turn_that_spent_its_summaries_leaves_its_backlog_to_a_settle_with_summaries_of_its_own(context_db):
    """A long turn spent its summaries with most of what it read still unfolded, and the settle after it shared the
    turn's bound, so it folded nothing: the next turn waited on summaries before it could answer, each reading about
    one call's worth of results, and fell further behind with every long turn. The settle has summaries of its own,
    and a backlog past what they can read whole is read with its tool calls and results cut (the history keeps them
    whole), so the next turn starts with room and its first call waits on none."""
    from coder.openai_agent.output_limits import CONTEXT_HINT

    pool, _, summary, _ = context_db
    raw = [{"role": "user", "content": "Look up sixty."}]
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)
    for i in range(60):  # one turn: every lookup is persisted before the next model call, as the session does
        raw += _lookups(1, start=i)
        await _store(pool, raw)
        await compact(model_data(raw))
    assert summary.await_count == compaction.MAX_SUMMARIES
    raw.append({"role": "assistant", "content": "Done."})
    await _store(pool, raw)
    await compact.settle()
    assert compaction.MAX_SUMMARIES < summary.await_count <= 2 * compaction.MAX_SUMMARIES
    read = [call.args[1] for call in summary.await_args_list[compaction.MAX_SUMMARIES:]]
    assert any(CONTEXT_HINT in item.get("output", "") for chunk in read for item in chunk)
    for chunk in read:
        check_pairs(chunk)
    checkpoint, stored = await compact.repo.load()
    assert stored == raw and checkpoint["covered"] > len(raw) // 2
    following = raw + [{"role": "user", "content": "And the sixty-first?"}]
    await _store(pool, following)
    made = summary.await_count
    view = (await compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=BUDGET)(
        model_data(following))).input
    assert summary.await_count == made and view[-1] == following[-1]
