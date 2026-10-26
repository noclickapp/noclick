"""A platform's agent turn goes as far as the limits the platform names on the node's runtime config
(``TURN_LIMITS_KEY``), the engine's defaults for any it leaves out, and a turn one of them ends still answers: the
platform names the closing words per limit (``TURN_WRAP_UP_KEY``) and the agent node hands them to the engine's
wrap-up call. The node's output says which limit ended the turn."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from coder.openai_agent.guards import TurnLimits, TurnSoFar
from nodes.agent.handlers.llm import execute_llm_model
from utils.turn_events import (
    TURN_EMPTY_ANSWER_KEY, TURN_FIRST_EFFORT_KEY, TURN_LIMITS_KEY, TURN_SO_FAR_KEY, TURN_WRAP_UP_KEY,
)

pytestmark = pytest.mark.asyncio
USER_ID = "00000000-0000-0000-0000-000000000001"
WRAP_UP = {"steps": {"prompt": "Say where the work stands.", "line": "Carrying on in a moment."}}


def _node(node_config):
    return SimpleNamespace(node_id="agent", sid=None, sio=None, organization_id=None, workflow_id="wf_1",
                           execution_id="exec_1", conversation_id=None, emit=AsyncMock(), user_id=USER_ID,
                           node_data={"config": node_config})


def _config():
    return SimpleNamespace(model="gpt-4o", temperature=0.7, system_prompt="", conversation_key=None, message="hello")


async def _created_with(monkeypatch, node_config):
    created = AsyncMock(side_effect=RuntimeError("stop after create"))
    monkeypatch.setattr("nodes.agent.handlers.llm.Agent.create", created)
    with pytest.raises(RuntimeError, match="stop after create"):
        await execute_llm_model(_node(node_config), _config(), None, USER_ID, None, emit_callback=MagicMock())
    return created.call_args.kwargs


async def test_a_turn_the_platform_names_closing_words_for_wraps_up(monkeypatch):
    kwargs = await _created_with(monkeypatch, {TURN_WRAP_UP_KEY: WRAP_UP})
    assert kwargs["wrap_up"] == WRAP_UP


async def test_any_other_turn_ends_on_the_limits_line(monkeypatch):
    assert (await _created_with(monkeypatch, {}))["wrap_up"] is None


async def test_a_workflow_agent_nodes_turn_keeps_its_30_steps_and_no_spend_or_time_limit(monkeypatch):
    """A node has no wrap-up, so a limit fails its run: one on an expensive model must not start failing on a
    spend or time limit it never had. The account's credits and spend cap still bound it."""
    limits = (await _created_with(monkeypatch, {}))["limits"]
    assert limits == TurnLimits() == TurnLimits(steps=30, spend_usd=None, minutes=None)


async def test_a_turn_goes_as_far_as_the_platform_says(monkeypatch):
    kwargs = await _created_with(monkeypatch, {TURN_LIMITS_KEY: {"steps": 100}})
    assert kwargs["limits"] == TurnLimits(steps=100, spend_usd=None, minutes=None)
    kwargs = await _created_with(monkeypatch, {TURN_LIMITS_KEY: {"steps": 40, "usd": 2.5, "minutes": 30}})
    assert kwargs["limits"] == TurnLimits(steps=40, spend_usd=2.5, minutes=30.0)


async def test_a_run_a_restart_handed_over_meets_its_limits_where_the_turn_stood(monkeypatch):
    """A platform running on a turn another process started says how far it had gone (``TURN_SO_FAR_KEY``)."""
    kwargs = await _created_with(monkeypatch, {TURN_SO_FAR_KEY: {"started_at": 1000.0, "steps": 37, "usd": 0.4,
                                                                 "quiet": 12}})
    assert kwargs["so_far"] == TurnSoFar(started_at=1000.0, steps=37, spent_usd=0.4, quiet=12)
    assert (await _created_with(monkeypatch, {}))["so_far"] is None


async def test_the_output_says_which_limit_ended_the_turn(monkeypatch):
    reply = [""]

    class Ended:
        """A turn its step limit ended, as the engine leaves it."""

        turn_ended_by = "steps"
        cleanup = AsyncMock()

        async def __call__(self, message):
            reply[0] += "Did A and B; C is left.\n\nCarrying on in a moment."

    monkeypatch.setattr("nodes.agent.handlers.llm.Agent.create", AsyncMock(return_value=Ended()))
    output = await execute_llm_model(_node({}), _config(), None, USER_ID, None, emit_callback=MagicMock(),
                                     final_response_ref=reply)
    assert output["status"] == "completed" and output["ended_by"] == "steps"
    assert output["response"].endswith("Carrying on in a moment.")


async def test_a_turn_someone_waits_on_starts_with_the_effort_the_platform_names(monkeypatch):
    assert (await _created_with(monkeypatch, {TURN_FIRST_EFFORT_KEY: "low"}))["first_call_effort"] == "low"
    assert (await _created_with(monkeypatch, {}))["first_call_effort"] is None


async def test_a_turn_the_platform_names_a_note_for_an_empty_answer_hands_it_to_the_engine(monkeypatch):
    note = "Your last response was empty: carry on, or end without a word."
    assert (await _created_with(monkeypatch, {TURN_EMPTY_ANSWER_KEY: note}))["empty_answer"] == note
    assert (await _created_with(monkeypatch, {}))["empty_answer"] is None
