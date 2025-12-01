"""
Workflow nodes package.

Contains concrete node implementations and re-exports core infrastructure
from nodes.core for backward compatibility.

Structure:
- nodes/core/  - Foundational infrastructure (base classes, registries, strategies)
- nodes/*.py   - Node implementations (agent, iteration, telegram, etc.)
"""

# Re-export core infrastructure for backward compatibility
from nodes.core import (
    WorkflowNode,
    NodeConfig,
    NodeFactory,
    NODE_REGISTRY,
    ExecutionStrategy,
    ExecutionContext,
    ExecutionResult,
    StrategyRegistry,
)

# Node implementations
from nodes.telegram_node import TelegramNode
from nodes.agent_node import AgentNode

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
