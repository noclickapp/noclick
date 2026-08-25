"""
Switch node for multi-way workflow branching.

Routes execution to different output handles based on matching a field value
against a list of cases. Each case maps a value to a named output handle.
Supports a default output for unmatched values.
"""

import logging
from typing import Dict, Any, Optional, Type, List, Set
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.execution_strategy import ExecutionStrategy, ExecutionContext, ExecutionResult

logger = logging.getLogger(__name__)


# ============================================================================
# Switch Node Configuration
# ============================================================================

class SwitchCase(BaseModel):
    """A single case for the switch node. The value doubles as the output handle name."""
    value: str = Field(
        ...,
        title="Match Value",
        description="Value to match against (also used as the output handle name)"
    )


class SwitchInnerConfig(BaseModel):
    """Configuration for the switch node."""

    input_data: Any = Field(
        ...,
        title="Input Data",
        description="Reference to the data to evaluate (e.g., {{trigger.data}})",
        json_schema_extra={
            "placeholder": "{{node-id.field}}",
            "ui:widget": "textarea"
        }
    )

    switch_cases: Optional[List[SwitchCase]] = Field(
        default=None,
        title="Cases",
        description="List of value-to-output mappings",
        json_schema_extra={
            "ui:widget": "switch_cases"
        }
    )

    default_output: Optional[str] = Field(
        default=None,
        title="Default Output",
        description="Case to route to when no cases match",
        json_schema_extra={
            "ui:widget": "switch_default_output"
        }
    )

    case_sensitive: str = Field(
        default="false",
        title="Case Sensitive",
        description="Whether value matching should be case sensitive",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        }
    )


class SwitchNodeConfig(NodeConfig[SwitchInnerConfig, None]):
    """Full configuration for switch node (no credentials needed)."""
    pass


# ============================================================================
# Switch Node Implementation
# ============================================================================

