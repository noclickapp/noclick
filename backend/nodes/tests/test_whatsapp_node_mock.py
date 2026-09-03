"""
Mock tests for WhatsApp Business Cloud API node.

Tests operations that are rate-limited, require special setup, or modify production data.
Uses mocked HTTP responses to test node logic without hitting the actual API.

Run: pytest backend/nodes/tests/test_whatsapp_node_mock.py
"""

import pytest
import asyncio
import os
import time
import threading
from unittest.mock import AsyncMock, patch, MagicMock
import json

from nodes.whatsapp_node import (
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppAccessTokenCredential,
    WhatsAppQRCredential,
    # All config types
    WhatsAppSendTextConfig,
    WhatsAppSendTemplateConfig,
    WhatsAppSendImageConfig,
    WhatsAppUploadMediaConfig,
    WhatsAppDownloadMediaConfig,
    WhatsAppGetBusinessProfileConfig,
    WhatsAppUpdateBusinessProfileConfig,
    WhatsAppRegisterPhoneConfig,
    WhatsAppRequestCodeConfig,
    WhatsAppListTemplatesConfig,
    WhatsAppCreateTemplateConfig,
    WhatsAppDeleteTemplateConfig,
    WhatsAppSendCatalogConfig,
    WhatsAppSendProductConfig,
    WhatsAppGetAccountInfoConfig,
    WhatsAppListPhoneNumbersConfig,
    WhatsAppReceiveMessageConfig,
    WhatsAppReceiveStatusConfig,
    WhatsAppGetChatsConfig,
    WhatsAppGetChatMessagesConfig,
    WhatsAppListContactsConfig,
    WhatsAppEditMessageConfig,
    WhatsAppMarkChatReadConfig,
    WhatsAppSendReactionConfig,
)


@pytest.fixture
def mock_credentials():
    """Create mock credentials for testing"""
    return WhatsAppAccessTokenCredential(
        access_token="test_token_12345",
        phone_number_id="1234567890123456",
        business_account_id="9876543210",
    )


@pytest.fixture
def test_phone():
    """Test phone number in E.164 format"""
    return "+12025550100"


