"""
Tests for node_op agent tools: the schema→tool converter
(nodes/agent/node_op_tools.py), the graph-free single-operation runner
(nodes/core/run_op.py), and the execute_tool dispatch branch
(nodes/agent/tool_execution.py).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.agent.node_op_tools import (
    build_node_op_tools,
    build_provider_output,
    is_node_op_provider,
    list_node_operations,
    node_supports_op_tools,
)
from nodes.agent.tool_execution import execute_tool
from nodes.core.run_op import (
    resolve_operation_credential,
    run_node_lookup,
    run_node_operation,
)


# ============================================================================
# Converter: qualifying predicate
# ============================================================================


def test_integration_nodes_qualify():
    for node_type in (
        "automation-linear",
        "automation-github-rest",
        "automation-google-sheets",
        "automation-reddit",
    ):
        assert node_supports_op_tools(node_type), node_type


def test_structural_nodes_do_not_qualify():
    for node_type in (
        "agent",
        "tool",
        "mcp-server",
        "alarm",
        "filesystem",
        "filter",
        "merge",
        "conditional",
        "interface-html-react",
        "trigger-webhook",
        "no-such-node-type",
    ):
        assert not node_supports_op_tools(node_type), node_type


# ============================================================================
# Converter: tool building
# ============================================================================


def test_build_linear_tools_shapes():
    params, configs = build_node_op_tools(
        "automation-linear",
        ["create_issue", "update_issue"],
        node_id="provider-1",
        credential_id="cred-123",
    )

    names = [p["function"]["name"] for p in params]
    # op tools in allowlist order + the companion lookup tool (these ops have
    # dynamic-option fields)
    assert names == ["linear__create_issue", "linear__update_issue", "linear__lookup_options"]

    create = next(p for p in params if p["function"]["name"] == "linear__create_issue")
    fn = create["function"]
    assert fn["description"] == "Create a new Linear issue"
    assert fn["parameters"]["required"] == ["title", "teamId"]
    props = fn["parameters"]["properties"]
    # operation const is stripped; field schemas keep their descriptions
    assert "operation" not in props
    assert props["teamId"]["description"]

    cfg = configs["linear__create_issue"]
    assert cfg["tool_type"] == "node_op"
    assert cfg["node_type"] == "automation-linear"
    assert cfg["operation"] == "create_issue"
    assert cfg["credential_id"] == "cred-123"
    assert cfg["node_id"] == "provider-1"
    # Shadow-injection pair must be present and match the LLM-facing schema
    assert cfg["_description"] == fn["description"]
    assert cfg["_parameters"] == fn["parameters"]


def test_trigger_operations_not_exposed():
    ops = {o["operation"] for o in list_node_operations("automation-linear")}
    assert "create_issue" in ops
    assert "on_issue_created" not in ops  # trigger ops are excluded from node op tools

    # Allowlisting a trigger op builds nothing rather than a broken tool
    params, configs = build_node_op_tools(
        "automation-linear", ["on_issue_created"], node_id="provider-1"
    )
    assert params == [] and configs == {}


def test_parameters_are_self_contained_and_clean():
    """Built parameter schemas ship standalone into sandbox MCP configs:
    no dangling $refs, no frontend-only ui:/x- extension keys."""
    for node_type in (
        "automation-linear",
        "automation-google-sheets",
        "automation-reddit",
        "automation-github-rest",
    ):
        all_ops = [o["operation"] for o in list_node_operations(node_type)]
        params, _ = build_node_op_tools(node_type, all_ops, node_id="p")
        assert params, node_type
        for p in params:
            blob = json.dumps(p["function"]["parameters"])
            assert "$ref" not in blob, (node_type, p["function"]["name"])
            assert '"ui:' not in blob, (node_type, p["function"]["name"])
            assert '"x-' not in blob, (node_type, p["function"]["name"])


def test_http_request_composite_body_fields_are_agent_visible():
    """The frontend hides composite-editor backing fields, but an agent needs
    them in its tool schema or every JSON/form/raw request is sent empty."""
    operations = (
        "send_http_post_request",
        "send_http_put_request",
        "send_http_patch_request",
        "send_http_delete_request",
    )
    params, _ = build_node_op_tools(
        "automation-http-request", list(operations), node_id="http-provider"
    )

    assert len(params) == len(operations)
    for param in params:
        properties = param["function"]["parameters"]["properties"]
        assert {"body_type", "body", "body_form", "content_type_override"} <= set(
            properties
        )
        blob = json.dumps(param["function"]["parameters"])
        assert '"ui:' not in blob
        assert '"x-' not in blob


def test_github_operations_unique_and_refined():
    """Pins the duplicate-class cleanup: every GitHub operation appears once,
    and the surviving submit_pull_request_review definition is the refined
    one (its event enum includes SUBMIT)."""
    ops = [o["operation"] for o in list_node_operations("automation-github-rest")]
    assert len(ops) == len(set(ops))

    params, _ = build_node_op_tools(
        "automation-github-rest", ["submit_pull_request_review"], node_id="p"
    )
    event = params[0]["function"]["parameters"]["properties"]["event"]
    assert "SUBMIT" in event["enum"]


def test_unknown_node_type_raises():
    with pytest.raises(ValueError):
        build_node_op_tools("no-such-node", ["op"], node_id="p")
    with pytest.raises(ValueError):
        list_node_operations("no-such-node")


# ============================================================================
# Companion lookup tool (dynamic-options fields)
# ============================================================================


def test_dynamic_fields_get_lookup_tool_and_enriched_descriptions():
    params, configs = build_node_op_tools(
        "automation-linear", ["create_issue"], node_id="p", credential_id="c1"
    )
    names = [p["function"]["name"] for p in params]
    assert names == ["linear__create_issue", "linear__lookup_options"]

    # Dynamic field descriptions reference the lookup tool
    team_id = params[0]["function"]["parameters"]["properties"]["teamId"]
    assert 'linear__lookup_options with field="teamId"' in team_id["description"]
    # Non-dynamic fields untouched
    assert "lookup_options" not in params[0]["function"]["parameters"]["properties"]["title"]["description"]

    lookup = configs["linear__lookup_options"]
    assert lookup["tool_type"] == "node_op_lookup"
    assert lookup["credential_id"] == "c1"
    # Config key → loader field_name translation is captured (non-trivial:
    # assigneeId routes to the user_id loader)
    assert lookup["fields"]["teamId"] == "team_id"
    assert lookup["fields"]["assigneeId"] == "user_id"

    lookup_fn = next(p for p in params if p["function"]["name"] == "linear__lookup_options")["function"]
    assert set(lookup_fn["parameters"]["properties"]) == {"field", "context", "search", "page_token"}
    assert lookup_fn["parameters"]["required"] == ["field"]
    assert "teamId" in lookup_fn["parameters"]["properties"]["field"]["enum"]
    # depends_on chains surface in the tool description
    assert "stateId" in lookup_fn["description"]
    assert "requires teamId in context" in lookup_fn["description"]


def test_sheets_lookup_covers_dependent_chain():
    params, configs = build_node_op_tools(
        "automation-google-sheets", ["append_rows_to_sheet"], node_id="p"
    )
    lookup = configs["google_sheets__lookup_options"]
    assert set(lookup["fields"]) == {"spreadsheet_id", "sheet_name"}
    desc = next(p for p in params if "lookup" in p["function"]["name"])["function"]["description"]
    assert "requires spreadsheet_id in context" in desc


def test_no_lookup_tool_without_dynamic_fields():
    params, configs = build_node_op_tools("automation-linear", ["list_teams"], node_id="p")
    assert [p["function"]["name"] for p in params] == ["linear__list_teams"]
    assert "linear__lookup_options" not in configs


async def test_execute_tool_dispatches_node_op_lookup():
    tool_configs = {
        "linear__lookup_options": {
            "node_id": "p",
            "tool_type": "node_op_lookup",
            "node_type": "automation-linear",
            "credential_id": "c1",
            "fields": {"teamId": "team_id", "stateId": "state_id"},
        }
    }
    expected = {"options": [{"label": "Eng", "value": "t1"}], "next_page_token": None}
    with patch(
        "nodes.core.run_op.run_node_lookup", new=AsyncMock(return_value=expected)
    ) as mock_lookup:
        result = await execute_tool(
            _fake_agent_node(),
            "linear__lookup_options",
            {"field": "stateId", "context": {"teamId": "t1"}},
            tool_configs,
        )
    assert result == expected
    kwargs = mock_lookup.call_args.kwargs
    assert kwargs["field_name"] == "state_id"  # config key translated to loader key
    assert kwargs["context"] == {"teamId": "t1"}
    assert kwargs["user_id"] == "user-1"


async def test_execute_tool_lookup_rejects_unknown_field():
    tool_configs = {
        "linear__lookup_options": {
            "node_id": "p",
            "tool_type": "node_op_lookup",
            "node_type": "automation-linear",
            "fields": {"teamId": "team_id"},
        }
    }
    result = await execute_tool(
        _fake_agent_node(), "linear__lookup_options", {"field": "ownerId"}, tool_configs
    )
    assert result["success"] is False
    assert "teamId" in result["error"]


async def test_run_node_lookup_executes_real_loader():
    """Through the real LinearNode.load_field_options: credential freshen path,
    _user_id context injection, and {options, next_page_token} normalization —
    only the GraphQL HTTP call is mocked."""
    payload = {"teams": {"nodes": [{"id": "t1", "name": "Engineering", "key": "ENG"}]}}
    creds = {"credential_type": "linear_pat", "api_key": "lin_api_test"}

    with patch(
        "nodes.linear_node._linear_graphql_call", new=AsyncMock(return_value=payload)
    ) as gql, patch(
        "nodes.core.run_op.resolve_operation_credential",
        new=AsyncMock(return_value=creds),
    ):
        result = await run_node_lookup(
            node_type="automation-linear",
            field_name="team_id",
            user_id="user-1",
            credential_id="cred-1",
            pool=object(),
        )

    assert result["options"] == [
        {"value": "t1", "label": "Engineering (ENG)", "metadata": {"key": "ENG"}}
    ]
    assert result["next_page_token"] is None
    gql.assert_awaited_once()


async def test_run_node_lookup_unknown_node_raises():
    with pytest.raises(ValueError, match="Unknown node type"):
        await run_node_lookup(
            node_type="no-such-node", field_name="x", user_id="u", pool=object()
        )


def test_operation_enumerators_agree_across_registry():
    """Drift tripwire: the agent-tool enumerator (_iter_operation_defs, walks
    the emitted JSON schema) and the extension builder's enumerator
    (operation_catalog.get_operations_for_node_type, introspects the Pydantic
    union) derive from different sources by necessity — one needs member JSON
    schemas, the other config classes. They MUST agree on the operation set
    and display metadata for every provider-qualifying node, or the allowlist
    UI and the builder show different operations for the same node."""
    from nodes.core.registry import NODE_REGISTRY
    from nodes.agent.node_op_tools import _iter_operation_defs
    from coder.workflow.operation_catalog import get_operations_for_node_type

    compared = 0
    for node_type, node_class in sorted(NODE_REGISTRY.items()):
        if not node_supports_op_tools(node_type):
            continue
        compared += 1
        schema_ops = {
            e["operation"]: (
                e["operation_schema"].get("x-display-name"),
                e["operation_schema"].get("x-category"),
            )
            for e in _iter_operation_defs(node_class)
        }
        selector_ops = {
            o.name: (o.display_name, o.category)
            for o in get_operations_for_node_type(node_type)
            if not o.is_trigger
        }
        assert set(schema_ops) == set(selector_ops), (
            f"{node_type}: operation sets diverged: "
            f"{sorted(set(schema_ops) ^ set(selector_ops))[:6]}"
        )
        for op, meta in schema_ops.items():
            assert meta == selector_ops[op], f"{node_type}.{op}: metadata diverged"
    assert compared >= 50  # the predicate qualifying ~58 types is itself pinned


# ============================================================================
# Provider mode (integration node wired to an agent's bottom handle)
# ============================================================================

_NODES = [
    {"id": "agent-1", "type": "agent"},
    {"id": "linear-1", "type": "automation-linear"},
    {"id": "tool-1", "type": "tool"},
    {"id": "sheets-1", "type": "automation-google-sheets"},
]


def test_is_node_op_provider_detects_agent_bottom_edge():
    edges = [{"source": "linear-1", "target": "agent-1", "targetHandle": "bottom", "sourceHandle": "top"}]
    assert is_node_op_provider("linear-1", "automation-linear", _NODES, edges)


def test_is_node_op_provider_negative_cases():
    bottom_edge = [{"source": "linear-1", "target": "agent-1", "targetHandle": "bottom"}]
    # normal dataflow edge into the agent is NOT provider mode
    left_edge = [{"source": "linear-1", "target": "agent-1", "targetHandle": None}]
    # bottom edge into a non-agent node
    non_agent = [{"source": "linear-1", "target": "sheets-1", "targetHandle": "bottom"}]

    assert not is_node_op_provider("linear-1", "automation-linear", _NODES, left_edge)
    assert not is_node_op_provider("linear-1", "automation-linear", _NODES, non_agent)
    # existing ToolNode must never short-circuit into provider mode
    assert not is_node_op_provider("tool-1", "tool", _NODES, bottom_edge)
    assert not is_node_op_provider("linear-1", "automation-linear", None, bottom_edge)
    assert not is_node_op_provider("linear-1", "automation-linear", _NODES, None)


def test_build_provider_output_flat_config():
    output = build_provider_output(
        "automation-linear",
        {
            "agent_tool_operations": ["create_issue", "update_issue"],
            "credentialIds": {"credential_type": "linear_oauth", "linear_oauth": "cred-7"},
        },
    )
    assert output == {
        "type": "node_op_tool_provider",
        "node_type": "automation-linear",
        "allowed_operations": ["create_issue", "update_issue"],
        "credential_id": "cred-7",
        "label": None,
        "sandbox_repos": [],
    }


def test_build_provider_output_nested_mirror_and_defaults():
    # FE mirrors fields under a nested 'config'; outer fields win, empty
    # credential entries and unresolved references are skipped
    output = build_provider_output(
        "automation-google-sheets",
        {
            "config": {
                "agent_tool_operations": ["append_row"],
                "credentialIds": {"google_oauth": ""},
            },
        },
    )
    assert output["allowed_operations"] == ["append_row"]
    assert output["credential_id"] is None

    empty = build_provider_output("automation-linear", {})
    assert empty["allowed_operations"] == []
    assert empty["credential_id"] is None


def test_same_type_providers_get_distinct_tool_names():
    """Two providers of the SAME node type wired to one agent must not
    collide — and the MODEL needs a semantic signal to pick between them:
    slugs come from the user-given node label (node id only as fallback),
    and node label + credential name are stamped into every description."""
    from nodes.agent_node import AgentNode

    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_edges = [
        {"source": "linear_a", "target": "agent-1", "targetHandle": "bottom"},
        {"source": "linear_b", "target": "agent-1", "targetHandle": "bottom"},
    ]
    inputs = {
        "linear_a": {
            "type": "node_op_tool_provider",
            "node_type": "automation-linear",
            "allowed_operations": ["create_issue"],
            "credential_id": "cred-a",
            "label": "Work Linear",
            "credential_label": "alex@work",
        },
        "linear_b": {
            "type": "node_op_tool_provider",
            "node_type": "automation-linear",
            "allowed_operations": ["create_issue"],
            "credential_id": "cred-b",
            # no label/credential_label — falls back to node-id slug
        },
    }

    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)
    names = [p["function"]["name"] for p in tool_params]
    assert len(names) == len(set(names)), f"colliding tool names: {names}"

    # Labeled provider: label-derived slug + label/credential tags in description
    assert tool_configs["work_linear__create_issue"]["credential_id"] == "cred-a"
    work_tool = next(p for p in tool_params if p["function"]["name"] == "work_linear__create_issue")
    assert "'Work Linear' node" in work_tool["function"]["description"]
    assert "'alex@work' credential" in work_tool["function"]["description"]

    # Unlabeled provider: node-id slug, tagged with the node id
    assert tool_configs["linear_b__create_issue"]["credential_id"] == "cred-b"
    b_tool = next(p for p in tool_params if p["function"]["name"] == "linear_b__create_issue")
    assert "'linear_b' node" in b_tool["function"]["description"]

    # The companion lookup tools must not collide either
    assert "work_linear__lookup_options" in tool_configs
    assert "linear_b__lookup_options" in tool_configs


def test_single_provider_keeps_clean_tool_names():
    """A provider wired to a DIFFERENT agent must not trigger collision
    renaming for this agent's sole provider."""
    from nodes.agent_node import AgentNode

    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_edges = [
        {"source": "linear_a", "target": "agent-1", "targetHandle": "bottom"},
        {"source": "linear_b", "target": "agent-2", "targetHandle": "bottom"},
    ]
    provider = {
        "type": "node_op_tool_provider",
        "node_type": "automation-linear",
        "allowed_operations": ["list_teams"],
        "credential_id": None,
    }
    inputs = {"linear_a": dict(provider), "linear_b": dict(provider)}

    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)
    assert [p["function"]["name"] for p in tool_params] == ["linear__list_teams"]
    assert tool_configs["linear__list_teams"]["node_id"] == "linear_a"


