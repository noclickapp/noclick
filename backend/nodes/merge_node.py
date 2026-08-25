"""
Merge node for combining multiple data streams.

This node combines data from multiple input branches into a single output stream.
It waits for all connected input branches to complete before performing the merge.

Key Features:
    - Append: Concatenates all inputs into a single array
    - Combine by position: Matches items by index position (like zip)
    - Combine by field: Matches items by a common field (like SQL JOIN)
    - Keep matches: Only keeps items that exist in all inputs
    - Remove duplicates: Merges and deduplicates across all inputs

Operations:
    - append: Concatenates all input arrays into one
    - combine_by_position: Zips inputs by index position
    - combine_by_field: Joins inputs by matching field values
    - keep_matches: Intersection of all inputs
    - remove_duplicates: Union of all inputs, deduplicated

Usage Examples:
    1. Append two lists:
       - Input 1: [1, 2, 3]
       - Input 2: [4, 5, 6]
       - Output: [1, 2, 3, 4, 5, 6]

    2. Combine by position:
       - Input 1: [{name: "Alice"}, {name: "Bob"}]
       - Input 2: [{email: "a@test.com"}, {email: "b@test.com"}]
       - Output: [{name: "Alice", email: "a@test.com"}, {name: "Bob", email: "b@test.com"}]

    3. Combine by field (join):
       - Input 1: [{id: 1, name: "Alice"}, {id: 2, name: "Bob"}]
       - Input 2: [{id: 1, email: "a@test.com"}, {id: 3, email: "c@test.com"}]
       - match_field: "id"
       - Output: [{id: 1, name: "Alice", email: "a@test.com"}]
"""

import logging
from typing import Dict, Any, Optional, Type, List, Set, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Merge Node Configuration
# ============================================================================
#
# Discriminated union over `operation`: each operation is its own config model
# exposing only the fields it needs, so the config UI never shows controls
# irrelevant to the selected operation.


def _operation_field(value: str, display_name: str) -> Any:
    """Build the hidden discriminator field shared by every operation config."""
    return Field(
        default=value,
        title=display_name,
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": display_name,
            "x-category": "Merge",
            "x-is-trigger": False,
        },
    )


_MATCH_FIELD_DESC = "Field name to match items across inputs (e.g., 'id', 'email')."


class MergeAppendConfig(BaseModel):
    """Concatenate all input arrays into one."""

    operation: Literal["append"] = _operation_field("append", "Append")


class MergeCombineByPositionConfig(BaseModel):
    """Combine inputs by index position (like zip)."""

    operation: Literal["combine_by_position"] = _operation_field(
        "combine_by_position", "Combine by Position"
    )


class MergeCombineByFieldConfig(BaseModel):
    """Join inputs by matching a common field (like a SQL JOIN)."""

    operation: Literal["combine_by_field"] = _operation_field(
        "combine_by_field", "Combine by Field"
    )
    match_field: Optional[str] = Field(
        default=None,
        title="Match Field",
        description=_MATCH_FIELD_DESC,
        json_schema_extra={"placeholder": "field_name"},
    )
    conflict_resolution: Literal["prefer_first", "prefer_last", "merge"] = Field(
        default="prefer_first",
        title="Conflict Resolution",
        description="When two inputs share a field, prefer the first input, the last input, or merge them.",
        json_schema_extra={"enumNames": ["Prefer first", "Prefer last", "Merge"]},
    )


class MergeKeepMatchesConfig(BaseModel):
    """Keep only items that exist in every input (intersection)."""

    operation: Literal["keep_matches"] = _operation_field(
        "keep_matches", "Keep Matches"
    )
    match_field: Optional[str] = Field(
        default=None,
        title="Match Field",
        description=_MATCH_FIELD_DESC + " Leave empty to compare whole items.",
        json_schema_extra={"placeholder": "field_name"},
    )


class MergeRemoveDuplicatesConfig(BaseModel):
    """Merge all inputs and remove duplicate items."""

    operation: Literal["remove_duplicates"] = _operation_field(
        "remove_duplicates", "Remove Duplicates"
    )
    dedupe_field: Optional[str] = Field(
        default=None,
        title="Deduplication Field",
        description="Field to use for detecting duplicates. Leave empty to compare whole items.",
        json_schema_extra={"placeholder": "field_name"},
    )


MergeConfig = Annotated[
    Union[
        MergeAppendConfig,
        MergeCombineByPositionConfig,
        MergeCombineByFieldConfig,
        MergeKeepMatchesConfig,
        MergeRemoveDuplicatesConfig,
    ],
    Discriminator("operation"),
]


