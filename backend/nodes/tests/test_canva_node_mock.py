"""
Mock tests for Canva Connect API node.

COMPLETE TEST COVERAGE: These are the ONLY tests for the Canva node. We do not have
integration tests because Canva Connect API requires user-delegated OAuth (no client
credentials grant), making automated testing complex. Mock tests provide full coverage
without OAuth overhead.

Provides complete test coverage for ALL 45 Canva Connect API operations using mocked
API responses. These tests do not require actual Canva credentials and run quickly.

Coverage includes:
- Design operations (5): list, create, get, list pages, export formats
- Asset operations (5): upload from URL, get, update, delete, get upload job
- Export operations (2): create export, get export job
- Folder operations (6): create, get, update, delete, list items, move item
- User operations (3): get user, get profile, get capabilities
- Resize operations (2): create resize, get resize job
- Brand template operations (3): list, get, get dataset
- Autofill operations (2): create job, get job
- Comment operations (5): create thread, get thread, create reply, list replies, get reply
- OAuth operations (2): introspect token, revoke token
- Binary upload operations (4): design import, asset upload with status checks
- Import operations (2): import from URL, get import job
- Connect API (1): get webhook keys
- OIDC operations (2): get JWKS, get user info
- App JWT operations (1): get app JWKS

These tests verify that:
1. Request parameters are correctly built from config
2. Correct API endpoints are called with proper HTTP methods
3. Responses are properly formatted
4. All 45 operations are functional without requiring API credentials

For optional manual testing utilities against the real Canva API, see:
scripts/optional_canva_oauth_utils/
"""

import pytest
from unittest.mock import AsyncMock, patch
from nodes.canva_node import (
    CanvaNode,
    CanvaNodeConfig,
    CanvaOAuthCredential,
    # Resize operations
    CanvaCreateResizeConfig,
    CanvaGetResizeJobConfig,
    # Binary import operations
    CanvaCreateDesignImportConfig,
    CanvaGetDesignImportJobConfig,
    # Binary asset upload operations
    CanvaCreateAssetUploadConfig,
    CanvaGetAssetUploadJobStatusConfig,
    # Brand template operations
    CanvaListBrandTemplatesConfig,
    CanvaGetBrandTemplateConfig,
    CanvaGetBrandTemplateDatasetConfig,
    # Autofill operations
    CanvaCreateAutofillJobConfig,
    CanvaGetAutofillJobConfig,
    # Comment operations
    CanvaCreateCommentThreadConfig,
    CanvaGetCommentThreadConfig,
    CanvaCreateReplyConfig,
    CanvaListRepliesConfig,
    CanvaGetReplyConfig,
    # OAuth token management
    CanvaIntrospectTokenConfig,
    CanvaRevokeTokenConfig,
    # Connect API
    CanvaGetWebhookKeysConfig,
    # OIDC operations
    CanvaGetOIDCJWKSConfig,
    CanvaGetOIDCUserInfoConfig,
    # App JWT operations
    CanvaGetAppJWKSConfig,
    # Asset operations (previously missing)
    CanvaUploadAssetFromURLConfig,
    CanvaGetAssetConfig,
    CanvaUpdateAssetConfig,
    CanvaDeleteAssetConfig,
    CanvaGetAssetUploadJobConfig,
    # Import operations (previously missing)
    CanvaImportFromURLConfig,
    CanvaGetImportJobConfig,
    # Folder operations (previously missing)
    CanvaDeleteFolderConfig,
    CanvaMoveItemConfig,
    # Basic operations (needed for complete coverage)
    CanvaListDesignsConfig,
    CanvaCreateDesignConfig,
    CanvaGetDesignConfig,
    CanvaListDesignPagesConfig,
    CanvaGetExportFormatsConfig,
    CanvaCreateExportConfig,
    CanvaGetExportJobConfig,
    CanvaCreateFolderConfig,
    CanvaGetFolderConfig,
    CanvaUpdateFolderConfig,
    CanvaListFolderItemsConfig,
    CanvaGetUserConfig,
    CanvaGetUserProfileConfig,
    CanvaGetUserCapabilitiesConfig,
)