def test_graph_builders_tolerate_dangling_and_duplicate_edges():
    """Stale canvas state can carry edges referencing deleted nodes or exact
    duplicates. Neither is a dependency: a dangling edge formerly bumped the
    target's in-degree with a source that never executes — reported as a
    FALSE cycle ('processed N-1 of N') with an empty cycle hint."""
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    h = object.__new__(WorkflowExecutionHandler)
    nodes = [
        {"id": "agent-1", "type": "agent"},
        {"id": "linear-1", "type": "automation-linear"},
    ]
    edges = [
        {"id": "e1", "source": "linear-1", "target": "agent-1", "targetHandle": "bottom"},
        # exact duplicate (different id)
        {"id": "e2", "source": "linear-1", "target": "agent-1", "targetHandle": "bottom"},
        # dangling source (node deleted, edge survived)
        {"id": "e3", "source": "ghost-node", "target": "agent-1", "targetHandle": "bottom"},
        # dangling target
        {"id": "e4", "source": "linear-1", "target": "other-ghost"},
    ]

    order = h._topological_sort(nodes, edges)
    assert order == ["linear-1", "agent-1"]

    # _build_dependency_maps must not KeyError on the ghost target nor park
    # agent-1 behind a ghost predecessor the concurrent executor waits on
    predecessors, node_by_id, successors, predecessor_edges = h._build_dependency_maps(nodes, edges)
    assert predecessors["agent-1"] == {"linear-1"}
    assert "ghost-node" not in predecessors["agent-1"]

    # A REAL cycle is still detected and described
    cyclic_edges = [
        {"id": "c1", "source": "linear-1", "target": "agent-1"},
        {"id": "c2", "source": "agent-1", "target": "linear-1"},
    ]
    assert h._topological_sort(nodes, cyclic_edges) == []
    assert "agent-1" in h._describe_cycle(nodes, cyclic_edges)


