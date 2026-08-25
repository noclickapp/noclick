"""
Approval node for human-in-the-loop workflow execution.

When this node executes it creates a pending approval request in the database,
persists all accumulated node outputs, and stops workflow execution gracefully.
A human later approves or rejects via the Feed UI, which resumes execution
down the corresponding output handle ("approved" or "rejected").

The node config defines form fields (same shape as the form node's) whose values are
resolved at execution time. The approver sees a filled-out form they can edit
before deciding. Downstream nodes reference fields via {{nodeId.values.field}}.
"""

import json
import logging
from typing import Dict, Any, Optional, Type, List

from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig, OutputHandle
from nodes.core.suspend_strategy import SuspendingExecutionStrategy

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

class ApprovalField(BaseModel):
    """A field in the approval form. Like the form node's FormField but includes a value
    that can contain references (e.g. {{upstream.amount}}) resolved at runtime."""

    name: str = Field(
        ...,
        min_length=1,
        pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$',
        title="Field Name",
        description="Identifier used in references: {{nodeId.values.field_name}}",
    )
    type: str = Field(
        default="string",
        title="Type",
        description="Data type: string, number, boolean, select, media",
    )
    label: str = Field(default="", title="Label", description="Display label")
    description: str = Field(default="", title="Description", description="Help text")
    required: bool = Field(default=False, title="Required")
    options: Optional[List[str]] = Field(default=None, title="Options", description="For select/dropdown fields")
    value: str = Field(
        default="",
        title="Value",
        description="Pre-filled value. Supports references like {{node.field}}.",
    )


class ApprovalInnerConfig(BaseModel):
    """Configuration for the approval node."""

    title: str = Field(
        default="",
        title="Title",
        description="Short title shown in the approval feed card",
        json_schema_extra={"placeholder": "Review new campaign"},
    )

    fields: List[ApprovalField] = Field(
        default_factory=list,
        title="Form Fields",
        description="Fields shown in the approval card. Values can reference upstream nodes.",
        json_schema_extra={"ui:widget": "approval_fields"},
    )

class ApprovalNodeConfig(NodeConfig[ApprovalInnerConfig, None]):
    """Full configuration for approval node (no credentials needed)."""
    pass


# ============================================================================
# Node Implementation
# ============================================================================

class ApprovalNode(WorkflowNode):
    """
    Approval workflow node for human-in-the-loop branching.

    Creates a pending approval request and halts execution until a human
    approves or rejects. The ConditionalExecutionStrategy-like
    ApprovalExecutionStrategy handles routing to the correct branch.
    """

    IS_CONDITIONAL_NODE = True

    edit_examples = [
        "Add an approval field to show the computed total amount to reviewer",
        "Change title to \"Review campaign before posting\" for clarity",
        "Add a boolean confirmation field and set its value to {{email.status}}",
        "Update field description to guide approver on decision criteria",
        "Add textarea field for reviewer comments during approval decision",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return ApprovalNodeConfig

    @classmethod
    def get_output_handles(cls) -> Optional[List[OutputHandle]]:
        return [
            {"id": "approved", "label": "Approved", "description": "Executes when the request is approved"},
            {"id": "rejected", "label": "Rejected", "description": "Executes when the request is rejected"},
        ]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the approval node — resolves form field values and returns them.

        Field values come from the node's stored config (which may contain
        resolved references like {{upstream.field}} that the execution handler
        already substituted). The actual DB insertion and execution halt are
        handled by ApprovalExecutionStrategy.
        """
        logger.info(f"[ApprovalNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, ApprovalNodeConfig):
            raise ValueError(f"[ApprovalNode] Configuration required for node {self.node_id}")

        config = node_config.config

        # Build values from the field definitions. The execution handler has
        # already resolved references in field.value (e.g. "{{http.amount}}" → "150").
        values: Dict[str, Any] = {}
        for field in config.fields:
            if field.value not in (None, ""):
                values[field.name] = field.value
            elif field.type == "boolean":
                values[field.name] = False

        fields_schema = [f.model_dump(exclude={"value"}) for f in config.fields]

        output = {
            "status": "pending",
            "title": config.title,
            "values": values,
            "fields": fields_schema,
            "isConditionalNode": True,
            # output_handle will be set on resume by the feed handler
        }

        # Persist to approval_requests table. Capture the row id so we
        # can include it in the created event — the FE correlates
        # created → resolved by this id (see ApprovalRequestCreatedEvent).
        approval_id: Optional[str] = None
        if self.execution_id:
            try:
                import json as _json
                from utils.database_pool import get_native_pool
                new_id = await get_native_pool().fetchval("""
                    INSERT INTO approval_requests
                        (workflow_id, execution_id, node_id, user_id, organization_id, title, content)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                """,
                    self.workflow_id, self.execution_id, self.node_id,
                    self.user_id, self.organization_id,
                    config.title,
                    _json.dumps({"fields": fields_schema, "values": values}),
                )
                if new_id is not None:
                    approval_id = str(new_id)
            except Exception as e:
                logger.error(f"[ApprovalNode] Failed to create approval request: {e}")

        # Emit real-time socket event
        if self.sio and self.sid and approval_id:
            try:
                from wss.sender import send_event
                from wss.sender.events import ApprovalRequestCreatedEvent
                await send_event(self.sio, self.sid, ApprovalRequestCreatedEvent(
                    approval_id=approval_id,
                    workflow_id=self.workflow_id or "",
                    execution_id=self.execution_id or "",
                    node_id=self.node_id,
                    title=config.title,
                    fields=fields_schema,
                    values=values,
                ))
            except Exception as e:
                logger.warning(f"[ApprovalNode] Failed to emit approval event: {e}")

        await self.emit(output)
        return output


# ============================================================================
# Execution Strategy
# ============================================================================

class ApprovalExecutionStrategy(SuspendingExecutionStrategy):
    """
    Execution strategy for approval nodes.

    Inherits the generic suspend flow from SuspendingExecutionStrategy:
    executes the approval node (which creates the pending approval_requests
    row), marks ALL downstream nodes on both branches skipped, and sets the
    execution status to 'awaiting_approval'. A human later resumes via the
    Feed UI down the chosen output handle.
    """

    suspended_status = "awaiting_approval"

    def handles(self, node_type: str) -> bool:
        return node_type == "approval"