class MergeNodeConfig(NodeConfig[MergeConfig, None]):
    """Full configuration for merge node (no credentials needed)."""

    pass


# ============================================================================
# Merge Node Implementation
# ============================================================================

class MergeNode(WorkflowNode):
    """
    Merge workflow node for combining multiple data streams.

    This node receives data from multiple input branches and combines them
    according to the configured operation. The execution handler passes all
    predecessor outputs to this node.

    Unlike conditional or iteration nodes, the merge node doesn't need a custom
    execution strategy because the standard workflow handler already passes
    all predecessor outputs to execute().
    """

    # Marker to identify this as a merge node (for potential future use)
    IS_MERGE_NODE = True

    edit_examples = [
        "Switch to combine_by_field and match on email to join user data",
        "Change operation to keep_matches to find common records across inputs",
        "Use remove_duplicates by ID field to consolidate overlapping results",
        "Change from append to combine_by_position for zipping paired arrays",
        "Update conflict resolution to merge when combining by the user_id field",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        """Get Pydantic config model for merge node."""
        return MergeNodeConfig

    def _extract_arrays_from_inputs(self, inputs: Dict[str, Any]) -> List[List[Any]]:
        """
        Extract array data from all inputs.

        Inputs may be:
        - Direct arrays: [1, 2, 3]
        - Objects with array fields: {data: [1, 2, 3], items: [...]}
        - Nested results: {filtered: [...], collected_results: [...]}

        Args:
            inputs: Dict of predecessor node outputs

        Returns:
            List of arrays extracted from inputs
        """
        arrays = []

        for node_id, output in inputs.items():
            if output is None:
                continue

            # Direct array
            if isinstance(output, list):
                arrays.append(output)
                continue

            # Object with potential array fields
            if isinstance(output, dict):
                # Priority order for finding the array
                array_fields = [
                    'data', 'items', 'filtered', 'collected_results',
                    'values', 'rows', 'results', 'records'
                ]

                found = False
                for field in array_fields:
                    if field in output and isinstance(output[field], list):
                        arrays.append(output[field])
                        found = True
                        break

                # If no standard array field found, check for any array in output
                if not found:
                    for key, value in output.items():
                        if isinstance(value, list) and key not in ('errors', '_metadata'):
                            arrays.append(value)
                            found = True
                            break

                # If still nothing, treat the whole output as a single item
                if not found and output:
                    arrays.append([output])

        return arrays

    def _append(self, arrays: List[List[Any]]) -> List[Any]:
        """Concatenate all arrays into one."""
        result = []
        for arr in arrays:
            result.extend(arr)
        return result

    def _combine_by_position(self, arrays: List[List[Any]]) -> List[Any]:
        """Combine arrays by index position (like zip)."""
        if not arrays:
            return []

        max_length = max(len(arr) for arr in arrays)
        result = []

        for i in range(max_length):
            combined = {}
            for arr in arrays:
                if i < len(arr):
                    item = arr[i]
                    if isinstance(item, dict):
                        combined.update(item)
                    else:
                        # Non-dict items get indexed keys
                        idx = arrays.index(arr)
                        combined[f'input_{idx}'] = item

            result.append(combined)

        return result

    def _combine_by_field(
        self,
        arrays: List[List[Any]],
        match_field: str,
        conflict_resolution: str = "prefer_first"
    ) -> List[Any]:
        """Combine arrays by matching field (like SQL JOIN)."""
        if not arrays or not match_field:
            return []

        # Build index from first array
        result_map: Dict[Any, Dict] = {}

        for arr_idx, arr in enumerate(arrays):
            for item in arr:
                if not isinstance(item, dict):
                    continue

                key = item.get(match_field)
                if key is None:
                    continue

                if key in result_map:
                    # Handle conflict
                    existing = result_map[key]
                    if conflict_resolution == "prefer_last":
                        result_map[key] = {**existing, **item}
                    elif conflict_resolution == "merge":
                        # Deep merge - combine all fields
                        for k, v in item.items():
                            if k not in existing:
                                existing[k] = v
                            elif isinstance(existing[k], list) and isinstance(v, list):
                                existing[k] = existing[k] + v
                            elif isinstance(existing[k], dict) and isinstance(v, dict):
                                existing[k] = {**existing[k], **v}
                            # else: prefer_first behavior (keep existing)
                    # prefer_first: don't overwrite, just add missing fields
                    else:
                        for k, v in item.items():
                            if k not in existing:
                                existing[k] = v
                else:
                    result_map[key] = dict(item)

        return list(result_map.values())

    def _keep_matches(
        self,
        arrays: List[List[Any]],
        match_field: Optional[str] = None
    ) -> List[Any]:
        """Keep only items that exist in ALL inputs (intersection)."""
        if not arrays:
            return []

        if len(arrays) == 1:
            return arrays[0]

        # Get keys from all arrays
        def get_key(item: Any) -> Any:
            if match_field and isinstance(item, dict):
                return item.get(match_field)
            if isinstance(item, dict):
                import json
                return json.dumps(item, sort_keys=True)
            return item

        # Find intersection of keys
        all_keys = [set(get_key(item) for item in arr if get_key(item) is not None) for arr in arrays]
        common_keys = all_keys[0]
        for keys in all_keys[1:]:
            common_keys = common_keys.intersection(keys)

        # Return items from first array that have common keys
        result = []
        seen = set()
        for item in arrays[0]:
            key = get_key(item)
            if key in common_keys and key not in seen:
                result.append(item)
                seen.add(key)

        return result

    def _remove_duplicates(
        self,
        arrays: List[List[Any]],
        dedupe_field: Optional[str] = None
    ) -> List[Any]:
        """Merge all arrays and remove duplicates."""
        all_items = self._append(arrays)

        seen = set()
        result = []

        for item in all_items:
            # Determine key for deduplication
            if dedupe_field and isinstance(item, dict):
                key = item.get(dedupe_field)
            elif isinstance(item, dict):
                import json
                key = json.dumps(item, sort_keys=True)
            elif isinstance(item, list):
                import json
                key = json.dumps(item, sort_keys=True)
            else:
                key = item

            if key not in seen:
                seen.add(key)
                result.append(item)

        return result

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the merge node.

        Args:
            inputs: Output data from all predecessor nodes

        Returns:
            Dict containing merged data
        """
        logger.info(f"[MergeNode] Executing node {self.node_id} with {len(inputs)} inputs")

        # Get config
        node_config = self.config
        if not node_config or not isinstance(node_config, MergeNodeConfig):
            return {
                "status": "no_config",
                "merged": [],
                "count": 0,
                "error": "Configuration required"
            }

        config = node_config.config

        try:
            # Extract arrays from all inputs
            arrays = self._extract_arrays_from_inputs(inputs)

            if not arrays:
                return {
                    "status": "success",
                    "merged": [],
                    "count": 0,
                    "input_count": 0,
                    "operation": config.operation,
                    "message": "No input data to merge"
                }

            # Dispatch on the operation config variant
            if isinstance(config, MergeAppendConfig):
                merged = self._append(arrays)
                operation_info = {'total_inputs': len(arrays)}

            elif isinstance(config, MergeCombineByPositionConfig):
                merged = self._combine_by_position(arrays)
                operation_info = {'total_inputs': len(arrays)}

            elif isinstance(config, MergeCombineByFieldConfig):
                if not config.match_field:
                    return {
                        "status": "error",
                        "merged": [],
                        "count": 0,
                        "error": "match_field is required for combine_by_field operation"
                    }
                merged = self._combine_by_field(
                    arrays,
                    config.match_field,
                    config.conflict_resolution
                )
                operation_info = {
                    'match_field': config.match_field,
                    'conflict_resolution': config.conflict_resolution
                }

            elif isinstance(config, MergeKeepMatchesConfig):
                merged = self._keep_matches(arrays, config.match_field)
                operation_info = {'match_field': config.match_field}

            elif isinstance(config, MergeRemoveDuplicatesConfig):
                merged = self._remove_duplicates(arrays, config.dedupe_field)
                operation_info = {'dedupe_field': config.dedupe_field}

            else:
                return {
                    "status": "error",
                    "merged": [],
                    "count": 0,
                    "error": f"Unknown configuration type: {type(config).__name__}"
                }

            # Calculate stats
            total_input_items = sum(len(arr) for arr in arrays)

            output = {
                'status': 'success',
                'merged': merged,
                'count': len(merged),
                'input_count': len(arrays),
                'total_input_items': total_input_items,
                'operation': config.operation,
                **operation_info,
                'isMergeNode': True,
            }

            logger.info(f"[MergeNode] Merged {total_input_items} items from {len(arrays)} inputs into {len(merged)} items")

            await self.emit(output)
            return output

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[MergeNode] Error: {error_msg}")
            return {
                "status": "error",
                "merged": [],
                "count": 0,
                "error": error_msg
            }