def create_test_node(config, credentials):
    """Helper to create node with config"""
    node_config = WhatsAppNodeConfig(config=config, credentials=credentials)
    return WhatsAppNode(
        node_id="test-whatsapp",
        node_type="automation-whatsapp",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


class MockResponse:
    """Mock httpx response"""

    def __init__(self, json_data, status_code=200, text="", content=b"", headers=None):
        self._json_data = json_data
        self.status_code = status_code
        self.text = text or json.dumps(json_data)
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json_data


# ============================================================================
# Messaging Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_send_text_success(mock_credentials, test_phone):
    """Test successful text message sending"""
    config = WhatsAppSendTextConfig(
        to=test_phone, body="Test message", preview_url=False
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "messaging_product": "whatsapp",
            "contacts": [{"input": test_phone, "wa_id": "1234567890"}],
            "messages": [{"id": "wamid.test123"}],
        },
        200,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_text_message"
        assert "timing_ms" in result
        assert "data" in result


@pytest.mark.asyncio
async def test_send_template_success(mock_credentials, test_phone):
    """Test successful template message sending"""
    config = WhatsAppSendTemplateConfig(
        to=test_phone,
        template_name="hello_world",
        language_code="en_US",
        parameters=json.dumps([{"type": "text", "text": "John"}]),
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"messaging_product": "whatsapp", "messages": [{"id": "wamid.template123"}]},
        200,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_template_message"


@pytest.mark.asyncio
async def test_send_image_success(mock_credentials, test_phone):
    """Test successful image message sending"""
    config = WhatsAppSendImageConfig(
        to=test_phone, image_url="https://example.com/image.jpg", caption="Test image"
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"messaging_product": "whatsapp", "messages": [{"id": "wamid.image123"}]}, 200
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_image_message"


# ============================================================================
# Media Management - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_upload_media_success(mock_credentials):
    """Test successful media upload (multipart binary POST to the /media endpoint)."""
    from nodes.core.media_resolver import ResolvedMedia

    config = WhatsAppUploadMediaConfig(
        media_url="https://example.com/media.jpg", media_type="image/jpeg"
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse({"id": "media_id_12345"}, 201)
    resolved = ResolvedMedia(
        data=b"\xff\xd8\xff", mime_type="image/jpeg", filename="media.jpg"
    )

    with patch(
        "nodes.core.media_resolver.resolve_media_input",
        new=AsyncMock(return_value=resolved),
    ), patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upload_media"
        assert result["data"]["id"] == "media_id_12345"

        # The endpoint needs real bytes as a multipart "file" part, not a JSON link.
        _, kwargs = mock_post.call_args
        assert kwargs["files"]["file"][1] == b"\xff\xd8\xff"
        assert kwargs["data"]["messaging_product"] == "whatsapp"
        assert kwargs["data"]["type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_download_media_success(mock_credentials):
    """Downloaded media bytes resolve to a stored {url, ...} file reference."""
    config = WhatsAppDownloadMediaConfig(
        media_url="https://lookaside.fbsbx.com/media/abc"
    )
    node = create_test_node(config, mock_credentials)
    node.user_id = "test-user"  # resolver needs user_id + workflow_id for R2 storage

    media_bytes = b"\xff\xd8\xff\xe0binary-jpeg-bytes"
    mock_response = MockResponse(
        {},
        200,
        content=media_bytes,
        headers={"content-type": "image/jpeg"},
    )

    stored_ref = {
        "download_url": "https://cdn.example.com/resource/whatsapp_media.jpg",
        "mime_type": "image/jpeg",
        "name": "whatsapp_media.jpg",
        "size_bytes": len(media_bytes),
    }

    with patch(
        "httpx.AsyncClient.get", new_callable=AsyncMock
    ) as mock_get, patch(
        "nodes.core.binary_output.create_resource_from_bytes",
        new=AsyncMock(return_value=stored_ref),
    ) as mock_store:
        mock_get.return_value = mock_response

        result = await node.run({})

        assert result["status"] == "success"
        assert result["action"] == "download_media"

        media = result["data"]["media"]
        assert media["url"] == "https://cdn.example.com/resource/whatsapp_media.jpg"
        assert media["mime_type"] == "image/jpeg"
        assert media["name"] == "whatsapp_media.jpg"
        assert media["size_bytes"] == len(media_bytes)
        # No leftover inline base64 / encoding sibling fields.
        assert "binary_data_base64" not in media
        assert "encoding" not in media

        # The raw downloaded bytes are what got stored.
        _, store_kwargs = mock_store.call_args
        assert store_kwargs["body"] == media_bytes
        assert store_kwargs["content_type"] == "image/jpeg"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://lookaside.fbsbx.com.attacker.example/steal",
        "https://attacker.example/steal",
    ],
)
async def test_download_media_never_sends_bearer_off_meta_origin(
    url, mock_credentials
):
    node = create_test_node(WhatsAppDownloadMediaConfig(media_url=url), mock_credentials)
    with patch("httpx.AsyncClient") as client:
        result = await node.execute({})
    assert result["status"] == "error"
    assert "outside" in result["error"]
    client.assert_not_called()


# ============================================================================
# Business Profile - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_business_profile_success(mock_credentials):
    """Test successful business profile retrieval"""
    config = WhatsAppGetBusinessProfileConfig(fields="about,address,description,email")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "data": [
                {
                    "about": "Test Business",
                    "address": "123 Test St",
                    "description": "Testing WhatsApp integration",
                    "email": "test@business.com",
                }
            ]
        },
        200,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_business_profile"
        assert result["data"]["data"][0]["about"] == "Test Business"


