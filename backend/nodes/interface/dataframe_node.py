# Interface dataframe node for displaying tabular data in the workflow interface.
# Renders upstream data as a table, or uses configured JSON data as fallback.
# Supports referencing persisted dataset resources for cross-node/cross-workflow data sharing.

import json
import logging
from typing import Dict, Any, List, Optional, Type, Union
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


class DataframeConfig(BaseModel):
    """Configuration for the dataframe interface component."""

    resource_id: str = Field(
        default="", title="Dataset",
        description="Select an existing dataset resource to display",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "resource_id",
                "placeholder": "Select a dataset...",
                "searchable": True,
                "allow_custom": False,
            }
        })

    data: Union[str, List[Any], Dict[str, Any]] = Field(
        default="", title="Data",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6,
                           "ui:placeholder": '[{"name": "Alice", "age": 30}]'})


class DataframeInterfaceNodeConfig(NodeConfig[DataframeConfig, None]):
    """Full configuration for dataframe interface node (no credentials)."""
    pass


class DataframeInterfaceNode(WorkflowNode):
    """Dataframe interface node — displays tabular data."""

    grid_layout = {"defaultW": 6, "defaultH": 4, "minW": 4, "minH": 3}
    edit_examples = [
        "Display a persisted dataset resource as a table",
        "Show data from an upstream node as a table",
        "Load JSON array inline and display as table",
        "Increase the table height to show more rows",
        "Switch to a different dataset resource",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return DataframeInterfaceNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """Load available dataset resources for the resource_id picker."""
        if field_name != "resource_id":
            return {"options": [], "next_page_token": None}

        user_id = (context or {}).get("_user_id")
        if not user_id:
            return {"options": [], "next_page_token": None}

        from utils.database_pool import get_native_pool

        rows = await get_native_pool().fetch("""
            SELECT wr.id, wr.name, wr.workflow_id, w.name AS workflow_name,
                   wr.metadata
            FROM workflow_resources wr
            JOIN workflows w ON w.id = wr.workflow_id
            WHERE wr.resource_type = 'dataset'
              AND (
                  wr.workflow_id IN (SELECT id FROM workflows WHERE owner_id = $1)
                  OR wr.workflow_id IN (
                      SELECT rs.resource_id::uuid FROM resource_shares rs
                      LEFT JOIN organization_members om ON rs.target_org_id = om.organization_id
                      WHERE rs.resource_type = 'workflow'
                        AND (
                            (rs.target_type = 'user' AND rs.target_user_id = $1)
                            OR (rs.target_type = 'organization' AND om.user_id = $1)
                        )
                  )
              )
            ORDER BY wr.updated_at DESC
            LIMIT 50
        """, user_id)

        options = []
        for r in rows:
            row_count = (r["metadata"] or {}).get("row_count", "?")
            label = f"{r['name']} ({row_count} rows) \u2014 {r['workflow_name']}"
            options.append({"value": str(r["id"]), "label": label})

        return {"options": options, "next_page_token": None}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config: DataframeConfig = self._config.config if self._config else DataframeConfig()

        # If resource_id is set, load data from the persisted dataset
        if config.resource_id:
            from utils.database_pool import get_native_pool
            # Dataset pickers intentionally support resources from other
            # workflows the executing user can view. Reapply that access
            # boundary here: a UUID alone must never disclose dataset rows.
            rows = await get_native_pool().fetch(
                """
                SELECT dr.data
                FROM dataset_rows dr
                JOIN workflow_resources wr ON wr.id = dr.resource_id
                WHERE dr.resource_id = $1
                  AND wr.resource_type = 'dataset'
                  AND (
                      wr.workflow_id = $2
                      OR (
                          $3::uuid IS NOT NULL
                          AND (
                              wr.workflow_id IN (
                                  SELECT id FROM workflows WHERE owner_id = $3
                              )
                              OR wr.workflow_id IN (
                                  SELECT rs.resource_id::uuid
                                  FROM resource_shares rs
                                  LEFT JOIN organization_members om
                                    ON rs.target_org_id = om.organization_id
                                  WHERE rs.resource_type = 'workflow'
                                    AND (
                                        (rs.target_type = 'user'
                                         AND rs.target_user_id = $3)
                                        OR (rs.target_type = 'organization'
                                            AND om.user_id = $3)
                                    )
                              )
                          )
                      )
                  )
                ORDER BY dr.row_index
                LIMIT 10000
                """,
                config.resource_id,
                self.workflow_id,
                self.user_id,
            )
            data = [r["data"] for r in rows]
        else:
            # Fallback: use upstream input or inline configured data
            data = inputs.get("value", inputs.get("data", config.data))
            # Parse JSON strings into native lists/dicts for the frontend
            if isinstance(data, str) and data.strip():
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    pass

        output = {"data": data, "type": "dataframe"}
        await self.emit(output)
        return output
