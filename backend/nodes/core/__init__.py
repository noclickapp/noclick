"""
Core workflow node infrastructure.

Contains foundational classes and registries for the workflow node system:
- WorkflowNode: Abstract base class for all nodes
- NodeConfig: Generic config container with Pydantic validation
- NodeFactory: Factory for creating node instances by type
- ExecutionStrategy: Protocol for custom node execution behavior
- StrategyRegistry: Registry for execution strategies
"""

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.execution_strategy import ExecutionStrategy, ExecutionContext, ExecutionResult
from nodes.core.strategy_registry import StrategyRegistry

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