@pytest.mark.asyncio
async def test_update_business_profile_success(mock_credentials):
    """Test successful business profile update"""
    config = WhatsAppUpdateBusinessProfileConfig(
        about="Updated description", address="456 New St"
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse({"success": True}, 200)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_business_profile"


# ============================================================================
# Phone Number Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_register_phone_success(mock_credentials):
    """Test successful phone registration"""
    config = WhatsAppRegisterPhoneConfig(pin="123456")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse({"success": True}, 200)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "register_phone_number"


@pytest.mark.asyncio
async def test_request_code_success(mock_credentials):
    """Test successful verification code request"""
    config = WhatsAppRequestCodeConfig(code_method="SMS", language="en_US")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse({"success": True}, 200)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "request_verification_code"


# ============================================================================
# Template Management - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_templates_success(mock_credentials):
    """Test successful template listing"""
    config = WhatsAppListTemplatesConfig(limit=10, status="APPROVED")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "data": [
                {
                    "name": "hello_world",
                    "language": "en_US",
                    "status": "APPROVED",
                    "category": "UTILITY",
                },
                {
                    "name": "welcome_message",
                    "language": "en_US",
                    "status": "APPROVED",
                    "category": "MARKETING",
                },
            ],
            "paging": {},
        },
        200,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_message_templates"
        assert len(result["data"]["data"]) == 2
        assert result["data"]["data"][0]["name"] == "hello_world"


@pytest.mark.asyncio
async def test_create_template_success(mock_credentials):
    """Test successful template creation"""
    config = WhatsAppCreateTemplateConfig(
        name="test_template",
        language="en_US",
        category="UTILITY",
        body="Hello {{1}}, welcome!",
        header="Welcome",
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"id": "template_id_12345", "status": "PENDING", "category": "UTILITY"}, 201
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_message_template"
        assert result["data"]["id"] == "template_id_12345"


@pytest.mark.asyncio
async def test_delete_template_success(mock_credentials):
    """Test successful template deletion"""
    config = WhatsAppDeleteTemplateConfig(template_name="test_template")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse({"success": True}, 200)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_message_template"


# ============================================================================
# Commerce Operations - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_send_catalog_success(mock_credentials, test_phone):
    """Test successful catalog message sending"""
    config = WhatsAppSendCatalogConfig(
        to=test_phone, body="Check out our catalog!", thumbnail_product_id="product_123"
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"messaging_product": "whatsapp", "messages": [{"id": "wamid.catalog123"}]}, 200
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_catalog_message"


@pytest.mark.asyncio
async def test_send_product_success(mock_credentials, test_phone):
    """Test successful product message sending"""
    config = WhatsAppSendProductConfig(
        to=test_phone,
        catalog_id="catalog_123",
        product_id="SKU_456",
        body="Check this out!",
    )
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {"messaging_product": "whatsapp", "messages": [{"id": "wamid.product123"}]}, 200
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_product_message"


# ============================================================================
# Account Management - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_account_info_success(mock_credentials):
    """Test successful account info retrieval"""
    config = WhatsAppGetAccountInfoConfig(fields="id,name,timezone_id")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "id": "9876543210",
            "name": "Test Business Account",
            "timezone_id": "America/Los_Angeles",
        },
        200,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_account_info"
        assert result["data"]["name"] == "Test Business Account"


@pytest.mark.asyncio
async def test_list_phone_numbers_success(mock_credentials):
    """Test successful phone number listing"""
    config = WhatsAppListPhoneNumbersConfig(limit=10)
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "data": [
                {
                    "id": "1234567890123456",
                    "verified_name": "Test Business",
                    "display_phone_number": "+1 (234) 567-8900",
                    "quality_rating": "GREEN",
                    "messaging_limit_tier": "TIER_1K",
                }
            ]
        },
        200,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_account_phone_numbers"
        assert len(result["data"]["data"]) == 1
        assert result["data"]["data"][0]["verified_name"] == "Test Business"


# ============================================================================
# Error Handling - Mock Tests
# ============================================================================


@pytest.mark.asyncio
async def test_api_error_handling(mock_credentials, test_phone):
    """Test handling of API errors"""
    config = WhatsAppSendTextConfig(to=test_phone, body="Test")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "error": {
                "message": "Invalid OAuth access token",
                "type": "OAuthException",
                "code": 190,
            }
        },
        401,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "error"
        assert "Invalid OAuth access token" in result["error"]
        assert result["status_code"] == 401


