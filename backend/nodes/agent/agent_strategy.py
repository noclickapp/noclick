"""Execution strategy for the AI agent node.

When the node DELIVERS a turn to an asynchronous runtime — signalled by an output
``status`` of ``awaiting_agent_turn`` — the response and downstream don't run in
THIS execution; they arrive later as a FRESH run fired by the turn-completion
callback (the decoupled "out" half). So on delivery we skip this run's downstream
and let the execution COMPLETE normally. Deliberately NOT a suspend: an execution
left ``awaiting_*`` could be stranded forever by a lost callback (a runtime crash) —
completing it means a lost turn just leaves no reply (the user resends), never a
perpetually-suspended run.

Any other output — a synchronous in-process SDK run, a one-shot harness, or a
turn-completion re-entry (the injected real output) — flows downstream as usual.
So the SAME node is async (deliver→complete, downstream via the callback) or
synchronous purely by what its ``execute()`` returns; no separate node type, no
per-harness branching in the engine.
"""
import logging
from typing import Dict, Set

from nodes.core.execution_strategy import (
    ExecutionContext,
    ExecutionResult,
    check_output_error,
)

logger = logging.getLogger(__name__)

# Node-output marker (NOT an execution status) the dispatch sets when it delivers a
# turn to an asynchronous runtime instead of producing a synchronous response.
AWAITING_AGENT_TURN = "awaiting_agent_turn"


class AgentExecutionStrategy:
    def handles(self, node_type: str) -> bool:
        return node_type == "agent"

    @staticmethod
    def _all_downstream(node_id: str, successors: Dict[str, Set[str]]) -> Set[str]:
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

                # A mocked output must NOT take the deliver path — there's no real
                # turn behind it, so its downstream must run normally here.
                delivered = (
                    not is_mocked
                    and isinstance(output, dict)
                    and output.get("status") == AWAITING_AGENT_TURN
                )
                if not delivered:
                    # Synchronous result — engine runs downstream normally.
                    return ExecutionResult(output=output, body_nodes_handled=set(), success=True)

                # Delivered to the runtime: skip THIS run's downstream (the response +
                # downstream come as a fresh run via run_agent_turn_downstream). The
                # execution then completes normally — no perpetual suspended state.
                all_downstream = self._all_downstream(node_id, ctx.successors)
                for downstream_id in all_downstream:
                    downstream_node = ctx.node_by_id.get(downstream_id)
                    if downstream_node:
                        await ctx.mark_skipped(downstream_id)
                        await ctx.emit_state(downstream_id, downstream_node.get("type", "unknown"), "skipped", None)
                        ctx.signal_done(downstream_id)

                logger.info(
                    "[AgentExecutionStrategy] node %s delivered turn — run completes, %d downstream skipped",
                    node_id, len(all_downstream),
                )
                return ExecutionResult(output=output, body_nodes_handled=all_downstream, success=True)

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
