"""
Twilio Communications Platform automation node.

Provides comprehensive workflow integration with 70+ operations across:

**Messaging APIs**:
- SMS/MMS: Send messages, get status, list messages, delete messages, media management
- WhatsApp Business: Template messages, media messages, interactive messages
- Messaging Services: Create services, add senders, configure settings

**Voice APIs**:
- Programmable Voice: Make calls, get call details, list calls, update calls (redirect/hangup)
- Recordings: List recordings, get recording, delete recording, get transcription
- Conferences: List conferences, get details, list participants, update participants

**Verification & Lookup APIs**:
- Twilio Verify: Send verification codes (SMS/Voice/Email), check codes, create services
- Lookup API: Phone validation, carrier lookup, caller name (CNAM)

**Conversations API**:
- Conversations: Create conversations, list conversations, get details, delete
- Messages: Send messages, list messages
- Participants: Add/remove participants

**Phone Numbers API**:
- Available Numbers: Search for available phone numbers by area code/region
- Incoming Numbers: List owned numbers, purchase numbers, update configuration, release numbers

**SendGrid Email API** (Twilio-owned):
- Transactional Email: Send emails with templates, attachments, CC/BCC
- Email Templates: Create, update, delete email templates
- Email Statistics: Get delivery stats, bounce/spam reports

Authentication: Account SID + Auth Token, API Key + Secret, or SendGrid API Key
API Documentation: https://www.twilio.com/docs/api
Rate Limits: Vary by API and account type (typically 1-100 requests/second)
"""

import logging
import base64
from urllib.parse import parse_qsl, urlsplit
from typing import Dict, Any, Optional, List, Literal, Tuple, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.dynamic_options import load_paginated_options
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from utils.webhook_signatures import verify_twilio_signature

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

TWILIO_API_VERSION = "2010-04-01"
TWILIO_API_BASE = "https://api.twilio.com"
TWILIO_VERIFY_API_BASE = "https://verify.twilio.com/v2"
TWILIO_CONVERSATIONS_API_BASE = "https://conversations.twilio.com/v1"
TWILIO_LOOKUPS_API_BASE = "https://lookups.twilio.com/v2"
SENDGRID_API_BASE = "https://api.sendgrid.com/v3"


def _twilio_incoming_numbers_page_url(
    account_sid: str, cursor: Optional[str] = None
) -> str:
    """Resolve a Twilio ``next_page_uri`` without widening credential egress.

    The dynamic-options ``page_token`` is caller-controlled on subsequent
    requests. Twilio returns a relative URI, so accepting anything else before
    attaching Basic auth would let a token such as ``@attacker.example/path``
    turn string concatenation into an attacker origin.
    """
    expected_path = (
        f"/{TWILIO_API_VERSION}/Accounts/{account_sid}"
        "/IncomingPhoneNumbers.json"
    )
    if cursor is None:
        return f"{TWILIO_API_BASE}{expected_path}"

    if (
        not isinstance(cursor, str)
        or not cursor.startswith("/")
        or cursor.startswith("//")
        or "\\" in cursor
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in cursor)
    ):
        raise ValueError("Invalid Twilio pagination cursor")

    parsed = urlsplit(cursor)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or parsed.path != expected_path
    ):
        raise ValueError("Invalid Twilio pagination cursor")

    url = f"{TWILIO_API_BASE}{cursor}"
    final = urlsplit(url)
    if (
        final.scheme != "https"
        or final.netloc != "api.twilio.com"
        or final.hostname != "api.twilio.com"
        or final.username is not None
        or final.password is not None
        or final.path != expected_path
    ):
        raise ValueError("Invalid Twilio pagination cursor")
    return url


# ============================================================================
# Webhook trigger helpers
# ============================================================================