@pytest.mark.asyncio
async def test_rate_limit_error(mock_credentials, test_phone):
    """Test handling of rate limit errors"""
    config = WhatsAppSendTextConfig(to=test_phone, body="Test")
    node = create_test_node(config, mock_credentials)

    mock_response = MockResponse(
        {
            "error": {
                "message": "Rate limit exceeded",
                "code": 4,
                "error_subcode": 2494055,
            }
        },
        429,
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 429


@pytest.mark.asyncio
async def test_network_timeout(mock_credentials, test_phone):
    """Test handling of network timeouts"""
    config = WhatsAppSendTextConfig(to=test_phone, body="Test")
    node = create_test_node(config, mock_credentials)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        import httpx

        mock_request.side_effect = httpx.TimeoutException("Request timeout")

        result = await node.execute({})

        assert result["status"] == "error"
        assert "timeout" in result["error"].lower()
        assert "timing_ms" in result


# ============================================================================
# Validation Tests
# ============================================================================


def test_config_validation_missing_fields():
    """Test Pydantic validation of required fields"""
    with pytest.raises(Exception):
        # Missing 'to' field should raise validation error
        WhatsAppSendTextConfig(body="Test")


def test_credential_validation():
    """Test credential validation"""
    with pytest.raises(Exception):
        # Missing access_token should raise validation error
        WhatsAppAccessTokenCredential(phone_number_id="123")


# ============================================================================
# Integration with Webhook Handler
# ============================================================================


@pytest.mark.asyncio
async def test_webhook_message_handling(mock_credentials):
    """Test webhook message reception"""
    config = WhatsAppReceiveMessageConfig(
        webhook_url="https://test.hooks.example.test", verify_token="test_verify_token"
    )
    node = create_test_node(config, mock_credentials)

    webhook_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "1234567890",
                                "phone_number_id": "1234567890123456",
                            },
                            "messages": [
                                {
                                    "from": "+12025550100",
                                    "id": "wamid.test123",
                                    "timestamp": "1234567890",
                                    "text": {"body": "Hello!"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    # execute() is only ever the MANUAL/test path — real firings short-circuit
    # via resolve_trigger_payload and never call it (nothing populates
    # inputs["webhook_payload"] in production). The output must say so instead
    # of faking a success envelope with empty data, which read as "the trigger
    # fired with no payload" to users and in-product agents alike.
    result = await node.execute({"webhook_payload": webhook_payload})

    assert result["status"] == "no_event"
    assert result["action"] == "receive_message"
    assert result["data"] == {}
    assert "No live event" in result["message"]


# ============================================================================
# WAHooks (QR credential) path — must run the synchronous SDK off the event loop
# ============================================================================


class _FakeWAHooksError(Exception):
    """Stand-in for wahooks.WAHooksError."""


class _FakeWAHooksClient:
    """Sync context-manager client mirroring wahooks' blocking API surface."""

    def __init__(self, record, sleep_s=0.0):
        self._record = record
        self._sleep_s = sleep_s

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send_message(self, conn_id, chat_id=None, text=None, reply_to=None):
        self._record["thread"] = threading.current_thread()
        self._record["send_kwargs"] = {"chat_id": chat_id, "text": text, "reply_to": reply_to}
        if self._sleep_s:
            time.sleep(self._sleep_s)
        return {"id": "wamid.qr123", "chat_id": chat_id, "text": text}

    def get_chats(self, conn_id, limit=None, offset=None, unread_only=False):
        self._record["get_chats_kwargs"] = {
            "limit": limit,
            "offset": offset,
            "unread_only": unread_only,
        }
        return [{"id": "111@c.us", "name": "Alice", "isGroup": False, "unread": True}]

    def get_messages(self, conn_id, chat_id, limit=50, before=None):
        self._record["get_messages_kwargs"] = {
            "chat_id": chat_id,
            "limit": limit,
            "before": before,
        }
        return {
            "messages": [{"id": "m1", "text": "hello", "fromMe": False}],
            "nextBefore": "cursor-1",
            "historyStartsAt": None,
        }

    def get_contacts(self, conn_id, limit=None, offset=None):
        self._record["get_contacts_kwargs"] = {"limit": limit, "offset": offset}
        return [{"jid": "111@c.us", "name": "Alice", "phoneNumber": "+111", "isGroup": False}]

    def edit_message(self, conn_id, message_id, chat_id, text):
        self._record["edit_kwargs"] = {
            "message_id": message_id,
            "chat_id": chat_id,
            "text": text,
        }
        return {"id": message_id, "edited": True}

    def mark_read(self, conn_id, chat_id):
        self._record["mark_read_chat_id"] = chat_id
        return {"ok": True}

    def react(self, conn_id, chat_id=None, message_id=None, reaction=None):
        self._record["react_kwargs"] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": reaction,
        }
        return {"ok": True}


@pytest.fixture
def qr_credentials():
    return WhatsAppQRCredential(connection_id="conn-abc123")


@pytest.mark.asyncio
async def test_wahooks_send_runs_off_event_loop_thread(qr_credentials):
    """The blocking wahooks client must execute in a worker thread, not the loop."""
    record = {}
    config = WhatsAppSendTextConfig(to="+12025550100", body="hi", preview_url=False)
    node = create_test_node(config, qr_credentials)

    loop_thread = threading.current_thread()

    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), patch(
        "wahooks.WAHooks", lambda api_key: _FakeWAHooksClient(record)
    ), patch("wahooks.WAHooksError", _FakeWAHooksError):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "send_text_message"
    assert result["data"]["id"] == "wamid.qr123"
    # to_chat_id() should have converted the E.164 number to a chat id.
    assert result["data"]["chat_id"] == "12025550100@s.whatsapp.net"
    # The blocking call ran on a different thread than the event loop.
    assert record["thread"] is not loop_thread


@pytest.mark.asyncio
async def test_wahooks_send_does_not_freeze_event_loop(qr_credentials):
    """A slow wahooks send must not stall other coroutines on the loop."""
    record = {}
    config = WhatsAppSendTextConfig(to="+12025550100", body="hi", preview_url=False)
    node = create_test_node(config, qr_credentials)

    ticks = 0
    done = asyncio.Event()

    async def ticker():
        nonlocal ticks
        while not done.is_set():
            await asyncio.sleep(0.01)
            ticks += 1

    ticker_task = asyncio.create_task(ticker())
    try:
        with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), patch(
            "wahooks.WAHooks", lambda api_key: _FakeWAHooksClient(record, sleep_s=0.3)
        ), patch("wahooks.WAHooksError", _FakeWAHooksError):
            result = await node.execute({})
    finally:
        done.set()
        await ticker_task

    assert result["status"] == "success"
    # If the 0.3s blocking send had run on the loop, the ticker would be starved.
    assert ticks >= 5


