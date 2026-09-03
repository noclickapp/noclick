"""
WhatsApp Business Cloud API automation node.

Provides comprehensive workflow integration for WhatsApp Business Platform with 40+ operations across:
- Messaging: Text, template, media, interactive, location, contacts, reactions
- Media Management: Upload, download, retrieve, delete
- Business Profile: Get, update profile information
- Phone Numbers: Register, verify, get info
- Templates: List, get, create, delete message templates
- Commerce: Catalog, product, multi-product messages
- Message Management: Mark as read
- Webhooks: Receive messages and status updates (via webhook trigger)
- Chats (QR credentials only): List chats/contacts, read message history, edit sent messages

Authentication: Meta Access Token (temporary 60-day or permanent system user token)
or WAHooks QR scan (personal account; chat/message reads are QR-only)
Base URL: https://graph.facebook.com/v21.0
Documentation: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import asyncio
import logging
import os
import time
import json
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator, ConfigDict
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import assert_exact_url_origin, guarded_async_client
from nodes.core.connection_evidence import ConnectionEvidence

logger = logging.getLogger(__name__)

# WhatsApp Cloud API base URL (v21.0 as of 2025)
WHATSAPP_API_BASE = "https://graph.facebook.com/v21.0"
WHATSAPP_API_VERSION = "v21.0"
WAHOOKS_API_ORIGIN = "https://api.wahooks.com"
WHATSAPP_MEDIA_ORIGIN = "https://lookaside.fbsbx.com"


# ============================================================================
# WhatsApp Node Credential Schema
# ============================================================================


class WhatsAppAccessTokenCredential(BaseModel):
    """
    Meta Access Token credential for WhatsApp Business Cloud API.

    Get your access token from Meta Developer Console:
    1. Go to https://developers.facebook.com/apps
    2. Select your app -> WhatsApp -> API Setup
    3. Generate either:
       - Temporary token (60 days, testing)
       - Permanent token (via System User in Business Settings)

    Required permissions:
    - whatsapp_business_messaging
    - whatsapp_business_management
    """

    credential_type: Literal["whatsapp_access_token"] = Field(
        "whatsapp_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        min_length=1,
        title="Access Token",
        description="Meta access token from Developer Console (temporary or permanent)",
        json_schema_extra={"ui:widget": "password"},
    )
    phone_number_id: str = Field(
        ...,
        min_length=1,
        title="Phone Number ID",
        description="WhatsApp Business Phone Number ID from API Setup page",
        json_schema_extra={"placeholder": "1234567890123456"},
    )
    business_account_id: Optional[str] = Field(
        None,
        title="Business Account ID (Optional)",
        description="WhatsApp Business Account ID (required for template management and account operations)",
        json_schema_extra={
            "placeholder": "Leave empty if not managing templates/account"
        },
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://developers.facebook.com/apps",
        "x-credential-instructions": "1. Go to Meta Developer Console\n2. Select your app -> WhatsApp -> API Setup\n3. Copy Phone Number ID and Access Token\n4. For permanent token: Business Settings -> System Users -> Generate New Token",
    })


class WhatsAppQRCredential(BaseModel):
    """
    WAHooks QR code scan credential for WhatsApp.

    Connect your WhatsApp account by scanning a QR code.
    No Meta Developer account required - just scan with your phone.
    """

    credential_type: Literal["whatsapp_qr"] = Field(
        "whatsapp_qr", json_schema_extra={"ui:hidden": True}
    )
    connection_id: str = Field(
        ...,
        min_length=1,
        title="Connection ID",
        description="WAHooks connection ID (auto-filled after QR scan)",
        json_schema_extra={"ui:hidden": True},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "qr_scan",
        "x-credential-instructions": "Connect your WhatsApp by scanning a QR code. A persistent connection fee of $0.99/month will be charged to your balance.",
    })


# Union type for WhatsApp credentials - supports both Meta Access Token and QR scan
WhatsAppCredential = Union[WhatsAppQRCredential, WhatsAppAccessTokenCredential]


# Recipient guidance shared by every QR-capable send op. Leads with the
# reply-to-a-trigger case and tells the agent to echo the chat id VERBATIM:
# to_chat_id() passes @-suffixed ids straight through, so reconstructing an
# E.164 number is both unnecessary and how replies got mis-addressed to
# non-existent accounts (WAHA accepts them, returns PENDING, never delivers).
_RECIPIENT_DESC = (
    "Recipient chat. When replying to an incoming message (e.g. from a WhatsApp "
    "trigger event), pass the sender's chat ID from that event EXACTLY as given "
    "(e.g. 12025550101@c.us or 12025550102@lid) — do NOT reformat it into a "
    "phone number. To start a new conversation, use a phone number in E.164 "
    "format (e.g., +12025550100)."
)


def _chat_picker_field(
    title: str, description: str = _RECIPIENT_DESC, *, field_name: str
) -> Any:
    """Recipient/chat picker backed by WhatsAppNode.load_field_options.

    QR credentials list the account's chats (with contact names); the Cloud
    API has no chat listing, so allow_custom keeps manual E.164 entry and
    {{references}} working for both credential types.
    """
    return Field(
        ...,
        title=title,
        description=description,
        json_schema_extra={
            "placeholder": "+12025550100",
            "x-dynamic-options": {
                "field_name": field_name,
                "placeholder": "Select a chat...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a phone number / chat ID",
            },
            "x-resource-type": "whatsapp_chat",
        },
    )


# ============================================================================
# Message Sending Operations
# ============================================================================


class WhatsAppSendTextConfig(BaseModel):
    """Send a text message"""

    operation: Literal["send_text_message"] = Field(
        "send_text_message",
        json_schema_extra={
            "const": "send_text_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Text Message",
        },
        title="Send Text Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    body: str = Field(
        ...,
        title="Message Text",
        description="Text message content (up to 4096 characters)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter your message...",
        },
    )
    reply_to_message_id: Optional[str] = Field(
        None,
        title="Reply To (Message ID)",
        description="Send as a reply to this message (from a trigger payload or Get Chat Messages)",
        json_schema_extra={"placeholder": "wamid.xxx... / message id"},
    )
    preview_url: bool = Field(
        False, title="Preview URL", description="Enable URL preview in message"
    )


class WhatsAppSendTemplateConfig(BaseModel):
    """Send a pre-approved template message"""

    operation: Literal["send_template_message"] = Field(
        "send_template_message",
        json_schema_extra={
            "const": "send_template_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Send Template Message",
        },
        title="Send Template Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    template_name: str = Field(
        ...,
        title="Template Name",
        description="Name of the approved message template",
        json_schema_extra={"placeholder": "hello_world"},
    )
    language_code: str = Field(
        "en_US",
        title="Language Code",
        description="Template language code (e.g., en_US, es_ES, pt_BR)",
        json_schema_extra={"placeholder": "en_US"},
    )
    parameters: Optional[str] = Field(
        None,
        title="Template Parameters (JSON)",
        description='JSON array of parameter values for template variables (e.g., [{"type":"text","text":"John"}])',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type":"text","text":"value1"},{"type":"text","text":"value2"}]',
        },
    )


class WhatsAppSendImageConfig(BaseModel):
    """Send an image message"""

    operation: Literal["send_image_message"] = Field(
        "send_image_message",
        json_schema_extra={
            "const": "send_image_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Image Message",
        },
        title="Send Image Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    image_url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/image.jpg",
            "ui:widget": "media_upload",
            "ui:accept": "image/*",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR image_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption (Optional)",
        description="Image caption",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter caption..."},
    )


class WhatsAppSendVideoConfig(BaseModel):
    """Send a video message"""

    operation: Literal["send_video_message"] = Field(
        "send_video_message",
        json_schema_extra={
            "const": "send_video_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Video Message",
        },
        title="Send Video Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    video_url: Optional[str] = Field(
        None,
        title="Video URL",
        description="The video to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/video.mp4",
            "ui:widget": "media_upload",
            "ui:accept": "video/*",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR video_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption (Optional)",
        description="Video caption",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter caption..."},
    )


class WhatsAppSendDocumentConfig(BaseModel):
    """Send a document message"""

    operation: Literal["send_document_message"] = Field(
        "send_document_message",
        json_schema_extra={
            "const": "send_document_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Document Message",
        },
        title="Send Document Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    document_url: Optional[str] = Field(
        None,
        title="Document URL",
        description="The document to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/document.pdf",
            "ui:widget": "media_upload",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR document_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )
    filename: Optional[str] = Field(
        None,
        title="Filename (Optional)",
        description="Document filename",
        json_schema_extra={"placeholder": "document.pdf"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption (Optional)",
        description="Document caption",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter caption..."},
    )


class WhatsAppSendAudioConfig(BaseModel):
    """Send an audio message"""

    operation: Literal["send_audio_message"] = Field(
        "send_audio_message",
        json_schema_extra={
            "const": "send_audio_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Audio Message",
        },
        title="Send Audio Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    audio_url: Optional[str] = Field(
        None,
        title="Audio URL",
        description="The audio to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/audio.mp3",
            "ui:widget": "media_upload",
            "ui:accept": "audio/*",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR audio_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )


class WhatsAppSendLocationConfig(BaseModel):
    """Send a location message"""

    operation: Literal["send_location_message"] = Field(
        "send_location_message",
        json_schema_extra={
            "const": "send_location_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Location Message",
        },
        title="Send Location Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    latitude: str = Field(
        ...,
        title="Latitude",
        description="Location latitude (e.g., 37.7749)",
        json_schema_extra={"placeholder": "37.7749"},
    )
    longitude: str = Field(
        ...,
        title="Longitude",
        description="Location longitude (e.g., -122.4194)",
        json_schema_extra={"placeholder": "-122.4194"},
    )
    name: Optional[str] = Field(
        None,
        title="Name (Optional)",
        description="Location name",
        json_schema_extra={"placeholder": "My Office"},
    )
    address: Optional[str] = Field(
        None,
        title="Address (Optional)",
        description="Location address",
        json_schema_extra={"placeholder": "123 Main St, San Francisco, CA"},
    )


class WhatsAppSendContactConfig(BaseModel):
    """Send a contact card message"""

    operation: Literal["send_contact_card"] = Field(
        "send_contact_card",
        json_schema_extra={
            "const": "send_contact_card",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Contact Card",
        },
        title="Send Contact Card",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    contact_name: str = Field(
        ...,
        title="Contact Name",
        description="Contact's full name",
        json_schema_extra={"placeholder": "John Doe"},
    )
    contact_phone: str = Field(
        ...,
        title="Contact Phone",
        description="Contact's phone number",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    contact_email: Optional[str] = Field(
        None,
        title="Contact Email (Optional)",
        description="Contact's email address",
        json_schema_extra={"placeholder": "john@example.com"},
    )


class WhatsAppSendButtonsConfig(BaseModel):
    """Send an interactive message with quick reply buttons"""

    operation: Literal["send_interactive_buttons"] = Field(
        "send_interactive_buttons",
        json_schema_extra={
            "const": "send_interactive_buttons",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Interactive Buttons",
        },
        title="Send Interactive Buttons",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Main message text",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Choose an option:"},
    )
    buttons: str = Field(
        ...,
        title="Buttons (JSON Array)",
        description='JSON array of button objects (max 3): [{"type":"reply","reply":{"id":"btn1","title":"Button 1"}}]',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type":"reply","reply":{"id":"btn1","title":"Option 1"}},{"type":"reply","reply":{"id":"btn2","title":"Option 2"}}]',
        },
    )
    header: Optional[str] = Field(
        None,
        title="Header (Optional)",
        description="Optional header text",
        json_schema_extra={"placeholder": "Select your choice"},
    )
    footer: Optional[str] = Field(
        None,
        title="Footer (Optional)",
        description="Optional footer text",
        json_schema_extra={"placeholder": "Powered by MyBusiness"},
    )


class WhatsAppSendListConfig(BaseModel):
    """Send an interactive list message"""

    operation: Literal["send_interactive_list"] = Field(
        "send_interactive_list",
        json_schema_extra={
            "const": "send_interactive_list",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Interactive List",
        },
        title="Send Interactive List",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Main message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Please select from the list:",
        },
    )
    button_text: str = Field(
        "View Options",
        title="Button Text",
        description="Text shown on the list button (max 20 chars)",
        json_schema_extra={"placeholder": "View Options"},
    )
    sections: str = Field(
        ...,
        title="List Sections (JSON Array)",
        description='JSON array of sections with rows (max 10 total): [{"title":"Section 1","rows":[{"id":"row1","title":"Option 1","description":"Description"}]}]',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"title":"Section 1","rows":[{"id":"opt1","title":"Option 1","description":"First option"}]}]',
        },
    )
    header: Optional[str] = Field(
        None,
        title="Header (Optional)",
        description="Optional header text",
        json_schema_extra={"placeholder": "Choose from menu"},
    )
    footer: Optional[str] = Field(
        None,
        title="Footer (Optional)",
        description="Optional footer text",
        json_schema_extra={"placeholder": "Select one option"},
    )


class WhatsAppSendReactionConfig(BaseModel):
    """Send a reaction (emoji) to a message"""

    operation: Literal["send_reaction_emoji"] = Field(
        "send_reaction_emoji",
        json_schema_extra={
            "const": "send_reaction_emoji",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Reaction Emoji",
        },
        title="Send Reaction Emoji",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    message_id: str = Field(
        ...,
        title="Message ID",
        description="WhatsApp message ID to react to (wamid)",
        json_schema_extra={"placeholder": "wamid.xxx..."},
    )
    emoji: str = Field(
        ...,
        title="Emoji",
        description="Single emoji character (use empty string to remove reaction)",
        json_schema_extra={"placeholder": "👍"},
    )


class WhatsAppMarkReadConfig(BaseModel):
    """Mark a message as read"""

    operation: Literal["mark_message_read"] = Field(
        "mark_message_read",
        json_schema_extra={
            "const": "mark_message_read",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mark Message Read",
        },
        title="Mark Message Read",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="WhatsApp message ID to mark as read (wamid)",
        json_schema_extra={"placeholder": "wamid.xxx..."},
    )


# ============================================================================
# Media Management Operations
# ============================================================================


class WhatsAppUploadMediaConfig(BaseModel):
    """Upload media to WhatsApp"""

    operation: Literal["upload_media"] = Field(
        "upload_media",
        json_schema_extra={
            "const": "upload_media",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Upload Media",
        },
        title="Upload Media",
    )
    media_url: str = Field(
        ...,
        title="Media URL",
        description="The media to upload — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Max 100MB.",
        json_schema_extra={
            "placeholder": "https://example.com/image.jpg",
            "ui:widget": "media_upload",
            "ui:accept": "image/*,video/*",
        },
    )
    media_type: str = Field(
        ...,
        title="Media Type",
        description="MIME type of the media (e.g., image/jpeg, video/mp4, application/pdf)",
        json_schema_extra={
            "enum": [
                "image/jpeg",
                "image/png",
                "video/mp4",
                "video/3gpp",
                "audio/aac",
                "audio/mp4",
                "audio/mpeg",
                "audio/amr",
                "audio/ogg",
                "application/pdf",
                "text/plain",
            ],
            "enumNames": [
                "Image (JPEG)",
                "Image (PNG)",
                "Video (MP4)",
                "Video (3GPP)",
                "Audio (AAC)",
                "Audio (MP4)",
                "Audio (MP3)",
                "Audio (AMR)",
                "Audio (OGG)",
                "Document (PDF)",
                "Document (TXT)",
            ],
        },
    )


class WhatsAppGetMediaUrlConfig(BaseModel):
    """Retrieve media URL from media ID"""

    operation: Literal["get_media_url"] = Field(
        "get_media_url",
        json_schema_extra={
            "const": "get_media_url",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Url",
        },
        title="Get Media Url",
    )
    media_id: str = Field(
        ...,
        title="Media ID",
        description="WhatsApp media ID",
        json_schema_extra={"placeholder": "1234567890123456"},
    )


class WhatsAppDownloadMediaConfig(BaseModel):
    """Download media file (returns binary data)"""

    operation: Literal["download_media"] = Field(
        "download_media",
        json_schema_extra={
            "const": "download_media",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Download Media",
        },
        title="Download Media",
    )
    media_url: str = Field(
        ...,
        title="Media URL",
        description="Media download URL from get_media_url operation (valid for 5 minutes)",
        json_schema_extra={"placeholder": "https://lookaside.fbsbx.com/..."},
    )


class WhatsAppDeleteMediaConfig(BaseModel):
    """Delete media from WhatsApp servers"""

    operation: Literal["delete_media"] = Field(
        "delete_media",
        json_schema_extra={
            "const": "delete_media",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Delete Media",
        },
        title="Delete Media",
    )
    media_id: str = Field(
        ...,
        title="Media ID",
        description="WhatsApp media ID to delete",
        json_schema_extra={"placeholder": "1234567890123456"},
    )


# ============================================================================
# Business Profile Operations
# ============================================================================


class WhatsAppGetBusinessProfileConfig(BaseModel):
    """Get business profile information"""

    operation: Literal["get_business_profile"] = Field(
        "get_business_profile",
        json_schema_extra={
            "const": "get_business_profile",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get Business Profile",
        },
        title="Get Business Profile",
    )
    fields: str = Field(
        "about,address,description,email,profile_picture_url,websites,vertical",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
        json_schema_extra={"placeholder": "about,address,description,email"},
    )


class WhatsAppUpdateBusinessProfileConfig(BaseModel):
    """Update business profile information"""

    operation: Literal["update_business_profile"] = Field(
        "update_business_profile",
        json_schema_extra={
            "const": "update_business_profile",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Update Business Profile",
        },
        title="Update Business Profile",
    )
    about: Optional[str] = Field(
        None,
        title="About (Optional)",
        description="Business description (max 139 chars)",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "We are a..."},
    )
    address: Optional[str] = Field(
        None,
        title="Address (Optional)",
        description="Business address (max 256 chars)",
        json_schema_extra={"placeholder": "123 Main St, City"},
    )
    description: Optional[str] = Field(
        None,
        title="Description (Optional)",
        description="Extended business description (max 512 chars)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Full business description...",
        },
    )
    email: Optional[str] = Field(
        None,
        title="Email (Optional)",
        description="Business email address",
        json_schema_extra={"placeholder": "business@example.com"},
    )
    vertical: Optional[str] = Field(
        None,
        title="Vertical/Industry (Optional)",
        description="Business category",
        json_schema_extra={
            "enum": [
                "AUTO",
                "BEAUTY",
                "APPAREL",
                "EDU",
                "ENTERTAIN",
                "EVENT_PLAN",
                "FINANCE",
                "GROCERY",
                "GOVT",
                "HOTEL",
                "HEALTH",
                "NONPROFIT",
                "PROF_SERVICES",
                "RETAIL",
                "TRAVEL",
                "RESTAURANT",
                "NOT_A_BIZ",
            ],
            "enumNames": [
                "Automotive",
                "Beauty/Spa/Salon",
                "Apparel/Clothing",
                "Education",
                "Entertainment",
                "Event Planning",
                "Finance/Banking",
                "Grocery",
                "Government",
                "Hotel/Lodging",
                "Healthcare",
                "Nonprofit",
                "Professional Services",
                "Retail",
                "Travel/Transportation",
                "Restaurant",
                "Not a Business",
            ],
        },
    )
    websites: Optional[str] = Field(
        None,
        title="Websites (Optional)",
        description="Comma-separated list of website URLs",
        json_schema_extra={
            "placeholder": "https://example.com,https://shop.example.com"
        },
    )


# ============================================================================
# Phone Number Operations
# ============================================================================


class WhatsAppRegisterPhoneConfig(BaseModel):
    """Register a phone number with WhatsApp Business"""

    operation: Literal["register_phone_number"] = Field(
        "register_phone_number",
        json_schema_extra={
            "const": "register_phone_number",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "Register Phone Number",
        },
        title="Register Phone Number",
    )
    pin: str = Field(
        ...,
        title="6-Digit PIN",
        description="6-digit PIN received via SMS or voice call",
        json_schema_extra={"placeholder": "123456"},
    )


class WhatsAppRequestCodeConfig(BaseModel):
    """Request verification code via SMS or voice"""

    operation: Literal["request_verification_code"] = Field(
        "request_verification_code",
        json_schema_extra={
            "const": "request_verification_code",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "Request Verification Code",
        },
        title="Request Verification Code",
    )
    code_method: str = Field(
        "SMS",
        title="Code Method",
        description="Method to receive verification code",
        json_schema_extra={
            "enum": ["SMS", "VOICE"],
            "enumNames": ["SMS Text Message", "Voice Call"],
        },
    )
    language: str = Field(
        "en_US",
        title="Language",
        description="Language for the verification message",
        json_schema_extra={"placeholder": "en_US"},
    )


class WhatsAppGetPhoneInfoConfig(BaseModel):
    """Get phone number information"""

    operation: Literal["get_phone_number_info"] = Field(
        "get_phone_number_info",
        json_schema_extra={
            "const": "get_phone_number_info",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "Get Phone Number Info",
        },
        title="Get Phone Number Info",
    )
    fields: str = Field(
        "verified_name,code_verification_status,display_phone_number,quality_rating,messaging_limit_tier",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
        json_schema_extra={"placeholder": "verified_name,quality_rating"},
    )


# ============================================================================
# Template Management Operations
# ============================================================================


class WhatsAppListTemplatesConfig(BaseModel):
    """List all message templates"""

    operation: Literal["list_message_templates"] = Field(
        "list_message_templates",
        json_schema_extra={
            "const": "list_message_templates",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "List Message Templates",
        },
        title="List Message Templates",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Number of templates to retrieve (1-250)",
        ge=1,
        le=250,
    )
    status: Optional[str] = Field(
        None,
        title="Filter by Status (Optional)",
        description="Filter templates by approval status",
        json_schema_extra={
            "enum": ["", "APPROVED", "PENDING", "REJECTED"],
            "enumNames": ["All Statuses", "Approved", "Pending", "Rejected"],
        },
    )


class WhatsAppGetTemplateConfig(BaseModel):
    """Get a specific message template"""

    operation: Literal["get_message_template"] = Field(
        "get_message_template",
        json_schema_extra={
            "const": "get_message_template",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Get Message Template",
        },
        title="Get Message Template",
    )
    template_id: str = Field(
        ...,
        title="Template ID",
        description="WhatsApp template ID",
        json_schema_extra={"placeholder": "1234567890123456"},
    )


class WhatsAppCreateTemplateConfig(BaseModel):
    """Create a new message template"""

    operation: Literal["create_message_template"] = Field(
        "create_message_template",
        json_schema_extra={
            "const": "create_message_template",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Create Message Template",
        },
        title="Create Message Template",
    )
    name: str = Field(
        ...,
        title="Template Name",
        description="Template name (lowercase, underscores only)",
        json_schema_extra={"placeholder": "welcome_message"},
    )
    language: str = Field(
        "en_US",
        title="Language",
        description="Template language code",
        json_schema_extra={"placeholder": "en_US"},
    )
    category: str = Field(
        ...,
        title="Category",
        description="Template category",
        json_schema_extra={
            "enum": ["AUTHENTICATION", "MARKETING", "UTILITY"],
            "enumNames": [
                "Authentication (OTP, verification)",
                "Marketing (promotions, announcements)",
                "Utility (account updates, alerts)",
            ],
        },
    )
    body: str = Field(
        ...,
        title="Body Text",
        description="Template body text (use {{1}}, {{2}} for variables)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Hello {{1}}, your order {{2}} is ready!",
        },
    )
    header: Optional[str] = Field(
        None,
        title="Header (Optional)",
        description="Optional header text or media",
        json_schema_extra={"placeholder": "Welcome!"},
    )
    footer: Optional[str] = Field(
        None,
        title="Footer (Optional)",
        description="Optional footer text (max 60 chars)",
        json_schema_extra={"placeholder": "Reply STOP to unsubscribe"},
    )


class WhatsAppDeleteTemplateConfig(BaseModel):
    """Delete a message template"""

    operation: Literal["delete_message_template"] = Field(
        "delete_message_template",
        json_schema_extra={
            "const": "delete_message_template",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Delete Message Template",
        },
        title="Delete Message Template",
    )
    template_name: str = Field(
        ...,
        title="Template Name",
        description="Name of the template to delete",
        json_schema_extra={"placeholder": "hello_world"},
    )


# ============================================================================
# Commerce Operations
# ============================================================================


class WhatsAppSendCatalogConfig(BaseModel):
    """Send catalog message"""

    operation: Literal["send_catalog_message"] = Field(
        "send_catalog_message",
        json_schema_extra={
            "const": "send_catalog_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Catalog Message",
        },
        title="Send Catalog Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Catalog message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Check out our catalog!",
        },
    )
    thumbnail_product_id: Optional[str] = Field(
        None,
        title="Thumbnail Product ID (Optional)",
        description="Product ID to show as thumbnail",
        json_schema_extra={"placeholder": "product_123"},
    )


class WhatsAppSendProductConfig(BaseModel):
    """Send a single product message"""

    operation: Literal["send_product_message"] = Field(
        "send_product_message",
        json_schema_extra={
            "const": "send_product_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Product Message",
        },
        title="Send Product Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    catalog_id: str = Field(
        ...,
        title="Catalog ID",
        description="Your Meta Commerce catalog ID",
        json_schema_extra={"placeholder": "1234567890"},
    )
    product_id: str = Field(
        ...,
        title="Product ID",
        description="Product ID from your catalog",
        json_schema_extra={"placeholder": "SKU_123"},
    )
    body: Optional[str] = Field(
        None,
        title="Message Body (Optional)",
        description="Optional message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Check out this product!",
        },
    )


class WhatsAppSendMultiProductConfig(BaseModel):
    """Send multiple products message"""

    operation: Literal["send_multi_product_message"] = Field(
        "send_multi_product_message",
        json_schema_extra={
            "const": "send_multi_product_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Multi Product Message",
        },
        title="Send Multi Product Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    catalog_id: str = Field(
        ...,
        title="Catalog ID",
        description="Your Meta Commerce catalog ID",
        json_schema_extra={"placeholder": "1234567890"},
    )
    product_ids: str = Field(
        ...,
        title="Product IDs (JSON Array)",
        description='JSON array of product IDs (max 30): ["SKU_1", "SKU_2", "SKU_3"]',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '["SKU_1", "SKU_2", "SKU_3"]',
        },
    )
    header: str = Field(
        "Our Products",
        title="Header Text",
        description="Section header text",
        json_schema_extra={"placeholder": "Our Products"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Browse our collection!",
        },
    )


# ============================================================================
# Account Management Operations
# ============================================================================


class WhatsAppGetAccountInfoConfig(BaseModel):
    """Get WhatsApp Business Account information"""

    operation: Literal["get_account_info"] = Field(
        "get_account_info",
        json_schema_extra={
            "const": "get_account_info",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Account Info",
        },
        title="Get Account Info",
    )
    fields: str = Field(
        "id,name,message_template_namespace,timezone_id,currency,account_review_status",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
        json_schema_extra={"placeholder": "id,name,timezone_id"},
    )


class WhatsAppListPhoneNumbersConfig(BaseModel):
    """List all phone numbers in the account"""

    operation: Literal["list_account_phone_numbers"] = Field(
        "list_account_phone_numbers",
        json_schema_extra={
            "const": "list_account_phone_numbers",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "List Account Phone Numbers",
        },
        title="List Account Phone Numbers",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Number of phone numbers to retrieve",
        ge=1,
        le=100,
    )


# ============================================================================
# QR-supported Read Operations
# ============================================================================


class WhatsAppGetChatsConfig(BaseModel):
    """List recent WhatsApp conversations"""

    operation: Literal["list_recent_chats"] = Field(
        "list_recent_chats",
        json_schema_extra={
            "const": "list_recent_chats",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "List Recent Chats",
            "x-keywords": ["conversations", "inbox", "chat list"],
        },
        title="List Recent Chats",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Maximum number of chats to return",
        ge=1,
        le=500,
    )
    unread_only: str = Field(
        "false",
        title="Unread Only",
        description="Only return chats marked unread (best-effort)",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No (all chats)", "Yes (unread only)"],
            "x-enum-searchable": True,
        },
    )


class WhatsAppGetChatMessagesConfig(BaseModel):
    """Read message history from a chat (QR credentials)"""

    operation: Literal["get_chat_messages"] = Field(
        "get_chat_messages",
        json_schema_extra={
            "const": "get_chat_messages",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Get Chat Messages",
            "x-keywords": ["read messages", "chat history", "conversation history"],
        },
        title="Get Chat Messages",
    )
    chat_id: str = _chat_picker_field(
        "Chat",
        "Chat to read messages from (pick from your WhatsApp chats)",
        field_name="chat_id",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Number of messages to return, newest first",
        ge=1,
        le=100,
    )
    before: Optional[str] = Field(
        None,
        title="Before (Cursor)",
        description="Pagination cursor from a previous page's next_before — fetches the next (older) page",
        json_schema_extra={"placeholder": "Leave empty for the newest messages"},
    )


class WhatsAppListContactsConfig(BaseModel):
    """List the connected account's WhatsApp contacts (QR credentials)"""

    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
            "x-keywords": ["address book", "phone numbers", "people"],
        },
        title="List Contacts",
    )
    limit: int = Field(
        200,
        title="Limit",
        description="Maximum number of contacts to return",
        ge=1,
        le=1000,
    )


