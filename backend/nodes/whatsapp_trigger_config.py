"""Shared incoming-message configuration for WhatsApp.

The schema states which inputs are user-supplied for QR versus Cloud API.
"""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class WhatsAppReceiveMessageConfig(BaseModel):
    """Receive incoming messages via webhook. Works with both QR scan and Cloud API credentials."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_message"] = Field(
        "receive_message",
        json_schema_extra={
            "const": "receive_message",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Message",
        },
        title="Receive Message",
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Webhook URL for receiving messages. Auto-registered for QR credentials; for Cloud API, configure in Meta Developer Console.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
            "readOnly": True,
        },
    )
    verify_token: Optional[str] = Field(
        default=None,
        title="Verify Token (Optional)",
        description="Cloud API subscription verification token. QR connections do not use this field.",
        json_schema_extra={
            "ui:widget": "password",
            "x-supported-credential-types": ["whatsapp_access_token"],
        },
    )
    include_group_messages: str = Field(
        "false",
        title="Trigger on Group Messages",
        description="Also trigger when a message arrives in a group chat. Off by default: an auto-reply bot answering into groups can message many people at once.",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No (direct messages only)", "Yes (also group chats)"],
            "x-enum-searchable": True,
        },
    )
