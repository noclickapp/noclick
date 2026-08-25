# Split Out node — turn an array (or an array field on an object) into one
# output item per element. Each item keeps the split field's name
# (or a Destination Field), and can carry the other fields. Pair with the
# Iteration node to then process each item.

import json
import logging
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from typing import Literal

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


class SplitOutConfigModel(BaseModel):
    input_data: Any = Field(
        ...,
        title="Input Data",
        description="The data to split — an array, or an object that contains the array field(s). e.g. {{node-id.items}}",
        json_schema_extra={"placeholder": "{{node-id.field}}", "ui:widget": "textarea"},
    )
    fields_to_split: str = Field(
        default="",
        title="Fields To Split Out",
        description="The field(s) holding the array to split out. Comma-separate to split multiple; dot notation supported. Leave empty if the input is itself an array.",
        json_schema_extra={"placeholder": "items"},
    )
    include: Literal["none", "all", "selected"] = Field(
        default="none",
        title="Include",
        description="Which of the input's other fields to keep on each output item.",
        json_schema_extra={
            "x-enum-searchable": True,
            "enumNames": ["No Other Fields", "All Other Fields", "Selected Other Fields"],
        },
    )
    fields_to_include: Optional[str] = Field(
        default=None,
        title="Fields To Include",
        description="Comma-separated field names to keep on each item.",
        json_schema_extra={
            "placeholder": "id,name",
            "ui:show-if": {"field": "include", "containsAny": ["selected"]},
        },
    )
    destination_field: Optional[str] = Field(
        default=None,
        title="Destination Field Name",
        description="Rename the split field on each output item (single field only).",
        json_schema_extra={"placeholder": "item"},
    )


class SplitOutNodeConfig(NodeConfig[SplitOutConfigModel, None]):
    """Full configuration for the Split Out node (no credentials)."""

    pass


class SplitOutNode(WorkflowNode):
    """Split an array into one item per element."""

    edit_examples = [
        "Split the items array into one item per element",
        "Split out the orders field and keep the customer id on each item",
        "Turn a list of tags into separate items",
        "Split out results, carrying all the other fields",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return SplitOutNodeConfig

    @staticmethod
    def _get_by_path(obj: Any, path: str) -> Any:
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    def _split_out(
        self,
        data: Any,
        fields: List[str],
        include: str,
        fields_to_include: Optional[str],
        destination: str,
    ) -> List[Dict[str, Any]]:
        """One item per array element. The split field's name (or a destination
        name) holds each element. Multiple fields zip by index.
        Fails loud when there's no array to split (no silent coercion)."""
        # No field name → the input must itself be the array.
        if not fields:
            if not isinstance(data, list):
                raise ValueError(
                    "Split Out needs an array. Either reference an array directly or set "
                    f"'Fields To Split Out'. Got {type(data).__name__}."
                )
            items: List[Dict[str, Any]] = []
            for elem in data:
                if isinstance(elem, dict) and not destination:
                    items.append(dict(elem))
                else:
                    items.append({(destination or "item"): elem})
            return items

        if not isinstance(data, dict):
            raise ValueError(
                f"Split Out with field names needs an object input; got {type(data).__name__}."
            )

        arrays: Dict[str, list] = {}
        for field in fields:
            arr = self._get_by_path(data, field)
            if not isinstance(arr, list):
                raise ValueError(
                    f"Field '{field}' is not an array (got {type(arr).__name__}). "
                    "Split Out needs an array to split."
                )
            arrays[field] = arr

        carried: Dict[str, Any] = {}
        if include == "all":
            roots = {f.split(".")[0] for f in fields}
            carried = {k: v for k, v in data.items() if k not in roots}
        elif include == "selected" and fields_to_include:
            for name in (n.strip() for n in fields_to_include.split(",")):
                if name:
                    value = self._get_by_path(data, name)
                    if value is not None:
                        carried[name] = value

        single = len(fields) == 1
        length = max((len(a) for a in arrays.values()), default=0)
        items = []
        for i in range(length):
            item = dict(carried)
            for field in fields:
                key = destination if (destination and single) else field.split(".")[-1]
                arr = arrays[field]
                if i < len(arr):
                    item[key] = arr[i]
            items.append(item)
        return items

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[SplitOutNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, SplitOutNodeConfig):
            return {"status": "no_config", "items": [], "count": 0, "error": "Configuration required"}

        config = node_config.config
        data = config.input_data

        # The handler resolves {{refs}}; a leftover string is parsed as JSON.
        if isinstance(data, str):
            if data.startswith("{{") and data.endswith("}}"):
                return {
                    "status": "error",
                    "items": [],
                    "count": 0,
                    "error": f"Input data reference '{data}' was not resolved. "
                    "Make sure the upstream node has executed and the path is correct.",
                }
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                return {"status": "error", "items": [], "count": 0, "error": f"Invalid JSON input: {e}"}

        fields = [f.strip() for f in (config.fields_to_split or "").split(",") if f.strip()]

        try:
            items = self._split_out(
                data,
                fields,
                config.include,
                config.fields_to_include,
                (config.destination_field or "").strip(),
            )
        except ValueError as e:
            logger.error(f"[SplitOutNode] {e}")
            return {"status": "error", "items": [], "count": 0, "error": str(e)}

        output = {"status": "success", "items": items, "count": len(items)}
        await self.emit(output)
        return output