class WhatsAppEditMessageConfig(BaseModel):
    """Edit a previously sent message (QR credentials)"""

    operation: Literal["edit_message"] = Field(
        "edit_message",
        json_schema_extra={
            "const": "edit_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Edit Message",
        },
        title="Edit Message",
    )
    chat_id: str = _chat_picker_field(
        "Chat",
        "Chat containing the message to edit",
        field_name="chat_id",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the sent message to edit (from a send operation's output or Get Chat Messages)",
        json_schema_extra={"placeholder": "message id"},
    )
    body: str = Field(
        ...,
        title="New Text",
        description="Replacement message text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class WhatsAppMarkChatReadConfig(BaseModel):
    """Mark a chat's messages as read (QR credentials)"""

    operation: Literal["mark_chat_read"] = Field(
        "mark_chat_read",
        json_schema_extra={
            "const": "mark_chat_read",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Mark Chat Read",
        },
        title="Mark Chat Read",
    )
    chat_id: str = _chat_picker_field(
        "Chat",
        "Chat to mark as read",
        field_name="chat_id",
    )


class WhatsAppGetProfileConfig(BaseModel):
    """Get the connected WhatsApp account profile info"""

    operation: Literal["get_account_profile"] = Field(
        "get_account_profile",
        json_schema_extra={
            "const": "get_account_profile",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get Account Profile",
        },
        title="Get Account Profile",
    )


# ============================================================================
# Webhook Operations (receive-only via webhook trigger)
# ============================================================================


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
        },
    )
    verify_token: Optional[str] = Field(
        default=None,
        title="Verify Token (Optional)",
        description="Token to verify webhook subscription (you choose this)",
        json_schema_extra={"ui:widget": "password"},
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


class WhatsAppReceiveStatusConfig(BaseModel):
    """Receive message status updates via webhook"""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_status_update"] = Field(
        "receive_status_update",
        json_schema_extra={
            "const": "receive_status_update",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Status Update",
        },
        title="Receive Status Update",
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Configure this URL in Meta Developer Console to receive status updates (sent, delivered, read, failed)",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    verify_token: Optional[str] = Field(
        default=None,
        title="Verify Token (Optional)",
        description="Token to verify webhook subscription",
        json_schema_extra={"ui:widget": "password"},
    )


