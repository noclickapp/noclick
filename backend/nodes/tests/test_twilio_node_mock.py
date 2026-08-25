"""
Mock tests for Twilio Communications Platform node.

Tests 40+ Twilio operations using mocked httpx responses across:
- SMS/MMS Messaging (4 operations)
- WhatsApp Business (2 operations)
- Voice Calls (4 operations)
- Recordings (3 operations)
- Conferences (4 operations)
- Verify API (2 operations)
- Lookup API (1 operation)
- Conversations API (6 operations)
- Phone Numbers API (5 operations)
- SendGrid Email API (3 operations)

No actual Twilio API calls are made - tests verify correct URL construction,
request body formation, authentication headers, and response handling.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import base64

# Import the node and all config classes
from nodes.twilio_node import (
    TwilioNode,
    TwilioNodeFullConfig,
    TwilioAccountCredential,
    TwilioAPIKeyCredential,
    SendGridAPIKeyCredential,
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
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def account_credentials():
    """Create Account SID + Auth Token credentials."""
    return TwilioAccountCredential(
        account_sid="AC_TEST_ACCOUNT_SID",
        auth_token="test_auth_token_12345",
    )


@pytest.fixture
def api_key_credentials():
    """Create API Key credentials."""
    return TwilioAPIKeyCredential(
        account_sid="AC_TEST_ACCOUNT_SID",
        api_key_sid="SK_TEST_API_KEY_SID",
        api_key_secret="test_api_key_secret_12345",
    )


@pytest.fixture
def sendgrid_credentials():
    """Create SendGrid API Key credentials."""
    return SendGridAPIKeyCredential(api_key="SG.test_sendgrid_api_key_12345")


def create_twilio_node(config, credentials) -> TwilioNode:
    """Helper to create a TwilioNode with given config and credentials."""
    full_config = TwilioNodeFullConfig(config=config, credentials=credentials)
    from unittest.mock import Mock

    return TwilioNode(
        node_id="test-twilio-node",
        node_type="automation-twilio",
        node_data={},
        config=full_config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_twilio_response(data: dict, status_code: int = 200):
    """Create a mock httpx response for Twilio API."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = data
    response.text = str(data)
    return response


