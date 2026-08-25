# Set Variable node — stores one or more values as named global variables.
# Variables become available as {{vars.variable_name}} throughout the workflow.
# Typically used in setup subgraphs to persist form values or computed outputs.

import json
import logging
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel, Field, field_validator

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


class VariableAssignment(BaseModel):
    variable_name: str = Field(default="", title="Variable Name")
    value: str = Field(default="", title="Value")

    @field_validator('value', 'variable_name', mode='before')
    @classmethod
    def coerce_none_to_str(cls, v: object) -> str:
        return "" if v is None else v


class SetVariableConfigModel(BaseModel):
    assignments: List[VariableAssignment] = Field(
        default_factory=lambda: [VariableAssignment()],
        title="Variables",
        json_schema_extra={"ui:widget": "variable_assignments"},
    )

    @field_validator('assignments', mode='before')
    @classmethod
    def parse_assignments_json(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v


class SetVariableNodeConfig(NodeConfig[SetVariableConfigModel, None]):
    """Full configuration for set variable node (no credentials)."""
    pass


class SetVariableNode(WorkflowNode):
    """
    Set Variable node — stores values as named global variables.

    Takes a list of variable assignments (name + value pairs) and returns them
    for the execution handlers to persist as workflow-level variables accessible
    via {{vars.name}}.
    """

    edit_examples = [
        "Add a new variable for user_id and set it to {{trigger.user_id}}",
        "Change total_amount value to {{calc.result}} instead of static number",
        "Add three more variables: api_key, retry_count, and last_run_time",
        "Update campaign_name variable to reference {{form.campaign_field}}",
        "Remove unused variables and keep only frequently referenced ones",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return SetVariableNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config.config

        # Backward compat: legacy configs have flat variable_name + value instead of assignments
        if isinstance(config, dict):
            if 'assignments' not in config and 'variable_name' in config:
                return {
                    "assignments": [{
                        "variable_name": config.get("variable_name", ""),
                        "value": config.get("value", ""),
                    }]
                }
            raw_assignments = config.get('assignments', [])
        else:
            raw_assignments = config.assignments

        assignments = []
        for a in raw_assignments:
            if isinstance(a, dict):
                assignments.append({
                    "variable_name": a.get("variable_name", ""),
                    "value": a.get("value", ""),
                })
            else:
                assignments.append({
                    "variable_name": a.variable_name,
                    "value": a.value,
                })

        return {"assignments": assignments}