# ============================================================================
# Discriminated Union - ALL Operations
# ============================================================================

WhatsAppConfig = Annotated[
    Union[
        # Messaging (12 operations)
        WhatsAppSendTextConfig,
        WhatsAppSendTemplateConfig,
        WhatsAppSendImageConfig,
        WhatsAppSendVideoConfig,
        WhatsAppSendDocumentConfig,
        WhatsAppSendAudioConfig,
        WhatsAppSendLocationConfig,
        WhatsAppSendContactConfig,
        WhatsAppSendButtonsConfig,
        WhatsAppSendListConfig,
        WhatsAppSendReactionConfig,
        WhatsAppMarkReadConfig,
        # Media Management (4 operations)
        WhatsAppUploadMediaConfig,
        WhatsAppGetMediaUrlConfig,
        WhatsAppDownloadMediaConfig,
        WhatsAppDeleteMediaConfig,
        # Business Profile (2 operations)
        WhatsAppGetBusinessProfileConfig,
        WhatsAppUpdateBusinessProfileConfig,
        # Phone Number (3 operations)
        WhatsAppRegisterPhoneConfig,
        WhatsAppRequestCodeConfig,
        WhatsAppGetPhoneInfoConfig,
        # Templates (4 operations)
        WhatsAppListTemplatesConfig,
        WhatsAppGetTemplateConfig,
        WhatsAppCreateTemplateConfig,
        WhatsAppDeleteTemplateConfig,
        # Commerce (3 operations)
        WhatsAppSendCatalogConfig,
        WhatsAppSendProductConfig,
        WhatsAppSendMultiProductConfig,
        # Account (2 operations)
        WhatsAppGetAccountInfoConfig,
        WhatsAppListPhoneNumbersConfig,
        # QR Operations (6 operations)
        WhatsAppGetChatsConfig,
        WhatsAppGetChatMessagesConfig,
        WhatsAppListContactsConfig,
        WhatsAppEditMessageConfig,
        WhatsAppMarkChatReadConfig,
        WhatsAppGetProfileConfig,
        # Webhooks (2 operations)
        WhatsAppReceiveMessageConfig,
        WhatsAppReceiveStatusConfig,
    ],
    Discriminator("operation"),
]