def test_triggered_runs_backfill_bottom_edge_providers():
    """start_node-scoped (webhook/cron) runs must include tool providers
    wired to a reachable agent's bottom handle — otherwise the agent's
    edge-scoped collection finds no provider edge and triggered runs get
    zero tools while manual full-graph runs work."""
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    nodes = [
        {"id": "trig", "type": "trigger-webhook"},
        {"id": "agent-1", "type": "agent"},
        {"id": "linear-1", "type": "automation-linear"},
        {"id": "unrelated", "type": "automation-slack"},
    ]
    edges = [
        {"source": "trig", "target": "agent-1"},
        {"source": "linear-1", "target": "agent-1", "sourceHandle": "top", "targetHandle": "bottom"},
        {"source": "unrelated", "target": "trig"},  # upstream of trigger, not backfilled
    ]

    handler = object.__new__(WorkflowExecutionHandler)
    reachable_nodes, reachable_edges = handler._get_reachable_nodes("trig", nodes, edges)

    reachable_ids = {n["id"] for n in reachable_nodes}
    assert "linear-1" in reachable_ids  # provider re-executes in triggered runs
    assert "unrelated" not in reachable_ids
    assert any(
        e.get("source") == "linear-1" and e.get("targetHandle") == "bottom"
        for e in reachable_edges
    )  # the provider→agent edge survives for edge-scoped collection


