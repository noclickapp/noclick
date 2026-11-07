"""
Workflow nodes package.

Contains concrete node implementations and re-exports core infrastructure
from nodes.core for backward compatibility.

Structure:
- nodes/core/  - Foundational infrastructure (base classes, registries, strategies)
- nodes/*.py   - Node implementations (agent, iteration, telegram, etc.)
"""

import importlib
from typing import Any

# Re-exported for backward compatibility, and imported on first use: importing
# the package used to import every node module (the registry imports them all),
# so any submodule, a stdlib-only one or a test helper, cost ~20 s to import.
_EXPORTS = {
    'WorkflowNode': 'nodes.core',
    'NodeConfig': 'nodes.core',
    'NodeFactory': 'nodes.core',
    'NODE_REGISTRY': 'nodes.core',
    'ExecutionStrategy': 'nodes.core',
    'ExecutionContext': 'nodes.core',
    'ExecutionResult': 'nodes.core',
    'StrategyRegistry': 'nodes.core',
    'TelegramNode': 'nodes.telegram_node',
    'AgentNode': 'nodes.agent_node',
}


# Declared so `from nodes import X` reads as defined to static tools (the
# open-edition exporter's test pruning among them); bound by __getattr__.
WorkflowNode: Any
NodeConfig: Any
NodeFactory: Any
NODE_REGISTRY: Any
ExecutionStrategy: Any
ExecutionContext: Any
ExecutionResult: Any
StrategyRegistry: Any
TelegramNode: Any
AgentNode: Any


def __getattr__(name):
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module 'nodes' has no attribute {name!r}")


__all__ = [
    # Core infrastructure
    'WorkflowNode',
    'NodeConfig',
    'NodeFactory',
    'NODE_REGISTRY',
    'ExecutionStrategy',
    'ExecutionContext',
    'ExecutionResult',
    'StrategyRegistry',
    # Node implementations
    'TelegramNode',
    'AgentNode',
]
