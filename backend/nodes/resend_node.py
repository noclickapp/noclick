"""
Resend transactional email automation node.

Provides workflow integration with Resend for operations including:
- Email Operations: send, get, reschedule, cancel transactional emails
- Webhook Trigger: receive delivery events (delivered, bounced, opened, complained)

Authentication: API Key (Bearer token)
API Base URL: https://api.resend.com
Documentation: https://resend.com/docs/api-reference
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, Discriminator, field_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

RESEND_API_BASE = "https://api.resend.com"

# ============================================================================
# Credential Schema
# ============================================================================


class ResendAPIKeyCredential(BaseModel):
    """API Key credential for Resend."""

    credential_type: Literal["resend_api_key"] = Field(
        "resend_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Resend API key (starts with re_) from the API Keys page",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={"x-credential-url": "https://resend.com/api-keys"})


ResendCredential = ResendAPIKeyCredential

# ============================================================================
# Email Operation Configs
# ============================================================================


class ResendSendEmailConfig(BaseModel):
    """Send a transactional email through Resend."""

    operation: Literal["send_email"] = Field(
        "send_email",
        json_schema_extra={
            "const": "send_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Send Email",
        },
        title="Send Email",
    )
    from_address: str = Field(
        ...,
        title="From",
        description='Sender address on a verified domain. Optionally include a name: "NoClick <hello@example.com>"',
    )
    to: str = Field(
        ...,
        title="To",
        description="Recipient email address. For multiple recipients, separate with commas (max 50)",
    )
    subject: str = Field(..., title="Subject", description="Email subject line")
    html: Optional[str] = Field(
        None,
        title="HTML Body",
        description="HTML version of the message body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    text: Optional[str] = Field(
        None,
        title="Plain Text Body",
        description="Plain text version. Auto-generated from HTML if omitted",
        json_schema_extra={"ui:widget": "textarea"},
    )
    cc: Optional[str] = Field(
        None, title="CC", description="Carbon copy recipients, comma-separated"
    )
    bcc: Optional[str] = Field(
        None, title="BCC", description="Blind carbon copy recipients, comma-separated"
    )
    reply_to: Optional[str] = Field(
        None, title="Reply-To", description="Reply-to address(es), comma-separated"
    )
    scheduled_at: Optional[str] = Field(
        None,
        title="Scheduled At",
        description='Schedule delivery using natural language ("in 1 hour") or ISO 8601',
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total)",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("attachments", mode="before")
    @classmethod
    def filter_attachments(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [a for a in v if isinstance(a, str) and a.strip()]


class ResendGetEmailConfig(BaseModel):
    """Retrieve the status and details of a sent email."""

    operation: Literal["get_email"] = Field(
        "get_email",
        json_schema_extra={
            "const": "get_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Get Email",
        },
        title="Get Email",
    )
    email_id: str = Field(
        ..., title="Email ID", description="The ID returned when the email was sent"
    )


class ResendUpdateEmailConfig(BaseModel):
    """Reschedule a previously scheduled email."""

    operation: Literal["update_email"] = Field(
        "update_email",
        json_schema_extra={
            "const": "update_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Reschedule Email",
        },
        title="Reschedule Email",
    )
    email_id: str = Field(
        ..., title="Email ID", description="The ID of the scheduled email to reschedule"
    )
    scheduled_at: str = Field(
        ...,
        title="Scheduled At",
        description='New delivery time using natural language ("in 1 hour") or ISO 8601',
    )


class ResendCancelEmailConfig(BaseModel):
    """Cancel a scheduled email before it is sent."""

    operation: Literal["cancel_email"] = Field(
        "cancel_email",
        json_schema_extra={
            "const": "cancel_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Cancel Email",
        },
        title="Cancel Email",
    )
    email_id: str = Field(
        ..., title="Email ID", description="The ID of the scheduled email to cancel"
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class ResendReceiveWebhookConfig(BaseModel):
    """Receive webhook events from Resend (delivered, bounced, opened, complained)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_webhook"] = Field(
        "receive_webhook",
        json_schema_extra={
            "const": "receive_webhook",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Webhook Events",
        },
        title="Receive Webhook Events",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL as an endpoint at resend.com/webhooks and select which events to send",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


# ============================================================================
# Discriminated Union
# ============================================================================