@pytest.mark.asyncio
async def test_wahooks_error_surfaces_as_error_result(qr_credentials):
    """Errors raised inside the worker thread propagate to the error envelope."""
    config = WhatsAppSendTextConfig(to="+12025550100", body="hi", preview_url=False)
    node = create_test_node(config, qr_credentials)

    class _FailingClient(_FakeWAHooksClient):
        def send_message(self, conn_id, chat_id=None, text=None, reply_to=None):
            raise _FakeWAHooksError("rate limited")

    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), patch(
        "wahooks.WAHooks", lambda api_key: _FailingClient({})
    ), patch("wahooks.WAHooksError", _FakeWAHooksError):
        result = await node.execute({})

    assert result["status"] == "error"
    assert result["action"] == "send_text_message"
    assert "rate limited" in result["error"]
    assert result["provider"] == "wahooks"


# ============================================================================
# WAHooks QR read/edit operations (wahooks 0.10.0)
# ============================================================================


def _qr_patches(record, client_cls=_FakeWAHooksClient):
    return (
        patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}),
        patch("wahooks.WAHooks", lambda api_key: client_cls(record)),
        patch("wahooks.WAHooksError", _FakeWAHooksError),
    )


async def _run_qr_op(config, qr_credentials, record):
    node = create_test_node(config, qr_credentials)
    p1, p2, p3 = _qr_patches(record)
    with p1, p2, p3:
        return await node.execute({})


@pytest.mark.asyncio
async def test_wahooks_get_chat_messages(qr_credentials):
    """get_chat_messages normalizes the page envelope and passes @-suffixed ids through."""
    record = {}
    config = WhatsAppGetChatMessagesConfig(chat_id="111@c.us", limit=25, before="tok")
    result = await _run_qr_op(config, qr_credentials, record)

    assert result["status"] == "success"
    assert record["get_messages_kwargs"] == {
        "chat_id": "111@c.us",
        "limit": 25,
        "before": "tok",
    }
    data = result["data"]
    assert data["messages"][0]["id"] == "m1"
    assert data["next_before"] == "cursor-1"
    assert data["history_starts_at"] is None


