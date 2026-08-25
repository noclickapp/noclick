"""
Filter node for data filtering and transformation in workflows.

The node is a discriminated union over `operation`: each operation is its own
config model exposing only the fields it needs, so the config UI never shows
irrelevant controls.

Operations:
    - filter_array:      Keep array items that match a condition
    - remove_duplicates: Remove duplicate items from an array
    - limit:             Limit an array to a number of items (with offset)
    - sort:              Sort array items
    - filter_object:     Keep or remove keys on an object

Usage Examples:
    1. Filter numbers greater than threshold:
       - operation: filter_array, operator: greater_than, filter_value: 25
       - [10, 20, 30, 40, 50] -> [30, 40, 50]

    2. Filter array of objects:
       - operation: filter_array, filter_field: age,
         operator: greater_than_or_equal, filter_value: 30
       - [{name: "Alice", age: 25}, {name: "Bob", age: 30}] -> [{name: "Bob", age: 30}]

    3. Remove duplicates:
       - operation: remove_duplicates
       - [1, 2, 2, 3, 3, 3] -> [1, 2, 3]

    4. Limit items:
       - operation: limit, limit: 3
       - [1, 2, 3, 4, 5] -> [1, 2, 3]
"""

import json
import logging
import re
from typing import Dict, Any, Optional, Type, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator, field_validator

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Filter Node Configuration
# ============================================================================

# Comparison operators. Defined as a Literal type alias so Pydantic inlines the
# enum into the JSON schema (a Python Enum would emit a `$ref`, which the config
# renderer can't surface as a dropdown).
FilterOperator = Literal[
    "equals", "not_equals", "contains", "not_contains",
    "starts_with", "ends_with", "greater_than", "greater_than_or_equal",
    "less_than", "less_than_or_equal", "is_empty", "is_not_empty",
    "regex_match", "in_list", "not_in_list",
]

# Human-readable labels for the operator dropdown — order matches FilterOperator.
_OPERATOR_LABELS = [
    "Equals", "Not equals", "Contains", "Does not contain",
    "Starts with", "Ends with", "Greater than", "Greater than or equal",
    "Less than", "Less than or equal", "Is empty", "Is not empty",
    "Regex match", "In list", "Not in list",
]

SortOrder = Literal["ascending", "descending"]


def _operation_field(value: str, display_name: str, category: str) -> Any:
    """Build the hidden discriminator field shared by every operation config."""
    return Field(
        default=value,
        title=display_name,
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": display_name,
            "x-category": category,
            "x-is-trigger": False,
        },
    )


def _input_data_field() -> Any:
    """Build the input-data field shared by every operation config."""
    return Field(
        ...,
        title="Input Data",
        description="Reference to the data to filter (e.g., {{sheets-1.values}} or {{agent-1.response.items}})",
        json_schema_extra={
            "placeholder": "{{node-id.field}}",
            "ui:widget": "textarea",
        },
    )