def test_legacy_tool_surfaces_are_edge_scoped_too():
    """Two agents, each with its own MCP server: agent A must NOT inherit
    agent B's MCP tools (which carry B's server auth config) just because
    both outputs are in node_outputs. Same for ToolNode/alarm/filesystem."""
    from nodes.agent_node import AgentNode

    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_edges = [
        {"source": "mcp-mine", "target": "agent-1", "targetHandle": "bottom"},
        {"source": "mcp-other", "target": "agent-2", "targetHandle": "bottom"},
    ]
    mcp_output = lambda name: {  # noqa: E731
        "type": "mcp_tool_definitions",
        "tools": [{
            "tool_name": name,
            "tool_type": "mcp",
            "tool_description": "d",
            "parameters": [],
            "mcp_server_config": {"url": f"https://{name}.example.com"},
        }],
    }
    inputs = {"mcp-mine": mcp_output("mine_tool"), "mcp-other": mcp_output("admin_tool")}

    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)
    assert [p["function"]["name"] for p in tool_params] == ["mine_tool"]
    assert "admin_tool" not in tool_configs


def test_agent_collects_only_edge_wired_providers():
    """Two agents + two providers in one run: each agent must collect tools
    only from the provider wired into ITS bottom handle (node_outputs carries
    every provider output, so collection must be edge-scoped)."""
    from nodes.agent_node import AgentNode

    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_edges = [
        {"source": "linear-1", "target": "agent-1", "targetHandle": "bottom"},
        {"source": "linear-2", "target": "agent-2", "targetHandle": "bottom"},
    ]

    provider_output = {
        "type": "node_op_tool_provider",
        "node_type": "automation-linear",
        "allowed_operations": ["list_teams"],
        "credential_id": None,
    }
    inputs = {"linear-1": dict(provider_output), "linear-2": dict(provider_output)}

    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)
    assert [p["function"]["name"] for p in tool_params] == ["linear__list_teams"]
    assert tool_configs["linear__list_teams"]["node_id"] == "linear-1"


