"""Discover a connection's tools from the existing integration registry.

The coordinator and credential permissions UI share this catalog with agent
node tools: there is no second set of provider operations or argument schemas.
"""

from functools import lru_cache
import re


@lru_cache(maxsize=1)
def connection_catalog():
    from nodes.core.catalog import every_node_facts
    from nodes.core.credential_connect import owners_first

    candidates = []
    providers = {}
    for node_type, facts in every_node_facts().items():
        types = []
        for credential in facts["credentials"]:
            if credential["hidden"]:
                continue
            kind = credential["type"]
            candidates.append((node_type, kind, {
                "credential_type": kind,
                "name": kind if credential["title"] is None else credential["title"],
                "oauth_provider": credential["oauth_provider"],
                "connection_method": credential["method"],
            }))
            types.append(kind)
        if facts["agent_tool_provider"] and types:
            providers[node_type] = tuple(types)
    methods = {}
    for _, kind, method in owners_first(candidates):
        methods.setdefault(kind, method)
    return methods, providers


def compatible_providers(credential_type):
    methods, providers = connection_catalog()
    oauth = methods.get(credential_type, {}).get("oauth_provider")
    matches = [node_type for node_type, types in providers.items() if any(
        t == credential_type or (oauth and methods[t].get("oauth_provider") == oauth)
        for t in types
    )]
    # A Microsoft credential can power several integrations. Put the service
    # it was connected for first rather than whichever registry entry came first.
    return sorted(matches, key=lambda provider: credential_type not in providers[provider])


def search_operations(operations, query):
    """Rank natural-language queries without requiring an exact phrase match."""
    words = set(re.findall(r"[a-z0-9]+", query.casefold())) - {
        "a", "an", "the", "my", "me", "to", "of", "for", "with", "using", "and", "or",
        "can", "please", "i", "want", "get", "find", "show", "available", "tool", "tools",
    }
    if not words:
        return list(operations)

    def score(op):
        title = set(re.findall(r"[a-z0-9]+", f"{op['node_type']} {op['operation']} {op['display_name']}".casefold()))
        body = set(re.findall(r"[a-z0-9]+", op.get("description", "").casefold()))
        return len(words & title) * 4 + len(words & body)

    return sorted((op for op in operations if score(op)), key=score, reverse=True)


def operation_catalog(credential_type, node_type=None):
    from nodes.agent.node_op_tools import list_node_operations

    providers = compatible_providers(credential_type)
    if node_type is not None and node_type not in providers:
        raise ValueError("This credential does not support that integration.")
    return [{"node_type": provider, **operation,
             "key": f"{provider}.{operation['operation']}"}
            for provider in ([node_type] if node_type else providers)
            for operation in list_node_operations(provider)]


@lru_cache(maxsize=1)
def _connectable_operations():
    """Public operation metadata, not executable tools or account access."""
    from nodes.agent.node_op_tools import list_node_operations
    from nodes.core.registry import is_listed

    _, providers = connection_catalog()
    return tuple({"node_type": provider, **operation, "credential_types": types}
                 for provider, types in providers.items() if is_listed(provider)
                 for operation in list_node_operations(provider))


def connection_suggestions(query):
    """Show how to connect a missing capability using the integration registry.

    Purchase credentials have their own owner-confirmation flow; never suggest
    entering a provider's managed number ID as a manual credential.
    """
    from utils.capabilities import PHONE_NUMBERS, capability

    methods, _ = connection_catalog()
    results = []
    for operation in search_operations(_connectable_operations(), query):
        connections = []
        for kind in operation["credential_types"]:
            if methods[kind]["connection_method"] == "purchase":
                if kind != "phone_number" or capability(PHONE_NUMBERS) is None:
                    continue
                tool = "request_phone_number"
            else:
                tool = "connect_credential"
            connections.append({"credential_type": kind, "name": methods[kind]["name"], "tool": tool})
        if connections:
            results.append({"node_type": operation["node_type"], "operation": operation["operation"],
                            "display_name": operation["display_name"], "connections": connections})
        if len(results) == 3:
            break
    return results


def operation_tool(credential_type, node_type, operation):
    from nodes.agent.node_op_tools import build_node_op_tools

    operations = operation_catalog(credential_type, node_type)
    if operation not in {op["operation"] for op in operations}:
        raise ValueError("Unknown operation. Discover this credential's operations first.")
    tools, configs = build_node_op_tools(node_type, [operation], node_id="credential", slug="credential")
    # Return the existing schema including dynamic-option hints and the lookup
    # descriptor; callers never accept arbitrary loader names from the model.
    return tools, configs
