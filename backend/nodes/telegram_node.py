"""
Telegram automation node implementation.

Handles Telegram-related workflow operations such as sending messages
via the Telegram Bot API and receiving messages via webhooks.

This node can operate in two modes:
1. Action mode: Send messages, manage chats, handle payments, etc.
2. Trigger mode: Receive messages via webhook (workflow entry point)
3. Setup mode: Guided channel setup flow (auto-detects channel ID)
"""

import json
import os
import time
import logging
from typing import Dict, Any, Optional, Union, Type, Literal, Annotated, List
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


# ============================================================================
# Telegram Webhook Management Utilities
# ============================================================================


async def set_telegram_webhook(bot_token: str, webhook_url: str) -> Dict[str, Any]:
    """Register a webhook URL with Telegram Bot API."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{bot_token}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": [
                        "message",
                        "edited_message",
                        "channel_post",
                        "edited_channel_post",
                        "callback_query",
                        "inline_query",
                        "chosen_inline_result",
                        "my_chat_member",
                    ],
                },
                timeout=30.0,
            )
            data = response.json()
            if response.status_code == 200 and data.get("ok"):
                logger.info(
                    f"[TELEGRAM] Successfully set webhook to {webhook_url[:50]}..."
                )
                return {"success": True, "message": "Webhook registered with Telegram"}
            else:
                error_msg = data.get("description", "Unknown error")
                logger.error(f"[TELEGRAM] Failed to set webhook: {error_msg}")
                return {"success": False, "error": f"Telegram API error: {error_msg}"}
    except httpx.TimeoutException:
        logger.error("[TELEGRAM] Timeout setting webhook")
        return {"success": False, "error": "Timeout connecting to Telegram API"}
    except Exception as e:
        logger.error(f"[TELEGRAM] Error setting webhook: {e}")
        return {"success": False, "error": str(e)}


async def delete_telegram_webhook(bot_token: str) -> Dict[str, Any]:
    """Remove the webhook from Telegram Bot API."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{bot_token}/deleteWebhook", timeout=30.0
            )
            data = response.json()
            if response.status_code == 200 and data.get("ok"):
                logger.info("[TELEGRAM] Successfully deleted webhook")
                return {"success": True, "message": "Webhook removed from Telegram"}
            else:
                error_msg = data.get("description", "Unknown error")
                logger.warning(f"[TELEGRAM] Failed to delete webhook: {error_msg}")
                return {"success": False, "error": error_msg}
    except Exception as e:
        logger.error(f"[TELEGRAM] Error deleting webhook: {e}")
        return {"success": False, "error": str(e)}


async def get_telegram_webhook_info(bot_token: str) -> Dict[str, Any]:
    """Get current webhook info from Telegram Bot API."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TELEGRAM_API_BASE}{bot_token}/getWebhookInfo", timeout=30.0
            )
            data = response.json()
            if response.status_code == 200 and data.get("ok"):
                return {"success": True, "info": data.get("result", {})}
            else:
                return {
                    "success": False,
                    "error": data.get("description", "Unknown error"),
                }
    except Exception as e:
        logger.error(f"[TELEGRAM] Error getting webhook info: {e}")
        return {"success": False, "error": str(e)}


async def setup_telegram_trigger_webhook(
    pool, user_id, workflow_id, node_id, bot_token
):
    """Set up a complete Telegram trigger webhook (internal + Telegram registration)."""
    from utils.webhook_manager import WebhookManager

    webhook_data = await WebhookManager.get_or_create_webhook(
        pool=pool,
        user_id=user_id,
        workflow_id=workflow_id,
        node_id=node_id,
    )
    webhook_url = webhook_data.get("webhook_url")
    telegram_result = await set_telegram_webhook(bot_token, webhook_url)
    return {
        "webhook_id": webhook_data.get("webhook_id"),
        "webhook_url": webhook_url,
        "relay_connected": webhook_data.get("relay_connected"),
        "is_production": webhook_data.get("is_production"),
        "telegram_registered": telegram_result.get("success", False),
        "telegram_error": telegram_result.get("error")
        if not telegram_result.get("success")
        else None,
    }


async def cleanup_telegram_trigger_webhook(pool, workflow_id, node_id, bot_token=None):
    """Clean up a Telegram trigger webhook."""
    from utils.webhook_manager import WebhookManager

    if bot_token:
        await delete_telegram_webhook(bot_token)
    return await WebhookManager.delete_webhook(pool, workflow_id, node_id)


# ============================================================================
# Redis helpers for setup_channel flow
# ============================================================================


async def _get_redis_client():
    """Get an async Redis client."""
    import redis.asyncio as redis

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    return redis.from_url(redis_url, decode_responses=True)


async def _store_setup_token(
    token: str, workflow_id: str, node_id: str, user_id: str
) -> None:
    """Store a setup token in Redis with 1-hour TTL."""
    client = await _get_redis_client()
    if not client:
        return
    try:
        await client.setex(
            f"telegram:setup:{token}",
            3600,
            json.dumps(
                {"workflow_id": workflow_id, "node_id": node_id, "user_id": user_id}
            ),
        )
    finally:
        await client.aclose()


async def _get_setup_token_data(token: str) -> Optional[Dict[str, Any]]:
    """Look up setup token data from Redis."""
    client = await _get_redis_client()
    if not client:
        return None
    try:
        data = await client.get(f"telegram:setup:{token}")
        return json.loads(data) if data else None
    finally:
        await client.aclose()


async def _store_setup_result(
    workflow_id: str, node_id: str, channel_id: str, channel_title: str
) -> None:
    """Store resolved channel_id for a setup flow in Redis with 24-hour TTL."""
    client = await _get_redis_client()
    if not client:
        return
    try:
        await client.setex(
            f"telegram:setup_result:{workflow_id}:{node_id}",
            86400,
            json.dumps({"channel_id": channel_id, "channel_title": channel_title}),
        )
    finally:
        await client.aclose()


async def _get_setup_result(workflow_id: str, node_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve resolved channel_id for a setup flow from Redis."""
    client = await _get_redis_client()
    if not client:
        return None
    try:
        data = await client.get(f"telegram:setup_result:{workflow_id}:{node_id}")
        return json.loads(data) if data else None
    finally:
        await client.aclose()


# ============================================================================
# Credential Schema
# ============================================================================


class TelegramBotTokenCredential(BaseModel):
    """Telegram Bot API token credential structure"""

    credential_type: Literal["telegram_bot_token"] = Field(
        "telegram_bot_token", json_schema_extra={"ui:hidden": True}
    )
    token: str = Field(
        ...,
        min_length=1,
        title="Bot Token",
        description="Bot token from @BotFather",
        json_schema_extra={
            "ui:widget": "password",
            "placeholder": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
        },
    )


# ============================================================================
# Config Models — Original 5 Operations (unchanged)
# ============================================================================


class TelegramChatIdConfig(BaseModel):
    """Send message directly to a chat ID"""

    operation: Literal["send_message_to_chat"] = Field(
        default="send_message_to_chat",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Message to Chat",
            "x-keywords": [
                "message a chat",
                "text a chat",
                "dm someone",
                "message by chat id",
                "ping a user",
            ],
        },
        title="Send Message to Chat",
    )
    message: str = Field(
        min_length=1,
        title="Message",
        description="The message to send via Telegram",
        json_schema_extra={"ui:widget": "textarea"},
    )
    chatId: Union[str, int] = Field(
        title="Chat ID",
        description="Numeric chat ID. For users: they must message the bot first.",
        json_schema_extra={"placeholder": "123456789"},
    )


class TelegramChannelConfig(BaseModel):
    """Send message to a public channel or group"""

    operation: Literal["send_message_to_channel"] = Field(
        default="send_message_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Send Message to Channel",
            "x-keywords": [
                "post to channel",
                "broadcast to group",
                "announce in channel",
                "message a group",
                "publish to channel",
            ],
        },
        title="Send Message to Channel",
    )
    message: str = Field(
        min_length=1,
        title="Message",
        description="The message to send via Telegram",
        json_schema_extra={"ui:widget": "textarea"},
    )
    username: str = Field(
        pattern=r"^@?[a-zA-Z0-9_]+$",
        title="Channel Username",
        description="Public channel/group username (bot must be admin).",
        json_schema_extra={"placeholder": "@channel_name"},
    )


class TelegramSendDocumentConfig(BaseModel):
    """Send a document/file to a chat ID"""

    operation: Literal["send_document_file"] = Field(
        default="send_document_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Document File",
            "x-keywords": [
                "attach a file",
                "send pdf",
                "share document",
                "upload file to chat",
            ],
        },
        title="Send Document File",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    document_url: str = Field(
        min_length=1,
        title="Document",
        description="The document to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). A Telegram file_id also works.",
        json_schema_extra={"placeholder": "https://example.com/file.pdf", "ui:widget": "media_upload"},
    )
    caption: str = Field(
        default="",
        title="Caption",
        description="Optional caption for the document",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TelegramWebhookConfig(BaseModel):
    """Deliver via webhook (no message required)"""

    operation: Literal["send_webhook_delivery"] = Field(
        default="send_webhook_delivery",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Send Webhook Delivery",
            "x-keywords": [
                "fire webhook",
                "trigger webhook",
                "ping webhook",
                "webhook only",
                "no message delivery",
            ],
        },
        title="Send Webhook Delivery",
    )
    webhookUrl: HttpUrl = Field(
        title="Webhook URL", description="Alternative: Webhook URL for message delivery"
    )