# ============================================================================
# Dispatch: execute_tool routes node_op
# ============================================================================


def _fake_agent_node():
    return SimpleNamespace(
        user_id="user-1",
        organization_id="org-1",
        workflow_id="wf-1",
        node_id="agent-1",
        conversation_id="conv-1",
    )


async def test_execute_tool_dispatches_node_op():
    tool_configs = {
        "linear__create_issue": {
            "node_id": "provider-1",
            "tool_type": "node_op",
            "node_type": "automation-linear",
            "operation": "create_issue",
            "credential_id": "cred-9",
        }
    }
    expected = {"type": "linear", "status": "success"}
    with patch(
        "nodes.core.run_op.run_node_operation", new=AsyncMock(return_value=expected)
    ) as mock_run:
        result = await execute_tool(
            _fake_agent_node(),
            "linear__create_issue",
            {"title": "Bug"},
            tool_configs,
        )

    assert result == expected
    kwargs = mock_run.call_args.kwargs
    assert kwargs["node_type"] == "automation-linear"
    assert kwargs["operation"] == "create_issue"
    assert kwargs["arguments"] == {"title": "Bug"}
    assert kwargs["user_id"] == "user-1"
    assert kwargs["credential_id"] == "cred-9"
    assert kwargs["organization_id"] == "org-1"
    assert kwargs["workflow_id"] == "wf-1"


