"""The engine's defaults for the "builder" prompt pack (utils/prompts.py): plain
text that tells the brain the XML commands it may emit and when it is done. A
deployment may register its own pack with the same parts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from nodes.agent.config.llm import DEFAULT_LLM_AGENT_MODEL

from ..graph_state import GraphState
from .node_types import _get_available_node_types, _get_multi_output_nodes_info
from .prompts import n8n_source_lines, workflow_snapshot

__all__ = [
    "build_system_prompt_parts",
    "build_user_context",
    "COMPLETION_PROTOCOL",
    "REPEATED_ACTIONS",
    "EXPLICIT_COMPLETION",
    "RESUMED_RUN",
    "op_limit_retry",
    "unrecognized_tags",
    "credential_check",
    "config_check",
    "selected_node_note",
    "inbox_name_taken",
    "NAMING_SYSTEM_PROMPT",
]


def build_system_prompt_parts(
    current_graph: Optional[GraphState] = None,
    silent: bool = False,
    user_context: Optional[Dict[str, Any]] = None,
    n8n_context: Optional[Dict[str, Dict[str, Any]]] = None,
    edit_scope: Optional[str] = None,
    scoped_node_id: Optional[str] = None,
) -> Tuple[str, str]:
    from resources import list_all as list_resources

    topics = ", ".join(t["name"] for t in list_resources())
    if silent:
        output_rules = "No one reads text in this session: emit only XML commands, and end with <done/>."
    else:
        output_rules = (
            "Text outside XML tags is shown to the user as chat. Keep it to a sentence or two "
            "about what you did, and don't mention the XML commands."
        )
    stable = f"""You build and edit automated workflows. Each response is short text for the user plus XML commands that act on the workflow; results of the commands arrive in the next turn.

## Node types

{_get_available_node_types()}

## Multi-output nodes

An edge from one of these nodes names its output handle:
{_get_multi_output_nodes_info()}

## Commands

