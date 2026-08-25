"""
Unit tests for Gmail node.
Tests the Gmail node functionality with mocked API responses.
All 27 operations are tested covering messages, drafts, labels, threads, and profile.
"""

import pytest
import base64
from unittest.mock import patch, AsyncMock, MagicMock

from nodes.gmail_node import (
    GmailNode,
    GmailNodeConfig,
    GmailOAuthCredential,
    # Message configs
    GmailSendConfig,
    GmailReadConfig,
    GmailGetMessageConfig,
    GmailGetAttachmentConfig,
    GmailDeleteMessageConfig,
    GmailTrashMessageConfig,
    GmailUntrashMessageConfig,
    GmailModifyMessageConfig,
    GmailReplyConfig,
    GmailForwardConfig,
    # Draft configs
    GmailCreateDraftConfig,
    GmailListDraftsConfig,
    GmailGetDraftConfig,
    GmailUpdateDraftConfig,
    GmailDeleteDraftConfig,
    GmailSendDraftConfig,
    # Label configs
    GmailListLabelsConfig,
    GmailCreateLabelConfig,
    GmailGetLabelConfig,
    GmailUpdateLabelConfig,
    GmailDeleteLabelConfig,
    # Thread configs
    GmailListThreadsConfig,
    GmailGetThreadConfig,
    GmailTrashThreadConfig,
    GmailUntrashThreadConfig,
    GmailModifyThreadConfig,
    GmailDeleteThreadConfig,
    # Profile config
    GmailGetProfileConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================




@pytest.fixture(autouse=True)
def _branding_tier_pool():
    """Send paths call maybe_brand_email_body → a tier lookup on the native
    pool. Mock tests run DB-less; the mock pool's None tier reads as free —
    the same result these tests see against a DB with no user_billing row."""
    from tests.mocks.mock_asyncpg import MockNativePool

    with patch("utils.database_pool.get_native_pool", return_value=MockNativePool()):
        yield

@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials."""
    return GmailOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="test@gmail.com",
    )


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create_response(status_code: int, json_data: dict = None, text: str = ""):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or {}
        mock_resp.text = text or str(json_data)
        return mock_resp

    return _create_response


def create_node(config, credentials):
    """Helper to create a Gmail node with config."""
    node_config = GmailNodeConfig(config=config, credentials=credentials)
    node = GmailNode(
        node_id="test_gmail_node",
        node_type="automation-gmail",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    # Mock the emit method
    node.emit = AsyncMock()
    return node


# ============================================================================
# Message Operations Tests
# ============================================================================


class TestSendOperation:
    """Tests for send email operation."""

    @pytest.mark.asyncio
    async def test_send_email_success(self, mock_credentials, mock_httpx_response):
        """Test successful email send."""
        config = GmailSendConfig(
            to="recipient@example.com", subject="Test Subject", body="<p>Test body</p>"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "msg123", "threadId": "thread123"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "send_email_message"
            assert result["message_id"] == "msg123"
            assert result["to"] == ["recipient@example.com"]

    @pytest.mark.asyncio
    async def test_send_email_with_cc_bcc(self, mock_credentials, mock_httpx_response):
        """Test sending email with CC and BCC."""
        config = GmailSendConfig(
            to="recipient@example.com",
            subject="Test Subject",
            body="<p>Test body</p>",
            cc="cc@example.com",
            bcc="bcc@example.com",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "msg123", "threadId": "thread123"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"


class TestReadOperation:
    """Tests for read emails operation."""

    @pytest.mark.asyncio
    async def test_read_emails_success(self, mock_credentials, mock_httpx_response):
        """Test successful email read."""
        config = GmailReadConfig(max_results=5, include_body=True)
        node = create_node(config, mock_credentials)

        list_response = mock_httpx_response(
            200,
            {
                "messages": [
                    {"id": "msg1", "threadId": "thread1"},
                    {"id": "msg2", "threadId": "thread2"},
                ]
            },
        )

        msg_response = mock_httpx_response(
            200,
            {
                "id": "msg1",
                "threadId": "thread1",
                "snippet": "Test snippet",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "test@gmail.com"},
                        {"name": "Subject", "value": "Test Email"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                    ],
                    "body": {"data": base64.urlsafe_b64encode(b"Test body").decode()},
                },
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                side_effect=[list_response, msg_response, msg_response]
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_emails_from_inbox"
            assert result["email_count"] == 2

    @pytest.mark.asyncio
    async def test_read_emails_with_query(self, mock_credentials, mock_httpx_response):
        """Test reading emails with search query."""
        config = GmailReadConfig(
            query="is:unread from:important@example.com", max_results=10
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"messages": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["query"] == "is:unread from:important@example.com"

    @pytest.mark.asyncio
    async def test_read_emails_max_results_sent_to_api(
        self, mock_credentials, mock_httpx_response
    ):
        """Test that max_results is correctly forwarded as maxResults to the Gmail API."""
        config = GmailReadConfig(max_results=20)
        node = create_node(config, mock_credentials)

        list_response = mock_httpx_response(200, {"messages": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=list_response)
            await node.execute({})

            list_call_params = mock_instance.get.call_args_list[0].kwargs["params"]
            assert list_call_params["maxResults"] == 20

    @pytest.mark.asyncio
    async def test_read_emails_fetch_detail_error_raises(
        self, mock_credentials, mock_httpx_response
    ):
        """Test that a non-200 response from message detail fetch raises ValueError."""
        config = GmailReadConfig(max_results=2)
        node = create_node(config, mock_credentials)

        list_response = mock_httpx_response(
            200, {"messages": [{"id": "msg1", "threadId": "thread1"}]}
        )
        error_response = mock_httpx_response(403, {"error": {"message": "Forbidden"}})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(side_effect=[list_response, error_response])

            with pytest.raises(
                ValueError, match="Gmail API error fetching message msg1"
            ):
                await node.execute({})


class TestGetMessageOperation:
    """Tests for get_message operation."""

    @pytest.mark.asyncio
    async def test_get_message_success(self, mock_credentials, mock_httpx_response):
        """Test getting a specific message."""
        config = GmailGetMessageConfig(message_id="msg123", format="full")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "msg123",
                "threadId": "thread123",
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": "Test snippet",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Subject", "value": "Test"},
                    ],
                    "body": {"data": base64.urlsafe_b64encode(b"Body").decode()},
                },
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_email_message"
            assert result["message_id"] == "msg123"


class TestDeleteMessageOperation:
    """Tests for delete_message operation."""

    @pytest.mark.asyncio
    async def test_delete_message_success(self, mock_credentials, mock_httpx_response):
        """Test permanently deleting a message."""
        config = GmailDeleteMessageConfig(message_id="msg123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(204, None)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "permanently_delete_message"
            assert result["message_id"] == "msg123"


class TestTrashMessageOperation:
    """Tests for trash_message operation."""

    @pytest.mark.asyncio
    async def test_trash_message_success(self, mock_credentials, mock_httpx_response):
        """Test moving a message to trash."""
        config = GmailTrashMessageConfig(message_id="msg123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "msg123", "labelIds": ["TRASH"]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "move_message_to_trash"
            assert "TRASH" in result["labels"]


class TestUntrashMessageOperation:
    """Tests for untrash_message operation."""

    @pytest.mark.asyncio
    async def test_untrash_message_success(self, mock_credentials, mock_httpx_response):
        """Test restoring a message from trash."""
        config = GmailUntrashMessageConfig(message_id="msg123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "msg123", "labelIds": ["INBOX"]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "restore_message_from_trash"


class TestModifyMessageOperation:
    """Tests for modify_message operation."""

    @pytest.mark.asyncio
    async def test_modify_message_add_labels(
        self, mock_credentials, mock_httpx_response
    ):
        """Test adding labels to a message."""
        config = GmailModifyMessageConfig(
            message_id="msg123", add_label_ids="STARRED,IMPORTANT"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "msg123", "labelIds": ["INBOX", "STARRED", "IMPORTANT"]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_message_labels"

    @pytest.mark.asyncio
    async def test_modify_message_remove_labels(
        self, mock_credentials, mock_httpx_response
    ):
        """Test removing labels from a message."""
        config = GmailModifyMessageConfig(
            message_id="msg123", remove_label_ids="UNREAD"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "msg123", "labelIds": ["INBOX"]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"


class TestReplyOperation:
    """Tests for reply operation."""

    @pytest.mark.asyncio
    async def test_reply_success(self, mock_credentials, mock_httpx_response):
        """Test replying to a message."""
        config = GmailReplyConfig(
            message_id="msg123", body="<p>Reply content</p>", reply_all=False
        )
        node = create_node(config, mock_credentials)

        orig_response = mock_httpx_response(
            200,
            {
                "id": "msg123",
                "threadId": "thread123",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "test@gmail.com"},
                        {"name": "Subject", "value": "Original Subject"},
                        {"name": "Message-ID", "value": "<orig123@mail.gmail.com>"},
                    ]
                },
            },
        )

        send_response = mock_httpx_response(
            200, {"id": "reply123", "threadId": "thread123"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=orig_response)
            mock_instance.post = AsyncMock(return_value=send_response)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "reply_to_email_message"
            assert result["in_reply_to"] == "msg123"


class TestForwardOperation:
    """Tests for forward operation."""

    @pytest.mark.asyncio
    async def test_forward_success(self, mock_credentials, mock_httpx_response):
        """Test forwarding a message."""
        config = GmailForwardConfig(
            message_id="msg123", to="forward_to@example.com", additional_message="FYI"
        )
        node = create_node(config, mock_credentials)

        orig_response = mock_httpx_response(
            200,
            {
                "id": "msg123",
                "threadId": "thread123",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "test@gmail.com"},
                        {"name": "Subject", "value": "Original Subject"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(b"Original body").decode()
                    },
                },
            },
        )

        send_response = mock_httpx_response(
            200, {"id": "fwd123", "threadId": "thread456"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=orig_response)
            mock_instance.post = AsyncMock(return_value=send_response)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "forward_email_message"
            assert result["forwarded_from"] == "msg123"
            assert result["to"] == ["forward_to@example.com"]


# ============================================================================
# Draft Operations Tests
# ============================================================================


class TestCreateDraftOperation:
    """Tests for create_draft operation."""

    @pytest.mark.asyncio
    async def test_create_draft_success(self, mock_credentials, mock_httpx_response):
        """Test creating a draft."""
        config = GmailCreateDraftConfig(
            to="recipient@example.com",
            subject="Draft Subject",
            body="<p>Draft body</p>",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "draft123", "message": {"id": "msg123"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_email_draft"
            assert result["draft_id"] == "draft123"


class TestListDraftsOperation:
    """Tests for list_drafts operation."""

    @pytest.mark.asyncio
    async def test_list_drafts_success(self, mock_credentials, mock_httpx_response):
        """Test listing drafts."""
        config = GmailListDraftsConfig(max_results=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "drafts": [
                    {"id": "draft1", "message": {"id": "msg1"}},
                    {"id": "draft2", "message": {"id": "msg2"}},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_email_drafts"
            assert result["draft_count"] == 2


class TestGetDraftOperation:
    """Tests for get_draft operation."""

    @pytest.mark.asyncio
    async def test_get_draft_success(self, mock_credentials, mock_httpx_response):
        """Test getting a specific draft."""
        config = GmailGetDraftConfig(draft_id="draft123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "draft123",
                "message": {
                    "id": "msg123",
                    "snippet": "Draft preview",
                    "payload": {
                        "headers": [
                            {"name": "To", "value": "recipient@example.com"},
                            {"name": "Subject", "value": "Draft Subject"},
                        ],
                        "body": {
                            "data": base64.urlsafe_b64encode(b"Draft body").decode()
                        },
                    },
                },
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_email_draft"
            assert result["draft_id"] == "draft123"


class TestUpdateDraftOperation:
    """Tests for update_draft operation."""

    @pytest.mark.asyncio
    async def test_update_draft_success(self, mock_credentials, mock_httpx_response):
        """Test updating a draft."""
        config = GmailUpdateDraftConfig(
            draft_id="draft123",
            to="new_recipient@example.com",
            subject="Updated Subject",
            body="<p>Updated body</p>",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "draft123", "message": {"id": "msg123"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.put = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_email_draft"


class TestDeleteDraftOperation:
    """Tests for delete_draft operation."""

    @pytest.mark.asyncio
    async def test_delete_draft_success(self, mock_credentials, mock_httpx_response):
        """Test deleting a draft."""
        config = GmailDeleteDraftConfig(draft_id="draft123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(204, None)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_email_draft"
            assert result["draft_id"] == "draft123"


class TestSendDraftOperation:
    """Tests for send_draft operation."""

    @pytest.mark.asyncio
    async def test_send_draft_success(self, mock_credentials, mock_httpx_response):
        """Test sending a draft."""
        config = GmailSendDraftConfig(draft_id="draft123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "msg123", "threadId": "thread123"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "send_email_draft"
            assert result["draft_id"] == "draft123"
            assert result["message_id"] == "msg123"


# ============================================================================
# Label Operations Tests
# ============================================================================


class TestListLabelsOperation:
    """Tests for list_labels operation."""

    @pytest.mark.asyncio
    async def test_list_labels_success(self, mock_credentials, mock_httpx_response):
        """Test listing all labels."""
        config = GmailListLabelsConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "labels": [
                    {"id": "INBOX", "name": "INBOX", "type": "system"},
                    {"id": "SENT", "name": "SENT", "type": "system"},
                    {"id": "Label_1", "name": "Custom Label", "type": "user"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_email_labels"
            assert result["label_count"] == 3


class TestCreateLabelOperation:
    """Tests for create_label operation."""

    @pytest.mark.asyncio
    async def test_create_label_success(self, mock_credentials, mock_httpx_response):
        """Test creating a new label."""
        config = GmailCreateLabelConfig(
            name="My Custom Label",
            label_list_visibility="labelShow",
            message_list_visibility="show",
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "Label_123", "name": "My Custom Label"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_email_label"
            assert result["name"] == "My Custom Label"

    @pytest.mark.asyncio
    async def test_create_label_with_color(self, mock_credentials, mock_httpx_response):
        """Test creating a label with color."""
        config = GmailCreateLabelConfig(
            name="Colored Label", background_color="#4285f4", text_color="#ffffff"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "Label_124", "name": "Colored Label"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"


class TestGetLabelOperation:
    """Tests for get_label operation."""

    @pytest.mark.asyncio
    async def test_get_label_success(self, mock_credentials, mock_httpx_response):
        """Test getting a specific label."""
        config = GmailGetLabelConfig(label_id="Label_123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "Label_123",
                "name": "My Label",
                "type": "user",
                "messagesTotal": 100,
                "messagesUnread": 10,
                "threadsTotal": 50,
                "threadsUnread": 5,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_email_label"
            assert result["messages_total"] == 100
            assert result["messages_unread"] == 10


class TestUpdateLabelOperation:
    """Tests for update_label operation."""

    @pytest.mark.asyncio
    async def test_update_label_success(self, mock_credentials, mock_httpx_response):
        """Test updating a label."""
        config = GmailUpdateLabelConfig(label_id="Label_123", name="Renamed Label")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"id": "Label_123", "name": "Renamed Label"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_email_label"
            assert result["name"] == "Renamed Label"


class TestDeleteLabelOperation:
    """Tests for delete_label operation."""

    @pytest.mark.asyncio
    async def test_delete_label_success(self, mock_credentials, mock_httpx_response):
        """Test deleting a label."""
        config = GmailDeleteLabelConfig(label_id="Label_123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(204, None)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_email_label"
            assert result["label_id"] == "Label_123"


# ============================================================================
# Thread Operations Tests
# ============================================================================


class TestListThreadsOperation:
    """Tests for list_threads operation."""

    @pytest.mark.asyncio
    async def test_list_threads_success(self, mock_credentials, mock_httpx_response):
        """Test listing threads."""
        config = GmailListThreadsConfig(max_results=10)
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "threads": [
                    {"id": "thread1", "snippet": "First thread"},
                    {"id": "thread2", "snippet": "Second thread"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_email_threads"
            assert result["thread_count"] == 2


class TestGetThreadOperation:
    """Tests for get_thread operation."""

    @pytest.mark.asyncio
    async def test_get_thread_success(self, mock_credentials, mock_httpx_response):
        """Test getting a specific thread."""
        config = GmailGetThreadConfig(thread_id="thread123", format="full")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "id": "thread123",
                "messages": [
                    {
                        "id": "msg1",
                        "snippet": "First message",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "sender@example.com"},
                                {"name": "Subject", "value": "Thread Subject"},
                            ],
                            "body": {
                                "data": base64.urlsafe_b64encode(b"Body 1").decode()
                            },
                        },
                    },
                    {
                        "id": "msg2",
                        "snippet": "Reply message",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "test@gmail.com"},
                                {"name": "Subject", "value": "Re: Thread Subject"},
                            ],
                            "body": {
                                "data": base64.urlsafe_b64encode(b"Body 2").decode()
                            },
                        },
                    },
                ],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_email_thread"
            assert result["thread_id"] == "thread123"
            assert result["message_count"] == 2


class TestTrashThreadOperation:
    """Tests for trash_thread operation."""

    @pytest.mark.asyncio
    async def test_trash_thread_success(self, mock_credentials, mock_httpx_response):
        """Test moving a thread to trash."""
        config = GmailTrashThreadConfig(thread_id="thread123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"id": "thread123"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "move_thread_to_trash"


class TestUntrashThreadOperation:
    """Tests for untrash_thread operation."""

    @pytest.mark.asyncio
    async def test_untrash_thread_success(self, mock_credentials, mock_httpx_response):
        """Test restoring a thread from trash."""
        config = GmailUntrashThreadConfig(thread_id="thread123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"id": "thread123"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "restore_thread_from_trash"


class TestModifyThreadOperation:
    """Tests for modify_thread operation."""

    @pytest.mark.asyncio
    async def test_modify_thread_success(self, mock_credentials, mock_httpx_response):
        """Test modifying thread labels."""
        config = GmailModifyThreadConfig(
            thread_id="thread123", add_label_ids="STARRED", remove_label_ids="UNREAD"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"id": "thread123"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_thread_labels"


class TestDeleteThreadOperation:
    """Tests for delete_thread operation."""

    @pytest.mark.asyncio
    async def test_delete_thread_success(self, mock_credentials, mock_httpx_response):
        """Test permanently deleting a thread."""
        config = GmailDeleteThreadConfig(thread_id="thread123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(204, None)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "permanently_delete_thread"
            assert result["thread_id"] == "thread123"


# ============================================================================
# Profile Operations Tests
# ============================================================================


class TestGetProfileOperation:
    """Tests for get_profile operation."""

    @pytest.mark.asyncio
    async def test_get_profile_success(self, mock_credentials, mock_httpx_response):
        """Test getting user profile."""
        config = GmailGetProfileConfig()
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "emailAddress": "test@gmail.com",
                "messagesTotal": 1000,
                "threadsTotal": 500,
                "historyId": "12345",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_user_profile"
            assert result["email_address"] == "test@gmail.com"
            assert result["messages_total"] == 1000


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_missing_credentials(self, mock_httpx_response):
        """Test error when credentials are missing."""
        config = GmailSendConfig(
            to="recipient@example.com", subject="Test", body="Test"
        )
        node_config = GmailNodeConfig(config=config, credentials=None)
        node = GmailNode(
            node_id="test_node",
            node_type="automation-gmail",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )
        node.emit = AsyncMock()

        with pytest.raises(ValueError, match="credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_error(self, mock_credentials, mock_httpx_response):
        """Test handling of API errors."""
        config = GmailSendConfig(
            to="recipient@example.com", subject="Test", body="Test"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(400, {"error": {"message": "Bad Request"}})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ValueError, match="Gmail API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_config(self):
        """Test error when config is invalid."""
        # Test with missing required field
        with pytest.raises(Exception):
            GmailSendConfig(subject="Test")  # Missing 'to' and 'body'


# ============================================================================
# Dynamic Options Tests
# ============================================================================


class TestDynamicOptions:
    """Tests for dynamic field options loading."""

    @pytest.mark.asyncio
    async def test_load_label_options(self, mock_httpx_response):
        """Test loading label options for dropdowns."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        mock_response = mock_httpx_response(
            200,
            {
                "labels": [
                    {"id": "INBOX", "name": "Inbox"},
                    {"id": "STARRED", "name": "Starred"},
                    {"id": "Label_1", "name": "Custom"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await GmailNode.load_field_options(
                "label_ids", credential_data, None
            )

            assert "options" in result
            assert len(result["options"]) == 3
            assert result["options"][0]["value"] == "INBOX"


# ============================================================================
# Schema Generation Tests
# ============================================================================


class TestSchemaGeneration:
    """Test JSON schema generation."""

    def test_config_schema_generated(self):
        """Test that config schema is properly generated."""
        schema = GmailNode.get_config_schema()

        assert schema is not None
        assert "$defs" in schema
        # Should have 27 operation configs + 1 credential
        assert len(schema["$defs"]) >= 27

    def test_config_model_defined(self):
        """Test that config model is defined."""
        model = GmailNode.get_config_model()

        assert model is not None
        assert model == GmailNodeConfig

    def test_all_operations_in_schema(self):
        """Test that all 27 operations are defined in schema."""
        schema = GmailNode.get_config_schema()
        defs = schema.get("$defs", {})

        # Check for all operation config classes
        expected_configs = [
            # Messages
            "GmailSendConfig",
            "GmailReadConfig",
            "GmailGetMessageConfig",
            "GmailDeleteMessageConfig",
            "GmailTrashMessageConfig",
            "GmailUntrashMessageConfig",
            "GmailModifyMessageConfig",
            "GmailReplyConfig",
            "GmailForwardConfig",
            # Drafts
            "GmailCreateDraftConfig",
            "GmailListDraftsConfig",
            "GmailGetDraftConfig",
            "GmailUpdateDraftConfig",
            "GmailDeleteDraftConfig",
            "GmailSendDraftConfig",
            # Labels
            "GmailListLabelsConfig",
            "GmailCreateLabelConfig",
            "GmailGetLabelConfig",
            "GmailUpdateLabelConfig",
            "GmailDeleteLabelConfig",
            # Threads
            "GmailListThreadsConfig",
            "GmailGetThreadConfig",
            "GmailTrashThreadConfig",
            "GmailUntrashThreadConfig",
            "GmailModifyThreadConfig",
            "GmailDeleteThreadConfig",
            # Profile
            "GmailGetProfileConfig",
        ]

        for config_name in expected_configs:
            assert config_name in defs, f"Missing config: {config_name}"


# ============================================================================
# Attachment Operations Tests (content-extraction integration)
# ============================================================================


def _pdf_bytes(text: str = "Invoice #9 total $55.00") -> bytes:
    from tests.mocks.pdf_fixtures import text_pdf

    return text_pdf(text)


def _payload_with_attachment() -> dict:
    return {
        "headers": [
            {"name": "From", "value": "vendor@example.com"},
            {"name": "Subject", "value": "Invoice"},
        ],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b"see attached").decode()}},
            {"mimeType": "application/pdf", "filename": "inv.pdf",
             "body": {"attachmentId": "ATT1", "size": 1400}},
        ],
    }


