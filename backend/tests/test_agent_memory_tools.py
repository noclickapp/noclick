"""An agent's memory tools (``nodes.agent.agent_memory``): offered when a
platform puts a spec on the turn and provides ``AGENT_MEMORY``, the writes
only on a thread that may write; every path (in process, pool-local for CLI
harnesses, dispatched by ``execute_tool``) hands the call to the provider; a
rehearsal runs the reads for real and fabricates the writes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.agent.agent_memory import (
    AGENT_MEMORY_KEY, MEMORY_CATALOG_KEY, MEMORY_READ_TOOL_TYPE, MEMORY_WRITE_TOOL_TYPE, agent_memory_of,
    execute_memory_tool, memory_catalog_of,
)
from nodes.agent.platform_tools import PLATFORM_TOOL_TYPES, build_platform_tools, execute_platform_tool_from_ctx
from nodes.agent.rehearsal import REHEARSAL_PASSTHROUGH_TOOL_TYPES
from utils import capabilities

SPEC = {"agent_id": "agt_1", "account_user_id": "acct_1", "tenant_id": None, "writes": True}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def provider(pool, *, spec, arguments):
        seen.append({"pool": pool, "spec": spec, "arguments": arguments})
        return {"success": True}

    monkeypatch.setattr(capabilities, "_providers", {capabilities.AGENT_MEMORY: provider})
    return seen


def _memory_tools(pairs):
    return {p["function"]["name"]: c for p, c in pairs if p["function"]["name"].startswith("memory__")}


def test_offered_with_a_spec_and_a_provider_writes_only_where_allowed(calls, monkeypatch):
    assert _memory_tools(build_platform_tools(False)) == {}
    tools = _memory_tools(build_platform_tools(False, agent_memory=SPEC))
    assert list(tools) == ["memory__search", "memory__read", "memory__save", "memory__delete"]
    assert tools["memory__read"]["tool_type"] == MEMORY_READ_TOOL_TYPE
    assert tools["memory__save"]["tool_type"] == MEMORY_WRITE_TOOL_TYPE
    assert tools["memory__save"]["spec"] == {**SPEC, "tool": "memory__save"}
    assert tools["memory__save"]["_parameters"]["required"] == ["name", "content"]
    read_only = _memory_tools(build_platform_tools(False, agent_memory={**SPEC, "writes": False}))
    assert list(read_only) == ["memory__search", "memory__read"]
    assert {MEMORY_READ_TOOL_TYPE, MEMORY_WRITE_TOOL_TYPE} <= PLATFORM_TOOL_TYPES

    monkeypatch.setattr(capabilities, "_providers", {})
    assert _memory_tools(build_platform_tools(False, agent_memory=SPEC)) == {}


def test_the_spec_and_the_catalog_ride_the_node_config():
    assert agent_memory_of(MagicMock(node_data={"config": {AGENT_MEMORY_KEY: SPEC}})) == SPEC
    assert agent_memory_of(MagicMock(node_data={"config": {}})) is None
    assert memory_catalog_of({MEMORY_CATALOG_KEY: " Your memory:\n- tone: How we write "}) == (
        "Your memory:\n- tone: How we write")
    for config in ({}, None, {MEMORY_CATALOG_KEY: "  "}, {MEMORY_CATALOG_KEY: ["x"]}):
        assert memory_catalog_of(config) is None


async def test_every_path_reaches_the_provider(calls, monkeypatch):
    from nodes.agent.tool_execution import execute_tool

    pool = object()
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    spec, args = {**SPEC, "tool": "memory__read"}, {"name": "tone"}
    assert (await execute_memory_tool(MagicMock(), args, {"spec": spec}))["success"]
    assert (await execute_platform_tool_from_ctx({"tool_type": MEMORY_READ_TOOL_TYPE, "spec": spec}, args, pool))[
        "success"]
    node = MagicMock(user_id=None, workflow_id=None, node_id="agent", conversation_id=None, execution_id=None)
    with patch("utils.tool_call_log.record_tool_call"):
        dispatched = await execute_tool(node, "memory__read", args,
                                        {"memory__read": {"tool_type": MEMORY_READ_TOOL_TYPE, "spec": spec}})
    assert dispatched["success"]
    assert calls == [{"pool": pool, "spec": spec, "arguments": args}] * 3

    monkeypatch.setattr(capabilities, "_providers", {})
    refused = await execute_platform_tool_from_ctx({"tool_type": MEMORY_WRITE_TOOL_TYPE, "spec": spec}, args, None)
    assert refused == {"success": False, "error": "Memory isn't available here."}


async def test_a_rehearsal_reads_memory_and_fabricates_saves(calls, monkeypatch):
    from nodes.agent import tool_execution

    assert MEMORY_READ_TOOL_TYPE in REHEARSAL_PASSTHROUGH_TOOL_TYPES
    assert MEMORY_WRITE_TOOL_TYPE not in REHEARSAL_PASSTHROUGH_TOOL_TYPES
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: object())
    monkeypatch.setattr(tool_execution, "is_rehearsing", AsyncMock(return_value=True))
    fabricated = AsyncMock(return_value={"success": True, "saved": "world"})
    monkeypatch.setattr(tool_execution, "rehearse_tool", fabricated)
    node = MagicMock(user_id=None, workflow_id=None, node_id="agent", conversation_id="rehearsal:wf:1",
                     execution_id=None)
    configs = {
        "memory__read": {"tool_type": MEMORY_READ_TOOL_TYPE, "spec": {**SPEC, "tool": "memory__read"}},
        "memory__save": {"tool_type": MEMORY_WRITE_TOOL_TYPE, "spec": {**SPEC, "tool": "memory__save"}},
    }
    with patch("utils.tool_call_log.record_tool_call"):
        await tool_execution.execute_tool(node, "memory__read", {"name": "tone"}, configs)
        saved = await tool_execution.execute_tool(node, "memory__save", {"name": "tone", "content": "x"}, configs)
    assert [c["spec"]["tool"] for c in calls] == ["memory__read"]
    assert saved == {"success": True, "saved": "world"} and fabricated.await_count == 1
