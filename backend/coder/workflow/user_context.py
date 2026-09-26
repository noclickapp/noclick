"""Shared builder context, including the requested publication outcome."""

from typing import Any, Dict, Optional

from coder.workflow.graph_state import GraphState


def build_user_context(
    user_context: Optional[Dict[str, Any]],
    current_graph: Optional[GraphState] = None,
) -> str:
    """Build context section describing what the user is currently looking at."""
    if not user_context:
        return ""
    parts = ["## Current User Context"]
    if user_context.get("source") == "coordinator":
        from coder.coordinator.reach import normalize_channel

        channel = normalize_channel(user_context.get("coordinator_channel")) or "auto"
        parts.append(
            f"This request came from the account coordinator on channel '{channel}'. "
            "For alerts to this same owner, configure the agent to call its built-in "
            "message_coordinator tool with purpose='owner_alert' and the requested channel "
            f"(default '{channel}' unless the instructions choose another). The coordinator delivers the alert "
            "through its existing owner channel. No recipient number, messaging credential, or outbound "
            "provider node is needed for this route. Include this in the agent's goal and standing instructions. "
            "This does not give the workflow access to WhatsApp inboxes, groups, or other recipients; "
            "those still require their own integration and destination."
        )
    has_workflow = user_context.get('has_workflow')
    workflow_id = user_context.get('workflow_id')
    workflow_name = user_context.get('workflow_name')
    # A present workflow_id means a workflow IS open. Only derive when the flag
    # is absent (the resume-after-ask path passes workflow_id without it); an
    # explicit False still wins. Without this, a missing flag fell through to
    # "does NOT have a workflow open", which made the brain re-add existing nodes.
    if has_workflow is None:
        has_workflow = bool(workflow_id)
    if has_workflow and workflow_id:
        wf_label = f'"{workflow_name}" ({workflow_id})' if workflow_name else workflow_id
        parts.append(f"The user has workflow {wf_label} open. Add nodes directly to this workflow — do NOT create a new workflow unless the user explicitly asks for one.")
    elif not has_workflow:
        parts.append("The user does NOT have a workflow open. If they mention an existing workflow, use <list_workflows> to find it and <open_workflow> to navigate there.")
    if user_context.get("builder_request_id"):
        if user_context.get("publication_requested"):
            parts.append("This managed request includes publication after building. Save the requested edits and emit <done/>; "
                         "the request runner will deploy them and report the actual URL. Your summary must say the changes "
                         "are saved and publication is pending, not that they are already live.")
        else:
            parts.append("This managed request only saves changes. No publication was requested. "
                         "Do not claim these edits updated the public site, even if the snapshot has a live URL.")
    inner_tab = user_context.get('inner_tab')
    if inner_tab:
        parts.append(f"The user is viewing the '{inner_tab}' tab.")
        if inner_tab == 'interface':
            parts.append(
                "They are looking at the Interface tab — they want a custom UI. "
                "Unless they are explicitly asking to edit an existing interface node, "
                "default to creating a NEW `interface-html-react` node. "
                "Add it with a DETAILED `goal` describing the UI — what it shows/does, and which "
                "nodes' data it reads (the system wires those via `nodes.getOutput(...)`). "
                "Do NOT write `jsx_source` or set `operation`/`fullscreen` yourself on the new node — "
                "the system authors a fullscreen React interface from your goal (node drafting). "
                "To refine an EXISTING interface afterward, edit its `jsx_source` directly with a `<field>` patch. "
                "Never add ReactFlow edges to interface-html-react nodes."
            )
    selected = user_context.get('selected_node_id')
    if selected:
        parts.append(f"The user has selected node/block: {selected}")
        # Add type info for the selected node
        if current_graph and selected in current_graph.nodes:
            node = current_graph.nodes[selected]
            parts.append(f"  Type: {node.type}, Operation: {node.operation or 'not set'}")
            # Hint about reading its config
            long_fields = [k for k, v in node.config.items() if v and len(str(v)) > 120]
            if long_fields:
                parts.append(f"  Has large config fields: {', '.join(long_fields)} — use <read_config node=\"{selected}\" field=\"...\"> to inspect")
    return "\n".join(parts)