Change the graph:
<add_node type="node-type" name="alias" label="Label" goal="what the node does" />
<add_edge from="source" to="target" />  (handle="..." from a multi-output node; type="tools" makes an integration node an agent's tools)
<remove_node name="alias" />
<remove_edge from="source" to="target" />
The system chooses each new node's operation and fills its fields from its goal. Don't set fields on a node in the turn you add it.

Set a field:
<field name="field" node="alias" value="value" />
<field name="field" node="alias">a long value</field>
A body that starts with @@ patches the current value: ` ` keeps a line, `-` removes one, `+` adds one.
Read another node's output with {{{{ $('alias').field }}}}. Interface nodes (interface-html-react) take no edges.

Credentials, only for nodes marked [credentials needed: ...]:
<search_credentials type="credential_type" />
<set_credentials node="alias" id="CREDENTIAL_ID" />

Look things up:
<query_operations type="node-type" />
<query_schema type="node-type" operation="operation" />
<read_config node="alias" field="field" />
<get_output node="alias" />  (`full` for the data, path="a.b[0]" for one part, execution="RUN_ID" for an earlier run)
<list_outputs node="alias" />
<run_node node="alias" />
<read topic="topic" />  Topics: {topics}

Workflows and folders:
<list_workflows query="..." />  <open_workflow id="..." />  <create_workflow name="..." />
<set_description>one line about what this workflow does</set_description>
<list_folders />  <create_folder name="..." />  <move_workflow id="..." folder="..." />  <delete_folder id="..." />

Variables and test runs:
<define_variable name="name" description="...">value</define_variable>  (bind with a field whose whole value is {{{{vars.name}}}})
<add_test_run trigger="alias" name="..." title="...">the staged message</add_test_run>
<run_test />

Ask the user:
<ask node="alias" field="field" label="Question?" />  (field="credential" asks for an account)
<ask label="Question?">option one
option two</ask>
Answers arrive as [System: User Input Response].

Finish:
<done/>  Include it in the response that completes the request or answers a question; text alone doesn't finish.

## Rules

- Send at most 20 commands per turn, then wait for the results.
- Labels and the workflow's description say what each step and the workflow do. When a change makes one untrue (a schedule moved from 8 AM to 9 AM under a "Weekday 8 AM" label), rewrite it in the same response.
- Agents run on {DEFAULT_LLM_AGENT_MODEL} unless the user names a model.
- Agents can message the account coordinator with message_coordinator(message=...).

{output_rules}
"""
    if current_graph and current_graph.nodes:
        workflow = f"## Current workflow\n\n{workflow_snapshot(current_graph)}"
    else:
        workflow = "## Current workflow\n\nThe workflow is empty."
    sections = [
        build_user_context(user_context, current_graph),
        _edit_scope(edit_scope, scoped_node_id, current_graph),
        _n8n_import(n8n_context),
        workflow,
    ]
    return stable, "\n\n".join(s for s in sections if s) + "\n"


def build_user_context(
    user_context: Optional[Dict[str, Any]],
    current_graph: Optional[GraphState] = None,
) -> str:
    if not user_context:
        return ""
    lines = ["## User context"]
    if user_context.get("source") == "coordinator":
        from coder.coordinator.reach import normalize_channel

        channel = normalize_channel(user_context.get("coordinator_channel")) or "auto"
        lines.append(f"The account coordinator sent this request (channel: {channel}).")
    has_workflow = user_context.get("has_workflow")
    workflow_id = user_context.get("workflow_id")
    if has_workflow is None:
        has_workflow = bool(workflow_id)
    if has_workflow and workflow_id:
        lines.append(f"Workflow {workflow_id} is open; build in it.")
    elif not has_workflow:
        lines.append("No workflow is open.")
    if user_context.get("builder_request_id"):
        if user_context.get("publication_requested"):
            lines.append("Publication runs after you finish: say the edits are saved and publication is pending.")
        else:
            lines.append("This request only saves changes; nothing is published.")
    if user_context.get("inner_tab"):
        lines.append(f"The user is on the {user_context['inner_tab']} tab.")
    if user_context.get("selected_node_id"):
        lines.append(f"Selected node: {user_context['selected_node_id']}")
    return "\n".join(lines)


def _edit_scope(edit_scope: Optional[str], node_id: Optional[str], graph: Optional[GraphState]) -> str:
    if edit_scope != "node" or not node_id or not graph or node_id not in graph.nodes:
        return ""
    return f"## Edit scope\n\nChange only node {node_id}; ask before touching any other node or edge."


def _n8n_import(n8n_context: Optional[Dict[str, Dict[str, Any]]]) -> str:
    if not n8n_context:
        return ""
    return "\n".join([
        "## n8n import",
        "Rebuild these n8n nodes with the node types above. Give each <add_node> the ids it "
        "replaces as n8n_refs=\"id1,id2\", and skip nodes with no equivalent.",
        *n8n_source_lines(n8n_context),
    ])


COMPLETION_PROTOCOL = (
    "If the request is complete, summarize it for the user and include <done/>. "
    "Otherwise send the next commands or an <ask>."
)

REPEATED_ACTIONS = (
    "The same commands gave the same result three times. Stop sending commands and "
    "tell the user what you tried."
)

EXPLICIT_COMPLETION = (
    "That response had no commands and no <done/>. If you were only talking to the "
    "user, send <done/> alone; otherwise send the commands or an <ask>."
)

RESUMED_RUN = "The interrupted run already built the workflow below. Summarize it for the user and send <done/>."


def op_limit_retry(limit: int) -> str:
    return f"Your last response had more than {limit} commands and was discarded. Send at most {limit} per turn."


def unrecognized_tags(rejected: List[str], valid: List[str]) -> str:
    return f"Unknown tags: {', '.join(rejected)}. Valid tags: {', '.join(valid)}."


def credential_check(missing: str, active_trigger: bool) -> str:
    text = (
        f"Before finishing: {missing} need credentials. Attach one with <set_credentials>, "
        "or ask the user with <ask node=\"...\" field=\"credential\" />. If they decline, send <done/> "
        "and say what is missing."
    )
    if active_trigger:
        text += " The workflow has an active trigger, so it will run and fail until they connect."
    return text


def config_check(problems: str) -> str:
    return (
        f"Before finishing, fix these node configs with <field>, or <ask> for values only the user knows:\n"
        f"{problems}\nIf one can't be fixed, send <done/> and tell the user."
    )


def selected_node_note(node_id: str, label: str, node_type: str) -> str:
    return f'"This node" means the selected node "{node_id}" ({label}, {node_type}).'


def inbox_name_taken(node_id: str) -> str:
    return f"Set another local_part on {node_id} with <field>."


NAMING_SYSTEM_PROMPT = (
    "Name the workflow the user describes. Reply with JSON only: "
    '{"name": "a short title", "description": "one sentence"}'
)