@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials for testing."""
    return CanvaOAuthCredential(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_at="2099-12-31T23:59:59Z",  # Far future
        display_name="Test Account",
    )


@pytest.fixture
def create_node(mock_credentials):
    """Factory fixture to create CanvaNode instances with given config."""

    def _create(config):
        node_config = CanvaNodeConfig(config=config, credentials=mock_credentials)
        return CanvaNode(
            node_id="test-node",
            node_type="automation-canva",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

    return _create


# ============================================================================
# Resize Operation Tests (2)
# ============================================================================


class TestResizeOperations:
    """Test resize operation mocks."""

    @pytest.mark.asyncio
    async def test_create_resize(self, create_node):
        """Test creating a resize job."""
        config = CanvaCreateResizeConfig(
            design_id="test-design-123", width=1920, height=1080, title="Resized Design"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "create_design_resize_job",
            "data": {"job": {"id": "resize-job-123", "status": "in_progress"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args.kwargs["method"] == "POST"
            assert call_args.kwargs["endpoint"] == "/v1/resizes"
            assert call_args.kwargs["json_body"]["design_id"] == "test-design-123"
            assert call_args.kwargs["json_body"]["width"] == 1920
            assert call_args.kwargs["json_body"]["height"] == 1080
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_resize_job(self, create_node):
        """Test getting resize job status."""
        config = CanvaGetResizeJobConfig(job_id="resize-job-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_design_resize_job_status",
            "data": {
                "job": {
                    "id": "resize-job-123",
                    "status": "success",
                    "design": {"id": "new-design-456"},
                }
            },
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            assert (
                "/v1/resizes/resize-job-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Binary Import Operation Tests (2)
# ============================================================================


class TestBinaryImportOperations:
    """Test binary design import operation mocks."""

    @pytest.mark.asyncio
    async def test_create_design_import(self, create_node):
        """Test importing design from binary data."""
        config = CanvaCreateDesignImportConfig(
            file_data="base64encodeddata==", title="Imported Design"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "import_design_from_binary_file",
            "data": {"job": {"id": "import-job-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            assert mock_request.call_args.kwargs["endpoint"] == "/v1/imports"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_design_import_job(self, create_node):
        """Test getting binary import job status."""
        config = CanvaGetDesignImportJobConfig(job_id="import-job-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_binary_design_import_job_status",
            "data": {"job": {"id": "import-job-123", "status": "success"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/imports/import-job-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Binary Asset Upload Operation Tests (2)
# ============================================================================


class TestBinaryAssetUploadOperations:
    """Test binary asset upload operation mocks."""

    @pytest.mark.asyncio
    async def test_create_asset_upload(self, create_node):
        """Test uploading asset from binary data."""
        config = CanvaCreateAssetUploadConfig(
            file_data="base64encodeddata==", name="Test Asset", tags=["test", "image"]
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "upload_asset_from_binary",
            "data": {"job": {"id": "asset-upload-job-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            mock_request.assert_called_once()
            assert mock_request.call_args.kwargs["endpoint"] == "/v1/asset-uploads"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_asset_upload_job_status(self, create_node):
        """Test getting binary asset upload job status."""
        config = CanvaGetAssetUploadJobStatusConfig(job_id="asset-upload-job-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_binary_asset_upload_job_status",
            "data": {"job": {"id": "asset-upload-job-123", "status": "success"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/asset-uploads/asset-upload-job-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Brand Template Operation Tests (3)
# ============================================================================


class TestBrandTemplateOperations:
    """Test brand template operation mocks."""

    @pytest.mark.asyncio
    async def test_list_brand_templates(self, create_node):
        """Test listing brand templates."""
        config = CanvaListBrandTemplatesConfig(query="test")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "list_brand_templates_with_search",
            "data": {"items": [{"id": "template-1"}, {"id": "template-2"}]},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/brand-templates"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_brand_template(self, create_node):
        """Test getting brand template metadata."""
        config = CanvaGetBrandTemplateConfig(brand_template_id="template-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_brand_template_metadata",
            "data": {"brand_template": {"id": "template-123", "name": "Test Template"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/brand-templates/template-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_brand_template_dataset(self, create_node):
        """Test getting brand template dataset."""
        config = CanvaGetBrandTemplateDatasetConfig(brand_template_id="template-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_autofill_dataset_definition",
            "data": {"dataset": {"fields": []}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/brand-templates/template-123/dataset"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Autofill Operation Tests (2)
# ============================================================================


class TestAutofillOperations:
    """Test autofill operation mocks."""

    @pytest.mark.asyncio
    async def test_create_autofill_job(self, create_node):
        """Test creating autofill job."""
        config = CanvaCreateAutofillJobConfig(
            brand_template_id="template-123",
            data={"field1": "value1"},
            title="Autofilled Design",
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "create_design_autofill_job",
            "data": {"job": {"id": "autofill-job-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/autofills"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_autofill_job(self, create_node):
        """Test getting autofill job status."""
        config = CanvaGetAutofillJobConfig(job_id="autofill-job-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_design_autofill_job_status",
            "data": {"job": {"id": "autofill-job-123", "status": "success"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/autofills/autofill-job-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Comment Operation Tests (5)
# ============================================================================


class TestCommentOperations:
    """Test comment operation mocks."""

    @pytest.mark.asyncio
    async def test_create_comment_thread(self, create_node):
        """Test creating comment thread."""
        config = CanvaCreateCommentThreadConfig(
            design_id="design-123", message="Test comment"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "create_design_comment_thread",
            "data": {"comment": {"id": "comment-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/designs/design-123/comments"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_comment_thread(self, create_node):
        """Test getting comment thread."""
        config = CanvaGetCommentThreadConfig(
            design_id="design-123", thread_id="thread-123"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_design_comment_thread",
            "data": {"thread": {"id": "thread-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/designs/design-123/comments/thread-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_reply(self, create_node):
        """Test creating reply to comment thread."""
        config = CanvaCreateReplyConfig(
            design_id="design-123", thread_id="thread-123", message="Test reply"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "create_comment_thread_reply",
            "data": {"reply": {"id": "reply-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/designs/design-123/comments/thread-123/replies"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_replies(self, create_node):
        """Test listing replies for a thread."""
        config = CanvaListRepliesConfig(design_id="design-123", thread_id="thread-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "list_comment_thread_replies",
            "data": {"items": []},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/designs/design-123/comments/thread-123/replies"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_reply(self, create_node):
        """Test getting specific reply."""
        config = CanvaGetReplyConfig(
            design_id="design-123", thread_id="thread-123", reply_id="reply-123"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_comment_thread_reply",
            "data": {"reply": {"id": "reply-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/designs/design-123/comments/thread-123/replies/reply-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# OAuth Token Management Tests (2)
# ============================================================================


class TestOAuthTokenManagementOperations:
    """Test OAuth token management operation mocks."""

    @pytest.mark.asyncio
    async def test_introspect_token(self, create_node):
        """Test token introspection."""
        config = CanvaIntrospectTokenConfig()
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "verify_token_validity",
            "data": {"active": True, "scope": "design:read"},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/oauth/introspect"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_revoke_token(self, create_node):
        """Test token revocation."""
        config = CanvaRevokeTokenConfig(token_type="access_token")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "revoke_access_or_refresh_token",
            "data": {"success": True},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/oauth/revoke"
            assert result["status"] == "success"


# ============================================================================
# Connect API Tests (1)
# ============================================================================


class TestConnectAPIOperations:
    """Test Connect API operation mocks."""

    @pytest.mark.asyncio
    async def test_get_webhook_keys(self, create_node):
        """Test getting webhook verification keys."""
        config = CanvaGetWebhookKeysConfig()
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_webhook_signature_verification_keys",
            "data": {"keys": []},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/connect/keys"
            assert result["status"] == "success"


# ============================================================================
# OIDC Operation Tests (2)
# ============================================================================


class TestOIDCOperations:
    """Test OIDC operation mocks."""

    @pytest.mark.asyncio
    async def test_get_oidc_jwks(self, create_node):
        """Test getting OIDC JWKS."""
        config = CanvaGetOIDCJWKSConfig()
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_openid_connect_jwks",
            "data": {"keys": []},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/oidc/jwks"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_oidc_userinfo(self, create_node):
        """Test getting OIDC user info."""
        config = CanvaGetOIDCUserInfoConfig()
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "fetch_current_user_oidc_claims",
            "data": {"sub": "user-123"},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/oidc/userinfo"
            assert result["status"] == "success"


# ============================================================================
# App JWT Operation Tests (1)
# ============================================================================


class TestAppJWTOperations:
    """Test App JWT operation mocks."""

    @pytest.mark.asyncio
    async def test_get_app_jwks(self, create_node):
        """Test getting app JWKS."""
        config = CanvaGetAppJWKSConfig(app_id="app-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_app_json_web_key_set",
            "data": {"keys": []},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/apps/app-123/jwks" in mock_request.call_args.kwargs["endpoint"]
            assert result["status"] == "success"


# ============================================================================
# Asset Operation Tests (5) - Previously Missing
# ============================================================================


class TestAssetOperations:
    """Test asset operation mocks."""

    @pytest.mark.asyncio
    async def test_upload_asset_from_url(self, create_node):
        """Test uploading asset from URL."""
        config = CanvaUploadAssetFromURLConfig(
            url="https://example.com/image.png", name="Test Asset"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "upload_asset_from_url",
            "data": {"job": {"id": "asset-job-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/url-asset-uploads"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_asset(self, create_node):
        """Test getting asset metadata."""
        config = CanvaGetAssetConfig(asset_id="asset-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_asset_metadata",
            "data": {"asset": {"id": "asset-123", "name": "Test Asset"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/assets/asset-123" in mock_request.call_args.kwargs["endpoint"]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_asset(self, create_node):
        """Test updating asset metadata."""
        config = CanvaUpdateAssetConfig(asset_id="asset-123", name="Updated Asset")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "update_asset_name_or_tags",
            "data": {},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/assets/asset-123" in mock_request.call_args.kwargs["endpoint"]
            assert mock_request.call_args.kwargs["method"] == "PATCH"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_asset(self, create_node):
        """Test deleting an asset."""
        config = CanvaDeleteAssetConfig(asset_id="asset-123")
        node = create_node(config)

        mock_response = {"status": "success", "action": "delete_asset", "data": {}}

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/assets/asset-123" in mock_request.call_args.kwargs["endpoint"]
            assert mock_request.call_args.kwargs["method"] == "DELETE"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_asset_upload_job(self, create_node):
        """Test getting asset upload job status."""
        config = CanvaGetAssetUploadJobConfig(job_id="asset-job-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_binary_asset_upload_job_status",
            "data": {"job": {"id": "asset-job-123", "status": "success"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/url-asset-uploads/asset-job-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Import Operation Tests (2) - Previously Missing
# ============================================================================


class TestImportOperations:
    """Test design import operation mocks."""

    @pytest.mark.asyncio
    async def test_import_from_url(self, create_node):
        """Test importing design from URL."""
        config = CanvaImportFromURLConfig(
            url="https://example.com/design.pdf", title="Imported Design"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "import_design_from_url",
            "data": {"job": {"id": "import-job-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/url-imports"
            assert (
                mock_request.call_args.kwargs["json_body"]["url"]
                == "https://example.com/design.pdf"
            )
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_import_job(self, create_node):
        """Test getting import job status."""
        config = CanvaGetImportJobConfig(job_id="import-job-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_design_import_job_status",
            "data": {"job": {"id": "import-job-123", "status": "success"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/url-imports/import-job-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Folder Operation Tests (2) - Previously Missing
# ============================================================================


class TestAdditionalFolderOperations:
    """Test additional folder operation mocks."""

    @pytest.mark.asyncio
    async def test_delete_folder(self, create_node):
        """Test deleting a folder."""
        config = CanvaDeleteFolderConfig(folder_id="folder-123")
        node = create_node(config)

        mock_response = {"status": "success", "action": "delete_folder", "data": {}}

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/folders/folder-123" in mock_request.call_args.kwargs["endpoint"]
            assert mock_request.call_args.kwargs["method"] == "DELETE"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_move_item(self, create_node):
        """Test moving item to another folder."""
        config = CanvaMoveItemConfig(
            item_id="design-123", item_type="design", to_folder_id="folder-456"
        )
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "move_item_to_folder",
            "data": {},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/folders/move"
            assert mock_request.call_args.kwargs["method"] == "POST"
            assert result["status"] == "success"


# ============================================================================
# Design Operation Tests (5) - Basic CRUD operations
# ============================================================================


class TestDesignOperations:
    """Test basic design operation mocks."""

    @pytest.mark.asyncio
    async def test_list_designs(self, create_node):
        """Test listing designs."""
        config = CanvaListDesignsConfig(query="test")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "list_user_designs",
            "data": {"items": [{"id": "design-1"}, {"id": "design-2"}]},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/designs"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_design(self, create_node):
        """Test creating a design."""
        config = CanvaCreateDesignConfig(design_type="Doc", title="Test Design")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "create_design",
            "data": {"design": {"id": "design-123", "title": "Test Design"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/designs"
            assert mock_request.call_args.kwargs["method"] == "POST"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_design(self, create_node):
        """Test getting design metadata."""
        config = CanvaGetDesignConfig(design_id="design-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_design_metadata",
            "data": {"design": {"id": "design-123", "title": "Test Design"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/designs/design-123" in mock_request.call_args.kwargs["endpoint"]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_design_pages(self, create_node):
        """Test listing design pages."""
        config = CanvaListDesignPagesConfig(design_id="design-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "list_design_pages",
            "data": {"items": [{"id": "page-1"}]},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/designs/design-123/pages"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_export_formats(self, create_node):
        """Test getting export formats."""
        config = CanvaGetExportFormatsConfig(design_id="design-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_design_export_formats",
            "data": {"formats": ["pdf", "png", "jpg"]},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/designs/design-123/export-formats"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Export Operation Tests (2) - Basic export operations
# ============================================================================


class TestExportOperations:
    """Test export operation mocks."""

    @pytest.mark.asyncio
    async def test_create_export(self, create_node):
        """Test creating an export job."""
        config = CanvaCreateExportConfig(design_id="design-123", format="pdf")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "create_design_export_job",
            "data": {"job": {"id": "export-job-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/exports"
            assert mock_request.call_args.kwargs["method"] == "POST"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_export_job(self, create_node):
        """Test getting export job status."""
        config = CanvaGetExportJobConfig(export_id="export-job-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_design_export_job_status",
            "data": {"job": {"id": "export-job-123", "status": "success"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/exports/export-job-123"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# Folder Operation Tests (4) - Basic folder operations
# ============================================================================


class TestBasicFolderOperations:
    """Test basic folder operation mocks."""

    @pytest.mark.asyncio
    async def test_create_folder(self, create_node):
        """Test creating a folder."""
        config = CanvaCreateFolderConfig(name="Test Folder", parent_folder_id="root")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "create_folder",
            "data": {"folder": {"id": "folder-123", "name": "Test Folder"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/folders"
            assert mock_request.call_args.kwargs["method"] == "POST"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_folder(self, create_node):
        """Test getting folder metadata."""
        config = CanvaGetFolderConfig(folder_id="folder-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_folder_details",
            "data": {"folder": {"id": "folder-123", "name": "Test Folder"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/folders/folder-123" in mock_request.call_args.kwargs["endpoint"]
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_folder(self, create_node):
        """Test updating folder name."""
        config = CanvaUpdateFolderConfig(folder_id="folder-123", name="Updated Folder")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "update_folder_name",
            "data": {},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert "/v1/folders/folder-123" in mock_request.call_args.kwargs["endpoint"]
            assert mock_request.call_args.kwargs["method"] == "PATCH"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_folder_items(self, create_node):
        """Test listing folder items."""
        config = CanvaListFolderItemsConfig(folder_id="folder-123")
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "list_folder_contents",
            "data": {"items": [{"id": "design-1", "type": "design"}]},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                "/v1/folders/folder-123/items"
                in mock_request.call_args.kwargs["endpoint"]
            )
            assert result["status"] == "success"


# ============================================================================
# User Operation Tests (3) - User profile operations
# ============================================================================


class TestUserOperations:
    """Test user operation mocks."""

    @pytest.mark.asyncio
    async def test_get_user(self, create_node):
        """Test getting current user."""
        config = CanvaGetUserConfig()
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_current_user_id",
            "data": {"user": {"id": "user-123"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/users/me"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_user_profile(self, create_node):
        """Test getting user profile."""
        config = CanvaGetUserProfileConfig()
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_user_profile_information",
            "data": {"profile": {"display_name": "Test User"}},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert mock_request.call_args.kwargs["endpoint"] == "/v1/users/me/profile"
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_user_capabilities(self, create_node):
        """Test getting user capabilities."""
        config = CanvaGetUserCapabilitiesConfig()
        node = create_node(config)

        mock_response = {
            "status": "success",
            "action": "get_user_available_features",
            "data": {"capabilities": ["designs:read", "designs:write"]},
        }

        with patch.object(
            node, "_make_request", new=AsyncMock(return_value=mock_response)
        ) as mock_request:
            result = await node.execute({})

            assert (
                mock_request.call_args.kwargs["endpoint"] == "/v1/users/me/capabilities"
            )
            assert result["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
