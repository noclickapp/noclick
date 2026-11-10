"""
Node type catalog helpers for the agentic brain's system prompt.

Introspects NODE_REGISTRY to emit human-readable descriptions of available
node types and multi-output handle metadata. Used when building the brain's
system prompt so it knows what nodes it can use.
"""

from __future__ import annotations

from typing import Union, get_args, get_origin

from nodes.core.registry import NODE_REGISTRY, is_listed
from ..operation_catalog import get_native_agent_tools_for_node_type
from ..structural_tools import STRUCTURAL_AGENT_TOOL_PROVIDERS, STRUCTURAL_AGENT_TOOL_TYPES
from utils.node_search import by_popularity, knows_demand


def _has_trigger_operation(node_type: str) -> bool:
    """True if any of ``node_type``'s operations is flagged ``x-is-trigger``, as the operation catalog reads them.

    Reading the config union by hand took only its first member for a plain ``Union``, so 77 of the 97 integrations
    with triggers (Gmail, Stripe, Telegram, ...) were never named trigger-capable."""
    return any(op.is_trigger for op in get_operations_for_node_type(node_type))


# Integrations the prompt names, the most used first, where the deployment knows which those are (``NODE_DEMAND``):
# the brain finds every other one with <find_nodes>. Naming all ~1,240 took 6,000 tokens of every turn and still named
# nothing by what it does.
PROMPT_INTEGRATIONS = 60


def _get_available_node_types() -> str:
    """Generate available node types string from the registry."""
    triggers = []
    integrations = []
    processing = []
    interface = []
    trigger_capable = []  # automation-* nodes with at least one `x-is-trigger` operation

    # Structural agent-tool providers are not integrations, but the builder
    # must still see them.  In particular, ``alarm`` is wired into an agent's
    # bottom handle to let it schedule future wake-ups; omitting it here made
    # the brain conclude that the native Alarm node did not exist even though
    # it is registered and supported by the graph-command layer.
    processing_types = {
        'agent', 'iteration', 'automation-serverless-function',
    } | STRUCTURAL_AGENT_TOOL_TYPES

    for node_type in NODE_REGISTRY.keys():
        if node_type.startswith('test-') or not is_listed(node_type):
            continue  # test nodes, and retired services saved nodes still run on
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

    structural_tool_providers = []
    for provider in STRUCTURAL_AGENT_TOOL_PROVIDERS:
        tools = get_native_agent_tools_for_node_type(provider.node_type)
        if tools:
            surface = ', '.join(tool.name for tool in tools)
        else:
            surface = 'runtime-discovered/custom tools'
        structural_tool_providers.append(
            f"{provider.node_type}: {surface} "
            "(automatically exposed when wired to an agent; not config operations)"
        )

    lines = [f"TRIGGERS: {', '.join(sorted(triggers))}"]
    if knows_demand():
        named = by_popularity(integrations)[:PROMPT_INTEGRATIONS]
        lines += [
            f"INTEGRATIONS: {len(integrations)} apps, each `automation-<app>`; the {len(named)} most used: "
            f"{', '.join(named)}",
            "TRIGGER-CAPABLE among those (can be used as a workflow entry node): "
            f"{', '.join(t for t in named if t in set(trigger_capable))}",
        ]
    else:  # nothing says which are used most, and naming any 60 would be arbitrary
        lines.append(f"INTEGRATIONS: {len(integrations)} apps, each `automation-<app>`")
    lines += [
        f"PROCESSING: {', '.join(sorted(processing))}",
        f"INTERFACE: {', '.join(sorted(interface))}",
    ]
    if structural_tool_providers:
        lines.append("STRUCTURAL AGENT TOOL PROVIDERS: " + "; ".join(structural_tool_providers))
    return "\n".join(lines)


def _get_multi_output_nodes_info() -> str:
    """Generate info about nodes with multiple output handles.

    Introspects node classes via get_output_handles() method to discover
    which nodes have multiple outputs. This keeps the node class as the
    single source of truth for handle definitions.
    """
    from nodes.core.catalog import every_node_facts

    lines = []

    for node_type, facts in every_node_facts().items():
        # Skip test nodes
        if node_type.startswith('test-'):
            continue

        # Check if node has output handles defined (the node catalog's copy of get_output_handles)
        handles = facts["output_handles"]
        if handles:
            handle_descs = [f'"{h["id"]}" ({h["description"]})' for h in handles]
            lines.append(f"- {node_type}: handles are {', '.join(handle_descs)}")

    return "\n".join(lines)
