"""Every workflow agent gets execute_bash — with a lazy sandbox.

The sandbox runtime is constructed for every workflow agent node (not just
ones with a FilesystemNode / git mounts / env vars wired), but nothing
boots until the model's first execute_bash call, so a pure-chat agent pays
nothing. The interactive coder chat (no node_id) is unchanged. Rehearsals
fabricate bash like every other tool — a Test Run must never boot a real
sandbox (execute_bash bypasses the tool_execution choke point, so it
consults the rehearsal gate itself).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _make_agent(**kwargs):
    from coder.openai_agent.agent import Agent
    from coder.openai_agent.config import AgentConfiguration

    async def _emit(*a, **k):
        return None

    return Agent(
        emit_message=_emit,
        config=AgentConfiguration.from_kwargs(model="gpt-4"),
        conversation_id="conv-always-bash",
        **kwargs,
    )


# ============================================================================
# Runtime construction gate
# ============================================================================


def test_bare_workflow_agent_gets_runtime():
    """No FilesystemNode, no mounts, no env — the runtime still exists, so
    the execute_bash tool is always on the workflow agent's belt."""
    agent = _make_agent(workflow_id="wf-1", node_id="agent-1")
    assert agent._runtime is not None
    assert agent._runtime.mount_path == "/workspace"


def test_conversation_key_makes_workspace_durable():
    agent = _make_agent(
        workflow_id="wf-1", node_id="agent-1", conversation_key="ck-1"
    )
    assert agent._runtime is not None
    assert agent._runtime.persistent is True


def test_interactive_chat_agent_stays_runtimeless():
    """The dashboard coder chat passes workflow_id but no node_id — it keeps
    its own working-directory model and must not gain a sandbox."""
    agent = _make_agent(workflow_id="wf-1")
    assert agent._runtime is None


# ============================================================================
# Rehearsal fence
# ============================================================================


def _bare_agent_with_runtime():
    from coder.openai_agent.agent import Agent

    agent = object.__new__(Agent)
    agent.user_id = "11111111-1111-1111-1111-111111111111"
    agent.workflow_id = "wf-1"
    agent.node_id = "agent-1"
    agent.conversation_id = "reh-conv-1"
    agent.execution_id = None
    agent._runtime = SimpleNamespace(
        run_bash=AsyncMock(return_value={"stdout": "REAL", "stderr": "", "exit_code": 0}),
        _fs_config=None,
        mount_path="/workspace",
        sandbox_setups=[],
        user_env={},
    )
    return agent


async def _invoke(agent, command="ls"):
    tool = agent._make_execute_bash_tool()
    with patch("utils.tool_call_log.record_tool_call"):
        out = await tool.on_invoke_tool(None, json.dumps({"command": command}))
    return json.loads(out)


async def test_rehearsal_fabricates_bash_and_never_boots_a_sandbox():
    agent = _bare_agent_with_runtime()
    fabricated = {"stdout": "fake listing\n", "stderr": "", "exit_code": 0}
    with patch("nodes.agent.rehearsal.is_rehearsing", AsyncMock(return_value=True)), \
         patch("nodes.agent.rehearsal.mock_tool_call", AsyncMock(return_value=fabricated)) as mock_call:
        result = await _invoke(agent)
    assert result["stdout"] == "fake listing\n"
    agent._runtime.run_bash.assert_not_awaited()
    assert mock_call.call_args.kwargs["tool_name"] == "execute_bash"


async def test_rehearsal_offshape_fabrication_is_normalized():
    """The world model drifting off the pinned shape still yields the
    execute_bash contract the agent expects."""
    agent = _bare_agent_with_runtime()
    with patch("nodes.agent.rehearsal.is_rehearsing", AsyncMock(return_value=True)), \
         patch("nodes.agent.rehearsal.mock_tool_call", AsyncMock(return_value=["not", "a", "dict"])):
        result = await _invoke(agent)
    assert result["exit_code"] == 0
    assert "not" in result["stdout"]
    agent._runtime.run_bash.assert_not_awaited()


async def test_rehearsal_unavailable_degrades_to_error_not_real_bash():
    from nodes.agent.rehearsal import RehearsalUnavailable

    agent = _bare_agent_with_runtime()
    with patch("nodes.agent.rehearsal.is_rehearsing", AsyncMock(return_value=True)), \
         patch("nodes.agent.rehearsal.mock_tool_call", AsyncMock(side_effect=RehearsalUnavailable("no world"))):
        result = await _invoke(agent)
    assert "rehearsal" in result["error"]
    agent._runtime.run_bash.assert_not_awaited()


async def test_normal_run_executes_real_bash():
    agent = _bare_agent_with_runtime()
    with patch("nodes.agent.rehearsal.is_rehearsing", AsyncMock(return_value=False)):
        result = await _invoke(agent)
    assert result["stdout"] == "REAL"
    agent._runtime.run_bash.assert_awaited_once_with("ls")


# ============================================================================
# Local runtime: bare construction boots and runs
# ============================================================================


async def test_local_runtime_bare_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
    from coder.openai_agent.sandbox import LocalSandboxRuntime

    rt = LocalSandboxRuntime(
        filesystem_configs=[], workflow_id="wf-e2e", node_id="agent-1"
    )
    try:
        assert rt.persistent is False  # ck-less: nothing to resume
        result = await rt.run_bash("echo bare-agent-shell")
    finally:
        await rt.close()
    assert result["exit_code"] == 0
    assert "bare-agent-shell" in result["stdout"]
