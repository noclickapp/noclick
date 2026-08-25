"""
Generic suspend execution strategy for workflow nodes.

A SuspendingExecutionStrategy pauses a workflow run at a node: it executes
the node, marks every downstream node skipped so the run loop ends naturally,
and sets the execution status to a suspended status. Resumption happens later
through a separate path (a human decision for the approval node, a timer for
the delay node) which restores the persisted node outputs and runs the
downstream subgraph.

Concrete strategies (ApprovalExecutionStrategy, DelayExecutionStrategy) just
declare which node type they handle and which suspended status to set.
"""

import logging
from typing import Dict, Set

from nodes.core.execution_strategy import ExecutionContext, ExecutionResult

logger = logging.getLogger(__name__)


# Execution statuses that mean a run is paused and waiting to be resumed.
# Outputs of executions in these statuses must not be pruned, and the
# workflow-completion path treats reaching one of them as a graceful stop.
SUSPENDED_STATUSES = frozenset({"awaiting_approval", "awaiting_delay"})


class SuspendingExecutionStrategy:
    """
    Base strategy for nodes that suspend workflow execution.

    1. Executes the node to get its output.
    2. Marks ALL downstream nodes as skipped so execution stops.
    3. Sets the execution status to ``suspended_status``.

    The node's own ``execute()`` is responsible for any node-specific side
    effects (persisting an approval request, scheduling a resume timer, etc.).
    """

    # Subclasses set this to the workflow_executions.status value to write.
    suspended_status: str = ""

    def handles(self, node_type: str) -> bool:
        raise NotImplementedError

    def _get_all_downstream(
        self,
        node_id: str,
        successors: Dict[str, Set[str]],
    ) -> Set[str]:
        """BFS to find all nodes downstream of node_id."""
        visited: Set[str] = set()
        queue = list(successors.get(node_id, set()))
        while queue:
            nid = queue.pop()
            if nid in visited:
                continue
            visited.add(nid)
            queue.extend(successors.get(nid, set()))
        return visited

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        node_id = ctx.node_id
        node = ctx.node
        node_type = node.get("type", "unknown")
        log_prefix = f"[{self.__class__.__name__}]"

        try:
            async with ctx.semaphore:
                await ctx.emit_state(node_id, node_type, "running", None)

                # Handle mocked output (for testing)
                mocked_output = node.get("config", {}).get("mockedOutput")
                if mocked_output is not None and isinstance(mocked_output, dict):
                    logger.info(f"{log_prefix} Using mocked output for node {node_id}")
                    suspend_output = mocked_output
                else:
                    suspend_output = await ctx.execute_node(node, ctx.node_outputs)

                # Mark the suspending node itself as completed
                await ctx.mark_completed(node_id, suspend_output)
                await ctx.emit_output(node_id, node_type, suspend_output)
                await ctx.emit_state(node_id, node_type, "completed", None)

                # Skip ALL downstream nodes so execution stops
                all_downstream = self._get_all_downstream(node_id, ctx.successors)
                for downstream_id in all_downstream:
                    downstream_node = ctx.node_by_id.get(downstream_id)
                    if downstream_node:
                        downstream_type = downstream_node.get("type", "unknown")
                        await ctx.mark_skipped(downstream_id)
                        await ctx.emit_state(downstream_id, downstream_type, "skipped", None)
                        ctx.signal_done(downstream_id)

                # Update execution status to the suspended status
                if ctx.execution_id:
                    try:
                        from utils.database_pool import get_native_pool
                        await get_native_pool().execute("""
                            UPDATE workflow_executions
                            SET status = $1, finished_at = NOW(),
                                nodes_executed = $2
                            WHERE id = $3
                        """, self.suspended_status, len(ctx.node_outputs), ctx.execution_id)
                    except Exception as e:
                        logger.error(f"{log_prefix} Failed to update execution status: {e}")

                logger.info(
                    f"{log_prefix} Node {node_id} suspended execution "
                    f"({self.suspended_status}), skipped {len(all_downstream)} downstream nodes"
                )

                return ExecutionResult(
                    output=suspend_output,
                    body_nodes_handled=all_downstream,
                    success=True,
                )

        except Exception as e:
            error_msg = f"{node_type} node {node_id} failed: {str(e)}"
            logger.error(f"{log_prefix} {error_msg}")

            await ctx.mark_failed(node_id, error_msg)
            await ctx.emit_state(node_id, node_type, "error", str(e))

            return ExecutionResult(
                output=None,
                body_nodes_handled=ctx.successors.get(node_id, set()),
                success=False,
                error=error_msg,
            )

        finally:
            ctx.signal_done(node_id)