ResendConfig = Annotated[
    Union[
        ResendSendEmailConfig,
        ResendGetEmailConfig,
        ResendUpdateEmailConfig,
        ResendCancelEmailConfig,
        ResendReceiveWebhookConfig,
    ],
    Discriminator("operation"),
]


class ResendNodeConfig(NodeConfig[ResendConfig, ResendCredential]):
    """Full configuration for Resend node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


def _split_recipients(value: Optional[str]) -> Optional[Union[str, List[str]]]:
    """Convert a comma-separated recipient string into the format Resend expects.

    Returns a single string for one address, a list for multiple, None if empty.
    """
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else parts


class ResendNode(WorkflowNode):
    """
    Resend transactional email automation node.

    Executes Resend API operations for sending, tracking, and managing
    transactional emails, plus a webhook trigger for delivery events.
    """

    edit_examples = [
        "Send a welcome email when a new user signs up",
        "Send a scheduled follow-up email 2 days after signup",
        "Check the delivery status of a previously sent email",
        "Cancel a scheduled email if the user already converted",
        "Trigger a workflow when an email bounces or a recipient complains",
    ]

    @classmethod
    def get_config_model(cls):
        return ResendNodeConfig

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create the internal webhook URL for the receive_webhook operation.

        Resend webhook endpoints are configured in the Resend dashboard, so this
        only provisions our inbound URL — the user pastes it into resend.com/webhooks.
        """
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        return {
            "values": {
                "webhook_id": webhook_data.get("webhook_id"),
                "webhook_url": webhook_data.get("webhook_url"),
                "relay_connected": webhook_data.get("relay_connected"),
                "is_production": webhook_data.get("is_production"),
            }
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, ResendNodeConfig):
            raise ValueError("Valid configuration is required")

        op_config = config.config

        # Webhook trigger mode — pass through the inbound event payload
        if isinstance(op_config, ResendReceiveWebhookConfig):
            return {
                "status": "success",
                "action": "receive_webhook",
                "data": {
                    **inputs,
                    "webhook_url": op_config.webhook_url,
                },
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Resend API key.")

        handlers = {
            "send_email": self._handle_send_email,
            "get_email": self._handle_get_email,
            "update_email": self._handle_update_email,
            "cancel_email": self._handle_cancel_email,
        }

        action = op_config.operation
        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")

        result = await handler(op_config, credentials)

        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }
        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: ResendCredential,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        url = f"{RESEND_API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "Content-Type": "application/json",
            # Resend rejects requests without a User-Agent with a 403.
            "User-Agent": "NoClick-Workflow/1.0",
        }

        if json_body:
            json_body = {k: v for k, v in json_body.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_body,
                )
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get(
                            "message", error_data.get("error", str(error_data))
                        )
                    except Exception:
                        error_message = error_text
                    if isinstance(error_message, str):
                        error_message = error_message.encode(
                            "ascii", errors="replace"
                        ).decode("ascii")

                    logger.error(
                        f"[ResendNode] API error ({action_name}): {error_message}"
                    )
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                if response.status_code == 204:
                    data = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                error_msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ResendNode] Request failed ({action_name}): {error_msg}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": error_msg,
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Email Handlers
    # =========================================================================

    async def _handle_send_email(
        self, config: ResendSendEmailConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "from": config.from_address,
            "to": _split_recipients(config.to),
            "subject": config.subject,
            "html": config.html,
            "text": config.text,
            "cc": _split_recipients(config.cc),
            "bcc": _split_recipients(config.bcc),
            "reply_to": _split_recipients(config.reply_to),
            "scheduled_at": config.scheduled_at,
        }
        if config.attachments:
            from nodes.core.media_resolver import resolve_attachments

            body["attachments"] = [
                {"filename": media.filename, "content": media.base64}
                for media in await resolve_attachments(config.attachments)
            ] or None
        return await self._make_request(
            "POST", "/emails", credentials, json_body=body, action_name="send_email"
        )

    async def _handle_get_email(
        self, config: ResendGetEmailConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"/emails/{config.email_id}", credentials, action_name="get_email"
        )

    async def _handle_update_email(
        self, config: ResendUpdateEmailConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "PATCH",
            f"/emails/{config.email_id}",
            credentials,
            json_body={"scheduled_at": config.scheduled_at},
            action_name="update_email",
        )

    async def _handle_cancel_email(
        self, config: ResendCancelEmailConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            f"/emails/{config.email_id}/cancel",
            credentials,
            action_name="cancel_email",
        )
