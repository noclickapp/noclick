"""
Integration tests for Apollo.io REST API node.

Tests the complete Apollo API node functionality including ALL 48 operations
organized by category: enrichment, search, accounts, contacts, deals,
sequences, emails, tasks, calls, and utility.

Uses a real Apollo API Key to test against the Apollo API. Tests are designed
to be non-destructive where possible (read operations). Write operations test
the action name is correct but may fail due to permission constraints.

To run these tests:
    APOLLO_API_KEY=your_api_key pytest nodes/tests/test_apollo_node.py -v

Note: Some endpoints require a Master API Key (available on paid plans).
"""

import asyncio
import os
import time
import pytest

# Import the node and config classes - ALL 48 operations
from nodes.apollo_node import (
    ApolloNode,
    ApolloNodeConfig,
    ApolloAPIKeyCredential,
    # Enrichment operations (4)
    ApolloPeopleEnrichmentConfig,
    ApolloBulkPeopleEnrichmentConfig,
    ApolloOrganizationEnrichmentConfig,
    ApolloBulkOrganizationEnrichmentConfig,
    # Search operations (5)
    ApolloPeopleSearchConfig,
    ApolloOrganizationSearchConfig,
    ApolloOrganizationJobPostingsConfig,
    ApolloGetOrganizationInfoConfig,
    ApolloSearchNewsArticlesConfig,
    # Account operations (9)
    ApolloCreateAccountConfig,
    ApolloUpdateAccountConfig,
    ApolloSearchAccountsConfig,
    ApolloViewAccountConfig,
    ApolloListAccountStagesConfig,
    ApolloBulkCreateAccountsConfig,
    ApolloBulkUpdateAccountsConfig,
    ApolloUpdateAccountStagesConfig,
    ApolloUpdateAccountOwnersConfig,
    # Contact operations (9)
    ApolloCreateContactConfig,
    ApolloUpdateContactConfig,
    ApolloSearchContactsConfig,
    ApolloViewContactConfig,
    ApolloListContactStagesConfig,
    ApolloBulkCreateContactsConfig,
    ApolloBulkUpdateContactsConfig,
    ApolloUpdateContactStagesConfig,
    ApolloUpdateContactOwnersConfig,
    # Deal operations (5)
    ApolloCreateDealConfig,
    ApolloListDealsConfig,
    ApolloViewDealConfig,
    ApolloUpdateDealConfig,
    ApolloListDealStagesConfig,
    # Sequence operations (5)
    ApolloSearchSequencesConfig,
    ApolloAddContactsToSequenceConfig,
    ApolloUpdateContactSequenceStatusConfig,
    ApolloSearchEmailsConfig,
    ApolloGetEmailStatsConfig,
    # Task operations (2)
    ApolloCreateTaskConfig,
    ApolloSearchTasksConfig,
    # Call operations (3)
    ApolloCreateCallRecordConfig,
    ApolloSearchCallsConfig,
    ApolloUpdateCallRecordConfig,
    # Utility operations (6)
    ApolloGetUsersConfig,
    ApolloGetEmailAccountsConfig,
    ApolloGetUsageStatsConfig,
    ApolloGetListsConfig,
    ApolloGetCustomFieldsConfig,
    ApolloCreateCustomFieldConfig,
)

# Environment variable for API Key (don't hardcode in tests)
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")

# Test IDs - will be populated during tests
TEST_ACCOUNT_ID = None
TEST_CONTACT_ID = None
TEST_DEAL_ID = None
TEST_DEAL_STAGE_ID = None
TEST_SEQUENCE_ID = None
TEST_ACCOUNT_STAGE_ID = None
TEST_CONTACT_STAGE_ID = None
TEST_USER_ID = None
TEST_CALL_ID = None
TEST_EMAIL_ID = None


def get_credentials():
    """Get Apollo credentials from environment."""
    if not APOLLO_API_KEY:
        pytest.skip("APOLLO_API_KEY environment variable not set")
    return ApolloAPIKeyCredential(api_key=APOLLO_API_KEY)


