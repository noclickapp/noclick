"""
Integration tests for Mailchimp Marketing API node.

Tests the Mailchimp API node functionality with real API credentials.
All tests use actual API calls to verify functionality.

Test Coverage:
- Basic Operations (ping, account info)
- Lists/Audiences (listing)
- Campaigns (listing)
- Automations (listing)
- Templates (listing)
- Error Handling (invalid list ID)

Uses a real Mailchimp API Key from environment variables.
Tests are designed to be non-destructive (read-only operations).
"""

import asyncio
import json
import os
import pytest
from pathlib import Path
from unittest.mock import Mock
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Import the node and credential classes
from nodes.mailchimp_node import (
    MailchimpNode,
    MailchimpNodeConfig,
    MailchimpAPIKeyCredential,
    # Marketing API config classes used in tests
    # Lists/Audiences
    MailchimpListListsConfig,
    MailchimpGetListConfig,
    # Campaigns
    MailchimpListCampaignsConfig,
    # Automations
    MailchimpListAutomationsConfig,
    # Templates
    MailchimpListTemplatesConfig,
    # Account/Root
    MailchimpGetAccountInfoConfig,
    MailchimpPingConfig,
)


@pytest.fixture
def mailchimp_credentials():
    """Get Mailchimp credentials from environment."""
    api_key = os.getenv('MAILCHIMP_API_KEY')

    if not api_key:
        pytest.skip("MAILCHIMP_API_KEY not set in environment")

    return MailchimpAPIKeyCredential(api_key=api_key)


def create_mailchimp_node(config):
    """Create a Mailchimp node instance with the given config."""
    node = MailchimpNode(
        node_id="test-mailchimp-node",
        node_type="automation-mailchimp",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user"
    )
    return node




class TestMailchimpBasicOperations:
    """Test basic Mailchimp operations like ping and account info."""

    @pytest.mark.asyncio
    async def test_ping(self, mailchimp_credentials):
        """Test the ping endpoint to verify API connectivity."""
        config = MailchimpNodeConfig(
            config=MailchimpPingConfig(),
            credentials=mailchimp_credentials
        )
        mailchimp_node = create_mailchimp_node(config)

        result = await mailchimp_node.execute({})

        assert result['status'] == 'success'
        assert 'health_status' in result['data']

    @pytest.mark.asyncio
    async def test_get_account_info(self, mailchimp_credentials):
        """Test getting account information."""
        config = MailchimpNodeConfig(
            config=MailchimpGetAccountInfoConfig(),
            credentials=mailchimp_credentials
        )
        mailchimp_node = create_mailchimp_node(config)

        result = await mailchimp_node.execute({})

        assert result['status'] == 'success'
        assert 'account_id' in result['data']
        assert 'account_name' in result['data']


class TestMailchimpListsOperations:
    """Test Mailchimp lists/audiences operations."""

    @pytest.mark.asyncio
    async def test_list_lists(self, mailchimp_credentials):
        """Test listing all audience lists."""
        config = MailchimpNodeConfig(
            config=MailchimpListListsConfig(count=10, offset=0),
            credentials=mailchimp_credentials
        )
        mailchimp_node = create_mailchimp_node(config)

        result = await mailchimp_node.execute({})

        assert result['status'] == 'success'
        assert 'lists' in result['data']
        if result['data']['lists']:
            assert 'lists_formatted' in result['data']



class TestMailchimpCampaignOperations:
    """Test Mailchimp campaign operations."""

    @pytest.mark.asyncio
    async def test_list_campaigns(self, mailchimp_credentials):
        """Test listing campaigns."""
        config = MailchimpNodeConfig(
            config=MailchimpListCampaignsConfig(count=10, offset=0),
            credentials=mailchimp_credentials
        )
        mailchimp_node = create_mailchimp_node(config)

        result = await mailchimp_node.execute({})

        assert result['status'] == 'success'
        assert 'campaigns' in result['data']


class TestMailchimpAutomationOperations:
    """Test Mailchimp automation operations."""

    @pytest.mark.asyncio
    async def test_list_automations(self, mailchimp_credentials):
        """Test listing automations."""
        config = MailchimpNodeConfig(
            config=MailchimpListAutomationsConfig(count=10, offset=0),
            credentials=mailchimp_credentials
        )
        mailchimp_node = create_mailchimp_node(config)

        result = await mailchimp_node.execute({})

        assert result['status'] == 'success'
        assert 'automations' in result['data']


class TestMailchimpTemplateOperations:
    """Test Mailchimp template operations."""

    @pytest.mark.asyncio
    async def test_list_templates(self, mailchimp_credentials):
        """Test listing templates."""
        config = MailchimpNodeConfig(
            config=MailchimpListTemplatesConfig(count=10, offset=0),
            credentials=mailchimp_credentials
        )
        mailchimp_node = create_mailchimp_node(config)

        result = await mailchimp_node.execute({})

        assert result['status'] == 'success'
        assert 'templates' in result['data']


class TestMailchimpErrorHandling:
    """Test error handling for invalid requests."""

    @pytest.mark.asyncio
    async def test_invalid_list_id(self, mailchimp_credentials):
        """Test error handling for invalid list ID."""
        config = MailchimpNodeConfig(
            config=MailchimpGetListConfig(list_id="invalid_list_id"),
            credentials=mailchimp_credentials
        )
        mailchimp_node = create_mailchimp_node(config)

        result = await mailchimp_node.execute({})

        assert result['status'] == 'error'
        assert 'error' in result



# NOTE: Additional test classes would be added here for:
# - TestMailchimpTagOperations
# - TestMailchimpSegmentOperations
# - TestMailchimpMergeFieldOperations
# - TestMailchimpInterestOperations
# - TestMailchimpReportOperations
# - TestMailchimpEcommerceOperations
# - TestMailchimpBatchOperations
# - TestMailchimpWebhookOperations
# - TestMailchimpFileManagerOperations
# - TestMailchimpSignupFormOperations
# - TestMailchimpFolderOperations
# - More Mandrill operations (send email, send template, etc.)
#
# Each class would contain comprehensive tests for all operations in that category.
# Due to the large number of operations (384 total), this test file serves as a
# foundation that can be extended with additional test methods as needed.
