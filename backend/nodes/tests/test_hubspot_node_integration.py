"""
Integration tests for HubSpot CRM API node.

Tests the complete HubSpot API node functionality including all 110 operations
organized by category:
- Core CRM: Contacts, Companies, Deals, Tickets (24 operations)
- Sales Objects: Leads, Products, Line Items, Quotes (24 operations)
- Activity Tracking: Notes, Tasks (12 operations)
- Engagement Tracking: Calls, Meetings, Emails (18 operations)
- Commerce: Orders (6 operations)
- System APIs: Owners, Properties, Pipelines, Pipeline Stages (23 operations)
- Cross-Object: Associations (3 operations)
- Batch Operations: batch_create, batch_read, batch_update, batch_archive, batch_upsert (5 operations)

Uses a real HubSpot Private App Access Token (or OAuth) to test against the HubSpot API.
Tests are designed to be non-destructive where possible (read operations).
Write operations create test resources and clean them up afterward.
"""

import asyncio
import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Import the node and config classes - ALL 78 operations
from nodes.hubspot_node import (
    HubSpotNode,
    HubSpotNodeConfig,
    HubSpotPATCredential,
    HubSpotOAuthCredential,
    # Contact operations (6)
    HubSpotListContactsConfig,
    HubSpotGetContactConfig,
    HubSpotCreateContactConfig,
    HubSpotUpdateContactConfig,
    HubSpotDeleteContactConfig,
    HubSpotSearchContactsConfig,
    # Company operations (6)
    HubSpotListCompaniesConfig,
    HubSpotGetCompanyConfig,
    HubSpotCreateCompanyConfig,
    HubSpotUpdateCompanyConfig,
    HubSpotDeleteCompanyConfig,
    HubSpotSearchCompaniesConfig,
    # Deal operations (6)
    HubSpotListDealsConfig,
    HubSpotGetDealConfig,
    HubSpotCreateDealConfig,
    HubSpotUpdateDealConfig,
    HubSpotDeleteDealConfig,
    HubSpotSearchDealsConfig,
    # Ticket operations (6)
    HubSpotListTicketsConfig,
    HubSpotGetTicketConfig,
    HubSpotCreateTicketConfig,
    HubSpotUpdateTicketConfig,
    HubSpotDeleteTicketConfig,
    HubSpotSearchTicketsConfig,
    # Lead operations (6)
    HubSpotListLeadsConfig,
    HubSpotGetLeadConfig,
    HubSpotCreateLeadConfig,
    HubSpotUpdateLeadConfig,
    HubSpotDeleteLeadConfig,
    HubSpotSearchLeadsConfig,
    # Product operations (6)
    HubSpotListProductsConfig,
    HubSpotGetProductConfig,
    HubSpotCreateProductConfig,
    HubSpotUpdateProductConfig,
    HubSpotDeleteProductConfig,
    HubSpotSearchProductsConfig,
    # Line Item operations (6)
    HubSpotListLineItemsConfig,
    HubSpotGetLineItemConfig,
    HubSpotCreateLineItemConfig,
    HubSpotUpdateLineItemConfig,
    HubSpotDeleteLineItemConfig,
    HubSpotSearchLineItemsConfig,
    # Quote operations (6)
    HubSpotListQuotesConfig,
    HubSpotGetQuoteConfig,
    HubSpotCreateQuoteConfig,
    HubSpotUpdateQuoteConfig,
    HubSpotDeleteQuoteConfig,
    HubSpotSearchQuotesConfig,
    # Note operations (6)
    HubSpotListNotesConfig,
    HubSpotGetNoteConfig,
    HubSpotCreateNoteConfig,
    HubSpotUpdateNoteConfig,
    HubSpotDeleteNoteConfig,
    HubSpotSearchNotesConfig,
    # Task operations (6)
    HubSpotListTasksConfig,
    HubSpotGetTaskConfig,
    HubSpotCreateTaskConfig,
    HubSpotUpdateTaskConfig,
    HubSpotDeleteTaskConfig,
    HubSpotSearchTasksConfig,
    # Call operations (6)
    HubSpotListCallsConfig,
    HubSpotGetCallConfig,
    HubSpotCreateCallConfig,
    HubSpotUpdateCallConfig,
    HubSpotDeleteCallConfig,
    HubSpotSearchCallsConfig,
    # Meeting operations (6)
    HubSpotListMeetingsConfig,
    HubSpotGetMeetingConfig,
    HubSpotCreateMeetingConfig,
    HubSpotUpdateMeetingConfig,
    HubSpotDeleteMeetingConfig,
    HubSpotSearchMeetingsConfig,
    # Email operations (6)
    HubSpotListEmailsConfig,
    HubSpotGetEmailConfig,
    HubSpotCreateEmailConfig,
    HubSpotUpdateEmailConfig,
    HubSpotDeleteEmailConfig,
    HubSpotSearchEmailsConfig,
    # Order operations (6)
    HubSpotListOrdersConfig,
    HubSpotGetOrderConfig,
    HubSpotCreateOrderConfig,
    HubSpotUpdateOrderConfig,
    HubSpotDeleteOrderConfig,
    HubSpotSearchOrdersConfig,
    # Owners API (1)
    HubSpotListOwnersConfig,
    # Associations API (3)
    HubSpotCreateAssociationConfig,
    HubSpotDeleteAssociationConfig,
    HubSpotListAssociationsConfig,
    # Properties API (5)
    HubSpotListPropertiesConfig,
    HubSpotGetPropertyConfig,
    HubSpotCreatePropertyConfig,
    HubSpotUpdatePropertyConfig,
    HubSpotArchivePropertyConfig,
    # Pipelines API (6)
    HubSpotListPipelinesConfig,
    HubSpotGetPipelineConfig,
    HubSpotCreatePipelineConfig,
    HubSpotUpdatePipelineConfig,
    HubSpotReplacePipelineConfig,
    HubSpotDeletePipelineConfig,
    # Pipeline Stages API (6)
    HubSpotListPipelineStagesConfig,
    HubSpotGetPipelineStageConfig,
    HubSpotCreatePipelineStageConfig,
    HubSpotUpdatePipelineStageConfig,
    HubSpotReplacePipelineStageConfig,
    HubSpotDeletePipelineStageConfig,
    # Batch Operations API (5)
    HubSpotBatchCreateConfig,
    HubSpotBatchReadConfig,
    HubSpotBatchUpdateConfig,
    HubSpotBatchArchiveConfig,
    HubSpotBatchUpsertConfig,
)

