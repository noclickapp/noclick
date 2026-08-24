"""Every SDK agent gets upload_file — parity with the CLI harnesses.

CLI harnesses inject a sandbox-keyed upload_file shadow tool unconditionally
(cloud/agent/runtime/cli_shadow.py); the SDK path used to gate its synthesized
upload_file on a FilesystemNode or a repo mount, leaving a bare SDK agent —
which still has execute_bash and a lazy sandbox — with no way to publish files
it creates. The synthesis is now unconditional, with a wired FilesystemNode's
own tool definition taking precedence.
"""

from nodes.agent_node import AgentNode
from nodes.filesystem_node import UPLOAD_FILE_TOOL_NAME, get_upload_tool_definition


def _bare_agent() -> AgentNode:
    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_nodes = []
    agent._workflow_edges = []
    return agent


def test_bare_sdk_agent_gets_upload_file():
    """No FilesystemNode, no mounts, no tools at all — upload_file is still
    on the belt, matching the CLI harnesses' unconditional shadow injection."""
    tool_params, tool_configs, _ = _bare_agent()._collect_tool_definitions({})

    assert UPLOAD_FILE_TOOL_NAME in tool_configs
    assert tool_configs[UPLOAD_FILE_TOOL_NAME]["tool_type"] == "filesystem"
    names = [p["function"]["name"] for p in tool_params]
    assert UPLOAD_FILE_TOOL_NAME in names


def test_wired_filesystem_node_definition_wins():
    """A FilesystemNode's own upload_file must not be clobbered or duplicated
    by the synthesized fallback — the config keeps the filesystem node's id,
    not the agent's."""
    agent = _bare_agent()
    agent._workflow_edges = [
        {"source": "fs-1", "target": "agent-1", "targetHandle": "bottom"}
    ]
    inputs = {"fs-1": {"type": "tool_definition", **get_upload_tool_definition()}}

    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)

    assert tool_configs[UPLOAD_FILE_TOOL_NAME]["node_id"] == "fs-1"
    names = [p["function"]["name"] for p in tool_params]
    assert names.count(UPLOAD_FILE_TOOL_NAME) == 1