async def test_execute_tool_node_op_missing_config_returns_error():
    tool_configs = {"broken": {"node_id": "p", "tool_type": "node_op"}}
    result = await execute_tool(_fake_agent_node(), "broken", {}, tool_configs)
    assert result["success"] is False
    assert "node_type/operation" in result["error"]


async def test_execute_tool_node_op_error_surfaces_as_dict():
    """Runner exceptions must come back to the model as {success: False},
    not abort the agent turn."""
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
        new=AsyncMock(side_effect=ValueError("Failed to resolve credential cred-9")),
    ):
        result = await execute_tool(
            _fake_agent_node(), "linear__create_issue", {}, tool_configs
        )
    assert result["success"] is False
    assert "cred-9" in result["error"]


def test_dynamic_op_tools_carry_lookup_pointer():
    """Ops with dynamic-option ID fields point at their lookup tool so the
    failure path can tell the agent how to resolve a bad ID."""
    _, configs = build_node_op_tools(
        "automation-google-sheets", ["read_sheet_data"], node_id="p", credential_id="c1"
    )
    read = configs["google_sheets__read_sheet_data"]
    assert read["lookup_tool"] == "google_sheets__lookup_options"
    assert "spreadsheet_id" in read["lookup_fields"]
    # Ops without dynamic fields (and providers with no loader) carry no pointer.
    _, linear = build_node_op_tools("automation-linear", ["list_teams"], node_id="p")
    assert "lookup_tool" not in linear["linear__list_teams"]


