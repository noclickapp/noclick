"""A platform's agent turn that runs out of model calls still answers: it ended "Max turns (30) exceeded" with the
generic failure line, after work that had happened. The platform names the closing words on the node's runtime
config (``TURN_WRAP_UP_KEY``) and the agent node hands them to the engine's wrap-up call."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nodes.agent.handlers.llm import execute_llm_model
from utils.turn_events import TURN_WRAP_UP_KEY

pytestmark = pytest.mark.asyncio
USER_ID = "00000000-0000-0000-0000-000000000001"


async def _created_with(monkeypatch, node_config):
    created = AsyncMock(side_effect=RuntimeError("stop after create"))
    monkeypatch.setattr("nodes.agent.handlers.llm.Agent.create", created)
    node = SimpleNamespace(node_id="agent", sid=None, sio=None, organization_id=None, workflow_id="wf_1",
                           execution_id="exec_1", conversation_id=None, emit=AsyncMock(),
                           node_data={"config": node_config})
    config = SimpleNamespace(model="gpt-4o", temperature=0.7, system_prompt="", conversation_key=None,
                             message="hello")
    with pytest.raises(RuntimeError, match="stop after create"):
        await execute_llm_model(node, config, None, USER_ID, None, emit_callback=MagicMock())
    return created.call_args.kwargs


async def test_a_turn_the_platform_names_closing_words_for_wraps_up(monkeypatch):
    kwargs = await _created_with(monkeypatch, {TURN_WRAP_UP_KEY: "Say where the work stands."})
    assert kwargs["wrap_up"] == "Say where the work stands."


async def test_any_other_turn_fails_at_its_last_model_call_as_before(monkeypatch):
    assert (await _created_with(monkeypatch, {}))["wrap_up"] is None
