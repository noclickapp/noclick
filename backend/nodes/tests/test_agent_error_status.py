"""Regression test for the agent LLM handler reporting status='failed' when
the OpenHands agent ends in AgentState.ERROR.

Previously, errors (rate limits, AssertionError inside OpenHands,
AgentStuckInLoopError) round-tripped as status='completed' with the error
string buried in the `response` field. Callers had no way to branch on
failure, which led the workflow brain into retry loops on a "successful"
response.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _CallableAgentStub:
    """Stand-in for an OpenHands Agent that satisfies `await agent(message)`
    and `await agent.cleanup()` without doing any real work."""

    def __init__(self):
        self.cleanup = AsyncMock()

    async def __call__(self, _message_dict):
        return None


def _make_node():
    return SimpleNamespace(
        node_id="n1",
        sid=None,
        sio=None,
        conversation_id=None,
        organization_id=None,
        workflow_id=None,
        user_id=None,
        execution_id=None,
        _execute_tool=AsyncMock(),
        _upload_images_to_r2=AsyncMock(return_value=[]),
        emit=AsyncMock(),
    )


def _make_config():
    return SimpleNamespace(
        model="gpt-4o",
        temperature=0.7,
        message="",
        system_prompt="",
        conversation_key=None,
    )


@pytest.mark.asyncio
async def test_agent_error_state_surfaces_as_failed_status():
    from nodes.agent.handlers import llm as llm_handler

    captured_response = (
        "Error: RuntimeError: There was an unexpected error while running the "
        "agent: AssertionError. You can refresh the page or ask the agent to "
        "try again."
    )
    final_response_ref = [captured_response]
    final_agent_state_ref = [("error", "RuntimeError: AssertionError")]
    collected_images_ref: list = []

    with patch.object(llm_handler, "Agent") as MockAgent:
        MockAgent.create = AsyncMock(return_value=_CallableAgentStub())
        out = await llm_handler.execute_llm_model(
            _make_node(),
            _make_config(),
            env_overrides=None,
            user_id=None,
            user_email=None,
            tool_configs={},
            filesystem_configs=None,
            effective_conversation_id=None,
            emit_callback=None,
            final_response_ref=final_response_ref,
            collected_images_ref=collected_images_ref,
            final_agent_state_ref=final_agent_state_ref,
        )

    assert out["status"] == "failed", f"expected failed, got {out['status']}"
    assert out["error"], "error field should be populated when status='failed'"
    assert out["response"] == captured_response


@pytest.mark.asyncio
async def test_agent_finished_state_still_completes():
    """Healthy run still reports status='completed' so we don't regress the happy path."""
    from nodes.agent.handlers import llm as llm_handler

    final_response_ref = ["Hello, this is a normal response."]
    final_agent_state_ref = [("finished", None)]
    collected_images_ref: list = []

    with patch.object(llm_handler, "Agent") as MockAgent:
        MockAgent.create = AsyncMock(return_value=_CallableAgentStub())
        out = await llm_handler.execute_llm_model(
            _make_node(),
            _make_config(),
            env_overrides=None,
            user_id=None,
            user_email=None,
            tool_configs={},
            filesystem_configs=None,
            effective_conversation_id=None,
            emit_callback=None,
            final_response_ref=final_response_ref,
            collected_images_ref=collected_images_ref,
            final_agent_state_ref=final_agent_state_ref,
        )

    assert out["status"] == "completed"
    assert "error" not in out