async def test_node_op_error_includes_lookup_hint():
    """A failed action whose provider has a lookup tool nudges the agent to
    resolve the offending ID via that tool — this is the runtime safety net
    for prompts that hardcode a display name where an ID is expected."""
    tool_configs = {
        "google_sheets__read_sheet_data": {
            "node_id": "p",
            "tool_type": "node_op",
            "node_type": "automation-google-sheets",
            "operation": "read_sheet_data",
            "credential_id": "c1",
            "lookup_tool": "google_sheets__lookup_options",
            "lookup_fields": ["spreadsheet_id", "sheet_name"],
        }
    }
    with patch(
        "nodes.core.run_op.run_node_operation",
        new=AsyncMock(side_effect=RuntimeError("Requested entity was not found.")),
    ):
        result = await execute_tool(
            _fake_agent_node(),
            "google_sheets__read_sheet_data",
            {"spreadsheet_id": "30 Day AI Content Calendar"},
            tool_configs,
        )
    assert result["success"] is False
    assert "Requested entity was not found." in result["error"]
    assert "google_sheets__lookup_options" in result["error"]
    # Names the field the agent actually supplied, not every dynamic field.
    assert "'spreadsheet_id'" in result["error"]
    assert "sheet_name" not in result["error"]


async def test_node_op_soft_failure_includes_lookup_hint():
    """Nodes that return {success: False} instead of raising get the same nudge."""
    tool_configs = {
        "google_sheets__read_sheet_data": {
            "node_id": "p",
            "tool_type": "node_op",
            "node_type": "automation-google-sheets",
            "operation": "read_sheet_data",
            "credential_id": "c1",
            "lookup_tool": "google_sheets__lookup_options",
            "lookup_fields": ["spreadsheet_id"],
        }
    }
    with patch(
        "nodes.core.run_op.run_node_operation",
        new=AsyncMock(return_value={"success": False, "error": "not found"}),
    ):
        result = await execute_tool(
            _fake_agent_node(),
            "google_sheets__read_sheet_data",
            {"spreadsheet_id": "My Sheet"},
            tool_configs,
        )
    assert result["success"] is False
    assert "google_sheets__lookup_options" in result["error"]