class TelegramReceiveConfig(BaseModel):
    """Receive messages via webhook (trigger mode)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_webhook_messages"] = Field(
        default="receive_webhook_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Webhook Messages",
            "x-keywords": [
                "when new message",
                "on incoming message",
                "watch for messages",
                "bot receives message",
                "listen for updates",
            ],
        },
        title="Receive Webhook Messages",
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
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    telegram_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    telegram_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


# ============================================================================
# Config Models — Rich Media Operations
# ============================================================================


class TelegramSendPhotoConfig(BaseModel):
    """Send a photo to a chat"""

    operation: Literal["send_photo_image"] = Field(
        default="send_photo_image",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Photo Image",
            "x-keywords": [
                "share a photo",
                "send picture",
                "attach image",
                "post a photo",
            ],
        },
        title="Send Photo Image",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    photo: str = Field(
        title="Photo",
        description="The photo to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). A Telegram file_id also works.",
        json_schema_extra={"placeholder": "https://example.com/photo.jpg", "ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    caption: str = Field(
        default="",
        title="Caption",
        description="Optional caption (HTML supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    parse_mode: str = Field(
        default="HTML",
        title="Parse Mode",
        json_schema_extra={
            "enum": ["HTML", "Markdown", "MarkdownV2", ""],
            "x-enum-searchable": True,
        },
    )


class TelegramSendVideoConfig(BaseModel):
    """Send a video to a chat"""

    operation: Literal["send_video_file"] = Field(
        default="send_video_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Video File",
            "x-keywords": [
                "share a video",
                "send clip",
                "attach video",
                "post a video",
            ],
        },
        title="Send Video File",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    video: str = Field(
        title="Video",
        description="The video to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). A Telegram file_id also works.",
        json_schema_extra={"placeholder": "https://example.com/video.mp4", "ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    caption: str = Field(
        default="", title="Caption", json_schema_extra={"ui:widget": "textarea"}
    )
    parse_mode: str = Field(
        default="HTML",
        title="Parse Mode",
        json_schema_extra={
            "enum": ["HTML", "Markdown", "MarkdownV2", ""],
            "x-enum-searchable": True,
        },
    )
    duration: str = Field(
        default="", title="Duration (seconds)", description="Optional video duration"
    )
    width: str = Field(
        default="", title="Width", description="Optional video width in pixels"
    )
    height: str = Field(
        default="", title="Height", description="Optional video height in pixels"
    )


class TelegramSendAudioConfig(BaseModel):
    """Send an audio file to a chat"""

    operation: Literal["send_audio_file"] = Field(
        default="send_audio_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Audio File",
            "x-keywords": ["share audio", "send music", "send mp3", "send sound file"],
        },
        title="Send Audio File",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    audio: str = Field(
        title="Audio",
        description="The audio file to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). A Telegram file_id also works.",
        json_schema_extra={"placeholder": "https://example.com/audio.mp3", "ui:widget": "media_upload", "ui:accept": "audio/*"},
    )
    caption: str = Field(
        default="", title="Caption", json_schema_extra={"ui:widget": "textarea"}
    )
    performer: str = Field(
        default="", title="Performer", description="Performer / artist name"
    )
    title: str = Field(default="", title="Track Title", description="Track title")
    duration: str = Field(default="", title="Duration (seconds)")


class TelegramSendVoiceConfig(BaseModel):
    """Send a voice note (.ogg) to a chat"""

    operation: Literal["send_voice_note"] = Field(
        default="send_voice_note",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Voice Note",
            "x-keywords": ["voice message", "send ogg", "audio memo", "record voice"],
        },
        title="Send Voice Note",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    voice: str = Field(
        title="Voice",
        description="The voice note (.ogg) to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). A Telegram file_id also works.",
        json_schema_extra={"placeholder": "https://example.com/voice.ogg", "ui:widget": "media_upload", "ui:accept": "audio/*"},
    )
    caption: str = Field(
        default="", title="Caption", json_schema_extra={"ui:widget": "textarea"}
    )
    duration: str = Field(default="", title="Duration (seconds)")


class TelegramSendAnimationConfig(BaseModel):
    """Send a GIF or silent H.264/MPEG-4 AVC video"""

    operation: Literal["send_animated_video"] = Field(
        default="send_animated_video",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Animated Video",
            "x-keywords": [
                "send gif",
                "share gif",
                "animated clip",
                "silent video",
                "looping video",
            ],
        },
        title="Send Animated Video",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    animation: str = Field(
        title="Animation",
        description="file_id or URL of the GIF/animation",
        json_schema_extra={"placeholder": "https://example.com/animation.gif"},
    )
    caption: str = Field(
        default="", title="Caption", json_schema_extra={"ui:widget": "textarea"}
    )
    parse_mode: str = Field(
        default="HTML",
        title="Parse Mode",
        json_schema_extra={
            "enum": ["HTML", "Markdown", "MarkdownV2", ""],
            "x-enum-searchable": True,
        },
    )


class TelegramSendVideoNoteConfig(BaseModel):
    """Send a circular video message"""

    operation: Literal["send_circular_video"] = Field(
        default="send_circular_video",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Circular Video",
            "x-keywords": ["video note", "round video", "circle video", "bubble video"],
        },
        title="Send Circular Video",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    video_note: str = Field(
        title="Video Note",
        description="file_id of the circular video",
        json_schema_extra={"placeholder": "file_id_here"},
    )
    duration: str = Field(default="", title="Duration (seconds)")
    length: str = Field(
        default="", title="Video Size", description="Video width/height (must be equal)"
    )


class TelegramSendStickerConfig(BaseModel):
    """Send a sticker"""

    operation: Literal["send_sticker"] = Field(
        default="send_sticker",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Sticker",
            "x-keywords": ["share sticker", "send emoji sticker", "sticker pack"],
        },
        title="Send Sticker",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    sticker: str = Field(
        title="Sticker",
        description="file_id, URL, or .WEBP/.TGS/.WEBM file path",
        json_schema_extra={"placeholder": "file_id_here"},
    )
    emoji: str = Field(
        default="", title="Emoji", description="Emoji associated with the sticker"
    )


class TelegramSendMediaGroupConfig(BaseModel):
    """Send a group of photos, videos, or documents as an album"""

    operation: Literal["send_photo_video_album"] = Field(
        default="send_photo_video_album",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Send Photo Video Album",
            "x-keywords": [
                "media album",
                "photo album",
                "group of photos",
                "media group",
                "multiple images",
                "gallery post",
            ],
        },
        title="Send Photo Video Album",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    media: str = Field(
        title="Media Array (JSON)",
        description='JSON array of 2–10 InputMedia objects. Each: {"type": "photo", "media": "url_or_file_id", "caption": "optional"}',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type":"photo","media":"https://example.com/1.jpg"},{"type":"photo","media":"https://example.com/2.jpg"}]',
        },
    )


class TelegramSendContactConfig(BaseModel):
    """Send a phone contact"""

    operation: Literal["send_contact_information"] = Field(
        default="send_contact_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Location and Contact",
            "x-is-trigger": False,
            "x-display-name": "Send Contact Information",
            "x-keywords": [
                "share contact",
                "send phone number",
                "send vcard",
                "share a person",
            ],
        },
        title="Send Contact Information",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    phone_number: str = Field(
        title="Phone Number",
        description="Contact's phone number",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    first_name: str = Field(title="First Name", description="Contact's first name")
    last_name: str = Field(
        default="", title="Last Name", description="Contact's last name (optional)"
    )


class TelegramSendLocationConfig(BaseModel):
    """Send a geographic location"""

    operation: Literal["send_location_pin"] = Field(
        default="send_location_pin",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Location and Contact",
            "x-is-trigger": False,
            "x-display-name": "Send Location Pin",
            "x-keywords": [
                "drop a pin",
                "share location",
                "send coordinates",
                "send gps",
                "share my location",
            ],
        },
        title="Send Location Pin",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    latitude: str = Field(
        title="Latitude",
        description="Latitude of the location",
        json_schema_extra={"placeholder": "37.7749"},
    )
    longitude: str = Field(
        title="Longitude",
        description="Longitude of the location",
        json_schema_extra={"placeholder": "-122.4194"},
    )
    horizontal_accuracy: str = Field(
        default="",
        title="Accuracy (meters)",
        description="Radius of location uncertainty (0–1500)",
    )


class TelegramSendVenueConfig(BaseModel):
    """Send a venue (location with title and address)"""

    operation: Literal["send_venue_location"] = Field(
        default="send_venue_location",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Location and Contact",
            "x-is-trigger": False,
            "x-display-name": "Send Venue Location",
            "x-keywords": [
                "share venue",
                "send place",
                "location with address",
                "send a spot",
                "named location",
            ],
        },
        title="Send Venue Location",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    latitude: str = Field(
        title="Latitude", json_schema_extra={"placeholder": "37.7749"}
    )
    longitude: str = Field(
        title="Longitude", json_schema_extra={"placeholder": "-122.4194"}
    )
    title: str = Field(
        title="Venue Title",
        description="Name of the venue",
        json_schema_extra={"placeholder": "Googleplex"},
    )
    address: str = Field(
        title="Address",
        description="Address of the venue",
        json_schema_extra={"placeholder": "1600 Amphitheatre Pkwy, Mountain View, CA"},
    )
    foursquare_id: str = Field(
        default="", title="Foursquare ID", description="Optional Foursquare identifier"
    )


class TelegramSendDiceConfig(BaseModel):
    """Send an animated emoji that displays a random value"""

    operation: Literal["send_dice_emoji"] = Field(
        default="send_dice_emoji",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Dice",
            "x-is-trigger": False,
            "x-display-name": "Send Dice Emoji",
            "x-keywords": [
                "roll dice",
                "throw dice",
                "random emoji",
                "spin slot machine",
                "lucky roll",
            ],
        },
        title="Send Dice Emoji",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    emoji: str = Field(
        default="🎲",
        title="Emoji",
        json_schema_extra={
            "enum": ["🎲", "🎯", "🏀", "⚽", "🎳", "🎰"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Config Models — Message Management Operations
# ============================================================================


class TelegramEditMessageTextConfig(BaseModel):
    """Edit the text of a sent message"""

    operation: Literal["edit_message_text"] = Field(
        default="edit_message_text",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Edit Message Text",
            "x-keywords": [
                "change message text",
                "rewrite message",
                "fix a message",
                "update text",
                "edit sent message",
            ],
        },
        title="Edit Message Text",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_id: str = Field(
        title="Message ID",
        description="ID of the message to edit",
        json_schema_extra={"placeholder": "42"},
    )
    text: str = Field(
        title="New Text",
        description="New message text (HTML supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    parse_mode: str = Field(
        default="HTML",
        title="Parse Mode",
        json_schema_extra={
            "enum": ["HTML", "Markdown", "MarkdownV2", ""],
            "x-enum-searchable": True,
        },
    )


class TelegramEditMessageCaptionConfig(BaseModel):
    """Edit the caption of a media message"""

    operation: Literal["edit_message_caption"] = Field(
        default="edit_message_caption",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Edit Message Caption",
            "x-keywords": [
                "change caption",
                "rewrite caption",
                "update media caption",
                "edit photo caption",
            ],
        },
        title="Edit Message Caption",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_id: str = Field(title="Message ID", json_schema_extra={"placeholder": "42"})
    caption: str = Field(
        title="New Caption", json_schema_extra={"ui:widget": "textarea"}
    )
    parse_mode: str = Field(
        default="HTML",
        title="Parse Mode",
        json_schema_extra={
            "enum": ["HTML", "Markdown", "MarkdownV2", ""],
            "x-enum-searchable": True,
        },
    )


class TelegramDeleteMessageConfig(BaseModel):
    """Delete a message"""

    operation: Literal["delete_message"] = Field(
        default="delete_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Message",
            "x-keywords": [
                "remove a message",
                "delete one message",
                "erase message",
                "take down message",
            ],
        },
        title="Delete Message",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_id: str = Field(
        title="Message ID",
        description="ID of the message to delete",
        json_schema_extra={"placeholder": "42"},
    )


class TelegramDeleteMessagesConfig(BaseModel):
    """Delete multiple messages at once"""

    operation: Literal["delete_multiple_messages"] = Field(
        default="delete_multiple_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Multiple Messages",
            "x-keywords": [
                "bulk delete messages",
                "delete many messages",
                "clear several messages",
                "remove messages batch",
                "purge messages",
            ],
        },
        title="Delete Multiple Messages",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_ids: str = Field(
        title="Message IDs",
        description="Comma-separated message IDs (up to 100)",
        json_schema_extra={"placeholder": "42,43,44"},
    )


class TelegramPinMessageConfig(BaseModel):
    """Pin a message in a chat"""

    operation: Literal["pin_message_in_chat"] = Field(
        default="pin_message_in_chat",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Pin Message in Chat",
            "x-keywords": [
                "pin a message",
                "stick message to top",
                "highlight message",
            ],
        },
        title="Pin Message in Chat",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_id: str = Field(title="Message ID", json_schema_extra={"placeholder": "42"})
    disable_notification: str = Field(
        default="false",
        title="Silent Pin",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (silent)", "No (notify)"],
            "x-enum-searchable": True,
        },
    )


class TelegramUnpinMessageConfig(BaseModel):
    """Unpin a message (or all messages) in a chat"""

    operation: Literal["unpin_chat_message"] = Field(
        default="unpin_chat_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Unpin Chat Message",
            "x-keywords": [
                "unpin message",
                "remove pinned message",
                "unstick message",
                "clear pinned",
            ],
        },
        title="Unpin Chat Message",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_id: str = Field(
        default="",
        title="Message ID",
        description="Leave empty to unpin all messages",
        json_schema_extra={"placeholder": "42 (or leave empty to unpin all)"},
    )


class TelegramForwardMessageConfig(BaseModel):
    """Forward a message to another chat"""

    operation: Literal["forward_message_to_chat"] = Field(
        default="forward_message_to_chat",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Forward Message to Chat",
            "x-keywords": [
                "forward a message",
                "relay message",
                "pass along message",
                "share with forward tag",
            ],
        },
        title="Forward Message to Chat",
    )
    chatId: Union[str, int] = Field(
        title="Destination Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    from_chat_id: Union[str, int] = Field(
        title="Source Chat ID",
        description="Chat the message is being forwarded from",
        json_schema_extra={"placeholder": "-1001234567890"},
    )
    message_id: str = Field(
        title="Message ID",
        description="ID of the message to forward",
        json_schema_extra={"placeholder": "42"},
    )


class TelegramCopyMessageConfig(BaseModel):
    """Copy a message to another chat (without forward tag)"""

    operation: Literal["copy_message_to_chat"] = Field(
        default="copy_message_to_chat",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Copy Message to Chat",
            "x-keywords": [
                "copy a message",
                "resend without forward",
                "duplicate message elsewhere",
                "repost message clean",
            ],
        },
        title="Copy Message to Chat",
    )
    chatId: Union[str, int] = Field(
        title="Destination Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    from_chat_id: Union[str, int] = Field(
        title="Source Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    message_id: str = Field(title="Message ID", json_schema_extra={"placeholder": "42"})
    caption: str = Field(
        default="",
        title="New Caption",
        description="Optional new caption (overrides original)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TelegramSendChatActionConfig(BaseModel):
    """Show a 'typing…' or 'uploading…' indicator in a chat"""

    operation: Literal["send_chat_typing_indicator"] = Field(
        default="send_chat_typing_indicator",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Action",
            "x-is-trigger": False,
            "x-display-name": "Send Chat Typing Indicator",
            "x-keywords": [
                "typing indicator",
                "show typing",
                "typing dots",
                "uploading status",
                "bot is typing",
            ],
        },
        title="Send Chat Typing Indicator",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    action: str = Field(
        title="Action",
        json_schema_extra={
            "enum": [
                "typing",
                "upload_photo",
                "record_video",
                "upload_video",
                "record_voice",
                "upload_voice",
                "upload_document",
                "choose_sticker",
                "find_location",
                "record_video_note",
                "upload_video_note",
            ],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Config Models — Poll Operations
# ============================================================================


class TelegramSendPollConfig(BaseModel):
    """Create and send a poll or quiz"""

    operation: Literal["send_poll_or_quiz"] = Field(
        default="send_poll_or_quiz",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Poll",
            "x-is-trigger": False,
            "x-display-name": "Send Poll or Quiz",
            "x-keywords": [
                "make a poll",
                "start a quiz",
                "ask a vote",
                "run survey",
                "create poll",
            ],
        },
        title="Send Poll or Quiz",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    question: str = Field(
        title="Question",
        description="Poll question (1–300 chars)",
        json_schema_extra={"placeholder": "What is your favorite color?"},
    )
    options: str = Field(
        title="Options (JSON)",
        description="JSON array of answer strings (2–10)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '["Red", "Green", "Blue"]',
        },
    )
    is_anonymous: str = Field(
        default="true",
        title="Anonymous",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (anonymous)", "No (public)"],
            "x-enum-searchable": True,
        },
    )
    poll_type: str = Field(
        default="regular",
        title="Poll Type",
        json_schema_extra={"enum": ["regular", "quiz"], "x-enum-searchable": True},
    )
    correct_option_id: str = Field(
        default="",
        title="Correct Option Index",
        description="0-based index of correct answer (quiz mode only)",
    )
    explanation: str = Field(
        default="",
        title="Explanation",
        description="Shown after quiz answer (quiz mode only)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    allows_multiple_answers: str = Field(
        default="false",
        title="Multiple Answers",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class TelegramStopPollConfig(BaseModel):
    """Stop a running poll"""

    operation: Literal["stop_active_poll"] = Field(
        default="stop_active_poll",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Stop Active Poll",
            "x-keywords": [
                "close poll",
                "end poll",
                "finish vote",
                "stop voting",
                "close quiz",
            ],
        },
        title="Stop Active Poll",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_id: str = Field(
        title="Message ID",
        description="ID of the poll message",
        json_schema_extra={"placeholder": "42"},
    )


# ============================================================================
# Config Models — Chat Info Operations
# ============================================================================


class TelegramGetChatConfig(BaseModel):
    """Get full information about a chat"""

    operation: Literal["get_chat_details"] = Field(
        default="get_chat_details",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Get Chat Details",
            "x-keywords": [
                "chat info",
                "group details",
                "about this chat",
                "fetch chat info",
                "channel metadata",
            ],
        },
        title="Get Chat Details",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )


class TelegramGetChatMemberConfig(BaseModel):
    """Get information about a member of a chat"""

    operation: Literal["get_chat_member_info"] = Field(
        default="get_chat_member_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Member",
            "x-is-trigger": False,
            "x-display-name": "Get Chat Member Info",
            "x-keywords": [
                "member details",
                "user status in chat",
                "is user banned",
                "member role",
                "check membership",
            ],
        },
        title="Get Chat Member Info",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    user_id: str = Field(
        title="User ID",
        description="Telegram user ID",
        json_schema_extra={"placeholder": "123456789"},
    )


class TelegramGetChatMemberCountConfig(BaseModel):
    """Get the number of members in a chat"""

    operation: Literal["get_chat_member_count"] = Field(
        default="get_chat_member_count",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Member",
            "x-is-trigger": False,
            "x-display-name": "Get Chat Member Count",
            "x-keywords": [
                "how many members",
                "member total",
                "group size",
                "subscriber count",
                "headcount",
            ],
        },
        title="Get Chat Member Count",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )


class TelegramGetChatAdministratorsConfig(BaseModel):
    """Get a list of administrators in a chat"""

    operation: Literal["get_chat_admin_list"] = Field(
        default="get_chat_admin_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Member",
            "x-is-trigger": False,
            "x-display-name": "Get Chat Admin List",
            "x-keywords": [
                "list admins",
                "who are admins",
                "chat administrators",
                "moderator list",
            ],
        },
        title="Get Chat Admin List",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )


# ============================================================================
# Config Models — Group/Channel Management Operations
# ============================================================================


class TelegramBanChatMemberConfig(BaseModel):
    """Ban a user from a chat"""

    operation: Literal["ban_user_from_chat"] = Field(
        default="ban_user_from_chat",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Member",
            "x-is-trigger": False,
            "x-display-name": "Ban User from Chat",
            "x-keywords": [
                "ban a member",
                "kick and ban",
                "block user",
                "remove member permanently",
            ],
        },
        title="Ban User from Chat",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    user_id: str = Field(
        title="User ID",
        description="ID of the user to ban",
        json_schema_extra={"placeholder": "123456789"},
    )
    until_date: str = Field(
        default="",
        title="Until Date",
        description="Unix timestamp when ban is lifted (0 or empty = permanent)",
    )
    revoke_messages: str = Field(
        default="false",
        title="Delete Messages",
        description="Delete all messages from this user",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class TelegramUnbanChatMemberConfig(BaseModel):
    """Unban a previously banned user"""

    operation: Literal["unban_user_from_chat"] = Field(
        default="unban_user_from_chat",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Member",
            "x-is-trigger": False,
            "x-display-name": "Unban User from Chat",
            "x-keywords": ["unban member", "remove ban", "lift ban", "allow back in"],
        },
        title="Unban User from Chat",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    user_id: str = Field(
        title="User ID", json_schema_extra={"placeholder": "123456789"}
    )


class TelegramRestrictChatMemberConfig(BaseModel):
    """Restrict a user's permissions in a chat"""

    operation: Literal["restrict_user_permissions"] = Field(
        default="restrict_user_permissions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Member",
            "x-is-trigger": False,
            "x-display-name": "Restrict User Permissions",
            "x-keywords": [
                "mute a user",
                "limit member",
                "silence user",
                "restrict posting",
                "read only user",
            ],
        },
        title="Restrict User Permissions",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    user_id: str = Field(
        title="User ID", json_schema_extra={"placeholder": "123456789"}
    )
    permissions: str = Field(
        title="Permissions (JSON)",
        description='ChatPermissions object. E.g. {"can_send_messages": true, "can_send_polls": false}',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"can_send_messages": true, "can_send_polls": false, "can_send_other_messages": false}',
        },
    )
    until_date: str = Field(
        default="",
        title="Until Date",
        description="Unix timestamp when restriction is lifted (0 or empty = forever)",
    )


