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
