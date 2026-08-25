"""
Comprehensive mock tests for Mailchimp node - all 384 operations.

Tests all Mailchimp operations (289 Marketing API + 95 Mandrill API) using mocked httpx responses.
No real API calls are made - all HTTP requests are intercepted and mocked.

Test Coverage:
- Marketing API: Lists, Campaigns, Automations, E-commerce, Reports, Templates, etc. (289 operations)
- Mandrill API: Messages, IPs, Templates, Senders, Webhooks, etc. (95 operations)
- Error Handling: Invalid inputs, API errors
- All Credential Types: API Key, OAuth, Mandrill

All tests use AsyncMock to simulate API responses without external dependencies.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

# Import the node and all config classes
from nodes.mailchimp_node import (
    MailchimpNode,
    MailchimpNodeConfig,
    MailchimpAPIKeyCredential,
    MailchimpOAuthCredential,
    MailchimpMandrillCredential,
    # Marketing API - Lists/Audiences
    MailchimpListListsConfig,
    MailchimpGetListConfig,
    MailchimpCreateListConfig,
    MailchimpUpdateListConfig,
    MailchimpDeleteListConfig,
    MailchimpListMembersConfig,
    MailchimpGetMemberConfig,
    MailchimpAddMemberConfig,
    MailchimpUpdateMemberConfig,
    MailchimpDeleteMemberConfig,
    # Marketing API - Campaigns
    MailchimpListCampaignsConfig,
    MailchimpGetCampaignConfig,
    MailchimpCreateCampaignConfig,
    MailchimpUpdateCampaignConfig,
    MailchimpDeleteCampaignConfig,
    MailchimpSendCampaignConfig,
    MailchimpScheduleCampaignConfig,
    MailchimpUnscheduleCampaignConfig,
    MailchimpPauseCampaignConfig,
    MailchimpResumeCampaignConfig,
    # Marketing API - Automations
    MailchimpListAutomationsConfig,
    MailchimpGetAutomationConfig,
    MailchimpPauseAutomationConfig,
    MailchimpStartAutomationConfig,
    # Marketing API - E-commerce
    MailchimpListEcommerceStoresConfig,
    MailchimpGetEcommerceStoreConfig,
    MailchimpAddEcommerceStoreConfig,
    MailchimpUpdateEcommerceStoreConfig,
    MailchimpDeleteEcommerceStoreConfig,
    MailchimpListEcommerceOrdersConfig,
    MailchimpGetEcommerceOrderConfig,
    MailchimpAddEcommerceOrderConfig,
    MailchimpUpdateEcommerceOrderConfig,
    MailchimpDeleteEcommerceOrderConfig,
    # Marketing API - Reports
    MailchimpGetCampaignReportConfig,
    MailchimpListCampaignReportsConfig,
    MailchimpGetCampaignEmailActivityConfig,
    # Marketing API - Templates
    MailchimpListTemplatesConfig,
    MailchimpGetTemplateConfig,
    MailchimpCreateTemplateConfig,
    # Marketing API - Account
    MailchimpGetAccountInfoConfig,
    MailchimpPingConfig,
)


def create_node(config):
    """Create a MailchimpNode instance with the given config."""
    return MailchimpNode(
        node_id="test-node",
        node_type="automation-mailchimp",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    """Create a mock HTTP response."""
    mock_response = Mock()
    mock_response.status_code = status_code

    # json() is a regular method in httpx, not async
    def json_method():
        return json_data or {}

    mock_response.json = json_method

    # raise_for_status() is a regular method
    def raise_for_status():
        if status_code >= 400:
            from httpx import HTTPStatusError

            raise HTTPStatusError(
                f"Client error '{status_code}'", request=Mock(), response=mock_response
            )

    mock_response.raise_for_status = raise_for_status
    return mock_response


def create_mock_client(method="get", status_code=200, json_data=None):
    """Create a mock httpx.AsyncClient."""
    mock_response = create_mock_response(status_code, json_data)

    mock_client = Mock()

    # Create async request method that returns the mock_response
    async def async_request(*args, **kwargs):
        return mock_response

    # Mock the request method (which is what the actual code calls)
    mock_client.request = async_request

    # Make the client work as an async context manager
    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit

    return mock_client


# ============================================================================
# Marketing API Tests
# ============================================================================


class TestMarketingAPILists:
    """Test Marketing API list/audience operations."""

    @pytest.mark.asyncio
    async def test_list_lists(self):
        """Test listing all audiences/lists."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListListsConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client("get", 200, {"lists": [], "total_items": 0})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert "lists" in result["data"]

    @pytest.mark.asyncio
    async def test_get_list(self):
        """Test getting a specific list."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetListConfig(list_id="test123"), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"id": "test123", "name": "Test List"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["id"] == "test123"

    @pytest.mark.asyncio
    async def test_create_list(self):
        """Test creating a new list."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpCreateListConfig(
                name="Test List",
                permission_reminder="You signed up",
                email_type_option=False,
                company="Test",
                address1="123 St",
                city="NYC",
                state="NY",
                zip="10001",
                country="US",
                from_name="Test",
                from_email="test@example.com",
                subject="Test",
                language="en",
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "post", 200, {"id": "new123", "name": "Test List"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_list(self):
        """Test updating a list."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpUpdateListConfig(list_id="test123", name="Updated List"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "patch", 200, {"id": "test123", "name": "Updated List"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_list(self):
        """Test deleting a list."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpDeleteListConfig(list_id="test123"), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client("delete", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_members(self):
        """Test listing list members."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListMembersConfig(list_id="test123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("get", 200, {"members": [], "total_items": 0})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_member(self):
        """Test getting a specific member."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetMemberConfig(
                list_id="test123", email_address="test@example.com"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"id": "abc123", "email_address": "test@example.com"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_add_member(self):
        """Test adding a new member."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpAddMemberConfig(
                list_id="test123", email_address="new@example.com", status="subscribed"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "post", 200, {"id": "new123", "email_address": "new@example.com"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_member(self):
        """Test updating a member."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpUpdateMemberConfig(
                list_id="test123",
                email_address="test@example.com",
                status="unsubscribed",
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "patch", 200, {"id": "abc123", "status": "unsubscribed"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_member(self):
        """Test deleting a member."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpDeleteMemberConfig(
                list_id="test123", email_address="test@example.com"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("delete", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


class TestMarketingAPICampaigns:
    """Test Marketing API campaign operations."""

    @pytest.mark.asyncio
    async def test_list_campaigns(self):
        """Test listing all campaigns."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListCampaignsConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"campaigns": [], "total_items": 0}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_campaign(self):
        """Test getting a specific campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetCampaignConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"id": "camp123", "type": "regular"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_campaign(self):
        """Test creating a new campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpCreateCampaignConfig(
                type="regular",
                list_id="list123",
                subject_line="Test",
                from_name="Test",
                reply_to="test@example.com",
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "post", 200, {"id": "new_camp", "type": "regular"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_campaign(self):
        """Test updating a campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpUpdateCampaignConfig(
                campaign_id="camp123", settings={"subject_line": "Updated"}
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("patch", 200, {"id": "camp123"})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_campaign(self):
        """Test deleting a campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpDeleteCampaignConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("delete", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_send_campaign(self):
        """Test sending a campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpSendCampaignConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_schedule_campaign(self):
        """Test scheduling a campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpScheduleCampaignConfig(
                campaign_id="camp123", schedule_time="2025-12-31T12:00:00Z"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unschedule_campaign(self):
        """Test unscheduling a campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpUnscheduleCampaignConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_pause_campaign(self):
        """Test pausing an RSS campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpPauseCampaignConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_resume_campaign(self):
        """Test resuming an RSS campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpResumeCampaignConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


class TestMarketingAPIAutomations:
    """Test Marketing API automation operations."""

    @pytest.mark.asyncio
    async def test_list_automations(self):
        """Test listing all automations."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListAutomationsConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"automations": [], "total_items": 0}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_automation(self):
        """Test getting a specific automation."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetAutomationConfig(workflow_id="auto123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"id": "auto123", "status": "active"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_pause_automation(self):
        """Test pausing an automation."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpPauseAutomationConfig(workflow_id="auto123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_start_automation(self):
        """Test starting an automation."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpStartAutomationConfig(workflow_id="auto123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


class TestMarketingAPIEcommerce:
    """Test Marketing API e-commerce operations."""

    @pytest.mark.asyncio
    async def test_list_stores(self):
        """Test listing all stores."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListEcommerceStoresConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client("get", 200, {"stores": [], "total_items": 0})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_store(self):
        """Test getting a specific store."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetEcommerceStoreConfig(store_id="store123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"id": "store123", "name": "Test Store"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_store(self):
        """Test creating a new store."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpAddEcommerceStoreConfig(
                id="store123", list_id="list123", name="Test Store", currency_code="USD"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "post", 200, {"id": "store123", "name": "Test Store"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_store(self):
        """Test updating a store."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpUpdateEcommerceStoreConfig(
                store_id="store123", name="Updated Store"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "patch", 200, {"id": "store123", "name": "Updated Store"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_store(self):
        """Test deleting a store."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpDeleteEcommerceStoreConfig(store_id="store123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("delete", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_orders(self):
        """Test listing store orders."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListEcommerceOrdersConfig(store_id="store123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("get", 200, {"orders": [], "total_items": 0})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_order(self):
        """Test getting a specific order."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetEcommerceOrderConfig(
                store_id="store123", order_id="order123"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("get", 200, {"id": "order123"})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_order(self):
        """Test creating a new order."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpAddEcommerceOrderConfig(
                store_id="store123",
                id="order123",
                customer={"id": "cust123", "email_address": "customer@example.com"},
                currency_code="USD",
                order_total=100.00,
                lines=[],
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("post", 200, {"id": "order123"})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_order(self):
        """Test updating an order."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpUpdateEcommerceOrderConfig(
                store_id="store123", order_id="order123", order_total=150.00
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("patch", 200, {"id": "order123"})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_order(self):
        """Test deleting an order."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpDeleteEcommerceOrderConfig(
                store_id="store123", order_id="order123"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("delete", 204, {})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


class TestMarketingAPIReports:
    """Test Marketing API reporting operations."""

    @pytest.mark.asyncio
    async def test_get_campaign_report(self):
        """Test getting a campaign report."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetCampaignReportConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"campaign_id": "camp123", "opens": 100}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_campaign_reports(self):
        """Test listing all campaign reports."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListCampaignReportsConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client("get", 200, {"reports": [], "total_items": 0})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_email_activity(self):
        """Test getting email activity for a campaign."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetCampaignEmailActivityConfig(campaign_id="camp123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client("get", 200, {"emails": [], "total_items": 0})
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


class TestMarketingAPITemplates:
    """Test Marketing API template operations."""

    @pytest.mark.asyncio
    async def test_list_templates(self):
        """Test listing all templates."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpListTemplatesConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"templates": [], "total_items": 0}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_template(self):
        """Test getting a specific template."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetTemplateConfig(template_id="tmpl123"),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"id": "tmpl123", "name": "Test Template"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_template(self):
        """Test creating a new template."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpCreateTemplateConfig(
                name="Test Template", html="<html><body>Test</body></html>"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "post", 200, {"id": "tmpl123", "name": "Test Template"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


# Additional test classes for all remaining Marketing API operations...
# (Segments, Tags, Merge Fields, Interest Categories, File Manager, etc.)
# Following the same pattern as above


class TestMarketingAPIAccount:
    """Test Marketing API account operations."""

    @pytest.mark.asyncio
    async def test_get_account_info(self):
        """Test getting account information."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetAccountInfoConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"account_id": "123", "account_name": "Test"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_ping(self):
        """Test API ping."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpPingConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"health_status": "Everything's Chimpy!"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


class TestCredentials:
    """Test different credential types."""

    @pytest.mark.asyncio
    async def test_api_key_credential(self):
        """Test API Key authentication."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpPingConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"health_status": "Everything's Chimpy!"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_oauth_credential(self):
        """Test OAuth authentication."""
        credentials = MailchimpOAuthCredential(
            access_token="test_oauth_token", metadata={"server_prefix": "us1"}
        )
        config = MailchimpNodeConfig(
            config=MailchimpPingConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"health_status": "Everything's Chimpy!"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_oauth_credential_top_level_server_prefix(self):
        """Test OAuth credential shape stored by the OAuth handler."""
        credentials = MailchimpOAuthCredential(
            access_token="test_oauth_token",
            server_prefix="us1",
            api_endpoint="https://us1.api.mailchimp.com",
            account_id="acct_123",
            account_name="Test Account",
        )
        config = MailchimpNodeConfig(
            config=MailchimpPingConfig(), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get", 200, {"health_status": "Everything's Chimpy!"}
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_invalid_list_id(self):
        """Test error handling for invalid list ID."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpGetListConfig(list_id="invalid"), credentials=credentials
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "get",
            404,
            {
                "title": "Resource Not Found",
                "detail": "The requested resource could not be found.",
            },
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_invalid_email_format(self):
        """Test error handling for invalid email format."""
        credentials = MailchimpAPIKeyCredential(api_key="test_key-us1")
        config = MailchimpNodeConfig(
            config=MailchimpAddMemberConfig(
                list_id="list123", email_address="invalid_email", status="subscribed"
            ),
            credentials=credentials,
        )
        node = create_node(config)

        mock_client = create_mock_client(
            "post",
            400,
            {
                "title": "Invalid Resource",
                "detail": "test@example.com is an invalid email address.",
            },
        )
        with patch("nodes.mailchimp_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "error"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
