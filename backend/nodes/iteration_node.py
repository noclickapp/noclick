"""
Iteration node for workflow loops.

This node enables for-loop functionality in workflows by iterating over an array
and executing downstream nodes once per item. The iteration context (current item,
index, total count) is made available to downstream nodes via references.

Key Features:
    - Iterates over arrays from upstream nodes (e.g., Google Sheets rows)
    - Supports header mode: first row becomes field names, creating named objects
    - Supports explicit field mapping for arrays without headers
    - **Implicit loop variable scoping**: Loop variables automatically available without node ID prefix
    - **Transitive loop body**: ALL nodes downstream from loop handle execute per iteration
    - Downstream nodes can reference {{item}}, {{index}}, {{items}}, {{total}}, {{row_number}}
    - Backward compatible: {{iteration-id.item.fieldName}} still works

Loop Body Propagation:
    When nodes are connected in a chain from the loop handle, ALL nodes in the chain
    execute once per iteration and have access to loop variables:

    iteration (loop) → A → B → C

    - Node A: Executes per iteration ✓
    - Node B: Executes per iteration ✓ (transitive)
    - Node C: Executes per iteration ✓ (transitive)

    This eliminates the need to connect the iteration node to every node in the chain,
    reducing edge clutter in complex workflows.

Usage Examples:
    1. Google Sheets with headers:
       - Input: [["name", "email"], ["Alice", "a@test.com"], ["Bob", "b@test.com"]]
       - Set header_row=True
       - Items become: [{name: "Alice", email: "a@test.com"}, {name: "Bob", ...}]
       - Reference: {{item.name}}, {{item.email}} (or {{iteration-id.item.name}} for explicit reference)

    2. Explicit field mapping:
       - Input: [["Alice", 25], ["Bob", 30]]
       - Set field_names=["name", "age"]
       - Items become: [{name: "Alice", age: 25}, {name: "Bob", age: 30}]

    3. Raw array iteration:
       - Input: ["item1", "item2", "item3"]
       - Items stay as-is, reference with {{item}}

    4. Implicit loop variables (available in ALL loop body nodes):
       - {{item}} - Current iteration item
       - {{index}} - Current iteration index (0-based)
       - {{items}} - Full array being iterated
       - {{total}} - Total number of items
       - {{row_number}} - Current row number (1-based, adjusted for headers)
"""

import asyncio
import logging
from collections import deque
from typing import Dict, Any, Optional, Type, List, Set, Literal
from pydantic import BaseModel, Field, field_validator

from nodes.core.base import WorkflowNode, NodeConfig, OutputHandle
from nodes.core.execution_strategy import ExecutionStrategy, ExecutionContext, ExecutionResult

logger = logging.getLogger(__name__)


# ============================================================================
# Iteration Node Configuration
# ============================================================================

class IterationInnerConfig(BaseModel):
    """Configuration for the iteration node."""
    # The field path to iterate over, can be a direct reference like {{node-id.items}}
    # or just a field name if the array comes from the direct predecessor
    # At runtime, references are resolved before Pydantic validation, so this
    # can be either a string (unresolved reference) or a list (resolved data)
    items: Any = Field(
        ...,
        title="Items",
        description="Reference to the array to iterate over (e.g., {{sheets-1.values}})",
        json_schema_extra={
            "placeholder": "{{node-id.field}}",
            "ui:widget": "textarea"
        }
    )

    # Header mode: treat first row as field names
    header_row: Literal["false", "true"] = Field(
        default="false",
        title="First Row is Header",
        description="If enabled, the first row is used as field names and each subsequent row becomes an object with named fields. Perfect for Google Sheets data.",
        json_schema_extra={"enumNames": ["No", "Yes"]},
    )

    @field_validator('header_row', mode='before')
    @classmethod
    def coerce_header_row(cls, v):
        """
        Coerce header_row to the "true"/"false" string the field expects.

        Handles legacy boolean data and loose frontend input (empty string,
        null/undefined, 1/yes) by normalising to "false" unless truthy.
        """
        if v is None or v == '' or v == 'null' or v == 'undefined':
            return "false"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return "true" if v.lower() in ('true', '1', 'yes') else "false"
        return "true" if bool(v) else "false"

    # Alternative: explicit field mapping
    field_names: Optional[str] = Field(
        default=None,
        title="Field Names",
        description="Comma-separated field names to map array values to object keys (e.g., 'name,email,message'). Use this when your data doesn't have a header row.",
        json_schema_extra={
            "placeholder": "field1,field2,field3"
        }
    )

    # Concurrency control for parallel iteration
    concurrency: int = Field(
        default=1,
        ge=1,
        le=10,
        title="Concurrency",
        description="Number of items to process in parallel (1 = sequential, up to 10 for parallel)"
    )


class IterationNodeConfig(NodeConfig[IterationInnerConfig, None]):
    """Full configuration for iteration node (no credentials needed)."""
    pass


# ============================================================================
# Iteration Node Implementation
# ============================================================================

