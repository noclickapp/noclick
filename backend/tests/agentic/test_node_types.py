"""Regression coverage for the builder's node-type prompt catalog."""

from coder.workflow.agentic.node_types import _get_available_node_types
from coder.workflow.operation_catalog import (
    get_native_agent_tools_for_node_type,
    get_operations_for_node_type,
)


def test_structural_agent_tool_providers_are_advertised_to_the_builder():
    """An agent can only select structural providers that its prompt exposes."""
    catalog = _get_available_node_types()
    processing = next(line for line in catalog.splitlines() if line.startswith("PROCESSING: "))

    assert "alarm" in processing.split(": ", 1)[1].split(", ")
    assert "filesystem" in processing.split(": ", 1)[1].split(", ")


def test_structural_provider_tools_are_advertised_without_calling_them_config_operations():
    catalog = _get_available_node_types()

    providers = next(line for line in catalog.splitlines() if line.startswith("STRUCTURAL AGENT TOOL PROVIDERS: "))
    assert "alarm: schedule_alarm, list_alarms, cancel_alarm, update_alarm" in providers
    assert "filesystem: upload_file" in providers
    assert "tool: runtime-discovered/custom tools" in providers
    assert "mcp-server: runtime-discovered/custom tools" in providers
    assert "noclick: runtime-discovered/custom tools" in providers
    assert "not config operations" in providers


def test_every_structural_provider_is_listed_as_processing():
    catalog = _get_available_node_types()
    processing = next(line for line in catalog.splitlines() if line.startswith("PROCESSING: "))

    for node_type in ("tool", "mcp-server", "noclick", "alarm", "filesystem"):
        assert node_type in processing.split(": ", 1)[1].split(", ")


def test_native_alarm_tools_are_kept_separate_from_alarm_config_operations():
    """Alarm emits runtime tools; its UI config has one ordinary operation."""
    assert [op.name for op in get_operations_for_node_type("alarm")] == ["default"]
    assert [tool.name for tool in get_native_agent_tools_for_node_type("alarm")] == [
        "schedule_alarm", "list_alarms", "cancel_alarm", "update_alarm",
    ]


def _line(catalog: str, prefix: str) -> str:
    return next(line for line in catalog.splitlines() if line.startswith(prefix))


def test_the_prompt_names_the_most_used_integrations_not_all_of_them():
    """Naming all ~1,240 took 6,000 tokens of every turn; the rest are found with <find_nodes>."""
    from coder.workflow.agentic import node_types
    from utils.node_search import knows_demand

    catalog = _get_available_node_types()
    if not knows_demand():  # the open edition: none named
        assert _line(catalog, "INTEGRATIONS: ").endswith("each `automation-<app>`")
        return
    named = _line(catalog, "INTEGRATIONS: ").split(": ", 2)[2].split(", ")
    assert len(named) == node_types.PROMPT_INTEGRATIONS
    assert {"automation-gmail", "automation-slack", "automation-google-sheets", "automation-hubspot"} <= set(named)
    assert "automation-hetrixtools" not in named
    assert len(catalog) < 5_000


def test_every_integration_with_a_trigger_operation_is_trigger_capable():
    """Reading the config union by hand took only its first member, so Gmail and Telegram were never named."""
    from coder.workflow.agentic.node_types import _has_trigger_operation

    assert _has_trigger_operation("automation-gmail")
    assert _has_trigger_operation("automation-telegram")
    assert not _has_trigger_operation("automation-http-request")






def test_an_invented_type_is_refused_with_the_nearest_ones():
    from coder.workflow.agentic.commands import execute_graph_mutations
    from coder.workflow.graph_state import GraphState
    from coder.workflow.workflow_xml import parse_xml

    results, added = execute_graph_mutations(parse_xml('<add_node type="automation-sharepoint" name="sp" />'),
                                             GraphState())
    assert added == []
    assert any("Nearest by name or purpose: automation-microsoft-sharepoint" in r for r in results)