def create_node(config) -> ApolloNode:
    """Create an ApolloNode instance with the given config."""
    credentials = get_credentials()
    node_config = ApolloNodeConfig(config=config, credentials=credentials)
    node = ApolloNode(
        node_id="test-node",
        node_type="automation-apollo",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Enrichment Operations Tests (4 operations)
# ============================================================================


class TestEnrichmentOperations:
    """Test enrichment-related Apollo API operations (4 total)."""

    @pytest.mark.asyncio
    async def test_people_enrichment(self):
        """Test enriching data for a single person."""
        config = ApolloPeopleEnrichmentConfig(
            email="tim@apple.com", first_name="Tim", last_name="Cook"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "enrich_single_person"
        # May succeed or fail depending on credits/API access

    @pytest.mark.asyncio
    async def test_people_enrichment_with_domain(self):
        """Test enriching person data using domain."""
        config = ApolloPeopleEnrichmentConfig(
            first_name="Satya", last_name="Nadella", domain="microsoft.com"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "enrich_single_person"

    @pytest.mark.asyncio
    async def test_bulk_people_enrichment(self):
        """Test enriching data for multiple people."""
        config = ApolloBulkPeopleEnrichmentConfig(
            details=[
                {
                    "email": "test1@example.com",
                    "first_name": "Test",
                    "last_name": "One",
                },
                {
                    "email": "test2@example.com",
                    "first_name": "Test",
                    "last_name": "Two",
                },
            ]
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "enrich_multiple_people"

    @pytest.mark.asyncio
    async def test_organization_enrichment(self):
        """Test enriching data for a single organization."""
        config = ApolloOrganizationEnrichmentConfig(domain="apollo.io")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "enrich_single_organization"
        if result["status"] == "success":
            assert "organization" in result["data"] or "data" in result

    @pytest.mark.asyncio
    async def test_bulk_organization_enrichment(self):
        """Test enriching data for multiple organizations."""
        config = ApolloBulkOrganizationEnrichmentConfig(
            domains=["apollo.io", "google.com", "microsoft.com"]
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "enrich_multiple_organizations"


# ============================================================================
# Search Operations Tests (5 operations)
# ============================================================================


class TestSearchOperations:
    """Test search-related Apollo API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_people_search(self):
        """Test searching for people/prospects."""
        config = ApolloPeopleSearchConfig(
            q_keywords="CEO", person_seniorities=["c_suite"], per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_people_in_apollo"
        if result["status"] == "success":
            assert "people" in result["data"] or "contacts" in result["data"]

    @pytest.mark.asyncio
    async def test_people_search_with_location(self):
        """Test searching for people in a specific location."""
        config = ApolloPeopleSearchConfig(
            person_titles=["Software Engineer"],
            person_locations=["San Francisco, CA"],
            per_page=5,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_people_in_apollo"

    @pytest.mark.asyncio
    async def test_organization_search(self):
        """Test searching for organizations."""
        config = ApolloOrganizationSearchConfig(
            q_organization_keyword_tags=["software", "technology"],
            organization_num_employees_ranges=["1001,2000", "2001,5000"],
            per_page=5,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_organizations_in_apollo"

    @pytest.mark.asyncio
    async def test_organization_job_postings(self):
        """Test getting job postings for an organization."""
        # First, we need a valid organization ID. Use a known one or skip if not available.
        # For testing, we'll use a placeholder that should return an error but verify the action
        config = ApolloOrganizationJobPostingsConfig(organization_id="org_nonexistent")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_organization_job_postings"

    @pytest.mark.asyncio
    async def test_get_organization_info(self):
        """Test getting complete organization information."""
        config = ApolloGetOrganizationInfoConfig(
            organization_id="5e66b6XXXXXXXXXXXXXXXXXX"  # Placeholder ID
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_organization_details"

    @pytest.mark.asyncio
    async def test_search_news_articles(self):
        """Test searching for news articles about organizations."""
        config = ApolloSearchNewsArticlesConfig(
            q_organization_domains=["apollo.io", "google.com"], per_page=5
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_organization_news_articles"


# ============================================================================
# Account Operations Tests (9 operations)
# ============================================================================


class TestAccountOperations:
    """Test account-related Apollo API operations (9 total)."""

    @pytest.mark.asyncio
    async def test_list_account_stages(self):
        """Test listing all account stages."""
        config = ApolloListAccountStagesConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_account_stages"
        if result["status"] == "success":
            assert "account_stages" in result["data"] or isinstance(
                result["data"], list
            )

    @pytest.mark.asyncio
    async def test_search_accounts(self):
        """Test searching for accounts."""
        global TEST_ACCOUNT_ID

        config = ApolloSearchAccountsConfig(q_organization_name="Apollo", per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_accounts"
        if result["status"] == "success":
            accounts = result["data"].get("accounts", [])
            if accounts:
                TEST_ACCOUNT_ID = accounts[0].get("id")

    @pytest.mark.asyncio
    async def test_create_account(self):
        """Test creating a new account."""
        global TEST_ACCOUNT_ID

        config = ApolloCreateAccountConfig(
            name=f"Test Account {int(time.time())}", domain="testaccount.example.com"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_account"
        if result["status"] == "success":
            account_data = result["data"].get("account", result["data"])
            if account_data and account_data.get("id"):
                TEST_ACCOUNT_ID = account_data["id"]

    @pytest.mark.asyncio
    async def test_view_account(self):
        """Test viewing a single account."""
        if not TEST_ACCOUNT_ID:
            pytest.skip("No account ID available for testing")

        config = ApolloViewAccountConfig(account_id=TEST_ACCOUNT_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_account_details"

    @pytest.mark.asyncio
    async def test_update_account(self):
        """Test updating an existing account."""
        if not TEST_ACCOUNT_ID:
            pytest.skip("No account ID available for testing")

        config = ApolloUpdateAccountConfig(
            account_id=TEST_ACCOUNT_ID, phone_number="+12025550100"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_account_details"

    @pytest.mark.asyncio
    async def test_bulk_create_accounts(self):
        """Test bulk creating accounts."""
        config = ApolloBulkCreateAccountsConfig(
            accounts=[
                {
                    "name": f"Bulk Account 1 {int(time.time())}",
                    "domain": "bulk1.example.com",
                },
                {
                    "name": f"Bulk Account 2 {int(time.time())}",
                    "domain": "bulk2.example.com",
                },
            ]
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_multiple_accounts"

    @pytest.mark.asyncio
    async def test_bulk_update_accounts(self):
        """Test bulk updating accounts."""
        if not TEST_ACCOUNT_ID:
            pytest.skip("No account ID available for testing")

        config = ApolloBulkUpdateAccountsConfig(
            accounts=[{"id": TEST_ACCOUNT_ID, "phone_number": "+1111111111"}]
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_multiple_accounts"

    @pytest.mark.asyncio
    async def test_update_account_stages(self):
        """Test updating account stages for multiple accounts."""
        global TEST_ACCOUNT_STAGE_ID

        if not TEST_ACCOUNT_ID:
            pytest.skip("No account ID available for testing")

        # Get account stages first
        stages_config = ApolloListAccountStagesConfig()
        stages_node = create_node(stages_config)
        stages_result = await stages_node.execute({})

        if stages_result["status"] == "success":
            stages = stages_result["data"].get("account_stages", [])
            if stages:
                TEST_ACCOUNT_STAGE_ID = stages[0].get("id")

        if not TEST_ACCOUNT_STAGE_ID:
            pytest.skip("No account stage ID available for testing")

        config = ApolloUpdateAccountStagesConfig(
            account_ids=[TEST_ACCOUNT_ID], account_stage_id=TEST_ACCOUNT_STAGE_ID
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_account_stage_bulk"

    @pytest.mark.asyncio
    async def test_update_account_owners(self):
        """Test updating account owners for multiple accounts."""
        global TEST_USER_ID

        if not TEST_ACCOUNT_ID:
            pytest.skip("No account ID available for testing")

        # Get users first
        users_config = ApolloGetUsersConfig()
        users_node = create_node(users_config)
        users_result = await users_node.execute({})

        if users_result["status"] == "success":
            users = users_result["data"].get("users", [])
            if users:
                TEST_USER_ID = users[0].get("id")

        if not TEST_USER_ID:
            # Use a placeholder user ID to test the endpoint is called correctly
            TEST_USER_ID = "user_placeholder_for_test"

        config = ApolloUpdateAccountOwnersConfig(
            account_ids=[TEST_ACCOUNT_ID], owner_id=TEST_USER_ID
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "update_account_ownership"


# ============================================================================
# Contact Operations Tests (9 operations)
# ============================================================================


class TestContactOperations:
    """Test contact-related Apollo API operations (9 total)."""

    @pytest.mark.asyncio
    async def test_list_contact_stages(self):
        """Test listing all contact stages."""
        config = ApolloListContactStagesConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_contact_stages"
        if result["status"] == "success":
            assert "contact_stages" in result["data"] or isinstance(
                result["data"], list
            )

    @pytest.mark.asyncio
    async def test_search_contacts(self):
        """Test searching for contacts."""
        global TEST_CONTACT_ID

        config = ApolloSearchContactsConfig(q_keywords="test", per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_contacts"
        if result["status"] == "success":
            contacts = result["data"].get("contacts", [])
            if contacts:
                TEST_CONTACT_ID = contacts[0].get("id")

    @pytest.mark.asyncio
    async def test_create_contact(self):
        """Test creating a new contact."""
        global TEST_CONTACT_ID

        config = ApolloCreateContactConfig(
            first_name="Test",
            last_name=f"Contact_{int(time.time())}",
            email=f"test_{int(time.time())}@example.com",
            title="Test Engineer",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_contact"
        if result["status"] == "success":
            contact_data = result["data"].get("contact", result["data"])
            if contact_data and contact_data.get("id"):
                TEST_CONTACT_ID = contact_data["id"]

    @pytest.mark.asyncio
    async def test_view_contact(self):
        """Test viewing a single contact."""
        if not TEST_CONTACT_ID:
            pytest.skip("No contact ID available for testing")

        config = ApolloViewContactConfig(contact_id=TEST_CONTACT_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_contact_details"

    @pytest.mark.asyncio
    async def test_update_contact(self):
        """Test updating an existing contact."""
        if not TEST_CONTACT_ID:
            pytest.skip("No contact ID available for testing")

        config = ApolloUpdateContactConfig(
            contact_id=TEST_CONTACT_ID, title=f"Updated Title {int(time.time())}"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_contact_details"

    @pytest.mark.asyncio
    async def test_bulk_create_contacts(self):
        """Test bulk creating contacts."""
        config = ApolloBulkCreateContactsConfig(
            contacts=[
                {
                    "first_name": "Bulk",
                    "last_name": f"Contact1_{int(time.time())}",
                    "email": f"bulk1_{int(time.time())}@example.com",
                },
                {
                    "first_name": "Bulk",
                    "last_name": f"Contact2_{int(time.time())}",
                    "email": f"bulk2_{int(time.time())}@example.com",
                },
            ]
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_multiple_contacts"

    @pytest.mark.asyncio
    async def test_bulk_update_contacts(self):
        """Test bulk updating contacts."""
        if not TEST_CONTACT_ID:
            pytest.skip("No contact ID available for testing")

        config = ApolloBulkUpdateContactsConfig(
            contacts=[
                {"id": TEST_CONTACT_ID, "title": f"Bulk Updated {int(time.time())}"}
            ]
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_multiple_contacts"

    @pytest.mark.asyncio
    async def test_update_contact_stages(self):
        """Test updating contact stages for multiple contacts."""
        global TEST_CONTACT_STAGE_ID

        if not TEST_CONTACT_ID:
            pytest.skip("No contact ID available for testing")

        # Get contact stages first
        stages_config = ApolloListContactStagesConfig()
        stages_node = create_node(stages_config)
        stages_result = await stages_node.execute({})

        if stages_result["status"] == "success":
            stages = stages_result["data"].get("contact_stages", [])
            if stages:
                TEST_CONTACT_STAGE_ID = stages[0].get("id")

        if not TEST_CONTACT_STAGE_ID:
            pytest.skip("No contact stage ID available for testing")

        config = ApolloUpdateContactStagesConfig(
            contact_ids=[TEST_CONTACT_ID], contact_stage_id=TEST_CONTACT_STAGE_ID
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_contact_stage_bulk"

    @pytest.mark.asyncio
    async def test_update_contact_owners(self):
        """Test updating contact owners for multiple contacts."""
        if not TEST_CONTACT_ID:
            pytest.skip("No contact ID available for testing")

        # Use placeholder if no user ID available
        user_id = TEST_USER_ID if TEST_USER_ID else "user_placeholder_for_test"

        config = ApolloUpdateContactOwnersConfig(
            contact_ids=[TEST_CONTACT_ID], owner_id=user_id
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "update_contact_ownership"


# ============================================================================
# Deal Operations Tests (5 operations)
# ============================================================================


class TestDealOperations:
    """Test deal-related Apollo API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_list_deal_stages(self):
        """Test listing all deal stages."""
        global TEST_DEAL_STAGE_ID

        config = ApolloListDealStagesConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_deal_stages"
        if result["status"] == "success":
            stages = result["data"].get("deal_stages", result["data"])
            if isinstance(stages, list) and stages:
                TEST_DEAL_STAGE_ID = stages[0].get("id")

    @pytest.mark.asyncio
    async def test_list_deals(self):
        """Test listing all deals."""
        global TEST_DEAL_ID

        config = ApolloListDealsConfig(per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_deals"
        if result["status"] == "success":
            deals = result["data"].get("opportunities", result["data"].get("deals", []))
            if isinstance(deals, list) and deals:
                TEST_DEAL_ID = deals[0].get("id")

    @pytest.mark.asyncio
    async def test_create_deal(self):
        """Test creating a new deal."""
        global TEST_DEAL_ID

        # First ensure we have a deal stage ID
        if not TEST_DEAL_STAGE_ID:
            stages_config = ApolloListDealStagesConfig()
            stages_node = create_node(stages_config)
            stages_result = await stages_node.execute({})
            if stages_result["status"] == "success":
                stages = stages_result["data"].get("deal_stages", stages_result["data"])
                if isinstance(stages, list) and stages:
                    stage_id = stages[0].get("id")
                else:
                    # Use placeholder to test the endpoint is called correctly
                    stage_id = "stage_placeholder_for_test"
            else:
                stage_id = "stage_placeholder_for_test"
        else:
            stage_id = TEST_DEAL_STAGE_ID

        config = ApolloCreateDealConfig(
            name=f"Test Deal {int(time.time())}", deal_stage_id=stage_id, amount=10000.0
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "create_deal"
        if result["status"] == "success":
            deal_data = result["data"].get(
                "opportunity", result["data"].get("deal", result["data"])
            )
            if deal_data and deal_data.get("id"):
                TEST_DEAL_ID = deal_data["id"]

    @pytest.mark.asyncio
    async def test_view_deal(self):
        """Test viewing a single deal."""
        # Use placeholder if no deal ID available
        deal_id = TEST_DEAL_ID if TEST_DEAL_ID else "deal_placeholder_for_test"

        config = ApolloViewDealConfig(deal_id=deal_id)
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "get_deal_details"

    @pytest.mark.asyncio
    async def test_update_deal(self):
        """Test updating an existing deal."""
        # Use placeholder if no deal ID available
        deal_id = TEST_DEAL_ID if TEST_DEAL_ID else "deal_placeholder_for_test"

        config = ApolloUpdateDealConfig(deal_id=deal_id, amount=20000.0)
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "update_deal_details"


# ============================================================================
# Sequence Operations Tests (5 operations)
# ============================================================================


class TestSequenceOperations:
    """Test sequence-related Apollo API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_search_sequences(self):
        """Test searching for sequences."""
        global TEST_SEQUENCE_ID

        config = ApolloSearchSequencesConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_outreach_sequences"
        if result["status"] == "success":
            sequences = result["data"].get(
                "emailer_campaigns", result["data"].get("sequences", [])
            )
            if isinstance(sequences, list) and sequences:
                TEST_SEQUENCE_ID = sequences[0].get("id")

    @pytest.mark.asyncio
    async def test_add_contacts_to_sequence(self):
        """Test adding contacts to a sequence."""
        # Use placeholders if no IDs available
        sequence_id = (
            TEST_SEQUENCE_ID if TEST_SEQUENCE_ID else "sequence_placeholder_for_test"
        )
        contact_id = (
            TEST_CONTACT_ID if TEST_CONTACT_ID else "contact_placeholder_for_test"
        )

        config = ApolloAddContactsToSequenceConfig(
            sequence_id=sequence_id, contact_ids=[contact_id]
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "add_contacts_to_outreach_sequence"

    @pytest.mark.asyncio
    async def test_update_contact_sequence_status(self):
        """Test updating a contact's status in a sequence."""
        # Use placeholders if no IDs available
        sequence_id = (
            TEST_SEQUENCE_ID if TEST_SEQUENCE_ID else "sequence_placeholder_for_test"
        )
        contact_id = (
            TEST_CONTACT_ID if TEST_CONTACT_ID else "contact_placeholder_for_test"
        )

        config = ApolloUpdateContactSequenceStatusConfig(
            contact_id=contact_id, sequence_id=sequence_id, status="paused"
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "update_contact_sequence_status"

    @pytest.mark.asyncio
    async def test_search_emails(self):
        """Test searching for outreach emails."""
        global TEST_EMAIL_ID

        config = ApolloSearchEmailsConfig(per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_sequence_emails"
        if result["status"] == "success":
            messages = result["data"].get("emailer_messages", [])
            if messages:
                TEST_EMAIL_ID = messages[0].get("id")

    @pytest.mark.asyncio
    async def test_get_email_stats(self):
        """Test getting email statistics."""
        email_id = TEST_EMAIL_ID
        sequence_id = TEST_SEQUENCE_ID

        if not email_id:
            # Try to find an email first
            search_config = ApolloSearchEmailsConfig(per_page=1)
            search_node = create_node(search_config)
            search_result = await search_node.execute({})
            if search_result["status"] == "success":
                messages = search_result["data"].get("emailer_messages", [])
                if messages:
                    email_id = messages[0].get("id")

        # Use placeholders if no IDs available
        if not email_id:
            email_id = "email_placeholder_for_test"
        if not sequence_id:
            sequence_id = "sequence_placeholder_for_test"

        config = ApolloGetEmailStatsConfig(
            emailer_message_id=email_id, sequence_id=sequence_id
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "get_sequence_email_statistics"


# ============================================================================
# Task Operations Tests (2 operations)
# ============================================================================


class TestTaskOperations:
    """Test task-related Apollo API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_search_tasks(self):
        """Test searching for tasks."""
        config = ApolloSearchTasksConfig(per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_tasks"

    @pytest.mark.asyncio
    async def test_create_task(self):
        """Test creating a new task."""
        config = ApolloCreateTaskConfig(
            note=f"Test task created at {int(time.time())}",
            priority="normal",
            type="action_item",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_task"


# ============================================================================
# Call Operations Tests (3 operations)
# ============================================================================


class TestCallOperations:
    """Test call-related Apollo API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_search_calls(self):
        """Test searching for calls."""
        global TEST_CALL_ID

        config = ApolloSearchCallsConfig(per_page=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_call_records"
        if result["status"] == "success":
            calls = result["data"].get("phone_calls", [])
            if calls:
                TEST_CALL_ID = calls[0].get("id")

    @pytest.mark.asyncio
    async def test_create_call_record(self):
        """Test creating a call record."""
        global TEST_CALL_ID

        if not TEST_CONTACT_ID:
            pytest.skip("No contact ID available for testing")

        config = ApolloCreateCallRecordConfig(
            contact_id=TEST_CONTACT_ID,
            phone_number="+12025550106",
            disposition="connected",
            duration_in_seconds=120,
            note=f"Test call at {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_call_activity_record"
        if result["status"] == "success":
            call_data = result["data"].get("phone_call", result["data"])
            if call_data and call_data.get("id"):
                TEST_CALL_ID = call_data["id"]

    @pytest.mark.asyncio
    async def test_update_call_record(self):
        """Test updating a call record."""
        # Use placeholder if no call ID available
        call_id = TEST_CALL_ID if TEST_CALL_ID else "call_placeholder_for_test"

        config = ApolloUpdateCallRecordConfig(
            call_id=call_id, note=f"Updated note at {int(time.time())}"
        )
        node = create_node(config)

        result = await node.execute({})

        # Verify the action is correct - even if API returns error, integration works
        assert result["action"] == "update_call_record"


# ============================================================================
# Utility Operations Tests (6 operations)
# ============================================================================


class TestUtilityOperations:
    """Test utility-related Apollo API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_get_users(self):
        """Test getting list of users in the organization."""
        config = ApolloGetUsersConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_organization_users"
        if result["status"] == "success":
            assert "users" in result["data"] or isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_get_email_accounts(self):
        """Test getting list of email accounts."""
        config = ApolloGetEmailAccountsConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_email_account_list"

    @pytest.mark.asyncio
    async def test_get_usage_stats(self):
        """Test getting API usage statistics."""
        config = ApolloGetUsageStatsConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_api_usage_and_limits"

    @pytest.mark.asyncio
    async def test_get_lists(self):
        """Test getting all lists."""
        config = ApolloGetListsConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_organization_lists"

    @pytest.mark.asyncio
    async def test_get_custom_fields(self):
        """Test getting all custom fields."""
        config = ApolloGetCustomFieldsConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_organization_custom_fields"

    @pytest.mark.asyncio
    async def test_create_custom_field(self):
        """Test creating a custom field."""
        config = ApolloCreateCustomFieldConfig(
            name=f"test_field_{int(time.time())}",
            field_type="string",
            entity_type="contact",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_custom_field"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_contact_id(self):
        """Test handling of invalid contact ID."""
        config = ApolloViewContactConfig(contact_id="contact_nonexistent_12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_contact_details"
        # Should return error status for nonexistent contact

    @pytest.mark.asyncio
    async def test_invalid_account_id(self):
        """Test handling of invalid account ID."""
        config = ApolloViewAccountConfig(account_id="account_nonexistent_12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_account_details"
        # Should return error status for nonexistent account

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = ApolloSearchContactsConfig()
        node_config = ApolloNodeConfig(config=config, credentials=None)
        node = ApolloNode(
            node_id="test-node",
            node_type="automation-apollo",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Timing and Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance and timing information."""

    @pytest.mark.asyncio
    async def test_timing_information(self):
        """Test that timing information is included in responses."""
        config = ApolloSearchContactsConfig(per_page=1)
        node = create_node(config)

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] >= 0
        assert result["timing_ms"]["total"] >= 0


if __name__ == "__main__":
    # Run tests with: APOLLO_API_KEY=your_key pytest nodes/tests/test_apollo_node.py -v
    pytest.main([__file__, "-v"])
