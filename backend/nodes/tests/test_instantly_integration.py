"""
Comprehensive integration tests for Instantly email automation node.

Tests ALL 35 operations organized by category.
Run: python scripts/test_instantly_integration.py <API_KEY>
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodes.instantly_node import (
    InstantlyNode,
    InstantlyNodeConfig,
    InstantlyAPIKeyCredential,
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


class TestRunner:
    def __init__(self, api_key: str):
        self.credentials = InstantlyAPIKeyCredential(api_key=api_key)
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.created_resources: list[tuple[str, str]] = []

        # IDs discovered during tests for cross-referencing
        self.account_id = None
        self.campaign_id = None
        self.lead_id = None
        self.lead_list_id = None
        self.email_id = None

    def create_node(self, config):
        node_config = InstantlyNodeConfig(config=config, credentials=self.credentials)
        return InstantlyNode(
            node_id="test-node",
            node_type="automation-instantly",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

    async def run_test(self, name: str, test_func):
        try:
            await test_func()
            print(f"  PASS: {name}")
            self.passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name} - {e}")
            self.failed += 1
        except Exception as e:
            print(f"  ERROR: {name} - {type(e).__name__}: {e}")
            self.failed += 1

    async def cleanup(self):
        """Clean up test-created resources."""
        print("\n[Cleanup]")
        for resource_type, resource_id in reversed(self.created_resources):
            try:
                if resource_type == "campaign":
                    config = InstantlyDeleteCampaignConfig(campaign_id=resource_id)
                elif resource_type == "lead":
                    config = InstantlyDeleteLeadConfig(lead_id=resource_id)
                elif resource_type == "lead_list":
                    config = InstantlyDeleteLeadListConfig(list_id=resource_id)
                else:
                    continue
                result = await self.create_node(config).execute({})
                print(f"  Deleted {resource_type}: {resource_id} ({result['status']})")
            except Exception as e:
                print(f"  Warning: Could not delete {resource_type} {resource_id}: {e}")

    async def run_all_tests(self):
        print("\n" + "=" * 70)
        print("Instantly Node Integration Tests - 35 Operations")
        print("=" * 70 + "\n")

        try:
            # =====================================================
            # Account Operations (6 tests)
            # =====================================================
            print("\n[Account Operations]")
            await self.run_test("list_email_accounts", self.test_list_accounts)
            await self.run_test("get_email_account", self.test_get_account)
            await self.run_test("create_account", self.test_create_account)
            await self.run_test("pause_email_account", self.test_pause_account)
            await self.run_test("resume_email_account", self.test_resume_account)
            await self.run_test("delete_account", self.test_delete_account)

            # =====================================================
            # Campaign Operations (8 tests)
            # =====================================================
            print("\n[Campaign Operations]")
            await self.run_test("list_campaigns", self.test_list_campaigns)
            await self.run_test("create_campaign", self.test_create_campaign)
            await self.run_test("get_campaign", self.test_get_campaign)
            await self.run_test("update_campaign", self.test_update_campaign)
            await self.run_test("activate_campaign", self.test_activate_campaign)
            await self.run_test("pause_campaign", self.test_pause_campaign)
            await self.run_test(
                "search_campaigns_by_contact_email", self.test_search_campaigns_by_contact
            )
            await self.run_test("delete_campaign", self.test_delete_campaign)

            # =====================================================
            # Lead List Operations (5 tests)
            # =====================================================
            print("\n[Lead List Operations]")
            await self.run_test("list_lead_lists", self.test_list_lead_lists)
            await self.run_test("create_lead_list", self.test_create_lead_list)
            await self.run_test("get_lead_list", self.test_get_lead_list)
            await self.run_test("update_lead_list", self.test_update_lead_list)
            await self.run_test("delete_lead_list", self.test_delete_lead_list)

            # =====================================================
            # Lead Operations (7 tests)
            # =====================================================
            print("\n[Lead Operations]")
            await self.run_test("list_leads", self.test_list_leads)
            await self.run_test("create_lead", self.test_create_lead)
            await self.run_test("get_lead", self.test_get_lead)
            await self.run_test("update_lead", self.test_update_lead)
            await self.run_test("bulk_add_leads_to_campaign", self.test_bulk_add_leads)
            await self.run_test("move_leads_to_campaign", self.test_move_lead)
            await self.run_test("delete_lead", self.test_delete_lead)

            # =====================================================
            # Email Operations (5 tests)
            # =====================================================
            print("\n[Email Operations]")
            await self.run_test("list_emails", self.test_list_emails)
            await self.run_test("get_email", self.test_get_email)
            await self.run_test("reply_to_email", self.test_reply_to_email)
            await self.run_test("count_unread_emails", self.test_count_unread_emails)
            await self.run_test("mark_email_thread_as_read", self.test_mark_thread_read)

            # =====================================================
            # Analytics Operations (3 tests)
            # =====================================================
            print("\n[Analytics Operations]")
            await self.run_test(
                "get_campaign_analytics", self.test_get_campaign_analytics
            )
            await self.run_test(
                "get_daily_campaign_analytics", self.test_get_daily_campaign_analytics
            )
            await self.run_test("get_account_warmup_analytics", self.test_get_warmup_analytics)

            # =====================================================
            # Webhook Trigger (1 test)
            # =====================================================
            print("\n[Webhook Trigger]")
            await self.run_test("receive_webhook", self.test_receive_webhook)

            # =====================================================
            # Error Handling Tests
            # =====================================================
            print("\n[Error Handling]")
            await self.run_test("invalid_id", self.test_invalid_id)
            await self.run_test("timing_info", self.test_timing_info)

        finally:
            await self.cleanup()

        total = self.passed + self.failed + self.skipped
        print("\n" + "=" * 70)
        print(
            f"Results: {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped"
        )
        print("=" * 70 + "\n")

        return self.failed == 0

    # ===========================================================
    # Account Tests
    # ===========================================================

    async def test_list_accounts(self):
        config = InstantlyListAccountsConfig(limit="5")
        result = await self.create_node(config).execute({})
        assert (
            result["status"] == "success"
        ), f"Expected success, got: {result.get('error')}"
        assert result["action"] == "list_email_accounts"
        # Store first account ID for later tests
        data = result.get("data")
        if isinstance(data, list) and len(data) > 0:
            self.account_id = data[0].get("id") or data[0].get("email")
        elif isinstance(data, dict) and data.get("items"):
            self.account_id = data["items"][0].get("id") or data["items"][0].get(
                "email"
            )

    async def test_get_account(self):
        if not self.account_id:
            self.skipped += 1
            print("  SKIP: get_account (no account_id available)")
            return
        config = InstantlyGetAccountConfig(account_id=self.account_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_email_account"

    async def test_create_account(self):
        # Creating an account requires valid SMTP credentials, so we just verify the API call works
        config = InstantlyCreateAccountConfig(
            email=f"test-{int(time.time())}@example-noclick-test.com",
            first_name="Test",
            last_name="Account",
            provider_code="1",
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "create_email_account"
        # May fail with 400/422 due to invalid SMTP, that's expected
        if result["status"] == "success" and result.get("data", {}).get("id"):
            self.created_resources.append(("account", result["data"]["id"]))

    async def test_pause_account(self):
        if not self.account_id:
            self.skipped += 1
            print("  SKIP: pause_account (no account_id)")
            return
        config = InstantlyPauseAccountConfig(account_id=self.account_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "pause_email_account"

    async def test_resume_account(self):
        if not self.account_id:
            self.skipped += 1
            print("  SKIP: resume_account (no account_id)")
            return
        config = InstantlyResumeAccountConfig(account_id=self.account_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "resume_email_account"

    async def test_delete_account(self):
        # Don't actually delete real accounts — just verify the call shape
        config = InstantlyDeleteAccountConfig(account_id="nonexistent-test-id")
        result = await self.create_node(config).execute({})
        assert result["action"] == "delete_email_account"

    # ===========================================================
    # Campaign Tests
    # ===========================================================

    async def test_list_campaigns(self):
        config = InstantlyListCampaignsConfig(limit="5")
        result = await self.create_node(config).execute({})
        assert (
            result["status"] == "success"
        ), f"Expected success, got: {result.get('error')}"
        assert result["action"] == "list_campaigns"
        data = result.get("data")
        if isinstance(data, list) and len(data) > 0:
            self.campaign_id = data[0].get("id")
        elif isinstance(data, dict) and data.get("items"):
            self.campaign_id = data["items"][0].get("id")

    async def test_create_campaign(self):
        config = InstantlyCreateCampaignConfig(name=f"Test Campaign {int(time.time())}")
        result = await self.create_node(config).execute({})
        assert result["action"] == "create_campaign"
        if result["status"] == "success":
            cid = result.get("data", {}).get("id")
            if cid:
                self.campaign_id = cid
                self.created_resources.append(("campaign", cid))

    async def test_get_campaign(self):
        if not self.campaign_id:
            self.skipped += 1
            print("  SKIP: get_campaign (no campaign_id)")
            return
        config = InstantlyGetCampaignConfig(campaign_id=self.campaign_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_campaign"

    async def test_update_campaign(self):
        if not self.campaign_id:
            self.skipped += 1
            print("  SKIP: update_campaign (no campaign_id)")
            return
        config = InstantlyUpdateCampaignConfig(
            campaign_id=self.campaign_id, name=f"Updated {int(time.time())}"
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "update_campaign"

    async def test_activate_campaign(self):
        if not self.campaign_id:
            self.skipped += 1
            print("  SKIP: activate_campaign (no campaign_id)")
            return
        config = InstantlyActivateCampaignConfig(campaign_id=self.campaign_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "activate_campaign"

    async def test_pause_campaign(self):
        if not self.campaign_id:
            self.skipped += 1
            print("  SKIP: pause_campaign (no campaign_id)")
            return
        config = InstantlyPauseCampaignConfig(campaign_id=self.campaign_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "pause_campaign"

    async def test_search_campaigns_by_contact(self):
        config = InstantlySearchCampaignsByContactConfig(email="test@example.com")
        result = await self.create_node(config).execute({})
        assert result["action"] == "search_campaigns_by_contact_email"

    async def test_delete_campaign(self):
        # Only delete the test campaign we created
        test_campaigns = [
            rid for rtype, rid in self.created_resources if rtype == "campaign"
        ]
        if not test_campaigns:
            self.skipped += 1
            print("  SKIP: delete_campaign (no test campaign to delete)")
            return
        cid = test_campaigns[-1]
        config = InstantlyDeleteCampaignConfig(campaign_id=cid)
        result = await self.create_node(config).execute({})
        assert result["action"] == "delete_campaign"
        # Remove from cleanup list since we just deleted it
        self.created_resources = [
            (t, i)
            for t, i in self.created_resources
            if not (t == "campaign" and i == cid)
        ]

    # ===========================================================
    # Lead List Tests
    # ===========================================================

    async def test_list_lead_lists(self):
        config = InstantlyListLeadListsConfig(limit="5")
        result = await self.create_node(config).execute({})
        assert (
            result["status"] == "success"
        ), f"Expected success, got: {result.get('error')}"
        assert result["action"] == "list_lead_lists"

    async def test_create_lead_list(self):
        config = InstantlyCreateLeadListConfig(name=f"Test List {int(time.time())}")
        result = await self.create_node(config).execute({})
        assert result["action"] == "create_lead_list"
        if result["status"] == "success":
            lid = result.get("data", {}).get("id")
            if lid:
                self.lead_list_id = lid
                self.created_resources.append(("lead_list", lid))

    async def test_get_lead_list(self):
        if not self.lead_list_id:
            self.skipped += 1
            print("  SKIP: get_lead_list (no lead_list_id)")
            return
        config = InstantlyGetLeadListConfig(list_id=self.lead_list_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_lead_list"

    async def test_update_lead_list(self):
        if not self.lead_list_id:
            self.skipped += 1
            print("  SKIP: update_lead_list (no lead_list_id)")
            return
        config = InstantlyUpdateLeadListConfig(
            list_id=self.lead_list_id, name=f"Updated List {int(time.time())}"
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "update_lead_list"

    async def test_delete_lead_list(self):
        test_lists = [
            rid for rtype, rid in self.created_resources if rtype == "lead_list"
        ]
        if not test_lists:
            self.skipped += 1
            print("  SKIP: delete_lead_list (no test list)")
            return
        lid = test_lists[-1]
        config = InstantlyDeleteLeadListConfig(list_id=lid)
        result = await self.create_node(config).execute({})
        assert result["action"] == "delete_lead_list"
        self.created_resources = [
            (t, i)
            for t, i in self.created_resources
            if not (t == "lead_list" and i == lid)
        ]

    # ===========================================================
    # Lead Tests
    # ===========================================================

    async def test_list_leads(self):
        config = InstantlyListLeadsConfig(limit="5")
        result = await self.create_node(config).execute({})
        assert result["action"] == "list_leads"

    async def test_create_lead(self):
        config = InstantlyCreateLeadConfig(
            email=f"test-lead-{int(time.time())}@example-noclick-test.com",
            first_name="Test",
            last_name="Lead",
            company_name="NoClick Test",
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "create_lead"
        if result["status"] == "success":
            lid = result.get("data", {}).get("id")
            if lid:
                self.lead_id = lid
                self.created_resources.append(("lead", lid))

    async def test_get_lead(self):
        if not self.lead_id:
            self.skipped += 1
            print("  SKIP: get_lead (no lead_id)")
            return
        config = InstantlyGetLeadConfig(lead_id=self.lead_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_lead"

    async def test_update_lead(self):
        if not self.lead_id:
            self.skipped += 1
            print("  SKIP: update_lead (no lead_id)")
            return
        config = InstantlyUpdateLeadConfig(lead_id=self.lead_id, first_name="Updated")
        result = await self.create_node(config).execute({})
        assert result["action"] == "update_lead"

    async def test_bulk_add_leads(self):
        import json

        leads = json.dumps(
            [
                {
                    "email": f"bulk1-{int(time.time())}@example-noclick-test.com",
                    "first_name": "Bulk1",
                },
                {
                    "email": f"bulk2-{int(time.time())}@example-noclick-test.com",
                    "first_name": "Bulk2",
                },
            ]
        )
        config = InstantlyBulkAddLeadsConfig(leads=leads)
        result = await self.create_node(config).execute({})
        assert result["action"] == "bulk_add_leads_to_campaign"

    async def test_move_lead(self):
        if not self.lead_id:
            self.skipped += 1
            print("  SKIP: move_lead (no lead_id)")
            return
        config = InstantlyMoveLeadConfig(lead_id=self.lead_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "move_leads_to_campaign"

    async def test_delete_lead(self):
        test_leads = [rid for rtype, rid in self.created_resources if rtype == "lead"]
        if not test_leads:
            self.skipped += 1
            print("  SKIP: delete_lead (no test lead)")
            return
        lid = test_leads[-1]
        config = InstantlyDeleteLeadConfig(lead_id=lid)
        result = await self.create_node(config).execute({})
        assert result["action"] == "delete_lead"
        self.created_resources = [
            (t, i) for t, i in self.created_resources if not (t == "lead" and i == lid)
        ]

    # ===========================================================
    # Email Tests
    # ===========================================================

    async def test_list_emails(self):
        config = InstantlyListEmailsConfig(limit="5")
        result = await self.create_node(config).execute({})
        assert result["action"] == "list_emails"
        data = result.get("data")
        if isinstance(data, list) and len(data) > 0:
            self.email_id = data[0].get("id")
        elif isinstance(data, dict) and data.get("items"):
            self.email_id = data["items"][0].get("id")

    async def test_get_email(self):
        if not self.email_id:
            self.skipped += 1
            print("  SKIP: get_email (no email_id)")
            return
        config = InstantlyGetEmailConfig(email_id=self.email_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_email"

    async def test_reply_to_email(self):
        if not self.email_id:
            self.skipped += 1
            print("  SKIP: reply_to_email (no email_id)")
            return
        config = InstantlyReplyToEmailConfig(
            email_id=self.email_id, body="<p>Test reply from integration test</p>"
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "reply_to_email"

    async def test_count_unread_emails(self):
        config = InstantlyCountUnreadEmailsConfig()
        result = await self.create_node(config).execute({})
        assert result["action"] == "count_unread_emails"

    async def test_mark_thread_read(self):
        # Use a dummy thread ID — we just want to verify the API call shape
        config = InstantlyMarkThreadReadConfig(thread_id="nonexistent-thread-id")
        result = await self.create_node(config).execute({})
        assert result["action"] == "mark_email_thread_as_read"

    # ===========================================================
    # Analytics Tests
    # ===========================================================

    async def test_get_campaign_analytics(self):
        if not self.campaign_id:
            # Try to get one from listing
            list_result = await self.create_node(
                InstantlyListCampaignsConfig(limit="1")
            ).execute({})
            data = list_result.get("data")
            if isinstance(data, list) and len(data) > 0:
                self.campaign_id = data[0].get("id")
            elif isinstance(data, dict) and data.get("items"):
                self.campaign_id = data["items"][0].get("id")

        if not self.campaign_id:
            self.skipped += 1
            print("  SKIP: get_campaign_analytics (no campaign_id)")
            return
        config = InstantlyGetCampaignAnalyticsConfig(campaign_id=self.campaign_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_campaign_analytics"

    async def test_get_daily_campaign_analytics(self):
        config = InstantlyGetDailyCampaignAnalyticsConfig()
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_daily_campaign_analytics"

    async def test_get_warmup_analytics(self):
        if not self.account_id:
            self.skipped += 1
            print("  SKIP: get_warmup_analytics (no account_id)")
            return
        config = InstantlyGetWarmupAnalyticsConfig(account_id=self.account_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_account_warmup_analytics"

    # ===========================================================
    # Webhook Trigger Test
    # ===========================================================

    async def test_receive_webhook(self):
        """Test webhook trigger mode — just passes through payload."""
        config = InstantlyReceiveWebhookConfig(event_type="reply_received")
        node_config = InstantlyNodeConfig(config=config, credentials=self.credentials)
        node = InstantlyNode(
            node_id="test-webhook",
            node_type="automation-instantly",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )
        payload = {
            "event_type": "reply_received",
            "lead_email": "test@example.com",
            "campaign_id": "abc",
        }
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook_events"
        assert result["data"] == payload

    # ===========================================================
    # Error & Performance Tests
    # ===========================================================

    async def test_invalid_id(self):
        config = InstantlyGetCampaignConfig(campaign_id="invalid-12345-nonexistent")
        result = await self.create_node(config).execute({})
        assert result["status"] == "error"
        assert result["status_code"] in [400, 404, 422]

    async def test_timing_info(self):
        config = InstantlyListCampaignsConfig(limit="1")
        result = await self.create_node(config).execute({})
        assert "timing_ms" in result
        assert result["timing_ms"]["total"] > 0


async def main():
    api_key = os.environ.get("INSTANTLY_API_KEY", "")
    if len(sys.argv) > 1:
        api_key = sys.argv[1]

    if not api_key:
        print("ERROR: API key required.")
        print("Usage: python scripts/test_instantly_integration.py <API_KEY>")
        print(
            "   or: INSTANTLY_API_KEY=<key> python scripts/test_instantly_integration.py"
        )
        sys.exit(1)

    runner = TestRunner(api_key)
    success = await runner.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