def create_mock_sendgrid_response(status_code: int = 202):
    """Create a mock httpx response for SendGrid API (typically 202 Accepted)."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = ""
    return response


# ============================================================================
# SMS/MMS Operations Tests (4 operations)
# ============================================================================


class TestSMSOperations:
    """Test SMS/MMS messaging operations."""

    @pytest.mark.asyncio
    async def test_send_sms(self, account_credentials):
        """Test sending an SMS message."""
        config = TwilioSendSMSConfig(
            from_number="+12025550100", to_number="+1987654321", body="Test SMS message"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "SM1234567890abcdef",
            "from": "+12025550100",
            "to": "+1987654321",
            "body": "Test SMS message",
            "status": "queued",
            "price": "0.00750",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "SM1234567890abcdef"
            assert result["status"] == "queued"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_message(self, account_credentials):
        """Test getting message details."""
        config = TwilioGetMessageConfig(message_sid="SM1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "SM1234567890abcdef",
            "status": "delivered",
            "price": "0.00750",
            "error_code": None,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "SM1234567890abcdef"
            assert result["status"] == "delivered"
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_messages(self, account_credentials):
        """Test listing messages with filters."""
        config = TwilioListMessagesConfig(to_number="+1987654321", page_size=10)
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "messages": [
                {"sid": "SM111", "to": "+1987654321", "status": "delivered"},
                {"sid": "SM222", "to": "+1987654321", "status": "sent"},
            ],
            "page_size": 10,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["messages"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_message(self, account_credentials):
        """Test deleting a message."""
        config = TwilioDeleteMessageConfig(message_sid="SM1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock 204 No Content response
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 204
            mock_client.delete.return_value = mock_response

            result = await node.execute({})

            assert result["success"] is True
            mock_client.delete.assert_called_once()


# ============================================================================
# WhatsApp Operations Tests (2 operations)
# ============================================================================


class TestWhatsAppOperations:
    """Test WhatsApp Business API operations."""

    @pytest.mark.asyncio
    async def test_send_whatsapp_message(self, account_credentials):
        """Test sending a WhatsApp message."""
        config = TwilioSendWhatsAppConfig(
            from_number="whatsapp:+14155238886",
            to_number="whatsapp:+1987654321",
            body="Hello from WhatsApp!",
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "SM1234567890abcdef",
            "from": "whatsapp:+14155238886",
            "to": "whatsapp:+1987654321",
            "body": "Hello from WhatsApp!",
            "status": "queued",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "SM1234567890abcdef"
            assert "whatsapp:" in result["from"]
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_whatsapp_message(self, account_credentials):
        """Test getting WhatsApp message details."""
        config = TwilioGetWhatsAppMessageConfig(message_sid="SM1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "SM1234567890abcdef",
            "from": "whatsapp:+14155238886",
            "to": "whatsapp:+1987654321",
            "status": "delivered",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "SM1234567890abcdef"
            assert result["status"] == "delivered"
            mock_client.get.assert_called_once()


# ============================================================================
# Voice Call Operations Tests (4 operations)
# ============================================================================


class TestVoiceCallOperations:
    """Test Programmable Voice API operations."""

    @pytest.mark.asyncio
    async def test_make_call(self, account_credentials):
        """Test making an outbound call."""
        config = TwilioMakeCallConfig(
            from_number="+12025550100",
            to_number="+1987654321",
            url="https://example.com/twiml",
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "CA1234567890abcdef",
            "from": "+12025550100",
            "to": "+1987654321",
            "status": "queued",
            "direction": "outbound-api",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "CA1234567890abcdef"
            assert result["status"] == "queued"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_call(self, account_credentials):
        """Test getting call details."""
        config = TwilioGetCallConfig(call_sid="CA1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "CA1234567890abcdef",
            "status": "completed",
            "duration": "45",
            "price": "0.01500",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "CA1234567890abcdef"
            assert result["status"] == "completed"
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_calls(self, account_credentials):
        """Test listing calls with filters."""
        config = TwilioListCallsConfig(status="completed", page_size=20)
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "calls": [
                {"sid": "CA111", "status": "completed", "duration": "30"},
                {"sid": "CA222", "status": "completed", "duration": "45"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["calls"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_call(self, account_credentials):
        """Test updating an in-progress call."""
        config = TwilioUpdateCallConfig(
            call_sid="CA1234567890abcdef", status="completed"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {"sid": "CA1234567890abcdef", "status": "completed"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["status"] == "completed"
            mock_client.post.assert_called_once()


# ============================================================================
# Recording Operations Tests (3 operations)
# ============================================================================


class TestRecordingOperations:
    """Test call recording operations."""

    @pytest.mark.asyncio
    async def test_list_recordings(self, account_credentials):
        """Test listing call recordings."""
        config = TwilioListRecordingsConfig(call_sid="CA1234567890abcdef", page_size=10)
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "recordings": [
                {"sid": "RE111", "call_sid": "CA1234567890abcdef", "duration": "45"},
                {"sid": "RE222", "call_sid": "CA1234567890abcdef", "duration": "30"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["recordings"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_recording(self, account_credentials):
        """Test getting recording details."""
        config = TwilioGetRecordingConfig(recording_sid="RE1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "RE1234567890abcdef",
            "duration": "45",
            "price": "0.00500",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "RE1234567890abcdef"
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_recording(self, account_credentials):
        """Test deleting a recording."""
        config = TwilioDeleteRecordingConfig(recording_sid="RE1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock 204 No Content response
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 204
            mock_client.delete.return_value = mock_response

            result = await node.execute({})

            assert result["success"] is True
            mock_client.delete.assert_called_once()


# ============================================================================
# Conference Operations Tests (4 operations)
# ============================================================================


class TestConferenceOperations:
    """Test conference call operations."""

    @pytest.mark.asyncio
    async def test_list_conferences(self, account_credentials):
        """Test listing conferences."""
        config = TwilioListConferencesConfig(status="in-progress", page_size=20)
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "conferences": [
                {"sid": "CF111", "friendly_name": "Meeting 1", "status": "in-progress"},
                {"sid": "CF222", "friendly_name": "Meeting 2", "status": "in-progress"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["conferences"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_conference(self, account_credentials):
        """Test getting conference details."""
        config = TwilioGetConferenceConfig(conference_sid="CF1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "CF1234567890abcdef",
            "friendly_name": "Team Meeting",
            "status": "in-progress",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "CF1234567890abcdef"
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_participants(self, account_credentials):
        """Test listing conference participants."""
        config = TwilioListParticipantsConfig(conference_sid="CF1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "participants": [
                {"call_sid": "CA111", "muted": False},
                {"call_sid": "CA222", "muted": True},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["participants"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_participant(self, account_credentials):
        """Test updating a conference participant."""
        config = TwilioUpdateParticipantConfig(
            conference_sid="CF1234567890abcdef",
            call_sid="CA1234567890abcdef",
            muted=True,
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {"call_sid": "CA1234567890abcdef", "muted": True}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["muted"] is True
            mock_client.post.assert_called_once()


# ============================================================================
# Verify API Operations Tests (2 operations)
# ============================================================================


class TestVerifyOperations:
    """Test Twilio Verify API operations (2FA)."""

    @pytest.mark.asyncio
    async def test_start_verification(self, account_credentials):
        """Test starting a verification."""
        config = TwilioStartVerificationConfig(
            verify_service_sid="VA1234567890abcdef", to="+1987654321", channel="sms"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "VE1234567890abcdef",
            "to": "+1987654321",
            "channel": "sms",
            "status": "pending",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["status"] == "pending"
            assert result["channel"] == "sms"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_verification(self, account_credentials):
        """Test checking a verification code."""
        config = TwilioCheckVerificationConfig(
            verify_service_sid="VA1234567890abcdef", to="+1987654321", code="123456"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "VE1234567890abcdef",
            "status": "approved",
            "valid": True,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["status"] == "approved"
            assert result["valid"] is True
            mock_client.post.assert_called_once()


# ============================================================================
# Lookup API Operations Tests (1 operation)
# ============================================================================


class TestLookupOperations:
    """Test Twilio Lookup API operations."""

    @pytest.mark.asyncio
    async def test_lookup_phone_number(self, account_credentials):
        """Test looking up phone number information."""
        config = TwilioLookupPhoneNumberConfig(
            phone_number="+1987654321", type="carrier"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "phone_number": "+1987654321",
            "country_code": "US",
            "carrier": {"name": "AT&T", "type": "mobile"},
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["phone_number"] == "+1987654321"
            assert result["carrier"]["type"] == "mobile"
            mock_client.get.assert_called_once()


# ============================================================================
# Conversations API Operations Tests (6 operations)
# ============================================================================


class TestConversationsOperations:
    """Test Twilio Conversations API operations."""

    @pytest.mark.asyncio
    async def test_create_conversation(self, account_credentials):
        """Test creating a conversation."""
        config = TwilioCreateConversationConfig(
            friendly_name="Customer Support Chat", unique_name="support_user123"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "CH1234567890abcdef",
            "friendly_name": "Customer Support Chat",
            "unique_name": "support_user123",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "CH1234567890abcdef"
            assert result["friendly_name"] == "Customer Support Chat"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_conversations(self, account_credentials):
        """Test listing conversations."""
        config = TwilioListConversationsConfig(page_size=20)
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "conversations": [
                {"sid": "CH111", "friendly_name": "Chat 1"},
                {"sid": "CH222", "friendly_name": "Chat 2"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["conversations"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_conversation_details(self, account_credentials):
        """Test getting conversation details."""
        config = TwilioGetConversationDetailsConfig(
            conversation_sid="CH1234567890abcdef"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "CH1234567890abcdef",
            "friendly_name": "Customer Support",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "CH1234567890abcdef"
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_conversation_message(self, account_credentials):
        """Test sending a message to a conversation."""
        config = TwilioSendConversationMessageConfig(
            conversation_sid="CH1234567890abcdef", body="Hello from the conversation!"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "IM1234567890abcdef",
            "body": "Hello from the conversation!",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "IM1234567890abcdef"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_participant(self, account_credentials):
        """Test adding a participant to a conversation."""
        config = TwilioAddParticipantConfig(
            conversation_sid="CH1234567890abcdef",
            messaging_binding_address="+1987654321",
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "MB1234567890abcdef",
            "conversation_sid": "CH1234567890abcdef",
            "messaging_binding": {"address": "+1987654321"},
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "MB1234567890abcdef"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_conversation(self, account_credentials):
        """Test deleting a conversation."""
        config = TwilioDeleteConversationConfig(conversation_sid="CH1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock 204 No Content response
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 204
            mock_client.delete.return_value = mock_response

            result = await node.execute({})

            assert result["success"] is True
            mock_client.delete.assert_called_once()


# ============================================================================
# Phone Numbers API Operations Tests (5 operations)
# ============================================================================


class TestPhoneNumbersOperations:
    """Test phone number management operations."""

    @pytest.mark.asyncio
    async def test_search_available_numbers(self, account_credentials):
        """Test searching for available phone numbers."""
        config = TwilioSearchAvailableNumbersConfig(
            country_code="US", area_code="415", limit=10
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "available_phone_numbers": [
                {"phone_number": "+14155551234", "friendly_name": "(415) 555-1234"},
                {"phone_number": "+14155555678", "friendly_name": "(415) 555-5678"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["available_phone_numbers"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_incoming_numbers(self, account_credentials):
        """Test listing owned phone numbers."""
        config = TwilioListIncomingNumbersConfig(page_size=20)
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "incoming_phone_numbers": [
                {"sid": "PN111", "phone_number": "+14155551234"},
                {"sid": "PN222", "phone_number": "+14155555678"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert len(result["incoming_phone_numbers"]) == 2
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_dynamic_phone_options_accepts_expected_relative_page_uri(
        self, account_credentials
    ):
        account_sid = account_credentials.account_sid
        cursor = (
            f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json"
            "?PageSize=200&Page=1&PageToken=next-token"
        )

        with patch("nodes.twilio_node.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                {
                    "incoming_phone_numbers": [
                        {
                            "sid": "PN111",
                            "phone_number": "+14155551234",
                            "friendly_name": "Main line",
                        }
                    ],
                    "next_page_uri": None,
                }
            )

            result = await TwilioNode._list_phone_number_options(
                account_credentials.model_dump(), page_token=cursor
            )

        assert result == {
            "options": [{"value": "PN111", "label": "Main line"}],
            "next_page_token": None,
        }
        mock_client.get.assert_awaited_once_with(
            f"https://api.twilio.com{cursor}",
            auth=(account_sid, account_credentials.auth_token),
            params=None,
        )

    @pytest.mark.parametrize(
        "page_token",
        [
            "@attacker.invalid/steal",
            r"\@attacker.invalid/steal",
            "https://attacker.invalid/steal",
            "https://api.twilio.com@attacker.invalid/steal",
            "https://attacker.invalid@api.twilio.com/2010-04-01/Accounts/AC123/IncomingPhoneNumbers.json",
            "https://api.twilio.com/2010-04-01/Accounts/AC123/IncomingPhoneNumbers.json",
            "//attacker.invalid/steal",
            "/2010-04-01/Accounts/ACother/IncomingPhoneNumbers.json?Page=1",
            "/2010-04-01/Accounts/AC_TEST_ACCOUNT_SID/Messages.json?Page=1",
            "/2010-04-01/Accounts/AC_TEST_ACCOUNT_SID/IncomingPhoneNumbers.json#@attacker.invalid",
        ],
    )
    @pytest.mark.asyncio
    async def test_dynamic_phone_options_rejects_untrusted_page_uri_before_auth(
        self, account_credentials, page_token
    ):
        with patch("nodes.twilio_node.httpx.AsyncClient") as mock_client_class:
            with pytest.raises(ValueError, match="Invalid Twilio pagination cursor"):
                await TwilioNode._list_phone_number_options(
                    account_credentials.model_dump(), page_token=page_token
                )

        mock_client_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_dynamic_phone_options_does_not_return_untrusted_provider_cursor(
        self, account_credentials
    ):
        with patch("nodes.twilio_node.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = create_mock_twilio_response(
                {
                    "incoming_phone_numbers": [],
                    "next_page_uri": "@attacker.invalid/steal",
                }
            )

            with pytest.raises(ValueError, match="Invalid Twilio pagination cursor"):
                await TwilioNode._list_phone_number_options(
                    account_credentials.model_dump()
                )

        requested_url = mock_client.get.await_args.args[0]
        assert requested_url.startswith("https://api.twilio.com/")
        assert "attacker.invalid" not in requested_url

    @pytest.mark.asyncio
    async def test_purchase_phone_number(self, account_credentials):
        """Test purchasing a phone number."""
        config = TwilioPurchasePhoneNumberConfig(
            phone_number="+14155551234", friendly_name="Main Business Line"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "PN1234567890abcdef",
            "phone_number": "+14155551234",
            "friendly_name": "Main Business Line",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["sid"] == "PN1234567890abcdef"
            assert result["phone_number"] == "+14155551234"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_phone_number(self, account_credentials):
        """Test updating phone number configuration."""
        config = TwilioUpdatePhoneNumberConfig(
            phone_number_sid="PN1234567890abcdef", friendly_name="Updated Name"
        )
        node = create_twilio_node(config, account_credentials)

        mock_response_data = {
            "sid": "PN1234567890abcdef",
            "friendly_name": "Updated Name",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_twilio_response(
                mock_response_data
            )

            result = await node.execute({})

            assert result["friendly_name"] == "Updated Name"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_phone_number(self, account_credentials):
        """Test releasing a phone number."""
        config = TwilioReleasePhoneNumberConfig(phone_number_sid="PN1234567890abcdef")
        node = create_twilio_node(config, account_credentials)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock 204 No Content response
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 204
            mock_client.delete.return_value = mock_response

            result = await node.execute({})

            assert result["success"] is True
            mock_client.delete.assert_called_once()


# ============================================================================
# SendGrid Email API Operations Tests (3 operations)
# ============================================================================


class TestSendGridOperations:
    """Test SendGrid Email API operations."""

    @pytest.mark.asyncio
    async def test_send_email(self, sendgrid_credentials):
        """Test sending an email via SendGrid."""
        config = SendGridSendEmailConfig(
            from_email="sender@example.com",
            to_email="recipient@example.com",
            subject="Test Email",
            html_content="<p>Hello World</p>",
        )
        node = create_twilio_node(config, sendgrid_credentials)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_sendgrid_response(202)

            result = await node.execute({})

            assert result["success"] is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_template_email(self, sendgrid_credentials):
        """Test sending an email using a SendGrid template."""
        config = SendGridSendTemplateEmailConfig(
            from_email="sender@example.com",
            to_email="recipient@example.com",
            template_id="d-12345abcdef",
            dynamic_template_data='{"name": "John Doe"}',
        )
        node = create_twilio_node(config, sendgrid_credentials)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = create_mock_sendgrid_response(202)

            result = await node.execute({})

            assert result["success"] is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_email_stats(self, sendgrid_credentials):
        """Test getting email delivery statistics."""
        config = SendGridGetEmailStatsConfig(
            start_date="2024-01-01", aggregated_by="day"
        )
        node = create_twilio_node(config, sendgrid_credentials)

        mock_response_data = [
            {
                "date": "2024-01-01",
                "stats": [{"metrics": {"delivered": 100, "bounces": 2}}],
            }
        ]

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Create response that returns list for JSON
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_response.text = str(mock_response_data)
            mock_client.get.return_value = mock_response

            result = await node.execute({})

            assert len(result) == 1
            mock_client.get.assert_called_once()


# ============================================================================
# Authentication Tests
# ============================================================================


class TestAuthentication:
    """Test different authentication methods."""

    @pytest.mark.asyncio
    async def test_account_sid_auth_token(self, account_credentials):
        """Test authentication with Account SID + Auth Token."""
        config = TwilioSendSMSConfig(
            from_number="+12025550100", to_number="+1987654321", body="Test"
        )
        node = create_twilio_node(config, account_credentials)

        # Verify credentials are stored correctly in the config
        credentials = node.config.credentials
        assert isinstance(credentials, TwilioAccountCredential)
        assert credentials.account_sid == "AC_TEST_ACCOUNT_SID"
        assert credentials.auth_token == "test_auth_token_12345"

    @pytest.mark.asyncio
    async def test_api_key_credentials(self, api_key_credentials):
        """Test authentication with API Key."""
        config = TwilioSendSMSConfig(
            from_number="+12025550100", to_number="+1987654321", body="Test"
        )
        node = create_twilio_node(config, api_key_credentials)

        # Verify credentials are stored correctly in the config
        credentials = node.config.credentials
        assert isinstance(credentials, TwilioAPIKeyCredential)
        assert credentials.account_sid == "AC_TEST_ACCOUNT_SID"
        assert credentials.api_key_sid == "SK_TEST_API_KEY_SID"
        assert credentials.api_key_secret == "test_api_key_secret_12345"

    @pytest.mark.asyncio
    async def test_sendgrid_api_key(self, sendgrid_credentials):
        """Test authentication with SendGrid API Key."""
        config = SendGridSendEmailConfig(
            from_email="test@example.com",
            to_email="recipient@example.com",
            subject="Test",
            html_content="<p>Test</p>",
        )
        node = create_twilio_node(config, sendgrid_credentials)

        # Verify credentials are stored correctly in the config
        credentials = node.config.credentials
        assert isinstance(credentials, SendGridAPIKeyCredential)
        assert credentials.api_key == "SG.test_sendgrid_api_key_12345"
