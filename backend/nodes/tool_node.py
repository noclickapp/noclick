"""
Tool node for workflow automation.

Defines tools that can be connected to AI Agent nodes, providing them with
callable capabilities. When the LLM calls a tool, execution flows to the
tool node's downstream nodes, which handle the actual implementation.
"""

import logging
import re
from typing import Dict, Any, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Tool Parameter Schema
# ============================================================================

class ToolParameter(BaseModel):
    """Definition of a single tool parameter."""
    name: str = Field(
        ...,
        min_length=1,
        pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$',
        title="Parameter Name",
        description="Name of the parameter (must be valid identifier)"
    )
    type: Literal['string', 'number', 'boolean', 'object', 'array'] = Field(
        default='string',
        title="Type",
        description="Data type of the parameter"
    )
    description: str = Field(
        default="",
        title="Description",
        description="Description shown to the LLM"
    )
    required: bool = Field(
        default=True,
        title="Required",
        description="Whether this parameter is required"
    )
    default: Optional[Any] = Field(
        default=None,
        title="Default Value",
        description="Default value if not provided"
    )


# ============================================================================
# Main Tool Configuration
# ============================================================================

class ToolConfig(BaseModel):
    """Configuration for a workflow tool definition."""
    tool_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$',
        title="Tool Name",
        description="Unique identifier for this tool (used in function calls)"
    )
    tool_description: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        title="Tool Description",
        description="Description shown to the LLM explaining what this tool does",
        json_schema_extra={"ui:widget": "textarea"}
    )
    parameters: List[ToolParameter] = Field(
        default_factory=list,
        title="Parameters",
        description="Parameters that the LLM can pass to this tool"
    )

    @field_validator('tool_name', mode='before')
    @classmethod
    def sanitize_tool_name(cls, v: str) -> str:
        """
        Sanitize tool name to be a valid identifier for LLM function calling.

        - Replaces spaces and hyphens with underscores
        - Removes other invalid characters
        - Ensures it starts with a letter or underscore
        """
        if not isinstance(v, str):
            return v

        # Replace spaces and hyphens with underscores
        sanitized = v.replace(' ', '_').replace('-', '_')

        # Remove any characters that aren't alphanumeric or underscore
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '', sanitized)

        # Collapse multiple underscores into one
        sanitized = re.sub(r'_+', '_', sanitized)

        # Strip trailing underscores only (not leading, as we may add one below)
        sanitized = sanitized.rstrip('_')

        # Strip leading underscores before checking if starts with digit
        sanitized = sanitized.lstrip('_')

        # Ensure it starts with a letter or underscore (not a number)
        if sanitized and sanitized[0].isdigit():
            sanitized = '_' + sanitized

        return sanitized if sanitized else v


class ToolNodeConfig(NodeConfig[ToolConfig, None]):
    """Full configuration for Tool node (no credentials needed)."""
    pass


# ============================================================================
# Tool Node Implementation
# ============================================================================

class ToolNode(WorkflowNode):
    """
    Tool definition node for workflow automation.

    This node defines the interface for a tool that AI agents can call.
    When the LLM decides to use this tool, the AgentNode executes the
    tool's downstream workflow nodes with the tool arguments as input.

    The tool node itself just provides:
    - Tool name (identifier for the LLM to call)
    - Tool description (explains what the tool does)
    - Parameters (what arguments the LLM can pass)

    The actual implementation is handled by whatever nodes are connected
    downstream from this tool node (e.g., HTTP Request, Database Query, etc.)
    """

    edit_examples = [
        "Rename tool to reflect its purpose",
        "Improve description to be more helpful to the LLM",
        "Add a required parameter",
        "Make an optional parameter required",
        "Add default value for optional parameter",
        "Change parameter type to array",
        "Add validation description to parameters",
    ]

    @classmethod
    def get_config_model(cls) -> type:
        """Get Pydantic config model for Tool node."""
        return ToolNodeConfig

    def get_tool_definition(self) -> ChatCompletionToolParam:
        """
        Convert this tool's configuration to LiteLLM's tool format.

        Returns:
            ChatCompletionToolParam ready to be passed to LLM
        """
        if not self.config or not isinstance(self.config, ToolNodeConfig):
            raise ValueError(f"Tool node {self.node_id} has no valid configuration")

        tool_config = self.config.config

        # Build parameter properties for JSON schema
        properties = {}
        required = []

        for param in tool_config.parameters:
            param_schema: Dict[str, Any] = {
                'type': param.type,
                'description': param.description or f"Parameter: {param.name}"
            }
            if param.default is not None:
                param_schema['default'] = param.default

            properties[param.name] = param_schema

            if param.required:
                required.append(param.name)

        return ChatCompletionToolParam(
            type='function',
            function=ChatCompletionToolParamFunctionChunk(
                name=tool_config.tool_name,
                description=tool_config.tool_description,
                parameters={
                    'type': 'object',
                    'properties': properties,
                    'required': required,
                }
            )
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute method for workflow traversal.

        Tool nodes don't execute in the traditional workflow sense.
        They provide their definition to be collected by AgentNodes.

        The 'workflow' tool_type indicates that when the LLM calls this tool,
        the agent should execute the tool's downstream nodes with the
        tool call arguments injected into the outputs.

        Returns:
            Dict containing the tool definition metadata
        """
        if not self.config or not isinstance(self.config, ToolNodeConfig):
            return {'error': 'Tool node has no valid configuration'}

        tool_config = self.config.config

        return {
            'type': 'tool_definition',
            'tool_type': 'workflow',  # Downstream nodes handle execution
            'tool_name': tool_config.tool_name,
            'tool_description': tool_config.tool_description,
            'parameters': [p.model_dump() for p in tool_config.parameters],
        }