@pytest.mark.asyncio
async def test_wahooks_get_chat_messages_converts_bare_phone(qr_credentials):
    """A bare E.164 chat_id gets the WAHooks suffix; empty cursor becomes None."""
    record = {}
    config = WhatsAppGetChatMessagesConfig(chat_id="+1 202-555-0100", before="")
    await _run_qr_op(config, qr_credentials, record)
    assert record["get_messages_kwargs"]["chat_id"] == "12025550100@s.whatsapp.net"
    assert record["get_messages_kwargs"]["before"] is None


@pytest.mark.asyncio
async def test_wahooks_list_recent_chats_forwards_filters(qr_credentials):
    record = {}
    config = WhatsAppGetChatsConfig(limit=10, unread_only="true")
    result = await _run_qr_op(config, qr_credentials, record)
    assert record["get_chats_kwargs"] == {"limit": 10, "offset": None, "unread_only": True}
    assert result["data"]["chats"][0]["name"] == "Alice"
    assert result["data"]["count"] == 1


@pytest.mark.asyncio
async def test_wahooks_list_contacts(qr_credentials):
    record = {}
    result = await _run_qr_op(WhatsAppListContactsConfig(limit=99), qr_credentials, record)
    assert record["get_contacts_kwargs"]["limit"] == 99
    assert result["data"]["contacts"][0]["jid"] == "111@c.us"


@pytest.mark.asyncio
async def test_wahooks_edit_message(qr_credentials):
    record = {}
    config = WhatsAppEditMessageConfig(chat_id="111@c.us", message_id="m1", body="fixed")
    result = await _run_qr_op(config, qr_credentials, record)
    assert result["status"] == "success"
    assert record["edit_kwargs"] == {"message_id": "m1", "chat_id": "111@c.us", "text": "fixed"}


@pytest.mark.asyncio
async def test_wahooks_mark_chat_read(qr_credentials):
    record = {}
    config = WhatsAppMarkChatReadConfig(chat_id="111@c.us")
    result = await _run_qr_op(config, qr_credentials, record)
    assert result["status"] == "success"
    assert record["mark_read_chat_id"] == "111@c.us"


@pytest.mark.asyncio
async def test_wahooks_send_reaction(qr_credentials):
    """send_reaction_emoji now routes to WAHooks react() for QR credentials."""
    record = {}
    config = WhatsAppSendReactionConfig(to="+12025550100", message_id="m1", emoji="👍")
    result = await _run_qr_op(config, qr_credentials, record)
    assert result["status"] == "success"
    assert record["react_kwargs"] == {
        "chat_id": "12025550100@s.whatsapp.net",
        "message_id": "m1",
        "reaction": "👍",
    }


@pytest.mark.asyncio
async def test_wahooks_send_text_forwards_reply_to(qr_credentials):
    record = {}
    config = WhatsAppSendTextConfig(
        to="111@c.us", body="hi", reply_to_message_id="m9", preview_url=False
    )
    result = await _run_qr_op(config, qr_credentials, record)
    assert result["status"] == "success"
    # @c.us id passes through untouched; reply_to is forwarded
    assert record["send_kwargs"] == {"chat_id": "111@c.us", "text": "hi", "reply_to": "m9"}


@pytest.mark.asyncio
async def test_qr_only_op_with_cloud_credentials_raises(mock_credentials):
    """A QR-only operation on a Cloud API credential fails loud, not 'unknown action'."""
    config = WhatsAppGetChatMessagesConfig(chat_id="111@c.us")
    node = create_test_node(config, mock_credentials)
    with pytest.raises(ValueError, match="QR credential"):
        await node.execute({})


@pytest.mark.asyncio
async def test_cloud_send_text_includes_reply_context(mock_credentials, test_phone):
    """Cloud API send_text carries reply_to_message_id as a context reference."""
    config = WhatsAppSendTextConfig(
        to=test_phone, body="hi", reply_to_message_id="wamid.orig", preview_url=False
    )
    node = create_test_node(config, mock_credentials)
    mock_response = MockResponse({"messages": [{"id": "wamid.new"}]})
    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=mock_response)) as req:
        result = await node.execute({})
    assert result["status"] == "success"
    assert req.call_args.kwargs["json"]["context"] == {"message_id": "wamid.orig"}


