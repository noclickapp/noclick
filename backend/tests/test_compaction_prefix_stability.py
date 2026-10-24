"""A turn's model calls share one prompt prefix, so the provider reads each call's prompt from the cache the call
before it wrote. OpenAI's caching on GPT-5.6 and later reads only a prefix an earlier request ended at, so an item the
compactor rewrites early in the view (a fold, a re-cut tool result) makes the whole prompt after it a cache miss.
Agents' turns read about half their input from cache, where calls seconds apart should read nine tenths: the
compactor folded every two or three calls of a turn, re-cut the older tool results on every call once past its
summaries, and the next turn dropped the request a fold had kept in view."""

import json
from unittest.mock import AsyncMock

import pytest

from coder.coordinator import compaction
from coder.openai_agent.output_limits import CONTEXT_HINT
from tests.test_coordinator_compaction import (  # noqa: F401 (fixtures)
    USER, builder_request_db, check_pairs, context_db, model_data,
)

pytestmark = pytest.mark.asyncio

INSTRUCTIONS = "System instructions"


def extends(earlier, later):
    """Whether ``later`` starts with every item of ``earlier``, unchanged: the provider reads it from cache."""
    return json.dumps(later[:len(earlier)], sort_keys=True) == json.dumps(earlier, sort_keys=True)


def rewrites(views):
    """The calls whose view does not extend the call's before it."""
    return [i for i in range(1, len(views)) if not extends(views[i - 1], views[i])]


async def persisted_call(pool, compactor, items):
    """One model call over ``items``, persisted first as the session does: the compactor's view of them."""
    await pool.execute("UPDATE conversations SET metadata=jsonb_set(metadata,'{sdk_history}',$2) "
                       "WHERE conversation_id=$1", f"coordinator:{USER}", items)
    return (await compactor(model_data(items))).input


