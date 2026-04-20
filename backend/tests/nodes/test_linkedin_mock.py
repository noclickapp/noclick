"""
Mock tests for LinkedIn API node.

Verifies that the correct LinkedIn-Version header is sent on all API requests
and that the create_text_post operation succeeds end-to-end with a mocked HTTP
response. No real HTTP calls are made.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nodes.linkedin_node import (
    LinkedInNode,
    LinkedInNodeConfig,
    LinkedInOAuthCredential,
    LinkedInCreateTextPostConfig,
    LINKEDIN_API_VERSION,
)


TEST_ACCESS_TOKEN = "test-access-token"
TEST_MEMBER_ID = "urn:li:person:abc123"


def make_credentials():
    return LinkedInOAuthCredential(
        access_token=TEST_ACCESS_TOKEN,
        sub=TEST_MEMBER_ID,
    )


def make_node(config) -> LinkedInNode:
    node_config = LinkedInNodeConfig(config=config, credentials=make_credentials())
    return LinkedInNode(
        node_id="test-node",
        node_type="automation-linkedin",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


# ---------------------------------------------------------------------------
# Version header tests
# ---------------------------------------------------------------------------

class TestLinkedInApiVersion:
    """Ensure the LinkedIn-Version header matches the expected active version."""

    def test_version_constant_format(self):
        """Version must be 6-digit YYYYMM string."""
        assert len(LINKEDIN_API_VERSION) == 6, (
            f"LinkedIn API version should be 6 chars (YYYYMM), got {LINKEDIN_API_VERSION!r}"
        )
        assert LINKEDIN_API_VERSION.isdigit(), (
            f"LinkedIn API version should be numeric, got {LINKEDIN_API_VERSION!r}"
        )

    def test_version_is_not_deprecated(self):
        """Version must not be one of the known-deprecated versions that return HTTP 426."""
        deprecated = {"202501", "202502", "202503", "202504"}
        assert LINKEDIN_API_VERSION not in deprecated, (
            f"LinkedIn API version {LINKEDIN_API_VERSION!r} is deprecated and will return HTTP 426. "
            "Update LINKEDIN_API_VERSION to a current active version (e.g. '202604')."
        )

    def test_version_header_sent_in_request(self):
        """LinkedIn-Version header must be included in every outgoing request."""
        captured_headers = {}

        async def fake_request(method, url, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.content = b'{"id": "post123"}'
            mock_resp.json.return_value = {"id": "post123"}
            mock_resp.headers = {"x-restli-id": "urn:li:share:post123"}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        import asyncio

        async def run():
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client.request = fake_request

                config = LinkedInCreateTextPostConfig(commentary="Hello LinkedIn!")
                node = make_node(config)
                node.emit = AsyncMock()
                await node.execute({})

            assert "LinkedIn-Version" in captured_headers, (
                "LinkedIn-Version header was not sent in the API request"
            )
            assert captured_headers["LinkedIn-Version"] == LINKEDIN_API_VERSION, (
                f"Expected LinkedIn-Version={LINKEDIN_API_VERSION!r}, "
                f"got {captured_headers['LinkedIn-Version']!r}"
            )

        asyncio.get_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
# create_text_post operation tests
# ---------------------------------------------------------------------------

class TestCreateTextPost:
    """Tests for the create_text_post LinkedIn operation."""

    @pytest.mark.asyncio
    async def test_create_text_post_success(self):
        """A successful post creation returns status 'success' with post_id."""
        post_urn = "urn:li:share:7123456789"

        async def fake_request(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.content = b"{}"
            mock_resp.json.return_value = {}
            mock_resp.headers = {"x-restli-id": post_urn}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.request = fake_request

            config = LinkedInCreateTextPostConfig(commentary="Hello from NoClick!")
            node = make_node(config)
            emitted = []
            node.emit = AsyncMock(side_effect=lambda data: emitted.append(data))

            await node.execute({})

        assert len(emitted) == 1
        result = emitted[0]
        assert result["status"] == "success", f"Expected success, got: {result}"
        assert result["action"] == "create_text_post"
        assert result["data"]["id"] == post_urn

    @pytest.mark.asyncio
    async def test_create_text_post_version_error_returns_error_status(self):
        """HTTP 426 (version error) is surfaced as status='error', not raised as exception."""
        async def fake_request(method, url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 426
            mock_resp.content = b'{"message": "Requested version 20250101 is not active"}'
            mock_resp.json.return_value = {"message": "Requested version 20250101 is not active"}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.request = fake_request

            config = LinkedInCreateTextPostConfig(commentary="Test post")
            node = make_node(config)
            emitted = []
            node.emit = AsyncMock(side_effect=lambda data: emitted.append(data))

            await node.execute({})

        assert len(emitted) == 1
        result = emitted[0]
        assert result["status"] == "error"
        assert result["status_code"] == 426
        assert "not active" in result["error"]
