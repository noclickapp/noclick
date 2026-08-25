"""
Mock tests for Telegram Bot API node.

Tests all 48 operations using mocked HTTP responses to verify node logic
without hitting the actual Telegram API.

Run: pytest backend/nodes/tests/test_telegram_node_mock.py -v
"""

import json
import asyncio
import socket
import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from utils.ssrf import SSRFError

from nodes.telegram_node import (
    TelegramNode,
    TelegramNodeConfig,
    TelegramBotTokenCredential,
    # Original operations
    TelegramChatIdConfig,
    TelegramChannelConfig,
    TelegramSendDocumentConfig,
    TelegramWebhookConfig,
    TelegramReceiveConfig,
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
)


# ============================================================================
# Fixtures & Helpers
# ============================================================================


@pytest.fixture
def credentials():
    return TelegramBotTokenCredential(token="123456789:ABCdefGHIjklMNOpqrsTUVwxyz")


def create_node(config, creds=None, trigger_payload=None):
    """Create a TelegramNode with the given config.

    trigger_payload: dict to inject as _triggerPayload in node_data, simulating
    how the execution engine provides webhook data to setup_channel nodes.
    """
    if creds is None:
        creds = TelegramBotTokenCredential(token="123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
    node_config = TelegramNodeConfig(config=config, credentials=creds)
    node_data = (
        {"config": {"_triggerPayload": trigger_payload}}
        if trigger_payload is not None
        else {}
    )
    return TelegramNode(
        node_id="test-node",
        node_type="automation-telegram",
        node_data=node_data,
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow-id",
    )


class MockResponse:
    """Mock httpx response for Telegram API (ok=true format)."""

    def __init__(self, result, status_code=200):
        self._result = result
        self.status_code = status_code
        self.text = json.dumps(
            {"ok": True, "result": result} if status_code == 200 else result
        )

    def json(self):
        if self.status_code == 200:
            return {"ok": True, "result": self._result}
        return self._result


class MockErrorResponse:
    """Mock httpx error response."""

    def __init__(self, description="Bad Request", error_code=400):
        self.status_code = error_code
        self.text = description

    def json(self):
        return {"ok": False, "description": self.text, "error_code": self.status_code}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/webhook",
        "http://169.254.169.254/latest/meta-data",
    ],
)
async def test_webhook_delivery_blocks_private_literals(url, credentials):
    node = create_node(TelegramWebhookConfig(webhookUrl=url), credentials)

    with pytest.raises(SSRFError, match="non-public address"):
        await node.execute({})


@pytest.mark.asyncio
async def test_webhook_delivery_blocks_hostname_resolving_private(
    monkeypatch, credentials
):
    loop = asyncio.get_running_loop()

    async def private_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", private_dns)
    node = create_node(
        TelegramWebhookConfig(webhookUrl="https://private.example/webhook"),
        credentials,
    )

    with pytest.raises(SSRFError, match="non-public address"):
        await node.execute({})


def mock_ok(result):
    """Return a MockResponse with the given result."""
    return MockResponse(result)


