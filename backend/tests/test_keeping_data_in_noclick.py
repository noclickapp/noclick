"""The open edition's default prompts know a workflow can keep what it collects in NoClick itself. Asked to keep a
scheduled workflow's rows in NoClick rather than a Google Sheet, the builder found only the interface SDK's tables,
decided a scheduled run couldn't keep anything, and the coordinator told the owner NoClick couldn't do it."""

from coder.coordinator import prompts as coordinator_defaults
from coder.workflow.agentic import prompts_default
from coder.workflow.structural_tools import STRUCTURAL_AGENT_TOOL_TYPES, get_structural_agent_tool_provider
from nodes.core.registry import NODE_REGISTRY


def test_the_builder_is_told_how_a_workflow_keeps_data_between_runs():
    stable, _ = prompts_default.build_system_prompt_parts()
    assert "a filesystem node wired into an agent keeps the agent's files from run to run" in stable
    # A node the builder can wire into an agent (an edge to it is a tools edge), whose storage persists.
    assert "filesystem" in NODE_REGISTRY and "filesystem" in STRUCTURAL_AGENT_TOOL_TYPES
    assert "persistent" in get_structural_agent_tool_provider("filesystem").description


def test_the_coordinator_is_told_a_workflow_needs_no_spreadsheet_to_keep_data():
    prompt = coordinator_defaults.system_prompt(in_credits=False, phone_steps=False)
    assert "keep what it collects in NoClick itself, with no spreadsheet or database account" in prompt
