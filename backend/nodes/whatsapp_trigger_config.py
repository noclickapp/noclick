"""Shared incoming-message configuration for WhatsApp.

The schema states which inputs are user-supplied for QR versus Cloud API.
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

# The chat picker WhatsAppNode.load_field_options serves (loader key "chat_id"
# or "to"), shared by the send operations' recipient and the trigger's chats.
CHAT_PICKER_OPTIONS = {
    "placeholder": "Select a chat...",
    "searchable": True,
    "allow_custom": True,
    "custom_placeholder": "Or enter a phone number / chat ID",
}


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
        description="Also trigger when a message arrives in a group chat. Off by default: an auto-reply bot answering into groups can message many people at once. Not consulted when Only These Chats is set.",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No (direct messages only)", "Yes (also group chats)"],
            "x-enum-searchable": True,
        },
    )
    include_self_chat: str = Field(
        "false",
        title="Trigger on Your Own Chat",
        description=(
            'Also trigger on what you write in your own "Message yourself" chat on the linked phone, so you can '
            "talk to an agent from WhatsApp. What you send in any other chat, and what a NoClick node sends, "
            "never triggers. Heard whether or not Only These Chats lists it."
        ),
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No", 'Yes (my "Message yourself" chat)'],
            "x-enum-searchable": True,
            "x-supported-credential-types": ["whatsapp_qr"],
        },
    )
    chat_ids: List[str] = Field(
        default_factory=list,
        title="Only These Chats",
        description=(
            "Start a run only for messages in these chats; leave empty for every chat. "
            "When set, the list alone decides: a group listed here fires even with group "
            "messages off, and every chat not listed, direct or group, is ignored."
        ),
        json_schema_extra={
            "x-dynamic-options": {**CHAT_PICKER_OPTIONS, "field_name": "chat_id"},
            "x-supported-credential-types": ["whatsapp_qr"],
        },
    )