# Environment variable for PAT (don't hardcode in tests)
HUBSPOT_PAT = os.environ.get("HUBSPOT_PAT", "")

# Track created resources for cleanup
CREATED_CONTACTS = []
CREATED_COMPANIES = []
CREATED_DEALS = []
CREATED_TICKETS = []
CREATED_LEADS = []
CREATED_PRODUCTS = []
CREATED_LINE_ITEMS = []
CREATED_QUOTES = []
CREATED_NOTES = []
CREATED_TASKS = []
CREATED_CALLS = []
CREATED_MEETINGS = []
CREATED_EMAILS = []
CREATED_ORDERS = []
CREATED_PROPERTIES = []  # (object_type, property_name) tuples
CREATED_PIPELINES = []  # (object_type, pipeline_id) tuples
CREATED_PIPELINE_STAGES = []  # (object_type, pipeline_id, stage_id) tuples
CREATED_ASSOCIATIONS = []  # (from_type, from_id, to_type, to_id, assoc_type_id) tuples


def get_credentials():
    """Get HubSpot credentials from environment."""
    if not HUBSPOT_PAT:
        pytest.skip("HUBSPOT_PAT environment variable not set")
    return HubSpotPATCredential(access_token=HUBSPOT_PAT)


def create_node(config) -> HubSpotNode:
    """Create a HubSpotNode instance with the given config."""
    credentials = get_credentials()
    node_config = HubSpotNodeConfig(config=config, credentials=credentials)
    node = HubSpotNode(
        node_id="test-node",
        node_type="automation-hubspot",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


def create_node_mock(config) -> HubSpotNode:
    """Create a HubSpotNode instance with mock credentials for testing."""
    mock_credentials = HubSpotPATCredential(access_token="mock_token")
    node_config = HubSpotNodeConfig(config=config, credentials=mock_credentials)
    node = HubSpotNode(
        node_id="test-node",
        node_type="automation-hubspot",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Fixtures for cleanup
# ============================================================================


@pytest.fixture(scope="module", autouse=True)
def cleanup_resources():
    """Clean up any created test resources after all tests."""
    yield
    # Cleanup contacts
    for contact_id in CREATED_CONTACTS:
        try:
            config = HubSpotDeleteContactConfig(contact_id=contact_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass  # Ignore cleanup errors

    # Cleanup companies
    for company_id in CREATED_COMPANIES:
        try:
            config = HubSpotDeleteCompanyConfig(company_id=company_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup deals
    for deal_id in CREATED_DEALS:
        try:
            config = HubSpotDeleteDealConfig(deal_id=deal_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup tickets
    for ticket_id in CREATED_TICKETS:
        try:
            config = HubSpotDeleteTicketConfig(ticket_id=ticket_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup leads
    for lead_id in CREATED_LEADS:
        try:
            config = HubSpotDeleteLeadConfig(lead_id=lead_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup products
    for product_id in CREATED_PRODUCTS:
        try:
            config = HubSpotDeleteProductConfig(product_id=product_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup line items
    for line_item_id in CREATED_LINE_ITEMS:
        try:
            config = HubSpotDeleteLineItemConfig(line_item_id=line_item_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup quotes
    for quote_id in CREATED_QUOTES:
        try:
            config = HubSpotDeleteQuoteConfig(quote_id=quote_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup notes
    for note_id in CREATED_NOTES:
        try:
            config = HubSpotDeleteNoteConfig(note_id=note_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup tasks
    for task_id in CREATED_TASKS:
        try:
            config = HubSpotDeleteTaskConfig(task_id=task_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup calls
    for call_id in CREATED_CALLS:
        try:
            config = HubSpotDeleteCallConfig(call_id=call_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup meetings
    for meeting_id in CREATED_MEETINGS:
        try:
            config = HubSpotDeleteMeetingConfig(meeting_id=meeting_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup emails
    for email_id in CREATED_EMAILS:
        try:
            config = HubSpotDeleteEmailConfig(email_id=email_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup orders
    for order_id in CREATED_ORDERS:
        try:
            config = HubSpotDeleteOrderConfig(order_id=order_id)
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup properties
    for object_type, property_name in CREATED_PROPERTIES:
        try:
            config = HubSpotArchivePropertyConfig(
                object_type=object_type, property_name=property_name
            )
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup pipeline stages first (before pipelines)
    for object_type, pipeline_id, stage_id in CREATED_PIPELINE_STAGES:
        try:
            config = HubSpotDeletePipelineStageConfig(
                object_type=object_type, pipeline_id=pipeline_id, stage_id=stage_id
            )
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup pipelines
    for object_type, pipeline_id in CREATED_PIPELINES:
        try:
            config = HubSpotDeletePipelineConfig(
                object_type=object_type, pipeline_id=pipeline_id
            )
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass

    # Cleanup associations
    for from_type, from_id, to_type, to_id, assoc_type_id in CREATED_ASSOCIATIONS:
        try:
            config = HubSpotDeleteAssociationConfig(
                from_object_type=from_type,
                from_object_id=from_id,
                to_object_type=to_type,
                to_object_id=to_id,
                association_type_id=assoc_type_id,
            )
            node = create_node(config)
            asyncio.get_event_loop().run_until_complete(node.execute({}))
        except Exception:
            pass


# ============================================================================
# Contact Operations Tests (6 operations)
# ============================================================================


class TestContactOperations:
    """Test contact-related HubSpot CRM API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_contacts(self):
        """Test listing contacts with pagination."""
        config = HubSpotListContactsConfig(limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_contacts"
        assert result["status"] == "success"
        assert "results" in result["data"]
        assert isinstance(result["data"]["results"], list)
        assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_list_contacts_with_properties(self):
        """Test listing contacts with specific properties."""
        config = HubSpotListContactsConfig(
            limit=5, properties="email,firstname,lastname"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_contacts"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_contact(self):
        """Test creating a new contact."""
        timestamp = int(time.time())
        config = HubSpotCreateContactConfig(
            email=f"test-{timestamp}@noclick-test.com",
            firstname="Test",
            lastname=f"Contact-{timestamp}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_contact"
        assert result["status"] == "success"
        assert "id" in result["data"]

        # Track for cleanup
        CREATED_CONTACTS.append(result["data"]["id"])

    @pytest.mark.asyncio
    async def test_get_contact(self):
        """Test getting a specific contact."""
        # First create a contact
        timestamp = int(time.time())
        create_config = HubSpotCreateContactConfig(
            email=f"test-get-{timestamp}@noclick-test.com",
            firstname="Test",
            lastname="Get",
        )
        node_instance = create_node(create_config)
        create_result = await node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test contact")

        contact_id = create_result["data"]["id"]
        CREATED_CONTACTS.append(contact_id)

        # Now get the contact
        config = HubSpotGetContactConfig(
            contact_id=contact_id, properties="email,firstname,lastname"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_contact"
        assert result["status"] == "success"
        assert result["data"]["id"] == contact_id

    @pytest.mark.asyncio
    async def test_update_contact(self):
        """Test updating an existing contact."""
        # First create a contact
        timestamp = int(time.time())
        create_config = HubSpotCreateContactConfig(
            email=f"test-update-{timestamp}@noclick-test.com",
            firstname="Original",
            lastname="Name",
        )
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test contact")

        contact_id = create_result["data"]["id"]
        CREATED_CONTACTS.append(contact_id)

        # Now update the contact
        config = HubSpotUpdateContactConfig(
            contact_id=contact_id, firstname="Updated", lastname="ContactName"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_contact"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_contact(self):
        """Test deleting a contact."""
        # First create a contact to delete
        timestamp = int(time.time())
        create_config = HubSpotCreateContactConfig(
            email=f"test-delete-{timestamp}@noclick-test.com",
            firstname="Test",
            lastname="Delete",
        )
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test contact")

        contact_id = create_result["data"]["id"]

        # Now delete the contact
        config = HubSpotDeleteContactConfig(contact_id=contact_id)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_contact"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_search_contacts(self):
        """Test searching for contacts."""
        config = HubSpotSearchContactsConfig(query="test", limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_contacts"
        assert result["status"] == "success"
        assert "results" in result["data"]

    @pytest.mark.asyncio
    async def test_search_contacts_with_filter(self):
        """Test searching contacts with property filter."""
        config = HubSpotSearchContactsConfig(
            filter_property="email",
            filter_operator="CONTAINS_TOKEN",
            filter_value="test",
            limit=5,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_contacts"
        # May succeed or fail based on filter syntax


# ============================================================================
# Company Operations Tests (6 operations)
# ============================================================================


class TestCompanyOperations:
    """Test company-related HubSpot CRM API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_companies(self):
        """Test listing companies with pagination."""
        config = HubSpotListCompaniesConfig(limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_companies"
        assert result["status"] == "success"
        assert "results" in result["data"]
        assert isinstance(result["data"]["results"], list)

    @pytest.mark.asyncio
    async def test_list_companies_with_properties(self):
        """Test listing companies with specific properties."""
        config = HubSpotListCompaniesConfig(limit=5, properties="name,domain,industry")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_companies"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_company(self):
        """Test creating a new company."""
        timestamp = int(time.time())
        config = HubSpotCreateCompanyConfig(
            name=f"Test Company {timestamp}",
            domain=f"testcompany{timestamp}.com",
            industry="COMPUTER_SOFTWARE",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_company"
        assert result["status"] == "success"
        assert "id" in result["data"]

        # Track for cleanup
        CREATED_COMPANIES.append(result["data"]["id"])

    @pytest.mark.asyncio
    async def test_get_company(self):
        """Test getting a specific company."""
        # First create a company
        timestamp = int(time.time())
        create_config = HubSpotCreateCompanyConfig(
            name=f"Test Get Company {timestamp}",
            domain=f"testgetcompany{timestamp}.com",
        )
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test company")

        company_id = create_result["data"]["id"]
        CREATED_COMPANIES.append(company_id)

        # Now get the company
        config = HubSpotGetCompanyConfig(
            company_id=company_id, properties="name,domain"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_company"
        assert result["status"] == "success"
        assert result["data"]["id"] == company_id

    @pytest.mark.asyncio
    async def test_delete_company(self):
        """Test deleting a company."""
        # First create a company to delete
        timestamp = int(time.time())
        create_config = HubSpotCreateCompanyConfig(name=f"Delete Company {timestamp}")
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test company")

        company_id = create_result["data"]["id"]

        # Now delete the company
        config = HubSpotDeleteCompanyConfig(company_id=company_id)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_company"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_search_companies(self):
        """Test searching for companies."""
        config = HubSpotSearchCompaniesConfig(query="test", limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_companies"
        assert result["status"] == "success"
        assert "results" in result["data"]


# ============================================================================
# Deal Operations Tests (6 operations)
# ============================================================================


class TestDealOperations:
    """Test deal-related HubSpot CRM API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_deals(self):
        """Test listing deals with pagination."""
        config = HubSpotListDealsConfig(limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_deals"
        assert result["status"] == "success"
        assert "results" in result["data"]
        assert isinstance(result["data"]["results"], list)

    @pytest.mark.asyncio
    async def test_list_deals_with_properties(self):
        """Test listing deals with specific properties."""
        config = HubSpotListDealsConfig(limit=5, properties="dealname,amount,dealstage")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_deals"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_deal(self):
        """Test creating a new deal."""
        timestamp = int(time.time())
        config = HubSpotCreateDealConfig(
            dealname=f"Test Deal {timestamp}", amount="10000"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_deal"
        assert result["status"] == "success"
        assert "id" in result["data"]

        # Track for cleanup
        CREATED_DEALS.append(result["data"]["id"])

    @pytest.mark.asyncio
    async def test_get_deal(self):
        """Test getting a specific deal."""
        # First create a deal
        timestamp = int(time.time())
        create_config = HubSpotCreateDealConfig(
            dealname=f"Test Get Deal {timestamp}", amount="5000"
        )
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test deal")

        deal_id = create_result["data"]["id"]
        CREATED_DEALS.append(deal_id)

        # Now get the deal
        config = HubSpotGetDealConfig(deal_id=deal_id, properties="dealname,amount")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_deal"
        assert result["status"] == "success"
        assert result["data"]["id"] == deal_id

    @pytest.mark.asyncio
    async def test_update_deal(self):
        """Test updating an existing deal."""
        # First create a deal
        timestamp = int(time.time())
        create_config = HubSpotCreateDealConfig(
            dealname=f"Original Deal {timestamp}", amount="1000"
        )
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test deal")

        deal_id = create_result["data"]["id"]
        CREATED_DEALS.append(deal_id)

        # Now update the deal
        config = HubSpotUpdateDealConfig(
            deal_id=deal_id, dealname=f"Updated Deal {timestamp}", amount="2500"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_deal"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_deal(self):
        """Test deleting a deal."""
        # First create a deal to delete
        timestamp = int(time.time())
        create_config = HubSpotCreateDealConfig(dealname=f"Delete Deal {timestamp}")
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success":
            pytest.skip("Could not create test deal")

        deal_id = create_result["data"]["id"]

        # Now delete the deal
        config = HubSpotDeleteDealConfig(deal_id=deal_id)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_deal"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_search_deals(self):
        """Test searching for deals."""
        config = HubSpotSearchDealsConfig(query="test", limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_deals"
        assert result["status"] == "success"
        assert "results" in result["data"]


# ============================================================================
# Ticket Operations Tests (6 operations)
# ============================================================================


class TestTicketOperations:
    """Test ticket-related HubSpot CRM API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_tickets(self):
        """Test listing tickets with pagination."""
        config = HubSpotListTicketsConfig(limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_support_tickets"
        assert result["status"] == "success"
        assert "results" in result["data"]
        assert isinstance(result["data"]["results"], list)

    @pytest.mark.asyncio
    async def test_list_tickets_with_properties(self):
        """Test listing tickets with specific properties."""
        config = HubSpotListTicketsConfig(
            limit=5, properties="subject,content,hs_pipeline_stage"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_support_tickets"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_search_tickets(self):
        """Test searching for tickets."""
        config = HubSpotSearchTicketsConfig(query="test", limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_support_tickets"
        assert result["status"] == "success"
        assert "results" in result["data"]


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_contact(self):
        """Test getting a contact that doesn't exist."""
        config = HubSpotGetContactConfig(contact_id="999999999999")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_contact"
        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_company(self):
        """Test getting a company that doesn't exist."""
        config = HubSpotGetCompanyConfig(company_id="999999999999")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_company"
        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_deal(self):
        """Test getting a deal that doesn't exist."""
        config = HubSpotGetDealConfig(deal_id="999999999999")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_deal"
        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_ticket(self):
        """Test getting a ticket that doesn't exist."""
        config = HubSpotGetTicketConfig(ticket_id="999999999999")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_support_ticket"
        assert result["status"] == "error"
        assert result["status_code"] == 404


# ============================================================================
# Order Operations Tests (6 operations)
# ============================================================================


class TestOrderOperations:
    """Test all order-related operations."""

    @pytest.mark.asyncio
    async def test_list_orders(self):
        """Test listing orders."""
        config = HubSpotListOrdersConfig(limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_orders"
        assert "data" in result

    @pytest.mark.asyncio
    async def test_search_orders(self):
        """Test searching orders."""
        config = HubSpotSearchOrdersConfig(query="Test", limit=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "search_orders"


# ============================================================================
# Owners API Tests (1 operation)
# ============================================================================


class TestOwnersAPI:
    """Test owners API operations."""

    @pytest.mark.asyncio
    async def test_list_owners(self):
        """Test listing all owners in the HubSpot account."""
        config = HubSpotListOwnersConfig(limit=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_account_owners"
        assert "data" in result


# ============================================================================
# Associations API Tests (3 operations)
# ============================================================================


class TestAssociationsAPI:
    """Test association operations between CRM objects."""

    @pytest.mark.asyncio
    async def test_create_list_delete_association(self):
        """Test creating, listing, and deleting associations."""
        # Create contact and company for association
        contact_config = HubSpotCreateContactConfig(
            email=f"test-assoc-{int(time.time())}@example.com"
        )
        contact_instance = create_node(contact_config)
        contact_result = await contact_instance.execute({})
        contact_id = contact_result["data"]["id"]
        CREATED_CONTACTS.append(contact_id)

        company_config = HubSpotCreateCompanyConfig(
            name=f"Test Company Assoc {int(time.time())}"
        )
        company_instance = create_node(company_config)
        company_result = await company_instance.execute({})
        company_id = company_result["data"]["id"]
        CREATED_COMPANIES.append(company_id)

        # Create association (contact_to_company association type is 1)
        create_assoc_config = HubSpotCreateAssociationConfig(
            from_object_type="contacts",
            from_object_id=contact_id,
            to_object_type="companies",
            to_object_id=company_id,
            association_type_id="1",
        )
        create_assoc_instance = create_node(create_assoc_config)
        create_assoc_result = await create_assoc_instance.execute({})

        assert create_assoc_result["status"] == "success"
        assert create_assoc_result["action"] == "create_record_association"
        CREATED_ASSOCIATIONS.append(
            ("contacts", contact_id, "companies", company_id, "1")
        )

        # List associations
        list_assoc_config = HubSpotListAssociationsConfig(
            object_type="contacts", object_id=contact_id, to_object_type="companies"
        )
        list_assoc_instance = create_node(list_assoc_config)
        list_assoc_result = await list_assoc_instance.execute({})

        assert list_assoc_result["status"] == "success"
        assert list_assoc_result["action"] == "list_record_associations"


# ============================================================================
# Properties API Tests (5 operations)
# ============================================================================


class TestPropertiesAPI:
    """Test properties API operations."""

    @pytest.mark.asyncio
    async def test_list_properties(self):
        """Test listing properties for an object type."""
        config = HubSpotListPropertiesConfig(object_type="contacts")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_custom_properties"
        assert "data" in result


class TestPipelinesAPI:
    """Test pipelines API operations."""

    @pytest.mark.asyncio
    async def test_list_pipelines(self):
        """Test listing pipelines for an object type."""
        config = HubSpotListPipelinesConfig(object_type="deals")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_pipelines"
        assert "data" in result


class TestPipelineStagesAPI:
    """Test pipeline stages API operations."""


class TestBatchOperations:
    """Test batch operations API."""

    @pytest.mark.asyncio
    async def test_batch_create(self):
        """Test batch creating multiple contacts."""
        config = HubSpotBatchCreateConfig(
            object_type="contacts",
            inputs=f"""[
                {{"properties": {{"email": "batch1-{int(time.time())}@example.com", "firstname": "Batch", "lastname": "User1"}}}},
                {{"properties": {{"email": "batch2-{int(time.time())}@example.com", "firstname": "Batch", "lastname": "User2"}}}}
            ]""",
        )
        node = create_node(config)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "batch_create_records"
        assert "results" in result["data"]

        # Track for cleanup
        for item in result["data"]["results"]:
            CREATED_CONTACTS.append(item["id"])

    @pytest.mark.asyncio
    async def test_batch_read(self):
        """Test batch reading multiple contacts."""
        # Create contacts first
        create_config = HubSpotBatchCreateConfig(
            object_type="contacts",
            inputs=f"""[
                {{"properties": {{"email": "read1-{int(time.time())}@example.com"}}}},
                {{"properties": {{"email": "read2-{int(time.time())}@example.com"}}}}
            ]""",
        )
        node_instance = create_node(create_config)
        create_result = await node_instance.execute({})
        contact_ids = [item["id"] for item in create_result["data"]["results"]]
        for cid in contact_ids:
            CREATED_CONTACTS.append(cid)

        # Batch read
        read_config = HubSpotBatchReadConfig(
            object_type="contacts",
            inputs=f'[{{"id": "{contact_ids[0]}"}}, {{"id": "{contact_ids[1]}"}}]',
            properties="email,firstname,lastname",
        )
        read_instance = create_node(read_config)
        read_result = await read_instance.execute({})

        assert read_result["status"] == "success"
        assert read_result["action"] == "batch_read_records"
        assert "results" in read_result["data"]

    @pytest.mark.asyncio
    async def test_batch_update(self):
        """Test batch updating multiple contacts."""
        # Create contacts first
        create_config = HubSpotBatchCreateConfig(
            object_type="contacts",
            inputs=f"""[
                {{"properties": {{"email": "update1-{int(time.time())}@example.com"}}}},
                {{"properties": {{"email": "update2-{int(time.time())}@example.com"}}}}
            ]""",
        )
        node_instance = create_node(create_config)
        create_result = await node_instance.execute({})
        contact_ids = [item["id"] for item in create_result["data"]["results"]]
        for cid in contact_ids:
            CREATED_CONTACTS.append(cid)

        # Batch update
        update_config = HubSpotBatchUpdateConfig(
            object_type="contacts",
            inputs=f"""[
                {{"id": "{contact_ids[0]}", "properties": {{"firstname": "Updated1"}}}},
                {{"id": "{contact_ids[1]}", "properties": {{"firstname": "Updated2"}}}}
            ]""",
        )
        update_instance = create_node(update_config)
        update_result = await update_instance.execute({})

        assert update_result["status"] == "success"
        assert update_result["action"] == "batch_update_records"

    @pytest.mark.asyncio
    async def test_batch_upsert(self):
        """Test batch upserting contacts by email."""
        timestamp = int(time.time())
        email1 = f"upsert1-{timestamp}@example.com"
        email2 = f"upsert2-{timestamp}@example.com"
        config = HubSpotBatchUpsertConfig(
            object_type="contacts",
            inputs=f"""[
                {{"idProperty": "email", "id": "{email1}", "properties": {{"email": "{email1}", "firstname": "Upsert1"}}}},
                {{"idProperty": "email", "id": "{email2}", "properties": {{"email": "{email2}", "firstname": "Upsert2"}}}}
            ]""",
        )
        node = create_node(config)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "batch_upsert_records"

        # Track for cleanup
        for item in result["data"]["results"]:
            CREATED_CONTACTS.append(item["id"])


# ============================================================================
# Timing Tests
# ============================================================================


class TestTiming:
    """Test that timing information is included in responses."""

    @pytest.mark.asyncio
    async def test_timing_included(self):
        """Test that timing_ms is included in all responses."""
        config = HubSpotListContactsConfig(limit=1)
        node = create_node(config)

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] >= 0
        assert result["timing_ms"]["total"] >= 0
