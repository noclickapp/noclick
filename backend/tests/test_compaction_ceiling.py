"""A turn's view folds at a ceiling set by the model it calls (``compaction.budget_for``), not a portable 48k: the
coordinator's model folded about every nine calls of a long turn, each fold a summary and a rewritten prompt cache, and
once its summaries were spent the turn re-read what the folds had cut (a site build fetched the same two guides six
times in one turn, 2026-11-04). The ceiling is the smaller of the model's context window and the prompt size its price
goes up at, less a margin for the count's error; a model the catalogs don't know keeps 48k. Between turns nothing
changes: once a run is over, the conversation still folds down small, so the next turn starts small."""

import logging

import pytest

from coder.coordinator import compaction
from coder.openai_agent import compaction as engine
from tests.test_coordinator_compaction import (  # noqa: F401 (fixtures)
    USER, builder_request_db, check_pairs, context_db, model_data, view_size,
)

pytestmark = pytest.mark.asyncio

LUNA = "openrouter/~openai/gpt-luna-latest"
# OpenRouter's catalog rows as it lists them (2026-11-04), the fields the ceiling reads.
ROWS = [
    {"id": "~openai/gpt-luna-latest", "context_length": 1050000, "top_provider": {"context_length": 1050000},
     "pricing": {"prompt": "0.0000001", "overrides": [{"min_prompt_tokens": 272000, "prompt": "0.0000002"}]}},
    {"id": "anthropic/claude-opus-4.5", "context_length": 200000, "top_provider": {"context_length": 200000},
     "pricing": {"prompt": "0.000005"}},
    {"id": "anthropic/claude-haiku-5.5", "context_length": 1000000, "top_provider": {"context_length": 1000000},
     "pricing": {"prompt": "0.0000001", "overrides": [{"min_prompt_tokens": 100000, "prompt": "0.0000005"}]}},
    {"id": "anthropic/claude-sonnet-5.5", "context_length": 1000000, "top_provider": {"context_length": 1000000},
     "pricing": {"prompt": "0.000002"}},
    {"id": "acme/tiny", "context_length": 8192, "top_provider": {"context_length": 8192}, "pricing": {}},
]
# The most a provider was measured billing for each token the compactor counts (Claude 5.5).
WORST_MEASURED = 1.38


@pytest.fixture
def catalog(monkeypatch):
    reads = []

    async def rows():
        reads.append(1)
        return ROWS

    monkeypatch.setattr("utils.model_catalog.get_openrouter_models", rows)
    monkeypatch.setattr(engine, "_UNKNOWN_MODELS", set())
    return reads


async def test_luna_folds_under_its_long_context_price_with_the_margin(catalog):
    budget = await engine.budget_for(LUNA)
    assert budget.hard == engine.CEILING_CAP == 240_000
    assert budget.hard <= 272_000 * (1 - engine.CEILING_MARGIN)
    # The settle still folds small between turns; only the turn's own folds read and keep more.
    assert (budget.target, budget.settle, budget.recent) == (20000, 32000, 6000)
    assert budget.chunk == budget.turn_recent == 60_000


async def test_a_200k_claude_folds_well_under_its_window_whatever_its_tokenizer_counts(catalog, monkeypatch):
    budget = await engine.budget_for("openrouter/anthropic/claude-opus-4.5")
    assert budget.hard < 200_000 and budget.hard * WORST_MEASURED < 200_000
    # Called directly with the account's own key, it's read from litellm's map: the same window, the same ceiling.
    import litellm

    monkeypatch.setitem(litellm.model_cost, "claude-opus-4-5", {"max_input_tokens": 200000,
                                                               "litellm_provider": "anthropic"})
    assert (await engine.budget_for("anthropic/claude-opus-4-5")).hard == budget.hard


async def test_the_cap_is_in_the_tokens_a_provider_bills(catalog):
    """A 1M Claude counts more tokens than the compactor does: its ceiling is the cap as Claude counts it."""
    budget = await engine.budget_for("openrouter/anthropic/claude-sonnet-5.5")
    assert budget.hard * engine.BILLED_PER_COUNTED["anthropic"] <= engine.CEILING_CAP < budget.hard * 1.5


async def test_a_price_step_below_the_window_sets_the_ceiling(catalog, monkeypatch):
    haiku = await engine.budget_for("openrouter/anthropic/claude-haiku-5.5")
    assert haiku.hard * WORST_MEASURED < 100_000
    import litellm

    monkeypatch.setitem(litellm.model_cost, "gemini/acme-pro", {
        "max_input_tokens": 1048576, "litellm_provider": "gemini", "input_cost_per_token_above_200k_tokens": 2.5e-06})
    assert 150_000 < (await engine.budget_for("gemini/acme-pro")).hard < 200_000


