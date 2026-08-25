"""
Comprehensive mock tests for Instantly Node - ALL 35 Operations.

Tests all Instantly node operations using mocked httpx responses.
Organized by operation category for easy navigation.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nodes.instantly_node import (
    InstantlyNode,
    InstantlyNodeConfig,
    InstantlyAPIKeyCredential,
    delete_instantly_webhook,
    register_instantly_webhook,
    cleanup_instantly_webhook,
    # Account operations
    InstantlyListAccountsConfig,
    InstantlyGetAccountConfig,
    InstantlyCreateAccountConfig,
    InstantlyPauseAccountConfig,
    InstantlyResumeAccountConfig,
    InstantlyDeleteAccountConfig,
    # Campaign operations
    InstantlyListCampaignsConfig,
    InstantlyGetCampaignConfig,
    InstantlyCreateCampaignConfig,
    InstantlyUpdateCampaignConfig,
    InstantlyDeleteCampaignConfig,
    InstantlyActivateCampaignConfig,
    InstantlyPauseCampaignConfig,
    InstantlySearchCampaignsByContactConfig,
    # Lead operations
    InstantlyListLeadsConfig,
    InstantlyGetLeadConfig,
    InstantlyCreateLeadConfig,
    InstantlyUpdateLeadConfig,
    InstantlyDeleteLeadConfig,
    InstantlyBulkAddLeadsConfig,
    InstantlyMoveLeadConfig,
    # Lead list operations
    InstantlyListLeadListsConfig,
    InstantlyGetLeadListConfig,
    InstantlyCreateLeadListConfig,
    InstantlyUpdateLeadListConfig,
    InstantlyDeleteLeadListConfig,
    # Email operations
    InstantlyListEmailsConfig,
    InstantlyGetEmailConfig,
    InstantlyReplyToEmailConfig,
    InstantlyCountUnreadEmailsConfig,
    InstantlyMarkThreadReadConfig,
    # Analytics operations
    InstantlyGetCampaignAnalyticsConfig,
    InstantlyGetDailyCampaignAnalyticsConfig,
    InstantlyGetWarmupAnalyticsConfig,
    # Webhook
    InstantlyReceiveWebhookConfig,
)


def make_mock_response(status_code=200, json_data=None):
    """Create a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(json_data or {})
    resp.json.return_value = json_data or {}
    return resp


