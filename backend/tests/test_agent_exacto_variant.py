"""Tests for _apply_exacto_variant — routes user-selected OpenRouter models through
OpenRouter's :exacto (tool-calling-accuracy) variant on the agent SDK model, while
leaving config.llm.model (billing/display) on the user's base id."""
from coder.openai_agent.agent import _apply_exacto_variant


def test_appends_exacto_to_a_bare_openrouter_model():
    assert _apply_exacto_variant("openrouter/openai/gpt-5.6-luna") == "openrouter/openai/gpt-5.6-luna:exacto"
    assert _apply_exacto_variant("openrouter/openai/gpt-4o-mini") == "openrouter/openai/gpt-4o-mini:exacto"
    # The auto-route (~) prefix is part of the slug, not a variant → still suffixed.
    assert _apply_exacto_variant("openrouter/~openai/gpt-mini-latest") == "openrouter/~openai/gpt-mini-latest:exacto"


def test_respects_an_explicit_variant_the_user_chose():
    for m in (
        "openrouter/openai/gpt-5.6-luna:free",
        "openrouter/openai/gpt-5.6-luna:nitro",
        "openrouter/openai/gpt-5.6-luna:exacto",
    ):
        assert _apply_exacto_variant(m) == m


def test_noop_for_non_openrouter_and_empty():
    assert _apply_exacto_variant("anthropic/claude-sonnet-4-5") == "anthropic/claude-sonnet-4-5"
    assert _apply_exacto_variant("gpt-4o-mini") == "gpt-4o-mini"
    assert _apply_exacto_variant("") == ""