async def test_node_op_error_no_hint_without_lookup_tool():
    """Providers without a lookup tool leave the error untouched."""
    tool_configs = {
        "linear__create_issue": {
            "node_id": "p",
            "tool_type": "node_op",
            "node_type": "automation-linear",
            "operation": "create_issue",
            "credential_id": "c1",
        }
    }
    with patch(
        "nodes.core.run_op.run_node_operation",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await execute_tool(
            _fake_agent_node(), "linear__create_issue", {"title": "x"}, tool_configs
        )
    assert result["error"] == "boom"
    assert "lookup_options" not in result["error"]


# ============================================================================
# Runner: standalone single-operation execution
# ============================================================================


def _mock_httpx_client(response_payload):
    """Mock httpx.AsyncClient async context manager whose post() returns the
    given GraphQL payload."""
    response = MagicMock()
    response.json.return_value = response_payload
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory, client


async def test_run_node_operation_executes_linear_create_issue():
    """End-to-end through the real LinearNode: discriminated-union config
    parse (with str coercion), operation dispatch, credential plumbing, and
    output shape — only the HTTP boundary is mocked."""
    payload = {
        "data": {
            "issueCreate": {
                "success": True,
                "issue": {"id": "iss-1", "identifier": "ENG-42", "title": "Bug"},
            }
        }
    }
    factory, client = _mock_httpx_client(payload)
    creds = {"credential_type": "linear_pat", "api_key": "lin_api_test_key"}

    with patch("nodes.linear_node.httpx.AsyncClient", factory), patch(
        "nodes.core.run_op.resolve_operation_credential",
        new=AsyncMock(return_value=creds),
    ) as mock_resolve:
        result = await run_node_operation(
            node_type="automation-linear",
            operation="create_issue",
            arguments={
                "title": "Bug",
                # native int for a str field — must coerce, not fail validation
                "teamId": 12345,
                # an LLM-supplied 'operation' must NOT override the declared op
                "operation": "delete_issue",
                # empty string for an optional field — must become None
                "description": "",
            },
            user_id="user-1",
            credential_id="cred-1",
            organization_id="org-1",
            workflow_id="wf-1",
        )

    mock_resolve.assert_awaited_once()
    assert result["status"] == "success"
    assert result["action"] == "create_issue"  # declared op won, not delete_issue

    sent = client.post.call_args.kwargs
    assert sent["headers"]["Authorization"]  # PAT header attached
    variables = sent["json"]["variables"]["input"]
    assert variables["title"] == "Bug"
    assert variables["teamId"] == "12345"  # coerced int → str
    assert "description" not in variables  # '' → None → omitted


async def test_run_node_operation_without_credential_id_skips_resolution():
    """No credential_id → no DB access; the node's own validation raises."""
    with patch(
        "nodes.core.run_op.resolve_operation_credential", new=AsyncMock()
    ) as mock_resolve:
        with pytest.raises(ValueError, match="[Cc]redential"):
            await run_node_operation(
                node_type="automation-linear",
                operation="create_issue",
                arguments={"title": "Bug", "teamId": "t-1"},
                user_id="user-1",
            )
        mock_resolve.assert_not_awaited()


# ============================================================================
# Credential resolution gating (run-as-owner) — exercises the SHARED policy
# (utils.credentials.resolve_credential_with_owner_fallback) through the
# runner's delegate, so the workflow handler and node_op path stay on one
# definition.
# ============================================================================


async def test_resolve_credential_runner_access_wins():
    creds = {"api_key": "k"}
    with patch(
        "utils.credentials.get_credential", new=AsyncMock(return_value=creds)
    ) as get_cred, patch(
        "utils.credentials.get_workflow_owner_id", new=AsyncMock()
    ) as owner_fn:
        result = await resolve_operation_credential(
            "cred-1", "runner-1", pool=object(), workflow_id="wf-1"
        )
    assert result == creds
    get_cred.assert_awaited_once()
    owner_fn.assert_not_awaited()


async def test_resolve_credential_owner_fallback_requires_authorization():
    """Runner miss + owner-authorized credential → resolved as owner."""
    creds = {"api_key": "owner-k"}
    get_cred = AsyncMock(side_effect=[None, creds])
    with patch("utils.credentials.get_credential", get_cred), patch(
        "utils.credentials.get_workflow_owner_id",
        new=AsyncMock(return_value="owner-1"),
    ), patch(
        "utils.credentials.is_credential_authorized_for_workflow",
        new=AsyncMock(return_value=True),
    ):
        result = await resolve_operation_credential(
            "cred-1", "runner-1", pool=object(), workflow_id="wf-1"
        )
    assert result == creds
    assert get_cred.call_args_list[1].args[1] == "owner-1"


async def test_resolve_credential_unauthorized_fallback_fails_closed():
    """Runner miss + credential NOT authorized for the workflow → ValueError,
    and the owner's credential is never fetched (exfiltration gate)."""
    get_cred = AsyncMock(return_value=None)
    with patch("utils.credentials.get_credential", get_cred), patch(
        "utils.credentials.get_workflow_owner_id",
        new=AsyncMock(return_value="owner-1"),
    ), patch(
        "utils.credentials.is_credential_authorized_for_workflow",
        new=AsyncMock(return_value=False),
    ):
        with pytest.raises(ValueError, match="Failed to resolve credential"):
            await resolve_operation_credential(
                "cred-1", "runner-1", pool=object(), workflow_id="wf-1"
            )
    assert get_cred.await_count == 1  # runner attempt only


async def test_resolve_credential_no_workflow_no_fallback():
    with patch(
        "utils.credentials.get_credential", new=AsyncMock(return_value=None)
    ), patch("utils.credentials.get_workflow_owner_id", new=AsyncMock()) as owner_fn:
        with pytest.raises(ValueError, match="Failed to resolve credential"):
            await resolve_operation_credential("cred-1", "runner-1", pool=object())
        owner_fn.assert_not_awaited()


def test_build_provider_output_accepts_handler_credential_variants():
    """build_provider_output must accept every credential shape the workflow
    handler accepts (single-id keys, legacy credentials object) — a config
    that resolves normally can't silently lose its credential in provider
    mode."""
    single_id = build_provider_output(
        "automation-linear",
        {"agent_tool_operations": ["get_issue"], "credential_id": "cred-single"},
    )
    assert single_id["credential_id"] == "cred-single"

    legacy_obj = build_provider_output(
        "automation-linear",
        {
            "agent_tool_operations": ["get_issue"],
            "credentials": {"credential_id": "cred-legacy"},
        },
    )
    assert legacy_obj["credential_id"] == "cred-legacy"
