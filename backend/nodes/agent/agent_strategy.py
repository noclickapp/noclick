"""Execution strategy for the AI agent node.

Agent turns complete in the current execution. Successful output flows to
downstream nodes, while a failure reported in the output follows the same error
path as a raised exception.
"""
import logging

from nodes.core.execution_strategy import (
    ExecutionContext,
    ExecutionResult,
    check_output_error,
)

logger = logging.getLogger(__name__)


class AgentExecutionStrategy:
    def handles(self, node_type: str) -> bool:
        return node_type == "agent"

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        node_id = ctx.node_id
        node = ctx.node
        node_type = node.get("type", "agent")
        try:
            async with ctx.semaphore:
                await ctx.emit_state(node_id, node_type, "running", None)

                mocked = node.get("config", {}).get("mockedOutput")
                is_mocked = isinstance(mocked, dict)
                if is_mocked:
                    output = mocked
                else:
                    output = await ctx.execute_node(node, ctx.node_outputs)
                    # Failures the node reports IN its output (credit gate,
                    # provider errors → status='failed') must halt downstream
                    # exactly like a raised exception — the main loop runs
                    # this check but agents stopped using that path when this
                    # strategy landed, so error strings could leak downstream as
                    # data. Mocked outputs
                    # are exempt: user-authored test data, not a live failure.
                    output_error = check_output_error(output)
                    if output_error:
                        error_msg = f"Node {node_id} failed: {output_error}"
                        logger.error("[AgentExecutionStrategy] %s", error_msg)
                        await ctx.mark_failed(node_id, error_msg)
                        # Emit the payload so the node panel shows the real
                        # error, then the terminal error state.
                        await ctx.emit_output(node_id, node_type, output)
                        await ctx.emit_state(node_id, node_type, "error", output_error)
                        return ExecutionResult(
                            output=output, body_nodes_handled=set(),
                            success=False, error=error_msg,
                        )

                await ctx.mark_completed(node_id, output)
                await ctx.emit_output(node_id, node_type, output)
                await ctx.emit_state(node_id, node_type, "completed", None)
                return ExecutionResult(
                    output=output, body_nodes_handled=set(), success=True
                )

        except Exception as e:
            error_msg = f"agent node {node_id} failed: {e}"
            logger.error("[AgentExecutionStrategy] %s", error_msg)
            await ctx.mark_failed(node_id, error_msg)
            await ctx.emit_state(node_id, node_type, "error", str(e))
            # body_nodes_handled MUST be empty on failure: the node is in
            # state.failed, so successors cascade-skip normally (which sets
            # their node_done). Returning the successors instead parks them in
            # nodes_in_iteration with node_done never set — anything ≥2 hops
            # downstream then waits forever and the run is never finalized.
            return ExecutionResult(
                output=None, body_nodes_handled=set(),
                success=False, error=error_msg,
            )
        finally:
            ctx.signal_done(node_id)
