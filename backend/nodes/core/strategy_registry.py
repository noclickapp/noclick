"""
Registry for execution strategies.

Provides a centralized place to register and lookup execution strategies
for different node types. Strategies are registered at module load time
and looked up during workflow execution.
"""

import logging
from typing import List, Optional

from nodes.core.execution_strategy import ExecutionStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """
    Registry for execution strategies.

    Strategies are registered in order of priority (first registered = first checked).
    When looking up a strategy for a node type, the registry returns the first
    strategy that handles that type.
    """
    _strategies: List[ExecutionStrategy] = []
    _initialized: bool = False

    @classmethod
    def register(cls, strategy: ExecutionStrategy) -> None:
        """
        Register an execution strategy.

        Args:
            strategy: The strategy instance to register
        """
        cls._strategies.append(strategy)
        logger.debug(f"[StrategyRegistry] Registered strategy: {strategy.__class__.__name__}")

    @classmethod
    def get_strategy(cls, node_type: str) -> Optional[ExecutionStrategy]:
        """
        Get the execution strategy for a node type, if one exists.

        Args:
            node_type: The type of node to find a strategy for

        Returns:
            The strategy that handles this node type, or None if no special handling needed
        """
        # Ensure strategies are initialized
        cls._ensure_initialized()

        for strategy in cls._strategies:
            if strategy.handles(node_type):
                return strategy
        return None

    @classmethod
    def _ensure_initialized(cls) -> None:
        """
        Ensure all strategies are registered.

        This is called lazily on first lookup to avoid import order issues.
        """
        if cls._initialized:
            return

        cls._initialized = True

        # Import and register strategies here to avoid circular imports
        # Each strategy module should register itself when imported
        try:
            from nodes.iteration_node import IterationExecutionStrategy
            cls.register(IterationExecutionStrategy())
            logger.info("[StrategyRegistry] Initialized with iteration strategy")
        except ImportError as e:
            logger.warning(f"[StrategyRegistry] Failed to import iteration strategy: {e}")

        try:
            from nodes.conditional_node import ConditionalExecutionStrategy
            cls.register(ConditionalExecutionStrategy())
            logger.info("[StrategyRegistry] Initialized with conditional strategy")
        except ImportError as e:
            logger.warning(f"[StrategyRegistry] Failed to import conditional strategy: {e}")

    @classmethod
    def clear(cls) -> None:
        """Clear all registered strategies (useful for testing)."""
        cls._strategies = []
        cls._initialized = False