async def test_an_unknown_model_keeps_the_portable_budget_said_once(catalog, caplog):
    with caplog.at_level(logging.WARNING, logger=engine.__name__):
        first = await engine.budget_for("openrouter/acme/unheard-of")
        second = await engine.budget_for("openrouter/acme/unheard-of")
    assert first == second == engine.Budget() and first.hard == 48_000
    assert len([r for r in caplog.records if "unheard-of" in r.getMessage()]) == 1


async def test_a_catalog_that_cant_be_read_is_an_unknown_model(monkeypatch):
    async def down():
        raise RuntimeError("OpenRouter is down")

    monkeypatch.setattr("utils.model_catalog.get_openrouter_models", down)
    monkeypatch.setattr(engine, "_UNKNOWN_MODELS", set())
    assert (await engine.budget_for(LUNA)).hard == 48_000


async def test_a_small_window_shrinks_the_whole_budget(catalog):
    budget = await engine.budget_for("openrouter/acme/tiny")
    assert budget.hard < 8192
    assert budget.recent < budget.chunk < budget.target < budget.settle < budget.hard


async def test_the_ceiling_is_the_turns_model_read_once_a_run(catalog):
    """The platform's summaries run on the default model, the turn on its own: the ceiling is the turn's."""

    class Nothing:
        async def load(self):
            return {}, items

        async def read(self, checkpoint):
            return None

        async def commit(self, **kwargs):
            raise AssertionError("nothing to fold")

    items = [{"role": "user", "content": "Hello"}]
    compactor = engine.Compactor(Nothing(), model="test", turn_model="openrouter/anthropic/claude-opus-4.5",
                                 user_id="u-1")
    await compactor(model_data(items))
    await compactor(model_data(items))
    assert compactor.budget == await engine.budget_for("openrouter/anthropic/claude-opus-4.5")
    assert len(catalog) == 2  # once for the run, once for the comparison above


def _lookups(start, n):
    items = []
    for i in range(start, start + n):
        items += [{"type": "function_call", "name": "lookup", "call_id": f"l{i}", "arguments": "{}"},
                  {"type": "function_call_output", "call_id": f"l{i}", "output": f"Result {i}: " + "fact " * 800}]
    return items


async def _call(pool, compactor, items):
    await pool.execute("UPDATE conversations SET metadata=jsonb_set(metadata,'{sdk_history}',$2) "
                       "WHERE conversation_id=$1", f"coordinator:{USER}", items)
    view = (await compactor(model_data(items))).input
    check_pairs(view)
    return view, compactor.overhead + view_size(view)


async def test_a_luna_turn_runs_past_the_old_ceiling_unfolded_and_the_next_starts_small(context_db, catalog):
    pool, _, summary, _ = context_db
    await pool.execute("UPDATE conversations SET metadata='{}' WHERE conversation_id=$1", f"coordinator:{USER}")
    raw = [{"role": "user", "content": "Build the bakery's site and check every page."}]
    turn = compaction.CoordinatorCompactor(pool, USER, epoch="", model=LUNA)
    sizes = []
    for n in range(60):
        raw += _lookups(n, 1)
        sizes.append((await _call(pool, turn, raw))[1])
    assert summary.await_count == 0 and max(sizes) > 48_000  # the whole turn in view, never folded

    await turn.settle()
    assert summary.await_count >= 1
    raw.append({"role": "user", "content": "Now add a gallery page."})
    following = compaction.CoordinatorCompactor(pool, USER, epoch="", model=LUNA)
    made = summary.await_count
    view, size = await _call(pool, following, raw)
    assert summary.await_count == made  # it waited on no summary
    assert size <= following.budget.settle and view[-1] == raw[-1]


async def test_a_fold_within_a_turn_keeps_the_turns_recent_reads_and_the_settle_a_short_tail(context_db):
    pool, _, summary, _ = context_db
    await pool.execute("UPDATE conversations SET metadata='{}' WHERE conversation_id=$1", f"coordinator:{USER}")
    budget = engine.Budget(target=4000, hard=16000, chunk=4000, recent=1500, settle=8000, turn_recent=6000)
    raw = [{"role": "user", "content": "Check every page."}]
    turn = compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget)
    views = []
    for n in range(16):
        raw += _lookups(n, 1)
        views.append((await _call(pool, turn, raw))[0])
    assert summary.await_count >= 1
    folded = views[-1]
    kept = [item for item in folded if item.get("type") == "function_call_output"]
    assert view_size(kept) >= budget.turn_recent  # the latest reads, whole
    assert kept == [item for item in raw if item.get("type") == "function_call_output"][-len(kept):]

    await turn.settle()
    view = (await _call(pool, compaction.CoordinatorCompactor(pool, USER, epoch="", model="test", budget=budget),
                        raw))[0]
    tail = [item for item in view if item.get("type") == "function_call_output"]
    assert len(tail) < len(kept) and view_size(tail) < budget.turn_recent
