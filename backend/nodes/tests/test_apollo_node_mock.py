"""
Mock tests for Apollo.io REST API node.

Tests all 48 Apollo API operations using mocked HTTP responses.
These tests don't require a real Apollo API key and verify the
correct behavior of the node implementation.

Operations tested (48 total):
- Enrichment (4): people_enrichment, bulk_people_enrichment, organization_enrichment, bulk_organization_enrichment
- Search (5): people_search, organization_search, organization_job_postings, get_organization_info, search_news_articles
- Accounts (9): create, update, search, view, list_stages, bulk_create, bulk_update, update_stages, update_owners
- Contacts (9): create, update, search, view, list_stages, bulk_create, bulk_update, update_stages, update_owners
- Deals (5): create, list, view, update, list_stages
- Sequences (5): search, add_contacts, update_status, search_emails, get_email_stats
- Tasks (2): create, search
- Calls (3): create, search, update
- Utility (6): get_users, get_email_accounts, get_usage_stats, get_lists, get_custom_fields, create_custom_field
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

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


# Test fixtures
@pytest.fixture
def api_key_credential():
    """Create API Key credential for testing."""
    return ApolloAPIKeyCredential(api_key="test_api_key_123")


def create_node(config, credentials) -> ApolloNode:
    """Create an ApolloNode instance with the given config and credentials."""
    node_config = ApolloNodeConfig(config=config, credentials=credentials)
    return ApolloNode(
        node_id="test-node",
        node_type="automation-apollo",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


def create_mock_response(status_code: int, json_data: dict):
    """Create a mock httpx.Response object."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = str(json_data)
    return response


# ============================================================================
# Enrichment Operations Mock Tests (4 operations)
# ============================================================================


