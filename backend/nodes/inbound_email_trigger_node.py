"""
Inbound-email trigger node implementation.

Entry point for workflows triggered by inbound email. The user reserves a
custom address on the configured inbound domain; mail is received by the
operator's email worker, POSTed to the backend inbound-email route, and injected
as the trigger node's output (from/to/subject/body/attachments) for downstream
nodes.

Address lifecycle is managed by EmailReservationManager:
- Reserved via the email:reserve_address socket event when the user picks a name
- Released when the node is removed (workflow update cleanup + cleanup hook)
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Inbound Email Trigger Node Configuration Model
# ============================================================================

class InboundEmailTriggerConfig(BaseModel):
    """Configuration for the inbound-email trigger node."""
    local_part: str = Field(
        ...,
        title="Email Address",
        description="Choose an inbox name. Email sent to this address triggers the workflow.",
        # Required: the node is invalid until an address is reserved.
        # ui:widget="email_trigger" renders the editable local-part input with a
        # live availability check and the reserved-address display + copy button.
        json_schema_extra={"ui:widget": "email_trigger", "ui:copyable": True},
    )
    email_address: Optional[str] = Field(
        default=None,
        title="Full Address",
        description="The full reserved email address (auto-generated).",
        json_schema_extra={"ui:hidden": True},
    )
    reservation_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    allowed_senders: Optional[str] = Field(
        default=None,
        title="Allowed Senders (optional)",
        description=(
            "Comma-separated email addresses or @domains allowed to trigger this "
            "workflow. Leave empty to accept email from anyone."
        ),
        json_schema_extra={"placeholder": "alice@example.com, @trusted.com"},
    )


class InboundEmailTriggerNodeConfig(NodeConfig[InboundEmailTriggerConfig, None]):
    """Full configuration for the inbound-email trigger node (no credentials needed)."""
    pass


# ============================================================================
# Inbound Email Trigger Node Implementation
# ============================================================================

class InboundEmailTriggerNode(WorkflowNode):
    """
    Inbound-email trigger node.

    Acts as an entry point for workflows triggered by inbound email to a reserved
    address. The parsed email (sender, subject, body, attachments) is passed
    through as output to downstream nodes.

    The inbound-email route injects the parsed email as ``_triggerPayload``; the
    execution handler uses ``resolve_trigger_payload`` (default — returns it
    unchanged) so the payload becomes this node's output without running execute().
    """

    edit_examples = [
        "Trigger this workflow when an email arrives at my reserved address",
        "Pick the inbox name for incoming emails",
        "Only accept email from a specific sender or domain",
        "Copy the email address to share it",
        "Process attachments from inbound emails",
    ]

    # Trashing must not surrender the reserved address — someone else could
    # claim it before the workflow is restored. Released only on node removal
    # and permanent deletion.
    preserve_registration_on_trash = True

    # A manual run can't produce an inbound email — replay the last received one.
    manual_run_replays_last_event = True

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for the inbound-email trigger node."""
        return InboundEmailTriggerNodeConfig

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Email → agent user turn; threads per sender. Replying happens via
        the auto-injected ``email__reply`` tool (nodes/agent/email_reply.py),
        whose recipient is locked server-side — the event text carries no
        reply instructions on purpose."""
        sender = output.get("from")
        if not sender:
            return None
        lines = [
            f"Email received at {output.get('to')}",
            f"From: {sender}",
            f"Subject: {output.get('subject') or '(no subject)'}",
            "",
            output.get("text") or output.get("html") or "(empty body)",
        ]
        attachments = output.get("attachments") or []
        if attachments:
            lines += ["", "Attachments:"]
            for a in attachments:
                lines.append(f"- {a.get('name')} ({a.get('mime_type')}): {a.get('download_url')}")
                # Inline-extracted document text (email_routes budgets it) rides
                # the event so the agent reads attachments without a tool call.
                if a.get("text"):
                    lines += [f"  Content of {a.get('name')}:", "  ---", a["text"], "  ---"]
                elif a.get("note"):
                    lines.append(f"  ({a['note']})")
        return {"text": "\n".join(lines), "conversation_key": str(sender).lower()}

    @classmethod
    async def cleanup_external_webhook(
        cls,
        pool,
        workflow_id: str,
        node_id: str,
        config: Dict[str, Any],
        credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Release the reserved address when the node is removed (MCP / operation-change paths)."""
        from utils.email_reservation_manager import EmailReservationManager
        try:
            await EmailReservationManager.release(pool, workflow_id, node_id)
        except Exception as e:
            logger.warning(f"[InboundEmailTriggerNode] Failed to release reservation for {node_id}: {e}")

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the inbound-email trigger node.

        On a real trigger the parsed email arrives via ``_triggerPayload`` and is
        used as the node output directly (execute is skipped). This runs only for
        manual node runs / testing, where it echoes any provided email metadata.
        """
        logger.info(f"[InboundEmailTriggerNode] Executing node {self.node_id}")

        email_meta = inputs.get("_email", {})
        output = {
            "type": "email-trigger",
            "status": "received",
            "timestamp": time.time(),
            "from": email_meta.get("from"),
            "to": email_meta.get("to"),
            "subject": email_meta.get("subject"),
            "text": email_meta.get("text"),
            "html": email_meta.get("html"),
            "attachments": email_meta.get("attachments", []),
            "headers": email_meta.get("headers", {}),
        }

        await self.emit(output)
        return output