async def test_a_turns_later_calls_extend_the_prompt_the_provider_cached(context_db, monkeypatch):
    """Through the real streamed SDK: a turn of lookups passes the target early and the hard ceiling late. Its calls,
    each reading the one before from the provider's cache, keep extending the prompt and fold once, at the hard
    ceiling."""
    from agents.models.interface import Model
    from openai.types.responses import (Response, ResponseCompletedEvent, ResponseFunctionToolCall,
                                        ResponseOutputMessage, ResponseOutputText)

    from coder.openai_agent import Agent
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    pool, _, summary, _ = context_db
    await pool.execute("UPDATE conversations SET metadata='{}' WHERE conversation_id=$1", f"coordinator:{USER}")
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    budget = compaction.Budget(target=6000, hard=16000, chunk=3000, recent=1500)
    views, summaries_before = [], []

    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, *args, **kwargs):
            views.append(list(input))
            summaries_before.append(summary.await_count)
            check_pairs(input)
            n = len(views)
            output = ([ResponseFunctionToolCall(type="function_call", name="lookup", call_id=f"look-{n}",
                                                arguments=json.dumps({"n": n}))] if n < 16 else
                      [ResponseOutputMessage(id="final", type="message", role="assistant", status="completed",
                                             content=[ResponseOutputText(type="output_text", text="Done",
                                                                         annotations=[])])])
            response = Response.model_construct(id=f"r{n}", created_at=0, model="test", object="response",
                                                output=output, status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    async def lookup(name, arguments):
        return {"text": f"Result {arguments['n']}: " + "fact " * 700}

    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    parameters = {"type": "object", "properties": {"n": {"type": "integer"}}}
    tool = {"type": "function", "function": {"name": "lookup", "description": "Look something up",
                                             "parameters": parameters}}
    instance = await Agent.create(emit_message=AsyncMock(), conversation_id=f"coordinator:{USER}",
                                  enable_persistence=True, user_id=USER, custom_tool_executor=lookup,
                                  config=AgentConfiguration.from_kwargs(model="gpt-4o", system_prompt=INSTRUCTIONS,
                                                                        custom_tools=[tool]),
                                  call_model_input_filter=compact)
    instance._sdk_agent.model = ModelDouble()
    instance._billing_hooks = None
    try:
        await instance({"content_items": [ContentItem(type="text", text="Look up the next sixteen items.")]})
    finally:
        await instance.cleanup()

    overhead = compaction.token_count([INSTRUCTIONS, [{"name": "lookup", "description": "Look something up",
                                                       "parameters": tool["function"]["parameters"]}]], "test") + 6000
    sizes = [overhead + compaction.token_count(view, "test") for view in views]
    broken = rewrites(views)
    folded = [i for i in range(1, len(views)) if summaries_before[i] > summaries_before[i - 1]]
    assert len(views) == 16 and summary.await_count
    # Calls well past the target kept extending the prompt the provider had cached: nothing folded there.
    midway = [i for i, size in enumerate(sizes) if size > (budget.target + budget.hard) // 2]
    assert midway and midway[0] < broken[0] - 1
    # One fold, where the next call would have passed the hard ceiling, is the only call that didn't read the one
    # before it from cache.
    assert broken == folded == [broken[0]]
    before = broken[0] - 1
    assert sizes[before] + (sizes[before] - sizes[before - 1]) > budget.hard
    assert views[broken[0]][0]["role"] == "developer"  # the checkpoint


async def test_results_cut_in_the_models_view_stay_cut_the_same_way_for_the_rest_of_the_turn(context_db):
    """Past its summaries (here one failed), a turn cuts older tool results in the model's view instead. It cut
    each call afresh, by just what that call was over the ceiling, so the oldest cut result read differently on
    every call and each call read only the prompt's opening from cache. A cut now holds for the rest of the turn
    and goes down to the target, as a fold does, so the calls after it extend the cut view until the ceiling comes
    round again."""
    pool, _, summary, budget = context_db
    summary.side_effect = RuntimeError("provider unavailable")
    raw = [{"role": "user", "content": "Add an order form to the bakery's site."}]
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    views, newest = [], []
    for i in range(12):  # one turn: every lookup is persisted before the next model call, as the session does
        raw += [{"type": "function_call", "name": "api_describe", "call_id": f"d{i}", "arguments": "{}"},
                {"type": "function_call_output", "call_id": f"d{i}",
                 "output": f'{{"success": true, "operation": "op{i}"}} ' + "schema " * 1200}]
        await pool.execute("UPDATE conversations SET metadata=jsonb_set(metadata,'{sdk_history}',$2) "
                           "WHERE conversation_id=$1", f"coordinator:{USER}", raw)
        views.append((await compact(model_data(raw))).input)
        newest.append(raw[-1])

    overhead = compaction.token_count([INSTRUCTIONS, []], "test") + 6000
    sizes = [overhead + compaction.token_count(view, "test") for view in views]
    assert summary.await_count == 1 and all(size <= budget.hard for size in sizes)
    broken = rewrites(views)
    assert broken
    for i in broken:
        check_pairs(views[i])
        assert CONTEXT_HINT in json.dumps(views[i])
        assert views[i][-1] == newest[i]  # the newest result is whole
    # Each cut reached the target or cut every older result; never a call cut afresh after one that read whole.
    assert len(broken) <= 4 and all(b - a >= 2 for a, b in zip(broken, broken[1:]))
    # A result once cut reads the same in every later view that holds it.
    seen = {}
    for view in views:
        for item in view:
            if item.get("type") == "function_call_output" and CONTEXT_HINT in item["output"]:
                assert seen.setdefault(item["call_id"], item["output"]) == item["output"]


async def test_the_next_turn_extends_the_view_a_fold_left(context_db):
    """A fold that covers the turn's own request keeps it in view, right after the checkpoint. The next turn's
    request then took over and the old one dropped out of view, so the next turn's first call rewrote the prompt
    from the checkpoint on and read none of it from cache, though nothing new was folded. The request the view
    holds now changes only with a fold: the last one the checkpoint covers."""
    pool, _, summary, budget = context_db
    raw = [{"role": "user", "content": "Price the bakery's domain and its renewal."}]
    turn = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    view = await persisted_call(pool, turn, raw)
    while not summary.await_count:  # one turn of lookups, until a later call folds its own request away
        n = len(raw)
        raw = raw + [{"type": "function_call", "name": "domains_search", "call_id": f"s{n}", "arguments": "{}"},
                     {"type": "function_call_output", "call_id": f"s{n}", "output": f"offer {n} " + "price " * 1700}]
        view = await persisted_call(pool, turn, raw)
    checkpoint, _ = await turn.repo.load()
    assert checkpoint["covered"] > 0 and view[1] == raw[0]  # the turn's request, after the checkpoint
    folded = summary.await_count
    raw = raw + [{"role": "assistant", "content": "It's $12 a year, renewing at $14."},
                 {"role": "user", "content": "Buy it."}]
    following = await persisted_call(
        pool, compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget), raw)
    assert summary.await_count == folded  # nothing new folded
    assert extends(view, following)


async def test_a_turns_first_call_folds_only_past_the_hard_ceiling(context_db):
    """A turn's first call folded at a lower trigger than its later calls, so a conversation whose last turn ended
    between the two folded as the next turn began: the prompt the provider had cached for it minutes before was
    rewritten from the first message on, and the new request paid for its summaries too. Every call now folds only
    where the view would pass the hard ceiling."""
    pool, _, summary, budget = context_db
    raw = [{"role": "user", "content": "Compare the three hosting offers."}]
    turn = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    view = await persisted_call(pool, turn, raw)
    overhead = compaction.token_count([INSTRUCTIONS, []], "test") + 6000
    midway = (budget.target + budget.hard) // 2
    while overhead + compaction.token_count(view, "test") <= midway:  # well past the target, short of the ceiling
        n = len(raw)
        raw = raw + [{"type": "function_call", "name": "offers_search", "call_id": f"o{n}", "arguments": "{}"},
                     {"type": "function_call_output", "call_id": f"o{n}", "output": f"offer {n} " + "terms " * 1400}]
        view = await persisted_call(pool, turn, raw)
    raw = raw + [{"role": "assistant", "content": "The second offer is cheapest over three years."},
                 {"role": "user", "content": "Take the second one."}]
    following = await persisted_call(
        pool, compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget), raw)
    assert overhead + compaction.token_count(following, "test") <= budget.hard
    assert not summary.await_count  # nothing folded, on the turn's first call either
    assert extends(view, following) and following[-1] == raw[-1]