# ============================================================================
# load_field_options — chat picker
# ============================================================================


@pytest.mark.asyncio
async def test_load_field_options_lists_chats():
    """QR credential: chats become options with name labels and jid fallback."""
    record = {}

    class _ChatsClient(_FakeWAHooksClient):
        def get_chats(self, conn_id, limit=None, offset=None, unread_only=False):
            return [
                {"id": "111@c.us", "name": "Alice", "isGroup": False, "unread": False},
                {"id": "222@g.us", "name": "Team", "isGroup": True, "unread": True},
                {"id": "333@c.us", "name": None, "isGroup": False, "unread": False},
            ]

    p1, p2, p3 = _qr_patches(record, _ChatsClient)
    with p1, p2, p3:
        result = await WhatsAppNode.load_field_options(
            "to", {"credential_type": "whatsapp_qr", "connection_id": "conn-1"}
        )
    options = result["options"]
    assert [o["value"] for o in options] == ["111@c.us", "222@g.us", "333@c.us"]
    assert options[0]["label"] == "Alice"
    assert options[1]["metadata"]["is_group"] is True
    assert options[2]["label"] == "333"  # jid fallback when name is missing
    assert result["next_page_token"] is None  # short page → no more results


@pytest.mark.asyncio
async def test_load_field_options_search_filters():
    record = {}

    class _ChatsClient(_FakeWAHooksClient):
        def get_chats(self, conn_id, limit=None, offset=None, unread_only=False):
            if offset:
                return []
            return [
                {"id": "111@c.us", "name": "Alice"},
                {"id": "222@c.us", "name": "Bob"},
            ]

    p1, p2, p3 = _qr_patches(record, _ChatsClient)
    with p1, p2, p3:
        result = await WhatsAppNode.load_field_options(
            "chat_id",
            {"credential_type": "whatsapp_qr", "connection_id": "conn-1"},
            search="ali",
        )
    assert [o["label"] for o in result["options"]] == ["Alice"]


@pytest.mark.asyncio
async def test_load_field_options_cloud_credential_empty():
    """Cloud API credential: no chat listing exists — empty options, no error."""
    result = await WhatsAppNode.load_field_options(
        "to", {"credential_type": "whatsapp_access_token", "access_token": "t"}
    )
    assert result == {"options": [], "next_page_token": None}


@pytest.mark.asyncio
async def test_load_field_options_qr_without_connection_raises():
    """QR credential missing its connection_id must fail loud (reconnect prompt)."""
    with pytest.raises(ValueError, match="Reconnect WhatsApp"):
        await WhatsAppNode.load_field_options(
            "to", {"credential_type": "whatsapp_qr"}
        )


# ============================================================================
# cleanup_external_webhook — credential-swap leak fix (2026-06-25)
#
# Closes the duplicate-execution bug reproduced in integration testing:
# swapping a credential on a WhatsApp trigger node left a WAHooks config
# attached to the OLD connection. When the old and new connections both
# saw the same WhatsApp event (a group message reached both connections), the
# orphan fired alongside the new one and the workflow ran twice.
#
# The fix wires WebhookManager.handle_credential_change to call this
# cleanup with the OLD credential. These tests pin the contract:
# - With proper old-credential context: delete the matching WAHooks config
# - Without credentials (legacy callers): no-op (don't 401/burn API quota)
# - Multiple configs on the connection: delete only the one whose URL
#   matches our noclick subdomain (don't nuke unrelated webhooks)
# ============================================================================


class _FakeWAHooksAdminClient:
    """Sync WAHooks client mirroring the admin surface used by cleanup:
    list_webhooks(connection_id), delete_webhook(webhook_id)."""

    def __init__(self, webhooks_by_connection):
        self._webhooks = webhooks_by_connection
        self.deleted = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_webhooks(self, connection_id):
        return list(self._webhooks.get(connection_id, []))

    def delete_webhook(self, webhook_id):
        for conn, whs in self._webhooks.items():
            self._webhooks[conn] = [w for w in whs if w["id"] != webhook_id]
        self.deleted.append(webhook_id)
        return True