class FilterArrayConfig(BaseModel):
    """Keep array items that match a condition."""

    operation: Literal["filter_array"] = _operation_field(
        "filter_array", "Filter Array", "Array"
    )
    input_data: Any = _input_data_field()
    filter_field: Optional[str] = Field(
        default=None,
        title="Field to Filter",
        description="For arrays of objects, the field name to filter on (e.g., 'age', 'status'). Leave empty to filter direct values.",
        json_schema_extra={"placeholder": "field_name"},
    )
    operator: FilterOperator = Field(
        default="equals",
        title="Operator",
        description="Comparison operator for filtering",
        json_schema_extra={"x-enum-searchable": True, "enumNames": _OPERATOR_LABELS},
    )
    filter_value: Optional[str] = Field(
        default=None,
        title="Filter Value",
        description="Value to compare against. For 'In list' / 'Not in list', use a comma-separated list.",
        json_schema_extra={"placeholder": "value"},
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
        """Older filter nodes stored case_sensitive as a boolean."""
        if isinstance(v, bool):
            return "true" if v else "false"
        return v


class RemoveDuplicatesConfig(BaseModel):
    """Remove duplicate items from an array."""

    operation: Literal["remove_duplicates"] = _operation_field(
        "remove_duplicates", "Remove Duplicates", "Array"
    )
    input_data: Any = _input_data_field()
    dedupe_field: Optional[str] = Field(
        default=None,
        title="Deduplication Field",
        description="For arrays of objects, the field to dedupe on. Leave empty to dedupe whole items.",
        json_schema_extra={"placeholder": "field_name"},
    )


class LimitConfig(BaseModel):
    """Limit an array to a number of items."""

    operation: Literal["limit"] = _operation_field("limit", "Limit", "Array")
    input_data: Any = _input_data_field()
    limit: int = Field(
        default=10,
        ge=1,
        title="Limit",
        description="Maximum number of items to return",
    )
    offset: int = Field(
        default=0,
        ge=0,
        title="Offset",
        description="Number of items to skip before applying the limit (for pagination)",
    )

    @field_validator("limit", mode="before")
    @classmethod
    def _coerce_limit(cls, v: Any) -> Any:
        """Older filter nodes could store limit as null before it was required."""
        return 10 if v is None else v


class SortConfig(BaseModel):
    """Sort array items."""

    operation: Literal["sort"] = _operation_field("sort", "Sort", "Array")
    input_data: Any = _input_data_field()
    sort_field: Optional[str] = Field(
        default=None,
        title="Sort Field",
        description="Field to sort by. Leave empty to sort direct values.",
        json_schema_extra={"placeholder": "field_name"},
    )
    sort_order: SortOrder = Field(
        default="ascending",
        title="Sort Order",
        description="Sort direction",
        json_schema_extra={"enumNames": ["Ascending", "Descending"]},
    )


class FilterObjectConfig(BaseModel):
    """Keep or remove keys on an object."""

    operation: Literal["filter_object"] = _operation_field(
        "filter_object", "Filter Object", "Object"
    )
    input_data: Any = _input_data_field()
    keep_keys: Optional[str] = Field(
        default=None,
        title="Keys to Keep",
        description="Comma-separated keys to keep (e.g., 'name,email,age'). Takes priority over Keys to Remove.",
        json_schema_extra={"placeholder": "key1,key2,key3"},
    )
    remove_keys: Optional[str] = Field(
        default=None,
        title="Keys to Remove",
        description="Comma-separated keys to remove (e.g., 'password,internal_id')",
        json_schema_extra={"placeholder": "key1,key2,key3"},
    )


class GroupByFieldConfig(BaseModel):
    """Group array items into buckets by a field value."""

    operation: Literal["group_by_field"] = _operation_field(
        "group_by_field", "Group by Field", "Array"
    )
    input_data: Any = _input_data_field()
    group_by_field: Optional[str] = Field(
        default=None,
        title="Group By Field",
        description="Field to group items by (e.g., 'category', 'status')",
        json_schema_extra={"placeholder": "field_name"},
    )


class SplitStringConfig(BaseModel):
    """Split a string into an array by a delimiter."""

    operation: Literal["split_string"] = _operation_field(
        "split_string", "Split String", "Text"
    )
    input_data: Any = _input_data_field()
    delimiter: str = Field(
        default=",",
        title="Delimiter",
        description="Character(s) to split the string by",
        json_schema_extra={"placeholder": ","},
    )
    trim_whitespace: Literal["false", "true"] = Field(
        default="true",
        title="Trim Whitespace",
        description="Remove leading/trailing whitespace from each part",
        json_schema_extra={"enumNames": ["No", "Yes"]},
    )

    @field_validator("trim_whitespace", mode="before")
    @classmethod
    def _coerce_trim_whitespace(cls, v: Any) -> Any:
        """Accept a legacy boolean value."""
        if isinstance(v, bool):
            return "true" if v else "false"
        return v


FilterConfig = Annotated[
    Union[
        FilterArrayConfig,
        RemoveDuplicatesConfig,
        LimitConfig,
        SortConfig,
        FilterObjectConfig,
        GroupByFieldConfig,
        SplitStringConfig,
    ],
    Discriminator("operation"),
]


class FilterNodeConfig(NodeConfig[FilterConfig, None]):
    """Full configuration for filter node (no credentials needed)."""

    pass


# ============================================================================
# Filter Node Implementation
# ============================================================================

class FilterNode(WorkflowNode):
    """
    Filter workflow node for data filtering and transformation.

    Dispatches on the operation config variant: filter_array, remove_duplicates,
    limit, sort, filter_object, group_by_field, split_string.
    """

    edit_examples = [
        "Filter rows where status equals 'active'",
        "Remove duplicate records by email address",
        "Sort results by date in descending order",
        "Limit results to the first 100 items",
        "Find items containing a specific keyword",
        "Extract only name and email fields from objects",
        "Filter numbers greater than a threshold value",
        "Group records by their status field",
        "Split a comma-separated string into a list",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        """Get Pydantic config model for filter node."""
        return FilterNodeConfig

    def _parse_value(self, value_str: str) -> Any:
        """Parse a filter value string into str, int, float, bool, or list."""
        if not value_str:
            return value_str

        # Try boolean
        if value_str.lower() in ('true', 'false'):
            return value_str.lower() == 'true'

        # Try number
        try:
            if '.' in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            pass

        # Try list (comma-separated)
        if ',' in value_str:
            return [v.strip() for v in value_str.split(',')]

        # Return as string
        return value_str

    def _compare_values(
        self,
        item_value: Any,
        filter_value: Any,
        operator: str,
        case_sensitive: bool,
    ) -> bool:
        """Compare two values based on operator."""
        # Handle empty checks
        if operator == "is_empty":
            return item_value is None or item_value == "" or (isinstance(item_value, (list, dict)) and len(item_value) == 0)

        if operator == "is_not_empty":
            return not (item_value is None or item_value == "" or (isinstance(item_value, (list, dict)) and len(item_value) == 0))

        # String operations
        if operator in ("contains", "not_contains", "starts_with", "ends_with"):
            item_str = str(item_value) if item_value is not None else ""
            filter_str = str(filter_value) if filter_value is not None else ""

            if not case_sensitive:
                item_str = item_str.lower()
                filter_str = filter_str.lower()

            if operator == "contains":
                return filter_str in item_str
            elif operator == "not_contains":
                return filter_str not in item_str
            elif operator == "starts_with":
                return item_str.startswith(filter_str)
            elif operator == "ends_with":
                return item_str.endswith(filter_str)

        # Regex match
        if operator == "regex_match":
            try:
                pattern = str(filter_value)
                flags = 0 if case_sensitive else re.IGNORECASE
                return bool(re.search(pattern, str(item_value), flags))
            except re.error as e:
                logger.error(f"Invalid regex pattern: {filter_value}")
                raise ValueError(f"Invalid regex pattern '{filter_value}': {str(e)}")

        # List operations
        if operator == "in_list":
            if not isinstance(filter_value, list):
                filter_value = [filter_value]
            return item_value in filter_value

        if operator == "not_in_list":
            if not isinstance(filter_value, list):
                filter_value = [filter_value]
            return item_value not in filter_value

        # Equality checks
        if operator == "equals":
            if not case_sensitive and isinstance(item_value, str) and isinstance(filter_value, str):
                return item_value.lower() == filter_value.lower()
            return item_value == filter_value

        if operator == "not_equals":
            if not case_sensitive and isinstance(item_value, str) and isinstance(filter_value, str):
                return item_value.lower() != filter_value.lower()
            return item_value != filter_value

        # Numeric comparisons
        try:
            item_num = float(item_value) if item_value is not None else 0
            filter_num = float(filter_value) if filter_value is not None else 0

            if operator == "greater_than":
                return item_num > filter_num
            elif operator == "greater_than_or_equal":
                return item_num >= filter_num
            elif operator == "less_than":
                return item_num < filter_num
            elif operator == "less_than_or_equal":
                return item_num <= filter_num
        except (ValueError, TypeError):
            return False

        return False

    def _filter_array(
        self,
        data: List[Any],
        field: Optional[str],
        operator: str,
        value: Any,
        case_sensitive: bool,
    ) -> List[Any]:
        """Filter array based on conditions."""
        if not isinstance(data, list):
            raise ValueError(f"filter_array requires array input, got {type(data).__name__}")

        result = []
        for item in data:
            # Get value to compare
            if field:
                # Array of objects - get field value
                if isinstance(item, dict):
                    item_value = item.get(field)
                else:
                    logger.warning(f"Item is not an object, cannot get field '{field}'")
                    continue
            else:
                # Direct value comparison
                item_value = item

            # Apply filter
            if self._compare_values(item_value, value, operator, case_sensitive):
                result.append(item)

        return result

    def _remove_duplicates(self, data: List[Any], field: Optional[str] = None) -> List[Any]:
        """Remove duplicate items from array."""
        if not isinstance(data, list):
            raise ValueError(f"remove_duplicates requires array input, got {type(data).__name__}")

        seen = set()
        result = []

        for item in data:
            # Determine key for deduplication
            if field and isinstance(item, dict):
                key = item.get(field)
            else:
                # For unhashable types (dict, list), convert to JSON string
                if isinstance(item, (dict, list)):
                    key = json.dumps(item, sort_keys=True)
                else:
                    key = item

            if key not in seen:
                seen.add(key)
                result.append(item)

        return result

    def _limit_items(self, data: List[Any], limit: int, offset: int = 0) -> List[Any]:
        """Limit number of items with optional offset."""
        if not isinstance(data, list):
            raise ValueError(f"limit requires array input, got {type(data).__name__}")

        return data[offset:offset + limit]

    def _sort_array(
        self,
        data: List[Any],
        field: Optional[str],
        order: str,
    ) -> List[Any]:
        """Sort array items."""
        if not isinstance(data, list):
            raise ValueError(f"sort requires array input, got {type(data).__name__}")

        reverse = (order == "descending")

        try:
            if field:
                # Sort by field value
                sorted_data = sorted(
                    data,
                    key=lambda x: x.get(field) if isinstance(x, dict) else None,
                    reverse=reverse,
                )
            else:
                # Sort direct values
                sorted_data = sorted(data, reverse=reverse)

            return sorted_data
        except TypeError as e:
            logger.warning(f"Could not sort array: {e}")
            return data

    def _filter_object(
        self,
        data: Dict[str, Any],
        keep_keys: Optional[List[str]],
        remove_keys: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Filter object properties."""
        if not isinstance(data, dict):
            raise ValueError(f"filter_object requires object input, got {type(data).__name__}")

        result = dict(data)

        # If keep_keys specified, only keep those keys
        if keep_keys:
            result = {k: v for k, v in result.items() if k in keep_keys}

        # If remove_keys specified, remove those keys
        if remove_keys:
            for key in remove_keys:
                result.pop(key, None)

        return result

    def _group_by_field(self, data: List[Any], group_by_field: Optional[str]) -> Dict[str, List[Any]]:
        """Group array items into buckets keyed by a field value."""
        if not isinstance(data, list):
            raise ValueError(f"group_by_field requires array input, got {type(data).__name__}")
        if not group_by_field:
            raise ValueError("group_by_field is required for the Group by Field operation")

        groups: Dict[str, List[Any]] = {}
        for item in data:
            if isinstance(item, dict):
                key = str(item.get(group_by_field, 'undefined'))
            else:
                key = 'undefined'
            groups.setdefault(key, []).append(item)

        return groups

    def _split_string(self, data: Any, delimiter: str, trim_whitespace: bool) -> List[str]:
        """Split a string into an array by a delimiter."""
        if not isinstance(data, str):
            # Try to extract a string value from common fields
            if isinstance(data, dict):
                for field in ['text', 'value', 'content', 'message', 'body']:
                    if field in data and isinstance(data[field], str):
                        data = data[field]
                        break
                else:
                    data = str(data)
            else:
                data = str(data)

        parts = data.split(delimiter)
        if trim_whitespace:
            parts = [p.strip() for p in parts]
        # Drop empty strings
        return [p for p in parts if p]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the filter node.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing filtered data with 'status' field
        """
        logger.info(f"[FilterNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, FilterNodeConfig):
            return {"status": "no_config", "filtered": [], "count": 0, "error": "Configuration required"}

        config = node_config.config

        try:
            # Get input data (should be resolved by handler)
            input_data = config.input_data

            # Parse input if it's still a string reference
            if isinstance(input_data, str):
                if input_data.startswith('{{') and input_data.endswith('}}'):
                    return {
                        "status": "error",
                        "filtered": [],
                        "count": 0,
                        "error": f"Input data reference '{input_data}' was not resolved. "
                                "Make sure the upstream node has executed and the path is correct.",
                    }
                try:
                    input_data = json.loads(input_data)
                except json.JSONDecodeError as e:
                    # split_string operates on the raw string; every other
                    # operation needs structured (JSON) input.
                    if not isinstance(config, SplitStringConfig):
                        return {
                            "status": "error",
                            "filtered": [],
                            "count": 0,
                            "error": f"Invalid JSON input: {str(e)}",
                        }

            # Dispatch on the operation config variant
            if isinstance(config, FilterArrayConfig):
                parsed_value = self._parse_value(config.filter_value) if config.filter_value else None
                filtered_data = self._filter_array(
                    input_data,
                    config.filter_field,
                    config.operator,
                    parsed_value,
                    config.case_sensitive == "true",
                )
                output = {
                    'status': 'success',
                    'filtered': filtered_data,
                    'count': len(filtered_data),
                    'original_count': len(input_data) if isinstance(input_data, list) else 0,
                    'operation': 'filter_array',
                }

            elif isinstance(config, RemoveDuplicatesConfig):
                deduplicated = self._remove_duplicates(input_data, config.dedupe_field)
                output = {
                    'status': 'success',
                    'filtered': deduplicated,
                    'count': len(deduplicated),
                    'original_count': len(input_data) if isinstance(input_data, list) else 0,
                    'duplicates_removed': (len(input_data) - len(deduplicated)) if isinstance(input_data, list) else 0,
                    'operation': 'remove_duplicates',
                }

            elif isinstance(config, LimitConfig):
                limited = self._limit_items(input_data, config.limit, config.offset)
                output = {
                    'status': 'success',
                    'filtered': limited,
                    'count': len(limited),
                    'original_count': len(input_data) if isinstance(input_data, list) else 0,
                    'limit': config.limit,
                    'offset': config.offset,
                    'operation': 'limit',
                }

            elif isinstance(config, SortConfig):
                sorted_data = self._sort_array(input_data, config.sort_field, config.sort_order)
                output = {
                    'status': 'success',
                    'filtered': sorted_data,
                    'count': len(sorted_data),
                    'sort_field': config.sort_field,
                    'sort_order': config.sort_order,
                    'operation': 'sort',
                }

            elif isinstance(config, FilterObjectConfig):
                keep_keys = [k.strip() for k in config.keep_keys.split(',')] if config.keep_keys else None
                remove_keys = [k.strip() for k in config.remove_keys.split(',')] if config.remove_keys else None

                filtered_obj = self._filter_object(input_data, keep_keys, remove_keys)
                output = {
                    'status': 'success',
                    'filtered': filtered_obj,
                    'keys_count': len(filtered_obj),
                    'original_keys_count': len(input_data) if isinstance(input_data, dict) else 0,
                    'operation': 'filter_object',
                }

            elif isinstance(config, GroupByFieldConfig):
                groups = self._group_by_field(input_data, config.group_by_field)
                output = {
                    'status': 'success',
                    'filtered': groups,
                    'count': len(groups),
                    'total_items': sum(len(items) for items in groups.values()),
                    'group_names': list(groups.keys()),
                    'operation': 'group_by_field',
                }

            elif isinstance(config, SplitStringConfig):
                parts = self._split_string(
                    input_data,
                    config.delimiter or ",",
                    config.trim_whitespace == "true",
                )
                output = {
                    'status': 'success',
                    'filtered': parts,
                    'count': len(parts),
                    'delimiter': config.delimiter,
                    'operation': 'split_string',
                }

            else:
                return {"status": "error", "filtered": [], "count": 0, "error": f"Unknown configuration type: {type(config).__name__}"}

            logger.info(f"[FilterNode] Operation '{output['operation']}' completed: {output.get('count', output.get('keys_count', 0))} items")

            await self.emit(output)
            return output

        except ValueError as e:
            error_msg = str(e)
            logger.error(f"[FilterNode] ValueError: {error_msg}")

            # Type mismatch errors carry a tailored response
            if "requires object input" in error_msg:
                return {
                    "status": "error",
                    "filtered": {},
                    "error": f"Input must be an object, got {error_msg.split('got ')[-1] if 'got ' in error_msg else 'invalid type'}",
                }
            return {
                "status": "error",
                "filtered": [],
                "count": 0,
                "error": error_msg,
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[FilterNode] Unexpected error: {error_msg}")
            return {
                "status": "error",
                "filtered": [],
                "count": 0,
                "error": f"Unexpected error: {error_msg}",
            }