class TelegramPromoteChatMemberConfig(BaseModel):
    """Promote a user to admin or update their admin rights"""

    operation: Literal["promote_user_to_admin"] = Field(
        default="promote_user_to_admin",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat Member",
            "x-is-trigger": False,
            "x-display-name": "Promote User to Admin",
            "x-keywords": [
                "make admin",
                "grant admin rights",
                "promote member",
                "give moderator role",
                "set admin powers",
            ],
        },
        title="Promote User to Admin",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    user_id: str = Field(
        title="User ID", json_schema_extra={"placeholder": "123456789"}
    )
    can_post_messages: str = Field(
        default="true",
        title="Can Post Messages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_edit_messages: str = Field(
        default="false",
        title="Can Edit Messages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_delete_messages: str = Field(
        default="false",
        title="Can Delete Messages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_manage_video_chats: str = Field(
        default="false",
        title="Can Manage Video Chats",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_restrict_members: str = Field(
        default="false",
        title="Can Restrict Members",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_promote_members: str = Field(
        default="false",
        title="Can Promote Members",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_change_info: str = Field(
        default="false",
        title="Can Change Info",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_invite_users: str = Field(
        default="false",
        title="Can Invite Users",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    can_pin_messages: str = Field(
        default="false",
        title="Can Pin Messages",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class TelegramSetChatTitleConfig(BaseModel):
    """Change the title of a chat"""

    operation: Literal["set_chat_title"] = Field(
        default="set_chat_title",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Set Chat Title",
            "x-keywords": [
                "rename chat",
                "change group name",
                "set group title",
                "edit chat name",
            ],
        },
        title="Set Chat Title",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    title: str = Field(
        title="New Title",
        description="New chat title (1–255 chars)",
        json_schema_extra={"placeholder": "My Awesome Channel"},
    )


class TelegramSetChatDescriptionConfig(BaseModel):
    """Change the description of a chat"""

    operation: Literal["set_chat_description"] = Field(
        default="set_chat_description",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Chat",
            "x-is-trigger": False,
            "x-display-name": "Set Chat Description",
            "x-keywords": [
                "change group description",
                "edit chat bio",
                "set group about",
                "update description",
            ],
        },
        title="Set Chat Description",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    description: str = Field(
        default="",
        title="Description",
        description="New chat description (0–255 chars)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TelegramCreateInviteLinkConfig(BaseModel):
    """Create an additional invite link for a chat"""

    operation: Literal["create_chat_invite_link"] = Field(
        default="create_chat_invite_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite Link",
            "x-is-trigger": False,
            "x-display-name": "Create Chat Invite Link",
            "x-keywords": [
                "new invite link",
                "generate invite",
                "make join link",
                "share invite url",
            ],
        },
        title="Create Chat Invite Link",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    name: str = Field(
        default="", title="Link Name", description="Invite link name (0–32 chars)"
    )
    expire_date: str = Field(
        default="", title="Expire Date", description="Unix timestamp when link expires"
    )
    member_limit: str = Field(
        default="",
        title="Member Limit",
        description="Max number of users that can join (1–99999)",
    )
    creates_join_request: str = Field(
        default="false",
        title="Requires Approval",
        description="Users joining via link must be approved by admin",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (approval required)", "No (join directly)"],
            "x-enum-searchable": True,
        },
    )


class TelegramRevokeInviteLinkConfig(BaseModel):
    """Revoke an invite link to a chat"""

    operation: Literal["revoke_chat_invite_link"] = Field(
        default="revoke_chat_invite_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invite Link",
            "x-is-trigger": False,
            "x-display-name": "Revoke Chat Invite Link",
            "x-keywords": [
                "revoke invite",
                "disable invite link",
                "kill join link",
                "expire invite",
            ],
        },
        title="Revoke Chat Invite Link",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "-1001234567890"}
    )
    invite_link: str = Field(
        title="Invite Link",
        description="The invite link to revoke",
        json_schema_extra={"placeholder": "https://t.me/+abc123"},
    )


# ============================================================================
# Config Models — Inline / Callback Operations
# ============================================================================


class TelegramAnswerCallbackQueryConfig(BaseModel):
    """Answer a callback query from an inline keyboard button"""

    operation: Literal["answer_inline_button_callback"] = Field(
        default="answer_inline_button_callback",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Callback and Inline Query",
            "x-is-trigger": False,
            "x-display-name": "Answer Inline Button Callback",
            "x-keywords": [
                "answer button press",
                "respond to button tap",
                "callback query reply",
                "acknowledge inline button",
            ],
        },
        title="Answer Inline Button Callback",
    )
    callback_query_id: str = Field(
        title="Callback Query ID",
        description="ID received from the callback_query update",
        json_schema_extra={"placeholder": "callback_query_id_here"},
    )
    text: str = Field(
        default="",
        title="Notification Text",
        description="Text to show in the notification (0–200 chars)",
        json_schema_extra={"placeholder": "Done!"},
    )
    show_alert: str = Field(
        default="false",
        title="Show as Alert",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (alert popup)", "No (toast notification)"],
            "x-enum-searchable": True,
        },
    )
    url: str = Field(
        default="", title="URL", description="URL to open in the user's browser"
    )
    cache_time: str = Field(
        default="",
        title="Cache Time",
        description="Max seconds the result may be cached client-side",
    )


class TelegramAnswerInlineQueryConfig(BaseModel):
    """Answer an inline query with a list of results"""

    operation: Literal["answer_inline_search_results"] = Field(
        default="answer_inline_search_results",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Callback and Inline Query",
            "x-is-trigger": False,
            "x-display-name": "Answer Inline Search Results",
            "x-keywords": [
                "inline query results",
                "respond to inline search",
                "answer mention search",
                "inline mode results",
            ],
        },
        title="Answer Inline Search Results",
    )
    inline_query_id: str = Field(
        title="Inline Query ID",
        json_schema_extra={"placeholder": "inline_query_id_here"},
    )
    results: str = Field(
        title="Results (JSON)",
        description="JSON array of InlineQueryResult objects (up to 50). See Telegram Bot API docs for InlineQueryResult types.",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type":"article","id":"1","title":"Result","input_message_content":{"message_text":"Hello"}}]',
        },
    )
    cache_time: str = Field(
        default="300",
        title="Cache Time (seconds)",
        description="How long results may be cached server-side",
    )
    is_personal: str = Field(
        default="false",
        title="Personal Results",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (user-specific)", "No (shared cache)"],
            "x-enum-searchable": True,
        },
    )
    next_offset: str = Field(
        default="", title="Next Offset", description="Offset for pagination of results"
    )