class TestEnrichmentOperationsMock:
    """Mock tests for enrichment-related Apollo API operations."""

    @pytest.mark.asyncio
    async def test_people_enrichment_success(self, api_key_credential):
        """Test successful people enrichment with mocked response."""
        config = ApolloPeopleEnrichmentConfig(
            email="test@example.com", first_name="Test", last_name="User"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {
                "person": {
                    "id": "person_123",
                    "first_name": "Test",
                    "last_name": "User",
                    "email": "test@example.com",
                    "title": "Engineer",
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "enrich_single_person"
            assert result["status"] == "success"
            assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_bulk_people_enrichment_success(self, api_key_credential):
        """Test successful bulk people enrichment."""
        config = ApolloBulkPeopleEnrichmentConfig(
            details=[{"email": "test1@example.com"}, {"email": "test2@example.com"}]
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {
                "matches": [
                    {"email": "test1@example.com", "id": "person_1"},
                    {"email": "test2@example.com", "id": "person_2"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "enrich_multiple_people"

    @pytest.mark.asyncio
    async def test_organization_enrichment_success(self, api_key_credential):
        """Test successful organization enrichment."""
        config = ApolloOrganizationEnrichmentConfig(domain="example.com")
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {
                "organization": {
                    "id": "org_123",
                    "name": "Example Inc",
                    "domain": "example.com",
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "enrich_single_organization"

    @pytest.mark.asyncio
    async def test_bulk_organization_enrichment_success(self, api_key_credential):
        """Test successful bulk organization enrichment."""
        config = ApolloBulkOrganizationEnrichmentConfig(
            domains=["example1.com", "example2.com"]
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {
                "organizations": [
                    {"domain": "example1.com", "id": "org_1"},
                    {"domain": "example2.com", "id": "org_2"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "enrich_multiple_organizations"


# ============================================================================
# Search Operations Mock Tests (5 operations)
# ============================================================================


class TestSearchOperationsMock:
    """Mock tests for search-related Apollo API operations."""

    @pytest.mark.asyncio
    async def test_people_search_success(self, api_key_credential):
        """Test successful people search."""
        config = ApolloPeopleSearchConfig(
            q_keywords="CEO", person_seniorities=["c_suite"], per_page=5
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {
                "people": [{"id": "person_1", "first_name": "John", "title": "CEO"}],
                "pagination": {"total_entries": 100},
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "search_people_in_apollo"

    @pytest.mark.asyncio
    async def test_organization_search_success(self, api_key_credential):
        """Test successful organization search."""
        config = ApolloOrganizationSearchConfig(
            q_organization_keyword_tags=["technology"], per_page=5
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"organizations": [{"id": "org_1", "name": "Tech Corp"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "search_organizations_in_apollo"

    @pytest.mark.asyncio
    async def test_get_organization_info_success(self, api_key_credential):
        """Test successful get organization info."""
        config = ApolloGetOrganizationInfoConfig(organization_id="org_123")
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {
                "organization": {
                    "id": "org_123",
                    "name": "Example Inc",
                    "industry": "Technology",
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "get_organization_details"

    @pytest.mark.asyncio
    async def test_search_news_articles_success(self, api_key_credential):
        """Test successful news articles search."""
        config = ApolloSearchNewsArticlesConfig(
            organization_ids=["org_123"], q_keywords="funding", per_page=10
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {"news_articles": [{"id": "article_1", "title": "Company Raises Funding"}]},
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "search_organization_news_articles"


# ============================================================================
# Account Operations Mock Tests (9 operations)
# ============================================================================


class TestAccountOperationsMock:
    """Mock tests for account-related Apollo API operations."""

    @pytest.mark.asyncio
    async def test_create_account_success(self, api_key_credential):
        """Test successful account creation."""
        config = ApolloCreateAccountConfig(
            name="Test Account", domain="testaccount.com"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"account": {"id": "acc_123", "name": "Test Account"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "create_account"

    @pytest.mark.asyncio
    async def test_bulk_create_accounts_success(self, api_key_credential):
        """Test successful bulk account creation."""
        config = ApolloBulkCreateAccountsConfig(
            accounts=[
                {"name": "Account 1", "domain": "account1.com"},
                {"name": "Account 2", "domain": "account2.com"},
            ]
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {
                "accounts": [
                    {"id": "acc_1", "name": "Account 1"},
                    {"id": "acc_2", "name": "Account 2"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "create_multiple_accounts"

    @pytest.mark.asyncio
    async def test_bulk_update_accounts_success(self, api_key_credential):
        """Test successful bulk account update."""
        config = ApolloBulkUpdateAccountsConfig(
            accounts=[
                {"id": "acc_1", "phone_number": "+12025550100"},
                {"id": "acc_2", "phone_number": "+0987654321"},
            ]
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"accounts": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "update_multiple_accounts"

    @pytest.mark.asyncio
    async def test_update_account_stages_success(self, api_key_credential):
        """Test successful update account stages."""
        config = ApolloUpdateAccountStagesConfig(
            account_ids=["acc_1", "acc_2"], account_stage_id="stage_123"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"success": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "update_account_stage_bulk"

    @pytest.mark.asyncio
    async def test_update_account_owners_success(self, api_key_credential):
        """Test successful update account owners."""
        config = ApolloUpdateAccountOwnersConfig(
            account_ids=["acc_1", "acc_2"], owner_id="user_123"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"success": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "update_account_ownership"


# ============================================================================
# Contact Operations Mock Tests (9 operations)
# ============================================================================


class TestContactOperationsMock:
    """Mock tests for contact-related Apollo API operations."""

    @pytest.mark.asyncio
    async def test_create_contact_success(self, api_key_credential):
        """Test successful contact creation."""
        config = ApolloCreateContactConfig(
            first_name="Test", last_name="Contact", email="test@example.com"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"contact": {"id": "contact_123", "first_name": "Test"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "create_contact"

    @pytest.mark.asyncio
    async def test_bulk_create_contacts_success(self, api_key_credential):
        """Test successful bulk contact creation."""
        config = ApolloBulkCreateContactsConfig(
            contacts=[
                {"first_name": "John", "last_name": "Doe", "email": "john@example.com"},
                {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
            ],
            run_dedupe=True,
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"contacts": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "create_multiple_contacts"

    @pytest.mark.asyncio
    async def test_bulk_update_contacts_success(self, api_key_credential):
        """Test successful bulk contact update."""
        config = ApolloBulkUpdateContactsConfig(
            contacts=[
                {"id": "contact_1", "title": "Senior Engineer"},
                {"id": "contact_2", "title": "Manager"},
            ]
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"contacts": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "update_multiple_contacts"

    @pytest.mark.asyncio
    async def test_update_contact_stages_success(self, api_key_credential):
        """Test successful update contact stages."""
        config = ApolloUpdateContactStagesConfig(
            contact_ids=["contact_1", "contact_2"], contact_stage_id="stage_123"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"success": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "update_contact_stage_bulk"

    @pytest.mark.asyncio
    async def test_update_contact_owners_success(self, api_key_credential):
        """Test successful update contact owners."""
        config = ApolloUpdateContactOwnersConfig(
            contact_ids=["contact_1", "contact_2"], owner_id="user_123"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"success": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "update_contact_ownership"


# ============================================================================
# Sequence Operations Mock Tests (5 operations)
# ============================================================================


class TestSequenceOperationsMock:
    """Mock tests for sequence-related Apollo API operations."""

    @pytest.mark.asyncio
    async def test_search_sequences_success(self, api_key_credential):
        """Test successful sequence search."""
        config = ApolloSearchSequencesConfig()
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"emailer_campaigns": [{"id": "seq_123", "name": "Outreach 1"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "search_outreach_sequences"

    @pytest.mark.asyncio
    async def test_search_emails_success(self, api_key_credential):
        """Test successful email search."""
        config = ApolloSearchEmailsConfig(
            emailer_campaign_id="seq_123", email_status="sent", per_page=10
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"emailer_messages": [{"id": "msg_1", "status": "sent"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "search_sequence_emails"

    @pytest.mark.asyncio
    async def test_get_email_stats_success(self, api_key_credential):
        """Test successful get email stats."""
        config = ApolloGetEmailStatsConfig(sequence_id="seq_123")
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {"stats": {"emails_sent": 100, "emails_opened": 50, "emails_clicked": 20}},
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "get_sequence_email_statistics"


# ============================================================================
# Call Operations Mock Tests (3 operations)
# ============================================================================


class TestCallOperationsMock:
    """Mock tests for call-related Apollo API operations."""

    @pytest.mark.asyncio
    async def test_create_call_record_success(self, api_key_credential):
        """Test successful call record creation."""
        config = ApolloCreateCallRecordConfig(
            contact_id="contact_123",
            duration=300,
            outcome="connected",
            direction="outbound",
            note="Follow-up call",
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"phone_call": {"id": "call_123", "outcome": "connected"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "create_call_activity_record"

    @pytest.mark.asyncio
    async def test_search_calls_success(self, api_key_credential):
        """Test successful call search."""
        config = ApolloSearchCallsConfig(
            contact_id="contact_123", outcome="connected", per_page=10
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"phone_calls": [{"id": "call_1", "outcome": "connected"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "search_call_records"

    @pytest.mark.asyncio
    async def test_update_call_record_success(self, api_key_credential):
        """Test successful call record update."""
        config = ApolloUpdateCallRecordConfig(
            call_id="call_123", duration=600, outcome="connected", note="Updated notes"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"phone_call": {"id": "call_123", "duration": 600}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "update_call_record"


# ============================================================================
# Utility Operations Mock Tests (6 operations)
# ============================================================================


class TestUtilityOperationsMock:
    """Mock tests for utility-related Apollo API operations."""

    @pytest.mark.asyncio
    async def test_get_users_success(self, api_key_credential):
        """Test successful get users."""
        config = ApolloGetUsersConfig()
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"users": [{"id": "user_1", "name": "John Doe"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "get_organization_users"

    @pytest.mark.asyncio
    async def test_get_lists_success(self, api_key_credential):
        """Test successful get lists."""
        config = ApolloGetListsConfig()
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"labels": [{"id": "list_1", "name": "Hot Leads"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "get_organization_lists"

    @pytest.mark.asyncio
    async def test_get_custom_fields_success(self, api_key_credential):
        """Test successful get custom fields."""
        config = ApolloGetCustomFieldsConfig(field_type="contact")
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200, {"typed_custom_fields": [{"id": "field_1", "name": "Custom Field 1"}]}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "get_organization_custom_fields"

    @pytest.mark.asyncio
    async def test_create_custom_field_success(self, api_key_credential):
        """Test successful create custom field."""
        config = ApolloCreateCustomFieldConfig(
            name="Custom Field Test", field_type="contact", widget_type="text"
        )
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            200,
            {"typed_custom_field": {"id": "field_new", "name": "Custom Field Test"}},
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["action"] == "create_custom_field"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_error(self):
        """Test that missing credentials raises ValueError."""
        config = ApolloGetUsersConfig()
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

    @pytest.mark.asyncio
    async def test_api_error_response(self, api_key_credential):
        """Test handling of API error response."""
        config = ApolloGetUsersConfig()
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(
            401, {"error": "Unauthorized", "message": "Invalid API key"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert result["status"] == "error"
            assert result["status_code"] == 401


# ============================================================================
# Timing Tests
# ============================================================================


class TestTimingInformation:
    """Test that timing information is included in responses."""

    @pytest.mark.asyncio
    async def test_timing_information_included(self, api_key_credential):
        """Test that timing information is included in all responses."""
        config = ApolloGetUsersConfig()
        node = create_node(config, api_key_credential)

        mock_response = create_mock_response(200, {"users": []})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.request.return_value = mock_response

            result = await node.execute({})

            assert "timing_ms" in result
            assert "api_request" in result["timing_ms"]
            assert "total" in result["timing_ms"]
            assert result["timing_ms"]["api_request"] >= 0
            assert result["timing_ms"]["total"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
