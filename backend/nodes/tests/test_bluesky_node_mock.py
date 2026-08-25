"""
Mock tests for BlueSky node operations that can't be safely integration tested.

This file covers:
- Destructive operations (delete account, deactivate, etc.)
- Operations requiring special data (video files, conversations, etc.)
- Operations that would create unwanted side effects

Uses unittest.mock to verify routing and logic without making real API calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nodes.bluesky_node import (
    BlueSkyNode,
    BlueSkyNodeConfig,
    BlueSkyAppPasswordCredential,
    # Destructive operations
    BlueSkyDeleteAccountConfig,
    BlueSkyDeactivateAccountConfig,
    BlueSkyActivateAccountConfig,
    BlueSkyRequestAccountDeleteConfig,
    BlueSkyDeleteSessionConfig,
    BlueSkyCreateAppPasswordConfig,
    BlueSkyRevokeAppPasswordConfig,
    # Email operations
    BlueSkyConfirmEmailConfig,
    BlueSkyRequestEmailConfirmationConfig,
    BlueSkyRequestEmailUpdateConfig,
    BlueSkyUpdateEmailConfig,
    # Password operations
    BlueSkyRequestPasswordResetConfig,
    BlueSkyResetPasswordConfig,
    # Account creation/invite operations
    BlueSkyCreateInviteCodeConfig,
    BlueSkyCreateInviteCodesConfig,
    # Video operations requiring files
    BlueSkyUploadVideoConfig,
    BlueSkyGetVideoJobStatusConfig,
    # Chat operations requiring conversation IDs
    BlueSkyGetConversationConfig,
    BlueSkyGetConversationForMembersConfig,
    BlueSkyGetMessagesConfig,
    BlueSkySendMessageConfig,
    BlueSkyDeleteMessageConfig,
    BlueSkyLeaveConversationConfig,
    BlueSkyMuteConversationConfig,
    BlueSkyUnmuteConversationConfig,
    BlueSkyUpdateConversationReadConfig,
    BlueSkyAcceptConversationConfig,
    BlueSkyAddMessageReactionConfig,
    BlueSkyRemoveMessageReactionConfig,
    BlueSkySendMessageBatchConfig,
    BlueSkyGetConversationLogConfig,
    BlueSkyDeleteChatAccountConfig,
    # Repository operations requiring complex data
    BlueSkyPutRecordConfig,
    BlueSkyDeleteRecordConfig,
    BlueSkyGetRecordConfig,
    BlueSkyUploadBlobConfig,
    BlueSkyApplyWritesConfig,
    # Graph operations that would create unwanted relationships
    BlueSkyUnblockUserConfig,
    BlueSkyMuteActorListConfig,
    BlueSkyUnmuteActorListConfig,
    # List/feed operations requiring URIs
    BlueSkyGetListConfig,
    BlueSkyGetListFeedConfig,
    BlueSkyGetStarterPackConfig,
    # Age assurance
    BlueSkyBeginAgeAssuranceConfig,
    # Moderation
    BlueSkyCreateModerationReportConfig,
    # Identity
    BlueSkyUpdateHandleConfig,
    # Notification
    BlueSkyRegisterPushConfig,
    BlueSkyUnregisterPushConfig,
    BlueSkyListActivitySubscriptionsConfig,
)


def create_mock_node(config) -> BlueSkyNode:
    """Create a BlueSkyNode instance with mocked credentials."""
    credentials = BlueSkyAppPasswordCredential(
        identifier="test.bsky.social", app_password="test-test-test-test"
    )
    node_config = BlueSkyNodeConfig(config=config, credentials=credentials)
    return BlueSkyNode(
        node_id="mock-node",
        node_type="automation-bluesky",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="mock-workflow",
    )


# ============================================================================
# Destructive Account Operations
# ============================================================================


class TestDestructiveOperations:
    """Mock tests for destructive account operations."""

    @pytest.mark.asyncio
    async def test_delete_account(self):
        """Test delete_account routing - MOCKED."""
        config = BlueSkyDeleteAccountConfig(
            password="test_password", did="did:plc:test123", token="test_token"
        )
        node = create_mock_node(config)

        with patch.object(
            node, "_delete_account", new_callable=AsyncMock
        ) as mock_delete:
            mock_delete.return_value = {
                "status": "success",
                "action": "delete_account",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "delete_account"
                mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_deactivate_account(self):
        """Test deactivate_account routing - MOCKED."""
        config = BlueSkyDeactivateAccountConfig()
        node = create_mock_node(config)

        with patch.object(
            node, "_deactivate_account", new_callable=AsyncMock
        ) as mock_deactivate:
            mock_deactivate.return_value = {
                "status": "success",
                "action": "deactivate_account",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "deactivate_account"
                mock_deactivate.assert_called_once()

    @pytest.mark.asyncio
    async def test_activate_account(self):
        """Test activate_account routing - MOCKED."""
        config = BlueSkyActivateAccountConfig()
        node = create_mock_node(config)

        with patch.object(
            node, "_activate_account", new_callable=AsyncMock
        ) as mock_activate:
            mock_activate.return_value = {
                "status": "success",
                "action": "activate_account",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "activate_account"
                mock_activate.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_account_delete(self):
        """Test request_account_delete routing - MOCKED."""
        config = BlueSkyRequestAccountDeleteConfig()
        node = create_mock_node(config)

        with patch.object(
            node, "_request_account_delete", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "status": "success",
                "action": "request_account_deletion",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "request_account_deletion"
                mock_request.assert_called_once()


# ============================================================================
# Session & Password Operations
# ============================================================================


class TestSessionPasswordOperations:
    """Mock tests for session and password management."""

    @pytest.mark.asyncio
    async def test_delete_session(self):
        """Test delete_session routing - MOCKED."""
        config = BlueSkyDeleteSessionConfig()
        node = create_mock_node(config)

        with patch.object(
            node, "_delete_session", new_callable=AsyncMock
        ) as mock_delete:
            mock_delete.return_value = {
                "status": "success",
                "action": "delete_session_logout",
                "timing_ms": 30,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "delete_session_logout"
                mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_app_password(self):
        """Test create_app_password routing - MOCKED."""
        config = BlueSkyCreateAppPasswordConfig(name="Test App")
        node = create_mock_node(config)

        with patch.object(
            node, "_create_app_password", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "status": "success",
                "action": "create_app_password",
                "password": "xxxx-xxxx-xxxx-xxxx",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "create_app_password"
                assert "password" in result
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_app_password(self):
        """Test revoke_app_password routing - MOCKED."""
        config = BlueSkyRevokeAppPasswordConfig(name="Test App")
        node = create_mock_node(config)

        with patch.object(
            node, "_revoke_app_password", new_callable=AsyncMock
        ) as mock_revoke:
            mock_revoke.return_value = {
                "status": "success",
                "action": "revoke_app_password",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "revoke_app_password"
                mock_revoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_password_reset(self):
        """Test request_password_reset routing - MOCKED."""
        config = BlueSkyRequestPasswordResetConfig(email="test@example.com")
        node = create_mock_node(config)

        with patch.object(
            node, "_request_password_reset", new_callable=AsyncMock
        ) as mock_reset:
            mock_reset.return_value = {
                "status": "success",
                "action": "request_password_reset",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "request_password_reset"
                mock_reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_password(self):
        """Test reset_password routing - MOCKED."""
        config = BlueSkyResetPasswordConfig(
            token="reset_token", password="new_password"
        )
        node = create_mock_node(config)

        with patch.object(
            node, "_reset_password", new_callable=AsyncMock
        ) as mock_reset:
            mock_reset.return_value = {
                "status": "success",
                "action": "reset_password",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "reset_password"
                mock_reset.assert_called_once()


# ============================================================================
# Email Operations
# ============================================================================


class TestEmailOperations:
    """Mock tests for email operations."""

    @pytest.mark.asyncio
    async def test_confirm_email(self):
        """Test confirm_email routing - MOCKED."""
        config = BlueSkyConfirmEmailConfig(
            email="test@example.com", token="confirm_token"
        )
        node = create_mock_node(config)

        with patch.object(
            node, "_confirm_email", new_callable=AsyncMock
        ) as mock_confirm:
            mock_confirm.return_value = {
                "status": "success",
                "action": "confirm_email",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "confirm_email"
                mock_confirm.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_email_confirmation(self):
        """Test request_email_confirmation routing - MOCKED."""
        config = BlueSkyRequestEmailConfirmationConfig()
        node = create_mock_node(config)

        with patch.object(
            node, "_request_email_confirmation", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "status": "success",
                "action": "request_email_confirmation",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "request_email_confirmation"
                mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_email_update(self):
        """Test request_email_update routing - MOCKED."""
        config = BlueSkyRequestEmailUpdateConfig(email="new@example.com")
        node = create_mock_node(config)

        with patch.object(
            node, "_request_email_update", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "status": "success",
                "action": "request_email_update",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "request_email_update"
                mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_email(self):
        """Test update_email routing - MOCKED."""
        config = BlueSkyUpdateEmailConfig(email="new@example.com", token="update_token")
        node = create_mock_node(config)

        with patch.object(node, "_update_email", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = {
                "status": "success",
                "action": "update_account_email",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "update_account_email"
                mock_update.assert_called_once()


# ============================================================================
# Account Creation & Invite Operations
# ============================================================================


class TestAccountCreationOperations:
    """Mock tests for account creation and invite operations."""

    @pytest.mark.asyncio
    async def test_create_account(self):
        """Test create_account - REMOVED (operation no longer exists)."""
        pytest.skip(
            "create_account operation removed - requires email/phone verification"
        )

    @pytest.mark.asyncio
    async def test_create_invite_code(self):
        """Test create_invite_code routing - MOCKED (requires admin)."""
        config = BlueSkyCreateInviteCodeConfig(use_count=1)
        node = create_mock_node(config)

        with patch.object(
            node, "_create_invite_code", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "status": "success",
                "action": "create_invite_code",
                "code": "test-invite-code",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "create_invite_code"
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_invite_codes(self):
        """Test create_invite_codes routing - MOCKED (requires admin)."""
        config = BlueSkyCreateInviteCodesConfig(code_count=5, use_count=1)
        node = create_mock_node(config)

        with patch.object(
            node, "_create_invite_codes", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "status": "success",
                "action": "create_multiple_invite_codes",
                "codes": ["code1", "code2", "code3", "code4", "code5"],
                "timing_ms": 150,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "create_multiple_invite_codes"
                assert len(result["codes"]) == 5
                mock_create.assert_called_once()


# ============================================================================
# Video Operations
# ============================================================================


class TestVideoOperations:
    """Mock tests for video operations requiring file data."""

    @pytest.mark.asyncio
    async def test_upload_video(self):
        """Test upload_video routing - MOCKED."""
        config = BlueSkyUploadVideoConfig(
            video_data="base64_video_data", mime_type="video/mp4"
        )
        node = create_mock_node(config)

        with patch.object(node, "_upload_video", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = {
                "status": "success",
                "action": "upload_video",
                "job_id": "video_job_123",
                "timing_ms": 500,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "upload_video"
                assert "job_id" in result
                mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_video_job_status(self):
        """Test get_video_job_status routing - MOCKED."""
        config = BlueSkyGetVideoJobStatusConfig(job_id="video_job_123")
        node = create_mock_node(config)

        with patch.object(
            node, "_get_video_job_status", new_callable=AsyncMock
        ) as mock_status:
            mock_status.return_value = {
                "status": "success",
                "action": "get_video_job_status",
                "job_status": "completed",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "get_video_job_status"
                mock_status.assert_called_once()


# ============================================================================
# Chat Operations
# ============================================================================


class TestChatOperationsRequiringData:
    """Mock tests for chat operations requiring conversation/message IDs."""

    @pytest.mark.asyncio
    async def test_get_conversation(self):
        """Test get_conversation routing - MOCKED."""
        config = BlueSkyGetConversationConfig(convo_id="convo_123")
        node = create_mock_node(config)

        with patch.object(
            node, "_get_conversation", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "status": "success",
                "action": "get_conversation",
                "conversation": {"id": "convo_123"},
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "get_conversation"
                mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test send_message routing - MOCKED."""
        config = BlueSkySendMessageConfig(convo_id="convo_123", text="Hello")
        node = create_mock_node(config)

        with patch.object(node, "_send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {
                "status": "success",
                "action": "send_message_in_conversation",
                "message_id": "msg_456",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "send_message_in_conversation"
                mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_message(self):
        """Test delete_message routing - MOCKED."""
        config = BlueSkyDeleteMessageConfig(convo_id="convo_123", message_id="msg_456")
        node = create_mock_node(config)

        with patch.object(
            node, "_delete_message", new_callable=AsyncMock
        ) as mock_delete:
            mock_delete.return_value = {
                "status": "success",
                "action": "delete_message_for_self",
                "timing_ms": 50,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "delete_message_for_self"
                mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_chat_account(self):
        """Test delete_chat_account routing - MOCKED."""
        config = BlueSkyDeleteChatAccountConfig()
        node = create_mock_node(config)

        with patch.object(
            node, "_delete_chat_account", new_callable=AsyncMock
        ) as mock_delete:
            mock_delete.return_value = {
                "status": "success",
                "action": "delete_chat_account",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "delete_chat_account"
                mock_delete.assert_called_once()


# ============================================================================
# Repository Operations Requiring Complex Data
# ============================================================================


class TestRepositoryOperationsComplex:
    """Mock tests for repository operations requiring complex/specific data."""

    @pytest.mark.asyncio
    async def test_upload_blob(self):
        """Test upload_blob routing - MOCKED."""
        config = BlueSkyUploadBlobConfig(
            blob_data="base64_blob_data", mime_type="image/png"
        )
        node = create_mock_node(config)

        with patch.object(node, "_upload_blob", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = {
                "status": "success",
                "action": "upload_blob_to_repository",
                "blob": {"ref": "blob_ref_123"},
                "timing_ms": 200,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "upload_blob_to_repository"
                mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_writes(self):
        """Test apply_writes routing - MOCKED."""
        config = BlueSkyApplyWritesConfig(
            repo="did:plc:test",
            writes=[
                {
                    "$type": "create",
                    "collection": "app.bsky.feed.post",
                    "value": {"text": "test"},
                }
            ],
        )
        node = create_mock_node(config)

        with patch.object(node, "_apply_writes", new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = {
                "status": "success",
                "action": "apply_writes_atomically",
                "results": [{"uri": "at://test/post"}],
                "timing_ms": 150,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "apply_writes_atomically"
                mock_apply.assert_called_once()


# ============================================================================
# Other Skipped Operations
# ============================================================================


class TestOtherSkippedOperations:
    """Mock tests for other operations that are skipped."""

    @pytest.mark.asyncio
    async def test_update_handle(self):
        """Test update_handle routing - MOCKED."""
        config = BlueSkyUpdateHandleConfig(handle="newhandle.bsky.social")
        node = create_mock_node(config)

        with patch.object(
            node, "_update_handle", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {
                "status": "success",
                "action": "update_account_handle",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "update_account_handle"
                mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_begin_age_assurance(self):
        """Test begin_age_assurance routing - MOCKED."""
        config = BlueSkyBeginAgeAssuranceConfig(dob="2000-01-01")
        node = create_mock_node(config)

        with patch.object(
            node, "_begin_age_assurance", new_callable=AsyncMock
        ) as mock_begin:
            mock_begin.return_value = {
                "status": "success",
                "action": "begin_age_assurance",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "begin_age_assurance"
                mock_begin.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_moderation_report(self):
        """Test create_moderation_report routing - MOCKED."""
        config = BlueSkyCreateModerationReportConfig(
            subject={
                "$type": "com.atproto.admin.defs#repoRef",
                "did": "did:plc:bad_actor",
            },
            reason_type="spam",
            reason="Spam content",
        )
        node = create_mock_node(config)

        with patch.object(
            node, "_create_moderation_report", new_callable=AsyncMock
        ) as mock_report:
            mock_report.return_value = {
                "status": "success",
                "action": "create_moderation_report",
                "report_id": "report_123",
                "timing_ms": 100,
            }

            with patch.object(
                node, "_create_session", new_callable=AsyncMock
            ) as mock_session:
                mock_session.return_value = {
                    "accessJwt": "test_token",
                    "did": "did:plc:test",
                }
                result = await node.execute({})

                assert result["action"] == "create_moderation_report"
                mock_report.assert_called_once()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("BlueSky Node Mock Tests - Destructive & Special-Data Operations")
    print("=" * 70)
    print("\nThese tests use mocks to verify routing without making real API calls.")
    print("\nTo run all mock tests:")
    print("  pytest nodes/tests/test_bluesky_node_mocked.py -v")
    print("=" * 70 + "\n")

    pytest.main([__file__, "-v"])