class TelegramSetMessageReactionConfig(BaseModel):
    """Set a reaction on a message"""

    operation: Literal["set_message_emoji_reaction"] = Field(
        default="set_message_emoji_reaction",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Set Message Emoji Reaction",
            "x-keywords": [
                "react to message",
                "add emoji reaction",
                "thumbs up message",
                "set reaction",
            ],
        },
        title="Set Message Emoji Reaction",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    message_id: str = Field(title="Message ID", json_schema_extra={"placeholder": "42"})
    reaction: str = Field(
        default="",
        title="Reaction Emoji",
        description="Emoji to react with (e.g. 👍). Leave empty to remove reaction.",
        json_schema_extra={"placeholder": "👍"},
    )
    is_big: str = Field(
        default="false",
        title="Big Reaction",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (big animation)", "No (normal)"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Config Models — Bot Info Operations
# ============================================================================


class TelegramGetMeConfig(BaseModel):
    """Get basic information about the bot"""

    operation: Literal["get_bot_information"] = Field(
        default="get_bot_information",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Bot",
            "x-is-trigger": False,
            "x-display-name": "Get Bot Information",
            "x-keywords": [
                "bot details",
                "who am i bot",
                "my bot info",
                "bot identity",
                "bot profile",
            ],
        },
        title="Get Bot Information",
    )


class TelegramGetFileConfig(BaseModel):
    """Get info about a file by its file_id (includes download URL)"""

    operation: Literal["get_file_download_info"] = Field(
        default="get_file_download_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get File Download Info",
            "x-keywords": [
                "download url for file",
                "resolve file id",
                "get file path",
                "file download link",
            ],
        },
        title="Get File Download Info",
    )
    file_id: str = Field(
        title="File ID",
        description="file_id from any Telegram message",
        json_schema_extra={"placeholder": "BQACAgIAAxkBAAI..."},
    )


# ============================================================================
# Config Models — Payment Operations
# ============================================================================


class TelegramSendInvoiceConfig(BaseModel):
    """Send a payment invoice"""

    operation: Literal["send_payment_invoice"] = Field(
        default="send_payment_invoice",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Invoice",
            "x-is-trigger": False,
            "x-display-name": "Send Payment Invoice",
            "x-keywords": [
                "bill the user",
                "request payment",
                "send invoice",
                "charge for purchase",
                "checkout invoice",
            ],
        },
        title="Send Payment Invoice",
    )
    chatId: Union[str, int] = Field(
        title="Chat ID", json_schema_extra={"placeholder": "123456789"}
    )
    title: str = Field(
        title="Product Title",
        description="Product name (1–32 chars)",
        json_schema_extra={"placeholder": "Premium Subscription"},
    )
    description: str = Field(
        title="Description",
        description="Product description (1–255 chars)",
        json_schema_extra={"placeholder": "Monthly premium access"},
    )
    payload: str = Field(
        title="Payload",
        description="Bot-defined invoice payload (1–128 bytes)",
        json_schema_extra={"placeholder": "subscription_monthly_usd"},
    )
    currency: str = Field(
        default="USD",
        title="Currency",
        description="ISO 4217 currency code or 'XTR' for Telegram Stars",
        json_schema_extra={"placeholder": "USD"},
    )
    prices: str = Field(
        title="Prices (JSON)",
        description='JSON array of LabeledPrice objects: [{"label": "Subscription", "amount": 999}] (amount in smallest currency unit)',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"label": "Subscription", "amount": 999}]',
        },
    )
    provider_token: str = Field(
        default="",
        title="Provider Token",
        description="Payment provider token (leave empty for Telegram Stars)",
    )
    photo_url: str = Field(
        default="", title="Photo URL", description="Optional product photo URL"
    )
    start_parameter: str = Field(
        default="",
        title="Start Parameter",
        description="Deep-linking parameter for /start",
    )


class TelegramAnswerPreCheckoutQueryConfig(BaseModel):
    """Confirm or reject a payment pre-checkout query"""

    operation: Literal["answer_payment_pre_checkout"] = Field(
        default="answer_payment_pre_checkout",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Callback and Inline Query",
            "x-is-trigger": False,
            "x-display-name": "Answer Payment Pre Checkout",
            "x-keywords": [
                "confirm checkout",
                "approve payment query",
                "pre checkout reply",
                "accept or reject payment",
            ],
        },
        title="Answer Payment Pre Checkout",
    )
    pre_checkout_query_id: str = Field(
        title="Pre-Checkout Query ID",
        json_schema_extra={"placeholder": "query_id_here"},
    )
    ok: str = Field(
        default="true",
        title="Approve Payment",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (approve)", "No (reject)"],
            "x-enum-searchable": True,
        },
    )
    error_message: str = Field(
        default="",
        title="Error Message",
        description="Required if 'ok' is false — reason for rejection",
    )


# ============================================================================
# Config Model — Setup Channel Flow (Phase 2)
# ============================================================================