class SwitchNode(WorkflowNode):
    """
    Switch workflow node for multi-way branching.

    Evaluates a field value against a list of cases and routes execution
    to the matching output handle. If no case matches, routes to the
    default output handle.
    """

    IS_CONDITIONAL_NODE = True

    edit_examples = [
        "Add a new case matching status=completed to route approved flow",
        "Change input data to reference {{http.response_status}} instead",
        "Enable case-sensitive matching for exact value comparison",
        "Set default output to handle case and remove case validation",
        "Add more cases for different environment types (prod/staging/dev)",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return SwitchNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the switch node.

        Evaluates the switch field against cases and returns which
        output handle to route to.
        """
        logger.info(f"[SwitchNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, SwitchNodeConfig):
            raise ValueError(f"[SwitchNode] Configuration required for node {self.node_id}")

        config = node_config.config

        # Get input data
        input_data = config.input_data
        if isinstance(input_data, str):
            if input_data.startswith('{{') and input_data.endswith('}}'):
                raise ValueError(
                    f"[SwitchNode] Input data reference '{input_data}' was not resolved. "
                    "Make sure the upstream node has executed and the path is correct."
                )
            import json
            try:
                input_data = json.loads(input_data)
            except json.JSONDecodeError:
                pass

        field_value = input_data

        cases = config.switch_cases or []
        case_sensitive = config.case_sensitive == "true"

        # Find matching case
        output_handle = config.default_output or "default"
        matched_case = None

        field_str = str(field_value) if case_sensitive else str(field_value).lower()

        for case in cases:
            case_value = case.value if case_sensitive else case.value.lower()
            if field_str == case_value:
                output_handle = case.value
                matched_case = case.value
                break

        output = {
            'status': 'success',
            'operation': 'switch',
            'output_handle': output_handle,
            'matched_case': matched_case,
            'data': input_data,
            'isConditionalNode': True,
            'switch_value': field_value,
            'available_cases': [c.value for c in cases],
        }

        logger.info(f"[SwitchNode] Switch matched '{matched_case}', routing to '{output_handle}'")

        await self.emit(output)
        return output


# ============================================================================
# Switch Execution Strategy
# ============================================================================

class SwitchExecutionStrategy:
    """
    Execution strategy for switch nodes.

    Routes workflow execution to the appropriate branch based on
    the switch evaluation result. Reuses the same branching logic
    as the conditional execution strategy.
    """

    def handles(self, node_type: str) -> bool:
        return node_type == 'switch'

    def _get_successors_by_handle(
        self,
        node_id: str,
        edges: List[Dict[str, Any]],
        all_successors: Set[str]
    ) -> Dict[str, Set[str]]:
        """Categorize successors based on the sourceHandle of the connecting edge."""
        handle_successors: Dict[str, Set[str]] = {}

        for edge in edges:
            if edge.get('source') != node_id:
                continue
            target = edge.get('target')
            if target not in all_successors:
                continue

            source_handle = edge.get('sourceHandle') or 'default'
            if source_handle not in handle_successors:
                handle_successors[source_handle] = set()
            handle_successors[source_handle].add(target)

        return handle_successors

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """Execute a switch node and route to the appropriate branch.

        Only executes the switch node itself and marks inactive branch successors
        as skipped. Active branch successors are left for the main execution loop,
        which correctly handles nested strategies (e.g., switch inside conditional).
        """
        node_id = ctx.node_id
        node = ctx.node
        node_type = 'switch'

        try:
            async with ctx.semaphore:
                await ctx.emit_state(node_id, node_type, 'running', None)

                # Check for mocked output
                mocked_output = node.get('config', {}).get('mockedOutput')
                if mocked_output is not None and isinstance(mocked_output, dict):
                    logger.info(f"[SwitchStrategy] Using mocked output for node {node_id}")
                    switch_output = mocked_output
                else:
                    switch_output = await ctx.execute_node(node, ctx.node_outputs)

                output_handle = switch_output.get('output_handle', 'default')

                logger.info(f"[SwitchStrategy] Node {node_id} routing to handle '{output_handle}'")

                # Mark switch node as completed and emit output
                await ctx.mark_completed(node_id, switch_output)
                await ctx.emit_output(node_id, node_type, switch_output)
                await ctx.emit_state(node_id, node_type, 'completed', None)

                # Get all successors categorized by handle
                all_successors = ctx.successors.get(node_id, set())
                handle_successors = self._get_successors_by_handle(node_id, ctx.edges, all_successors)

                # Mark nodes on inactive branches as skipped so cascade-skip
                # propagates to their downstream nodes via the main loop
                skipped_nodes: Set[str] = set()
                for handle, successors in handle_successors.items():
                    if handle == output_handle:
                        continue
                    for skipped_id in successors:
                        skipped_node = ctx.node_by_id.get(skipped_id)
                        if skipped_node:
                            skipped_type = skipped_node.get('type', 'unknown')
                            await ctx.mark_skipped(skipped_id)
                            await ctx.emit_state(skipped_id, skipped_type, 'skipped', None)
                            ctx.signal_done(skipped_id)
                            skipped_nodes.add(skipped_id)
                            logger.info(f"[SwitchStrategy] Skipped node {skipped_id} (not on active branch)")

                logger.info(f"[SwitchStrategy] Node {node_id} completed, routed to '{output_handle}'")

                # Only return skipped nodes as handled — active branch successors
                # are executed by the main loop (supports nested strategies)
                return ExecutionResult(
                    output=switch_output,
                    body_nodes_handled=skipped_nodes,
                    success=True
                )

        except Exception as e:
            error_msg = f"Switch node {node_id} failed: {str(e)}"
            logger.error(f"[SwitchStrategy] {error_msg}")

            await ctx.mark_failed(node_id, error_msg)
            await ctx.emit_state(node_id, node_type, 'error', str(e))

            return ExecutionResult(
                output=None,
                body_nodes_handled=ctx.successors.get(node_id, set()),
                success=False,
                error=error_msg
            )

        finally:
            ctx.signal_done(node_id)
