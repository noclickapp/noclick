"""Canonical OpenAI Agents SDK wrapper exported by the backend.

Both workflow-agent execution and interactive chat import ``Agent`` from this
package so lifecycle, tool, session, and cleanup behavior stays centralized.
"""

from agents import set_tracing_disabled

# The SDK exports every run's trace, model inputs and outputs included, to OpenAI whenever an
# OPENAI_API_KEY is set, whichever model ran. Nothing reads those traces; our own tracing is OpenTelemetry.
set_tracing_disabled(True)

__all__ = ["Agent"]


def __getattr__(name):
    # Agent (and LiteLLM under it) imports at its first use: importing a light
    # submodule (guards, progress) shouldn't import the model client.
    if name == "Agent":
        from .agent import Agent

        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