class TelegramSetupChannelConfig(BaseModel):
    """
    Guided channel setup flow.

    Registers a webhook with the bot, then generates a deep-link for the user.
    When the user adds the bot to their channel as admin, the channel ID is
    automatically detected and stored — no manual copy-pasting needed.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["setup_telegram_channel_guided"] = Field(
        default="setup_telegram_channel_guided",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Setup Telegram Channel Guided",
            "x-keywords": [
                "guided channel setup",
                "auto detect channel",
                "wizard add channel",
                "connect channel deep link",
                "onboard channel",
            ],
        },
        title="Setup Telegram Channel Guided",
    )
    # Webhook fields (same as receive mode)
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
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    telegram_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    # Setup-specific fields
    setup_link: Optional[str] = Field(
        default=None,
        title="Setup Link",
        description="Click this link to start setup, then add your bot as admin to your channel",
        json_schema_extra={"ui:widget": "readonly", "ui:copyable": True},
    )
    channel_id: Optional[str] = Field(
        default=None,
        title="Detected Channel ID",
        description="Auto-populated once the bot is added as admin to a channel",
        json_schema_extra={"ui:loadValue": True},
    )
    channel_title: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    setup_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    setup_status: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class TelegramConnectChannelConfig(BaseModel):
    """
    Connect a Telegram channel by entering its @username or numeric ID.

    The bot must already be added as an admin to the channel before running.
    This node validates the connection and returns the channel details.
    Works correctly in setup flows — runs once and returns channel_id immediately.
    """

    operation: Literal["connect_telegram_channel"] = Field(
        default="connect_telegram_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Connect Telegram Channel",
            "x-keywords": [
                "link channel by username",
                "connect channel manually",
                "add channel by id",
                "validate channel connection",
            ],
        },
        title="Connect Telegram Channel",
    )
    channel_identifier: str = Field(
        default="",
        title="Channel Username or ID",
        description="Enter your channel @username (e.g. @mychannel) or numeric ID (e.g. -1001234567890). Add your bot as admin to the channel first.",
        json_schema_extra={"ui:placeholder": "@mychannel or -1001234567890"},
    )


# ============================================================================
# Discriminated Union — all operations
# ============================================================================

TelegramConfig = Annotated[
    Union[
        # Original operations (preserved for backward compat)
        TelegramChatIdConfig,
        TelegramReceiveConfig,
        TelegramChannelConfig,
        TelegramSendDocumentConfig,
        TelegramWebhookConfig,
        # Rich media
        TelegramSendPhotoConfig,
        TelegramSendVideoConfig,
        TelegramSendAudioConfig,
        TelegramSendVoiceConfig,
        TelegramSendAnimationConfig,
        TelegramSendVideoNoteConfig,
        TelegramSendStickerConfig,
        TelegramSendMediaGroupConfig,
        TelegramSendContactConfig,
        TelegramSendLocationConfig,
        TelegramSendVenueConfig,
        TelegramSendDiceConfig,
        # Message management
        TelegramEditMessageTextConfig,
        TelegramEditMessageCaptionConfig,
        TelegramDeleteMessageConfig,
        TelegramDeleteMessagesConfig,
        TelegramPinMessageConfig,
        TelegramUnpinMessageConfig,
        TelegramForwardMessageConfig,
        TelegramCopyMessageConfig,
        TelegramSendChatActionConfig,
        # Polls
        TelegramSendPollConfig,
        TelegramStopPollConfig,
        # Chat info
        TelegramGetChatConfig,
        TelegramGetChatMemberConfig,
        TelegramGetChatMemberCountConfig,
        TelegramGetChatAdministratorsConfig,
        # Group/channel management
        TelegramBanChatMemberConfig,
        TelegramUnbanChatMemberConfig,
        TelegramRestrictChatMemberConfig,
        TelegramPromoteChatMemberConfig,
        TelegramSetChatTitleConfig,
        TelegramSetChatDescriptionConfig,
        TelegramCreateInviteLinkConfig,
        TelegramRevokeInviteLinkConfig,
        # Inline/callback
        TelegramAnswerCallbackQueryConfig,
        TelegramAnswerInlineQueryConfig,
        TelegramSetMessageReactionConfig,
        # Bot info
        TelegramGetMeConfig,
        TelegramGetFileConfig,
        # Payments
        TelegramSendInvoiceConfig,
        TelegramAnswerPreCheckoutQueryConfig,
        # Setup flow
        TelegramSetupChannelConfig,
        TelegramConnectChannelConfig,
    ],
    Field(discriminator="operation"),
]


class TelegramNodeConfig(NodeConfig[TelegramConfig, TelegramBotTokenCredential]):
    """Full configuration for Telegram node including credentials"""

    @model_validator(mode="before")
    @classmethod
    def infer_operation(cls, data: Any) -> Any:
        """Infer operation from config fields for backward compatibility."""
        if isinstance(data, dict) and "config" in data:
            config = data["config"]
            if isinstance(config, dict) and "operation" not in config:
                if "webhook_url" in config and "webhookUrl" not in config:
                    config["operation"] = "receive_webhook_messages"
                elif "chatId" in config:
                    config["operation"] = "send_message_to_chat"
                elif "username" in config:
                    config["operation"] = "send_message_to_channel"
                elif "webhookUrl" in config:
                    config["operation"] = "send_webhook_delivery"
        return data


# ============================================================================
# Telegram Node Implementation
# ============================================================================


class TelegramNode(WorkflowNode):
    """
    Telegram automation node supporting 48 operations across messaging,
    media, polls, chat management, payments, and guided channel setup.
    """

    edit_examples = [
        'Send a text message to chat 123456789: "Meeting in 5 minutes"',
        "Send a photo to the #alerts channel with a caption",
        "Edit a previously sent message with updated status",
        "Create a poll with voting options in the team chat",
        "Ban a spammer from the group and send notification",
        "Forward a message from #general to #archive with context",
        "Set up a webhook to receive incoming messages from Telegram",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        return TelegramNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """For setup_channel: always force execute() (handles my_chat_member, /start, and idle runs).
        For all other operations: use payload directly as output (default behavior)."""
        operation = config.get("operation")
        if operation == "setup_telegram_channel_guided":
            return None  # Always force execute() — _handle_setup_channel handles all update types
        if not isinstance(payload, dict):
            return None  # Non-dict payload: no real webhook, let execute() run normally
        return payload  # Default: payload IS the output

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Telegram update → message text for the agent's user turn + the chat
        id as conversation key (one conversation per chat). The chat id in the
        text doubles as the reply id for send-message tools."""
        msg = next(
            (
                output[k]
                for k in (
                    "message",
                    "edited_message",
                    "channel_post",
                    "edited_channel_post",
                )
                if isinstance(output.get(k), dict)
            ),
            None,
        )
        text = (msg or {}).get("text") or (msg or {}).get("caption")
        if not msg or not text:
            # Non-message updates (callbacks, member changes, media without
            # caption): deliver the raw update as JSON.
            return super().resolve_agent_event(output)
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        sender = msg.get("from") or {}
        who = sender.get("username") or sender.get("first_name") or "unknown"
        where = f"chat {chat_id}" + (f" ({chat['title']})" if chat.get("title") else "")
        return {
            "text": f"Telegram message from {who} in {where}:\n{text}",
            "conversation_key": str(chat_id) if chat_id is not None else None,
        }

    @classmethod
    async def cleanup_external_webhook(
        cls, pool, workflow_id, node_id, config, credentials=None
    ):
        bot_token = credentials.get("bot_token") if credentials else None
        if bot_token:
            await delete_telegram_webhook(bot_token)

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
        """Load computed field values for webhook_url and setup_channel fields."""

        # ---- setup_channel: channel_id polling ----
        if field_name == "channel_id":
            result = await _get_setup_result(str(workflow_id), node_id)
            if result:
                return {
                    "values": {
                        "channel_id": result["channel_id"],
                        "channel_title": result.get("channel_title", ""),
                        "setup_status": "complete",
                    }
                }
            return {"value": None}

        if field_name not in ("webhook_url",):
            return {"value": None}

        # ---- webhook_url (used by both receive and setup_channel) ----
        from utils.encryption import get_encryption

        credential_id = (
            credential_ids.get("telegram_bot_token") if credential_ids else None
        )

        if not credential_id:
            logger.warning(f"[TelegramNode] No bot token credential for node {node_id}")
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
                    "telegram_registered": False,
                    "telegram_error": "Bot token not configured — please add credentials",
                }
            }

        try:
            from repositories.credentials import credential_access_predicate
            from repositories.organization import PRIMARY_ORG_SQL

            async with pool.acquire() as conn:
                org_row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
                org_id = str(org_row["organization_id"]) if org_row else None
                row = await conn.fetchrow(
                    f"""
                    SELECT c.credential FROM credentials c
                    WHERE c.id = $1 AND {credential_access_predicate()}
                    """,
                    credential_id,
                    user_id,
                    org_id,
                )
                if not row:
                    return {
                        "values": {
                            "telegram_registered": False,
                            "telegram_error": "Bot token credential not found",
                        }
                    }
                encryption = get_encryption()
                credential_data = encryption.decrypt_credential(row["credential"])
                bot_token = credential_data.get("token")
                if not bot_token:
                    return {
                        "values": {
                            "telegram_registered": False,
                            "telegram_error": "Bot token is empty",
                        }
                    }
        except Exception as e:
            logger.error(f"[TelegramNode] Error fetching credential: {e}")
            return {
                "values": {
                    "telegram_registered": False,
                    "telegram_error": f"Error fetching credential: {e}",
                }
            }

        result = await setup_telegram_trigger_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            bot_token=bot_token,
        )

        # For setup_channel mode: also compute the setup_link
        extra = {}
        if context and context.get("operation") == "setup_telegram_channel_guided":
            try:
                async with httpx.AsyncClient() as client:
                    me_resp = await client.get(
                        f"{TELEGRAM_API_BASE}{bot_token}/getMe", timeout=10.0
                    )
                    me_data = me_resp.json()
                    if me_data.get("ok"):
                        username = me_data["result"].get("username", "")
                        token = uuid4().hex[:16]
                        await _store_setup_token(
                            token, str(workflow_id), node_id, user_id
                        )
                        extra["setup_token"] = token
                        extra[
                            "setup_link"
                        ] = f"https://t.me/{username}?start=setup_{token}"
                        extra["setup_status"] = "pending"
            except Exception as e:
                logger.warning(f"[TelegramNode] Could not generate setup_link: {e}")

        return {"values": {**result, **extra}}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the Telegram node."""
        logger.info(f"[TelegramNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, TelegramNodeConfig):
            raise ValueError(
                f"[TelegramNode] Configuration required for node {self.node_id}"
            )

        config = node_config.config
        credentials = node_config.credentials

        # ---- Original operations (unchanged behaviour) ----
        if isinstance(config, TelegramReceiveConfig):
            output = await self._handle_receive(inputs)
        elif isinstance(config, TelegramChatIdConfig):
            chat_id = (
                str(config.chatId) if isinstance(config.chatId, int) else config.chatId
            )
            output = await self._send_message(
                credentials, chat_id, config.message, method="chatId"
            )
        elif isinstance(config, TelegramChannelConfig):
            username = (
                config.username
                if config.username.startswith("@")
                else f"@{config.username}"
            )
            output = await self._send_message(
                credentials, username, config.message, method="channel"
            )
        elif isinstance(config, TelegramSendDocumentConfig):
            chat_id = (
                str(config.chatId) if isinstance(config.chatId, int) else config.chatId
            )
            output = await self._send_document(
                credentials, chat_id, config.document_url, config.caption
            )
        elif isinstance(config, TelegramWebhookConfig):
            output = await self._send_to_webhook(config.webhookUrl)

        # ---- Setup channel flow ----
        elif isinstance(config, TelegramSetupChannelConfig):
            output = await self._handle_setup_channel(config, inputs)

        # ---- Connect channel (simple, setup-flow-friendly) ----
        elif isinstance(config, TelegramConnectChannelConfig):
            output = await self._handle_connect_channel(credentials, config)

        # ---- Rich media ----
        elif isinstance(config, TelegramSendPhotoConfig):
            output = await self._handle_send_photo(credentials, config)
        elif isinstance(config, TelegramSendVideoConfig):
            output = await self._handle_send_video(credentials, config)
        elif isinstance(config, TelegramSendAudioConfig):
            output = await self._handle_send_audio(credentials, config)
        elif isinstance(config, TelegramSendVoiceConfig):
            output = await self._handle_send_voice(credentials, config)
        elif isinstance(config, TelegramSendAnimationConfig):
            output = await self._handle_send_animation(credentials, config)
        elif isinstance(config, TelegramSendVideoNoteConfig):
            output = await self._handle_send_video_note(credentials, config)
        elif isinstance(config, TelegramSendStickerConfig):
            output = await self._handle_send_sticker(credentials, config)
        elif isinstance(config, TelegramSendMediaGroupConfig):
            output = await self._handle_send_media_group(credentials, config)
        elif isinstance(config, TelegramSendContactConfig):
            output = await self._handle_send_contact(credentials, config)
        elif isinstance(config, TelegramSendLocationConfig):
            output = await self._handle_send_location(credentials, config)
        elif isinstance(config, TelegramSendVenueConfig):
            output = await self._handle_send_venue(credentials, config)
        elif isinstance(config, TelegramSendDiceConfig):
            output = await self._handle_send_dice(credentials, config)

        # ---- Message management ----
        elif isinstance(config, TelegramEditMessageTextConfig):
            output = await self._handle_edit_message_text(credentials, config)
        elif isinstance(config, TelegramEditMessageCaptionConfig):
            output = await self._handle_edit_message_caption(credentials, config)
        elif isinstance(config, TelegramDeleteMessageConfig):
            output = await self._handle_delete_message(credentials, config)
        elif isinstance(config, TelegramDeleteMessagesConfig):
            output = await self._handle_delete_messages(credentials, config)
        elif isinstance(config, TelegramPinMessageConfig):
            output = await self._handle_pin_message(credentials, config)
        elif isinstance(config, TelegramUnpinMessageConfig):
            output = await self._handle_unpin_message(credentials, config)
        elif isinstance(config, TelegramForwardMessageConfig):
            output = await self._handle_forward_message(credentials, config)
        elif isinstance(config, TelegramCopyMessageConfig):
            output = await self._handle_copy_message(credentials, config)
        elif isinstance(config, TelegramSendChatActionConfig):
            output = await self._handle_send_chat_action(credentials, config)

        # ---- Polls ----
        elif isinstance(config, TelegramSendPollConfig):
            output = await self._handle_send_poll(credentials, config)
        elif isinstance(config, TelegramStopPollConfig):
            output = await self._handle_stop_poll(credentials, config)

        # ---- Chat info ----
        elif isinstance(config, TelegramGetChatConfig):
            output = await self._handle_get_chat(credentials, config)
        elif isinstance(config, TelegramGetChatMemberConfig):
            output = await self._handle_get_chat_member(credentials, config)
        elif isinstance(config, TelegramGetChatMemberCountConfig):
            output = await self._handle_get_chat_member_count(credentials, config)
        elif isinstance(config, TelegramGetChatAdministratorsConfig):
            output = await self._handle_get_chat_administrators(credentials, config)

        # ---- Group/channel management ----
        elif isinstance(config, TelegramBanChatMemberConfig):
            output = await self._handle_ban_chat_member(credentials, config)
        elif isinstance(config, TelegramUnbanChatMemberConfig):
            output = await self._handle_unban_chat_member(credentials, config)
        elif isinstance(config, TelegramRestrictChatMemberConfig):
            output = await self._handle_restrict_chat_member(credentials, config)
        elif isinstance(config, TelegramPromoteChatMemberConfig):
            output = await self._handle_promote_chat_member(credentials, config)
        elif isinstance(config, TelegramSetChatTitleConfig):
            output = await self._handle_set_chat_title(credentials, config)
        elif isinstance(config, TelegramSetChatDescriptionConfig):
            output = await self._handle_set_chat_description(credentials, config)
        elif isinstance(config, TelegramCreateInviteLinkConfig):
            output = await self._handle_create_invite_link(credentials, config)
        elif isinstance(config, TelegramRevokeInviteLinkConfig):
            output = await self._handle_revoke_invite_link(credentials, config)

        # ---- Inline/callback ----
        elif isinstance(config, TelegramAnswerCallbackQueryConfig):
            output = await self._handle_answer_callback_query(credentials, config)
        elif isinstance(config, TelegramAnswerInlineQueryConfig):
            output = await self._handle_answer_inline_query(credentials, config)
        elif isinstance(config, TelegramSetMessageReactionConfig):
            output = await self._handle_set_message_reaction(credentials, config)

        # ---- Bot info ----
        elif isinstance(config, TelegramGetMeConfig):
            output = await self._handle_get_me(credentials)
        elif isinstance(config, TelegramGetFileConfig):
            output = await self._handle_get_file(credentials, config)

        # ---- Payments ----
        elif isinstance(config, TelegramSendInvoiceConfig):
            output = await self._handle_send_invoice(credentials, config)
        elif isinstance(config, TelegramAnswerPreCheckoutQueryConfig):
            output = await self._handle_answer_pre_checkout_query(credentials, config)

        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        await self.emit(output)
        return output

    # ============================================================================
    # Shared HTTP helper
    # ============================================================================

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: Optional[TelegramBotTokenCredential],
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Authenticated request to the Telegram Bot API. Raises ValueError on error."""
        if not credentials:
            raise ValueError(
                "[TelegramNode] Bot token is required. Please add credentials to this node."
            )
        url = f"{TELEGRAM_API_BASE}{credentials.token}/{endpoint}"
        timeout = (
            60.0
            if endpoint in ("sendDocument", "sendVideo", "sendAudio", "sendAnimation")
            else 30.0
        )
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, url, json=json_data, timeout=timeout
            )
        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("description", response.text)
            error_code = error_data.get("error_code", response.status_code)
            raise ValueError(f"Telegram API error ({error_code}): {error_msg}")
        result = response.json()
        if not result.get("ok"):
            raise ValueError(
                f"Telegram API error: {result.get('description', 'Unknown error')}"
            )
        return result.get("result", {})

    def _chat_id_str(self, chat_id: Union[str, int]) -> str:
        return str(chat_id) if isinstance(chat_id, int) else chat_id

    # ============================================================================
    # Original operation handlers (unchanged)
    # ============================================================================

    async def _send_message(self, credentials, chat_id, message, method):
        if not credentials:
            raise ValueError("[TelegramNode] Bot token required.")
        bot_token = credentials.token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=30.0,
            )
        if response.status_code != 200:
            error_data = response.json()
            raise ValueError(
                f"Telegram API error ({error_data.get('error_code', response.status_code)}): {error_data.get('description', response.text)}"
            )
        result = response.json()
        if not result.get("ok"):
            raise ValueError(
                f"Telegram API error: {result.get('description', 'Unknown error')}"
            )
        sent = result.get("result", {})
        return {
            "type": "telegram",
            "method": method,
            "message": message,
            "chat_id": chat_id,
            "message_id": sent.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _send_document(self, credentials, chat_id, document_url, caption=""):
        if not credentials:
            raise ValueError("[TelegramNode] Bot token required.")
        document_url = await self._resolve_media_ref(document_url)
        payload: Dict[str, Any] = {"chat_id": chat_id, "document": document_url}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{credentials.token}/sendDocument",
                json=payload,
                timeout=60.0,
            )
        if response.status_code != 200:
            error_data = response.json()
            raise ValueError(
                f"Telegram API error ({error_data.get('error_code', response.status_code)}): {error_data.get('description', response.text)}"
            )
        result = response.json()
        if not result.get("ok"):
            raise ValueError(
                f"Telegram API error: {result.get('description', 'Unknown error')}"
            )
        sent = result.get("result", {})
        doc = sent.get("document", {})
        return {
            "type": "telegram",
            "method": "send_document",
            "chat_id": chat_id,
            "document_url": document_url,
            "caption": caption,
            "message_id": sent.get("message_id"),
            "file_id": doc.get("file_id"),
            "file_name": doc.get("file_name"),
            "file_size": doc.get("file_size"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _send_to_webhook(self, webhook_url):
        async with guarded_async_client() as client:
            response = await client.post(
                str(webhook_url),
                json={"source": "telegram_node", "timestamp": time.time()},
                timeout=30.0,
            )
        output = {
            "type": "telegram",
            "method": "webhook",
            "webhook_url": str(webhook_url),
            "response_status": response.status_code,
            "timestamp": time.time(),
            "status": "sent" if response.status_code < 400 else "failed",
        }
        if response.status_code >= 400:
            output["error"] = f"Webhook returned status {response.status_code}"
        return output

    async def _ensure_telegram_webhook_registered(self):
        if not self.config or not isinstance(self.config, TelegramNodeConfig):
            return
        config = self.config.config
        credentials = self.config.credentials
        if not isinstance(config, (TelegramReceiveConfig, TelegramSetupChannelConfig)):
            return
        if not credentials or not credentials.token:
            return
        webhook_url = config.webhook_url
        if not webhook_url:
            return
        try:
            result = await set_telegram_webhook(credentials.token, webhook_url)
            if not result.get("success"):
                logger.warning(
                    f"[TelegramNode] Failed to re-register webhook: {result.get('error')}"
                )
        except Exception as e:
            logger.warning(f"[TelegramNode] Error during webhook re-registration: {e}")

    async def _handle_receive(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[TelegramNode] Handling received message for node {self.node_id}")
        await self._ensure_telegram_webhook_registered()
        webhook_meta = inputs.get("_webhook", {})
        message = inputs.get("message", {})
        callback_query = inputs.get("callback_query", {})
        inline_query = inputs.get("inline_query", {})
        update_type = "unknown"
        chat_id = None
        from_user = None
        text = None
        if message:
            update_type = "message"
            chat_id = message.get("chat", {}).get("id")
            from_user = message.get("from", {})
            text = message.get("text", "")
        elif callback_query:
            update_type = "callback_query"
            chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
            from_user = callback_query.get("from", {})
            text = callback_query.get("data", "")
        elif inline_query:
            update_type = "inline_query"
            from_user = inline_query.get("from", {})
            text = inline_query.get("query", "")
        return {
            "type": "telegram",
            "method": "receive",
            "status": "triggered",
            "timestamp": time.time(),
            "update_id": inputs.get("update_id"),
            "update_type": update_type,
            "chat_id": chat_id,
            "from_user": from_user,
            "text": text,
            "message": message or None,
            "callback_query": callback_query or None,
            "inline_query": inline_query or None,
            "raw_update": {k: v for k, v in inputs.items() if k != "_webhook"},
            "webhook_id": webhook_meta.get("id"),
        }

    # ============================================================================
    # Connect channel handler (simple, setup-flow-friendly)
    # ============================================================================

    async def _handle_connect_channel(
        self,
        credentials: TelegramBotTokenCredential,
        config: TelegramConnectChannelConfig,
    ) -> Dict[str, Any]:
        """Validate a channel by @username or ID and confirm bot has admin rights."""
        token = credentials.token
        identifier = config.channel_identifier.strip()
        if not identifier:
            raise ValueError(
                "channel_identifier is required. Enter @username or numeric channel ID."
            )

        async with httpx.AsyncClient() as client:
            # Resolve channel info
            chat_resp = await client.get(
                f"{TELEGRAM_API_BASE}{token}/getChat",
                params={"chat_id": identifier},
                timeout=10.0,
            )
            chat_data = chat_resp.json()
            if not chat_data.get("ok"):
                desc = chat_data.get("description", "Unknown error")
                raise ValueError(
                    f"Channel not found: {desc}. "
                    "Make sure the @username is correct and the bot is already a member of the channel."
                )

            chat = chat_data["result"]
            channel_id = str(chat["id"])
            channel_title = chat.get("title", "")
            channel_username = chat.get("username", "")

            # Get bot's own user ID
            me_resp = await client.get(
                f"{TELEGRAM_API_BASE}{token}/getMe", timeout=10.0
            )
            me_data = me_resp.json()
            if not me_data.get("ok"):
                raise ValueError("Could not get bot info from Telegram.")
            bot_id = me_data["result"]["id"]

            # Check admin status
            member_resp = await client.get(
                f"{TELEGRAM_API_BASE}{token}/getChatMember",
                params={"chat_id": channel_id, "user_id": bot_id},
                timeout=10.0,
            )
            member_data = member_resp.json()

        bot_is_admin = False
        if member_data.get("ok"):
            status = member_data["result"].get("status", "")
            bot_is_admin = status in ("administrator", "creator")

        if not bot_is_admin:
            raise ValueError(
                f"Bot is not an admin of '{channel_title or identifier}'. "
                "To fix this:\n"
                "1. Open Telegram → go to your channel\n"
                "2. Tap the channel name → Edit → Administrators\n"
                "3. Tap Add Administrator → search for your bot → select it\n"
                "4. Enable Post Messages permission → tap Save\n"
                "Then run setup again."
            )

        return {
            "channel_id": channel_id,
            "channel_title": channel_title,
            "channel_username": f"@{channel_username}" if channel_username else "",
            "bot_is_admin": True,
            "status": "connected",
        }

    # ============================================================================
    # Setup channel handler
    # ============================================================================

    async def _handle_setup_channel(
        self, config: TelegramSetupChannelConfig, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle setup_channel: detect my_chat_member admin promotion and store channel_id."""
        await self._ensure_telegram_webhook_registered()

        # Telegram webhook payloads arrive via _triggerPayload in node_data (set by the execution
        # engine when a webhook fires). After credential resolution node_data becomes
        # {'config': {..., '_triggerPayload': {...}}, 'credentials': {...}}.
        # Predecessor node outputs in `inputs` are keyed by node ID, not by Telegram update
        # keys, so we read the trigger payload from node_data['config'] instead.
        node_config_raw = self.node_data or {}
        trigger_payload = (
            node_config_raw.get("_triggerPayload")
            or node_config_raw.get("config", {}).get("_triggerPayload")
            or {}
        )

        # Check if triggered by a my_chat_member update (bot added as admin to a channel)
        my_chat_member = trigger_payload.get("my_chat_member", {})
        if my_chat_member:
            new_member = my_chat_member.get("new_chat_member", {})
            chat = my_chat_member.get("chat", {})
            status = new_member.get("status", "")
            # Bot was made admin (administrator) or creator
            if status in ("administrator", "creator"):
                channel_id = str(chat.get("id", ""))
                channel_title = chat.get("title", "")
                chat_type = chat.get("type", "")
                if channel_id:
                    await _store_setup_result(
                        str(self.workflow_id), self.node_id, channel_id, channel_title
                    )
                    logger.info(
                        f"[TelegramNode] Setup complete: channel_id={channel_id} ({channel_title})"
                    )
                    # Optionally notify the user who triggered setup via /start
                    from_user = my_chat_member.get("from", {})
                    from_chat_id = from_user.get("id")
                    if from_chat_id and self.config and self.config.credentials:
                        try:
                            await self._make_request(
                                "POST",
                                "sendMessage",
                                self.config.credentials,
                                {
                                    "chat_id": from_chat_id,
                                    "text": f"✅ Channel connected!\n\nBot has been added as admin to <b>{channel_title}</b>.\nChannel ID: <code>{channel_id}</code>\n\nYou can now close this and return to NoClick.",
                                    "parse_mode": "HTML",
                                },
                            )
                        except Exception:
                            pass  # Best-effort notification
                    return {
                        "type": "telegram",
                        "operation": "setup_telegram_channel_guided",
                        "status": "complete",
                        "channel_id": channel_id,
                        "channel_title": channel_title,
                        "chat_type": chat_type,
                        "timestamp": time.time(),
                    }

        # Check if triggered by /start setup_{token} message
        message = trigger_payload.get("message", {})
        if message:
            text = message.get("text", "")
            if text.startswith("/start setup_"):
                token = text.split("/start setup_", 1)[1].strip()
                token_data = await _get_setup_token_data(token)
                from_user = message.get("from", {})
                from_chat_id = message.get("chat", {}).get("id")
                if (
                    token_data
                    and from_chat_id
                    and self.config
                    and self.config.credentials
                ):
                    try:
                        await self._make_request(
                            "POST",
                            "sendMessage",
                            self.config.credentials,
                            {
                                "chat_id": from_chat_id,
                                "text": "👋 Great! Now add me as <b>admin</b> to the channel you want to connect.\n\nOnce you make me admin, I'll automatically detect the channel ID.",
                                "parse_mode": "HTML",
                            },
                        )
                    except Exception:
                        pass

        # Check if channel is already resolved (polling path)
        existing = await _get_setup_result(str(self.workflow_id), self.node_id)
        if existing:
            return {
                "type": "telegram",
                "operation": "setup_telegram_channel_guided",
                "status": "complete",
                "channel_id": existing["channel_id"],
                "channel_title": existing.get("channel_title", ""),
                "timestamp": time.time(),
            }

        # Generate setup_link dynamically if not already stored in config.
        # This handles the case where load_field_value ran before credentials were set.
        setup_link = config.setup_link
        setup_token = config.setup_token
        credentials = self.config.credentials if self.config else None

        if (not setup_link or not setup_token) and credentials and credentials.token:
            try:
                async with httpx.AsyncClient() as client:
                    me_resp = await client.get(
                        f"{TELEGRAM_API_BASE}{credentials.token}/getMe", timeout=10.0
                    )
                    me_data = me_resp.json()
                    if me_data.get("ok"):
                        username = me_data["result"].get("username", "")
                        if not setup_token:
                            setup_token = uuid4().hex[:16]
                            await _store_setup_token(
                                setup_token,
                                str(self.workflow_id),
                                self.node_id,
                                self.user_id or "",
                            )
                        setup_link = (
                            f"https://t.me/{username}?start=setup_{setup_token}"
                        )
                        logger.info(
                            f"[TelegramNode] Generated setup_link for node {self.node_id}"
                        )
            except Exception as e:
                logger.warning(f"[TelegramNode] Could not generate setup_link: {e}")

        return {
            "type": "telegram",
            "operation": "setup_telegram_channel_guided",
            "status": "pending",
            "setup_link": setup_link,
            "setup_token": setup_token,
            "timestamp": time.time(),
        }

    # ============================================================================
    # Rich media handlers
    # ============================================================================

    async def _resolve_media_ref(self, value: str) -> str:
        """Telegram's API fetches a URL or reuses a file_id. A workflow
        resource_id (from an upstream HTTP download/upload) is resolved to a
        fetchable presigned URL; URLs and file_ids pass through unchanged."""
        from nodes.core.media_resolver import is_resource_id, resolve_media_input

        if value and is_resource_id(value):
            return (await resolve_media_input(value)).download_url
        return value

    async def _handle_send_photo(
        self, creds, config: TelegramSendPhotoConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {"chat_id": chat_id, "photo": await self._resolve_media_ref(config.photo)}
        if config.caption:
            payload["caption"] = config.caption
            payload["parse_mode"] = config.parse_mode or "HTML"
        result = await self._make_request("POST", "sendPhoto", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_photo_image",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_video(
        self, creds, config: TelegramSendVideoConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {"chat_id": chat_id, "video": await self._resolve_media_ref(config.video)}
        if config.caption:
            payload["caption"] = config.caption
            payload["parse_mode"] = config.parse_mode or "HTML"
        if config.duration:
            payload["duration"] = int(config.duration)
        if config.width:
            payload["width"] = int(config.width)
        if config.height:
            payload["height"] = int(config.height)
        result = await self._make_request("POST", "sendVideo", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_video_file",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_audio(
        self, creds, config: TelegramSendAudioConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {"chat_id": chat_id, "audio": await self._resolve_media_ref(config.audio)}
        if config.caption:
            payload["caption"] = config.caption
        if config.performer:
            payload["performer"] = config.performer
        if config.title:
            payload["title"] = config.title
        if config.duration:
            payload["duration"] = int(config.duration)
        result = await self._make_request("POST", "sendAudio", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_audio_file",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_voice(
        self, creds, config: TelegramSendVoiceConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {"chat_id": chat_id, "voice": await self._resolve_media_ref(config.voice)}
        if config.caption:
            payload["caption"] = config.caption
        if config.duration:
            payload["duration"] = int(config.duration)
        result = await self._make_request("POST", "sendVoice", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_voice_note",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_animation(
        self, creds, config: TelegramSendAnimationConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {"chat_id": chat_id, "animation": config.animation}
        if config.caption:
            payload["caption"] = config.caption
            payload["parse_mode"] = config.parse_mode or "HTML"
        result = await self._make_request("POST", "sendAnimation", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_animated_video",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_video_note(
        self, creds, config: TelegramSendVideoNoteConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {"chat_id": chat_id, "video_note": await self._resolve_media_ref(config.video_note)}
        if config.duration:
            payload["duration"] = int(config.duration)
        if config.length:
            payload["length"] = int(config.length)
        result = await self._make_request("POST", "sendVideoNote", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_circular_video",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_sticker(
        self, creds, config: TelegramSendStickerConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {"chat_id": chat_id, "sticker": config.sticker}
        if config.emoji:
            payload["emoji"] = config.emoji
        result = await self._make_request("POST", "sendSticker", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_sticker",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_media_group(
        self, creds, config: TelegramSendMediaGroupConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        try:
            media_list = json.loads(config.media)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid media JSON: {e}")
        if not isinstance(media_list, list) or len(media_list) < 2:
            raise ValueError("media must be a JSON array with 2–10 items")
        result = await self._make_request(
            "POST", "sendMediaGroup", creds, {"chat_id": chat_id, "media": media_list}
        )
        message_ids = [
            m.get("message_id") for m in (result if isinstance(result, list) else [])
        ]
        return {
            "type": "telegram",
            "operation": "send_photo_video_album",
            "chat_id": chat_id,
            "message_ids": message_ids,
            "count": len(message_ids),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_contact(
        self, creds, config: TelegramSendContactConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "phone_number": config.phone_number,
            "first_name": config.first_name,
        }
        if config.last_name:
            payload["last_name"] = config.last_name
        result = await self._make_request("POST", "sendContact", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_contact_information",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_location(
        self, creds, config: TelegramSendLocationConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "latitude": float(config.latitude),
            "longitude": float(config.longitude),
        }
        if config.horizontal_accuracy:
            payload["horizontal_accuracy"] = float(config.horizontal_accuracy)
        result = await self._make_request("POST", "sendLocation", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_location_pin",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_venue(
        self, creds, config: TelegramSendVenueConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "latitude": float(config.latitude),
            "longitude": float(config.longitude),
            "title": config.title,
            "address": config.address,
        }
        if config.foursquare_id:
            payload["foursquare_id"] = config.foursquare_id
        result = await self._make_request("POST", "sendVenue", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_venue_location",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_send_dice(
        self, creds, config: TelegramSendDiceConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        result = await self._make_request(
            "POST", "sendDice", creds, {"chat_id": chat_id, "emoji": config.emoji}
        )
        dice = result.get("dice", {})
        return {
            "type": "telegram",
            "operation": "send_dice_emoji",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "emoji": dice.get("emoji"),
            "value": dice.get("value"),
            "timestamp": time.time(),
            "status": "sent",
        }

    # ============================================================================
    # Message management handlers
    # ============================================================================

    async def _handle_edit_message_text(
        self, creds, config: TelegramEditMessageTextConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(config.message_id),
            "text": config.text,
        }
        if config.parse_mode:
            payload["parse_mode"] = config.parse_mode
        result = await self._make_request("POST", "editMessageText", creds, payload)
        return {
            "type": "telegram",
            "operation": "edit_message_text",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "edited",
        }

    async def _handle_edit_message_caption(
        self, creds, config: TelegramEditMessageCaptionConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(config.message_id),
            "caption": config.caption,
        }
        if config.parse_mode:
            payload["parse_mode"] = config.parse_mode
        result = await self._make_request("POST", "editMessageCaption", creds, payload)
        return {
            "type": "telegram",
            "operation": "edit_message_caption",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "edited",
        }

    async def _handle_delete_message(
        self, creds, config: TelegramDeleteMessageConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        await self._make_request(
            "POST",
            "deleteMessage",
            creds,
            {"chat_id": chat_id, "message_id": int(config.message_id)},
        )
        return {
            "type": "telegram",
            "operation": "delete_message",
            "chat_id": chat_id,
            "message_id": config.message_id,
            "timestamp": time.time(),
            "status": "deleted",
        }

    async def _handle_delete_messages(
        self, creds, config: TelegramDeleteMessagesConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        ids = [int(i.strip()) for i in config.message_ids.split(",") if i.strip()]
        await self._make_request(
            "POST", "deleteMessages", creds, {"chat_id": chat_id, "message_ids": ids}
        )
        return {
            "type": "telegram",
            "operation": "delete_multiple_messages",
            "chat_id": chat_id,
            "message_ids": ids,
            "count": len(ids),
            "timestamp": time.time(),
            "status": "deleted",
        }

    async def _handle_pin_message(
        self, creds, config: TelegramPinMessageConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(config.message_id),
            "disable_notification": config.disable_notification == "true",
        }
        await self._make_request("POST", "pinChatMessage", creds, payload)
        return {
            "type": "telegram",
            "operation": "pin_message_in_chat",
            "chat_id": chat_id,
            "message_id": config.message_id,
            "timestamp": time.time(),
            "status": "pinned",
        }

    async def _handle_unpin_message(
        self, creds, config: TelegramUnpinMessageConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        if config.message_id:
            await self._make_request(
                "POST",
                "unpinChatMessage",
                creds,
                {"chat_id": chat_id, "message_id": int(config.message_id)},
            )
            status_msg = "unpinned"
        else:
            await self._make_request(
                "POST", "unpinAllChatMessages", creds, {"chat_id": chat_id}
            )
            status_msg = "all_unpinned"
        return {
            "type": "telegram",
            "operation": "unpin_chat_message",
            "chat_id": chat_id,
            "timestamp": time.time(),
            "status": status_msg,
        }

    async def _handle_forward_message(
        self, creds, config: TelegramForwardMessageConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        from_chat_id = self._chat_id_str(config.from_chat_id)
        result = await self._make_request(
            "POST",
            "forwardMessage",
            creds,
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_id": int(config.message_id),
            },
        )
        return {
            "type": "telegram",
            "operation": "forward_message_to_chat",
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "forwarded",
        }

    async def _handle_copy_message(
        self, creds, config: TelegramCopyMessageConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        from_chat_id = self._chat_id_str(config.from_chat_id)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": int(config.message_id),
        }
        if config.caption:
            payload["caption"] = config.caption
            payload["parse_mode"] = "HTML"
        result = await self._make_request("POST", "copyMessage", creds, payload)
        return {
            "type": "telegram",
            "operation": "copy_message_to_chat",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "copied",
        }

    async def _handle_send_chat_action(
        self, creds, config: TelegramSendChatActionConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        await self._make_request(
            "POST",
            "sendChatAction",
            creds,
            {"chat_id": chat_id, "action": config.action},
        )
        return {
            "type": "telegram",
            "operation": "send_chat_typing_indicator",
            "chat_id": chat_id,
            "action": config.action,
            "timestamp": time.time(),
            "status": "sent",
        }

    # ============================================================================
    # Poll handlers
    # ============================================================================

    async def _handle_send_poll(
        self, creds, config: TelegramSendPollConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        try:
            options = json.loads(config.options)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid options JSON: {e}")
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "question": config.question,
            "options": options,
            "is_anonymous": config.is_anonymous == "true",
            "type": config.poll_type,
            "allows_multiple_answers": config.allows_multiple_answers == "true",
        }
        if config.poll_type == "quiz" and config.correct_option_id:
            payload["correct_option_id"] = int(config.correct_option_id)
        if config.explanation:
            payload["explanation"] = config.explanation
        result = await self._make_request("POST", "sendPoll", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_poll_or_quiz",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_stop_poll(
        self, creds, config: TelegramStopPollConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        result = await self._make_request(
            "POST",
            "stopPoll",
            creds,
            {"chat_id": chat_id, "message_id": int(config.message_id)},
        )
        return {
            "type": "telegram",
            "operation": "stop_active_poll",
            "chat_id": chat_id,
            "poll": result,
            "timestamp": time.time(),
            "status": "stopped",
        }

    # ============================================================================
    # Chat info handlers
    # ============================================================================

    async def _handle_get_chat(
        self, creds, config: TelegramGetChatConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        result = await self._make_request(
            "POST", "getChat", creds, {"chat_id": chat_id}
        )
        return {
            "type": "telegram",
            "operation": "get_chat_details",
            "chat": result,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _handle_get_chat_member(
        self, creds, config: TelegramGetChatMemberConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        result = await self._make_request(
            "POST",
            "getChatMember",
            creds,
            {"chat_id": chat_id, "user_id": int(config.user_id)},
        )
        return {
            "type": "telegram",
            "operation": "get_chat_member_info",
            "chat_id": chat_id,
            "member": result,
            "status": result.get("status"),
            "timestamp": time.time(),
        }

    async def _handle_get_chat_member_count(
        self, creds, config: TelegramGetChatMemberCountConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        result = await self._make_request(
            "POST", "getChatMemberCount", creds, {"chat_id": chat_id}
        )
        return {
            "type": "telegram",
            "operation": "get_chat_member_count",
            "chat_id": chat_id,
            "count": result,
            "timestamp": time.time(),
            "status": "success",
        }

    async def _handle_get_chat_administrators(
        self, creds, config: TelegramGetChatAdministratorsConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        result = await self._make_request(
            "POST", "getChatAdministrators", creds, {"chat_id": chat_id}
        )
        admins = result if isinstance(result, list) else []
        return {
            "type": "telegram",
            "operation": "get_chat_admin_list",
            "chat_id": chat_id,
            "administrators": admins,
            "count": len(admins),
            "timestamp": time.time(),
            "status": "success",
        }

    # ============================================================================
    # Group/channel management handlers
    # ============================================================================

    async def _handle_ban_chat_member(
        self, creds, config: TelegramBanChatMemberConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "user_id": int(config.user_id),
            "revoke_messages": config.revoke_messages == "true",
        }
        if config.until_date:
            payload["until_date"] = int(config.until_date)
        await self._make_request("POST", "banChatMember", creds, payload)
        return {
            "type": "telegram",
            "operation": "ban_user_from_chat",
            "chat_id": chat_id,
            "user_id": config.user_id,
            "timestamp": time.time(),
            "status": "banned",
        }

    async def _handle_unban_chat_member(
        self, creds, config: TelegramUnbanChatMemberConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        await self._make_request(
            "POST",
            "unbanChatMember",
            creds,
            {"chat_id": chat_id, "user_id": int(config.user_id)},
        )
        return {
            "type": "telegram",
            "operation": "unban_user_from_chat",
            "chat_id": chat_id,
            "user_id": config.user_id,
            "timestamp": time.time(),
            "status": "unbanned",
        }

    async def _handle_restrict_chat_member(
        self, creds, config: TelegramRestrictChatMemberConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        try:
            permissions = json.loads(config.permissions)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid permissions JSON: {e}")
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "user_id": int(config.user_id),
            "permissions": permissions,
        }
        if config.until_date:
            payload["until_date"] = int(config.until_date)
        await self._make_request("POST", "restrictChatMember", creds, payload)
        return {
            "type": "telegram",
            "operation": "restrict_user_permissions",
            "chat_id": chat_id,
            "user_id": config.user_id,
            "timestamp": time.time(),
            "status": "restricted",
        }

    async def _handle_promote_chat_member(
        self, creds, config: TelegramPromoteChatMemberConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "user_id": int(config.user_id),
            "can_post_messages": config.can_post_messages == "true",
            "can_edit_messages": config.can_edit_messages == "true",
            "can_delete_messages": config.can_delete_messages == "true",
            "can_manage_video_chats": config.can_manage_video_chats == "true",
            "can_restrict_members": config.can_restrict_members == "true",
            "can_promote_members": config.can_promote_members == "true",
            "can_change_info": config.can_change_info == "true",
            "can_invite_users": config.can_invite_users == "true",
            "can_pin_messages": config.can_pin_messages == "true",
        }
        await self._make_request("POST", "promoteChatMember", creds, payload)
        return {
            "type": "telegram",
            "operation": "promote_user_to_admin",
            "chat_id": chat_id,
            "user_id": config.user_id,
            "timestamp": time.time(),
            "status": "promoted",
        }

    async def _handle_set_chat_title(
        self, creds, config: TelegramSetChatTitleConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        await self._make_request(
            "POST", "setChatTitle", creds, {"chat_id": chat_id, "title": config.title}
        )
        return {
            "type": "telegram",
            "operation": "set_chat_title",
            "chat_id": chat_id,
            "title": config.title,
            "timestamp": time.time(),
            "status": "updated",
        }

    async def _handle_set_chat_description(
        self, creds, config: TelegramSetChatDescriptionConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        await self._make_request(
            "POST",
            "setChatDescription",
            creds,
            {"chat_id": chat_id, "description": config.description},
        )
        return {
            "type": "telegram",
            "operation": "set_chat_description",
            "chat_id": chat_id,
            "timestamp": time.time(),
            "status": "updated",
        }

    async def _handle_create_invite_link(
        self, creds, config: TelegramCreateInviteLinkConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "creates_join_request": config.creates_join_request == "true",
        }
        if config.name:
            payload["name"] = config.name
        if config.expire_date:
            payload["expire_date"] = int(config.expire_date)
        if config.member_limit:
            payload["member_limit"] = int(config.member_limit)
        result = await self._make_request(
            "POST", "createChatInviteLink", creds, payload
        )
        return {
            "type": "telegram",
            "operation": "create_chat_invite_link",
            "chat_id": chat_id,
            "invite_link": result.get("invite_link"),
            "name": result.get("name"),
            "expire_date": result.get("expire_date"),
            "member_limit": result.get("member_limit"),
            "timestamp": time.time(),
            "status": "created",
        }

    async def _handle_revoke_invite_link(
        self, creds, config: TelegramRevokeInviteLinkConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        result = await self._make_request(
            "POST",
            "revokeChatInviteLink",
            creds,
            {"chat_id": chat_id, "invite_link": config.invite_link},
        )
        return {
            "type": "telegram",
            "operation": "revoke_chat_invite_link",
            "chat_id": chat_id,
            "invite_link": result.get("invite_link"),
            "timestamp": time.time(),
            "status": "revoked",
        }

    # ============================================================================
    # Inline/callback handlers
    # ============================================================================

    async def _handle_answer_callback_query(
        self, creds, config: TelegramAnswerCallbackQueryConfig
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "callback_query_id": config.callback_query_id,
            "show_alert": config.show_alert == "true",
        }
        if config.text:
            payload["text"] = config.text
        if config.url:
            payload["url"] = config.url
        if config.cache_time:
            payload["cache_time"] = int(config.cache_time)
        await self._make_request("POST", "answerCallbackQuery", creds, payload)
        return {
            "type": "telegram",
            "operation": "answer_inline_button_callback",
            "callback_query_id": config.callback_query_id,
            "timestamp": time.time(),
            "status": "answered",
        }

    async def _handle_answer_inline_query(
        self, creds, config: TelegramAnswerInlineQueryConfig
    ) -> Dict[str, Any]:
        try:
            results = json.loads(config.results)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid results JSON: {e}")
        payload: Dict[str, Any] = {
            "inline_query_id": config.inline_query_id,
            "results": results,
            "cache_time": int(config.cache_time) if config.cache_time else 300,
            "is_personal": config.is_personal == "true",
        }
        if config.next_offset:
            payload["next_offset"] = config.next_offset
        await self._make_request("POST", "answerInlineQuery", creds, payload)
        return {
            "type": "telegram",
            "operation": "answer_inline_search_results",
            "inline_query_id": config.inline_query_id,
            "result_count": len(results),
            "timestamp": time.time(),
            "status": "answered",
        }

    async def _handle_set_message_reaction(
        self, creds, config: TelegramSetMessageReactionConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(config.message_id),
            "is_big": config.is_big == "true",
        }
        if config.reaction:
            payload["reaction"] = [{"type": "emoji", "emoji": config.reaction}]
        else:
            payload["reaction"] = []
        await self._make_request("POST", "setMessageReaction", creds, payload)
        return {
            "type": "telegram",
            "operation": "set_message_emoji_reaction",
            "chat_id": chat_id,
            "message_id": config.message_id,
            "reaction": config.reaction,
            "timestamp": time.time(),
            "status": "set",
        }

    # ============================================================================
    # Bot info handlers
    # ============================================================================

    async def _handle_get_me(self, creds) -> Dict[str, Any]:
        result = await self._make_request("GET", "getMe", creds)
        return {
            "type": "telegram",
            "operation": "get_bot_information",
            "bot": result,
            "id": result.get("id"),
            "username": result.get("username"),
            "first_name": result.get("first_name"),
            "timestamp": time.time(),
            "status": "success",
        }

    async def _handle_get_file(
        self, creds, config: TelegramGetFileConfig
    ) -> Dict[str, Any]:
        result = await self._make_request(
            "POST", "getFile", creds, {"file_id": config.file_id}
        )
        file_path = result.get("file_path", "")
        download_url = (
            f"https://api.telegram.org/file/bot{creds.token}/{file_path}"
            if file_path
            else None
        )
        return {
            "type": "telegram",
            "operation": "get_file_download_info",
            "file_id": config.file_id,
            "file_path": file_path,
            "file_size": result.get("file_size"),
            "download_url": download_url,
            "timestamp": time.time(),
            "status": "success",
        }

    # ============================================================================
    # Payment handlers
    # ============================================================================

    async def _handle_send_invoice(
        self, creds, config: TelegramSendInvoiceConfig
    ) -> Dict[str, Any]:
        chat_id = self._chat_id_str(config.chatId)
        try:
            prices = json.loads(config.prices)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid prices JSON: {e}")
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "title": config.title,
            "description": config.description,
            "payload": config.payload,
            "currency": config.currency,
            "prices": prices,
        }
        if config.provider_token:
            payload["provider_token"] = config.provider_token
        if config.photo_url:
            payload["photo_url"] = config.photo_url
        if config.start_parameter:
            payload["start_parameter"] = config.start_parameter
        result = await self._make_request("POST", "sendInvoice", creds, payload)
        return {
            "type": "telegram",
            "operation": "send_payment_invoice",
            "chat_id": chat_id,
            "message_id": result.get("message_id"),
            "timestamp": time.time(),
            "status": "sent",
        }

    async def _handle_answer_pre_checkout_query(
        self, creds, config: TelegramAnswerPreCheckoutQueryConfig
    ) -> Dict[str, Any]:
        ok = config.ok == "true"
        payload: Dict[str, Any] = {
            "pre_checkout_query_id": config.pre_checkout_query_id,
            "ok": ok,
        }
        if not ok and config.error_message:
            payload["error_message"] = config.error_message
        await self._make_request("POST", "answerPreCheckoutQuery", creds, payload)
        return {
            "type": "telegram",
            "operation": "answer_payment_pre_checkout",
            "pre_checkout_query_id": config.pre_checkout_query_id,
            "approved": ok,
            "timestamp": time.time(),
            "status": "answered",
        }
