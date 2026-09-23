"""Discover a connection's tools from the existing integration registry.

The coordinator and credential permissions UI share this catalog with agent
node tools: there is no second set of provider operations or argument schemas.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def connection_catalog():
    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.credential_connect import credential_classes_for_node, credential_type_of
    from nodes.agent.node_op_tools import node_supports_op_tools

    methods = {}
    providers = {}
    for node_type, cls in NODE_REGISTRY.items():
        supported = node_supports_op_tools(node_type)
        types = []
        for credential_cls in credential_classes_for_node(cls):
            kind = credential_type_of(credential_cls)
            if not kind:
                continue
            schema = credential_cls.model_json_schema()
            if schema.get("x-credential-hidden"):
                continue
            methods.setdefault(kind, {
                "credential_type": kind,
                "name": schema.get("title", kind),
                "oauth_provider": schema.get("x-oauth-provider"),
            })
            types.append(kind)
        if supported and types:
            providers[node_type] = tuple(types)
    return methods, providers


def compatible_providers(credential_type):
    methods, providers = connection_catalog()
    oauth = methods.get(credential_type, {}).get("oauth_provider")
    return [node_type for node_type, types in providers.items() if any(
        t == credential_type or (oauth and methods[t].get("oauth_provider") == oauth)
        for t in types
    )]


def operation_catalog(credential_type, node_type=None):
    from nodes.agent.node_op_tools import list_node_operations

    providers = compatible_providers(credential_type)
    if node_type is not None and node_type not in providers:
        raise ValueError("This credential does not support that integration.")
    return [{"node_type": provider, **operation,
             "key": f"{provider}.{operation['operation']}"}
            for provider in ([node_type] if node_type else providers)
            for operation in list_node_operations(provider)]


def operation_tool(credential_type, node_type, operation):
    from nodes.agent.node_op_tools import build_node_op_tools

    operations = operation_catalog(credential_type, node_type)
    if operation not in {op["operation"] for op in operations}:
        raise ValueError("Unknown operation. Discover this credential's operations first.")
    tools, configs = build_node_op_tools(node_type, [operation], node_id="credential", slug="credential")
    # Return the existing schema including dynamic-option hints and the lookup
    # descriptor; callers never accept arbitrary loader names from the model.
    return tools, configs
