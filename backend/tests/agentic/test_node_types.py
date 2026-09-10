"""Regression coverage for the builder's node-type prompt catalog."""

from coder.workflow.agentic.node_types import _get_available_node_types


def test_structural_agent_tool_providers_are_advertised_to_the_builder():
    """An agent can only select structural providers that its prompt exposes."""
    catalog = _get_available_node_types()
    processing = next(line for line in catalog.splitlines() if line.startswith("PROCESSING: "))

    assert "alarm" in processing.split(": ", 1)[1].split(", ")
    assert "filesystem" in processing.split(": ", 1)[1].split(", ")