class TestAttachmentOperations:
    """fetch_email_message inlining + fetch_email_attachment op.

    Contracts: single-message fetch auto-inlines extracted text (free path);
    bulk inbox fetch stays metadata-only; the explicit op extracts by
    filename or id and errors with the available filenames on a miss.
    """

    @pytest.mark.asyncio
    async def test_get_message_inlines_attachment_text(self, mock_credentials, mock_httpx_response):
        node = create_node(GmailGetMessageConfig(message_id="msg1"), mock_credentials)
        pdf = _pdf_bytes()
        msg_resp = mock_httpx_response(200, {
            "id": "msg1", "threadId": "t1", "snippet": "s", "labelIds": [],
            "payload": _payload_with_attachment(),
        })
        att_resp = mock_httpx_response(200, {"data": base64.urlsafe_b64encode(pdf).decode()})

        with patch("httpx.AsyncClient") as mock_client:
            inst = mock_client.return_value.__aenter__.return_value
            inst.get = AsyncMock(side_effect=[msg_resp, att_resp])
            result = await node.execute({})

        att = result["attachments"][0]
        assert att["filename"] == "inv.pdf" and att["attachment_id"] == "ATT1"
        assert "$55.00" in att["text"]
        assert att["extractable"] is True

    @pytest.mark.asyncio
    async def test_inbox_fetch_is_metadata_only(self, mock_credentials, mock_httpx_response):
        node = create_node(GmailReadConfig(max_results=1, include_body=True), mock_credentials)
        list_resp = mock_httpx_response(200, {"messages": [{"id": "msg1", "threadId": "t1"}]})
        msg_resp = mock_httpx_response(200, {
            "id": "msg1", "threadId": "t1", "snippet": "s", "labelIds": [],
            "payload": _payload_with_attachment(),
        })

        with patch("httpx.AsyncClient") as mock_client:
            inst = mock_client.return_value.__aenter__.return_value
            inst.get = AsyncMock(side_effect=[list_resp, msg_resp])
            result = await node.execute({})

        att = result["emails"][0]["attachments"][0]
        assert att["filename"] == "inv.pdf"
        assert "text" not in att  # bulk path never inlines content

    @pytest.mark.asyncio
    async def test_fetch_attachment_by_filename_extracts(self, mock_credentials, mock_httpx_response):
        node = create_node(
            GmailGetAttachmentConfig(message_id="msg1", filename="inv.pdf"), mock_credentials
        )
        msg_resp = mock_httpx_response(200, {"payload": _payload_with_attachment()})
        att_resp = mock_httpx_response(
            200, {"data": base64.urlsafe_b64encode(_pdf_bytes()).decode()}
        )

        with patch("httpx.AsyncClient") as mock_client:
            inst = mock_client.return_value.__aenter__.return_value
            inst.get = AsyncMock(side_effect=[msg_resp, att_resp])
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["extraction_method"] == "document"
        assert "$55.00" in result["text"]

    @pytest.mark.asyncio
    async def test_fetch_attachment_miss_lists_available(self, mock_credentials, mock_httpx_response):
        node = create_node(
            GmailGetAttachmentConfig(message_id="msg1", filename="nope.pdf"), mock_credentials
        )
        msg_resp = mock_httpx_response(200, {"payload": _payload_with_attachment()})

        with patch("httpx.AsyncClient") as mock_client:
            inst = mock_client.return_value.__aenter__.return_value
            inst.get = AsyncMock(side_effect=[msg_resp])
            with pytest.raises(ValueError, match="Available: inv.pdf"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_fetch_attachment_save_as_resource(self, mock_credentials, mock_httpx_response):
        node = create_node(
            GmailGetAttachmentConfig(message_id="msg1", filename="inv.pdf", mode="save_as_resource"),
            mock_credentials,
        )
        node.user_id = "00000000-0000-4000-8000-000000000001"
        msg_resp = mock_httpx_response(200, {"payload": _payload_with_attachment()})
        att_resp = mock_httpx_response(
            200, {"data": base64.urlsafe_b64encode(_pdf_bytes()).decode()}
        )
        ref = {"resource_id": "r1", "name": "inv.pdf", "mime_type": "application/pdf",
               "size_bytes": 1400, "download_url": "https://r2/x"}

        with patch("httpx.AsyncClient") as mock_client, \
             patch("utils.resource_store.create_resource_from_bytes",
                   new_callable=AsyncMock, return_value=ref) as create_res:
            inst = mock_client.return_value.__aenter__.return_value
            inst.get = AsyncMock(side_effect=[msg_resp, att_resp])
            result = await node.execute({})

        assert result["resource"] == ref
        assert create_res.call_args.kwargs["filename"] == "inv.pdf"
        assert create_res.call_args.kwargs["content_type"] == "application/pdf"
