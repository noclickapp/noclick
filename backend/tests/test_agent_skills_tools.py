"""An agent's ``skill__read`` (``nodes.agent.agent_skills``): offered when a platform puts a spec on the turn and
provides ``AGENT_SKILLS``; its calls reach the provider by every path; a rehearsal reads skills for real."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.agent.agent_skills import (
    AGENT_SKILLS_KEY, SKILL_CATALOG_KEY, SKILL_READ_TOOL_TYPE, agent_skills_of, skill_catalog_of,
)
from nodes.agent.platform_tools import PLATFORM_TOOL_TYPES, build_platform_tools, execute_platform_tool_from_ctx
from nodes.agent.rehearsal import REHEARSAL_PASSTHROUGH_TOOL_TYPES
from utils import capabilities

SPEC = {"agent_id": "agt_1", "account_user_id": "acct_1"}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def provider(pool, *, spec, arguments):
        seen.append({"pool": pool, "spec": spec, "arguments": arguments})
        return {"success": True, "content": "Steps"}

    monkeypatch.setattr(capabilities, "_providers", {capabilities.AGENT_SKILLS: provider})
    return seen


def _skill_tools(pairs):
    return {p["function"]["name"]: c for p, c in pairs if p["function"]["name"].startswith("skill__")}


def test_offered_with_a_spec_and_a_provider(calls, monkeypatch):
    assert _skill_tools(build_platform_tools(False)) == {}
    tools = _skill_tools(build_platform_tools(False, agent_skills=SPEC))
    assert list(tools) == ["skill__read"]
    assert tools["skill__read"]["tool_type"] == SKILL_READ_TOOL_TYPE and tools["skill__read"]["spec"] == SPEC
    assert tools["skill__read"]["_parameters"]["required"] == ["name"]
    assert SKILL_READ_TOOL_TYPE in PLATFORM_TOOL_TYPES
    monkeypatch.setattr(capabilities, "_providers", {})
    assert _skill_tools(build_platform_tools(False, agent_skills=SPEC)) == {}


def test_the_spec_and_the_catalog_ride_the_node_config():
    assert agent_skills_of(MagicMock(node_data={"config": {AGENT_SKILLS_KEY: SPEC}})) == SPEC
    assert agent_skills_of(MagicMock(node_data={"config": {}})) is None
    assert skill_catalog_of({SKILL_CATALOG_KEY: " Your skills:\n- pdf: Forms "}) == "Your skills:\n- pdf: Forms"
    for config in ({}, None, {SKILL_CATALOG_KEY: " "}, {SKILL_CATALOG_KEY: ["x"]}):
        assert skill_catalog_of(config) is None


async def test_every_path_reaches_the_provider_and_a_rehearsal_reads_for_real(calls, monkeypatch):
    from nodes.agent import tool_execution

    pool = object()
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    args = {"name": "pdf-forms"}
    assert (await execute_platform_tool_from_ctx({"tool_type": SKILL_READ_TOOL_TYPE, "spec": SPEC}, args, pool))[
        "success"]
    assert SKILL_READ_TOOL_TYPE in REHEARSAL_PASSTHROUGH_TOOL_TYPES
    monkeypatch.setattr(tool_execution, "is_rehearsing", AsyncMock(return_value=True))
    fabricated = AsyncMock(return_value={"success": True, "content": "world"})
    monkeypatch.setattr(tool_execution, "rehearse_tool", fabricated)
    node = MagicMock(user_id=None, workflow_id=None, node_id="agent", conversation_id="rehearsal:wf:1",
                     execution_id=None)
    with patch("utils.tool_call_log.record_tool_call"):
        read = await tool_execution.execute_tool(node, "skill__read", args,
                                                 {"skill__read": {"tool_type": SKILL_READ_TOOL_TYPE, "spec": SPEC}})
    assert read == {"success": True, "content": "Steps"} and fabricated.await_count == 0
    assert calls == [{"pool": pool, "spec": SPEC, "arguments": args}] * 2

    monkeypatch.setattr(capabilities, "_providers", {})
    refused = await execute_platform_tool_from_ctx({"tool_type": SKILL_READ_TOOL_TYPE, "spec": SPEC}, args, None)
    assert refused == {"success": False, "error": "Skills aren't available here."}