class IterationNode(WorkflowNode):
    """
    Iteration workflow node for looping over arrays.

    This is a control flow node that executes downstream nodes once per item
    in the input array. The actual iteration logic is handled by the
    WorkflowExecutionHandler, which recognizes this node type and handles
    it specially.

    The node validates config, transforms data if needed (header row mode),
    and returns iteration metadata. The heavy lifting of re-executing
    downstream nodes happens in the handler.
    """

    # Marker to identify this as a control flow node
    IS_ITERATION_NODE = True

    edit_examples = [
        "Loop over rows from Google Sheets with headers",
        "Iterate over API response items in parallel",
        "Use header row mode for spreadsheet data",
        "Process each item 5 at a time for faster execution",
        "Define custom field names for array data",
        "Run the same workflow step for every email address",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        """Get Pydantic config model for iteration node."""
        return IterationNodeConfig

    @classmethod
    def get_output_handles(cls) -> Optional[List[OutputHandle]]:
        """Return the two output handles for iteration nodes.

        - 'loop': Connects to body nodes that execute once per item
        - 'done': Connects to nodes that run after all iterations complete
        """
        return [
            {
                'id': 'loop',
                'label': 'Loop Body',
                'description': 'Executes once per item in the array',
            },
            {
                'id': 'done',
                'label': 'After Loop',
                'description': 'Executes once after all iterations complete, receives collected_results',
            },
        ]

    def _transform_to_objects(
        self,
        raw_items: List[Any],
        headers: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Transform a list of arrays into a list of objects using headers as keys.

        Args:
            raw_items: List of arrays (each array is a row)
            headers: List of field names to use as keys

        Returns:
            List of dicts with header-keyed values
        """
        result = []
        for row in raw_items:
            if not isinstance(row, (list, tuple)):
                # Single value - wrap in object with first header
                obj = {headers[0]: row} if headers else {'value': row}
            else:
                # Map each value to its corresponding header
                obj = {}
                for i, value in enumerate(row):
                    if i < len(headers):
                        key = headers[i]
                        # Clean up header names (strip whitespace, handle empty)
                        key = str(key).strip() if key else f'field_{i}'
                        obj[key] = value
                    else:
                        # Extra values beyond headers - use index-based key
                        obj[f'field_{i}'] = value
                # Add any headers that weren't filled (for short rows)
                for i in range(len(row), len(headers)):
                    obj[headers[i]] = None
            result.append(obj)
        return result

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the iteration node.

        Note: The actual iteration logic (executing downstream nodes per item)
        is handled by IterationExecutionStrategy. This execute() method is called
        once to set up the iteration context.

        The strategy will:
        1. Call this execute() to get the items array
        2. For each item, inject loop variables at top level (implicit scoping)
        3. Execute downstream nodes with access to {{item}}, {{index}}, etc.
        4. Aggregate results

        Loop variables available in body nodes (implicit scoping):
        - {{item}} - Current iteration item
        - {{index}} - Current iteration index (0-based)
        - {{items}} - Full array being iterated
        - {{total}} - Total number of items
        - {{row_number}} - Current row number (1-based, adjusted for headers)

        Backward compatible explicit references also work:
        - {{iteration-id.item}}, {{iteration-id.index}}, etc.

        Args:
            inputs: Output data from upstream nodes (items array should be resolved here)

        Returns:
            Dict containing iteration metadata and the items array
        """
        logger.info(f"[IterationNode] Executing node {self.node_id}")

        # Get config
        node_config = self.config
        if not node_config or not isinstance(node_config, IterationNodeConfig):
            raise ValueError(f"[IterationNode] Configuration required for node {self.node_id}")

        config = node_config.config

        # The 'items' field should already be resolved by the handler's reference resolution
        # It will contain the actual array from the upstream node
        items_ref = config.items

        # At this point, items_ref should be the resolved array (if it was a reference)
        # The handler resolves references before calling execute()
        # However, if it's still a string, it means it wasn't resolved (direct value or error)
        if isinstance(items_ref, str):
            # Check if it looks like an unresolved reference
            if items_ref.startswith('{{') and items_ref.endswith('}}'):
                raise ValueError(
                    f"[IterationNode] Items reference '{items_ref}' was not resolved. "
                    "Make sure the upstream node has executed and the path is correct."
                )
            # Otherwise try to parse as JSON array
            import json
            try:
                raw_items = json.loads(items_ref)
            except json.JSONDecodeError:
                raise ValueError(
                    f"[IterationNode] Items must be an array. Got string: {items_ref[:100]}..."
                )
        elif isinstance(items_ref, list):
            raw_items = items_ref
        else:
            raise ValueError(
                f"[IterationNode] Items must be an array. Got {type(items_ref).__name__}: {items_ref}"
            )

        # Apply transformations based on config
        headers: Optional[List[str]] = None
        items = raw_items

        # Option 1: Header row mode - first row contains field names
        if config.header_row == "true" and len(raw_items) > 0:
            if not isinstance(raw_items[0], (list, tuple)):
                # Provide helpful error message for common case (RSS/API data already as objects)
                item_type = type(raw_items[0]).__name__
                if item_type == 'dict':
                    raise ValueError(
                        f"[IterationNode] header_row=True requires 2D array (array of arrays), "
                        f"but first item is already a dict/object with keys: {list(raw_items[0].keys())[:5]}. "
                        f"For RSS feeds or API data that returns objects, set header_row=False to use the data as-is."
                    )
                else:
                    raise ValueError(
                        f"[IterationNode] header_row=True requires 2D array (array of arrays). "
                        f"First item is {item_type}, not an array."
                    )
            headers = [str(h).strip() for h in raw_items[0]]
            data_rows = raw_items[1:]  # Skip header row
            items = self._transform_to_objects(data_rows, headers)
            logger.info(f"[IterationNode] Transformed with headers: {headers}")

        # Option 2: Explicit field names provided
        elif config.field_names:
            field_names_str = config.field_names.strip()
            if field_names_str:
                headers = [f.strip() for f in field_names_str.split(',')]
                items = self._transform_to_objects(raw_items, headers)
                logger.info(f"[IterationNode] Transformed with explicit fields: {headers}")

        total = len(items)
        concurrency = config.concurrency
        logger.info(f"[IterationNode] Iterating over {total} items with concurrency={concurrency}")

        # Return the iteration context
        # The handler will update this with 'item' and 'index' for each iteration
        output = {
            'items': items,
            'total': total,
            'item': items[0] if items else None,  # Current item (first for initial state)
            'index': 0,  # Current index (0 for initial state)
            'isIterationNode': True,  # Marker for handler to recognize
            'headers': headers,  # Include headers for reference
            'concurrency': concurrency,  # Concurrency limit for parallel execution
        }

        await self.emit(output)
        return output


# ============================================================================
# Iteration Execution Strategy
# ============================================================================

class IterationExecutionStrategy:
    """
    Execution strategy for iteration nodes.

    Handles the orchestration of body nodes for each item in the iteration,
    including:
    - Topological sorting of body nodes based on inter-dependencies
    - Concurrent execution with configurable parallelism
    - Progress reporting and state management
    - Result aggregation
    - Two output handles:
      - "loop" (or null/undefined): body nodes that execute per-item
      - "done": nodes that receive aggregated results after all iterations
    """

    def handles(self, node_type: str) -> bool:
        """Return True if this strategy handles iteration nodes."""
        return node_type == 'iteration'

    def _get_successors_by_handle(
        self,
        node_id: str,
        edges: List[Dict[str, Any]],
        all_successors: Set[str]
    ) -> tuple[Set[str], Set[str]]:
        """
        Categorize successors based on the sourceHandle of the connecting edge.

        Returns:
            (loop_successors, done_successors) tuple where:
            - loop_successors: nodes connected via "loop" handle (or null/undefined for backward compatibility)
            - done_successors: nodes connected via "done" handle
        """
        loop_successors: Set[str] = set()
        done_successors: Set[str] = set()

        # Build a map of target -> sourceHandle for edges from this node
        for edge in edges:
            if edge.get('source') != node_id:
                continue
            target = edge.get('target')
            if target not in all_successors:
                continue

            source_handle = edge.get('sourceHandle')
            # "loop" handle or null/undefined = body node (backward compatibility)
            # "done" handle = post-iteration node
            if source_handle == 'done':
                done_successors.add(target)
            else:
                # Treat "loop", null, undefined, or any other value as loop body
                loop_successors.add(target)

        return loop_successors, done_successors

    def _find_loopback_node(
        self,
        iteration_node_id: str,
        loop_body_ids: Set[str],
        edges: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Find the body node that loops back to the iteration node's input.

        The loop-back connection explicitly marks which body node's output should
        be aggregated into collected_results. If no loop-back is found, returns None
        and we fall back to the last body node (topologically sorted).

        Args:
            iteration_node_id: The iteration node ID
            loop_body_ids: Set of body node IDs (connected via "loop" handle)
            edges: All workflow edges

        Returns:
            The ID of the body node that loops back, or None if no loop-back found
        """
        for edge in edges:
            source = edge.get('source')
            target = edge.get('target')
            # Check if this edge goes FROM a body node TO the iteration node
            if source in loop_body_ids and target == iteration_node_id:
                logger.info(f"[IterationStrategy] Found loop-back from {source} to {iteration_node_id}")
                return source
        return None

    def _find_all_loop_body_nodes(
        self,
        iteration_node_id: str,
        initial_loop_nodes: Set[str],
        done_nodes: Set[str],
        successors: Dict[str, Set[str]],
        node_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        edges: Optional[List[Dict[str, Any]]] = None,
    ) -> Set[str]:
        """
        Find ALL nodes that should execute as part of the loop body.

        Starting from nodes directly connected to the loop handle, traverse
        forward through the graph to find all transitively reachable nodes.

        This enables loop variable propagation through chains:
        iteration (loop) → A → B → C
        All of A, B, C should execute per iteration with loop variables.

        Args:
            iteration_node_id: The iteration node ID
            initial_loop_nodes: Nodes directly connected via loop handle
            done_nodes: Nodes connected via done handle (exclude from loop)
            successors: Map of node ID to successor IDs

        Returns:
            Set of all node IDs that should execute per iteration

        Stops traversal at:
            - Nodes connected to "done" handle (those execute after loop)
            - The iteration node itself (loopback edges for aggregation)
        """
        loop_body = set(initial_loop_nodes)
        to_visit = list(initial_loop_nodes)
        visited = set()

        logger.info(
            f"[IterationStrategy] Starting transitive loop body discovery from: {initial_loop_nodes}"
        )

        while to_visit:
            node_id = to_visit.pop(0)

            if node_id in visited:
                continue
            visited.add(node_id)

            # For nested iteration nodes, only follow done-handle successors.
            # Loop-handle successors are the inner loop body — they'll be executed
            # by the inner iteration's own strategy. Including them here causes
            # double execution and recursive {'iterations': {...}} nesting that
            # leads to exponential memory growth.
            node_data = node_by_id.get(node_id, {}) if node_by_id else {}
            is_nested_iteration = (
                node_data.get('type') == 'iteration'
                and node_id != iteration_node_id
            )

            if is_nested_iteration and edges is not None:
                # Only traverse done-handle successors of nested iterations
                node_successors = successors.get(node_id, set())
                _, nested_done_nodes = self._get_successors_by_handle(
                    node_id, edges, node_successors
                )
                for successor in nested_done_nodes:
                    if successor == iteration_node_id:
                        continue
                    if successor in done_nodes:
                        continue
                    if successor not in loop_body:
                        logger.info(
                            f"[IterationStrategy] Adding done-handle successor of nested iteration: "
                            f"{successor} (from {node_id})"
                        )
                        loop_body.add(successor)
                        to_visit.append(successor)
                continue

            # Get successors of this node
            for successor in successors.get(node_id, set()):
                # Stop if we reach the iteration node (loopback for aggregation)
                if successor == iteration_node_id:
                    logger.info(
                        f"[IterationStrategy] Found loopback edge: {node_id} → {iteration_node_id}"
                    )
                    continue

                # Stop if this successor is connected to done handle
                # (done nodes execute AFTER loop, not during)
                if successor in done_nodes:
                    logger.info(
                        f"[IterationStrategy] Stopping at done node: {successor}"
                    )
                    continue

                # Add to loop body and continue traversal
                if successor not in loop_body:
                    logger.info(
                        f"[IterationStrategy] Adding transitive loop body node: {successor} (from {node_id})"
                    )
                    loop_body.add(successor)
                    to_visit.append(successor)

        logger.info(
            f"[IterationStrategy] Transitive loop body discovery complete. "
            f"Initial nodes: {initial_loop_nodes}, All loop body nodes: {loop_body}"
        )

        return loop_body

    def _sort_body_nodes(
        self,
        body_ids: Set[str],
        predecessors: Dict[str, Set[str]],
        successors: Dict[str, Set[str]]
    ) -> List[str]:
        """
        Sort body nodes topologically based on inter-body-node dependencies.

        This ensures that if body node A depends on body node B, B executes first
        within each iteration.

        Args:
            body_ids: Set of body node IDs
            predecessors: Map of node ID to predecessor IDs
            successors: Map of node ID to successor IDs

        Returns:
            List of body node IDs in execution order
        """
        if len(body_ids) <= 1:
            return list(body_ids)

        # Build in-degree for body nodes only (edges within body)
        body_in_degree = {bid: 0 for bid in body_ids}
        body_successors = {bid: [] for bid in body_ids}

        for bid in body_ids:
            for pred in predecessors.get(bid, set()):
                if pred in body_ids:  # Only count dependencies within body
                    body_in_degree[bid] += 1
            for succ in successors.get(bid, set()):
                if succ in body_ids:  # Only track successors within body
                    body_successors[bid].append(succ)

        # Kahn's algorithm for topological sort
        queue = deque([bid for bid in body_ids if body_in_degree[bid] == 0])
        sorted_body = []

        while queue:
            bid = queue.popleft()
            sorted_body.append(bid)
            for succ in body_successors[bid]:
                body_in_degree[succ] -= 1
                if body_in_degree[succ] == 0:
                    queue.append(succ)

        # If cycle detected, fall back to arbitrary order
        if len(sorted_body) != len(body_ids):
            logger.warning("[IterationStrategy] Cycle in body nodes, using arbitrary order")
            return list(body_ids)

        return sorted_body

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """
        Execute an iteration node and its body nodes for each item.

        This method handles the iteration logic with implicit loop variable scoping:
        1. Execute the iteration node to get the items array
        2. Identify and sort body nodes (direct successors)
        3. For each item:
           - Inject loop variables at TOP LEVEL: {{item}}, {{index}}, {{items}}, {{total}}, {{row_number}}
           - Execute all body nodes with iteration context
        4. Aggregate results and signal completion

        Loop Variable Scoping:
        - Loop variables are injected at the top level of node_outputs
        - Body nodes can reference {{item}} instead of {{iteration-id.item}}
        - This matches industry best practices (Make, Zapier)
        - Reduces edge clutter and improves UX for complex workflows
        - Backward compatible: {{iteration-id.item}} still works

        Args:
            ctx: ExecutionContext with node info and callbacks

        Returns:
            ExecutionResult with aggregated output and handled body nodes
        """
        node_id = ctx.node_id
        node = ctx.node
        node_type = 'iteration'

        # Initialize variables for error/finally handling
        all_loop_body_node_ids: Set[str] = set()
        done_node_ids: Set[str] = set()

        try:
            async with ctx.semaphore:
                await ctx.emit_state(node_id, node_type, 'running', None)

                # Check if iteration node has mocked output - use mocked items if so
                # This allows iteration to still loop over items while using mocked data
                mocked_output = node.get('config', {}).get('mockedOutput')
                if mocked_output is not None and isinstance(mocked_output, dict):
                    logger.info(f"[IterationStrategy] Using mocked output for iteration node {node_id}")
                    iteration_output = mocked_output
                else:
                    # Execute the iteration node to get items array
                    iteration_output = await ctx.execute_node(node, ctx.node_outputs)

                items = iteration_output.get('items', [])
                total = len(items)

                if not isinstance(items, list):
                    raise ValueError(f"Iteration node expected array, got {type(items).__name__}")

                logger.info(f"[IterationStrategy] Node {node_id} iterating over {total} items")

                # Get direct successors and categorize by handle
                all_successors = ctx.successors.get(node_id, set())
                initial_loop_node_ids, done_node_ids = self._get_successors_by_handle(
                    node_id, ctx.edges, all_successors
                )
                logger.info(
                    f"[IterationStrategy] Direct loop nodes: {initial_loop_node_ids}, "
                    f"Done nodes: {done_node_ids}"
                )

                # Find ALL nodes in the loop body (including transitive downstream nodes)
                # This allows chains like: iteration → A → B → C
                # where all of A, B, C execute per iteration with loop variables
                all_loop_body_node_ids = self._find_all_loop_body_nodes(
                    node_id, initial_loop_node_ids, done_node_ids, ctx.successors,
                    node_by_id=ctx.node_by_id, edges=ctx.edges,
                )
                logger.info(
                    f"[IterationStrategy] All loop body nodes (including transitive): "
                    f"{all_loop_body_node_ids}"
                )

                # Sort loop body nodes for execution order
                sorted_body_node_ids = self._sort_body_nodes(
                    all_loop_body_node_ids, ctx.predecessors, ctx.successors
                )
                logger.info(f"[IterationStrategy] Body node execution order: {sorted_body_node_ids}")

                # Collect results per iteration
                iteration_results: List[Dict[str, Any]] = [None] * total

                # Calculate row offset for sheet addressing:
                # If header_row was used, data starts at row 2 (row 1 is header)
                has_header = iteration_output.get('headers') is not None
                row_offset = 2 if has_header else 1

                # Get concurrency limit - prefer from iteration output, fall back to node config
                # When mocked, the mocked output may not have concurrency, so read from config
                concurrency_limit = iteration_output.get('concurrency')
                if concurrency_limit is None:
                    # Try multiple locations for concurrency config:
                    # Due to a frontend quirk, updated config values may be at top level
                    # while stale values remain in nested config. Prefer top-level.
                    # 1. Top-level config (has newer values): node.config.concurrency
                    # 2. Nested config (standard schema structure): node.config.config.concurrency
                    outer_config = node.get('config', {})
                    inner_config = outer_config.get('config', {}) if isinstance(outer_config, dict) else {}

                    # Prefer top-level (newer) over nested (may be stale)
                    if isinstance(outer_config, dict) and 'concurrency' in outer_config:
                        concurrency_limit = outer_config.get('concurrency', 1)
                    elif isinstance(inner_config, dict) and 'concurrency' in inner_config:
                        concurrency_limit = inner_config.get('concurrency', 1)
                    else:
                        concurrency_limit = 1
                logger.info(f"[IterationStrategy] Iteration concurrency limit: {concurrency_limit}")

                # Create semaphore to limit concurrent iterations
                iteration_semaphore = asyncio.Semaphore(concurrency_limit)

                # Shared counter for tracking completed iterations (monotonically increasing for progress UI)
                completed_count = 0
                completed_count_lock = asyncio.Lock()

                async def execute_single_iteration(index: int, item: Any) -> Dict[str, Any]:
                    """Execute body nodes for a single iteration."""
                    nonlocal completed_count
                    async with iteration_semaphore:
                        row_number = index + row_offset

                        # Create iteration context for this item
                        iteration_context = {
                            'items': items,
                            'total': total,
                            'item': item,
                            'index': index,
                            'row_number': row_number,
                            'isIterationNode': True,
                        }

                        # Emit progress update (iteration starting)
                        await ctx.emit_output(node_id, node_type, {
                            'progress': f"{index + 1}/{total}",
                            'index': index,
                            'row_number': row_number,
                            'total': total,
                            'item': item,
                            'completed': completed_count,
                        })

                        # Execute each body node for this iteration (in topological order)
                        iteration_outputs: Dict[str, Any] = {}
                        iteration_failed = False

                        for body_node_id in sorted_body_node_ids:
                            body_node = ctx.node_by_id.get(body_node_id)
                            if not body_node:
                                continue

                            body_node_type = body_node.get('type', 'unknown')

                            # Check if body node is disabled
                            if body_node.get('config', {}).get('disabled', False):
                                logger.info(f"[IterationStrategy] Skipping disabled body node {body_node_id}")
                                continue

                            # Check for mocked output
                            body_mocked = body_node.get('config', {}).get('mockedOutput')
                            if body_mocked is not None:
                                iteration_outputs[body_node_id] = body_mocked
                                continue

                            try:
                                await ctx.emit_state(body_node_id, body_node_type, 'running', None)

                                # Create node_outputs with this iteration's context
                                iteration_node_outputs = dict(ctx.node_outputs)
                                iteration_node_outputs[node_id] = iteration_context

                                # IMPLICIT LOOP VARIABLE SCOPING
                                # Inject loop variables at top level so nodes can reference {{item}}, {{index}}, etc.
                                # without needing to know the iteration node ID ({{iteration-id.item}})
                                # This matches industry best practices (Make, Zapier)

                                # Define loop variables to inject
                                loop_vars = {
                                    'item': item,
                                    'index': index,
                                    'items': items,
                                    'total': total,
                                    'row_number': row_number,
                                }

                                # Check for name collisions and warn if found
                                for var_name, var_value in loop_vars.items():
                                    if var_name in iteration_node_outputs and var_name != node_id:
                                        # There's a node with the same ID as a loop variable
                                        # This is unlikely but possible (e.g., a node named "item")
                                        logger.warning(
                                            f"[IterationStrategy] Loop variable '{var_name}' shadows existing node output. "
                                            f"Loop scope takes precedence. Original value available at node ID."
                                        )
                                    # Inject loop variable at top level
                                    iteration_node_outputs[var_name] = var_value

                                # Include outputs from previously executed body nodes in this iteration
                                # This allows body nodes to reference each other (e.g., agent -> sheets write)
                                iteration_node_outputs.update(iteration_outputs)

                                # Nested iteration: run the inner iteration's full strategy
                                # so its body nodes execute per-item with proper loop context.
                                # Without this, the inner iteration's body nodes would run
                                # outside any iteration context with unresolved references.
                                if body_node_type == 'iteration':
                                    nested_ctx = ExecutionContext(
                                        node_id=body_node_id,
                                        node=body_node,
                                        workflow_id=ctx.workflow_id,
                                        node_outputs=iteration_node_outputs,
                                        node_by_id=ctx.node_by_id,
                                        successors=ctx.successors,
                                        predecessors=ctx.predecessors,
                                        edges=ctx.edges,
                                        sid=ctx.sid,
                                        user_id=ctx.user_id,
                                        semaphore=ctx.semaphore,
                                        execute_node=ctx.execute_node,
                                        emit_state=ctx.emit_state,
                                        emit_output=ctx.emit_output,
                                        mark_completed=ctx.mark_completed,
                                        mark_failed=ctx.mark_failed,
                                        mark_skipped=ctx.mark_skipped,
                                        signal_done=ctx.signal_done,
                                        organization_id=ctx.organization_id,
                                        execution_id=ctx.execution_id,
                                    )
                                    nested_result = await IterationExecutionStrategy().execute(nested_ctx)
                                    body_output = nested_result.output
                                    # Track inner body nodes so they're skipped by the main loop
                                    all_loop_body_node_ids.update(nested_result.body_nodes_handled)
                                else:
                                    body_output = await ctx.execute_node(body_node, iteration_node_outputs)

                                iteration_outputs[body_node_id] = body_output

                                await ctx.emit_output(body_node_id, body_node_type, body_output)
                                await ctx.emit_state(body_node_id, body_node_type, 'completed', None)

                            except Exception as e:
                                logger.error(f"[IterationStrategy] Body node {body_node_id} failed at iteration {index}: {e}")
                                iteration_outputs[body_node_id] = {'error': str(e)}
                                iteration_failed = True

                                await ctx.emit_state(body_node_id, body_node_type, 'error', str(e))

                        # Persist body node outputs for this iteration (fire-and-forget).
                        # Keyed by the REAL execution_id under a composite node_id
                        # '<body_node>#iter:<index>' so CAS retention (Phase A, which
                        # prunes by execution_id) reaches them, while the carousel still
                        # surfaces each iteration under the body node (history prefix match).
                        if ctx.execution_id and iteration_outputs and not iteration_failed:
                            try:
                                from utils.node_outputs import persist_outputs
                                from utils.database_pool import get_native_pool
                                pool = get_native_pool()
                                iter_outputs = {
                                    f"{nid}#iter:{index}": out
                                    for nid, out in iteration_outputs.items()
                                }

                                async def _persist_iter_outputs(
                                    p=pool,
                                    wf=ctx.workflow_id,
                                    eid=ctx.execution_id,
                                    outs=iter_outputs,
                                ):
                                    try:
                                        await persist_outputs(p, workflow_id=wf, execution_id=eid, node_outputs=outs)
                                    except Exception as e:
                                        logger.warning(
                                            f"[IterationStrategy] Failed to persist iteration outputs "
                                            f"for execution {eid}: {e}"
                                        )

                                from utils.async_helpers import spawn
                                spawn(_persist_iter_outputs(), name="iteration-persist-outputs")
                            except Exception:
                                pass  # Non-critical — don't block iteration

                        # Increment completed counter and emit progress update
                        async with completed_count_lock:
                            completed_count += 1
                            current_completed = completed_count
                        await ctx.emit_output(node_id, node_type, {
                            'progress': f"{current_completed}/{total}",
                            'completed': current_completed,
                            'total': total,
                        })

                        return {
                            'index': index,
                            'item': item,
                            'outputs': iteration_outputs,
                            'success': not iteration_failed,
                        }

                # Execute all iterations concurrently (limited by semaphore)
                iteration_tasks = [
                    execute_single_iteration(index, item)
                    for index, item in enumerate(items)
                ]
                completed_results = await asyncio.gather(*iteration_tasks, return_exceptions=True)

                # Process results, handling any exceptions
                for i, result in enumerate(completed_results):
                    if isinstance(result, Exception):
                        logger.error(f"[IterationStrategy] Iteration {i} raised exception: {result}")
                        iteration_results[i] = {
                            'index': i,
                            'item': items[i],
                            'outputs': {'error': str(result)},
                            'success': False,
                        }
                    else:
                        iteration_results[i] = result

                # Determine which body node's output to aggregate into collected_results
                # Priority: 1) Node that loops back to iteration input, 2) Last body node (topological)
                loopback_node_id = self._find_loopback_node(node_id, all_loop_body_node_ids, ctx.edges)
                aggregation_source_id = loopback_node_id or (sorted_body_node_ids[-1] if sorted_body_node_ids else None)

                if loopback_node_id:
                    logger.info(f"[IterationStrategy] Using loop-back node {loopback_node_id} for aggregation")
                elif aggregation_source_id:
                    logger.info(f"[IterationStrategy] No loop-back found, using last body node {aggregation_source_id} for aggregation")

                # Build collected_results: flat array of the aggregation source node's outputs
                # This simplifies downstream access - instead of navigating results[*].outputs.nodeId.result,
                # consumers can directly use collected_results[*]
                collected_results = []

                if aggregation_source_id:
                    for result in iteration_results:
                        if not result.get('success', False):
                            # Include error info for failed iterations
                            collected_results.append({'_iteration_error': result.get('outputs', {}).get('error', 'Unknown error')})
                            continue

                        outputs = result.get('outputs', {})
                        node_output = outputs.get(aggregation_source_id)

                        if node_output is None:
                            collected_results.append(None)
                        elif isinstance(node_output, dict):
                            # Extract the useful data based on node type
                            # For serverless functions: extract 'result' field
                            # For API nodes (Apollo, etc.): extract 'data' or 'data.person' field
                            # This removes metadata like status, timing_ms, etc.
                            if 'result' in node_output and node_output.get('type') == 'serverless_function':
                                collected_results.append(node_output['result'])
                            elif 'data' in node_output and node_output.get('status') in ('success', 'completed'):
                                # API nodes typically have {data: {...}, status: 'success', ...}
                                # Extract just the data payload
                                data = node_output['data']
                                # For Apollo/enrichment nodes, data is {person: {...}}
                                # Extract the person object directly for cleaner output
                                if isinstance(data, dict) and 'person' in data and len(data) == 1:
                                    collected_results.append(data['person'])
                                else:
                                    collected_results.append(data)
                            else:
                                collected_results.append(node_output)
                        else:
                            collected_results.append(node_output)

                    logger.info(f"[IterationStrategy] Built collected_results with {len(collected_results)} items from body node {aggregation_source_id}")

                # Build final aggregated output
                # NOTE: We intentionally exclude the full `iteration_results` from final_output.
                # Storing it here caused massive memory retention: each iteration's body node
                # outputs stayed alive for the entire workflow. With nested iterations this
                # created exponential growth (inner results × outer iterations). Downstream
                # consumers should use `collected_results` (flat array) instead.
                headers = iteration_output.get('headers')
                success_count = sum(1 for r in iteration_results if r and r.get('success', False))
                final_output = {
                    'items': items,
                    'total': total,
                    'results_count': len(iteration_results),
                    'results_success': success_count,
                    'collected_results': collected_results,
                    'isIterationNode': True,
                    'completed': True,
                    'headers': headers,
                    'item': items[0] if items else None,
                    'index': 0,
                    'row_number': row_offset,
                }

                # Mark iteration node as completed
                await ctx.mark_completed(node_id, final_output)
                await ctx.emit_output(node_id, node_type, final_output)
                await ctx.emit_state(node_id, node_type, 'completed', None)

                # Update loop body node outputs internally (don't mark as completed)
                # This prevents the workflow executor from re-executing these nodes with aggregated output
                # before the iteration strategy returns and marks them as handled
                for body_node_id in all_loop_body_node_ids:
                    body_node = ctx.node_by_id.get(body_node_id)
                    if body_node:
                        # Set lightweight output for body nodes.
                        # IMPORTANT: We only keep lastOutput (not all iterations' outputs).
                        # Storing the full iterations array caused 20GB+ memory retention:
                        # 21 iterations × 10 body nodes × large agent outputs = OOM.
                        # Downstream consumers should use collected_results (on the
                        # aggregation source node or the iteration node) instead.
                        body_output = None
                        if iteration_results:
                            last_result = iteration_results[-1]
                            if body_node_id in last_result.get('outputs', {}):
                                body_output = {
                                    'lastOutput': last_result['outputs'].get(body_node_id),
                                    'iterationCount': total,
                                }
                                # Add collected_results to the aggregation source node's output
                                # This allows downstream nodes (like Google Sheets) to access
                                # the flat array directly via {{body_node.collected_results}}
                                if body_node_id == aggregation_source_id:
                                    body_output['collected_results'] = collected_results
                                    logger.info(f"[IterationStrategy] Added collected_results to aggregation source node {body_node_id}")

                        # Update output internally without calling mark_completed
                        # This avoids triggering re-execution of these nodes before they're marked as handled
                        if body_output is not None:
                            ctx.node_outputs[body_node_id] = body_output

                        # Signal done so dependencies can proceed, but don't emit state or mark completed
                        # The workflow executor will handle that after this strategy returns
                        ctx.signal_done(body_node_id)

                # Release iteration_results to allow GC of per-iteration output dicts.
                # All needed data has been extracted into body_output and collected_results.
                iteration_results.clear()

                # Execute "done" handle nodes with aggregated output
                # These nodes receive the final aggregated results after all iterations complete
                for done_node_id in done_node_ids:
                    done_node = ctx.node_by_id.get(done_node_id)
                    if not done_node:
                        continue

                    done_node_type = done_node.get('type', 'unknown')

                    # Check if done node is disabled
                    if done_node.get('config', {}).get('disabled', False):
                        logger.info(f"[IterationStrategy] Skipping disabled done node {done_node_id}")
                        await ctx.mark_completed(done_node_id, None)
                        await ctx.emit_state(done_node_id, done_node_type, 'completed', None)
                        ctx.signal_done(done_node_id)
                        continue

                    # Check for mocked output
                    done_mocked = done_node.get('config', {}).get('mockedOutput')
                    if done_mocked is not None:
                        logger.info(f"[IterationStrategy] Using mocked output for done node {done_node_id}")
                        await ctx.mark_completed(done_node_id, done_mocked)
                        await ctx.emit_output(done_node_id, done_node_type, done_mocked)
                        await ctx.emit_state(done_node_id, done_node_type, 'completed', None)
                        ctx.signal_done(done_node_id)
                        continue

                    try:
                        await ctx.emit_state(done_node_id, done_node_type, 'running', None)

                        # Create node_outputs with the final aggregated output from iteration
                        # Done nodes can reference {{iteration-node.collected_results}}, etc.
                        done_node_outputs = dict(ctx.node_outputs)
                        done_node_outputs[node_id] = final_output

                        done_output = await ctx.execute_node(done_node, done_node_outputs)

                        await ctx.mark_completed(done_node_id, done_output)
                        await ctx.emit_output(done_node_id, done_node_type, done_output)
                        await ctx.emit_state(done_node_id, done_node_type, 'completed', None)
                        logger.info(f"[IterationStrategy] Done node {done_node_id} completed successfully")

                    except Exception as e:
                        logger.error(f"[IterationStrategy] Done node {done_node_id} failed: {e}")
                        await ctx.emit_state(done_node_id, done_node_type, 'error', str(e))

                    finally:
                        ctx.signal_done(done_node_id)

                logger.info(f"[IterationStrategy] Node {node_id} completed {total} iterations")

                # Mark ALL handled nodes (loop body + done nodes) so workflow executor doesn't re-execute them
                all_handled_nodes = all_loop_body_node_ids | done_node_ids
                logger.info(f"[IterationStrategy] Marking as handled: {all_handled_nodes}")

                return ExecutionResult(
                    output=final_output,
                    body_nodes_handled=all_handled_nodes,  # Include ALL transitive loop body nodes + done nodes
                    success=True
                )

        except Exception as e:
            error_msg = f"Iteration node {node_id} failed: {str(e)}"
            logger.error(f"[IterationStrategy] {error_msg}")

            await ctx.mark_failed(node_id, error_msg)
            await ctx.emit_state(node_id, node_type, 'error', str(e))

            # Mark all transitive loop body nodes + done nodes as handled
            # If error happened early, fallback to all direct successors
            if all_loop_body_node_ids or done_node_ids:
                all_handled_nodes = all_loop_body_node_ids | done_node_ids
            else:
                all_handled_nodes = ctx.successors.get(node_id, set())

            logger.info(f"[IterationStrategy] Error handling - marking as handled: {all_handled_nodes}")

            return ExecutionResult(
                output=None,
                body_nodes_handled=all_handled_nodes,
                success=False,
                error=error_msg
            )

        finally:
            # Signal that iteration node is done
            ctx.signal_done(node_id)

            # Signal that ALL handled nodes are done (transitive loop body + done nodes)
            handled_nodes = (all_loop_body_node_ids | done_node_ids) if (all_loop_body_node_ids or done_node_ids) else ctx.successors.get(node_id, set())
            for successor_id in handled_nodes:
                ctx.signal_done(successor_id)
