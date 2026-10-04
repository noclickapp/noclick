"""Bound arguments (``nodes.agent.tool_binding``): a bound parameter leaves an
operation tool's schema, is filled from the turn's person, wins over what the
model passes (pass-through objects included), and is what the tool-call guard
judges and the operation runs with. (The CLI pool's side is a hosted test:
``cloud/tests/platform/test_platform_binding.py``.)"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from coder.workflow.workflow_ops import validate_agent_tool_operations
from nodes.agent import tool_binding
from nodes.agent.node_op_tools import build_node_op_tools, build_provider_output
from nodes.agent.tool_execution import execute_tool
from utils import capabilities

SEND = "send_email_message"
USER = {"id": "user_42", "email": "ana@example.com", "name": "Ana", "metadata": {"plan": "pro", "seats": 3}}


def test_templates_fill_from_the_person_and_keep_a_whole_value_s_type():
    filled = tool_binding.fill({"to": "{{user.email}}", "prefix": "users/{{ user.id }}/",
                                "seats": "{{user.metadata.seats}}", "fixed": 7}, USER)
    assert filled == {"to": "ana@example.com", "prefix": "users/user_42/", "seats": 3, "fixed": 7}
    # Anything the person lacks leaves the binding unfillable; no person fills nothing templated.
    assert tool_binding.fill({"to": "{{user.metadata.region}}"}, USER) is None
    assert tool_binding.fill({"to": "{{user.email}}"}, {**USER, "email": None}) is None
    assert tool_binding.fill({"to": "{{user.email}}"}, None) is None
    assert tool_binding.fill({"to": "ops@acme.com"}, None) == {"to": "ops@acme.com"}


def test_only_the_person_s_fields_are_templates():
    assert tool_binding.template_error({"to": "{{user.email}}", "x": ["{{user.metadata.k}}"]}) is None
    problem = tool_binding.template_error({"to": "{{secrets.key}}"})
    assert problem and "{{secrets.key}}" in problem and "{{user.email}}" in problem


def test_bound_values_win_over_the_model_and_its_pass_through_objects():
    parameters = {"type": "object", "properties": {
        "amount": {"type": "integer"},
        "extra_params": {"anyOf": [{"type": "object", "additionalProperties": True}, {"type": "null"}]},
        "address": {"type": "object", "properties": {"customer": {"type": "string"}}},
    }}
    final = tool_binding.apply(
        {"amount": 5, "customer": "cus_evil", "extra_params": {"customer": "cus_evil", "memo": "hi"},
         "address": {"customer": "kept"}},
        {"customer": "cus_42"}, parameters)
    assert final == {"amount": 5, "customer": "cus_42", "extra_params": {"memo": "hi"},
                     "address": {"customer": "kept"}}
    stripped = tool_binding.strip({"type": "object", "properties": {"to": {}, "subject": {}},
                                   "required": ["to", "subject"]}, ["to"])
    assert stripped == {"type": "object", "properties": {"subject": {}}, "required": ["subject"]}


def test_a_bound_operation_leaves_its_schema_and_carries_its_values():
    entry = {"operation": SEND, "bind": {"to": "{{user.email}}"}}
    params, configs = build_node_op_tools("automation-gmail", [entry, "fetch_emails_from_inbox"], node_id="gmail",
                                          tool_user=USER)
    send = configs[f"gmail__{SEND}"]
    assert "to" not in send["_parameters"]["properties"] and "to" not in send["_parameters"].get("required", [])
    assert "subject" in send["_parameters"]["properties"]
    assert send[tool_binding.BOUND_ARGUMENTS_KEY] == {"to": "ana@example.com"}
    model_facing = next(p for p in params if p["function"]["name"] == f"gmail__{SEND}")
    assert "to" not in model_facing["function"]["parameters"]["properties"]
    assert tool_binding.BOUND_ARGUMENTS_KEY not in configs["gmail__fetch_emails_from_inbox"]

    # A person without an email: the bound operation isn't offered this turn; the rest are.
    _, configs = build_node_op_tools("automation-gmail", [entry, "fetch_emails_from_inbox"], node_id="gmail",
                                     tool_user={"id": "user_7"})
    assert f"gmail__{SEND}" not in configs and "gmail__fetch_emails_from_inbox" in configs


def test_a_provider_node_s_allowlist_keeps_its_bindings():
    output = build_provider_output("automation-gmail", {"agent_tool_operations": [
        {"operation": SEND, "bind": {"to": "ops@acme.com"}}, "fetch_emails_from_inbox"]})
    assert output["allowed_operations"] == [{"operation": SEND, "bind": {"to": "ops@acme.com"}},
                                            "fetch_emails_from_inbox"]


def test_the_allowlist_validator_checks_what_a_binding_fixes():
    ok, error = validate_agent_tool_operations("automation-gmail", [{"operation": SEND, "bind": {"to": "a@b.co"}}])
    assert error is None and ok == [{"operation": SEND, "bind": {"to": "a@b.co"}}]
    _, error = validate_agent_tool_operations("automation-gmail", [{"operation": SEND, "bind": {"recipient": "x"}}])
    assert "takes no parameter 'recipient'" in error
    _, error = validate_agent_tool_operations("automation-gmail", [{"operation": SEND, "bind": {"to": "{{env.X}}"}}])
    assert "isn't something NoClick fills in" in error
    _, error = validate_agent_tool_operations("automation-gmail", [{"operation": SEND, "bind": {}}])
    assert "bind must be an object" in error


@pytest.fixture
def guarded(monkeypatch):
    seen = []

    async def guard(**call):
        seen.append(call["arguments"])
        return None

    monkeypatch.setitem(capabilities._providers, capabilities.TOOL_CALL_GUARD, guard)
    run = AsyncMock(return_value={"success": True, "id": "msg-1"})
    with patch("nodes.core.run_op.run_node_operation", new=run), patch("utils.tool_call_log.record_tool_call"):
        yield SimpleNamespace(seen=seen, run=run)


@pytest.mark.asyncio
async def test_the_guard_judges_and_the_operation_runs_with_the_final_arguments(guarded):
    _, configs = build_node_op_tools("automation-gmail", [{"operation": SEND, "bind": {"to": "{{user.email}}"}}],
                                     node_id="gmail", tool_user=USER)
    node = SimpleNamespace(user_id="u", organization_id=None, workflow_id="w", node_id="agent",
                           conversation_id="c", execution_id=None)
    result = await execute_tool(node, f"gmail__{SEND}", {"to": "attacker@evil.test", "subject": "Hi", "body": "x"},
                                configs)
    assert result["success"] is True
    final = {"to": "ana@example.com", "subject": "Hi", "body": "x"}
    assert guarded.seen == [final]
    assert guarded.run.await_args.kwargs["arguments"] == final