@pytest.mark.asyncio
async def test_cleanup_external_webhook_deletes_matching_wahooks_config():
    """End-to-end check: given the OLD credential + OLD node config from
    the autosave diff, the WhatsApp cleanup finds the WAHooks config on
    the OLD connection whose URL matches our noclick webhook subdomain
    and deletes it. This is what closes the duplicate-execution loop
    when a user swaps credentials on a trigger node."""
    from nodes.whatsapp_node import WhatsAppNode

    old_connection = "conn-OLD"
    other_connection = "conn-NEW"
    noclick_webhook_id = "5dda188b-7569-4328-824b-5a5d37972bd4"

    # Asked rather than spelled: cleanup matches on this instance's own webhook
    # URL, and a self-hosted install mints those under its own host.
    from utils.webhook_delivery import get_webhook_url

    our_url = get_webhook_url(noclick_webhook_id)

    # Two WAHooks configs target our URL on the OLD connection (the leak), plus
    # an unrelated webhook on a different connection.
    state = {
        old_connection: [
            {"id": "whk-leak", "url": our_url},
            {"id": "whk-unrelated", "url": "https://something-else.example.com"},
        ],
        other_connection: [
            {"id": "whk-other", "url": our_url},
        ],
    }
    fake_client = _FakeWAHooksAdminClient(state)

    old_config = {
        "operation": "receive_message",
        "webhook_id": noclick_webhook_id,
        "credentialIds": {"whatsapp_qr": "cred-OLD"},
    }
    old_credential = {
        "credential_type": "whatsapp_qr",
        "connection_id": old_connection,
    }

    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), patch(
        "wahooks.WAHooks", lambda api_key: fake_client
    ):
        await WhatsAppNode.cleanup_external_webhook(
            pool=None,
            workflow_id="wf-1",
            node_id="trigger-node",
            config=old_config,
            credentials=old_credential,
        )

    # Cleanup MUST: delete the leaking webhook on the OLD connection
    assert "whk-leak" in fake_client.deleted
    # Cleanup MUST NOT: touch the unrelated webhook on the OLD connection
    assert "whk-unrelated" not in fake_client.deleted
    # Cleanup MUST NOT: touch the new connection's webhook (different conn)
    assert "whk-other" not in fake_client.deleted


@pytest.mark.asyncio
async def test_cleanup_external_webhook_noop_when_credentials_missing():
    """Legacy callers (and the pre-fix operation-change path) pass
    credentials=None. The provider must short-circuit instead of probing
    every WAHooks connection — preserves the existing safe-no-op behavior
    so we don't regress."""
    from nodes.whatsapp_node import WhatsAppNode

    fake_client = _FakeWAHooksAdminClient({"conn-X": [{"id": "whk-1", "url": "https://x.hooks.example.test"}]})

    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), patch(
        "wahooks.WAHooks", lambda api_key: fake_client
    ):
        await WhatsAppNode.cleanup_external_webhook(
            pool=None, workflow_id="wf", node_id="n", config={"webhook_id": "anything"},
            credentials=None,
        )
    assert fake_client.deleted == []


@pytest.mark.asyncio
async def test_cleanup_external_webhook_noop_when_no_match():
    """If the WAHooks connection has no webhook for our noclick URL,
    we delete nothing — protects against deleting webhooks the user
    registered for some other reason."""
    from nodes.whatsapp_node import WhatsAppNode

    fake_client = _FakeWAHooksAdminClient({
        "conn-X": [{"id": "whk-other", "url": "https://different.example.com/hook"}],
    })
    old_config = {"webhook_id": "5dda188b-7569-4328-824b-5a5d37972bd4"}
    old_credential = {"credential_type": "whatsapp_qr", "connection_id": "conn-X"}

    with patch.dict(os.environ, {"WAHOOKS_API_KEY": "test-key"}), patch(
        "wahooks.WAHooks", lambda api_key: fake_client
    ):
        await WhatsAppNode.cleanup_external_webhook(
            pool=None, workflow_id="wf", node_id="n",
            config=old_config, credentials=old_credential,
        )
    assert fake_client.deleted == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
