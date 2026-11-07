"""
Core workflow node infrastructure.

Contains foundational classes and registries for the workflow node system:
- WorkflowNode: Abstract base class for all nodes
- NodeConfig: Generic config container with Pydantic validation
- NodeFactory: Factory for creating node instances by type
- ExecutionStrategy: Protocol for custom node execution behavior
- StrategyRegistry: Registry for execution strategies
"""

import importlib
from typing import Any

# Imported on first use: the registry imports every node module, and each of
# them imports nodes.core.base, so an eager import here made any node module
# imported first import itself again half-built through the registry.
_EXPORTS = {
    'WorkflowNode': 'nodes.core.base',
    'NodeConfig': 'nodes.core.base',
    'NodeFactory': 'nodes.core.registry',
    'NODE_REGISTRY': 'nodes.core.registry',
    'ExecutionStrategy': 'nodes.core.execution_strategy',
    'ExecutionContext': 'nodes.core.execution_strategy',
    'ExecutionResult': 'nodes.core.execution_strategy',
    'StrategyRegistry': 'nodes.core.strategy_registry',
}


# Declared so `from nodes.core import X` reads as defined to static tools (the
# open-edition exporter's test pruning among them); bound by __getattr__.
WorkflowNode: Any
NodeConfig: Any
NodeFactory: Any
NODE_REGISTRY: Any
ExecutionStrategy: Any
ExecutionContext: Any
ExecutionResult: Any
StrategyRegistry: Any


def __getattr__(name):
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module 'nodes.core' has no attribute {name!r}")


__all__ = [
    'WorkflowNode',
    'NodeConfig',
    'NodeFactory',
    'NODE_REGISTRY',
    'ExecutionStrategy',
    'ExecutionContext',
    'ExecutionResult',
    'StrategyRegistry',
]
