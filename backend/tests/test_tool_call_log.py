"""
Tests for tool-call observability: the durable per-invocation records
captured at tool_execution.execute_tool (the single choke point for all
harnesses) and the tool_call_log recorder.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.mocks.mock_asyncpg import MockNativePool

from nodes.agent.tool_execution import execute_tool
from utils.tool_call_log import (
    _bounded_arguments,
    _insert,
    _redact_protected_payloads,
    _to_uuid,
    fetch_tool_calls_since,
    mark_protected_tool_arguments,
)


def _agent_node():
    return SimpleNamespace(
        user_id="11111111-1111-1111-1111-111111111111",
        organization_id=None,
        workflow_id="22222222-2222-2222-2222-222222222222",
        node_id="agent-1",
        conversation_id="conv-1",
        execution_id="33333333-3333-3333-3333-333333333333",
    )


async def test_execute_tool_records_successful_call():
    tool_configs = {
        "linear__create_issue": {
            "node_id": "provider-1",
            "tool_type": "node_op",
            "node_type": "automation-linear",
            "operation": "create_issue",
            "credential_id": "44444444-4444-4444-4444-444444444444",
        }
    }
    with patch(
        "nodes.core.run_op.run_node_operation",
        new=AsyncMock(return_value={"status": "success", "action": "create_issue"}),
    ), patch("utils.tool_call_log.record_tool_call") as record:
        result = await execute_tool(
            _agent_node(), "linear__create_issue", {"title": "Bug"}, tool_configs
        )

    assert result["status"] == "success"
    record.assert_called_once()
    kw = record.call_args.kwargs
    assert kw["tool_name"] == "linear__create_issue"
    assert kw["tool_type"] == "node_op"
    assert kw["result_status"] == "success"
    assert kw["operation"] == "create_issue"
    assert kw["provider_node_id"] == "provider-1"
    assert kw["credential_id"] == "44444444-4444-4444-4444-444444444444"
    assert kw["execution_id"] == "33333333-3333-3333-3333-333333333333"
    assert kw["arguments"] == {"title": "Bug"}
    assert kw["error"] is None
    assert kw["duration_ms"] is not None


async def test_execute_tool_records_exception_as_error():
    tool_configs = {
        "linear__create_issue": {
            "node_id": "p",
            "tool_type": "node_op",
            "node_type": "automation-linear",
            "operation": "create_issue",
            "credential_id": "cred-9",
        }
    }
    with patch(
        "nodes.core.run_op.run_node_operation",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ), patch("utils.tool_call_log.record_tool_call") as record:
        result = await execute_tool(_agent_node(), "linear__create_issue", {}, tool_configs)

    assert result["success"] is False
    kw = record.call_args.kwargs
    assert kw["result_status"] == "error"
    assert "boom" in kw["error"]


async def test_execute_tool_records_soft_failure_as_error():
    """Handlers that return {success: False} (no raise) still record an error."""
    tool_configs = {"t": {"node_id": "p", "tool_type": "node_op"}}  # missing operation
    with patch("utils.tool_call_log.record_tool_call") as record:
        result = await execute_tool(_agent_node(), "t", {}, tool_configs)

    assert result["success"] is False
    kw = record.call_args.kwargs
    assert kw["result_status"] == "error"
    assert "node_type/operation" in kw["error"]


async def test_shopify_tool_audit_omits_protected_payloads():
    tool_configs = {
        "shopify__get_customer": {
            "node_id": "shopify-1",
            "tool_type": "node_op",
            "node_type": "automation-shopify",
            "operation": "get_customer_by_id",
            "credential_id": "44444444-4444-4444-4444-444444444444",
        }
    }
    protected_result = {
        "status": "success",
        "data": {"customer": {"email": "buyer@example.com"}},
    }
    provider = AsyncMock(return_value=protected_result)
    with patch(
        "nodes.core.run_op.run_node_operation",
        new=provider,
    ), patch("utils.tool_call_log.record_tool_call") as record:
        result = await execute_tool(
            _agent_node(),
            "shopify__get_customer",
            {"customer_id": "123"},
            tool_configs,
        )

    assert result == protected_result
    assert provider.await_args.kwargs["arguments"] == {"customer_id": "123"}
    kw = record.call_args.kwargs
    arguments, error, preview = _redact_protected_payloads(
        kw["arguments"], kw["error"], kw["result_preview"]
    )
    assert arguments is None
    assert preview is None
    assert error is None


def test_protected_tool_audit_replaces_provider_error_bodies():
    arguments, error, preview = _redact_protected_payloads(
        mark_protected_tool_arguments({"customer_id": "123"}),
        "Shopify returned buyer@example.com in an error body",
        "customer payload",
    )

    assert arguments is None
    assert error == "Shopify operation failed"
    assert preview is None


async def test_insert_passes_typed_values_through_pool():
    captured = {}

    async def fake_execute(sql, *args, timeout=None):
        captured["sql"] = sql
        captured["args"] = args

    pool = MockNativePool()
    pool.execute.side_effect = fake_execute
    with patch("utils.database_pool.get_native_pool", return_value=pool):
        await _insert(
            user_id="11111111-1111-1111-1111-111111111111",
            workflow_id="22222222-2222-2222-2222-222222222222",
            execution_id=None,
            conversation_id="conv-1",
            agent_node_id="agent-1",
            tool_name="linear__create_issue",
            tool_type="node_op",
            provider_node_id="p1",
            operation="create_issue",
            credential_id="not-a-uuid",  # tolerated → NULL, never raises
            arguments={"title": "Bug"},
            result_status="success",
            error=None,
            result_preview="ok",
            duration_ms=12.7,
        )

    args = captured["args"]
    import uuid

    assert isinstance(args[0], uuid.UUID)  # user_id coerced
    assert args[2] is None  # execution_id absent
    assert args[9] is None  # invalid credential uuid → NULL
    # Plain dict passed to the pool — the jsonb codec serializes it;
    # pre-dumping would double-encode.
    assert args[10] == {"title": "Bug"}
    assert args[14] == 12  # duration truncated to int ms


def test_arguments_bounded():
    small = {"a": 1}
    assert _bounded_arguments(small) == small
    huge = {"blob": "x" * 50_000, "other": 1}
    bounded = _bounded_arguments(huge)
    assert bounded["_truncated"] is True
    assert bounded["_keys"] == ["blob", "other"]
    assert _bounded_arguments(None) is None


# ============================================================================
# Response-package read side: fetch_tool_calls_since (scoped by node,
# conversation, and an advancing timestamp boundary)
# ============================================================================

import datetime as _dt


async def test_fetch_tool_calls_since_maps_rows_and_returns_boundary():
    now = _dt.datetime(2026, 6, 30, 12, 0, 0, tzinfo=_dt.timezone.utc)
    created = _dt.datetime(2026, 6, 30, 11, 59, 0, tzinfo=_dt.timezone.utc)
    rows = [{
        "tool_name": "linear__create_issue", "tool_type": "node_op",
        "operation": "create_issue", "provider_node_id": "p1",
        "credential_id": "cred-1", "result_status": "success", "error": None,
        "result_preview": "ok", "arguments": {"title": "Bug"}, "duration_ms": 12,
        "model": "codex", "created_at": created, "query_now": now,
    }]
    captured = {}

    async def fake_fetch(sql, *args, timeout=None):
        captured["args"] = args
        return rows

    pool = MockNativePool()
    pool.fetch.side_effect = fake_fetch
    with patch("utils.database_pool.get_native_pool", return_value=pool):
        tools, boundary = await fetch_tool_calls_since(
            agent_node_id="agent-1", conversation_id="ck:wf:agent-1:key",
            after="2026-06-30T11:58:00+00:00", lookback_s=14400,
        )

    # Window query is scoped + bounded: (agent_node_id, conversation_id, after, lookback, cap).
    # `after` reaches the pool as a DATETIME — asyncpg's timestamptz codec rejects
    # the raw ISO string stored in Redis.
    assert captured["args"] == (
        "agent-1", "ck:wf:agent-1:key",
        _dt.datetime(2026, 6, 30, 11, 58, 0, tzinfo=_dt.timezone.utc), 14400, 200,
    )
    assert boundary == now.isoformat()       # next window's lower bound
    assert len(tools) == 1
    t = tools[0]
    assert t["tool_name"] == "linear__create_issue"
    assert t["arguments"] == {"title": "Bug"}  # jsonb decoded to a dict
    assert t["created_at"] == created.isoformat()
    assert "query_now" not in t                # internal column not surfaced


async def test_fetch_tool_calls_since_empty_leaves_boundary_unset():
    # No tool calls this response → don't advance the boundary, so a late-landing
    # fire-and-forget insert is still caught by the next response's window.
    async def fake_fetch(sql, *args, timeout=None):
        return []

    pool = MockNativePool()
    pool.fetch.side_effect = fake_fetch
    with patch("utils.database_pool.get_native_pool", return_value=pool):
        tools, boundary = await fetch_tool_calls_since(
            agent_node_id="a", conversation_id="c", after=None, lookback_s=60,
        )
    assert tools == [] and boundary is None


async def test_fetch_tool_calls_since_requires_scope():
    # Without a conversation scope the window would mix concurrent conversations
    # on one node — refuse rather than return mixed data.
    tools, boundary = await fetch_tool_calls_since(
        agent_node_id="a", conversation_id="", after=None, lookback_s=60,
    )
    assert tools == [] and boundary is None


def test_to_uuid_tolerates_garbage():
    assert _to_uuid(None) is None
    assert _to_uuid("nope") is None
    assert str(_to_uuid("11111111-1111-1111-1111-111111111111")) == (
        "11111111-1111-1111-1111-111111111111"
    )


# ============================================================================
# execute_bash recording (SDK FunctionTool — bypasses the execute_tool
# choke point, records directly in Agent._make_execute_bash_tool)
# ============================================================================

import json as _json


def _bare_agent_with_runtime(run_bash_result):
    from coder.openai_agent.agent import Agent

    agent = object.__new__(Agent)
    agent.user_id = "11111111-1111-1111-1111-111111111111"
    agent.workflow_id = "22222222-2222-2222-2222-222222222222"
    agent.node_id = "agent-1"
    agent.conversation_id = "conv-1"
    agent.execution_id = "33333333-3333-3333-3333-333333333333"
    agent._runtime = SimpleNamespace(
        run_bash=AsyncMock(return_value=run_bash_result),
        _fs_config={"node_id": "fs-1"},
        mount_path="/workspace",
        sandbox_setups=[],
        # Real SandboxRuntime always sets this in __init__; the tool description
        # reads it to advertise user env-var NAMES to the model.
        user_env={},
    )
    return agent


async def _invoke_bash(agent, command="echo hi"):
    tool = agent._make_execute_bash_tool()
    with patch("utils.tool_call_log.record_tool_call") as rec:
        out = await tool.on_invoke_tool(None, _json.dumps({"command": command}))
    return out, rec


async def test_execute_bash_records_success_with_exit_code():
    agent = _bare_agent_with_runtime({"stdout": "hi\n", "stderr": "", "exit_code": 0})
    out, rec = await _invoke_bash(agent)
    assert _json.loads(out)["exit_code"] == 0
    rec.assert_called_once()
    kw = rec.call_args.kwargs
    assert kw["tool_name"] == "execute_bash" and kw["tool_type"] == "bash"
    assert kw["result_status"] == "success"
    assert kw["arguments"] == {"command": "echo hi"}
    assert kw["execution_id"] == "33333333-3333-3333-3333-333333333333"
    assert kw["agent_node_id"] == "agent-1"
    assert kw["provider_node_id"] == "fs-1"
    assert "exit 0" in kw["result_preview"]
    assert kw["duration_ms"] >= 0


async def test_execute_bash_nonzero_exit_is_not_an_error():
    # Agents probe with failing commands constantly (`which gh`, `grep -q`) —
    # a non-zero exit is a successful tool execution, not a failure.
    agent = _bare_agent_with_runtime({"stdout": "", "stderr": "no such file", "exit_code": 2})
    _, rec = await _invoke_bash(agent, "ls /nope")
    kw = rec.call_args.kwargs
    assert kw["result_status"] == "success"
    assert "exit 2" in kw["result_preview"]
    assert "no such file" in kw["result_preview"]
    assert kw["error"] is None


async def test_execute_bash_infra_failure_records_error():
    agent = _bare_agent_with_runtime({"error": "Sandbox unavailable: image build failed"})
    _, rec = await _invoke_bash(agent)
    kw = rec.call_args.kwargs
    assert kw["result_status"] == "error"
    assert "Sandbox unavailable" in kw["error"]
    assert kw["result_preview"] is None


async def test_execute_bash_records_without_volume():
    agent = _bare_agent_with_runtime({"stdout": "", "stderr": "", "exit_code": 0})
    agent._runtime._fs_config = None  # ephemeral provider-mount sandbox
    _, rec = await _invoke_bash(agent)
    assert rec.call_args.kwargs["provider_node_id"] is None
