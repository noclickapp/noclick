"""Canonical OpenAI Agents SDK wrapper exported by the backend.

Both workflow-agent execution and interactive chat import ``Agent`` from this
package so lifecycle, tool, session, and cleanup behavior stays centralized.
"""

from .agent import Agent

__all__ = ["Agent"]
