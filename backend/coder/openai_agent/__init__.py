"""Canonical OpenAI Agents SDK wrapper exported by the backend.

Both workflow-agent execution and interactive chat import ``Agent`` from this
package so lifecycle, tool, session, and cleanup behavior stays centralized.
"""

from agents import set_tracing_disabled

# The SDK exports every run's trace, model inputs and outputs included, to OpenAI whenever an
# OPENAI_API_KEY is set, whichever model ran. Nothing reads those traces; our own tracing is OpenTelemetry.
set_tracing_disabled(True)

from .agent import Agent  # noqa: E402

__all__ = ["Agent"]