async def set_twilio_sms_webhook(
    account_sid: str, auth_token: str, phone_number_sid: str, sms_url: str
) -> None:
    """Point (or clear) a Twilio phone number's inbound-SMS webhook URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{TWILIO_API_BASE}/{TWILIO_API_VERSION}/Accounts/{account_sid}"
            f"/IncomingPhoneNumbers/{phone_number_sid}.json",
            auth=(account_sid, auth_token),
            data={"SmsUrl": sms_url, "SmsMethod": "POST"},
        )
        response.raise_for_status()


# ============================================================================
# Credential Schemas
# ============================================================================


class TwilioAccountCredential(BaseModel):
    """
    Account SID + Auth Token credential for Twilio APIs (recommended for most use cases).

    Get your credentials at: https://console.twilio.com/
    Navigate to: Console Dashboard → Account Info → Account SID & Auth Token

    This is the primary authentication method for all Twilio services except SendGrid.
    """

    credential_type: Literal["twilio_account"] = Field(
        "twilio_account", json_schema_extra={"ui:hidden": True}
    )
    account_sid: str = Field(
        ...,
        title="Account SID",
        description="Your Twilio Account SID (starts with AC)",
        json_schema_extra={"placeholder": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    auth_token: str = Field(
        ...,
        title="Auth Token",
        description="Your Twilio Auth Token from the console",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.twilio.com/",
            "x-credential-instructions": "Navigate to Console Dashboard → Account Info section → Copy Account SID and Auth Token",
        }
    )


class TwilioAPIKeyCredential(BaseModel):
    """
    API Key + Secret credential for Twilio APIs (recommended for production/multi-user apps).

    Create API keys at: https://console.twilio.com/us1/account/keys-credentials/api-keys
    Navigate to: Console → Account → API Keys & Tokens → Create API Key

    Benefits over Auth Token:
    - Can create multiple keys per account
    - Independent revocation (don't need to rotate main Auth Token)
    - Better security for server-to-server communication
    """

    credential_type: Literal["twilio_api_key"] = Field(
        "twilio_api_key", json_schema_extra={"ui:hidden": True}
    )
    account_sid: str = Field(
        ...,
        title="Account SID",
        description="Your Twilio Account SID (starts with AC)",
        json_schema_extra={"placeholder": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    api_key_sid: str = Field(
        ...,
        title="API Key SID",
        description="Your API Key SID (starts with SK)",
        json_schema_extra={"placeholder": "SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    api_key_secret: str = Field(
        ...,
        title="API Key Secret",
        description="Your API Key Secret (shown only once when created)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://console.twilio.com/us1/account/keys-credentials/api-keys",
            "x-credential-instructions": "Navigate to Console → API Keys & Tokens → Create API Key → Save the API Key SID and Secret (secret is shown only once)",
        }
    )


class SendGridAPIKeyCredential(BaseModel):
    """
    SendGrid API Key credential for SendGrid Email API (Twilio-owned email service).

    Get your API key at: https://app.sendgrid.com/settings/api_keys
    Navigate to: Settings → API Keys → Create API Key

    Note: SendGrid uses a separate authentication system from Twilio's main APIs.
    Create a 'Restricted Access' key with only the permissions you need.
    """

    credential_type: Literal["sendgrid_api_key"] = Field(
        "sendgrid_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="SendGrid API Key",
        description="Your SendGrid API key (starts with SG.)",
        json_schema_extra={
            "ui:widget": "password",
            "placeholder": "SG.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.sendgrid.com/settings/api_keys",
            "x-credential-instructions": "Navigate to Settings → API Keys → Create API Key → Select 'Restricted Access' → Grant 'Mail Send' permission → Generate & View",
        }
    )


# Union of all credential types - Account SID shown first (most common), then API Key, then SendGrid
TwilioCredential = Union[
    TwilioAccountCredential, TwilioAPIKeyCredential, SendGridAPIKeyCredential
]


# ============================================================================
# SMS/MMS Messaging Operations
# ============================================================================


class TwilioSendSMSConfig(BaseModel):
    """Send an SMS or MMS message via Twilio Messaging API"""

    model_config = ConfigDict(title="Send SMS")

    operation: Literal["send_sms_message"] = Field(
        "send_sms_message",
        json_schema_extra={
            "const": "send_sms_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Sms Message",
        },
        title="Send Sms Message",
    )
    from_number: str = Field(
        ...,
        title="From Number",
        description="Your Twilio phone number in E.164 format (e.g., +12025550100)",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    to_number: str = Field(
        ...,
        title="To Number",
        description="Recipient's phone number in E.164 format (e.g., +1987654321)",
        json_schema_extra={"placeholder": "+1987654321"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Text content of the message (up to 1600 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    media_url: Optional[str] = Field(
        None,
        title="Media URL (Optional)",
        description="The media to send (for MMS) — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Supports images, videos, PDFs, etc.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*,video/*"},
    )
    status_callback: Optional[str] = Field(
        None,
        title="Status Callback URL (Optional)",
        description="Webhook URL to receive message delivery status updates",
    )


class TwilioGetMessageConfig(BaseModel):
    """Get details about a specific message by SID"""

    model_config = ConfigDict(title="Get Message")

    operation: Literal["get_message"] = Field(
        "get_message",
        json_schema_extra={
            "const": "get_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Message",
        },
        title="Get Message",
    )
    message_sid: str = Field(
        ...,
        title="Message SID",
        description="The unique identifier for the message (starts with MM or SM)",
        json_schema_extra={"placeholder": "SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


class TwilioListMessagesConfig(BaseModel):
    """List messages sent/received from your account with filters"""

    model_config = ConfigDict(title="List Messages")

    operation: Literal["list_messages"] = Field(
        "list_messages",
        json_schema_extra={
            "const": "list_messages",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List Messages",
        },
        title="List Messages",
    )
    to_number: Optional[str] = Field(
        None,
        title="To Number (Filter)",
        description="Filter by recipient phone number in E.164 format",
    )
    from_number: Optional[str] = Field(
        None,
        title="From Number (Filter)",
        description="Filter by sender phone number in E.164 format",
    )
    date_sent: Optional[str] = Field(
        None,
        title="Date Sent (Filter)",
        description="Filter by date sent (YYYY-MM-DD format)",
    )
    page_size: int = Field(
        20,
        title="Page Size",
        description="Number of messages to return (max 1000)",
        ge=1,
        le=1000,
    )


class TwilioDeleteMessageConfig(BaseModel):
    """Delete a message from your account (removes from logs)"""

    model_config = ConfigDict(title="Delete Message")

    operation: Literal["delete_message"] = Field(
        "delete_message",
        json_schema_extra={
            "const": "delete_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Message",
        },
        title="Delete Message",
    )
    message_sid: str = Field(
        ...,
        title="Message SID",
        description="The unique identifier for the message to delete",
        json_schema_extra={"placeholder": "SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


# ============================================================================
# WhatsApp Business Messaging Operations
# ============================================================================


class TwilioSendWhatsAppConfig(BaseModel):
    """Send a WhatsApp message via Twilio (template or session message)"""

    model_config = ConfigDict(title="Send WhatsApp")

    operation: Literal["send_whatsapp_message"] = Field(
        "send_whatsapp_message",
        json_schema_extra={
            "const": "send_whatsapp_message",
            "ui:hidden": True,
            "x-category": "WhatsApp Message",
            "x-is-trigger": False,
            "x-display-name": "Send Whatsapp Message",
        },
        title="Send Whatsapp Message",
    )
    from_number: str = Field(
        ...,
        title="From Number",
        description="Your Twilio WhatsApp number with 'whatsapp:' prefix (e.g., whatsapp:+14155238886)",
        json_schema_extra={"placeholder": "whatsapp:+14155238886"},
    )
    to_number: str = Field(
        ...,
        title="To Number",
        description="Recipient's WhatsApp number with 'whatsapp:' prefix (e.g., whatsapp:+1987654321)",
        json_schema_extra={"placeholder": "whatsapp:+1987654321"},
    )
    body: Optional[str] = Field(
        None,
        title="Message Body (Optional)",
        description="Text content (required for session messages, optional for templates)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    content_sid: Optional[str] = Field(
        None,
        title="Content SID (Template)",
        description="Pre-approved WhatsApp message template SID (starts with HX)",
        json_schema_extra={"placeholder": "HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    media_url: Optional[str] = Field(
        None,
        title="Media URL (Optional)",
        description="The media to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Supports images, videos, documents.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*,video/*"},
    )


class TwilioGetWhatsAppMessageConfig(BaseModel):
    """Get details about a specific WhatsApp message"""

    model_config = ConfigDict(title="Get WhatsApp Message")

    operation: Literal["get_whatsapp_message"] = Field(
        "get_whatsapp_message",
        json_schema_extra={
            "const": "get_whatsapp_message",
            "ui:hidden": True,
            "x-category": "WhatsApp Message",
            "x-is-trigger": False,
            "x-display-name": "Get Whatsapp Message",
        },
        title="Get Whatsapp Message",
    )
    message_sid: str = Field(
        ...,
        title="Message SID",
        description="The unique identifier for the WhatsApp message",
        json_schema_extra={"placeholder": "SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


# ============================================================================
# Voice Call Operations
# ============================================================================


class TwilioMakeCallConfig(BaseModel):
    """Make an outbound phone call with TwiML instructions"""

    model_config = ConfigDict(title="Make Call")

    operation: Literal["make_outbound_call"] = Field(
        "make_outbound_call",
        json_schema_extra={
            "const": "make_outbound_call",
            "ui:hidden": True,
            "x-category": "Call",
            "x-is-trigger": False,
            "x-display-name": "Make Outbound Call",
        },
        title="Make Outbound Call",
    )
    from_number: str = Field(
        ...,
        title="From Number",
        description="Your Twilio phone number in E.164 format (e.g., +12025550100)",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    to_number: str = Field(
        ...,
        title="To Number",
        description="Recipient's phone number in E.164 format (e.g., +1987654321)",
        json_schema_extra={"placeholder": "+1987654321"},
    )
    url: str = Field(
        ...,
        title="TwiML URL",
        description="URL that returns TwiML instructions for the call (e.g., play audio, say text)",
        json_schema_extra={"placeholder": "https://example.com/twiml"},
    )
    status_callback: Optional[str] = Field(
        None,
        title="Status Callback URL (Optional)",
        description="Webhook URL to receive call status updates (ringing, answered, completed)",
    )
    timeout: Optional[int] = Field(
        60,
        title="Timeout (Seconds)",
        description="Number of seconds to wait for an answer before giving up (max 600)",
        ge=1,
        le=600,
    )
    record: Optional[bool] = Field(
        False, title="Record Call", description="Enable call recording"
    )


class TwilioGetCallConfig(BaseModel):
    """Get details about a specific call by SID"""

    model_config = ConfigDict(title="Get Call")

    operation: Literal["get_call"] = Field(
        "get_call",
        json_schema_extra={
            "const": "get_call",
            "ui:hidden": True,
            "x-category": "Call",
            "x-is-trigger": False,
            "x-display-name": "Get Call",
        },
        title="Get Call",
    )
    call_sid: str = Field(
        ...,
        title="Call SID",
        description="The unique identifier for the call (starts with CA)",
        json_schema_extra={"placeholder": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


class TwilioListCallsConfig(BaseModel):
    """List calls made to/from your account with filters"""

    model_config = ConfigDict(title="List Calls")

    operation: Literal["list_calls"] = Field(
        "list_calls",
        json_schema_extra={
            "const": "list_calls",
            "ui:hidden": True,
            "x-category": "Call",
            "x-is-trigger": False,
            "x-display-name": "List Calls",
        },
        title="List Calls",
    )
    to_number: Optional[str] = Field(
        None, title="To Number (Filter)", description="Filter by recipient phone number"
    )
    from_number: Optional[str] = Field(
        None, title="From Number (Filter)", description="Filter by caller phone number"
    )
    status: Optional[
        Literal[
            "queued",
            "ringing",
            "in-progress",
            "completed",
            "failed",
            "busy",
            "no-answer",
            "canceled",
        ]
    ] = Field(None, title="Status (Filter)", description="Filter by call status")
    start_time: Optional[str] = Field(
        None,
        title="Start Time (Filter)",
        description="Filter by call start time (YYYY-MM-DD format)",
    )
    page_size: int = Field(
        20,
        title="Page Size",
        description="Number of calls to return (max 1000)",
        ge=1,
        le=1000,
    )


class TwilioUpdateCallConfig(BaseModel):
    """Update an in-progress call (redirect, hangup, or modify)"""

    model_config = ConfigDict(title="Update Call")

    operation: Literal["update_in_progress_call"] = Field(
        "update_in_progress_call",
        json_schema_extra={
            "const": "update_in_progress_call",
            "ui:hidden": True,
            "x-category": "Call",
            "x-is-trigger": False,
            "x-display-name": "Update in Progress Call",
        },
        title="Update in Progress Call",
    )
    call_sid: str = Field(
        ...,
        title="Call SID",
        description="The unique identifier for the call to update",
        json_schema_extra={"placeholder": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    url: Optional[str] = Field(
        None,
        title="New TwiML URL (Optional)",
        description="Redirect call to new TwiML instructions",
    )
    status: Optional[Literal["canceled", "completed"]] = Field(
        None,
        title="Status (Optional)",
        description="Set status to 'canceled' (hangup queued/ringing) or 'completed' (hangup in-progress)",
    )


# ============================================================================
# Recording Operations
# ============================================================================


class TwilioListRecordingsConfig(BaseModel):
    """List call recordings from your account"""

    model_config = ConfigDict(title="List Recordings")

    operation: Literal["list_call_recordings"] = Field(
        "list_call_recordings",
        json_schema_extra={
            "const": "list_call_recordings",
            "ui:hidden": True,
            "x-category": "Recording",
            "x-is-trigger": False,
            "x-display-name": "List Call Recordings",
        },
        title="List Call Recordings",
    )
    call_sid: Optional[str] = Field(
        None,
        title="Call SID (Filter)",
        description="Filter recordings by specific call",
    )
    date_created: Optional[str] = Field(
        None,
        title="Date Created (Filter)",
        description="Filter by creation date (YYYY-MM-DD format)",
    )
    page_size: int = Field(
        20,
        title="Page Size",
        description="Number of recordings to return (max 1000)",
        ge=1,
        le=1000,
    )


class TwilioGetRecordingConfig(BaseModel):
    """Get details about a specific recording"""

    model_config = ConfigDict(title="Get Recording")

    operation: Literal["get_call_recording"] = Field(
        "get_call_recording",
        json_schema_extra={
            "const": "get_call_recording",
            "ui:hidden": True,
            "x-category": "Recording",
            "x-is-trigger": False,
            "x-display-name": "Get Call Recording",
        },
        title="Get Call Recording",
    )
    recording_sid: str = Field(
        ...,
        title="Recording SID",
        description="The unique identifier for the recording (starts with RE)",
        json_schema_extra={"placeholder": "RExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


class TwilioDeleteRecordingConfig(BaseModel):
    """Delete a call recording from your account"""

    model_config = ConfigDict(title="Delete Recording")

    operation: Literal["delete_call_recording"] = Field(
        "delete_call_recording",
        json_schema_extra={
            "const": "delete_call_recording",
            "ui:hidden": True,
            "x-category": "Recording",
            "x-is-trigger": False,
            "x-display-name": "Delete Call Recording",
        },
        title="Delete Call Recording",
    )
    recording_sid: str = Field(
        ...,
        title="Recording SID",
        description="The unique identifier for the recording to delete",
        json_schema_extra={"placeholder": "RExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


# ============================================================================
# Conference Operations
# ============================================================================


class TwilioListConferencesConfig(BaseModel):
    """List conferences in your account"""

    model_config = ConfigDict(title="List Conferences")

    operation: Literal["list_conferences"] = Field(
        "list_conferences",
        json_schema_extra={
            "const": "list_conferences",
            "ui:hidden": True,
            "x-category": "Conference",
            "x-is-trigger": False,
            "x-display-name": "List Conferences",
        },
        title="List Conferences",
    )
    status: Optional[Literal["init", "in-progress", "completed"]] = Field(
        None, title="Status (Filter)", description="Filter by conference status"
    )
    friendly_name: Optional[str] = Field(
        None,
        title="Friendly Name (Filter)",
        description="Filter by conference friendly name",
    )
    page_size: int = Field(
        20,
        title="Page Size",
        description="Number of conferences to return (max 1000)",
        ge=1,
        le=1000,
    )


class TwilioGetConferenceConfig(BaseModel):
    """Get details about a specific conference"""

    model_config = ConfigDict(title="Get Conference")

    operation: Literal["get_conference"] = Field(
        "get_conference",
        json_schema_extra={
            "const": "get_conference",
            "ui:hidden": True,
            "x-category": "Conference",
            "x-is-trigger": False,
            "x-display-name": "Get Conference",
        },
        title="Get Conference",
    )
    conference_sid: str = Field(
        ...,
        title="Conference SID",
        description="The unique identifier for the conference (starts with CF)",
        json_schema_extra={"placeholder": "CFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


class TwilioListParticipantsConfig(BaseModel):
    """List participants in a conference"""

    model_config = ConfigDict(title="List Participants")

    operation: Literal["list_conference_participants"] = Field(
        "list_conference_participants",
        json_schema_extra={
            "const": "list_conference_participants",
            "ui:hidden": True,
            "x-category": "Conference",
            "x-is-trigger": False,
            "x-display-name": "List Conference Participants",
        },
        title="List Conference Participants",
    )
    conference_sid: str = Field(
        ...,
        title="Conference SID",
        description="The conference to list participants from",
        json_schema_extra={"placeholder": "CFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    muted: Optional[bool] = Field(
        None, title="Muted (Filter)", description="Filter by muted status (true/false)"
    )


class TwilioUpdateParticipantConfig(BaseModel):
    """Update a conference participant (mute, hold, kick)"""

    model_config = ConfigDict(title="Update Participant")

    operation: Literal["update_conference_participant"] = Field(
        "update_conference_participant",
        json_schema_extra={
            "const": "update_conference_participant",
            "ui:hidden": True,
            "x-category": "Conference",
            "x-is-trigger": False,
            "x-display-name": "Update Conference Participant",
        },
        title="Update Conference Participant",
    )
    conference_sid: str = Field(
        ...,
        title="Conference SID",
        description="The conference containing the participant",
        json_schema_extra={"placeholder": "CFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    call_sid: str = Field(
        ...,
        title="Participant Call SID",
        description="The call SID of the participant to update",
        json_schema_extra={"placeholder": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    muted: Optional[bool] = Field(
        None, title="Muted", description="Mute or unmute the participant"
    )
    hold: Optional[bool] = Field(
        None, title="Hold", description="Put participant on hold or take off hold"
    )


# ============================================================================
# Twilio Verify API Operations (2FA)
# ============================================================================


class TwilioStartVerificationConfig(BaseModel):
    """Send a verification code via SMS, Voice, or Email (Twilio Verify API)"""

    model_config = ConfigDict(title="Start Verification")

    operation: Literal["start_verification_code"] = Field(
        "start_verification_code",
        json_schema_extra={
            "const": "start_verification_code",
            "ui:hidden": True,
            "x-category": "Verification",
            "x-is-trigger": False,
            "x-display-name": "Start Verification Code",
        },
        title="Start Verification Code",
    )
    verify_service_sid: str = Field(
        ...,
        title="Verify Service SID",
        description="Your Twilio Verify service SID (create at console.twilio.com/verify)",
        json_schema_extra={"placeholder": "VAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    to: str = Field(
        ...,
        title="To (Phone/Email)",
        description="Phone number (E.164) or email address to send verification code",
        json_schema_extra={"placeholder": "+12025550100 or user@example.com"},
    )
    channel: Literal["sms", "call", "email"] = Field(
        "sms", title="Channel", description="Delivery method for verification code"
    )
    locale: Optional[str] = Field(
        "en",
        title="Locale",
        description="Language for the verification message (e.g., en, es, fr)",
        json_schema_extra={"placeholder": "en"},
    )


class TwilioCheckVerificationConfig(BaseModel):
    """Check if a verification code is correct (Twilio Verify API)"""

    model_config = ConfigDict(title="Check Verification")

    operation: Literal["check_verification_code"] = Field(
        "check_verification_code",
        json_schema_extra={
            "const": "check_verification_code",
            "ui:hidden": True,
            "x-category": "Verification",
            "x-is-trigger": False,
            "x-display-name": "Check Verification Code",
        },
        title="Check Verification Code",
    )
    verify_service_sid: str = Field(
        ...,
        title="Verify Service SID",
        description="Your Twilio Verify service SID",
        json_schema_extra={"placeholder": "VAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    to: str = Field(
        ...,
        title="To (Phone/Email)",
        description="The phone number or email that received the code",
        json_schema_extra={"placeholder": "+12025550100 or user@example.com"},
    )
    code: str = Field(
        ...,
        title="Verification Code",
        description="The code entered by the user",
        json_schema_extra={"placeholder": "123456"},
    )


# ============================================================================
# Lookup API Operations (Phone Validation)
# ============================================================================


class TwilioLookupPhoneNumberConfig(BaseModel):
    """Look up phone number information (carrier, line type, validation)"""

    model_config = ConfigDict(title="Lookup Phone Number")

    operation: Literal["lookup_phone_number_info"] = Field(
        "lookup_phone_number_info",
        json_schema_extra={
            "const": "lookup_phone_number_info",
            "ui:hidden": True,
            "x-category": "Phone Number",
            "x-is-trigger": False,
            "x-display-name": "Lookup Phone Number Info",
        },
        title="Lookup Phone Number Info",
    )
    phone_number: str = Field(
        ...,
        title="Phone Number",
        description="Phone number to look up in E.164 format (e.g., +12025550100)",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    type: Optional[str] = Field(
        None,
        title="Data Type (Optional)",
        description="Comma-separated list: validation, caller_name, line_type_intelligence, etc. (may incur charges)",
        json_schema_extra={"placeholder": "line_type_intelligence"},
    )


# ============================================================================
# Conversations API Operations
# ============================================================================


class TwilioCreateConversationConfig(BaseModel):
    """Create a new conversation (Conversations API)"""

    model_config = ConfigDict(title="Create Conversation")

    operation: Literal["create_conversation"] = Field(
        "create_conversation",
        json_schema_extra={
            "const": "create_conversation",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Create Conversation",
        },
        title="Create Conversation",
    )
    friendly_name: str = Field(
        ...,
        title="Friendly Name",
        description="Human-readable name for the conversation",
        json_schema_extra={"placeholder": "Customer Support - John Doe"},
    )
    unique_name: Optional[str] = Field(
        None,
        title="Unique Name (Optional)",
        description="Unique identifier for the conversation (e.g., user_123_support)",
    )


class TwilioListConversationsConfig(BaseModel):
    """List all conversations in your account"""

    model_config = ConfigDict(title="List Conversations")

    operation: Literal["list_conversations"] = Field(
        "list_conversations",
        json_schema_extra={
            "const": "list_conversations",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "List Conversations",
        },
        title="List Conversations",
    )
    page_size: int = Field(
        20,
        title="Page Size",
        description="Number of conversations to return (max 100)",
        ge=1,
        le=100,
    )


class TwilioGetConversationDetailsConfig(BaseModel):
    """Get details about a specific conversation"""

    model_config = ConfigDict(title="Get Conversation Details")

    operation: Literal["get_conversation"] = Field(
        "get_conversation",
        json_schema_extra={
            "const": "get_conversation",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation",
        },
        title="Get Conversation",
    )
    conversation_sid: str = Field(
        ...,
        title="Conversation SID",
        description="The unique identifier for the conversation (starts with CH)",
        json_schema_extra={"placeholder": "CHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


class TwilioSendConversationMessageConfig(BaseModel):
    """Send a message to a conversation"""

    model_config = ConfigDict(title="Send Conversation Message")

    operation: Literal["send_conversation_message"] = Field(
        "send_conversation_message",
        json_schema_extra={
            "const": "send_conversation_message",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Send Conversation Message",
        },
        title="Send Conversation Message",
    )
    conversation_sid: str = Field(
        ...,
        title="Conversation SID",
        description="The conversation to send the message to",
        json_schema_extra={"placeholder": "CHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Text content of the message",
        json_schema_extra={"ui:widget": "textarea"},
    )
    author: Optional[str] = Field(
        None,
        title="Author (Optional)",
        description="Display name of the message sender",
    )


class TwilioAddParticipantConfig(BaseModel):
    """Add a participant to a conversation (SMS, WhatsApp, or Chat)"""

    model_config = ConfigDict(title="Add Participant")

    operation: Literal["add_conversation_participant"] = Field(
        "add_conversation_participant",
        json_schema_extra={
            "const": "add_conversation_participant",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Add Conversation Participant",
        },
        title="Add Conversation Participant",
    )
    conversation_sid: str = Field(
        ...,
        title="Conversation SID",
        description="The conversation to add the participant to",
        json_schema_extra={"placeholder": "CHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    messaging_binding_address: str = Field(
        ...,
        title="Participant Address",
        description="Phone number (E.164) or WhatsApp number (whatsapp:+12025550100)",
        json_schema_extra={"placeholder": "+12025550100 or whatsapp:+12025550100"},
    )
    messaging_binding_proxy_address: Optional[str] = Field(
        None,
        title="Proxy Address (Optional)",
        description="Your Twilio phone number to use for this participant",
    )


class TwilioDeleteConversationConfig(BaseModel):
    """Delete a conversation"""

    model_config = ConfigDict(title="Delete Conversation")

    operation: Literal["delete_conversation"] = Field(
        "delete_conversation",
        json_schema_extra={
            "const": "delete_conversation",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Delete Conversation",
        },
        title="Delete Conversation",
    )
    conversation_sid: str = Field(
        ...,
        title="Conversation SID",
        description="The unique identifier for the conversation to delete",
        json_schema_extra={"placeholder": "CHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


# ============================================================================
# Phone Numbers API Operations
# ============================================================================


class TwilioSearchAvailableNumbersConfig(BaseModel):
    """Search for available phone numbers to purchase"""

    model_config = ConfigDict(title="Search Available Numbers")

    operation: Literal["search_available_phone_numbers"] = Field(
        "search_available_phone_numbers",
        json_schema_extra={
            "const": "search_available_phone_numbers",
            "ui:hidden": True,
            "x-category": "Phone Number",
            "x-is-trigger": False,
            "x-display-name": "Search Available Phone Numbers",
        },
        title="Search Available Phone Numbers",
    )
    country_code: str = Field(
        "US",
        title="Country Code",
        description="Two-letter country code (US, GB, CA, etc.)",
        json_schema_extra={"placeholder": "US"},
    )
    area_code: Optional[str] = Field(
        None,
        title="Area Code (Optional)",
        description="Filter by area code (e.g., 415, 212)",
    )
    contains: Optional[str] = Field(
        None,
        title="Contains (Optional)",
        description="Filter numbers containing this pattern (e.g., '555')",
    )
    sms_enabled: Optional[bool] = Field(
        True, title="SMS Enabled", description="Filter by SMS capability"
    )
    voice_enabled: Optional[bool] = Field(
        True, title="Voice Enabled", description="Filter by voice capability"
    )
    limit: int = Field(
        10,
        title="Limit",
        description="Number of results to return (max 100)",
        ge=1,
        le=100,
    )


class TwilioListIncomingNumbersConfig(BaseModel):
    """List phone numbers owned by your account"""

    model_config = ConfigDict(title="List Incoming Numbers")

    operation: Literal["list_owned_phone_numbers"] = Field(
        "list_owned_phone_numbers",
        json_schema_extra={
            "const": "list_owned_phone_numbers",
            "ui:hidden": True,
            "x-category": "Phone Number",
            "x-is-trigger": False,
            "x-display-name": "List Owned Phone Numbers",
        },
        title="List Owned Phone Numbers",
    )
    phone_number: Optional[str] = Field(
        None,
        title="Phone Number (Filter)",
        description="Filter by specific phone number",
    )
    friendly_name: Optional[str] = Field(
        None, title="Friendly Name (Filter)", description="Filter by friendly name"
    )
    page_size: int = Field(
        20,
        title="Page Size",
        description="Number of numbers to return (max 1000)",
        ge=1,
        le=1000,
    )


class TwilioPurchasePhoneNumberConfig(BaseModel):
    """Purchase an available phone number"""

    model_config = ConfigDict(title="Purchase Phone Number")

    operation: Literal["purchase_phone_number"] = Field(
        "purchase_phone_number",
        json_schema_extra={
            "const": "purchase_phone_number",
            "ui:hidden": True,
            "x-category": "Phone Number",
            "x-is-trigger": False,
            "x-display-name": "Purchase Phone Number",
        },
        title="Purchase Phone Number",
    )
    phone_number: str = Field(
        ...,
        title="Phone Number",
        description="The phone number to purchase in E.164 format (e.g., +12025550100)",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    friendly_name: Optional[str] = Field(
        None,
        title="Friendly Name (Optional)",
        description="Human-readable label for the number",
    )
    sms_url: Optional[str] = Field(
        None,
        title="SMS Webhook URL (Optional)",
        description="URL to call when an SMS is received",
    )
    voice_url: Optional[str] = Field(
        None,
        title="Voice Webhook URL (Optional)",
        description="URL to call when a call is received",
    )


class TwilioUpdatePhoneNumberConfig(BaseModel):
    """Update configuration for an owned phone number"""

    model_config = ConfigDict(title="Update Phone Number")

    operation: Literal["update_phone_number_configuration"] = Field(
        "update_phone_number_configuration",
        json_schema_extra={
            "const": "update_phone_number_configuration",
            "ui:hidden": True,
            "x-category": "Phone Number",
            "x-is-trigger": False,
            "x-display-name": "Update Phone Number Configuration",
        },
        title="Update Phone Number Configuration",
    )
    phone_number_sid: str = Field(
        ...,
        title="Phone Number SID",
        description="The SID of the phone number to update (starts with PN)",
        json_schema_extra={"placeholder": "PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    friendly_name: Optional[str] = Field(
        None, title="Friendly Name (Optional)", description="Update the friendly name"
    )
    sms_url: Optional[str] = Field(
        None,
        title="SMS Webhook URL (Optional)",
        description="Update the SMS webhook URL",
    )
    voice_url: Optional[str] = Field(
        None,
        title="Voice Webhook URL (Optional)",
        description="Update the voice webhook URL",
    )


class TwilioReleasePhoneNumberConfig(BaseModel):
    """Release (delete) a phone number from your account"""

    model_config = ConfigDict(title="Release Phone Number")

    operation: Literal["release_phone_number"] = Field(
        "release_phone_number",
        json_schema_extra={
            "const": "release_phone_number",
            "ui:hidden": True,
            "x-category": "Phone Number",
            "x-is-trigger": False,
            "x-display-name": "Release Phone Number",
        },
        title="Release Phone Number",
    )
    phone_number_sid: str = Field(
        ...,
        title="Phone Number SID",
        description="The SID of the phone number to release",
        json_schema_extra={"placeholder": "PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )


# ============================================================================
# SendGrid Email API Operations
# ============================================================================


class SendGridSendEmailConfig(BaseModel):
    """Send a transactional email via SendGrid Email API"""

    model_config = ConfigDict(title="Send Email")

    operation: Literal["send_sendgrid_transactional_email"] = Field(
        "send_sendgrid_transactional_email",
        json_schema_extra={
            "const": "send_sendgrid_transactional_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Send Sendgrid Transactional Email",
        },
        title="Send Sendgrid Transactional Email",
    )
    from_email: str = Field(
        ...,
        title="From Email",
        description="Sender's email address (must be verified in SendGrid)",
        json_schema_extra={"placeholder": "sender@example.com"},
    )
    from_name: Optional[str] = Field(
        None, title="From Name (Optional)", description="Sender's display name"
    )
    to_email: str = Field(
        ...,
        title="To Email",
        description="Recipient's email address",
        json_schema_extra={"placeholder": "recipient@example.com"},
    )
    to_name: Optional[str] = Field(
        None, title="To Name (Optional)", description="Recipient's display name"
    )
    subject: str = Field(..., title="Subject", description="Email subject line")
    html_content: Optional[str] = Field(
        None,
        title="HTML Content (Optional)",
        description="Email body in HTML format",
        json_schema_extra={"ui:widget": "textarea"},
    )
    text_content: Optional[str] = Field(
        None,
        title="Plain Text Content (Optional)",
        description="Email body in plain text format",
        json_schema_extra={"ui:widget": "textarea"},
    )
    cc_emails: Optional[str] = Field(
        None,
        title="CC Emails (Optional)",
        description="Comma-separated CC email addresses",
        json_schema_extra={"placeholder": "cc1@example.com,cc2@example.com"},
    )
    bcc_emails: Optional[str] = Field(
        None,
        title="BCC Emails (Optional)",
        description="Comma-separated BCC email addresses",
        json_schema_extra={"placeholder": "bcc1@example.com,bcc2@example.com"},
    )
    reply_to_email: Optional[str] = Field(
        None, title="Reply-To Email (Optional)", description="Email address for replies"
    )


class SendGridSendTemplateEmailConfig(BaseModel):
    """Send an email using a SendGrid template"""

    model_config = ConfigDict(title="Send Template Email")

    operation: Literal["send_sendgrid_template_email"] = Field(
        "send_sendgrid_template_email",
        json_schema_extra={
            "const": "send_sendgrid_template_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Send Sendgrid Template Email",
        },
        title="Send Sendgrid Template Email",
    )
    from_email: str = Field(
        ...,
        title="From Email",
        description="Sender's email address (must be verified)",
        json_schema_extra={"placeholder": "sender@example.com"},
    )
    to_email: str = Field(
        ...,
        title="To Email",
        description="Recipient's email address",
        json_schema_extra={"placeholder": "recipient@example.com"},
    )
    template_id: str = Field(
        ...,
        title="Template ID",
        description="SendGrid template ID (d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)",
        json_schema_extra={"placeholder": "d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    )
    dynamic_template_data: Optional[str] = Field(
        None,
        title="Template Data (JSON)",
        description='JSON object with template variables (e.g., {"name": "John", "order_id": "12345"})',
        json_schema_extra={"ui:widget": "textarea"},
    )


class SendGridGetEmailStatsConfig(BaseModel):
    """Get email delivery statistics from SendGrid"""

    model_config = ConfigDict(title="Get Email Stats")

    operation: Literal["get_sendgrid_email_stats"] = Field(
        "get_sendgrid_email_stats",
        json_schema_extra={
            "const": "get_sendgrid_email_stats",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Get Sendgrid Email Stats",
        },
        title="Get Sendgrid Email Stats",
    )
    start_date: str = Field(
        ...,
        title="Start Date",
        description="Start date for stats (YYYY-MM-DD format)",
        json_schema_extra={"placeholder": "2024-01-01"},
    )
    end_date: Optional[str] = Field(
        None,
        title="End Date (Optional)",
        description="End date for stats (defaults to today)",
        json_schema_extra={"placeholder": "2024-12-31"},
    )
    aggregated_by: Literal["day", "week", "month"] = Field(
        "day", title="Aggregated By", description="Time interval for aggregation"
    )


# ============================================================================
# Union Config Type (Discriminated Union for All Operations)
# ============================================================================

class TwilioOnIncomingSmsConfig(BaseModel):
    """Trigger: fires when an SMS is received by a Twilio phone number."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_incoming_sms"] = Field(
        "on_incoming_sms",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Incoming SMS",
        },
        title="On Incoming SMS",
    )
    phone_number_sid: str = Field(
        ...,
        title="Phone Number SID",
        description="SID of the Twilio number to receive SMS on (starts with PN)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "phone_number_sid",
                "placeholder": "Select a phone number...",
                "searchable": True,
                "allow_custom": True,
            },
            "x-resource-type": "twilio_phone_number",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


