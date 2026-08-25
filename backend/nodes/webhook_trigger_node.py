"""
Webhook trigger node implementation.

This node acts as an entry point for workflows triggered by external HTTP webhooks.
When a webhook is received, this node outputs the webhook payload data to downstream nodes.

Webhook lifecycle is managed by the centralized WebhookManager via schema markers:
- webhook_url field uses ui:widget="webhook" to trigger automatic webhook creation
- Cleanup happens automatically when the node is deleted
"""

import time
import logging
from enum import Enum
from typing import Dict, Any, Optional, Union, Type
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Webhook Trigger Node Configuration Models
# ============================================================================

class WebhookHttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class WebhookAuthentication(str, Enum):
    NONE = "none"
    BASIC = "basic"
    HEADER = "header"
    JWT = "jwt"


class WebhookResponseMode(str, Enum):
    IMMEDIATELY = "immediately"
    LAST_NODE = "last_node"


class WebhookTriggerConfig(BaseModel):
    """Configuration for webhook trigger node"""
    # webhook_url is declared first so it renders at the top of the config panel —
    # it's the field users come here for; HTTP method and the rest follow.
    webhook_id: Optional[str] = Field(
        default=None,
        title="Webhook ID",
        description="Auto-generated webhook ID (read-only)",
        json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="The URL to send webhooks to (auto-generated)",
        # ui:widget="webhook" tells the system to use WebhookManager for this field
        # ui:loadValue triggers the backend to load the value on field render
        # ui:copyable adds a copy button to the field
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True}
    )
    http_method: WebhookHttpMethod = Field(
        default=WebhookHttpMethod.POST,
        title="HTTP Method",
        description="HTTP method this webhook accepts.",
        json_schema_extra={
            "enum": [method.value for method in WebhookHttpMethod],
            "enumLabels": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        },
    )
    # Hidden fields populated by WebhookManager for relay status
    relay_connected: Optional[bool] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True}
    )
    secret: Optional[str] = Field(
        default=None,
        title="Secret (Optional)",
        description="Secret for HMAC-SHA256 signature verification. Leave empty for no verification.",
        json_schema_extra={"ui:widget": "password", "placeholder": "Optional webhook secret"}
    )
    authentication: WebhookAuthentication = Field(
        default=WebhookAuthentication.NONE,
        title="Authentication",
        description="Require callers to authenticate before this webhook runs.",
        json_schema_extra={
            "enum": [mode.value for mode in WebhookAuthentication],
            "enumLabels": ["None", "Basic Auth", "Header Auth", "JWT Auth"],
        },
    )
    respond: WebhookResponseMode = Field(
        default=WebhookResponseMode.IMMEDIATELY,
        title="Respond",
        description="Choose when and how the webhook HTTP response is returned.",
        json_schema_extra={
            "enum": [mode.value for mode in WebhookResponseMode],
            "enumLabels": [
                "Immediately",
                "When Last Node Finishes",
            ],
        },
    )
    basic_auth_username: Optional[str] = Field(
        default=None,
        title="Username",
        description="Username required for Basic Auth.",
        json_schema_extra={"ui:show-if": {"field": "authentication", "contains": "basic"}}
    )
    basic_auth_password: Optional[str] = Field(
        default=None,
        title="Password",
        description="Password required for Basic Auth.",
        json_schema_extra={"ui:widget": "password", "ui:show-if": {"field": "authentication", "contains": "basic"}}
    )
    header_auth_name: Optional[str] = Field(
        default=None,
        title="Header Name",
        description="Header that must be present for Header Auth.",
        json_schema_extra={"placeholder": "x-webhook-token", "ui:show-if": {"field": "authentication", "contains": "header"}}
    )
    header_auth_value: Optional[str] = Field(
        default=None,
        title="Header Value",
        description="Expected header value for Header Auth.",
        json_schema_extra={"ui:widget": "password", "ui:show-if": {"field": "authentication", "contains": "header"}}
    )
    jwt_auth_header: Optional[str] = Field(
        default="authorization",
        title="JWT Header",
        description="Header containing a Bearer JWT.",
        json_schema_extra={"placeholder": "authorization", "ui:show-if": {"field": "authentication", "contains": "jwt"}}
    )
    jwt_auth_secret: Optional[str] = Field(
        default=None,
        title="JWT Secret",
        description="Shared secret used to verify HS256 JWTs.",
        json_schema_extra={"ui:widget": "password", "ui:show-if": {"field": "authentication", "contains": "jwt"}}
    )


class WebhookTriggerNodeConfig(NodeConfig[WebhookTriggerConfig, None]):
    """Full configuration for webhook trigger node (no credentials needed)"""
    pass


# ============================================================================
# Webhook Trigger Node Implementation
# ============================================================================

class WebhookTriggerNode(WorkflowNode):
    """
    Webhook trigger node.

    Acts as an entry point for workflows triggered by external HTTP requests.
    The webhook payload is passed through as output to downstream nodes.

    Webhook URL lifecycle is managed automatically by WebhookManager:
    - Created when the webhook_url field is loaded (ui:widget="webhook")
    - Deleted when the node is removed from the workflow
    """

    edit_examples = [
        "Accept webhook requests from Slack notifications",
        "Trigger this workflow when a GitHub webhook fires",
        "Add a secret for HMAC signature verification",
        "Copy and paste the webhook URL to use elsewhere",
        "Receive data from external HTTP POST requests",
        "Extract webhook headers and query parameters",
    ]

    # A manual run can't produce an HTTP request — replay the last received one.
    manual_run_replays_last_event = True

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for webhook trigger node"""
        return WebhookTriggerNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute webhook trigger node.

        For trigger nodes, the inputs contain the webhook payload data.
        We simply pass this through to downstream nodes.

        Args:
            inputs: Webhook payload data from the HTTP request

        Returns:
            Dict containing the webhook payload and metadata
        """
        logger.info(f"[WebhookTriggerNode] Executing node {self.node_id}")

        # Extract webhook metadata if present
        webhook_meta = inputs.get("_webhook", {})

        # Build output with the webhook payload
        output = {
            "type": "webhook-trigger",
            "status": "triggered",
            "timestamp": time.time(),
            "webhook_id": webhook_meta.get("id"),
            "method": webhook_meta.get("method", "POST"),
            "headers": webhook_meta.get("headers", {}),
            "query_params": webhook_meta.get("query_params", {}),
            # The actual payload (without metadata)
            "payload": {k: v for k, v in inputs.items() if k != "_webhook"},
        }

        # Emit output to frontend
        await self.emit(output)

        logger.info(f"[WebhookTriggerNode] Webhook triggered, passing payload to downstream nodes")
        return output
