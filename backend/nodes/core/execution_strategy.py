"""
Execution Strategy Protocol for workflow node orchestration.

Provides a pluggable architecture for nodes that need custom execution behavior,
such as iteration nodes, conditional nodes, or sub-workflow nodes. Strategies
allow node-specific orchestration logic to live with the node code rather than
in the central workflow handler.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, Set, Callable, Awaitable, Optional, Protocol, List


def check_output_error(output: Any) -> Optional[str]:
    """Error indicator carried IN a node's output (vs a raised exception).

    The ONE definition both execution paths share: the main-loop node runner
    (WorkflowExecutionHandler._check_output_for_error delegates here) and the
    strategies that bypass it. Without this shared check, credit-gate or provider
    failures returned as ``{status:'failed'}`` can be marked completed and parsed
    downstream as ordinary data, masking the root cause.

    Returns the error message when the output indicates failure, else None.
    """
    if not isinstance(output, dict):
        return None

    # exit_code (serverless functions use 0=success, non-zero=failure)
    exit_code = output.get('exit_code')
    if exit_code is not None and exit_code != 0:
        return output.get('error') or output.get('stderr') or f"Exit code {exit_code}"

    status = output.get('status')
    if status == 'error':
        return output.get('error') or output.get('message') or "Node returned error status"

    # Agent nodes report LLM/harness failures as status='failed' with the
    # error text in 'response'. Scoped to type='agent': integration nodes can
    # legitimately return provider payloads carrying a top-level
    # status='failed'.
    if status == 'failed' and output.get('type') == 'agent':
        return output.get('error') or output.get('response') or "Agent run failed"

    return None


@dataclass
class ExecutionContext:
    """
    Context passed to execution strategies containing all necessary
    information and callbacks for orchestrating node execution.
    """
    # Node identification
    node_id: str
    node: Dict[str, Any]
    workflow_id: str

    # Graph information
    node_outputs: Dict[str, Any]
    node_by_id: Dict[str, Dict[str, Any]]
    successors: Dict[str, Set[str]]
    predecessors: Dict[str, Set[str]]
    edges: List[Dict[str, Any]]
    """List of edges with source, target, sourceHandle, targetHandle fields."""

    # Session context
    sid: str
    user_id: str

    # Concurrency control
    semaphore: asyncio.Semaphore

    # Callbacks for the strategy to use
    execute_node: Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]]
    """Execute a single node with given outputs context. Returns node output."""

    emit_state: Callable[[str, str, str, Optional[str]], Awaitable[None]]
    """Emit node state: (node_id, node_type, state, error)"""

    emit_output: Callable[[str, str, Any], Awaitable[None]]
    """Emit node output: (node_id, node_type, output)"""

    # State management callbacks
    mark_completed: Callable[[str, Any], Awaitable[None]]
    """Mark a node as completed with output: (node_id, output)"""

    mark_failed: Callable[[str, str], Awaitable[None]]
    """Mark a node as failed: (node_id, error_message)"""

    mark_skipped: Callable[[str], Awaitable[None]]
    """Mark a node as skipped (e.g., inactive conditional branch): (node_id)"""

    signal_done: Callable[[str], None]
    """Signal that a node is done (sets its event): (node_id)"""

    # Optional context (fields with defaults must come after non-default fields)
    organization_id: Optional[str] = None
    execution_id: Optional[str] = None


@dataclass
class ExecutionResult:
    """Result from a strategy execution."""
    output: Any
    body_nodes_handled: Set[str] = field(default_factory=set)
    """Node IDs that the strategy executed (should be skipped by main loop)."""
    success: bool = True
    error: Optional[str] = None


class ExecutionStrategy(Protocol):
    """
    Protocol for custom node execution strategies.

    Implement this protocol to define custom orchestration behavior for
    specific node types (e.g., iteration, conditional, sub-workflow).
    """

    def handles(self, node_type: str) -> bool:
        """
        Return True if this strategy handles the given node type.

        Args:
            node_type: The type string of the node (e.g., 'iteration')

        Returns:
            True if this strategy should handle execution of this node type
        """
        ...

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """
        Execute the node with custom orchestration behavior.

        This method is called instead of the default node execution when
        the strategy indicates it handles the node type. The strategy has
        full control over how the node and any related nodes are executed.

        Args:
            ctx: ExecutionContext containing node info, graph data, and callbacks

        Returns:
            ExecutionResult with output, handled nodes, and success status
        """
        ...
