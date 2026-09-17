"""``Agent.create(history_limit=…)`` must reach the persistent session: the
coordinator bounds its replayed history this way, and a factory that let the
argument fall into ignored kwargs raised NameError on every turn (2026-09-17)."""

from unittest.mock import AsyncMock

import pytest

from coder.openai_agent import Agent
from coder.openai_agent.config import AgentConfiguration


@pytest.mark.asyncio
async def test_history_limit_reaches_the_session():
    config = AgentConfiguration.from_kwargs(
        model="openrouter/openai/gpt-5.6-luna", enable_cmd=False, enable_editor=False, enable_mcp=False,
    )
    agent = await Agent.create(
        emit_message=AsyncMock(), config=config, conversation_id="coordinator:u1", user_id="u1",
        enable_persistence=True, history_limit=7,
    )
    try:
        assert agent._session is not None and agent._session._history_limit == 7
    finally:
        await agent.cleanup()