class TestInstantlyNodeMock:
    """Comprehensive mock tests for all Instantly node operations."""

    @pytest.fixture
    def credential(self):
        return InstantlyAPIKeyCredential(api_key="test-api-key-mock")

    def create_node(self, config, credential):
        node_config = InstantlyNodeConfig(config=config, credentials=credential)
        return InstantlyNode(
            node_id="test-node",
            node_type="automation-instantly",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

    def mock_client(self, response):
        """Create a patched httpx.AsyncClient context manager."""
        mock_client_instance = AsyncMock()
        mock_client_instance.request = AsyncMock(return_value=response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        return patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance)

    # =========================================================================
    # Account Operations (6 tests)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_accounts(self, credential):
        response = make_mock_response(200, [
            {"id": "acc-1", "email": "test@example.com", "status": "active"},
            {"id": "acc-2", "email": "test2@example.com", "status": "paused"},
        ])
        node = self.create_node(InstantlyListAccountsConfig(limit="10"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_email_accounts"
        assert len(result["data"]) == 2
        assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_get_account(self, credential):
        response = make_mock_response(200, {"email": "test@example.com", "status": 1})
        node = self.create_node(InstantlyGetAccountConfig(email="test@example.com"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_email_account"
        assert result["data"]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_create_account(self, credential):
        response = make_mock_response(200, {"id": "acc-new", "email": "new@example.com"})
        config = InstantlyCreateAccountConfig(
            email="new@example.com", first_name="New", last_name="User", provider_code="2"
        )
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_email_account"

    @pytest.mark.asyncio
    async def test_pause_account(self, credential):
        response = make_mock_response(200, {"success": True})
        node = self.create_node(InstantlyPauseAccountConfig(email="test@example.com"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "pause_email_account"

    @pytest.mark.asyncio
    async def test_resume_account(self, credential):
        response = make_mock_response(200, {"success": True})
        node = self.create_node(InstantlyResumeAccountConfig(email="test@example.com"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "resume_email_account"

    @pytest.mark.asyncio
    async def test_delete_account(self, credential):
        response = make_mock_response(204)
        node = self.create_node(InstantlyDeleteAccountConfig(email="test@example.com"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_email_account"

    # =========================================================================
    # Campaign Operations (8 tests)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_campaigns(self, credential):
        response = make_mock_response(200, [
            {"id": "camp-1", "name": "Campaign A", "status": "active"},
        ])
        node = self.create_node(InstantlyListCampaignsConfig(limit="5"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_campaigns"

    @pytest.mark.asyncio
    async def test_get_campaign(self, credential):
        response = make_mock_response(200, {"id": "camp-1", "name": "Campaign A"})
        node = self.create_node(InstantlyGetCampaignConfig(campaign_id="camp-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_campaign"

    @pytest.mark.asyncio
    async def test_create_campaign(self, credential):
        response = make_mock_response(200, {"id": "camp-new", "name": "New Campaign"})
        node = self.create_node(InstantlyCreateCampaignConfig(name="New Campaign"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_campaign"
        assert result["data"]["name"] == "New Campaign"

    @pytest.mark.asyncio
    async def test_update_campaign(self, credential):
        response = make_mock_response(200, {"id": "camp-1", "name": "Updated"})
        config = InstantlyUpdateCampaignConfig(campaign_id="camp-1", name="Updated")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_campaign"

    @pytest.mark.asyncio
    async def test_delete_campaign(self, credential):
        response = make_mock_response(204)
        node = self.create_node(InstantlyDeleteCampaignConfig(campaign_id="camp-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_campaign"

    @pytest.mark.asyncio
    async def test_activate_campaign(self, credential):
        response = make_mock_response(200, {"success": True})
        node = self.create_node(InstantlyActivateCampaignConfig(campaign_id="camp-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "activate_campaign"

    @pytest.mark.asyncio
    async def test_pause_campaign(self, credential):
        response = make_mock_response(200, {"success": True})
        node = self.create_node(InstantlyPauseCampaignConfig(campaign_id="camp-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "pause_campaign"

    @pytest.mark.asyncio
    async def test_search_campaigns_by_contact(self, credential):
        response = make_mock_response(200, [{"id": "camp-1", "name": "Found Campaign"}])
        config = InstantlySearchCampaignsByContactConfig(email="lead@example.com")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_campaigns_by_contact_email"

    # =========================================================================
    # Lead Operations (7 tests)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_leads(self, credential):
        response = make_mock_response(200, [
            {"id": "lead-1", "email": "lead@example.com", "first_name": "John"},
        ])
        node = self.create_node(InstantlyListLeadsConfig(limit="10"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_leads"

    @pytest.mark.asyncio
    async def test_get_lead(self, credential):
        response = make_mock_response(200, {"id": "lead-1", "email": "lead@example.com"})
        node = self.create_node(InstantlyGetLeadConfig(lead_id="lead-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_lead"

    @pytest.mark.asyncio
    async def test_create_lead(self, credential):
        response = make_mock_response(200, {"id": "lead-new", "email": "new@example.com"})
        config = InstantlyCreateLeadConfig(
            email="new@example.com", first_name="Jane", last_name="Doe", company_name="Acme"
        )
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_lead"

    @pytest.mark.asyncio
    async def test_update_lead(self, credential):
        response = make_mock_response(200, {"id": "lead-1", "first_name": "Updated"})
        config = InstantlyUpdateLeadConfig(lead_id="lead-1", first_name="Updated")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_lead"

    @pytest.mark.asyncio
    async def test_delete_lead(self, credential):
        response = make_mock_response(204)
        node = self.create_node(InstantlyDeleteLeadConfig(lead_id="lead-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_lead"

    @pytest.mark.asyncio
    async def test_bulk_add_leads(self, credential):
        response = make_mock_response(200, {"added": 2, "failed": 0})
        leads_json = json.dumps([
            {"email": "bulk1@example.com", "first_name": "Bulk1"},
            {"email": "bulk2@example.com", "first_name": "Bulk2"},
        ])
        config = InstantlyBulkAddLeadsConfig(leads=leads_json, campaign_id="camp-1")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "bulk_add_leads_to_campaign"

    @pytest.mark.asyncio
    async def test_bulk_add_leads_invalid_json(self, credential):
        config = InstantlyBulkAddLeadsConfig(leads="not valid json {{{")
        node = self.create_node(config, credential)
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["action"] == "bulk_add_leads_to_campaign"
        assert "Invalid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_move_lead(self, credential):
        response = make_mock_response(200, {"success": True})
        config = InstantlyMoveLeadConfig(lead_ids="lead-1", to_campaign_id="camp-2")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "move_leads_to_campaign"

    # =========================================================================
    # Lead List Operations (5 tests)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_lead_lists(self, credential):
        response = make_mock_response(200, [{"id": "list-1", "name": "My List"}])
        node = self.create_node(InstantlyListLeadListsConfig(limit="10"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_lead_lists"

    @pytest.mark.asyncio
    async def test_get_lead_list(self, credential):
        response = make_mock_response(200, {"id": "list-1", "name": "My List"})
        node = self.create_node(InstantlyGetLeadListConfig(list_id="list-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_lead_list"

    @pytest.mark.asyncio
    async def test_create_lead_list(self, credential):
        response = make_mock_response(200, {"id": "list-new", "name": "New List"})
        node = self.create_node(InstantlyCreateLeadListConfig(name="New List"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_lead_list"

    @pytest.mark.asyncio
    async def test_update_lead_list(self, credential):
        response = make_mock_response(200, {"id": "list-1", "name": "Updated List"})
        config = InstantlyUpdateLeadListConfig(list_id="list-1", name="Updated List")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_lead_list"

    @pytest.mark.asyncio
    async def test_delete_lead_list(self, credential):
        response = make_mock_response(204)
        node = self.create_node(InstantlyDeleteLeadListConfig(list_id="list-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_lead_list"

    # =========================================================================
    # Email Operations (5 tests)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_emails(self, credential):
        response = make_mock_response(200, [
            {"id": "email-1", "subject": "Hello", "from": "sender@example.com"},
        ])
        node = self.create_node(InstantlyListEmailsConfig(limit="5"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_emails"

    @pytest.mark.asyncio
    async def test_get_email(self, credential):
        response = make_mock_response(200, {"id": "email-1", "subject": "Hello", "body": "<p>Hi</p>"})
        node = self.create_node(InstantlyGetEmailConfig(email_id="email-1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_email"

    @pytest.mark.asyncio
    async def test_reply_to_email(self, credential):
        response = make_mock_response(200, {"id": "email-reply-1", "status": "sent"})
        config = InstantlyReplyToEmailConfig(
            reply_to_uuid="email-1", eaccount="sender@test.com",
            body="<p>Thanks!</p>", subject="Re: Hello"
        )
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "reply_to_email"

    @pytest.mark.asyncio
    async def test_count_unread_emails(self, credential):
        response = make_mock_response(200, {"count": 42})
        node = self.create_node(InstantlyCountUnreadEmailsConfig(), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "count_unread_emails"
        assert result["data"]["count"] == 42

    @pytest.mark.asyncio
    async def test_mark_thread_read(self, credential):
        response = make_mock_response(200, {"success": True})
        config = InstantlyMarkThreadReadConfig(thread_id="thread-1")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "mark_email_thread_as_read"

    # =========================================================================
    # Analytics Operations (3 tests)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_campaign_analytics(self, credential):
        response = make_mock_response(200, {
            "sent": 1000, "opened": 450, "replied": 120, "bounced": 15
        })
        config = InstantlyGetCampaignAnalyticsConfig(campaign_id="camp-1")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_campaign_analytics"
        assert result["data"]["sent"] == 1000

    @pytest.mark.asyncio
    async def test_get_daily_campaign_analytics(self, credential):
        response = make_mock_response(200, [
            {"date": "2025-01-01", "sent": 100, "opened": 45},
            {"date": "2025-01-02", "sent": 120, "opened": 60},
        ])
        config = InstantlyGetDailyCampaignAnalyticsConfig(start_date="2025-01-01", end_date="2025-01-02")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_daily_campaign_analytics"

    @pytest.mark.asyncio
    async def test_get_warmup_analytics(self, credential):
        response = make_mock_response(200, {"account_id": "acc-1", "warmup_score": 85})
        config = InstantlyGetWarmupAnalyticsConfig(email="test@example.com")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_account_warmup_analytics"

    # =========================================================================
    # Webhook Trigger (1 test)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_receive_webhook_passthrough(self, credential):
        """Webhook trigger passes through payload when no webhook_url is set."""
        config = InstantlyReceiveWebhookConfig(event_type="reply_received")
        node = self.create_node(config, credential)
        payload = {"event_type": "reply_received", "lead_email": "lead@test.com", "campaign_id": "camp-1"}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook_events"
        assert result["data"]["event_type"] == "reply_received"
        assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_receive_webhook_reregisters_on_execute(self, credential):
        """Running the webhook node manually re-registers with Instantly."""
        config = InstantlyReceiveWebhookConfig(
            event_type="reply_received",
            webhook_url="https://hooks.example.com/wh-123",
            instantly_webhook_id="old-wh-id",
        )
        node = self.create_node(config, credential)

        # Mock: DELETE old webhook succeeds, POST new webhook succeeds
        mock_client_instance = AsyncMock()
        delete_resp = make_mock_response(200, {})
        post_resp = make_mock_response(200, {"id": "new-wh-id"})
        mock_client_instance.delete = AsyncMock(return_value=delete_resp)
        mock_client_instance.post = AsyncMock(return_value=post_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["registered"] is True
        assert result["data"]["instantly_webhook_id"] == "new-wh-id"

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_api_error_response(self, credential):
        """Test that API errors are properly returned."""
        response = make_mock_response(404, {"message": "Campaign not found"})
        config = InstantlyGetCampaignConfig(campaign_id="nonexistent")
        node = self.create_node(config, credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "Campaign not found" in result["error"]
        assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_api_unauthorized(self, credential):
        """Test unauthorized response handling."""
        response = make_mock_response(401, {"message": "Invalid API key"})
        node = self.create_node(InstantlyListAccountsConfig(), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 401

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test that missing credentials raises ValueError."""
        config = InstantlyListAccountsConfig()
        node_config = InstantlyNodeConfig(config=config, credentials=None)
        node = InstantlyNode(
            node_id="test", node_type="automation-instantly",
            node_data={}, config=node_config, sio=None, sid=None, workflow_id="test"
        )
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_missing_config(self):
        """Test that missing config raises ValueError."""
        node = InstantlyNode(
            node_id="test", node_type="automation-instantly",
            node_data={}, config=None, sio=None, sid=None, workflow_id="test"
        )
        with pytest.raises(ValueError, match="Valid configuration is required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_timeout_handling(self, credential):
        """Test that timeouts are properly handled."""
        import httpx
        mock_client_instance = AsyncMock()
        mock_client_instance.request = AsyncMock(side_effect=httpx.TimeoutException("Connection timed out"))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        node = self.create_node(InstantlyListAccountsConfig(), credential)
        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 408
        assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_timing_info_present(self, credential):
        """Test that timing info is included in all responses."""
        response = make_mock_response(200, [])
        node = self.create_node(InstantlyListCampaignsConfig(limit="1"), credential)
        with self.mock_client(response):
            result = await node.execute({})
        assert "timing_ms" in result
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["total"] >= 0

    # =========================================================================
    # Config Validation Tests
    # =========================================================================

    def test_config_discriminator(self):
        """Test that all operation configs can be discriminated."""
        configs = [
            InstantlyListAccountsConfig(),
            InstantlyGetAccountConfig(email="test@test.com"),
            InstantlyCreateAccountConfig(email="t@t.com", first_name="T", last_name="T"),
            InstantlyPauseAccountConfig(email="test@test.com"),
            InstantlyResumeAccountConfig(email="test@test.com"),
            InstantlyDeleteAccountConfig(email="test@test.com"),
            InstantlyListCampaignsConfig(),
            InstantlyGetCampaignConfig(campaign_id="test"),
            InstantlyCreateCampaignConfig(name="test"),
            InstantlyUpdateCampaignConfig(campaign_id="test"),
            InstantlyDeleteCampaignConfig(campaign_id="test"),
            InstantlyActivateCampaignConfig(campaign_id="test"),
            InstantlyPauseCampaignConfig(campaign_id="test"),
            InstantlySearchCampaignsByContactConfig(email="t@t.com"),
            InstantlyListLeadsConfig(),
            InstantlyGetLeadConfig(lead_id="test"),
            InstantlyCreateLeadConfig(email="t@t.com"),
            InstantlyUpdateLeadConfig(lead_id="test"),
            InstantlyDeleteLeadConfig(lead_id="test"),
            InstantlyBulkAddLeadsConfig(leads='[{"email":"t@t.com"}]'),
            InstantlyMoveLeadConfig(lead_ids="test"),
            InstantlyListLeadListsConfig(),
            InstantlyGetLeadListConfig(list_id="test"),
            InstantlyCreateLeadListConfig(name="test"),
            InstantlyUpdateLeadListConfig(list_id="test", name="test"),
            InstantlyDeleteLeadListConfig(list_id="test"),
            InstantlyListEmailsConfig(),
            InstantlyGetEmailConfig(email_id="test"),
            InstantlyReplyToEmailConfig(reply_to_uuid="test", eaccount="sender@test.com", subject="Re: test", body="test"),
            InstantlyCountUnreadEmailsConfig(),
            InstantlyMarkThreadReadConfig(thread_id="test"),
            InstantlyGetCampaignAnalyticsConfig(campaign_id="test"),
            InstantlyGetDailyCampaignAnalyticsConfig(),
            InstantlyGetWarmupAnalyticsConfig(email="test@test.com"),
            InstantlyReceiveWebhookConfig(),
        ]
        # Verify all 35 configs have unique operation values
        operations = [c.operation for c in configs]
        assert len(operations) == 35, f"Expected 35 operations, got {len(operations)}"
        assert len(set(operations)) == 35, f"Duplicate operations found: {[a for a in operations if operations.count(a) > 1]}"

    def test_node_config_parsing(self):
        """Test that InstantlyNodeConfig can parse from dict."""
        data = {
            "config": {"operation": "list_email_accounts", "limit": "5"},
            "credentials": {"credential_type": "instantly_api_key", "api_key": "test-key"},
        }
        config = InstantlyNodeConfig(**data)
        assert isinstance(config.config, InstantlyListAccountsConfig)
        assert config.config.limit == "5"
        assert config.credentials.api_key == "test-key"

    def test_schema_generation(self):
        """Test that schema generates correctly."""
        schema = InstantlyNode.get_config_schema()
        assert "properties" in schema
        assert "config" in schema["properties"]
        assert "credentials" in schema["properties"]
        one_of = schema["properties"]["config"].get("oneOf", [])
        assert len(one_of) == 35


class TestInstantlyWebhookLifecycle:
    """Tests for webhook registration, re-registration, and cleanup."""

    @pytest.mark.asyncio
    async def test_delete_instantly_webhook_success(self):
        """Test successful webhook deletion from Instantly API."""
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(return_value=make_mock_response(200, {}))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance):
            result = await delete_instantly_webhook("test-key", "wh-123")
        assert result["success"] is True
        mock_client_instance.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_instantly_webhook_failure(self):
        """Test webhook deletion handles API errors gracefully."""
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(return_value=make_mock_response(404, {"error": "Not found"}))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance):
            result = await delete_instantly_webhook("test-key", "wh-nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_register_instantly_webhook_success(self):
        """Test successful webhook registration with Instantly API."""
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(
            return_value=make_mock_response(200, {"id": "new-wh-id", "webhook_url": "https://hooks.test/wh-1"})
        )
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance):
            result = await register_instantly_webhook("test-key", "https://hooks.test/wh-1", "reply_received")
        assert result["success"] is True
        assert result["instantly_webhook_id"] == "new-wh-id"

    @pytest.mark.asyncio
    async def test_register_instantly_webhook_failure(self):
        """Test webhook registration handles API errors gracefully."""
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=make_mock_response(400, {"error": "Bad request"}))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance):
            result = await register_instantly_webhook("test-key", "https://hooks.test/wh-1", "reply_received")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cleanup_calls_delete_then_internal(self):
        """Test cleanup deletes from Instantly API then internal webhook."""
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(return_value=make_mock_response(200, {}))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        mock_wm = MagicMock()
        mock_wm.delete_webhook = AsyncMock(return_value=True)

        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance), \
             patch('utils.webhook_manager.WebhookManager', mock_wm):
            result = await cleanup_instantly_webhook(
                pool=MagicMock(),
                workflow_id="wf-123",
                node_id="node-1",
                api_key="test-key",
                instantly_webhook_id="wh-abc",
            )
        assert result is True
        mock_client_instance.delete.assert_called_once()
        mock_wm.delete_webhook.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_without_credentials_skips_api(self):
        """Test cleanup skips Instantly API call when no credentials provided."""
        mock_wm = MagicMock()
        mock_wm.delete_webhook = AsyncMock(return_value=True)

        with patch('utils.webhook_manager.WebhookManager', mock_wm):
            result = await cleanup_instantly_webhook(
                pool=MagicMock(),
                workflow_id="wf-123",
                node_id="node-1",
            )
        assert result is True
        mock_wm.delete_webhook.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_external_webhook_classmethod(self):
        """Test the generic cleanup_external_webhook classmethod on InstantlyNode."""
        mock_client_instance = AsyncMock()
        mock_client_instance.delete = AsyncMock(return_value=make_mock_response(200, {}))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        config = {"instantly_webhook_id": "wh-abc", "action": "receive_webhook_events"}
        credentials = {"api_key": "test-key"}

        with patch('nodes.instantly_node.httpx.AsyncClient', return_value=mock_client_instance):
            await InstantlyNode.cleanup_external_webhook(
                pool=MagicMock(), workflow_id="wf-123", node_id="node-1",
                config=config, credentials=credentials,
            )
        mock_client_instance.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_external_webhook_no_credentials_is_noop(self):
        """Test cleanup_external_webhook does nothing without credentials."""
        # Should not raise or make any API calls
        await InstantlyNode.cleanup_external_webhook(
            pool=MagicMock(), workflow_id="wf-123", node_id="node-1",
            config={"instantly_webhook_id": "wh-abc"}, credentials=None,
        )

    @pytest.mark.asyncio
    async def test_cleanup_external_webhook_no_webhook_id_is_noop(self):
        """Test cleanup_external_webhook does nothing without instantly_webhook_id in config."""
        await InstantlyNode.cleanup_external_webhook(
            pool=MagicMock(), workflow_id="wf-123", node_id="node-1",
            config={"action": "list_campaigns"}, credentials={"api_key": "test-key"},
        )
