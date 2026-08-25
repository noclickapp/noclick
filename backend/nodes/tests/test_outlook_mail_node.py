"""
Mock tests for Outlook Mail workflow node.

Tests all 65 Outlook operations with mocked Microsoft Graph API responses.
Does not require actual Microsoft OAuth credentials.

Operations covered:
- Mail: 24 operations (send, read, reply, forward, drafts, attachments, folders, MIME, etc.)
- Calendar: 17 operations (events, meetings, reminders, schedules, etc.)
- Contacts: 10 operations (CRUD contacts and folders)
- Categories: 5 operations (manage email categories)
- Message Rules: 5 operations (inbox automation rules)
- Settings: 4 operations (mailbox settings, auto-reply, etc.)
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Import the node and config classes - ALL 65 operations
from nodes.outlook_mail_node import (
    OutlookMailNode,
    OutlookNodeConfig,
    OutlookOAuthCredential,
    # Original operations (4)
    OutlookSendConfig,
    OutlookReadConfig,
    OutlookReplyConfig,
    OutlookForwardConfig,
    # Basic operations (10)
    OutlookGetMessageConfig,
    OutlookMarkReadConfig,
    OutlookDeleteConfig,
    OutlookMoveConfig,
    OutlookCreateDraftConfig,
    OutlookListFoldersConfig,
    OutlookCreateFolderConfig,
    OutlookGetAttachmentsConfig,
    OutlookGetMailboxSettingsConfig,
    OutlookUpdateAutoReplyConfig,
    # Advanced message operations (6)
    OutlookCopyMessageConfig,
    OutlookUpdateMessageConfig,
    OutlookSendDraftConfig,
    OutlookCreateReplyDraftConfig,
    OutlookCreateReplyAllDraftConfig,
    OutlookCreateForwardDraftConfig,
    # Attachment operations (2)
    OutlookAddAttachmentConfig,
    OutlookDeleteAttachmentConfig,
    # Folder operations (4)
    OutlookUpdateFolderConfig,
    OutlookDeleteFolderConfig,
    OutlookMoveFolderConfig,
    OutlookCopyFolderConfig,
    # Message rules (5)
    OutlookListMessageRulesConfig,
    OutlookGetMessageRuleConfig,
    OutlookCreateMessageRuleConfig,
    OutlookUpdateMessageRuleConfig,
    OutlookDeleteMessageRuleConfig,
    # Categories (5)
    OutlookListCategoriesConfig,
    OutlookGetCategoryConfig,
    OutlookCreateCategoryConfig,
    OutlookUpdateCategoryConfig,
    OutlookDeleteCategoryConfig,
    # MIME operations (2)
    OutlookGetMimeContentConfig,
    OutlookSendMimeConfig,
    # Calendar operations (17)
    OutlookListEventsConfig,
    OutlookCreateEventConfig,
    OutlookGetEventConfig,
    OutlookUpdateEventConfig,
    OutlookDeleteEventConfig,
    OutlookCancelEventConfig,
    OutlookAcceptEventConfig,
    OutlookDeclineEventConfig,
    OutlookTentativelyAcceptEventConfig,
    OutlookDismissReminderConfig,
    OutlookSnoozeReminderConfig,
    OutlookFindMeetingTimesConfig,
    OutlookGetScheduleConfig,
    OutlookListEventInstancesConfig,
    OutlookListCalendarsConfig,
    OutlookListCalendarGroupsConfig,
    OutlookGetRoomListsConfig,
    # Contacts operations (10)
    OutlookListContactsConfig,
    OutlookCreateContactConfig,
    OutlookGetContactConfig,
    OutlookUpdateContactConfig,
    OutlookDeleteContactConfig,
    OutlookListContactFoldersConfig,
    OutlookCreateContactFolderConfig,
    OutlookGetContactFolderConfig,
    OutlookUpdateContactFolderConfig,
    OutlookDeleteContactFolderConfig,
)


# Mock credential data
MOCK_CREDENTIALS = OutlookOAuthCredential(
    access_token="mock_access_token_12345",
    refresh_token="mock_refresh_token_67890",
    expires_at="2099-12-31T23:59:59Z",
    email="test@outlook.com",
)



@pytest.fixture(autouse=True)
def _branding_tier_pool():
    """Send paths call maybe_brand_email_body → a tier lookup on the native
    pool. Mock tests run DB-less; the mock pool's None tier reads as free —
    the same result these tests see against a DB with no user_billing row."""
    from tests.mocks.mock_asyncpg import MockNativePool

    with patch("utils.database_pool.get_native_pool", return_value=MockNativePool()):
        yield

def create_node(config) -> OutlookMailNode:
    """Create an OutlookMailNode instance with mock credentials."""
    node_config = OutlookNodeConfig(config=config, credentials=MOCK_CREDENTIALS)
    node = OutlookMailNode(
        node_id="test-outlook-node",
        node_type="automation-outlook",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


def create_mock_response(
    status_code: int, json_data: dict = None, content: bytes = None
):
    """Create a mock httpx response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.content = content or b'{"success": true}'
    mock_response.json.return_value = json_data or {}
    mock_response.text = str(json_data) if json_data else ""
    return mock_response


# ============================================================================
# Send Email Tests
# ============================================================================