async def test_what_a_turn_leaves_out_of_its_view_stays_out_for_the_rest_of_the_turn(context_db):
    """A turn that can't fold (here its summary failed) and whose older calls pass the ceiling even as stubs, the
    model's reasoning beside them whole, leaves the oldest call groups out of the model's view rather than failing.
    What it leaves out stays out for the rest of the turn, and it leaves out down to the target as a fold goes, so the
    prompt is rewritten from there only when the ceiling comes round again; the newest result reads whole, and the
    history keeps it all."""
    from coder.openai_agent import compaction as engine

    pool, _, summary, budget = context_db
    summary.side_effect = RuntimeError("provider unavailable")
    raw = [{"role": "user", "content": "Build me a weekly digest of Hacker News."}]
    compact = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    views, marks = [], []
    for i in range(120):
        thought = [{"type": "summary_text", "text": f"Step {i}: checking the feed. " + "reasoning " * 100}]
        raw = raw + [{"type": "reasoning", "summary": thought, "content": thought},
                     {"type": "function_call", "name": "fetch", "call_id": f"f{i}", "arguments": "{}"},
                     {"type": "function_call_output", "call_id": f"f{i}", "output": f"story {i} " + "text " * 1200}]
        views.append(await persisted_call(pool, compact, raw))
        marks.append(compact.left_out["calls"])

    note = {"role": "developer", "content": engine.PROMPTS.LEFT_OUT_NOTE}
    overhead = compaction.token_count([INSTRUCTIONS, []], "test") + 6000
    assert summary.await_count == 1 and all(overhead + compaction.token_count(v, "test") <= budget.hard for v in views)
    left = [i for i, view in enumerate(views) if note in view]
    assert left and left == list(range(left[0], len(views)))  # once something is left out, the note stays
    for view in views:
        check_pairs(view)
    assert views[-1][-1] == raw[-1] and views[-1][0] == raw[0]  # the newest result whole, the request in view
    # A call group left out never comes back in a later call of the turn.
    gone, before = set(), None
    for view in views[left[0]:]:
        shown = {item["call_id"] for item in view if item.get("type") == "function_call"}
        assert not shown & gone
        gone |= (before or set()) - shown
        before = shown
    assert gone
    # Leaving out goes down to the target, so it comes round only every so many calls.
    moves = [i for i in range(1, len(marks)) if marks[i] != marks[i - 1]]
    assert moves and len(moves) <= (len(views) - left[0]) // 5
    _, stored = await compact.repo.load()
    assert stored == raw