TwilioNodeConfig = Annotated[
    Union[
        # Trigger Operations
        TwilioOnIncomingSmsConfig,
        # SMS/MMS Operations
        TwilioSendSMSConfig,
        TwilioGetMessageConfig,
        TwilioListMessagesConfig,
        TwilioDeleteMessageConfig,
        # WhatsApp Operations
        TwilioSendWhatsAppConfig,
        TwilioGetWhatsAppMessageConfig,
        # Voice Call Operations
        TwilioMakeCallConfig,
        TwilioGetCallConfig,
        TwilioListCallsConfig,
        TwilioUpdateCallConfig,
        # Recording Operations
        TwilioListRecordingsConfig,
        TwilioGetRecordingConfig,
        TwilioDeleteRecordingConfig,
        # Conference Operations
        TwilioListConferencesConfig,
        TwilioGetConferenceConfig,
        TwilioListParticipantsConfig,
        TwilioUpdateParticipantConfig,
        # Verify API Operations
        TwilioStartVerificationConfig,
        TwilioCheckVerificationConfig,
        # Lookup API Operations
        TwilioLookupPhoneNumberConfig,
        # Conversations API Operations
        TwilioCreateConversationConfig,
        TwilioListConversationsConfig,
        TwilioGetConversationDetailsConfig,
        TwilioSendConversationMessageConfig,
        TwilioAddParticipantConfig,
        TwilioDeleteConversationConfig,
        # Phone Numbers API Operations
        TwilioSearchAvailableNumbersConfig,
        TwilioListIncomingNumbersConfig,
        TwilioPurchasePhoneNumberConfig,
        TwilioUpdatePhoneNumberConfig,
        TwilioReleasePhoneNumberConfig,
        # SendGrid Email API Operations
        SendGridSendEmailConfig,
        SendGridSendTemplateEmailConfig,
        SendGridGetEmailStatsConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Config (Config + Credentials)
# ============================================================================


class TwilioNodeFullConfig(NodeConfig):
    """Full configuration for Twilio automation node"""

    config: TwilioNodeConfig = Field(..., discriminator="operation")
    credentials: TwilioCredential


# ============================================================================
# Twilio Node Implementation
# ============================================================================


class TwilioNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """
    Twilio Communications Platform automation node.

    Supports 40+ operations across Messaging, Voice, WhatsApp, Verify, Lookup,
    Conversations, Phone Numbers, and SendGrid Email APIs.

    Authentication:
    - Account SID + Auth Token (primary)
    - API Key SID + Secret (recommended for production)
    - SendGrid API Key (for email operations only)
    """

    edit_examples = [
        "Send an SMS message to verify a user email address",
        "Make a voice call to alert support when an order ships",
        "Send WhatsApp template message for customer confirmation",
        "Search available phone numbers in area code 415",
        "Verify a 2FA code submitted by the customer",
        "Send a transactional email via SendGrid to order@example.com",
        "Create a conversation and add multiple participants",
    ]

    @classmethod
    def get_config_model(cls):
        return TwilioNodeFullConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic dropdown options for a field."""
        logger.info(f"[TwilioNode] load_field_options called: field={field_name}")
        if field_name == "phone_number_sid":
            return await cls._list_phone_number_options(
                credential_data, page_token=page_token, search=search
            )
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_phone_number_options(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List the user's owned Twilio phone numbers for dropdown options.

        Twilio's IncomingPhoneNumbers endpoint has no native name filter, so
        search mode paginates via ``next_page_uri`` until the shared safety
        cap and substring-filters server-side.
        """
        account_sid = (credential_data or {}).get("account_sid")
        auth_token = (credential_data or {}).get("auth_token")
        if not account_sid or not auth_token:
            raise ValueError("Connect a Twilio account to load phone numbers")

        list_url = _twilio_incoming_numbers_page_url(account_sid)

        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            # Twilio's next_page_uri is a relative path with its query baked in.
            # Resolve it through the exact-origin/path gate before attaching auth;
            # page 2+ therefore needs no separate ``params``.
            url = (
                _twilio_incoming_numbers_page_url(account_sid, cursor)
                if cursor
                else list_url
            )
            params = None if cursor else {"PageSize": 200}
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, auth=(account_sid, auth_token), params=params)
                response.raise_for_status()
                data = response.json()
            next_cursor = data.get("next_page_uri")
            if next_cursor:
                # Do not hand an unvalidated provider cursor to the browser (or
                # feed it into the in-call search pagination loop).
                _twilio_incoming_numbers_page_url(account_sid, next_cursor)
            options = [
                {
                    "value": num.get("sid"),
                    "label": num.get("friendly_name")
                    or num.get("phone_number")
                    or num.get("sid"),
                }
                for num in (data.get("incoming_phone_numbers") or [])
                if num.get("sid")
            ]
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=search,
            log_label="TwilioNode._list_phone_number_options",
        )

    # ========================================================================
    # Webhook Trigger (on_incoming_sms)
    # ========================================================================

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "phone_number_sid": (config or {}).get("phone_number_sid"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ) -> Dict[str, Any]:
        phone_sid = (config or {}).get("phone_number_sid")
        if not phone_sid:
            raise ValueError(
                "Set the Twilio phone number SID to activate this trigger"
            )
        credential = credential or {}
        account_sid = credential.get("account_sid")
        auth_token = credential.get("auth_token")
        if not account_sid or not auth_token:
            raise ValueError(
                "Twilio trigger requires an Account SID + Auth Token credential"
            )
        await set_twilio_sms_webhook(account_sid, auth_token, phone_sid, webhook_url)
        # The auth token is the X-Twilio-Signature signing key.
        return {"signing_secret": auth_token}

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential, config, node_id
    ) -> None:
        credential = credential or {}
        phone_sid = (config or {}).get("phone_number_sid")
        account_sid = credential.get("account_sid")
        auth_token = credential.get("auth_token")
        if not (phone_sid and account_sid and auth_token):
            return
        await set_twilio_sms_webhook(account_sid, auth_token, phone_sid, "")

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Twilio's ``X-Twilio-Signature`` over the form-encoded POST."""
        auth_token = (config or {}).get("signing_secret")
        url = (config or {}).get("webhook_url")
        if not auth_token or not url:
            return False
        form_params = dict(parse_qsl(body.decode("utf-8", errors="replace")))
        return verify_twilio_signature(
            url, form_params, auth_token, headers.get("x-twilio-signature", "")
        )

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        """Parse Twilio's form-encoded inbound-SMS body into named fields."""
        if not isinstance(payload, dict):
            return payload
        raw = payload.get("raw")
        if not raw:
            return payload
        parsed = dict(parse_qsl(raw))
        parsed["_webhook"] = payload.get("_webhook")
        return parsed

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Deliver an inbound SMS/WhatsApp message to a directly-wired agent.

        ``output`` is the parsed inbound webhook (see ``resolve_trigger_payload``):
        Twilio form fields ``From`` (sender, ``whatsapp:`` prefixed for WhatsApp),
        ``To`` (the Twilio number), and ``Body``. To reply you send FROM the Twilio
        number back TO the sender, so the sender (``From``) is surfaced verbatim as
        the reply id and the ck keys on the ``sender:twilio_number`` pair — the same
        contact texting two different business numbers is two conversations.
        """
        sender = str(output.get("From") or "").strip()
        if not sender:
            return super().resolve_agent_event(output)
        twilio_number = str(output.get("To") or "").strip()
        body = output.get("Body") or "[non-text message]"
        channel = "WhatsApp" if sender.lower().startswith("whatsapp:") else "SMS"
        text = (
            f"Twilio {channel} message from {sender} to your number {twilio_number}:\n{body}\n\n"
            f"To reply, call a send tool with to_number={sender} and from_number={twilio_number} "
            f"(pass both exactly, including any 'whatsapp:' prefix)."
        )
        return {"text": text, "conversation_key": f"{sender}:{twilio_number}"}

    @classmethod
    def webhook_ack_response(cls) -> Dict[str, str]:
        """Twilio expects a TwiML response; return an empty one."""
        return {
            "content": '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            "media_type": "application/xml",
        }

    def _get_basic_auth_header(self, credentials) -> str:
        """Generate Basic Authentication header for Twilio APIs"""
        if isinstance(credentials, TwilioAPIKeyCredential):
            creds_str = f"{credentials.api_key_sid}:{credentials.api_key_secret}"
        else:  # TwilioAccountCredential
            creds_str = f"{credentials.account_sid}:{credentials.auth_token}"

        encoded = base64.b64encode(creds_str.encode()).decode()
        return f"Basic {encoded}"

    def _get_sendgrid_auth_header(self, credentials: SendGridAPIKeyCredential) -> str:
        """Generate Bearer token header for SendGrid API"""
        return f"Bearer {credentials.api_key}"

    async def _make_twilio_request(
        self,
        method: str,
        endpoint: str,
        credentials,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        api_base: str = TWILIO_API_BASE,
    ) -> Dict[str, Any]:
        """Make an authenticated request to Twilio API"""
        url = f"{api_base}/{endpoint}"

        headers = {"Authorization": self._get_basic_auth_header(credentials)}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=headers, params=params)
                elif method == "POST":
                    response = await client.post(
                        url, headers=headers, data=data, params=params
                    )
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

                # Handle 204 No Content responses (e.g., DELETE operations)
                if response.status_code == 204:
                    return {
                        "success": True,
                        "message": "Operation completed successfully",
                    }

                return response.json()

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Twilio API error: {e.response.status_code} - {e.response.text}"
                )
                raise Exception(
                    f"Twilio API error: {e.response.status_code} - {e.response.text}"
                )
            except Exception as e:
                logger.error(f"Request failed: {str(e)}")
                raise Exception(f"Request failed: {str(e)}")

    async def _make_sendgrid_request(
        self,
        method: str,
        endpoint: str,
        credentials: SendGridAPIKeyCredential,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated request to SendGrid API"""
        url = f"{SENDGRID_API_BASE}/{endpoint}"

        headers = {
            "Authorization": self._get_sendgrid_auth_header(credentials),
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=headers, params=params)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=json_data)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

                # SendGrid returns 202 Accepted for successful email sends
                if response.status_code == 202:
                    return {"success": True, "message": "Email queued for delivery"}

                return response.json() if response.text else {"success": True}

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"SendGrid API error: {e.response.status_code} - {e.response.text}"
                )
                raise Exception(
                    f"SendGrid API error: {e.response.status_code} - {e.response.text}"
                )
            except Exception as e:
                logger.error(f"Request failed: {str(e)}")
                raise Exception(f"Request failed: {str(e)}")

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the Twilio node operation"""
        logger.info(f"[TwilioNode] Executing node {self.node_id}")

        # Extract configuration
        node_config = self.config
        if not node_config or not isinstance(node_config, TwilioNodeFullConfig):
            raise ValueError("TwilioNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                "[TwilioNode] Credentials are required. "
                "Please add your Twilio credentials in the credentials tab."
            )

        # Extract account_sid for URL construction (needed for most Twilio APIs)
        if isinstance(credentials, SendGridAPIKeyCredential):
            account_sid = None  # SendGrid doesn't need account_sid
        elif isinstance(credentials, TwilioAPIKeyCredential):
            account_sid = credentials.account_sid
        else:  # TwilioAccountCredential
            account_sid = credentials.account_sid

        action = config.operation

        # ========== Trigger Operations ==========
        if action == "on_incoming_sms":
            return {
                "message": (
                    "This trigger fires when an SMS is received by the Twilio "
                    "number. It outputs the parsed inbound message fields "
                    "(From, To, Body, ...)."
                ),
                "phone_number_sid": config.phone_number_sid,
            }

        # ========== SMS/MMS Operations ==========
        if action == "send_sms_message":
            typed_config: TwilioSendSMSConfig = config
            data = {
                "From": typed_config.from_number,
                "To": typed_config.to_number,
                "Body": typed_config.body,
            }
            if typed_config.media_url:
                data["MediaUrl"] = typed_config.media_url
            if typed_config.status_callback:
                data["StatusCallback"] = typed_config.status_callback

            return await self._make_twilio_request(
                "POST",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Messages.json",
                credentials,
                data=data,
            )

        elif action == "get_message":
            typed_config: TwilioGetMessageConfig = config
            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Messages/{typed_config.message_sid}.json",
                credentials,
            )

        elif action == "list_messages":
            typed_config: TwilioListMessagesConfig = config
            params = {"PageSize": typed_config.page_size}
            if typed_config.to_number:
                params["To"] = typed_config.to_number
            if typed_config.from_number:
                params["From"] = typed_config.from_number
            if typed_config.date_sent:
                params["DateSent"] = typed_config.date_sent

            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Messages.json",
                credentials,
                params=params,
            )

        elif action == "delete_message":
            typed_config: TwilioDeleteMessageConfig = config
            return await self._make_twilio_request(
                "DELETE",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Messages/{typed_config.message_sid}.json",
                credentials,
            )

        # ========== WhatsApp Operations ==========
        elif action == "send_whatsapp_message":
            typed_config: TwilioSendWhatsAppConfig = config
            data = {"From": typed_config.from_number, "To": typed_config.to_number}
            if typed_config.body:
                data["Body"] = typed_config.body
            if typed_config.content_sid:
                data["ContentSid"] = typed_config.content_sid
            if typed_config.media_url:
                data["MediaUrl"] = typed_config.media_url

            return await self._make_twilio_request(
                "POST",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Messages.json",
                credentials,
                data=data,
            )

        elif action == "get_whatsapp_message":
            typed_config: TwilioGetWhatsAppMessageConfig = config
            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Messages/{typed_config.message_sid}.json",
                credentials,
            )

        # ========== Voice Call Operations ==========
        elif action == "make_outbound_call":
            typed_config: TwilioMakeCallConfig = config
            data = {
                "From": typed_config.from_number,
                "To": typed_config.to_number,
                "Url": typed_config.url,
            }
            if typed_config.status_callback:
                data["StatusCallback"] = typed_config.status_callback
            if typed_config.timeout:
                data["Timeout"] = typed_config.timeout
            if typed_config.record:
                data["Record"] = "true"

            return await self._make_twilio_request(
                "POST",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Calls.json",
                credentials,
                data=data,
            )

        elif action == "get_call":
            typed_config: TwilioGetCallConfig = config
            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Calls/{typed_config.call_sid}.json",
                credentials,
            )

        elif action == "list_calls":
            typed_config: TwilioListCallsConfig = config
            params = {"PageSize": typed_config.page_size}
            if typed_config.to_number:
                params["To"] = typed_config.to_number
            if typed_config.from_number:
                params["From"] = typed_config.from_number
            if typed_config.status:
                params["Status"] = typed_config.status
            if typed_config.start_time:
                params["StartTime"] = typed_config.start_time

            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Calls.json",
                credentials,
                params=params,
            )

        elif action == "update_in_progress_call":
            typed_config: TwilioUpdateCallConfig = config
            data = {}
            if typed_config.url:
                data["Url"] = typed_config.url
            if typed_config.status:
                data["Status"] = typed_config.status

            return await self._make_twilio_request(
                "POST",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Calls/{typed_config.call_sid}.json",
                credentials,
                data=data,
            )

        # ========== Recording Operations ==========
        elif action == "list_call_recordings":
            typed_config: TwilioListRecordingsConfig = config
            params = {"PageSize": typed_config.page_size}
            if typed_config.call_sid:
                params["CallSid"] = typed_config.call_sid
            if typed_config.date_created:
                params["DateCreated"] = typed_config.date_created

            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Recordings.json",
                credentials,
                params=params,
            )

        elif action == "get_call_recording":
            typed_config: TwilioGetRecordingConfig = config
            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Recordings/{typed_config.recording_sid}.json",
                credentials,
            )

        elif action == "delete_call_recording":
            typed_config: TwilioDeleteRecordingConfig = config
            return await self._make_twilio_request(
                "DELETE",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Recordings/{typed_config.recording_sid}.json",
                credentials,
            )

        # ========== Conference Operations ==========
        elif action == "list_conferences":
            typed_config: TwilioListConferencesConfig = config
            params = {"PageSize": typed_config.page_size}
            if typed_config.status:
                params["Status"] = typed_config.status
            if typed_config.friendly_name:
                params["FriendlyName"] = typed_config.friendly_name

            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Conferences.json",
                credentials,
                params=params,
            )

        elif action == "get_conference":
            typed_config: TwilioGetConferenceConfig = config
            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Conferences/{typed_config.conference_sid}.json",
                credentials,
            )

        elif action == "list_conference_participants":
            typed_config: TwilioListParticipantsConfig = config
            params = {}
            if typed_config.muted is not None:
                params["Muted"] = str(typed_config.muted).lower()

            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Conferences/{typed_config.conference_sid}/Participants.json",
                credentials,
                params=params,
            )

        elif action == "update_conference_participant":
            typed_config: TwilioUpdateParticipantConfig = config
            data = {}
            if typed_config.muted is not None:
                data["Muted"] = str(typed_config.muted).lower()
            if typed_config.hold is not None:
                data["Hold"] = str(typed_config.hold).lower()

            return await self._make_twilio_request(
                "POST",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/Conferences/{typed_config.conference_sid}/Participants/{typed_config.call_sid}.json",
                credentials,
                data=data,
            )

        # ========== Verify API Operations ==========
        elif action == "start_verification_code":
            typed_config: TwilioStartVerificationConfig = config
            data = {"To": typed_config.to, "Channel": typed_config.channel}
            if typed_config.locale:
                data["Locale"] = typed_config.locale

            return await self._make_twilio_request(
                "POST",
                f"Services/{typed_config.verify_service_sid}/Verifications",
                credentials,
                data=data,
                api_base=TWILIO_VERIFY_API_BASE,
            )

        elif action == "check_verification_code":
            typed_config: TwilioCheckVerificationConfig = config
            data = {"To": typed_config.to, "Code": typed_config.code}

            return await self._make_twilio_request(
                "POST",
                f"Services/{typed_config.verify_service_sid}/VerificationCheck",
                credentials,
                data=data,
                api_base=TWILIO_VERIFY_API_BASE,
            )

        # ========== Lookup API Operations ==========
        elif action == "lookup_phone_number_info":
            typed_config: TwilioLookupPhoneNumberConfig = config
            params = {}
            if typed_config.type:
                params["Fields"] = typed_config.type

            return await self._make_twilio_request(
                "GET",
                f"PhoneNumbers/{typed_config.phone_number}",
                credentials,
                params=params,
                api_base=TWILIO_LOOKUPS_API_BASE,
            )

        # ========== Conversations API Operations ==========
        elif action == "create_conversation":
            typed_config: TwilioCreateConversationConfig = config
            data = {"FriendlyName": typed_config.friendly_name}
            if typed_config.unique_name:
                data["UniqueName"] = typed_config.unique_name

            return await self._make_twilio_request(
                "POST",
                "Conversations",
                credentials,
                data=data,
                api_base=TWILIO_CONVERSATIONS_API_BASE,
            )

        elif action == "list_conversations":
            typed_config: TwilioListConversationsConfig = config
            params = {"PageSize": typed_config.page_size}

            return await self._make_twilio_request(
                "GET",
                "Conversations",
                credentials,
                params=params,
                api_base=TWILIO_CONVERSATIONS_API_BASE,
            )

        elif action == "get_conversation":
            typed_config: TwilioGetConversationDetailsConfig = config
            return await self._make_twilio_request(
                "GET",
                f"Conversations/{typed_config.conversation_sid}",
                credentials,
                api_base=TWILIO_CONVERSATIONS_API_BASE,
            )

        elif action == "send_conversation_message":
            typed_config: TwilioSendConversationMessageConfig = config
            data = {"Body": typed_config.body}
            if typed_config.author:
                data["Author"] = typed_config.author

            return await self._make_twilio_request(
                "POST",
                f"Conversations/{typed_config.conversation_sid}/Messages",
                credentials,
                data=data,
                api_base=TWILIO_CONVERSATIONS_API_BASE,
            )

        elif action == "add_conversation_participant":
            typed_config: TwilioAddParticipantConfig = config
            data = {"MessagingBinding.Address": typed_config.messaging_binding_address}
            if typed_config.messaging_binding_proxy_address:
                data[
                    "MessagingBinding.ProxyAddress"
                ] = typed_config.messaging_binding_proxy_address

            return await self._make_twilio_request(
                "POST",
                f"Conversations/{typed_config.conversation_sid}/Participants",
                credentials,
                data=data,
                api_base=TWILIO_CONVERSATIONS_API_BASE,
            )

        elif action == "delete_conversation":
            typed_config: TwilioDeleteConversationConfig = config
            return await self._make_twilio_request(
                "DELETE",
                f"Conversations/{typed_config.conversation_sid}",
                credentials,
                api_base=TWILIO_CONVERSATIONS_API_BASE,
            )

        # ========== Phone Numbers API Operations ==========
        elif action == "search_available_phone_numbers":
            typed_config: TwilioSearchAvailableNumbersConfig = config
            params = {"PageSize": typed_config.limit}
            if typed_config.area_code:
                params["AreaCode"] = typed_config.area_code
            if typed_config.contains:
                params["Contains"] = typed_config.contains
            if typed_config.sms_enabled is not None:
                params["SmsEnabled"] = str(typed_config.sms_enabled).lower()
            if typed_config.voice_enabled is not None:
                params["VoiceEnabled"] = str(typed_config.voice_enabled).lower()

            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/AvailablePhoneNumbers/{typed_config.country_code}/Local.json",
                credentials,
                params=params,
            )

        elif action == "list_owned_phone_numbers":
            typed_config: TwilioListIncomingNumbersConfig = config
            params = {"PageSize": typed_config.page_size}
            if typed_config.phone_number:
                params["PhoneNumber"] = typed_config.phone_number
            if typed_config.friendly_name:
                params["FriendlyName"] = typed_config.friendly_name

            return await self._make_twilio_request(
                "GET",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/IncomingPhoneNumbers.json",
                credentials,
                params=params,
            )

        elif action == "purchase_phone_number":
            typed_config: TwilioPurchasePhoneNumberConfig = config
            data = {"PhoneNumber": typed_config.phone_number}
            if typed_config.friendly_name:
                data["FriendlyName"] = typed_config.friendly_name
            if typed_config.sms_url:
                data["SmsUrl"] = typed_config.sms_url
            if typed_config.voice_url:
                data["VoiceUrl"] = typed_config.voice_url

            return await self._make_twilio_request(
                "POST",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/IncomingPhoneNumbers.json",
                credentials,
                data=data,
            )

        elif action == "update_phone_number_configuration":
            typed_config: TwilioUpdatePhoneNumberConfig = config
            data = {}
            if typed_config.friendly_name:
                data["FriendlyName"] = typed_config.friendly_name
            if typed_config.sms_url:
                data["SmsUrl"] = typed_config.sms_url
            if typed_config.voice_url:
                data["VoiceUrl"] = typed_config.voice_url

            return await self._make_twilio_request(
                "POST",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/IncomingPhoneNumbers/{typed_config.phone_number_sid}.json",
                credentials,
                data=data,
            )

        elif action == "release_phone_number":
            typed_config: TwilioReleasePhoneNumberConfig = config
            return await self._make_twilio_request(
                "DELETE",
                f"{TWILIO_API_VERSION}/Accounts/{account_sid}/IncomingPhoneNumbers/{typed_config.phone_number_sid}.json",
                credentials,
            )

        # ========== SendGrid Email API Operations ==========
        elif action == "send_sendgrid_transactional_email":
            typed_config: SendGridSendEmailConfig = config

            # Build email payload
            personalizations = [{"to": [{"email": typed_config.to_email}]}]
            if typed_config.to_name:
                personalizations[0]["to"][0]["name"] = typed_config.to_name

            # Add CC if provided
            if typed_config.cc_emails:
                cc_list = [
                    {"email": email.strip()}
                    for email in typed_config.cc_emails.split(",")
                ]
                personalizations[0]["cc"] = cc_list

            # Add BCC if provided
            if typed_config.bcc_emails:
                bcc_list = [
                    {"email": email.strip()}
                    for email in typed_config.bcc_emails.split(",")
                ]
                personalizations[0]["bcc"] = bcc_list

            # Build content array
            content = []
            if typed_config.text_content:
                content.append(
                    {"type": "text/plain", "value": typed_config.text_content}
                )
            if typed_config.html_content:
                content.append(
                    {"type": "text/html", "value": typed_config.html_content}
                )

            if not content:
                raise ValueError("Either html_content or text_content must be provided")

            email_data = {
                "personalizations": personalizations,
                "from": {"email": typed_config.from_email},
                "subject": typed_config.subject,
                "content": content,
            }

            if typed_config.from_name:
                email_data["from"]["name"] = typed_config.from_name

            if typed_config.reply_to_email:
                email_data["reply_to"] = {"email": typed_config.reply_to_email}

            return await self._make_sendgrid_request(
                "POST", "mail/send", credentials, json_data=email_data
            )

        elif action == "send_sendgrid_template_email":
            typed_config: SendGridSendTemplateEmailConfig = config

            # Parse dynamic template data if provided
            dynamic_data = {}
            if typed_config.dynamic_template_data:
                import json

                dynamic_data = json.loads(typed_config.dynamic_template_data)

            email_data = {
                "personalizations": [
                    {
                        "to": [{"email": typed_config.to_email}],
                        "dynamic_template_data": dynamic_data,
                    }
                ],
                "from": {"email": typed_config.from_email},
                "template_id": typed_config.template_id,
            }

            return await self._make_sendgrid_request(
                "POST", "mail/send", credentials, json_data=email_data
            )

        elif action == "get_sendgrid_email_stats":
            typed_config: SendGridGetEmailStatsConfig = config
            params = {
                "start_date": typed_config.start_date,
                "aggregated_by": typed_config.aggregated_by,
            }
            if typed_config.end_date:
                params["end_date"] = typed_config.end_date

            return await self._make_sendgrid_request(
                "GET", "stats", credentials, params=params
            )

        else:
            raise ValueError(f"Unknown action: {action}")


# Factory function for node creation
def create_twilio_node(config: TwilioNodeFullConfig) -> TwilioNode:
    """Factory function to create a Twilio node instance"""
    return TwilioNode(config)