class WhatsAppNodeConfig(NodeConfig[WhatsAppConfig, WhatsAppCredential]):
    """Full configuration for WhatsApp node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================

# Events our per-node WAHooks webhook subscribes to: message deliveries fire
# the workflow; session.status powers dead-session detection (credential
# marked + owner alerted when the phone link dies, instead of leaving the
# trigger falsely marked as healthy).
WAHOOKS_WEBHOOK_EVENTS = ["message", "session.status"]


def _wahooks_ensure_webhook(api_key: str, connection_id: str, webhook_url: str) -> bool:
    """Sync (thread-pool) create-or-upgrade of our WAHooks webhook on a
    connection: registers the URL if absent and upgrades a pre-existing
    config to the full WAHOOKS_WEBHOOK_EVENTS subscription. Returns True when
    anything was created/updated."""
    from wahooks import WAHooks

    with WAHooks(api_key=api_key) as client:
        ours = [
            w for w in client.list_webhooks(connection_id)
            if w.get("url") == webhook_url
        ]
        if not ours:
            client.create_webhook(
                connection_id, url=webhook_url, events=list(WAHOOKS_WEBHOOK_EVENTS)
            )
            return True
        changed = False
        for w in ours:
            have = set(w.get("events") or [])
            if not set(WAHOOKS_WEBHOOK_EVENTS) <= have:
                client.update_webhook(
                    w["id"], events=sorted(have | set(WAHOOKS_WEBHOOK_EVENTS))
                )
                changed = True
        return changed


class WhatsAppNode(WorkflowNode):
    """
    WhatsApp Business Cloud API automation node.

    Provides 32 operations across messaging, media, profiles, templates, and commerce.
    Uses Meta access tokens for authentication.
    """

    # The chat list comes from the linked phone, so it is both recognisable and
    # the only thing that proves the QR session is actually still alive.
    connection_evidence = ConnectionEvidence(
        field="chat_id",
        noun="chats",
    )

    edit_examples = [
        "Send order confirmation message using approved template",
        "Reply to customer inquiry with shipping tracking info",
        "Send invoice PDF as media attachment to customer",
        "Create interactive menu for product selection",
        "List templates and send personalized promotional message",
        "Update business profile with hours and contact info",
        "Mark messages as read after handling customer support",
        "Read recent messages from a chat and summarize them",
    ]

    @classmethod
    def get_config_model(cls):
        return WhatsAppNodeConfig

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Inbound WhatsApp message → the agent's user turn text + the sender
        chat id as conversation key (one conversation per chat).

        The chat id is surfaced VERBATIM with its @c.us/@lid/@s.whatsapp.net
        suffix so a send tool can pass it straight back as ``to`` — to_chat_id()
        passes @-suffixed ids through untouched. Without this the agent gets the
        raw WAHooks JSON, hand-builds an E.164 number, and mis-addresses the
        reply to a non-existent account (WAHA returns PENDING, never delivers).
        Non-message envelopes fall back to the base raw-JSON default.
        """
        # WAHooks 'message' envelope (QR-linked accounts) — the channel case.
        if output.get("event") == "message" and isinstance(output.get("payload"), dict):
            p = output["payload"]
            key = (p.get("_data") or {}).get("key") or {}
            chat_id = str(p.get("from") or key.get("remoteJid") or "").strip()
            if not chat_id:
                return super().resolve_agent_event(output)
            media = p.get("media") if isinstance(p.get("media"), dict) else {}
            has_media = bool(p.get("hasMedia") or media)
            # For media messages, body is the caption (may be empty).
            body = p.get("body") or p.get("caption") or (
                "[media message]" if has_media else "[non-text message]"
            )
            participant = str(key.get("participant") or "").strip()  # sender in a group
            header = f"WhatsApp message from {chat_id}"
            if participant and participant != chat_id:
                header += f" (sent by {participant})"
            media_note = ""
            if has_media:
                if media.get("rehosted") and media.get("url"):
                    desc = ", ".join(
                        str(x) for x in (media.get("mimetype"), media.get("filename")) if x
                    )
                    media_note = (
                        f"\nAttached media ({desc or 'unknown type'}): {media['url']}\n"
                        f"Download that URL (e.g. curl -o) to view or process the file — "
                        f"it is a public, unguessable link."
                    )
                else:
                    # Not rehosted: the provider URL is platform-authed and
                    # useless to the run — say so instead of dangling it.
                    media_note = (
                        "\n[The attached media could not be retrieved — ask the "
                        "sender to describe it or resend if its content matters.]"
                    )
            text = (
                f"{header}:\n{body}{media_note}\n\n"
                f"To reply, call a send tool with to={chat_id} "
                f"(pass this chat id exactly — do not convert it to a phone number)."
            )
            return {"text": text, "conversation_key": chat_id}

        # Meta Cloud API envelope — bare E.164 sender numbers.
        if output.get("object") == "whatsapp_business_account":
            try:
                value = output["entry"][0]["changes"][0]["value"]
                msg = (value.get("messages") or [])[0]
            except (KeyError, IndexError, TypeError):
                return super().resolve_agent_event(output)
            sender = str(msg.get("from") or "").strip()
            if not sender:
                return super().resolve_agent_event(output)
            body = (msg.get("text") or {}).get("body") or "[non-text message]"
            text = (
                f"WhatsApp message from {sender}:\n{body}\n\n"
                f"To reply, call a send tool with to={sender}."
            )
            return {"text": text, "conversation_key": sender}

        return super().resolve_agent_event(output)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Drop WAHooks events a receive_message trigger must never fire on.

        A QR-linked personal account receives EVERY WhatsApp Web event as a
        "message": contact stories (status@broadcast), Channel posts
        (@newsletter), and the account's own outgoing messages (fromMe) — an
        auto-reply workflow fed those DMs arbitrary contacts (incl. replying to
        their stories) and echoes itself. Group chats are opt-in via
        include_group_messages. Cloud API payloads (different envelope) pass
        through untouched.
        """
        if (config or {}).get("operation") != "receive_message":
            return True
        event_payload = payload.get("payload")
        if payload.get("event") != "message" or not isinstance(event_payload, dict):
            # A WAHooks envelope (event+session keys) that isn't a message is
            # control-plane traffic (session.status, …) — normally consumed by
            # handle_control_event before this filter; dropping it here too
            # means a missed control event can never fire the workflow as a
            # ghost trigger. Non-WAHooks shapes (Meta Cloud API) pass through.
            if "event" in payload and "session" in payload:
                return False
            return True

        key = (event_payload.get("_data") or {}).get("key") or {}
        if event_payload.get("fromMe") or key.get("fromMe"):
            return False
        chat_id = str(event_payload.get("from") or key.get("remoteJid") or "")
        if chat_id == "status@broadcast" or chat_id.endswith("@newsletter"):
            return False
        if chat_id.endswith("@g.us") and (config or {}).get("include_group_messages") != "true":
            return False
        return True

    @classmethod
    def trigger_fire_budget_channel(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[str]:
        """Budget receive_message fires per chat — bounds two-party echo loops
        (bot replies, the counterparty auto-responds, repeat) that no
        authorship filter can catch."""
        if (config or {}).get("operation") != "receive_message":
            return None
        event_payload = payload.get("payload")
        if payload.get("event") != "message" or not isinstance(event_payload, dict):
            return None
        key = (event_payload.get("_data") or {}).get("key") or {}
        return str(event_payload.get("from") or key.get("remoteJid") or "unknown")

    # Provider media URLs require a service credential and are not safe to hand
    # to a run. Rehost at delivery time, with caps that keep large media from
    # stalling the delivery path.
    MEDIA_REHOST_MAX_BYTES = 25 * 1024 * 1024
    MEDIA_REHOST_TIMEOUT_S = 20

    @classmethod
    async def transform_trigger_payload(
        cls, payload, config, *, pool, workflow_id, node_id
    ):
        """Rehost an inbound message's media to workflow resources (R2) and
        swap ``payload.media.url`` for the public capability URL the agent can
        actually download. Without rehosting, media reaches agents as an opaque
        placeholder with no fetchable content. Failures raise into the delivery seam,
        which keeps the original payload — the message still runs."""
        if payload.get("event") != "message":
            return None
        p = payload.get("payload") or {}
        media = p.get("media") or {}
        url = media.get("url")
        if not url or not isinstance(url, str):
            return None
        api_key = os.environ.get("WAHOOKS_API_KEY")
        if not api_key or not workflow_id:
            return None

        # The service credential must only be sent to its provider. The URL is
        # carried in an inbound payload, so validate the parsed origin
        # before attaching the bearer (also blocks private-network SSRF).
        assert_exact_url_origin(url, WAHOOKS_API_ORIGIN)

        owner = await pool.fetchrow(
            "SELECT owner_id, organization_id FROM workflows WHERE id = $1::uuid",
            workflow_id,
        )
        if not owner:
            return None

        chunks, total = [], 0
        async with guarded_async_client(timeout=cls.MEDIA_REHOST_TIMEOUT_S) as client:
            async with client.stream(
                "GET", url, headers={"Authorization": f"Bearer {api_key}"}
            ) as resp:
                resp.raise_for_status()
                content_type_header = resp.headers.get("content-type")
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > cls.MEDIA_REHOST_MAX_BYTES:
                        logger.warning(
                            f"[WhatsAppNode] Media exceeds rehost cap "
                            f"({cls.MEDIA_REHOST_MAX_BYTES} bytes) — delivering without content"
                        )
                        return None
                    chunks.append(chunk)
        body = b"".join(chunks)

        from utils.resource_store import create_resource_from_bytes

        mimetype = media.get("mimetype") or content_type_header or "application/octet-stream"
        filename = media.get("filename") or url.rsplit("/", 1)[-1] or "whatsapp-media"
        resource = await create_resource_from_bytes(
            user_id=str(owner["owner_id"]),
            workflow_id=str(workflow_id),
            node_id=node_id,
            organization_id=str(owner["organization_id"]) if owner["organization_id"] else None,
            body=body,
            content_type=mimetype,
            filename=filename,
            metadata={"source": "whatsapp_inbound_media"},
        )
        p["media"] = {
            **media,
            "url": resource["download_url"],
            "mimetype": mimetype,
            "filename": filename,
            "size": resource["size_bytes"],
            "rehosted": True,
            "resource_id": resource["resource_id"],
        }
        logger.info(
            f"[WhatsAppNode] Rehosted inbound media ({resource['size_bytes']} bytes, "
            f"{mimetype}) as resource {resource['resource_id']}"
        )
        return payload

    @classmethod
    async def handle_control_event(
        cls, payload, config, *, pool, workflow_id, node_id
    ):
        """Consume WAHooks ``session.status`` pushes: never a workflow run;
        a definitive death (FAILED/STOPPED) marks the moment the phone link
        died, so the owner is alerted instead of leaving the trigger falsely
        marked as healthy. The event names a WAHA session we can't map to a
        connection id, so before alerting we live-verify the node's OWN
        credential's connection — a stale registration delivering another
        session's death must not mis-flag a healthy credential."""
        if payload.get("event") != "session.status" or "session" not in payload:
            return None
        status = str((payload.get("payload") or {}).get("status") or "").upper()
        consumed = f"session.status {status or 'unknown'} consumed"
        if status not in ("FAILED", "STOPPED"):
            return consumed

        credential_id = ((config or {}).get("credentialIds") or {}).get("whatsapp_qr")
        if not credential_id:
            return f"{consumed} (no QR credential attached)"

        try:
            from utils.credentials import credential_metadata

            row = await pool.fetchrow(
                """SELECT (SELECT metadata FROM credentials WHERE id = $1::uuid) AS metadata,
                          (SELECT name FROM workflows WHERE id = $2::uuid) AS workflow_name""",
                credential_id, workflow_id,
            )
            connection_id = credential_metadata(row).get("connection_id") if row else None
            api_key = os.environ.get("WAHOOKS_API_KEY")
            if not (connection_id and api_key):
                return consumed

            from wahooks import WAHooks

            def _live_status():
                with WAHooks(api_key=api_key) as client:
                    return (client.get_connection(connection_id) or {}).get("status", "")

            live = await asyncio.wait_for(asyncio.to_thread(_live_status), timeout=5)
            if live == "connected":
                return f"{consumed} (credential connection healthy)"

            from utils.notifications import send_channel_disconnected_alert

            await send_channel_disconnected_alert(
                str(credential_id),
                provider_label="WhatsApp",
                session_status=live or status.lower(),
                workflow_id=workflow_id,
                workflow_name=row["workflow_name"] if row else None,
                pool=pool,
            )
            return f"{consumed} — owner alerted"
        except Exception as e:
            logger.warning(f"[WhatsAppNode] session.status handling failed: {e}")
            return consumed

    @classmethod
    async def cleanup_external_webhook(
        cls, pool, workflow_id, node_id, config, credentials=None
    ):
        """Clean up WAHooks webhook when node is removed or operation changes."""
        if not credentials or credentials.get("credential_type") != "whatsapp_qr":
            return
        connection_id = credentials.get("connection_id")
        if not connection_id:
            return
        api_key = os.environ.get("WAHOOKS_API_KEY")
        if not api_key:
            return
        try:
            webhook_id = config.get("webhook_id")
            if not webhook_id:
                return
            # Find the WAHooks webhook that points to our webhook URL and delete it
            from wahooks import WAHooks
            from utils.webhook_delivery import get_webhook_url

            our_url = get_webhook_url(webhook_id)

            def _delete_matching_webhook():
                with WAHooks(api_key=api_key) as client:
                    for wh in client.list_webhooks(connection_id):
                        if wh.get("url") == our_url:
                            client.delete_webhook(wh["id"])
                            return True
                return False

            if await asyncio.to_thread(_delete_matching_webhook):
                logger.info(
                    f"[WhatsAppNode] Deleted WAHooks webhook for connection {connection_id}"
                )
        except Exception as e:
            logger.warning(f"[WhatsAppNode] Failed to cleanup WAHooks webhook: {e}")

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load chat options for recipient/chat picker fields.

        QR credentials list the account's chats via WAHooks (offset-paginated;
        search delegates to load_paginated_options' paginate-and-filter). The
        Cloud API has no chat listing, so non-QR credentials get an empty set —
        allow_custom on the field keeps manual phone entry working.
        """
        if field_name not in ("to", "chat_id"):
            return {"options": [], "next_page_token": None}

        from nodes.core.dynamic_options import load_paginated_options, normalize_search

        connection_id = credential_data.get("connection_id")
        if not connection_id:
            if credential_data.get("credential_type") == "whatsapp_qr":
                raise ValueError("Reconnect WhatsApp via QR scan to load chats")
            return {"options": [], "next_page_token": None}

        api_key = os.environ.get("WAHOOKS_API_KEY")
        if not api_key:
            raise ValueError(
                "WhatsApp QR service is not configured; set WAHOOKS_API_KEY "
                "on this backend"
            )

        from wahooks import WAHooks

        page_size = 200

        def _fetch_contacts():
            from wahooks import WAHooks
            with WAHooks(api_key=api_key) as client:
                return client.get_contacts(connection_id, limit=1000)

        async def fetch_page(cursor):
            offset = int(cursor) if cursor else 0

            def _fetch():
                from wahooks import WAHooks
                with WAHooks(api_key=api_key) as client:
                    return client.get_chats(connection_id, limit=page_size, offset=offset)

            chats = await asyncio.to_thread(_fetch)
            last_page = len(chats) < page_size
            # Contacts fill two gaps chats can't: names for number-only chats,
            # and people with no chat history at all (contacts > chats on real
            # accounts). One fetch per load; appended after the final chats page.
            contacts = await asyncio.to_thread(_fetch_contacts) if last_page else []
            contact_names = {c.get("jid"): c.get("name") for c in contacts if c.get("jid")}
            seen = set()
            options = []
            for chat in chats:
                cid = chat.get("id")
                if not cid:
                    continue
                seen.add(cid)
                options.append({
                    "value": cid,
                    "label": chat.get("name") or contact_names.get(cid)
                    or cid.split("@")[0],
                    "metadata": {
                        "is_group": chat.get("isGroup", False),
                        "unread": chat.get("unread", False),
                    },
                })
            for c in contacts:
                jid = c.get("jid")
                if not jid or jid in seen or c.get("isGroup"):
                    continue
                options.append({
                    "value": jid,
                    "label": c.get("name") or c.get("phoneNumber") or jid.split("@")[0],
                    "metadata": {"is_group": False, "contact_only": True},
                })
            # Advance by what the server actually returned — it may cap below
            # page_size, and requested==returned is not a reliable end signal.
            next_cursor = None if last_page else str(offset + len(chats))
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=normalize_search(search),
            log_label="whatsapp_chats",
        )

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Load computed values for webhook fields.
        For QR credentials, auto-registers the webhook URL with WAHooks
        so incoming messages are forwarded to our webhook endpoint.
        """
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        # Create our internal webhook URL
        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        webhook_url = webhook_data.get("webhook_url")
        wahooks_registered = False

        # If QR credentials are selected, auto-register the webhook with WAHooks
        credential_id = (credential_ids or {}).get("whatsapp_qr")
        if credential_id and webhook_url:
            try:
                from utils.encryption import get_encryption

                encryption = get_encryption()

                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT credential FROM credentials WHERE id = $1 AND owner_id = $2",
                        credential_id,
                        user_id,
                    )
                    if row:
                        cred_data = encryption.decrypt_credential(row["credential"])
                        connection_id = cred_data.get("connection_id")

                        if connection_id:
                            api_key = os.environ.get("WAHOOKS_API_KEY")
                            if api_key:
                                # Registering on a definitively dead session
                                # would report success on a webhook that can
                                # never fire (the builder did exactly this on a
                                # 3-day-dead session). Unknown status (WAHooks
                                # unreachable) still registers — never dead on
                                # a non-definitive signal.
                                from utils.whatsapp_qr import dead_session_status

                                if dead := await dead_session_status(connection_id):
                                    logger.warning(
                                        f"[WhatsAppNode] NOT registering webhook: connection "
                                        f"{connection_id} session is {dead} — "
                                        f"credential needs a re-scan"
                                    )
                                else:
                                    await asyncio.to_thread(
                                        _wahooks_ensure_webhook, api_key, connection_id, webhook_url
                                    )
                                    wahooks_registered = True
                                    logger.info(
                                        f"[WhatsAppNode] WAHooks webhook registered for connection {connection_id}"
                                    )
            except Exception as e:
                logger.warning(
                    f"[WhatsAppNode] Failed to auto-register WAHooks webhook: {e}"
                )

        return {
            "values": {
                **webhook_data,
                "wahooks_registered": wahooks_registered,
            }
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute WhatsApp operation"""
        config = self.config
        if not config or not isinstance(config, WhatsAppNodeConfig):
            raise ValueError("WhatsApp configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "WhatsApp credentials required. Add your access token in the credentials tab."
            )

        op_config = config.config
        action = op_config.operation

        # Webhook trigger operations work the same for both credential types —
        # data comes from webhook payload, not from API calls. execute() only
        # runs WITHOUT a live delivery (real firings short-circuit via
        # resolve_trigger_payload), so this is the manual/test path: the one
        # chance to tell the user the truth about whether events CAN arrive.
        if action == "receive_message":
            if isinstance(credentials, WhatsAppQRCredential):
                conn_id = credentials.connection_id

                # Definitively dead session = messages can never arrive; fail
                # the manual run loudly instead of returning a green no-event.
                from utils.whatsapp_qr import dead_session_status

                if dead := await dead_session_status(conn_id):
                    raise ValueError(
                        f"WhatsApp connection is dead (session {dead}) — "
                        f"incoming messages cannot reach this trigger. Re-scan the QR "
                        f"code for THIS WhatsApp credential to reconnect it; do NOT "
                        f"create a new credential (repeated fresh scans can get all "
                        f"of the phone's links logged out by WhatsApp)."
                    )

                webhook_url = getattr(op_config, "webhook_url", None)
                if webhook_url:
                    try:
                        api_key = os.environ.get("WAHOOKS_API_KEY")
                        if api_key and await asyncio.to_thread(
                            _wahooks_ensure_webhook, api_key, conn_id, webhook_url
                        ):
                            logger.info(
                                f"[WhatsAppNode] Re-registered WAHooks webhook for connection {conn_id}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[WhatsAppNode] Failed to verify WAHooks webhook: {e}"
                        )
            # Real firings never reach here — the payload short-circuits in
            # resolve_trigger_payload, so execute() is always the no-event path.
            return self.no_event_output(
                "receive_message",
                "To test: send a WhatsApp message to the connected number from "
                "ANOTHER phone (own/self messages are filtered as fromMe), or mock "
                "this node's output.",
            )
        elif action == "receive_status_update":
            return self.no_event_output("receive_status_update")

        # Route to WAHooks handler for QR scan credentials
        if isinstance(credentials, WhatsAppQRCredential):
            return await self._execute_wahooks(op_config, credentials)

        qr_only_actions = {
            "list_recent_chats",
            "get_chat_messages",
            "list_contacts",
            "edit_message",
            "mark_chat_read",
            "get_account_profile",
        }
        if action in qr_only_actions:
            raise ValueError(
                f"The '{action}' operation requires a WhatsApp QR credential "
                "(the Meta Cloud API has no chat/message read access)."
            )

        # Route to appropriate handler
        if action == "send_text_message":
            return await self._handle_send_text(op_config, credentials)
        elif action == "send_template_message":
            return await self._handle_send_template(op_config, credentials)
        elif action == "send_image_message":
            return await self._handle_send_image(op_config, credentials)
        elif action == "send_video_message":
            return await self._handle_send_video(op_config, credentials)
        elif action == "send_document_message":
            return await self._handle_send_document(op_config, credentials)
        elif action == "send_audio_message":
            return await self._handle_send_audio(op_config, credentials)
        elif action == "send_location_message":
            return await self._handle_send_location(op_config, credentials)
        elif action == "send_contact_card":
            return await self._handle_send_contact(op_config, credentials)
        elif action == "send_interactive_buttons":
            return await self._handle_send_buttons(op_config, credentials)
        elif action == "send_interactive_list":
            return await self._handle_send_list(op_config, credentials)
        elif action == "send_reaction_emoji":
            return await self._handle_send_reaction(op_config, credentials)
        elif action == "mark_message_read":
            return await self._handle_mark_read(op_config, credentials)
        elif action == "upload_media":
            return await self._handle_upload_media(op_config, credentials)
        elif action == "get_media_url":
            return await self._handle_get_media_url(op_config, credentials)
        elif action == "download_media":
            return await self._handle_download_media(op_config, credentials)
        elif action == "delete_media":
            return await self._handle_delete_media(op_config, credentials)
        elif action == "get_business_profile":
            return await self._handle_get_business_profile(op_config, credentials)
        elif action == "update_business_profile":
            return await self._handle_update_business_profile(op_config, credentials)
        elif action == "register_phone_number":
            return await self._handle_register_phone(op_config, credentials)
        elif action == "request_verification_code":
            return await self._handle_request_code(op_config, credentials)
        elif action == "get_phone_number_info":
            return await self._handle_get_phone_info(op_config, credentials)
        elif action == "list_message_templates":
            return await self._handle_list_templates(op_config, credentials)
        elif action == "get_message_template":
            return await self._handle_get_template(op_config, credentials)
        elif action == "create_message_template":
            return await self._handle_create_template(op_config, credentials)
        elif action == "delete_message_template":
            return await self._handle_delete_template(op_config, credentials)
        elif action == "send_catalog_message":
            return await self._handle_send_catalog(op_config, credentials)
        elif action == "send_product_message":
            return await self._handle_send_product(op_config, credentials)
        elif action == "send_multi_product_message":
            return await self._handle_send_multi_product(op_config, credentials)
        elif action == "get_account_info":
            return await self._handle_get_account_info(op_config, credentials)
        elif action == "list_account_phone_numbers":
            return await self._handle_list_phone_numbers(op_config, credentials)
        raise ValueError(f"Unknown WhatsApp action: {action}")

    async def _execute_wahooks(
        self, op_config, credentials: WhatsAppQRCredential
    ) -> Dict[str, Any]:
        """Execute WhatsApp operation via WAHooks API (v0.3.1+)"""
        from wahooks import WAHooks, WAHooksError

        action = op_config.operation

        supported_actions = {
            "send_text_message",
            "send_image_message",
            "send_video_message",
            "send_document_message",
            "send_audio_message",
            "send_location_message",
            "send_contact_card",
            "send_reaction_emoji",
            "list_recent_chats",
            "get_chat_messages",
            "list_contacts",
            "edit_message",
            "mark_chat_read",
            "get_account_profile",
        }
        if action not in supported_actions:
            raise ValueError(
                f"The '{action}' operation requires Meta Cloud API credentials (Access Token). "
                f"QR scan credentials support: {', '.join(sorted(supported_actions))}"
            )

        # Convert a phone number ("+12025550100") to a WAHooks chat id. Ids that
        # already carry a server suffix (@c.us / @g.us / @lid / @s.whatsapp.net —
        # e.g. picked from the chat dropdown or a trigger payload) pass through;
        # the server accepts all of them.
        def to_chat_id(phone: str) -> str:
            if "@" in phone:
                return phone
            return (
                phone.lstrip("+").replace(" ", "").replace("-", "") + "@s.whatsapp.net"
            )

        start_time = time.time()
        try:
            api_key = os.environ.get("WAHOOKS_API_KEY")
            if not api_key:
                raise ValueError(
                    "WhatsApp QR service is not configured; set WAHOOKS_API_KEY "
                    "on this backend"
                )
            conn_id = credentials.connection_id

            # wahooks==0.10.0 ships only a synchronous httpx client; run the
            # blocking call off the event loop so a slow WhatsApp API request
            # can't freeze every other coroutine in the container.
            def _run_wahooks_op():
                with WAHooks(api_key=api_key) as client:
                    if action == "list_recent_chats":
                        res = client.get_chats(
                            conn_id,
                            limit=op_config.limit,
                            unread_only=op_config.unread_only == "true",
                        )
                        if isinstance(res, list):
                            res = {"chats": res, "count": len(res)}
                        return res
                    if action == "get_chat_messages":
                        page = client.get_messages(
                            conn_id,
                            to_chat_id(op_config.chat_id),
                            limit=op_config.limit,
                            before=op_config.before or None,
                        )
                        return {
                            "messages": page.get("messages", []),
                            "next_before": page.get("nextBefore"),
                            "history_starts_at": page.get("historyStartsAt"),
                        }
                    if action == "list_contacts":
                        res = client.get_contacts(conn_id, limit=op_config.limit)
                        if isinstance(res, list):
                            res = {"contacts": res, "count": len(res)}
                        return res
                    if action == "edit_message":
                        return client.edit_message(
                            conn_id,
                            op_config.message_id,
                            to_chat_id(op_config.chat_id),
                            op_config.body,
                        )
                    if action == "mark_chat_read":
                        return client.mark_read(conn_id, to_chat_id(op_config.chat_id))
                    if action == "get_account_profile":
                        return client.get_profile(conn_id)
                    # Send operations require a recipient
                    chat_id = to_chat_id(op_config.to)
                    if action == "send_reaction_emoji":
                        return client.react(
                            conn_id,
                            chat_id=chat_id,
                            message_id=op_config.message_id,
                            reaction=op_config.emoji,
                        )
                    if action == "send_text_message":
                        return client.send_message(
                            conn_id,
                            chat_id=chat_id,
                            text=op_config.body,
                            reply_to=op_config.reply_to_message_id or None,
                        )
                    if action == "send_image_message":
                        return client.send_image(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.image_url or op_config.media_id,
                            caption=getattr(op_config, "caption", None),
                        )
                    if action == "send_video_message":
                        return client.send_video(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.video_url or op_config.media_id,
                            caption=getattr(op_config, "caption", None),
                        )
                    if action == "send_document_message":
                        return client.send_document(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.document_url or op_config.media_id,
                            filename=getattr(op_config, "filename", None),
                            caption=getattr(op_config, "caption", None),
                        )
                    if action == "send_audio_message":
                        return client.send_audio(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.audio_url or op_config.media_id,
                        )
                    if action == "send_location_message":
                        return client.send_location(
                            conn_id,
                            chat_id=chat_id,
                            latitude=float(op_config.latitude),
                            longitude=float(op_config.longitude),
                            name=getattr(op_config, "name", None),
                            address=getattr(op_config, "address", None),
                        )
                    if action == "send_contact_card":
                        return client.send_contact(
                            conn_id,
                            chat_id=chat_id,
                            contact_name=op_config.contact_name,
                            contact_phone=op_config.contact_phone,
                        )

            result = await asyncio.to_thread(_run_wahooks_op)

            api_time = (time.time() - start_time) * 1000
            return {
                "status": "success",
                "action": action,
                "data": result if isinstance(result, dict) else {"result": result},
                "provider": "wahooks",
                "timing_ms": {"api_request": round(api_time, 2)},
            }

        except WAHooksError as e:
            api_time = (time.time() - start_time) * 1000
            return {
                "status": "error",
                "action": action,
                "error": str(e),
                "error_code": getattr(e, "status_code", None),
                "provider": "wahooks",
                "timing_ms": {"api_request": round(api_time, 2)},
            }
        except Exception as e:
            api_time = (time.time() - start_time) * 1000
            return {
                "status": "error",
                "action": action,
                "error": str(e),
                "provider": "wahooks",
                "timing_ms": {"api_request": round(api_time, 2)},
            }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: WhatsAppAccessTokenCredential,  # Only for Cloud API calls
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make authenticated request to WhatsApp API"""
        url = f"{WHATSAPP_API_BASE}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "Content-Type": "application/json",
        }

        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                # Handle successful responses
                if response.status_code in [200, 201]:
                    return {
                        "status": "success",
                        "action": action_name,
                        "data": response.json() if response.text else {},
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Handle errors
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    error_data = {"message": response.text}

                error_message = error_data.get("error", {}).get(
                    "message", str(error_data)
                )
                error_code = error_data.get("error", {}).get(
                    "code", response.status_code
                )

                return {
                    "status": "error",
                    "action": action_name,
                    "error": error_message,
                    "error_code": error_code,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timeout (30s)",
                "timing_ms": {
                    "api_request": round((time.time() - start_time) * 1000, 2)
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "action": action_name,
                "error": str(e),
                "timing_ms": {
                    "api_request": round((time.time() - start_time) * 1000, 2)
                },
            }

    # ========================================================================
    # Messaging Handlers
    # ========================================================================

    async def _handle_send_text(
        self, config: WhatsAppSendTextConfig, credentials: WhatsAppAccessTokenCredential
    ) -> Dict[str, Any]:
        """Send text message"""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": config.to,
            "type": "text",
            "text": {"preview_url": config.preview_url, "body": config.body},
        }
        if config.reply_to_message_id:
            payload["context"] = {"message_id": config.reply_to_message_id}

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_text_message",
        )

    async def _handle_send_template(
        self,
        config: WhatsAppSendTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send template message"""
        template_params = []
        if config.parameters:
            try:
                template_params = json.loads(config.parameters)
            except:
                template_params = []

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "template",
            "template": {
                "name": config.template_name,
                "language": {"code": config.language_code},
            },
        }

        if template_params:
            payload["template"]["components"] = [
                {"type": "body", "parameters": template_params}
            ]

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_template_message",
        )

    async def _handle_send_image(
        self,
        config: WhatsAppSendImageConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send image message"""
        image_obj = {}
        if config.image_url:
            image_obj["link"] = config.image_url
        elif config.media_id:
            image_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either image_url or media_id is required",
            }

        if config.caption:
            image_obj["caption"] = config.caption

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "image",
            "image": image_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_image_message",
        )

    async def _handle_send_video(
        self,
        config: WhatsAppSendVideoConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send video message"""
        video_obj = {}
        if config.video_url:
            video_obj["link"] = config.video_url
        elif config.media_id:
            video_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either video_url or media_id is required",
            }

        if config.caption:
            video_obj["caption"] = config.caption

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "video",
            "video": video_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_video_message",
        )

    async def _handle_send_document(
        self,
        config: WhatsAppSendDocumentConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send document message"""
        document_obj = {}
        if config.document_url:
            document_obj["link"] = config.document_url
        elif config.media_id:
            document_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either document_url or media_id is required",
            }

        if config.filename:
            document_obj["filename"] = config.filename
        if config.caption:
            document_obj["caption"] = config.caption

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "document",
            "document": document_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_document_message",
        )

    async def _handle_send_audio(
        self,
        config: WhatsAppSendAudioConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send audio message"""
        audio_obj = {}
        if config.audio_url:
            audio_obj["link"] = config.audio_url
        elif config.media_id:
            audio_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either audio_url or media_id is required",
            }

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "audio",
            "audio": audio_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_audio_message",
        )

    async def _handle_send_location(
        self,
        config: WhatsAppSendLocationConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send location message"""
        location_obj = {"latitude": config.latitude, "longitude": config.longitude}

        if config.name:
            location_obj["name"] = config.name
        if config.address:
            location_obj["address"] = config.address

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "location",
            "location": location_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_location_message",
        )

    async def _handle_send_contact(
        self,
        config: WhatsAppSendContactConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send contact card message"""
        contact_obj = {
            "name": {
                "formatted_name": config.contact_name,
                "first_name": config.contact_name.split()[0]
                if " " in config.contact_name
                else config.contact_name,
            },
            "phones": [{"phone": config.contact_phone, "type": "MOBILE"}],
        }

        if config.contact_email:
            contact_obj["emails"] = [{"email": config.contact_email, "type": "WORK"}]

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "contacts",
            "contacts": [contact_obj],
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_contact_card",
        )

    async def _handle_send_buttons(
        self,
        config: WhatsAppSendButtonsConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send interactive message with buttons"""
        try:
            buttons = json.loads(config.buttons)
        except:
            return {"status": "error", "error": "Invalid buttons JSON format"}

        interactive_obj = {
            "type": "button",
            "body": {"text": config.body},
            "action": {"buttons": buttons},
        }

        if config.header:
            interactive_obj["header"] = {"type": "text", "text": config.header}
        if config.footer:
            interactive_obj["footer"] = {"text": config.footer}

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_interactive_buttons",
        )

    async def _handle_send_list(
        self, config: WhatsAppSendListConfig, credentials: WhatsAppAccessTokenCredential
    ) -> Dict[str, Any]:
        """Send interactive list message"""
        try:
            sections = json.loads(config.sections)
        except:
            return {"status": "error", "error": "Invalid sections JSON format"}

        interactive_obj = {
            "type": "list",
            "body": {"text": config.body},
            "action": {"button": config.button_text, "sections": sections},
        }

        if config.header:
            interactive_obj["header"] = {"type": "text", "text": config.header}
        if config.footer:
            interactive_obj["footer"] = {"text": config.footer}

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_interactive_list",
        )

    async def _handle_send_reaction(
        self,
        config: WhatsAppSendReactionConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send reaction to a message"""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": config.to,
            "type": "reaction",
            "reaction": {"message_id": config.message_id, "emoji": config.emoji},
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_reaction_emoji",
        )

    async def _handle_mark_read(
        self, config: WhatsAppMarkReadConfig, credentials: WhatsAppAccessTokenCredential
    ) -> Dict[str, Any]:
        """Mark message as read"""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": config.message_id,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="mark_message_read",
        )

    # ========================================================================
    # Media Management Handlers
    # ========================================================================

    async def _handle_upload_media(
        self,
        config: WhatsAppUploadMediaConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Upload media to WhatsApp — multipart binary upload to the /media endpoint."""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(
            config.media_url, default_mime=config.media_type
        )
        # WhatsApp keys media on the declared MIME type; honor the chosen media_type.
        mime = config.media_type or resolved.mime_type

        url = f"{WHATSAPP_API_BASE}/{credentials.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {credentials.access_token}"}
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    data={"messaging_product": "whatsapp", "type": mime},
                    files={"file": (resolved.filename, resolved.data, mime)},
                )
                api_time = (time.time() - start_time) * 1000

                if response.status_code in [200, 201]:
                    return {
                        "status": "success",
                        "action": "upload_media",
                        "data": response.json() if response.text else {},
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                error_data = {}
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {"message": response.text}
                error_message = error_data.get("error", {}).get(
                    "message", str(error_data)
                )
                error_code = error_data.get("error", {}).get(
                    "code", response.status_code
                )
                return {
                    "status": "error",
                    "action": "upload_media",
                    "error": error_message,
                    "error_code": error_code,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": "upload_media",
                "error": "Request timeout (120s)",
                "timing_ms": {
                    "api_request": round((time.time() - start_time) * 1000, 2)
                },
            }

    async def _handle_get_media_url(
        self,
        config: WhatsAppGetMediaUrlConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get media URL from media ID"""
        return await self._make_request(
            "GET", config.media_id, credentials, action_name="get_media_url"
        )

    async def _handle_download_media(
        self,
        config: WhatsAppDownloadMediaConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Download media file"""
        # Download binary data from media URL
        try:
            # Meta's get-media endpoint returns a short-lived URL on this
            # code-owned media origin. Never attach the WhatsApp bearer to an
            # arbitrary URL copied into the hidden operation config.
            assert_exact_url_origin(config.media_url, WHATSAPP_MEDIA_ORIGIN)
            async with guarded_async_client(timeout=60.0) as client:
                headers = {"Authorization": f"Bearer {credentials.access_token}"}
                response = await client.get(config.media_url, headers=headers)

                if response.status_code == 200:
                    import mimetypes

                    from nodes.core.binary_output import BinaryOutput

                    mime = (
                        response.headers.get("content-type")
                        or "application/octet-stream"
                    )
                    ext = mimetypes.guess_extension(mime.split(";")[0].strip()) or ""
                    return {
                        "status": "success",
                        "action": "download_media",
                        "data": {
                            "media": BinaryOutput(
                                data=response.content,
                                content_type=mime,
                                filename=f"whatsapp_media{ext}",
                            ),
                        },
                    }
                else:
                    return {
                        "status": "error",
                        "action": "download_media",
                        "error": f"Failed to download media: {response.status_code}",
                    }
        except Exception as e:
            return {"status": "error", "action": "download_media", "error": str(e)}

    async def _handle_delete_media(
        self,
        config: WhatsAppDeleteMediaConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Delete media from WhatsApp"""
        return await self._make_request(
            "DELETE", config.media_id, credentials, action_name="delete_media"
        )

    # ========================================================================
    # Business Profile Handlers
    # ========================================================================

    async def _handle_get_business_profile(
        self,
        config: WhatsAppGetBusinessProfileConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get business profile"""
        params = {"fields": config.fields}

        return await self._make_request(
            "GET",
            f"{credentials.phone_number_id}/whatsapp_business_profile",
            credentials,
            params=params,
            action_name="get_business_profile",
        )

    async def _handle_update_business_profile(
        self,
        config: WhatsAppUpdateBusinessProfileConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Update business profile"""
        payload = {"messaging_product": "whatsapp"}

        if config.about:
            payload["about"] = config.about
        if config.address:
            payload["address"] = config.address
        if config.description:
            payload["description"] = config.description
        if config.email:
            payload["email"] = config.email
        if config.vertical:
            payload["vertical"] = config.vertical
        if config.websites:
            payload["websites"] = [url.strip() for url in config.websites.split(",")]

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/whatsapp_business_profile",
            credentials,
            json_body=payload,
            action_name="update_business_profile",
        )

    # ========================================================================
    # Phone Number Handlers
    # ========================================================================

    async def _handle_register_phone(
        self,
        config: WhatsAppRegisterPhoneConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Register phone number"""
        payload = {"messaging_product": "whatsapp", "pin": config.pin}

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/register",
            credentials,
            json_body=payload,
            action_name="register_phone_number",
        )

    async def _handle_request_code(
        self,
        config: WhatsAppRequestCodeConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Request verification code"""
        payload = {"code_method": config.code_method, "language": config.language}

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/request_code",
            credentials,
            json_body=payload,
            action_name="request_verification_code",
        )

    async def _handle_get_phone_info(
        self,
        config: WhatsAppGetPhoneInfoConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get phone number info"""
        params = {"fields": config.fields}

        return await self._make_request(
            "GET",
            credentials.phone_number_id,
            credentials,
            params=params,
            action_name="get_phone_number_info",
        )

    # ========================================================================
    # Template Management Handlers
    # ========================================================================

    async def _handle_list_templates(
        self,
        config: WhatsAppListTemplatesConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """List message templates"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for template operations",
            }

        params = {"limit": config.limit}
        if config.status:
            params["status"] = config.status

        return await self._make_request(
            "GET",
            f"{credentials.business_account_id}/message_templates",
            credentials,
            params=params,
            action_name="list_message_templates",
        )

    async def _handle_get_template(
        self,
        config: WhatsAppGetTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get specific template"""
        return await self._make_request(
            "GET", config.template_id, credentials, action_name="get_message_template"
        )

    async def _handle_create_template(
        self,
        config: WhatsAppCreateTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Create message template"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for template operations",
            }

        components = [{"type": "BODY", "text": config.body}]

        if config.header:
            components.insert(
                0, {"type": "HEADER", "format": "TEXT", "text": config.header}
            )
        if config.footer:
            components.append({"type": "FOOTER", "text": config.footer})

        payload = {
            "name": config.name,
            "language": config.language,
            "category": config.category,
            "components": components,
        }

        return await self._make_request(
            "POST",
            f"{credentials.business_account_id}/message_templates",
            credentials,
            json_body=payload,
            action_name="create_message_template",
        )

    async def _handle_delete_template(
        self,
        config: WhatsAppDeleteTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Delete template"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for template operations",
            }

        params = {"name": config.template_name}

        return await self._make_request(
            "DELETE",
            f"{credentials.business_account_id}/message_templates",
            credentials,
            params=params,
            action_name="delete_message_template",
        )

    # ========================================================================
    # Commerce Handlers
    # ========================================================================

    async def _handle_send_catalog(
        self,
        config: WhatsAppSendCatalogConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send catalog message"""
        action_obj = {"name": "catalog_message"}

        if config.thumbnail_product_id:
            action_obj["parameters"] = {
                "thumbnail_product_retailer_id": config.thumbnail_product_id
            }

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": {
                "type": "catalog_message",
                "body": {"text": config.body},
                "action": action_obj,
            },
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_catalog_message",
        )

    async def _handle_send_product(
        self,
        config: WhatsAppSendProductConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send product message"""
        interactive_obj = {
            "type": "product",
            "action": {
                "catalog_id": config.catalog_id,
                "product_retailer_id": config.product_id,
            },
        }

        if config.body:
            interactive_obj["body"] = {"text": config.body}

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_product_message",
        )

    async def _handle_send_multi_product(
        self,
        config: WhatsAppSendMultiProductConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send multi-product message"""
        try:
            product_ids = json.loads(config.product_ids)
        except:
            return {"status": "error", "error": "Invalid product_ids JSON format"}

        sections = [
            {
                "title": config.header,
                "product_items": [{"product_retailer_id": pid} for pid in product_ids],
            }
        ]

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": {
                "type": "product_list",
                "header": {"type": "text", "text": config.header},
                "body": {"text": config.body},
                "action": {"catalog_id": config.catalog_id, "sections": sections},
            },
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_multi_product_message",
        )

    # ========================================================================
    # Account Management Handlers
    # ========================================================================

    async def _handle_get_account_info(
        self,
        config: WhatsAppGetAccountInfoConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get account info"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for account operations",
            }

        params = {"fields": config.fields}

        return await self._make_request(
            "GET",
            credentials.business_account_id,
            credentials,
            params=params,
            action_name="get_account_info",
        )

    async def _handle_list_phone_numbers(
        self,
        config: WhatsAppListPhoneNumbersConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """List phone numbers"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for account operations",
            }

        params = {
            "fields": "id,verified_name,display_phone_number,quality_rating,messaging_limit_tier",
            "limit": config.limit,
        }

        return await self._make_request(
            "GET",
            f"{credentials.business_account_id}/phone_numbers",
            credentials,
            params=params,
            action_name="list_account_phone_numbers",
        )

    # ========================================================================
    # Webhook Handlers
    # ========================================================================
