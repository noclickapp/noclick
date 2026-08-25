"""
Pydantic models for workflow generation input/output.

These models define the contract between the workflow builder and the frontend,
ensuring type safety and consistent data structures across the system.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Input Models
# ============================================================================

class BuilderInput(BaseModel):
    """
    Input to a workflow builder.

    This is the standard input format for all workflow builders,
    regardless of the underlying generation strategy.
    """
    prompt: str = Field(
        ...,
        description="Natural language description of the desired workflow",
        min_length=1,
    )
    generation_id: Optional[str] = Field(
        default=None,
        description="Unique ID for this generation session (auto-generated if not provided)",
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional additional context for generation (e.g., available credentials)",
    )


# ============================================================================
# Output Models - Nodes
# ============================================================================

class NodeStatus(str, Enum):
    """Status of a node during and after generation."""
    PENDING = "pending"
    ADDING = "adding"
    EDITING = "editing"
    COMPLETE = "complete"
    ERROR = "error"


class GeneratedNode(BaseModel):
    """
    A node in the generated workflow.

    This model represents the final output format that the frontend expects
    for rendering nodes in the workflow visualization.
    """
    id: str = Field(..., description="Unique identifier for the node")
    type: str = Field(..., description="Node type (e.g., 'automation-slack', 'trigger-webhook')")
    label: str = Field(..., description="Human-readable label for display")
    goal: str = Field(default="", description="What this node should accomplish")
    description: str = Field(default="", description="Detailed description of the node")

    # Graph position
    level: int = Field(default=0, description="Vertical level in the graph (0 = triggers)")
    index: int = Field(default=0, description="Horizontal index at this level")
    parent_ids: List[str] = Field(default_factory=list, alias="parentIds")

    # Operation (filled in node drafter)
    operation: Optional[str] = Field(default=None, description="Selected operation for this node")
    operation_reason: Optional[str] = Field(
        default=None,
        alias="operationReason",
        description="Why this operation was selected",
    )

    # Configuration (filled in node drafter)
    config: Dict[str, Any] = Field(default_factory=dict, description="Node configuration")
    user_fields: List[str] = Field(
        default_factory=list,
        alias="userFields",
        description="Fields that require user input",
    )

    # UI state
    status: NodeStatus = Field(default=NodeStatus.PENDING, description="Current status")
    content: str = Field(default="", description="Display content for the node")

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)


# ============================================================================
# Output Models - Edges
# ============================================================================

class EdgeStatus(str, Enum):
    """Status of an edge during and after generation."""
    PENDING = "pending"
    ANIMATING = "animating"
    COMPLETE = "complete"


class GeneratedEdge(BaseModel):
    """
    An edge (connection) in the generated workflow.
    """
    id: str = Field(..., description="Unique identifier for the edge")
    source_id: str = Field(..., alias="sourceId", description="ID of the source node")
    target_id: str = Field(..., alias="targetId", description="ID of the target node")
    status: EdgeStatus = Field(default=EdgeStatus.PENDING, description="Current status")

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)


# ============================================================================
# Output Models - Inputs
# ============================================================================

class InputType(str, Enum):
    """Type of user input required."""
    CREDENTIAL = "credential"
    TEXT = "text"
    SELECTION = "selection"
    # Field-bound <ask> targeting a node config field. The frontend introspects
    # the field's JSON schema and renders the appropriate widget (live picker,
    # enum select, text input). See docstring on <ask> in agentic/prompts.py.
    CONFIG = "config"


class GeneratedInput(BaseModel):
    """
    A request for user input (credentials, selections, etc.).
    """
    id: str = Field(..., description="Unique identifier for the input request")
    node_id: str = Field(..., alias="nodeId", description="ID of the node requiring this input")
    type: InputType = Field(..., description="Type of input required")
    label: str = Field(..., description="Human-readable label")
    description: str = Field(default="", description="Detailed description")
    credential_type: Optional[str] = Field(
        default=None,
        alias="credentialType",
        description="For credential inputs, the service type (e.g., 'slack', 'github')",
    )
    required: bool = Field(default=True, description="Whether this input is required")

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)


# ============================================================================
# Output Models - Complete Result
# ============================================================================

class BuilderOutput(BaseModel):
    """
    Complete output from a workflow builder.

    This is the final result format that contains all generated nodes, edges,
    and input requests, along with metadata about the generation.
    """
    nodes: List[GeneratedNode] = Field(
        default_factory=list,
        description="All nodes in the workflow",
    )
    edges: List[GeneratedEdge] = Field(
        default_factory=list,
        description="All edges connecting nodes",
    )
    inputs: List[GeneratedInput] = Field(
        default_factory=list,
        description="Required user inputs",
    )
    summary: str = Field(
        default="",
        description="Brief description of the generated workflow",
    )
    errors: Optional[List[str]] = Field(
        default=None,
        description="Any errors that occurred during generation",
    )
    generation_id: str = Field(
        default="",
        description="Unique ID for this generation session",
    )


# ============================================================================
# Event Models
# ============================================================================

BuilderEventType = Literal[
    # Graph structure events
    "node_start",
    "node_complete",
    "edge_add",
    "edge_complete",
    "input_request",
    # Processing events
    "node_processing_start",
    "node_operation_selected",
    "node_config_filling",
    "node_updated",
    # Mutation events
    "node_added",
    "node_removed",
    "edge_added",
    "edge_removed",
    # Completion events
    "generation_complete",
    "error",
]


class BuilderEvent(BaseModel):
    """
    Event emitted during workflow generation.

    These events enable real-time UI updates as the workflow is being generated.
    """
    type: BuilderEventType = Field(..., description="Type of event")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
