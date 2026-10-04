"""A rehearsal is recognised by its agent's thread id as well as its own.

The in-process agent holds its effective conversation id,
``ck:{workflow}:{node}:{rehearsal id}``, while the rehearsal is keyed by the
bare ``rehearsal:{workflow}:{nonce}``. Its ``execute_bash`` fence and thought
rows read the former, so before the two were tied together an SDK agent's
shell ran FOR REAL inside a rehearsal.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from nodes.agent import rehearsal as rh
from nodes.agent.rehearsal import RehearsalScenario

pytestmark = pytest.mark.asyncio

REHEARSAL = "rehearsal:wf-1:abc123"
THREAD = f"ck:wf-1:agent-1:{REHEARSAL}"
SCENARIO = RehearsalScenario(scenario="An ordinary day.", trigger_node_id="agent-1", trigger_payload={})


@pytest.fixture
def redis(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: fake)
    return fake


async def test_the_agents_thread_id_names_its_rehearsal(redis):
    await rh.start_rehearsal(REHEARSAL, SCENARIO, user_id="u-1")
    assert await rh.is_rehearsing(THREAD) is True
    assert (await rh.load_rehearsal(THREAD))["scenario"] == "An ordinary day."
    assert rh.is_rehearsal_conversation(THREAD) is True
    assert rh.public_frames_key(THREAD) == rh.public_frames_key(REHEARSAL)
    # A real thread whose key merely mentions a rehearsal is no rehearsal.
    assert rh.rehearsal_key("ck:wf-1:agent-1:sdk:account:x:rehearsal:y") == "ck:wf-1:agent-1:sdk:account:x:rehearsal:y"
    assert rh.is_rehearsal_conversation("ck:wf-1:agent-1:sdk:account:x:rehearsal:y") is False
    await rh.end_rehearsal(THREAD)
    assert await rh.is_rehearsing(REHEARSAL) is False


async def test_frames_from_the_thread_id_land_with_the_rehearsals_own(redis):
    await rh.start_rehearsal(REHEARSAL, SCENARIO, public=True)
    await rh.emit_rehearsal_thought(THREAD, "Checking the order first.")
    [frame] = await rh.read_public_frames(REHEARSAL)
    assert frame["kind"] == "thought" and frame["conversation_id"] == REHEARSAL


async def test_an_sdk_agents_shell_is_fabricated_in_a_rehearsal(redis):
    """The fence the shell consults, unpatched: before the fix it looked the
    thread id up, found nothing, and ran the command in a real sandbox."""
    from coder.openai_agent.agent import Agent

    await rh.start_rehearsal(REHEARSAL, SCENARIO)
    agent = object.__new__(Agent)
    agent.user_id, agent.workflow_id, agent.node_id = "11111111-1111-1111-1111-111111111111", "wf-1", "agent-1"
    agent.conversation_id, agent.execution_id = THREAD, None
    agent._runtime = SimpleNamespace(
        run_bash=AsyncMock(return_value={"stdout": "REAL", "stderr": "", "exit_code": 0}),
        _fs_config=None, mount_path="/workspace", sandbox_setups=[], user_env={},
    )
    fabricated = {"stdout": "report.csv\n", "stderr": "", "exit_code": 0}
    with patch("nodes.agent.rehearsal.mock_tool_call", AsyncMock(return_value=fabricated)) as world, \
            patch("utils.tool_call_log.record_tool_call"):
        out = json.loads(await agent._make_execute_bash_tool().on_invoke_tool(None, json.dumps({"command": "ls"})))
    assert out["stdout"] == "report.csv\n"
    agent._runtime.run_bash.assert_not_awaited()
    assert world.call_args.kwargs["conversation_id"] == THREAD
