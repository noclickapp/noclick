"""The community builder follows the key the instance has.

`builder_config` here is the open edition's: one model per call, chosen at run
time from WORKFLOW_BUILDER_MODEL or the provider key that exists, so a single
key saved in Settings is enough to build with.
"""

import os

import pytest

from coder.workflow import builder_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("WORKFLOW_BUILDER_MODEL", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_brain_model_follows_the_available_key(monkeypatch):
    assert builder_config.resolve_brain_model() == "openrouter/openai/gpt-5.6-luna", (
        "with no key at all the OpenRouter route is named — the key the builder asks for"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    assert builder_config.resolve_brain_model() == "openai/gpt-5.6-luna"
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert builder_config.resolve_brain_model() == "openrouter/openai/gpt-5.6-luna"
    monkeypatch.setenv("WORKFLOW_BUILDER_MODEL", "anthropic/claude-sonnet-4")
    assert builder_config.resolve_brain_model() == "anthropic/claude-sonnet-4", "an explicit choice always wins"


def test_missing_brain_key_names_the_variable_and_provider(monkeypatch):
    assert builder_config.missing_brain_key("openrouter/openai/gpt-5.6-luna") == ("OPENROUTER_API_KEY", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert builder_config.missing_brain_key("openrouter/openai/gpt-5.6-luna") is None
    assert builder_config.missing_brain_key("anthropic/claude-sonnet-4") == ("ANTHROPIC_API_KEY", "anthropic")


def test_fallback_rides_openrouter_only(monkeypatch):
    for name in ("WORKFLOW_BUILDER_MODEL", "WORKFLOW_BUILDER_FALLBACK_MODEL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert builder_config.resolve_brain_fallback_model() == "openrouter/google/gemini-3.5-flash:nitro"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert builder_config.resolve_brain_fallback_model() is None, "a direct OpenAI key cannot reach an OpenRouter fallback"
    monkeypatch.setenv("WORKFLOW_BUILDER_FALLBACK_MODEL", "openai/gpt-5-mini")
    assert builder_config.resolve_brain_fallback_model() == "openai/gpt-5-mini"
