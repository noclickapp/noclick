"""
Credential tests for the Instagram Graph API node that need no live account.

The mocked operation tests live in test_instagram_node_mock.py.
"""

import pytest

from nodes.instagram_node import (
    InstagramNode,
    InstagramNodeConfig,
    InstagramSystemUserTokenCredential,
    InstagramPageAccessTokenCredential,
    InstagramGetProfileConfig,
)


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = InstagramGetProfileConfig(fields="id,username")
        node_config = InstagramNodeConfig(config=config, credentials=None)
        node = InstagramNode(
            node_id="test-node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestAlternativeCredentials:
    """Test alternative credential types."""

    @pytest.mark.asyncio
    async def test_system_user_token_credential(self):
        """Test System User Token credential format."""
        credential = InstagramSystemUserTokenCredential(
            access_token="test_system_user_token_12345",
            instagram_user_id="test_user_id",
            instagram_username="test_user",
        )

        assert hasattr(credential, "access_token")
        assert hasattr(credential, "instagram_user_id")
        assert hasattr(credential, "instagram_username")
        assert credential.access_token == "test_system_user_token_12345"

    @pytest.mark.asyncio
    async def test_page_access_token_credential(self):
        """Test Page Access Token credential format."""
        credential = InstagramPageAccessTokenCredential(
            access_token="test_page_token_12345",
            instagram_user_id="test_user_id",
            page_id="test_page_id",
            instagram_username="test_user",
            expires_at=None,  # Permanent token
        )

        assert hasattr(credential, "access_token")
        assert hasattr(credential, "instagram_user_id")
        assert hasattr(credential, "page_id")
        assert hasattr(credential, "instagram_username")
        assert hasattr(credential, "expires_at")
        assert credential.access_token == "test_page_token_12345"
        assert credential.expires_at is None  # Permanent