# ============================================================================
# Original Operations — backward compatibility
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_to_chat_id(mock_client_class, credentials):
    """Original send_to_chat_id still works."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.post.return_value = MockResponse(
        {"message_id": 10, "chat": {"id": 123}}
    )

    node = create_node(TelegramChatIdConfig(chatId="123", message="Hello"), credentials)
    result = await node.execute({})

    assert result["status"] == "sent"
    assert result["method"] == "chatId"
    assert result["message_id"] == 10
    assert result["chat_id"] == "123"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_to_channel(mock_client_class, credentials):
    """Original send_to_channel normalizes @ prefix."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.post.return_value = MockResponse({"message_id": 11})

    node = create_node(
        TelegramChannelConfig(username="mychannel", message="Hi"), credentials
    )
    result = await node.execute({})

    assert result["status"] == "sent"
    assert result["method"] == "channel"
    assert result["chat_id"] == "@mychannel"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_document(mock_client_class, credentials):
    """Original send_document returns file metadata."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.post.return_value = MockResponse(
        {
            "message_id": 12,
            "document": {
                "file_id": "file123",
                "file_name": "test.pdf",
                "file_size": 1024,
            },
        }
    )

    node = create_node(
        TelegramSendDocumentConfig(
            chatId="123", document_url="https://example.com/test.pdf", caption="A doc"
        ),
        credentials,
    )
    result = await node.execute({})

    assert result["status"] == "sent"
    assert result["method"] == "send_document"
    assert result["file_id"] == "file123"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_receive_mode_parses_message(mock_client_class, credentials):
    """receive mode extracts text, chat_id and from_user from message update."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.post.return_value = MockResponse({"ok": True})  # for re-registration

    node = create_node(
        TelegramReceiveConfig(
            webhook_id="wh1",
            webhook_url="https://example.com/wh",
            telegram_registered=True,
        ),
        credentials,
    )

    inputs = {
        "update_id": 999,
        "message": {
            "message_id": 42,
            "chat": {"id": 777},
            "from": {"id": 111, "first_name": "Alice"},
            "text": "Hello bot",
        },
    }
    result = await node.execute(inputs)

    assert result["update_type"] == "message"
    assert result["chat_id"] == 777
    assert result["text"] == "Hello bot"
    assert result["from_user"]["first_name"] == "Alice"
    assert result["status"] == "triggered"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_receive_mode_parses_callback_query(mock_client_class, credentials):
    """receive mode extracts data from callback_query update."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.post.return_value = MockResponse({"ok": True})

    node = create_node(
        TelegramReceiveConfig(
            webhook_id="wh1",
            webhook_url="https://example.com/wh",
            telegram_registered=True,
        ),
        credentials,
    )
    inputs = {
        "update_id": 1000,
        "callback_query": {
            "id": "cbq1",
            "data": "button_pressed",
            "from": {"id": 222, "first_name": "Bob"},
            "message": {"message_id": 50, "chat": {"id": 888}},
        },
    }
    result = await node.execute(inputs)
    assert result["update_type"] == "callback_query"
    assert result["text"] == "button_pressed"
    assert result["chat_id"] == 888


# ============================================================================
# Rich Media Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_photo_success(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 20})

    node = create_node(
        TelegramSendPhotoConfig(
            chatId="123", photo="https://example.com/photo.jpg", caption="Nice photo"
        )
    )
    result = await node.execute({})

    assert result["status"] == "sent"
    assert result["operation"] == "send_photo_image"
    assert result["message_id"] == 20
    call_args = mock_client.request.call_args
    assert "sendPhoto" in call_args[0][1]
    body = call_args[1]["json"]
    assert body["photo"] == "https://example.com/photo.jpg"
    assert body["caption"] == "Nice photo"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_video_success(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 21})

    node = create_node(
        TelegramSendVideoConfig(
            chatId="123",
            video="https://example.com/video.mp4",
            duration="30",
            width="1920",
            height="1080",
        )
    )
    result = await node.execute({})

    assert result["status"] == "sent"
    assert result["operation"] == "send_video_file"
    body = mock_client.request.call_args[1]["json"]
    assert body["duration"] == 30
    assert body["width"] == 1920


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_audio_with_metadata(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 22})

    node = create_node(
        TelegramSendAudioConfig(
            chatId="123",
            audio="file_id_abc",
            performer="Artist",
            title="Song",
            duration="180",
        )
    )
    result = await node.execute({})

    assert result["status"] == "sent"
    assert result["operation"] == "send_audio_file"
    body = mock_client.request.call_args[1]["json"]
    assert body["performer"] == "Artist"
    assert body["title"] == "Song"
    assert body["duration"] == 180


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_voice(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 23})

    node = create_node(TelegramSendVoiceConfig(chatId="123", voice="voice_file_id"))
    result = await node.execute({})
    assert result["operation"] == "send_voice_note"
    assert result["status"] == "sent"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_animation(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 24})

    node = create_node(
        TelegramSendAnimationConfig(
            chatId="123", animation="https://example.com/anim.gif"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "send_animated_video"
    assert result["status"] == "sent"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_video_note(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 25})

    node = create_node(
        TelegramSendVideoNoteConfig(
            chatId="123", video_note="video_note_file_id", length="240"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "send_circular_video"
    body = mock_client.request.call_args[1]["json"]
    assert body["length"] == 240


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_sticker(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 26})

    node = create_node(
        TelegramSendStickerConfig(chatId="123", sticker="sticker_file_id", emoji="😀")
    )
    result = await node.execute({})
    assert result["operation"] == "send_sticker"
    body = mock_client.request.call_args[1]["json"]
    assert body["emoji"] == "😀"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_media_group(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = MockResponse(
        [{"message_id": 30}, {"message_id": 31}]
    )

    media_json = json.dumps(
        [
            {"type": "photo", "media": "https://example.com/1.jpg"},
            {"type": "photo", "media": "https://example.com/2.jpg"},
        ]
    )
    node = create_node(TelegramSendMediaGroupConfig(chatId="123", media=media_json))
    result = await node.execute({})
    assert result["operation"] == "send_photo_video_album"
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_send_media_group_invalid_json(credentials):
    """send_media_group raises ValueError on invalid JSON."""
    node = create_node(TelegramSendMediaGroupConfig(chatId="123", media="not json"))
    with pytest.raises(ValueError, match="Invalid media JSON"):
        await node.execute({})


@pytest.mark.asyncio
async def test_send_media_group_too_few_items(credentials):
    """send_media_group raises ValueError when fewer than 2 items."""
    node = create_node(
        TelegramSendMediaGroupConfig(
            chatId="123", media='[{"type":"photo","media":"url"}]'
        )
    )
    with pytest.raises(ValueError, match="2–10 items"):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_contact(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 27})

    node = create_node(
        TelegramSendContactConfig(
            chatId="123",
            phone_number="+12025550100",
            first_name="Alice",
            last_name="Smith",
        )
    )
    result = await node.execute({})
    assert result["operation"] == "send_contact_information"
    body = mock_client.request.call_args[1]["json"]
    assert body["phone_number"] == "+12025550100"
    assert body["last_name"] == "Smith"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_location(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 28})

    node = create_node(
        TelegramSendLocationConfig(
            chatId="123",
            latitude="37.7749",
            longitude="-122.4194",
            horizontal_accuracy="50",
        )
    )
    result = await node.execute({})
    assert result["operation"] == "send_location_pin"
    body = mock_client.request.call_args[1]["json"]
    assert body["latitude"] == 37.7749
    assert body["horizontal_accuracy"] == 50.0


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_venue(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 29})

    node = create_node(
        TelegramSendVenueConfig(
            chatId="123",
            latitude="37.0",
            longitude="-122.0",
            title="Office",
            address="123 Main St",
        )
    )
    result = await node.execute({})
    assert result["operation"] == "send_venue_location"
    body = mock_client.request.call_args[1]["json"]
    assert body["title"] == "Office"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_dice(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {"message_id": 32, "dice": {"emoji": "🎲", "value": 4}}
    )

    node = create_node(TelegramSendDiceConfig(chatId="123", emoji="🎲"))
    result = await node.execute({})
    assert result["operation"] == "send_dice_emoji"
    assert result["emoji"] == "🎲"
    assert result["value"] == 4


# ============================================================================
# Message Management Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_edit_message_text(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 42, "text": "New text"})

    node = create_node(
        TelegramEditMessageTextConfig(chatId="123", message_id="42", text="New text")
    )
    result = await node.execute({})
    assert result["operation"] == "edit_message_text"
    assert result["status"] == "edited"
    body = mock_client.request.call_args[1]["json"]
    assert body["text"] == "New text"
    assert body["message_id"] == 42


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_edit_message_caption(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 43})

    node = create_node(
        TelegramEditMessageCaptionConfig(
            chatId="123", message_id="43", caption="New caption"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "edit_message_caption"
    assert result["status"] == "edited"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_delete_message(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(TelegramDeleteMessageConfig(chatId="123", message_id="44"))
    result = await node.execute({})
    assert result["operation"] == "delete_message"
    assert result["status"] == "deleted"
    assert result["message_id"] == "44"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_delete_messages(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramDeleteMessagesConfig(chatId="123", message_ids="44,45,46")
    )
    result = await node.execute({})
    assert result["operation"] == "delete_multiple_messages"
    assert result["count"] == 3
    body = mock_client.request.call_args[1]["json"]
    assert body["message_ids"] == [44, 45, 46]


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_pin_message(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramPinMessageConfig(
            chatId="123", message_id="42", disable_notification="true"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "pin_message_in_chat"
    assert result["status"] == "pinned"
    body = mock_client.request.call_args[1]["json"]
    assert body["disable_notification"] is True


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_unpin_message_specific(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(TelegramUnpinMessageConfig(chatId="123", message_id="42"))
    result = await node.execute({})
    assert result["operation"] == "unpin_chat_message"
    assert result["status"] == "unpinned"
    assert "unpinChatMessage" in mock_client.request.call_args[0][1]


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_unpin_message_all(mock_client_class, credentials):
    """Empty message_id unpins all."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(TelegramUnpinMessageConfig(chatId="123", message_id=""))
    result = await node.execute({})
    assert result["status"] == "all_unpinned"
    assert "unpinAllChatMessages" in mock_client.request.call_args[0][1]


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_forward_message(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 55})

    node = create_node(
        TelegramForwardMessageConfig(chatId="456", from_chat_id="123", message_id="42")
    )
    result = await node.execute({})
    assert result["operation"] == "forward_message_to_chat"
    assert result["status"] == "forwarded"
    assert result["message_id"] == 55


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_copy_message(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 56})

    node = create_node(
        TelegramCopyMessageConfig(
            chatId="456", from_chat_id="123", message_id="42", caption="New caption"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "copy_message_to_chat"
    assert result["status"] == "copied"
    body = mock_client.request.call_args[1]["json"]
    assert body["caption"] == "New caption"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_chat_action(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(TelegramSendChatActionConfig(chatId="123", action="typing"))
    result = await node.execute({})
    assert result["operation"] == "send_chat_typing_indicator"
    assert result["action"] == "typing"
    assert result["status"] == "sent"


# ============================================================================
# Poll Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_poll(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {"message_id": 60, "poll": {"id": "poll1"}}
    )

    options = json.dumps(["Option A", "Option B", "Option C"])
    node = create_node(
        TelegramSendPollConfig(chatId="123", question="Best color?", options=options)
    )
    result = await node.execute({})
    assert result["operation"] == "send_poll_or_quiz"
    assert result["status"] == "sent"
    body = mock_client.request.call_args[1]["json"]
    assert body["question"] == "Best color?"
    assert body["options"] == ["Option A", "Option B", "Option C"]


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_poll_quiz_mode(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 61})

    options = json.dumps(["2", "3", "4", "5"])
    node = create_node(
        TelegramSendPollConfig(
            chatId="123",
            question="1+1=?",
            options=options,
            poll_type="quiz",
            correct_option_id="0",
            explanation="One plus one is two",
        )
    )
    result = await node.execute({})
    body = mock_client.request.call_args[1]["json"]
    assert body["type"] == "quiz"
    assert body["correct_option_id"] == 0
    assert body["explanation"] == "One plus one is two"


@pytest.mark.asyncio
async def test_send_poll_invalid_options_json(credentials):
    node = create_node(
        TelegramSendPollConfig(chatId="123", question="Q?", options="not json")
    )
    with pytest.raises(ValueError, match="Invalid options JSON"):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_stop_poll(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {"id": "poll1", "is_closed": True, "total_voter_count": 10}
    )

    node = create_node(TelegramStopPollConfig(chatId="123", message_id="60"))
    result = await node.execute({})
    assert result["operation"] == "stop_active_poll"
    assert result["status"] == "stopped"
    assert result["poll"]["is_closed"] is True


# ============================================================================
# Chat Info Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_chat(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {
            "id": -1001234567890,
            "type": "channel",
            "title": "My Channel",
            "username": "mychannel",
            "member_count": 1500,
        }
    )

    node = create_node(TelegramGetChatConfig(chatId="-1001234567890"))
    result = await node.execute({})
    assert result["operation"] == "get_chat_details"
    assert result["chat"]["title"] == "My Channel"
    assert result["status"] == "success"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_chat_member(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {"status": "administrator", "user": {"id": 111, "first_name": "Alice"}}
    )

    node = create_node(
        TelegramGetChatMemberConfig(chatId="-1001234567890", user_id="111")
    )
    result = await node.execute({})
    assert result["operation"] == "get_chat_member_info"
    assert result["status"] == "administrator"
    assert result["member"]["user"]["first_name"] == "Alice"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_chat_member_count(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(1500)

    node = create_node(TelegramGetChatMemberCountConfig(chatId="-1001234567890"))
    result = await node.execute({})
    assert result["operation"] == "get_chat_member_count"
    assert result["count"] == 1500


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_chat_administrators(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = MockResponse(
        [
            {"status": "creator", "user": {"id": 100, "first_name": "Owner"}},
            {"status": "administrator", "user": {"id": 200, "first_name": "Admin"}},
        ]
    )

    node = create_node(TelegramGetChatAdministratorsConfig(chatId="-1001234567890"))
    result = await node.execute({})
    assert result["operation"] == "get_chat_admin_list"
    assert result["count"] == 2
    assert result["administrators"][0]["status"] == "creator"


# ============================================================================
# Group/Channel Management Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_ban_chat_member(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramBanChatMemberConfig(
            chatId="-1001234567890", user_id="111", revoke_messages="true"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "ban_user_from_chat"
    assert result["status"] == "banned"
    body = mock_client.request.call_args[1]["json"]
    assert body["revoke_messages"] is True


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_ban_with_until_date(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramBanChatMemberConfig(
            chatId="123", user_id="111", until_date="9999999999"
        )
    )
    await node.execute({})
    body = mock_client.request.call_args[1]["json"]
    assert body["until_date"] == 9999999999


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_unban_chat_member(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(TelegramUnbanChatMemberConfig(chatId="123", user_id="111"))
    result = await node.execute({})
    assert result["operation"] == "unban_user_from_chat"
    assert result["status"] == "unbanned"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_restrict_chat_member(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    perms = json.dumps({"can_send_messages": False, "can_send_polls": False})
    node = create_node(
        TelegramRestrictChatMemberConfig(chatId="123", user_id="111", permissions=perms)
    )
    result = await node.execute({})
    assert result["operation"] == "restrict_user_permissions"
    assert result["status"] == "restricted"
    body = mock_client.request.call_args[1]["json"]
    assert body["permissions"]["can_send_messages"] is False


@pytest.mark.asyncio
async def test_restrict_invalid_permissions_json(credentials):
    node = create_node(
        TelegramRestrictChatMemberConfig(
            chatId="123", user_id="111", permissions="bad json"
        )
    )
    with pytest.raises(ValueError, match="Invalid permissions JSON"):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_promote_chat_member(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramPromoteChatMemberConfig(
            chatId="123",
            user_id="111",
            can_post_messages="true",
            can_delete_messages="true",
        )
    )
    result = await node.execute({})
    assert result["operation"] == "promote_user_to_admin"
    assert result["status"] == "promoted"
    body = mock_client.request.call_args[1]["json"]
    assert body["can_post_messages"] is True
    assert body["can_delete_messages"] is True
    assert body["can_pin_messages"] is False


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_set_chat_title(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(TelegramSetChatTitleConfig(chatId="123", title="New Title"))
    result = await node.execute({})
    assert result["operation"] == "set_chat_title"
    assert result["title"] == "New Title"
    assert result["status"] == "updated"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_set_chat_description(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramSetChatDescriptionConfig(chatId="123", description="A great channel")
    )
    result = await node.execute({})
    assert result["operation"] == "set_chat_description"
    assert result["status"] == "updated"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_create_invite_link(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {
            "invite_link": "https://t.me/+abc123",
            "name": "My Invite",
            "expire_date": 1999999999,
            "member_limit": 100,
        }
    )

    node = create_node(
        TelegramCreateInviteLinkConfig(
            chatId="123", name="My Invite", member_limit="100"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "create_chat_invite_link"
    assert result["invite_link"] == "https://t.me/+abc123"
    assert result["status"] == "created"
    body = mock_client.request.call_args[1]["json"]
    assert body["member_limit"] == 100


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_revoke_invite_link(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {"invite_link": "https://t.me/+abc123", "is_revoked": True}
    )

    node = create_node(
        TelegramRevokeInviteLinkConfig(chatId="123", invite_link="https://t.me/+abc123")
    )
    result = await node.execute({})
    assert result["operation"] == "revoke_chat_invite_link"
    assert result["status"] == "revoked"


# ============================================================================
# Inline / Callback Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_answer_callback_query(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramAnswerCallbackQueryConfig(
            callback_query_id="cbq123", text="Done!", show_alert="true"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "answer_inline_button_callback"
    assert result["status"] == "answered"
    body = mock_client.request.call_args[1]["json"]
    assert body["text"] == "Done!"
    assert body["show_alert"] is True


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_answer_inline_query(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    results_json = json.dumps(
        [
            {
                "type": "article",
                "id": "1",
                "title": "Result",
                "input_message_content": {"message_text": "Hi"},
            }
        ]
    )
    node = create_node(
        TelegramAnswerInlineQueryConfig(inline_query_id="iq123", results=results_json)
    )
    result = await node.execute({})
    assert result["operation"] == "answer_inline_search_results"
    assert result["result_count"] == 1
    assert result["status"] == "answered"


@pytest.mark.asyncio
async def test_answer_inline_query_invalid_json(credentials):
    node = create_node(
        TelegramAnswerInlineQueryConfig(inline_query_id="iq123", results="bad json")
    )
    with pytest.raises(ValueError, match="Invalid results JSON"):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_set_message_reaction_with_emoji(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramSetMessageReactionConfig(
            chatId="123", message_id="42", reaction="👍", is_big="true"
        )
    )
    result = await node.execute({})
    assert result["operation"] == "set_message_emoji_reaction"
    assert result["reaction"] == "👍"
    assert result["status"] == "set"
    body = mock_client.request.call_args[1]["json"]
    assert body["reaction"] == [{"type": "emoji", "emoji": "👍"}]
    assert body["is_big"] is True


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_set_message_reaction_remove(mock_client_class, credentials):
    """Empty reaction removes existing reaction."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramSetMessageReactionConfig(chatId="123", message_id="42", reaction="")
    )
    await node.execute({})
    body = mock_client.request.call_args[1]["json"]
    assert body["reaction"] == []


# ============================================================================
# Bot Info Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_me(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {
            "id": 123456789,
            "is_bot": True,
            "first_name": "MyBot",
            "username": "mybot",
            "can_join_groups": True,
        }
    )

    node = create_node(TelegramGetMeConfig())
    result = await node.execute({})
    assert result["operation"] == "get_bot_information"
    assert result["username"] == "mybot"
    assert result["bot"]["is_bot"] is True
    assert result["status"] == "success"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_get_file(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(
        {
            "file_id": "BQACAgI123",
            "file_path": "documents/file_123.pdf",
            "file_size": 204800,
        }
    )

    node = create_node(TelegramGetFileConfig(file_id="BQACAgI123"))
    result = await node.execute({})
    assert result["operation"] == "get_file_download_info"
    assert result["file_path"] == "documents/file_123.pdf"
    assert result["file_size"] == 204800
    assert "download_url" in result
    assert (
        "BQACAgI123" in result["download_url"]
        or "documents/file_123.pdf" in result["download_url"]
    )


# ============================================================================
# Payment Operations
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_send_invoice(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok({"message_id": 70})

    prices_json = json.dumps([{"label": "Subscription", "amount": 999}])
    node = create_node(
        TelegramSendInvoiceConfig(
            chatId="123",
            title="Premium",
            description="Monthly premium",
            payload="sub_monthly",
            currency="USD",
            prices=prices_json,
        )
    )
    result = await node.execute({})
    assert result["operation"] == "send_payment_invoice"
    assert result["message_id"] == 70
    assert result["status"] == "sent"
    body = mock_client.request.call_args[1]["json"]
    assert body["currency"] == "USD"
    assert body["prices"][0]["amount"] == 999


@pytest.mark.asyncio
async def test_send_invoice_invalid_prices_json(credentials):
    node = create_node(
        TelegramSendInvoiceConfig(
            chatId="123",
            title="P",
            description="D",
            payload="p",
            currency="USD",
            prices="bad json",
        )
    )
    with pytest.raises(ValueError, match="Invalid prices JSON"):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_answer_pre_checkout_query_approved(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramAnswerPreCheckoutQueryConfig(pre_checkout_query_id="pcq123", ok="true")
    )
    result = await node.execute({})
    assert result["operation"] == "answer_payment_pre_checkout"
    assert result["approved"] is True
    assert result["status"] == "answered"
    body = mock_client.request.call_args[1]["json"]
    assert body["ok"] is True


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_answer_pre_checkout_query_rejected(mock_client_class, credentials):
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = mock_ok(True)

    node = create_node(
        TelegramAnswerPreCheckoutQueryConfig(
            pre_checkout_query_id="pcq123", ok="false", error_message="Out of stock"
        )
    )
    result = await node.execute({})
    assert result["approved"] is False
    body = mock_client.request.call_args[1]["json"]
    assert body["ok"] is False
    assert body["error_message"] == "Out of stock"


# ============================================================================
# Setup Channel Flow
# ============================================================================


@pytest.mark.asyncio
@patch("nodes.telegram_node._get_setup_result", new_callable=AsyncMock)
@patch("nodes.telegram_node._store_setup_result", new_callable=AsyncMock)
async def test_setup_channel_detects_admin_promotion(mock_store, mock_get, credentials):
    """setup_channel detects my_chat_member admin promotion and stores channel_id."""
    mock_get.return_value = None

    my_chat_member_payload = {
        "my_chat_member": {
            "chat": {"id": -1001234567890, "title": "My Channel", "type": "channel"},
            "from": {"id": 999, "first_name": "Owner"},
            "new_chat_member": {
                "status": "administrator",
                "user": {"id": 123456789, "is_bot": True},
            },
        }
    }

    node = create_node(
        TelegramSetupChannelConfig(
            webhook_id="wh1",
            webhook_url="https://example.com/wh",
            telegram_registered=True,
            setup_token="testtoken123",
        ),
        credentials,
        trigger_payload=my_chat_member_payload,
    )

    # Mock _make_request so the confirmation DM doesn't fail
    with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"message_id": 1}
        result = await node.execute({})

    assert result["operation"] == "setup_telegram_channel_guided"
    assert result["status"] == "complete"
    assert result["channel_id"] == "-1001234567890"
    assert result["channel_title"] == "My Channel"
    mock_store.assert_called_once_with(
        "test-workflow-id", "test-node", "-1001234567890", "My Channel"
    )


@pytest.mark.asyncio
@patch("nodes.telegram_node._get_setup_result", new_callable=AsyncMock)
async def test_setup_channel_returns_pending_when_not_resolved(mock_get, credentials):
    """setup_channel returns pending status when channel hasn't been connected yet."""
    mock_get.return_value = None

    node = create_node(
        TelegramSetupChannelConfig(
            setup_link="https://t.me/mybot?start=setup_abc123",
            setup_token="abc123",
            setup_status="pending",
        ),
        credentials,
    )

    result = await node.execute({})

    assert result["operation"] == "setup_telegram_channel_guided"
    assert result["status"] == "pending"
    assert result["setup_link"] == "https://t.me/mybot?start=setup_abc123"


@pytest.mark.asyncio
@patch("nodes.telegram_node._get_setup_result", new_callable=AsyncMock)
async def test_setup_channel_returns_complete_when_already_resolved(
    mock_get, credentials
):
    """setup_channel returns complete immediately if channel was already stored in Redis."""
    mock_get.return_value = {
        "channel_id": "-1009876543210",
        "channel_title": "Already Connected",
    }

    node = create_node(TelegramSetupChannelConfig(), credentials)
    result = await node.execute({})

    assert result["status"] == "complete"
    assert result["channel_id"] == "-1009876543210"


@pytest.mark.asyncio
@patch("nodes.telegram_node._get_setup_result", new_callable=AsyncMock)
@patch("nodes.telegram_node._get_setup_token_data", new_callable=AsyncMock)
async def test_setup_channel_handles_start_command(
    mock_token_data, mock_get, credentials
):
    """setup_channel sends instructions when user sends /start setup_* command."""
    mock_get.return_value = None
    mock_token_data.return_value = {
        "workflow_id": "test-workflow-id",
        "node_id": "test-node",
    }

    start_payload = {
        "message": {
            "text": "/start setup_validtoken",
            "from": {"id": 999, "first_name": "User"},
            "chat": {"id": 999},
        }
    }

    node = create_node(
        TelegramSetupChannelConfig(
            webhook_id="wh1",
            webhook_url="https://example.com/wh",
            telegram_registered=True,
            setup_token="validtoken",
        ),
        credentials,
        trigger_payload=start_payload,
    )

    with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"message_id": 1}
        result = await node.execute({})
        # Should have attempted to DM the user
        mock_req.assert_called_once()
        call_body = mock_req.call_args[0][3]
        assert "admin" in call_body["text"].lower()

    assert result["status"] == "pending"


# ============================================================================
# Error Handling
# ============================================================================


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_api_error_raises_value_error(mock_client_class, credentials):
    """Telegram API errors raise ValueError with error details."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = MockErrorResponse("chat not found", 400)

    node = create_node(
        TelegramSendPhotoConfig(chatId="99999", photo="https://example.com/photo.jpg")
    )
    with pytest.raises(ValueError, match="Telegram API error.*400.*chat not found"):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_forbidden_error(mock_client_class, credentials):
    """403 Forbidden (bot not admin) raises ValueError."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.return_value = MockErrorResponse(
        "Forbidden: bot is not a member of the channel chat", 403
    )

    node = create_node(TelegramGetChatConfig(chatId="-1001234567890"))
    with pytest.raises(ValueError, match="Telegram API error.*403"):
        await node.execute({})


@pytest.mark.asyncio
async def test_missing_credentials_raises_value_error():
    """Node raises ValueError when credentials are missing."""
    node_config = TelegramNodeConfig(
        config=TelegramSendPhotoConfig(chatId="123", photo="url"), credentials=None
    )
    node = TelegramNode(
        node_id="n1",
        node_type="automation-telegram",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="wf1",
    )
    with pytest.raises(ValueError, match="Bot token is required"):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_network_timeout_raises(mock_client_class, credentials):
    """Network timeout propagates as httpx.TimeoutException."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_client.request.side_effect = httpx.TimeoutException("timeout")

    node = create_node(TelegramSendPhotoConfig(chatId="123", photo="url"))
    with pytest.raises(httpx.TimeoutException):
        await node.execute({})


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_ok_false_response_raises(mock_client_class, credentials):
    """ok=false in response body raises ValueError even with 200 status."""
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.return_value = {"ok": False, "description": "Something went wrong"}
    mock_client.request.return_value = bad_resp

    node = create_node(TelegramGetMeConfig())
    with pytest.raises(ValueError, match="Telegram API error: Something went wrong"):
        await node.execute({})


# ============================================================================
# Config Validation
# ============================================================================


def test_send_photo_config_requires_photo():
    with pytest.raises(Exception):
        TelegramSendPhotoConfig(chatId="123")  # missing photo


def test_send_contact_requires_phone_and_name():
    with pytest.raises(Exception):
        TelegramSendContactConfig(
            chatId="123", phone_number="+12025550100"
        )  # missing first_name


def test_send_location_requires_coordinates():
    with pytest.raises(Exception):
        TelegramSendLocationConfig(chatId="123", latitude="37.0")  # missing longitude


def test_telegram_node_config_backward_compat_chatid():
    """Legacy configs without 'operation' field are inferred correctly (chatId → send_to_chat_id)."""
    config = TelegramNodeConfig.model_validate(
        {
            "config": {"chatId": "123", "message": "hi"},
            "credentials": {"token": "123:abc"},
        }
    )
    assert config.config.operation == "send_message_to_chat"


def test_telegram_node_config_backward_compat_username():
    """Legacy configs with username field are inferred as send_to_channel."""
    config = TelegramNodeConfig.model_validate(
        {
            "config": {"username": "mychannel", "message": "hi"},
            "credentials": {"token": "123:abc"},
        }
    )
    assert config.config.operation == "send_message_to_channel"


def test_telegram_node_config_backward_compat_receive():
    """Legacy configs with webhook_url are inferred as receive mode."""
    config = TelegramNodeConfig.model_validate(
        {
            "config": {"webhook_url": "https://example.com/wh"},
            "credentials": {"token": "123:abc"},
        }
    )
    assert config.config.operation == "receive_webhook_messages"


def test_send_dice_default_emoji():
    """send_dice defaults to 🎲."""
    config = TelegramSendDiceConfig(chatId="123")
    assert config.emoji == "🎲"


def test_promote_member_defaults():
    """promote_chat_member can_post_messages defaults to true, others to false."""
    config = TelegramPromoteChatMemberConfig(chatId="123", user_id="456")
    assert config.can_post_messages == "true"
    assert config.can_delete_messages == "false"
    assert config.can_pin_messages == "false"


def test_setup_channel_config_has_webhook_flag():
    """TelegramSetupChannelConfig has x-requires-webhook metadata."""
    schema = TelegramSetupChannelConfig.model_config.get("json_schema_extra", {})
    assert schema.get("x-requires-webhook") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
