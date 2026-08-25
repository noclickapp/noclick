"""
Node type catalog helpers for the agentic brain's system prompt.

Introspects NODE_REGISTRY to emit human-readable descriptions of available
node types and multi-output handle metadata. Used when building the brain's
system prompt so it knows what nodes it can use.
"""

from __future__ import annotations

from typing import Union, get_args, get_origin

from nodes.core.registry import NODE_REGISTRY


def _has_trigger_operation(node_type: str) -> bool:
    """True if `node_type`'s config model has any operation flagged `x-is-trigger`.

    Walks the node's config-model discriminated union and reads
    `json_schema_extra` on each variant's `operation` discriminator field.
    Lightweight introspection — kept inline rather than reusing
    operation_catalog.get_operations_for_node_type so this helper stays
    decoupled from the heavier extension runtime (litellm, GraphState, etc).
    """
    node_class = NODE_REGISTRY.get(node_type)
    if not node_class:
        return False

    config_model = getattr(node_class, 'get_config_model', lambda: None)()
    if not config_model:
        return False

    config_field = config_model.model_fields.get('config')
    if not config_field:
        return False

    config_type = config_field.annotation
    # Unwrap Annotated[Union[...], Discriminator] → Union[...]
    if get_origin(config_type) is not None:
        args = get_args(config_type)
        if args:
            config_type = args[0]

    union_members = get_args(config_type) if get_origin(config_type) is Union else [config_type]

    for member in union_members:
        if not hasattr(member, 'model_fields'):
            continue
        op_field = member.model_fields.get('operation')
        if not op_field:
            continue
        extra = op_field.json_schema_extra or {}
        if isinstance(extra, dict) and extra.get('x-is-trigger'):
            return True
    return False


def _get_available_node_types() -> str:
    """Generate available node types string from the registry."""
    triggers = []
    integrations = []
    processing = []
    interface = []
    trigger_capable = []  # automation-* nodes with at least one `x-is-trigger` operation

    # Node types that are processing/control flow, not integrations
    processing_types = {'agent', 'tool', 'iteration', 'automation-serverless-function', 'mcp-server'}

    for node_type in NODE_REGISTRY.keys():
        if node_type.startswith('test-'):
            continue  # Skip test nodes
        elif node_type.startswith('trigger-'):
            triggers.append(node_type)
        elif node_type in processing_types:
            processing.append(node_type)
        elif node_type.startswith('interface-'):
            interface.append(node_type)
        elif node_type.startswith('automation-'):
            integrations.append(node_type)
            if _has_trigger_operation(node_type):
                trigger_capable.append(node_type)

    lines = [
        f"TRIGGERS: {', '.join(sorted(triggers))}",
        f"TRIGGER-CAPABLE INTEGRATIONS (can be used as a workflow entry node): {', '.join(sorted(trigger_capable))}",
        f"INTEGRATIONS: {', '.join(sorted(integrations))}",
        f"PROCESSING: {', '.join(sorted(processing))}",
        f"INTERFACE: {', '.join(sorted(interface))}",
    ]
    return "\n".join(lines)


def _get_multi_output_nodes_info() -> str:
    """Generate info about nodes with multiple output handles.

    Introspects node classes via get_output_handles() method to discover
    which nodes have multiple outputs. This keeps the node class as the
    single source of truth for handle definitions.
    """
    lines = []

    for node_type, node_class in NODE_REGISTRY.items():
        # Skip test nodes
        if node_type.startswith('test-'):
            continue

        # Check if node has output handles defined
        handles = node_class.get_output_handles()
        if handles:
            handle_descs = [f'"{h["id"]}" ({h["description"]})' for h in handles]
            lines.append(f"- {node_type}: handles are {', '.join(handle_descs)}")

    return "\n".join(lines)
