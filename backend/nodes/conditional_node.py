"""
Conditional (If/Else) node for workflow branching.

This node enables simple true/false branching in workflows by evaluating
a condition and routing execution to the "true" or "false" output handle.

For multi-way branching (switch/case), see switch_node.py.
"""

import logging
import re
from typing import Dict, Any, Optional, Type, List, Set, Literal
from pydantic import BaseModel, Field, field_validator
from enum import Enum

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.execution_strategy import ExecutionStrategy, ExecutionContext, ExecutionResult

logger = logging.getLogger(__name__)


# ============================================================================
# Conditional Node Configuration
# ============================================================================

class ConditionalOperator(str, Enum):
    """Comparison operators for conditions."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    REGEX_MATCH = "regex_match"


class ConditionalInnerConfig(BaseModel):
    """Configuration for the conditional (if/else) node."""

    input_data: Any = Field(
        ...,
        title="Input Data",
        description="Reference to the data to evaluate (e.g., {{trigger.data}})",
        json_schema_extra={
            "placeholder": "{{node-id.field}}",
            "ui:widget": "textarea"
        }
    )

    condition_field: Optional[str] = Field(
        default=None,
        title="Field to Evaluate",
        description="Path to the field to evaluate (e.g., 'status' or 'data.user.role'). Leave empty to evaluate the entire input.",
        json_schema_extra={
            "placeholder": "field_name"
        }
    )

    condition_operator: Optional[ConditionalOperator] = Field(
        default=ConditionalOperator.EQUALS,
        title="Operator",
        description="Comparison operator for the condition",
        # `enum` is derived from ConditionalOperator so the config UI renders a
        # searchable dropdown — a bare Enum field emits only a `$ref`, which the
        # renderer can't surface as a dropdown.
        json_schema_extra={
            "enum": [op.value for op in ConditionalOperator],
            "enumNames": [
                "Equals", "Not equals", "Contains", "Does not contain",
                "Starts with", "Ends with", "Greater than",
                "Greater than or equal", "Less than", "Less than or equal",
                "Is empty", "Is not empty", "Is true", "Is false", "Regex match",
            ],
            "x-enum-searchable": True,
        },
    )

    condition_value: Optional[str] = Field(
        default=None,
        title="Comparison Value",
        description="Value to compare against (not needed for is_empty, is_true, etc.)",
        json_schema_extra={
            "placeholder": "value"
        }
    )

    case_sensitive: Literal["false", "true"] = Field(
        default="false",
        title="Case Sensitive",
        description="Whether string comparisons should be case sensitive",
        json_schema_extra={"enumNames": ["No", "Yes"]},
    )

    @field_validator("case_sensitive", mode="before")
    @classmethod
    def _coerce_case_sensitive(cls, v: Any) -> Any:
        """Older conditional nodes stored case_sensitive as a boolean."""
        if isinstance(v, bool):
            return "true" if v else "false"
        return v


class ConditionalNodeConfig(NodeConfig[ConditionalInnerConfig, None]):
    """Full configuration for conditional node (no credentials needed)."""
    pass


# ============================================================================
# Conditional Node Implementation
# ============================================================================

class ConditionalNode(WorkflowNode):
    """
    Conditional workflow node for if/else branching.

    Evaluates a condition and routes execution to the "true" or "false"
    output handle. The actual routing logic is handled by the
    ConditionalExecutionStrategy.
    """

    IS_CONDITIONAL_NODE = True

    edit_examples = [
        "Route by user tier (send pro users to premium path)",
        "Check if email is empty before sending",
        "Only process if the status is not failed",
        "Route based on a number exceeding a threshold",
        "Branch if response contains a specific keyword",
        "Check if a field matches a regex pattern",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return ConditionalNodeConfig

    def _get_nested_value(self, data: Any, path: str) -> Any:
        """Get a nested value from data using dot notation with array index support (e.g. 'emails[0].reply_text')."""
        if not path:
            return data

        import re
        parts = path.split('.')
        current = data

        for part in parts:
            # Parse array indices: "emails[0]" -> key="emails", indices=[0]
            key_match = re.match(r'^([^\[]*)((?:\[\d+\])*)$', part)
            if key_match:
                key = key_match.group(1)
                indices_str = key_match.group(2)
            else:
                key = part
                indices_str = ''

            # Navigate to the key first (if non-empty)
            if key:
                if isinstance(current, dict):
                    current = current.get(key)
                elif hasattr(current, key):
                    current = getattr(current, key)
                else:
                    return None
                if current is None:
                    return None

            # Apply array indices
            if indices_str:
                for idx_str in re.findall(r'\[(\d+)\]', indices_str):
                    idx = int(idx_str)
                    if isinstance(current, (list, tuple)) and idx < len(current):
                        current = current[idx]
                    else:
                        return None
                    if current is None:
                        return None

        return current

    def _parse_value(self, value_str: str) -> Any:
        """Parse a string value to its appropriate type."""
        if not value_str:
            return value_str

        if value_str.lower() == 'true':
            return True
        if value_str.lower() == 'false':
            return False

        try:
            if '.' in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            pass

        return value_str

    def _evaluate_condition(
        self,
        field_value: Any,
        operator: ConditionalOperator,
        compare_value: Any,
        case_sensitive: bool
    ) -> bool:
        """Evaluate a condition."""
        if operator == ConditionalOperator.IS_EMPTY:
            return field_value is None or field_value == "" or \
                   (isinstance(field_value, (list, dict)) and len(field_value) == 0)

        if operator == ConditionalOperator.IS_NOT_EMPTY:
            return not (field_value is None or field_value == "" or \
                       (isinstance(field_value, (list, dict)) and len(field_value) == 0))

        if operator == ConditionalOperator.IS_TRUE:
            return bool(field_value) is True

        if operator == ConditionalOperator.IS_FALSE:
            return bool(field_value) is False

        if operator in (ConditionalOperator.CONTAINS, ConditionalOperator.NOT_CONTAINS,
                       ConditionalOperator.STARTS_WITH, ConditionalOperator.ENDS_WITH):
            field_str = str(field_value) if field_value is not None else ""
            compare_str = str(compare_value) if compare_value is not None else ""

            if not case_sensitive:
                field_str = field_str.lower()
                compare_str = compare_str.lower()

            if operator == ConditionalOperator.CONTAINS:
                return compare_str in field_str
            elif operator == ConditionalOperator.NOT_CONTAINS:
                return compare_str not in field_str
            elif operator == ConditionalOperator.STARTS_WITH:
                return field_str.startswith(compare_str)
            elif operator == ConditionalOperator.ENDS_WITH:
                return field_str.endswith(compare_str)

        if operator == ConditionalOperator.REGEX_MATCH:
            try:
                pattern = str(compare_value)
                flags = 0 if case_sensitive else re.IGNORECASE
                return bool(re.search(pattern, str(field_value), flags))
            except re.error:
                logger.error(f"Invalid regex pattern: {compare_value}")
                return False

        if operator == ConditionalOperator.EQUALS:
            if not case_sensitive and isinstance(field_value, str) and isinstance(compare_value, str):
                return field_value.lower() == compare_value.lower()
            return field_value == compare_value

        if operator == ConditionalOperator.NOT_EQUALS:
            if not case_sensitive and isinstance(field_value, str) and isinstance(compare_value, str):
                return field_value.lower() != compare_value.lower()
            return field_value != compare_value

        try:
            field_num = float(field_value) if field_value is not None else 0
            compare_num = float(compare_value) if compare_value is not None else 0

            if operator == ConditionalOperator.GREATER_THAN:
                return field_num > compare_num
            elif operator == ConditionalOperator.GREATER_THAN_OR_EQUAL:
                return field_num >= compare_num
            elif operator == ConditionalOperator.LESS_THAN:
                return field_num < compare_num
            elif operator == ConditionalOperator.LESS_THAN_OR_EQUAL:
                return field_num <= compare_num
        except (ValueError, TypeError):
            return False

        return False

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the conditional node (if/else evaluation)."""
        logger.info(f"[ConditionalNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, ConditionalNodeConfig):
            raise ValueError(f"[ConditionalNode] Configuration required for node {self.node_id}")

        config = node_config.config

        # Get input data
        input_data = config.input_data
        if isinstance(input_data, str):
            if input_data.startswith('{{') and input_data.endswith('}}'):
                raise ValueError(
                    f"[ConditionalNode] Input data reference '{input_data}' was not resolved. "
                    "Make sure the upstream node has executed and the path is correct."
                )
            import json
            try:
                input_data = json.loads(input_data)
            except json.JSONDecodeError:
                pass

        field_value = self._get_nested_value(input_data, config.condition_field) \
            if config.condition_field else input_data

        compare_value = self._parse_value(config.condition_value) if config.condition_value else None

        result = self._evaluate_condition(
            field_value,
            config.condition_operator,
            compare_value,
            config.case_sensitive == "true"
        )

        output_handle = "true" if result else "false"

        output = {
            'status': 'success',
            'operation': 'if_else',
            'condition_result': result,
            'output_handle': output_handle,
            'data': input_data,
            'isConditionalNode': True,
            'evaluated_field': config.condition_field,
            'evaluated_value': field_value,
        }

        logger.info(f"[ConditionalNode] If/Else evaluated to {result}, routing to '{output_handle}'")

        await self.emit(output)
        return output


# ============================================================================
# Conditional Execution Strategy
# ============================================================================

class ConditionalExecutionStrategy:
    """
    Execution strategy for conditional (if/else) nodes.

    Handles routing workflow execution to the appropriate branch based on
    the condition evaluation result.
    """

    def handles(self, node_type: str) -> bool:
        return node_type == 'conditional'

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
        """Execute a conditional node and route to the appropriate branch.

        Only executes the conditional node itself and marks inactive branch
        successors as skipped. Active branch successors are left for the main
        execution loop, which correctly handles nested strategies (e.g., a switch
        node on the active branch).
        """
        node_id = ctx.node_id
        node = ctx.node
        node_type = 'conditional'

        try:
            async with ctx.semaphore:
                await ctx.emit_state(node_id, node_type, 'running', None)

                mocked_output = node.get('config', {}).get('mockedOutput')
                if mocked_output is not None and isinstance(mocked_output, dict):
                    logger.info(f"[ConditionalStrategy] Using mocked output for node {node_id}")
                    conditional_output = mocked_output
                else:
                    conditional_output = await ctx.execute_node(node, ctx.node_outputs)

                output_handle = conditional_output.get('output_handle', 'default')

                logger.info(f"[ConditionalStrategy] Node {node_id} routing to handle '{output_handle}'")

                # Mark conditional node as completed and emit output
                await ctx.mark_completed(node_id, conditional_output)
                await ctx.emit_output(node_id, node_type, conditional_output)
                await ctx.emit_state(node_id, node_type, 'completed', None)

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
                            logger.info(f"[ConditionalStrategy] Skipped node {skipped_id} (not on active branch)")

                logger.info(f"[ConditionalStrategy] Node {node_id} completed, routed to '{output_handle}'")

                # Only return skipped nodes as handled — active branch successors
                # are executed by the main loop (supports nested strategies)
                return ExecutionResult(
                    output=conditional_output,
                    body_nodes_handled=skipped_nodes,
                    success=True
                )

        except Exception as e:
            error_msg = f"Conditional node {node_id} failed: {str(e)}"
            logger.error(f"[ConditionalStrategy] {error_msg}")

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