class TestSendEmail:
    """Test send email operation."""

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        """Test successful email sending."""
        config = OutlookSendConfig(
            to="recipient@example.com",
            subject="Test Subject",
            body="<p>Test body content</p>",
            save_to_sent=True,
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "send_email_message"
        assert result["to"] == "recipient@example.com"
        assert result["subject"] == "Test Subject"

    @pytest.mark.asyncio
    async def test_send_email_with_cc_bcc(self):
        """Test sending email with CC and BCC."""
        config = OutlookSendConfig(
            to="recipient@example.com",
            subject="Test Subject",
            body="Test body",
            cc="cc@example.com",
            bcc="bcc@example.com",
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_send_email_api_error(self):
        """Test handling of API error during send."""
        config = OutlookSendConfig(
            to="recipient@example.com", subject="Test", body="Test"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            400, {"error": {"message": "Invalid recipient"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})


# ============================================================================
# Read Emails Tests
# ============================================================================


class TestReadEmails:
    """Test read emails operation."""

    @pytest.mark.asyncio
    async def test_read_emails_success(self):
        """Test successful email reading from inbox."""
        config = OutlookReadConfig(folder="inbox", max_results=10, include_body="true")
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "msg-1",
                        "subject": "Test Email 1",
                        "from": {
                            "emailAddress": {
                                "address": "sender@example.com",
                                "name": "Sender",
                            }
                        },
                        "toRecipients": [
                            {"emailAddress": {"address": "me@example.com"}}
                        ],
                        "ccRecipients": [],
                        "receivedDateTime": "2024-01-15T10:30:00Z",
                        "isRead": False,
                        "importance": "normal",
                        "hasAttachments": False,
                        "bodyPreview": "This is a test...",
                        "body": {
                            "content": "<p>This is a test email</p>",
                            "contentType": "html",
                        },
                    },
                    {
                        "id": "msg-2",
                        "subject": "Test Email 2",
                        "from": {
                            "emailAddress": {
                                "address": "other@example.com",
                                "name": "Other",
                            }
                        },
                        "toRecipients": [
                            {"emailAddress": {"address": "me@example.com"}}
                        ],
                        "ccRecipients": [],
                        "receivedDateTime": "2024-01-14T09:00:00Z",
                        "isRead": True,
                        "importance": "high",
                        "hasAttachments": True,
                        "bodyPreview": "Another test...",
                        "body": {
                            "content": "<p>Another test email</p>",
                            "contentType": "html",
                        },
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "read_inbox_emails"
        assert result["email_count"] == 2
        assert len(result["emails"]) == 2
        assert result["emails"][0]["subject"] == "Test Email 1"
        assert result["emails"][1]["is_read"] is True

        # Verify OData query params are in the URL with literal $ (not %24-encoded)
        call_args = mock_client.return_value.get.call_args
        request_url = call_args[0][0]
        assert "$top=10" in request_url, f"Expected $top in URL, got: {request_url}"
        assert "$select=" in request_url, f"Expected $select in URL, got: {request_url}"
        assert (
            "$orderby=" in request_url
        ), f"Expected $orderby in URL, got: {request_url}"
        assert (
            "%24" not in request_url
        ), f"OData params should not be percent-encoded: {request_url}"

    @pytest.mark.asyncio
    async def test_read_emails_with_filter(self):
        """Test reading emails with filter query."""
        config = OutlookReadConfig(
            folder="inbox", filter_query="isRead eq false", max_results=5
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {"value": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["filter"] == "isRead eq false"

        # Verify $filter param is in URL with literal $
        call_args = mock_client.return_value.get.call_args
        request_url = call_args[0][0]
        assert "$filter=" in request_url, f"Expected $filter in URL, got: {request_url}"
        assert (
            "%24" not in request_url
        ), f"OData params should not be percent-encoded: {request_url}"


# ============================================================================
# Reply to Email Tests
# ============================================================================


class TestReplyEmail:
    """Test reply to email operation."""

    @pytest.mark.asyncio
    async def test_reply_email_success(self):
        """Test successful reply to email."""
        config = OutlookReplyConfig(
            message_id="msg-12345", body="<p>This is my reply</p>", reply_all=False
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "reply_to_email_message"
        assert result["message_id"] == "msg-12345"
        assert result["reply_all"] is False

    @pytest.mark.asyncio
    async def test_reply_all_email(self):
        """Test reply all to email."""
        config = OutlookReplyConfig(
            message_id="msg-12345", body="Reply to all", reply_all=True
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["reply_all"] is True


# ============================================================================
# Forward Email Tests
# ============================================================================


class TestForwardEmail:
    """Test forward email operation."""

    @pytest.mark.asyncio
    async def test_forward_email_success(self):
        """Test successful email forwarding."""
        config = OutlookForwardConfig(
            message_id="msg-12345",
            to="forward@example.com",
            comment="Please see the forwarded email",
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "forward_email_message"
        assert result["forwarded_to"] == "forward@example.com"


# ============================================================================
# Get Message Tests
# ============================================================================


class TestGetMessage:
    """Test get single message operation."""

    @pytest.mark.asyncio
    async def test_get_message_success(self):
        """Test getting a specific message by ID."""
        config = OutlookGetMessageConfig(
            message_id="msg-12345", include_attachments=False
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "id": "msg-12345",
                "subject": "Test Subject",
                "from": {
                    "emailAddress": {"address": "sender@example.com", "name": "Sender"}
                },
                "toRecipients": [{"emailAddress": {"address": "me@example.com"}}],
                "ccRecipients": [],
                "receivedDateTime": "2024-01-15T10:30:00Z",
                "sentDateTime": "2024-01-15T10:29:00Z",
                "isRead": True,
                "importance": "normal",
                "hasAttachments": False,
                "body": {"content": "<p>Message body</p>", "contentType": "html"},
                "bodyPreview": "Message body",
                "conversationId": "conv-123",
                "parentFolderId": "inbox",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_email_message"
        assert result["email"]["id"] == "msg-12345"
        assert result["email"]["subject"] == "Test Subject"

    @pytest.mark.asyncio
    async def test_get_message_with_attachments(self):
        """hasAttachments → a second listing GET (metadata $select, no $expand)
        → shared-record shape + inline-extracted text for small documents."""
        import base64 as b64

        from tests.mocks.pdf_fixtures import text_pdf

        config = OutlookGetMessageConfig(
            message_id="msg-12345", include_attachments=True
        )
        node = create_node(config)

        message_resp = create_mock_response(
            200,
            {
                "id": "msg-12345",
                "subject": "Test with Attachments",
                "from": {
                    "emailAddress": {"address": "sender@example.com", "name": "Sender"}
                },
                "toRecipients": [],
                "ccRecipients": [],
                "receivedDateTime": "2024-01-15T10:30:00Z",
                "isRead": True,
                "importance": "normal",
                "hasAttachments": True,
                "body": {"content": "Body", "contentType": "text"},
                "bodyPreview": "Body",
            },
        )
        listing_resp = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "att-1",
                        "name": "file.pdf",
                        "contentType": "application/pdf",
                        "size": 1024,
                        "isInline": False,
                    }
                ]
            },
        )
        # inline enrichment fetches the single attachment via _graph_call
        # (client.request), which returns contentBytes
        content_resp = create_mock_response(
            200,
            {
                "id": "att-1",
                "contentBytes": b64.b64encode(text_pdf("Outlook invoice $31.00")).decode(),
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(
                side_effect=[message_resp, listing_resp]
            )
            mock_client.return_value.request = AsyncMock(return_value=content_resp)

            result = await node.execute({})

        assert result["status"] == "success"
        atts = result["email"]["attachments"]
        assert len(atts) == 1
        # legacy Graph keys + shared record keys coexist
        assert atts[0]["id"] == "att-1" and atts[0]["attachment_id"] == "att-1"
        assert atts[0]["source"] == "outlook" and atts[0]["extractable"] is True
        # natural surfacing: small text-layer doc inlined its text
        assert "$31.00" in atts[0]["text"]
        assert len(result["email"]["attachments"]) == 1


# ============================================================================
# Mark Read/Unread Tests
# ============================================================================


class TestMarkRead:
    """Test mark message as read/unread operation."""

    @pytest.mark.asyncio
    async def test_mark_as_read(self):
        """Test marking message as read."""
        config = OutlookMarkReadConfig(message_id="msg-12345", is_read=True)
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "msg-12345", "isRead": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "mark_email_as_read_unread"
        assert result["is_read"] is True

    @pytest.mark.asyncio
    async def test_mark_as_unread(self):
        """Test marking message as unread."""
        config = OutlookMarkReadConfig(message_id="msg-12345", is_read=False)
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "msg-12345", "isRead": False})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["is_read"] is False


# ============================================================================
# Delete Message Tests
# ============================================================================


class TestDeleteMessage:
    """Test delete message operation."""

    @pytest.mark.asyncio
    async def test_delete_to_trash(self):
        """Test moving message to deleted items (soft delete)."""
        config = OutlookDeleteConfig(message_id="msg-12345", permanent=False)
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "msg-12345-moved"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_email_message"
        assert result["permanent"] is False

    @pytest.mark.asyncio
    async def test_permanent_delete(self):
        """Test permanently deleting message."""
        config = OutlookDeleteConfig(message_id="msg-12345", permanent=True)
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["permanent"] is True


# ============================================================================
# Move Message Tests
# ============================================================================


class TestMoveMessage:
    """Test move message operation."""

    @pytest.mark.asyncio
    async def test_move_message_success(self):
        """Test moving message to another folder."""
        config = OutlookMoveConfig(message_id="msg-12345", destination_folder="archive")
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "msg-12345-new"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "move_email_to_folder"
        assert result["destination_folder"] == "archive"


# ============================================================================
# Create Draft Tests
# ============================================================================


class TestCreateDraft:
    """Test create draft operation."""

    @pytest.mark.asyncio
    async def test_create_draft_success(self):
        """Test creating a draft email."""
        config = OutlookCreateDraftConfig(
            to="recipient@example.com",
            subject="Draft Subject",
            body="<p>Draft body</p>",
            cc="cc@example.com",
        )
        node = create_node(config)

        mock_response = create_mock_response(201, {"id": "draft-12345"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_email_draft"
        assert result["draft_id"] == "draft-12345"


# ============================================================================
# List Folders Tests
# ============================================================================


class TestListFolders:
    """Test list mail folders operation."""

    @pytest.mark.asyncio
    async def test_list_folders_success(self):
        """Test listing mail folders."""
        config = OutlookListFoldersConfig(include_child_folders=False)
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "folder-inbox",
                        "displayName": "Inbox",
                        "parentFolderId": "root",
                        "childFolderCount": 2,
                        "totalItemCount": 150,
                        "unreadItemCount": 5,
                    },
                    {
                        "id": "folder-sent",
                        "displayName": "Sent Items",
                        "parentFolderId": "root",
                        "childFolderCount": 0,
                        "totalItemCount": 200,
                        "unreadItemCount": 0,
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_mail_folders"
        assert result["folder_count"] == 2
        assert result["folders"][0]["name"] == "Inbox"

    @pytest.mark.asyncio
    async def test_list_folders_with_children(self):
        """Test listing folders with child folders expanded."""
        config = OutlookListFoldersConfig(include_child_folders=True)
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "folder-inbox",
                        "displayName": "Inbox",
                        "parentFolderId": "root",
                        "childFolderCount": 1,
                        "totalItemCount": 100,
                        "unreadItemCount": 5,
                        "childFolders": [
                            {
                                "id": "folder-subfolder",
                                "displayName": "Work",
                                "parentFolderId": "folder-inbox",
                                "childFolderCount": 0,
                                "totalItemCount": 20,
                                "unreadItemCount": 2,
                            }
                        ],
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert "child_folders" in result["folders"][0]


# ============================================================================
# Create Folder Tests
# ============================================================================


class TestCreateFolder:
    """Test create folder operation."""

    @pytest.mark.asyncio
    async def test_create_folder_success(self):
        """Test creating a new mail folder."""
        config = OutlookCreateFolderConfig(
            folder_name="My New Folder", parent_folder="inbox"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            201, {"id": "new-folder-id", "displayName": "My New Folder"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_mail_folder"
        assert result["folder_name"] == "My New Folder"


# ============================================================================
# Get Attachments Tests
# ============================================================================


class TestGetAttachments:
    """Test get attachments operation."""

    @pytest.mark.asyncio
    async def test_get_attachments_success(self):
        """Test getting attachments from a message."""
        config = OutlookGetAttachmentsConfig(
            message_id="msg-12345", include_content=False
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "att-1",
                        "name": "document.pdf",
                        "contentType": "application/pdf",
                        "size": 102400,
                        "isInline": False,
                        "@odata.type": "#microsoft.graph.fileAttachment",
                    },
                    {
                        "id": "att-2",
                        "name": "image.png",
                        "contentType": "image/png",
                        "size": 51200,
                        "isInline": True,
                        "@odata.type": "#microsoft.graph.fileAttachment",
                    },
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_email_attachments"
        assert result["attachment_count"] == 2
        assert result["attachments"][0]["name"] == "document.pdf"

    @pytest.mark.asyncio
    async def test_get_attachments_with_content(self):
        """Test getting attachments with base64 content."""
        config = OutlookGetAttachmentsConfig(
            message_id="msg-12345", include_content=True
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "att-1",
                        "name": "test.txt",
                        "contentType": "text/plain",
                        "size": 100,
                        "isInline": False,
                        "contentBytes": "VGVzdCBjb250ZW50",  # "Test content" base64
                        "@odata.type": "#microsoft.graph.fileAttachment",
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert "content_base64" in result["attachments"][0]


# ============================================================================
# Get Mailbox Settings Tests
# ============================================================================


class TestGetMailboxSettings:
    """Test get mailbox settings operation."""

    @pytest.mark.asyncio
    async def test_get_mailbox_settings_success(self):
        """Test getting mailbox settings."""
        config = OutlookGetMailboxSettingsConfig()
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "timeZone": "Pacific Standard Time",
                "language": {"locale": "en-US"},
                "dateFormat": "MM/dd/yyyy",
                "timeFormat": "h:mm tt",
                "archiveFolder": "archive-folder-id",
                "automaticRepliesSetting": {
                    "status": "disabled",
                    "externalAudience": "all",
                    "internalReplyMessage": "",
                    "externalReplyMessage": "",
                    "scheduledStartDateTime": {"dateTime": None},
                    "scheduledEndDateTime": {"dateTime": None},
                },
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_mailbox_settings"
        assert result["settings"]["timezone"] == "Pacific Standard Time"
        assert result["settings"]["auto_reply"]["status"] == "disabled"


# ============================================================================
# Update Auto-Reply Tests
# ============================================================================


class TestUpdateAutoReply:
    """Test update auto-reply settings operation."""

    @pytest.mark.asyncio
    async def test_enable_auto_reply(self):
        """Test enabling auto-reply."""
        config = OutlookUpdateAutoReplyConfig(
            enabled=True,
            internal_message="I am out of the office.",
            external_message="I am currently unavailable.",
            external_audience="all",
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_auto_reply_settings"
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_disable_auto_reply(self):
        """Test disabling auto-reply."""
        config = OutlookUpdateAutoReplyConfig(enabled=False)
        node = create_node(config)

        mock_response = create_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_scheduled_auto_reply(self):
        """Test setting scheduled auto-reply."""
        config = OutlookUpdateAutoReplyConfig(
            enabled=True,
            internal_message="Out of office from Jan 1 to Jan 15",
            external_message="Out of office from Jan 1 to Jan 15",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-15T00:00:00Z",
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["scheduled"] is True


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = OutlookSendConfig(to="test@example.com", subject="Test", body="Test")
        node_config = OutlookNodeConfig(config=config, credentials=None)
        node = OutlookMailNode(
            node_id="test-node",
            node_type="automation-outlook",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_401_unauthorized(self):
        """Test handling of 401 unauthorized error."""
        config = OutlookReadConfig(folder="inbox")
        node = create_node(config)

        mock_response = create_mock_response(
            401, {"error": {"message": "Access token has expired"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_api_404_not_found(self):
        """Test handling of 404 not found error."""
        config = OutlookGetMessageConfig(message_id="nonexistent-msg")
        node = create_node(config)

        mock_response = create_mock_response(
            404, {"error": {"message": "Resource not found"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})


# ============================================================================
# Timing Tests
# ============================================================================


class TestTiming:
    """Test timing information in responses."""

    @pytest.mark.asyncio
    async def test_timing_included(self):
        """Test that timing information is included in response."""
        config = OutlookReadConfig(folder="inbox", max_results=1)
        node = create_node(config)

        mock_response = create_mock_response(200, {"value": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert "timing_ms" in result
        assert result["timing_ms"] >= 0


# ============================================================================
# Template Resolution Tests
# ============================================================================


class TestTemplateResolution:
    """Test template variable resolution in inputs."""

    @pytest.mark.asyncio
    async def test_template_in_recipient(self):
        """Test template resolution in recipient field."""
        config = OutlookSendConfig(
            to="{{input.prev_node.email}}", subject="Test", body="Test body"
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({"prev_node": {"email": "dynamic@example.com"}})

        assert result["status"] == "success"
        assert result["to"] == "dynamic@example.com"

    @pytest.mark.asyncio
    async def test_template_in_body(self):
        """Test template resolution in email body."""
        config = OutlookSendConfig(
            to="test@example.com",
            subject="Hello {{input.prev_node.name}}",
            body="Dear {{input.prev_node.name}}, your order {{input.prev_node.order_id}} is ready.",
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute(
                {"prev_node": {"name": "John", "order_id": "12345"}}
            )

        assert result["status"] == "success"
        assert result["subject"] == "Hello John"


# ============================================================================
# Advanced Message Operations Tests
# ============================================================================


class TestCopyMessage:
    """Test copy message operation."""

    @pytest.mark.asyncio
    async def test_copy_message_success(self):
        """Test successfully copying a message to another folder."""
        config = OutlookCopyMessageConfig(
            message_id="msg-12345", destination_folder="archive"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "msg-12345-copy"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "copy_message_to_folder"
        assert result["destination_folder"] == "archive"

    @pytest.mark.asyncio
    async def test_copy_message_error(self):
        """Test error handling when copying fails."""
        config = OutlookCopyMessageConfig(
            message_id="msg-12345", destination_folder="archive"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            404, {"error": {"message": "Message not found"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Microsoft Graph API error"):
                await node.execute({})


class TestUpdateMessage:
    """Test update message operation."""

    @pytest.mark.asyncio
    async def test_update_message_subject(self):
        """Test updating message subject."""
        config = OutlookUpdateMessageConfig(
            message_id="msg-12345", subject="Updated Subject", importance="high"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "msg-12345", "subject": "Updated Subject", "importance": "high"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_email_message_properties"
        assert result["subject"] == "Updated Subject"

    @pytest.mark.asyncio
    async def test_update_message_categories(self):
        """Test updating message categories."""
        config = OutlookUpdateMessageConfig(
            message_id="msg-12345", categories="Red category, Blue category"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "msg-12345", "categories": ["Red category", "Blue category"]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"


class TestSendDraft:
    """Test send draft operation."""

    @pytest.mark.asyncio
    async def test_send_draft_success(self):
        """Test sending an existing draft."""
        config = OutlookSendDraftConfig(message_id="draft-12345")
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "send_email_draft"
        assert result["draft_id"] == "draft-12345"


class TestCreateReplyDraft:
    """Test create reply draft operation."""

    @pytest.mark.asyncio
    async def test_create_reply_draft_success(self):
        """Test creating a reply draft."""
        config = OutlookCreateReplyDraftConfig(message_id="msg-12345")
        node = create_node(config)

        mock_response = create_mock_response(201, {"id": "reply-draft-123"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_reply_draft"
        assert result["draft_id"] == "reply-draft-123"


class TestCreateReplyAllDraft:
    """Test create reply all draft operation."""

    @pytest.mark.asyncio
    async def test_create_reply_all_draft_success(self):
        """Test creating a reply all draft."""
        config = OutlookCreateReplyAllDraftConfig(message_id="msg-12345")
        node = create_node(config)

        mock_response = create_mock_response(201, {"id": "reply-all-draft-123"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_reply_all_draft"
        assert result["draft_id"] == "reply-all-draft-123"


class TestCreateForwardDraft:
    """Test create forward draft operation."""

    @pytest.mark.asyncio
    async def test_create_forward_draft_success(self):
        """Test creating a forward draft."""
        config = OutlookCreateForwardDraftConfig(message_id="msg-12345")
        node = create_node(config)

        mock_response = create_mock_response(201, {"id": "forward-draft-123"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_forward_draft"
        assert result["draft_id"] == "forward-draft-123"


# ============================================================================
# Attachment Operations Tests
# ============================================================================


class TestAddAttachment:
    """Test add attachment operation."""

    @pytest.mark.asyncio
    async def test_add_attachment_success(self):
        """Test adding an attachment to a message."""
        config = OutlookAddAttachmentConfig(
            message_id="msg-12345",
            file_name="document.pdf",
            content_base64="SGVsbG8gV29ybGQ=",
            content_type="application/pdf",
        )
        node = create_node(config)

        mock_response = create_mock_response(
            201,
            {
                "id": "att-123",
                "name": "document.pdf",
                "contentType": "application/pdf",
                "size": 1024,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "add_attachment_to_message"
        assert result["attachment_id"] == "att-123"
        assert result["file_name"] == "document.pdf"


class TestDeleteAttachment:
    """Test delete attachment operation."""

    @pytest.mark.asyncio
    async def test_delete_attachment_success(self):
        """Test deleting an attachment."""
        config = OutlookDeleteAttachmentConfig(
            message_id="msg-12345", attachment_id="att-123"
        )
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_attachment_from_message"


# ============================================================================
# Advanced Folder Operations Tests
# ============================================================================


class TestUpdateFolder:
    """Test update folder operation."""

    @pytest.mark.asyncio
    async def test_update_folder_success(self):
        """Test updating a folder name."""
        config = OutlookUpdateFolderConfig(
            folder_id="folder-123", display_name="Updated Folder Name"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "folder-123", "displayName": "Updated Folder Name"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_mail_folder"
        assert result["folder_name"] == "Updated Folder Name"


class TestDeleteFolder:
    """Test delete folder operation."""

    @pytest.mark.asyncio
    async def test_delete_folder_success(self):
        """Test deleting a folder."""
        config = OutlookDeleteFolderConfig(folder_id="folder-123")
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_mail_folder"


class TestMoveFolder:
    """Test move folder operation."""

    @pytest.mark.asyncio
    async def test_move_folder_success(self):
        """Test moving a folder."""
        config = OutlookMoveFolderConfig(
            folder_id="folder-123", destination_folder_id="folder-parent"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "folder-123-moved"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "move_mail_folder"


class TestCopyFolder:
    """Test copy folder operation."""

    @pytest.mark.asyncio
    async def test_copy_folder_success(self):
        """Test copying a folder."""
        config = OutlookCopyFolderConfig(
            folder_id="folder-123", destination_folder_id="folder-parent"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "folder-123-copy"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "copy_mail_folder"


# ============================================================================
# Message Rules Tests
# ============================================================================


class TestMessageRules:
    """Test message rules operations."""

    @pytest.mark.asyncio
    async def test_list_message_rules_success(self):
        """Test listing message rules."""
        config = OutlookListMessageRulesConfig()
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "rule-1",
                        "displayName": "Move emails from boss",
                        "isEnabled": True,
                    },
                    {"id": "rule-2", "displayName": "Delete spam", "isEnabled": True},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_inbox_rules"
        assert result["rule_count"] == 2

    @pytest.mark.asyncio
    async def test_get_message_rule_success(self):
        """Test getting a specific message rule."""
        config = OutlookGetMessageRuleConfig(rule_id="rule-1")
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {"id": "rule-1", "displayName": "Move emails from boss", "isEnabled": True},
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_inbox_rule"
        assert result["rule"]["displayName"] == "Move emails from boss"

    @pytest.mark.asyncio
    async def test_create_message_rule_success(self):
        """Test creating a message rule."""
        config = OutlookCreateMessageRuleConfig(
            display_name="Move emails from sender",
            conditions='{"fromAddresses": [{"emailAddress": {"address": "sender@example.com"}}]}',
            actions='{"moveToFolder": "inbox"}',
        )
        node = create_node(config)

        mock_response = create_mock_response(
            201, {"id": "rule-new", "displayName": "Move emails from sender"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_inbox_rule"
        assert result["rule_id"] == "rule-new"

    @pytest.mark.asyncio
    async def test_update_message_rule_success(self):
        """Test updating a message rule."""
        config = OutlookUpdateMessageRuleConfig(
            rule_id="rule-1", display_name="Updated rule name"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "rule-1", "displayName": "Updated rule name"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_inbox_rule"

    @pytest.mark.asyncio
    async def test_delete_message_rule_success(self):
        """Test deleting a message rule."""
        config = OutlookDeleteMessageRuleConfig(rule_id="rule-1")
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_inbox_rule"


# ============================================================================
# Categories Tests
# ============================================================================


class TestCategories:
    """Test category operations."""

    @pytest.mark.asyncio
    async def test_list_categories_success(self):
        """Test listing categories."""
        config = OutlookListCategoriesConfig()
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {"id": "cat-1", "displayName": "Red category", "color": "preset0"},
                    {"id": "cat-2", "displayName": "Blue category", "color": "preset1"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_message_categories"
        assert result["category_count"] == 2

    @pytest.mark.asyncio
    async def test_get_category_success(self):
        """Test getting a specific category."""
        config = OutlookGetCategoryConfig(category_id="cat-1")
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "cat-1", "displayName": "Red category", "color": "preset0"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_message_category"
        assert result["category"]["displayName"] == "Red category"

    @pytest.mark.asyncio
    async def test_create_category_success(self):
        """Test creating a category."""
        config = OutlookCreateCategoryConfig(
            display_name="My Category", color="preset5"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            201, {"id": "cat-new", "displayName": "My Category", "color": "preset5"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_message_category"
        assert result["category_id"] == "cat-new"

    @pytest.mark.asyncio
    async def test_update_category_success(self):
        """Test updating a category."""
        config = OutlookUpdateCategoryConfig(category_id="cat-1", color="preset10")
        node = create_node(config)

        mock_response = create_mock_response(200, {"id": "cat-1", "color": "preset10"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_message_category"

    @pytest.mark.asyncio
    async def test_delete_category_success(self):
        """Test deleting a category."""
        config = OutlookDeleteCategoryConfig(category_id="cat-1")
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_message_category"


# ============================================================================
# MIME Operations Tests
# ============================================================================


class TestMimeOperations:
    """Test MIME content operations."""

    @pytest.mark.asyncio
    async def test_get_mime_content_success(self):
        """Test getting MIME content of a message."""
        config = OutlookGetMimeContentConfig(message_id="msg-12345")
        node = create_node(config)

        mime_content = b"From: sender@example.com\r\nTo: recipient@example.com\r\nSubject: Test\r\n\r\nBody"
        mock_response = create_mock_response(200, content=mime_content)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_email_mime_content"
        assert "mime_content" in result

    @pytest.mark.asyncio
    async def test_send_mime_success(self):
        """Test sending a MIME formatted message."""
        config = OutlookSendMimeConfig(
            mime_content="From: sender@example.com\r\nTo: recipient@example.com\r\nSubject: Test\r\n\r\nBody"
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "send_mime_message"


# ============================================================================
# Calendar Operations Tests
# ============================================================================


class TestCalendarEvents:
    """Test calendar event CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_events_success(self):
        """Test listing calendar events."""
        config = OutlookListEventsConfig(max_results=10, order_by="start/dateTime")
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "event-1",
                        "subject": "Team Meeting",
                        "start": {"dateTime": "2024-01-15T10:00:00", "timeZone": "UTC"},
                        "end": {"dateTime": "2024-01-15T11:00:00", "timeZone": "UTC"},
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_calendar_events"
        assert result["event_count"] == 1

    @pytest.mark.asyncio
    async def test_create_event_success(self):
        """Test creating a calendar event."""
        config = OutlookCreateEventConfig(
            subject="Team Meeting",
            start_datetime="2024-01-15T10:00:00",
            end_datetime="2024-01-15T11:00:00",
            timezone="UTC",
            location="Conference Room A",
        )
        node = create_node(config)

        mock_response = create_mock_response(
            201, {"id": "event-new", "subject": "Team Meeting"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_calendar_event"
        assert result["event_id"] == "event-new"

    @pytest.mark.asyncio
    async def test_get_event_success(self):
        """Test getting a specific event."""
        config = OutlookGetEventConfig(event_id="event-1")
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "event-1", "subject": "Team Meeting"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_calendar_event"

    @pytest.mark.asyncio
    async def test_update_event_success(self):
        """Test updating an event."""
        config = OutlookUpdateEventConfig(
            event_id="event-1", subject="Updated Meeting Title"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "event-1", "subject": "Updated Meeting Title"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_calendar_event"

    @pytest.mark.asyncio
    async def test_delete_event_success(self):
        """Test deleting an event."""
        config = OutlookDeleteEventConfig(event_id="event-1")
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_calendar_event"

    @pytest.mark.asyncio
    async def test_cancel_event_success(self):
        """Test canceling an event."""
        config = OutlookCancelEventConfig(
            event_id="event-1", comment="Meeting cancelled"
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "cancel_calendar_event"


class TestEventResponses:
    """Test event invitation response operations."""

    @pytest.mark.asyncio
    async def test_accept_event_success(self):
        """Test accepting an event invitation."""
        config = OutlookAcceptEventConfig(
            event_id="event-1", comment="Looking forward to it!", send_response=True
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "accept_calendar_event_invitation"

    @pytest.mark.asyncio
    async def test_decline_event_success(self):
        """Test declining an event invitation."""
        config = OutlookDeclineEventConfig(
            event_id="event-1", comment="Unable to attend", send_response=True
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "decline_calendar_event_invitation"

    @pytest.mark.asyncio
    async def test_tentatively_accept_event_success(self):
        """Test tentatively accepting an event invitation."""
        config = OutlookTentativelyAcceptEventConfig(
            event_id="event-1", comment="Will try to attend", send_response=True
        )
        node = create_node(config)

        mock_response = create_mock_response(202, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "tentatively_accept_calendar_event_invitation"


class TestEventReminders:
    """Test event reminder operations."""

    @pytest.mark.asyncio
    async def test_dismiss_reminder_success(self):
        """Test dismissing an event reminder."""
        config = OutlookDismissReminderConfig(event_id="event-1")
        node = create_node(config)

        mock_response = create_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "dismiss_event_reminder"

    @pytest.mark.asyncio
    async def test_snooze_reminder_success(self):
        """Test snoozing an event reminder."""
        config = OutlookSnoozeReminderConfig(
            event_id="event-1", new_reminder_time="2024-01-15T09:00:00"
        )
        node = create_node(config)

        mock_response = create_mock_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "snooze_event_reminder"


class TestAdvancedCalendar:
    """Test advanced calendar operations."""

    @pytest.mark.asyncio
    async def test_find_meeting_times_success(self):
        """Test finding available meeting times."""
        config = OutlookFindMeetingTimesConfig(
            attendees="user1@example.com, user2@example.com",
            meeting_duration=60,
            start_time="2024-01-15T09:00:00",
            end_time="2024-01-15T17:00:00",
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "meetingTimeSuggestions": [
                    {
                        "meetingTimeSlot": {
                            "start": {"dateTime": "2024-01-15T10:00:00"},
                            "end": {"dateTime": "2024-01-15T11:00:00"},
                        }
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "find_available_meeting_times"

    @pytest.mark.asyncio
    async def test_get_schedule_success(self):
        """Test getting free/busy schedule."""
        config = OutlookGetScheduleConfig(
            schedules="user1@example.com, user2@example.com",
            start_time="2024-01-15T00:00:00",
            end_time="2024-01-16T00:00:00",
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "scheduleId": "user1@example.com",
                        "availabilityView": "0000000000000000",
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_free_busy_schedule"

    @pytest.mark.asyncio
    async def test_list_event_instances_success(self):
        """Test listing recurring event instances."""
        config = OutlookListEventInstancesConfig(
            event_id="event-recurring",
            start_datetime="2024-01-01T00:00:00",
            end_datetime="2024-12-31T23:59:59",
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {"id": "instance-1", "start": {"dateTime": "2024-01-15T10:00:00"}},
                    {"id": "instance-2", "start": {"dateTime": "2024-01-22T10:00:00"}},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_recurring_event_instances"

    @pytest.mark.asyncio
    async def test_list_calendars_success(self):
        """Test listing calendars."""
        config = OutlookListCalendarsConfig()
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {"id": "cal-1", "name": "Calendar"},
                    {"id": "cal-2", "name": "Birthdays"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_calendars"

    @pytest.mark.asyncio
    async def test_list_calendar_groups_success(self):
        """Test listing calendar groups."""
        config = OutlookListCalendarGroupsConfig()
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"value": [{"id": "group-1", "name": "My Calendars"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_calendar_groups"

    @pytest.mark.asyncio
    async def test_get_room_lists_success(self):
        """Test getting room lists."""
        config = OutlookGetRoomListsConfig()
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"value": [{"name": "Building 1", "address": "building1@example.com"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_available_room_lists"


# ============================================================================
# Contacts Operations Tests
# ============================================================================


class TestContacts:
    """Test contacts CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_contacts_success(self):
        """Test listing contacts."""
        config = OutlookListContactsConfig(max_results=10, order_by="displayName")
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {
                        "id": "contact-1",
                        "displayName": "John Doe",
                        "emailAddresses": [{"address": "john.doe@example.com"}],
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_contacts"
        assert result["contact_count"] == 1

    @pytest.mark.asyncio
    async def test_create_contact_success(self):
        """Test creating a contact."""
        config = OutlookCreateContactConfig(
            given_name="John",
            surname="Doe",
            email_address="john.doe@example.com",
            business_phone="+1-555-0123",
        )
        node = create_node(config)

        mock_response = create_mock_response(
            201, {"id": "contact-new", "givenName": "John", "surname": "Doe"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_contact_person"
        assert result["contact_id"] == "contact-new"

    @pytest.mark.asyncio
    async def test_get_contact_success(self):
        """Test getting a specific contact."""
        config = OutlookGetContactConfig(contact_id="contact-1")
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "contact-1", "givenName": "John", "surname": "Doe"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_contact_person"

    @pytest.mark.asyncio
    async def test_update_contact_success(self):
        """Test updating a contact."""
        config = OutlookUpdateContactConfig(
            contact_id="contact-1", email_address="john.newemail@example.com"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "id": "contact-1",
                "emailAddresses": [{"address": "john.newemail@example.com"}],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_contact_person"

    @pytest.mark.asyncio
    async def test_delete_contact_success(self):
        """Test deleting a contact."""
        config = OutlookDeleteContactConfig(contact_id="contact-1")
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_contact_person"


class TestContactFolders:
    """Test contact folder operations."""

    @pytest.mark.asyncio
    async def test_list_contact_folders_success(self):
        """Test listing contact folders."""
        config = OutlookListContactFoldersConfig()
        node = create_node(config)

        mock_response = create_mock_response(
            200,
            {
                "value": [
                    {"id": "folder-1", "displayName": "My Contacts"},
                    {"id": "folder-2", "displayName": "Work Contacts"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "list_contact_folders"
        assert result["folder_count"] == 2

    @pytest.mark.asyncio
    async def test_create_contact_folder_success(self):
        """Test creating a contact folder."""
        config = OutlookCreateContactFolderConfig(display_name="My Contacts")
        node = create_node(config)

        mock_response = create_mock_response(
            201, {"id": "folder-new", "displayName": "My Contacts"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "create_contact_folder"
        assert result["folder_id"] == "folder-new"

    @pytest.mark.asyncio
    async def test_get_contact_folder_success(self):
        """Test getting a specific contact folder."""
        config = OutlookGetContactFolderConfig(folder_id="folder-1")
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "folder-1", "displayName": "My Contacts"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "get_contact_folder"

    @pytest.mark.asyncio
    async def test_update_contact_folder_success(self):
        """Test updating a contact folder."""
        config = OutlookUpdateContactFolderConfig(
            folder_id="folder-1", display_name="Updated Folder Name"
        )
        node = create_node(config)

        mock_response = create_mock_response(
            200, {"id": "folder-1", "displayName": "Updated Folder Name"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.patch = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "update_contact_folder"

    @pytest.mark.asyncio
    async def test_delete_contact_folder_success(self):
        """Test deleting a contact folder."""
        config = OutlookDeleteContactFolderConfig(folder_id="folder-1")
        node = create_node(config)

        mock_response = create_mock_response(204, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.delete = AsyncMock(return_value=mock_response)

            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "delete_contact_folder"


# ============================================================================
# OData URL Building Tests
# ============================================================================


class TestODataUrlBuilding:
    """Test that OData query parameters use literal $ in URLs, not %24-encoded."""

    def test_build_odata_url_preserves_dollar_sign(self):
        """Verify _build_odata_url keeps $ literal in param names."""
        url = OutlookMailNode._build_odata_url(
            "https://graph.microsoft.com/v1.0/me/messages",
            {"$top": 10, "$select": "id,subject", "$filter": "isRead eq false"},
        )
        assert "$top=10" in url
        assert "$select=id,subject" in url
        assert "$filter=" in url
        assert "%24" not in url, f"$ should not be percent-encoded: {url}"

    def test_build_odata_url_empty_params(self):
        """Verify empty params returns base URL unchanged."""
        base = "https://graph.microsoft.com/v1.0/me/messages"
        assert OutlookMailNode._build_odata_url(base, {}) == base

    def test_build_odata_url_encodes_values_safely(self):
        """Verify param values are URL-safe but $ in keys is preserved."""
        url = OutlookMailNode._build_odata_url(
            "https://graph.microsoft.com/v1.0/me/messages", {"$search": '"test query"'}
        )
        assert "$search=" in url
        assert "%24" not in url

    @pytest.mark.asyncio
    async def test_read_emails_url_has_literal_odata_params(self):
        """Regression test: read emails must use literal $top/$select in URL."""
        config = OutlookReadConfig(folder="inbox", max_results=5, include_body="true")
        node = create_node(config)
        mock_response = create_mock_response(200, {"value": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            await node.execute({})

        call_args = mock_client.return_value.get.call_args
        request_url = call_args[0][0]
        assert "$top=5" in request_url
        assert "$select=" in request_url
        assert "$orderby=" in request_url
        assert (
            "%24" not in request_url
        ), f"OData $ must not be percent-encoded: {request_url}"
        # Ensure params dict is NOT passed (would cause double-encoding)
        assert call_args[1].get("params") is None or "params" not in call_args[1]

    @pytest.mark.asyncio
    async def test_list_events_url_has_literal_odata_params(self):
        """Regression test: list events must use literal $top/$orderby in URL."""
        config = OutlookListEventsConfig(max_results=20)
        node = create_node(config)
        mock_response = create_mock_response(200, {"value": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            await node.execute({})

        call_args = mock_client.return_value.get.call_args
        request_url = call_args[0][0]
        assert "$top=20" in request_url
        assert "%24" not in request_url

    @pytest.mark.asyncio
    async def test_list_contacts_url_has_literal_odata_params(self):
        """Regression test: list contacts must use literal $top/$orderby in URL."""
        config = OutlookListContactsConfig(max_results=15)
        node = create_node(config)
        mock_response = create_mock_response(200, {"value": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            await node.execute({})

        call_args = mock_client.return_value.get.call_args
        request_url = call_args[0][0]
        assert "$top=15" in request_url
        assert "%24" not in request_url

    @pytest.mark.asyncio
    async def test_list_folders_url_has_literal_odata_params(self):
        """Regression test: list folders must use literal $select in URL."""
        config = OutlookListFoldersConfig()
        node = create_node(config)
        mock_response = create_mock_response(200, {"value": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_client.return_value
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            await node.execute({})

        call_args = mock_client.return_value.get.call_args
        request_url = call_args[0][0]
        assert "$select=" in request_url
        assert "%24" not in request_url


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# Additional Calendar operations (merged from the former Outlook Calendar node)
# ============================================================================
import nodes.outlook_mail_node as _oc


def _run_calendar_op(config, status_code=200, json_data=None):
    """Run a node op whose handler uses the shared _graph_call (client.request),
    capturing the (method, url, json) that was sent."""
    captured = {}

    async def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["params"] = kwargs.get("params")
        return create_mock_response(status_code, json_data)

    node = create_node(config)

    async def _go():
        with patch("nodes.outlook_mail_node.httpx.AsyncClient") as mock_client, patch.object(
            OutlookMailNode, "_ensure_fresh_token", new=AsyncMock(return_value="tok")
        ):
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value.request = AsyncMock(side_effect=fake_request)
            result = await node.execute({})
        return result, captured

    import asyncio
    return asyncio.get_event_loop().run_until_complete(_go())


class TestOutlookCalendarCoverage:
    def test_get_calendar(self):
        r, cap = _run_calendar_op(_oc.OutlookGetCalendarConfig(calendar_id="cal1"), 200, {"id": "cal1"})
        assert r["status"] == "success" and cap["method"] == "GET"
        assert cap["url"].endswith("/me/calendars/cal1")

    def test_create_calendar(self):
        r, cap = _run_calendar_op(_oc.OutlookCreateCalendarConfig(name="Work"), 201, {"id": "c2"})
        assert cap["method"] == "POST" and cap["url"].endswith("/me/calendars")
        assert cap["json"]["name"] == "Work"

    def test_delete_calendar(self):
        r, cap = _run_calendar_op(_oc.OutlookDeleteCalendarConfig(calendar_id="cal1"), 204)
        assert cap["method"] == "DELETE" and cap["url"].endswith("/me/calendars/cal1")

    def test_get_calendar_view(self):
        r, cap = _run_calendar_op(_oc.OutlookCalendarViewConfig(
            start_date_time="2026-01-01T00:00:00Z", end_date_time="2026-01-02T00:00:00Z"), 200, {"value": []})
        assert cap["method"] == "GET" and cap["url"].endswith("/me/calendarView")
        assert cap["params"]["startDateTime"] == "2026-01-01T00:00:00Z"

    def test_forward_event(self):
        r, cap = _run_calendar_op(_oc.OutlookForwardCalendarEventConfig(
            event_id="e1", to_recipients="a@b.com, c@d.com", comment="fyi"), 202)
        assert cap["method"] == "POST" and cap["url"].endswith("/me/events/e1/forward")
        assert len(cap["json"]["ToRecipients"]) == 2

    def test_list_event_attachments(self):
        r, cap = _run_calendar_op(_oc.OutlookListEventAttachmentsConfig(event_id="e1"), 200, {"value": []})
        assert cap["url"].endswith("/me/events/e1/attachments")

    def test_get_event_attachment(self):
        r, cap = _run_calendar_op(_oc.OutlookGetEventAttachmentConfig(event_id="e1", attachment_id="at1"), 200, {"id": "at1"})
        assert cap["url"].endswith("/me/events/e1/attachments/at1")

    def test_delete_event_attachment(self):
        r, cap = _run_calendar_op(_oc.OutlookDeleteEventAttachmentConfig(event_id="e1", attachment_id="at1"), 204)
        assert cap["method"] == "DELETE" and cap["url"].endswith("/me/events/e1/attachments/at1")

    def test_calendar_view_delta(self):
        r, cap = _run_calendar_op(_oc.OutlookCalendarViewDeltaConfig(
            start_date_time="2026-01-01T00:00:00Z", end_date_time="2026-01-02T00:00:00Z"), 200, {"value": []})
        assert cap["url"].endswith("/me/calendarView/delta")

    def test_calendar_group_crud(self):
        r, cap = _run_calendar_op(_oc.OutlookCreateCalendarGroupConfig(name="G"), 201, {"id": "g1"})
        assert cap["method"] == "POST" and cap["url"].endswith("/me/calendarGroups")
        r, cap = _run_calendar_op(_oc.OutlookGetCalendarGroupConfig(group_id="g1"), 200, {"id": "g1"})
        assert cap["url"].endswith("/me/calendarGroups/g1")
        r, cap = _run_calendar_op(_oc.OutlookListCalendarsInGroupConfig(group_id="g1"), 200, {"value": []})
        assert cap["url"].endswith("/me/calendarGroups/g1/calendars")

    def test_calendar_permissions(self):
        r, cap = _run_calendar_op(_oc.OutlookListCalendarPermissionsConfig(calendar_id="cal1"), 200, {"value": []})
        assert cap["url"].endswith("/me/calendars/cal1/calendarPermissions")
        r, cap = _run_calendar_op(_oc.OutlookCreateCalendarPermissionConfig(
            calendar_id="cal1", resource='{"role":"read"}'), 201, {"id": "p1"})
        assert cap["method"] == "POST" and cap["json"] == {"role": "read"}
        r, cap = _run_calendar_op(_oc.OutlookUpdateCalendarPermissionConfig(
            calendar_id="cal1", permission_id="p1", role="write"), 200, {"id": "p1"})
        assert cap["method"] == "PATCH" and cap["json"] == {"role": "write"}

    def test_allowed_sharing_roles(self):
        r, cap = _run_calendar_op(_oc.OutlookAllowedSharingRolesConfig(
            calendar_id="cal1", user_email="x@y.com"), 200, {"value": ["read"]})
        assert "allowedCalendarSharingRoles(User='x%40y.com')" in cap["url"]

    def test_reminder_view(self):
        r, cap = _run_calendar_op(_oc.OutlookReminderViewConfig(
            start_date_time="2026-01-01T00:00:00Z", end_date_time="2026-01-02T00:00:00Z"), 200, {"value": []})
        assert "reminderView(startDateTime=" in cap["url"]

    def test_calendar_triggers_passthrough(self):
        """Each decomposed trigger passes the Graph notification through with
        its own operation name."""
        import asyncio
        for cfg_cls, op in [
            (_oc.OutlookOnCalendarEventCreatedConfig, "on_calendar_event_created"),
            (_oc.OutlookOnCalendarEventUpdatedConfig, "on_calendar_event_updated"),
            (_oc.OutlookOnCalendarEventDeletedConfig, "on_calendar_event_deleted"),
            (_oc.OutlookOnCalendarEventChangeConfig, "on_calendar_event_change"),
        ]:
            node = create_node(cfg_cls(webhook_url="https://abc.hooks.example.test"))
            result = asyncio.get_event_loop().run_until_complete(
                node.execute({"value": [{"resource": "Users/x/Events/e1"}]}))
            assert result["status"] == "success"
            assert result["operation"] == op
            assert result["data"]["value"][0]["resource"].startswith("Users")

    def test_calendar_trigger_subscription_change_types(self):
        """Each trigger registers a Graph subscription with its own changeType +
        the calendar-scoped resource."""
        import asyncio
        for op, change_type in [
            ("on_calendar_event_created", "created"),
            ("on_calendar_event_updated", "updated"),
            ("on_calendar_event_deleted", "deleted"),
            ("on_calendar_event_change", "created,updated,deleted"),
        ]:
            captured = {}

            async def fake_request(method, url, **kwargs):
                captured["url"] = url
                captured["json"] = kwargs.get("json")
                return create_mock_response(201, {"id": "sub_1"})

            async def _go():
                with patch("nodes.outlook_mail_node.httpx.AsyncClient") as mc:
                    mc.return_value.__aenter__ = AsyncMock(return_value=mc.return_value)
                    mc.return_value.__aexit__ = AsyncMock(return_value=None)
                    mc.return_value.request = AsyncMock(side_effect=fake_request)
                    return await OutlookMailNode._register_external_webhook(
                        webhook_url="https://abc.hooks.example.test",
                        credential={"access_token": "tok"},
                        config={"operation": op, "calendar_id": "cal1"},
                        node_id="n1",
                    )

            extra = asyncio.get_event_loop().run_until_complete(_go())
            assert extra["external_webhook_id"] == "sub_1"
            assert captured["url"].endswith("/subscriptions")
            assert captured["json"]["changeType"] == change_type
            assert captured["json"]["resource"] == "/me/calendars/cal1/events"
