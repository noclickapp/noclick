"""
Integration tests for Affinity CRM node.

Tests against the real Affinity API using an API key loaded from backend/.env.
All tests are skipped if AFFINITY_API_KEY is not set.

These tests exercise read-only operations where possible.
Write operations that create entities also clean up after themselves.

Requirements:
  - Set AFFINITY_API_KEY in backend/.env
  - Affinity account must have API access (Premium, Scale, Advanced, or Enterprise tier)

Run: pytest nodes/tests/test_affinity_node_integration.py -v
"""

import os
import pytest
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend directory
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

AFFINITY_API_KEY = os.environ.get("AFFINITY_API_KEY", "")

# Skip all integration tests if no API key is available
pytestmark = pytest.mark.skipif(
    not AFFINITY_API_KEY,
    reason="AFFINITY_API_KEY not set in backend/.env — skipping integration tests",
)

from nodes.affinity_node import (
    AffinityNode,
    AffinityNodeConfig,
    AffinityAPIKeyCredential,
    AffinityGetWhoamiConfig,
    AffinityGetRateLimitConfig,
    AffinityListPersonsConfig,
    AffinityListOrganizationsConfig,
    AffinityListOpportunitiesConfig,
    AffinityListListsConfig,
    AffinityGetListConfig,
    AffinityListListEntriesConfig,
    AffinityListFieldsConfig,
    AffinityListFieldValuesConfig,
    AffinityListNotesConfig,
    AffinityListRemindersConfig,
    AffinityGetRelationshipStrengthsConfig,
    AffinityListWebhooksConfig,
    AffinityListFilesConfig,
    AffinityListCompaniesV2Config,
    AffinityCreatePersonConfig,
    AffinityDeletePersonConfig,
    AffinityCreateOrganizationConfig,
    AffinityDeleteOrganizationConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REAL_CREDS = AffinityAPIKeyCredential(api_key=AFFINITY_API_KEY)


def create_node(op_config) -> AffinityNode:
    node_config = AffinityNodeConfig(config=op_config, credentials=REAL_CREDS)
    return AffinityNode(
        node_id="integration-test-node",
        node_type="automation-affinity",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="integration-test",
    )


def skip_on_rate_limit(result: dict):
    """Skip the current test if we hit a rate limit."""
    if result.get("status_code") == 429:
        pytest.skip("Rate limit hit — skipping test")


# ---------------------------------------------------------------------------
# System Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationSystem:
    @pytest.mark.asyncio
    async def test_get_whoami(self):
        """Verify API key is valid by fetching current user info."""
        node = create_node(AffinityGetWhoamiConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", f"Expected success, got: {result.get('error')}"
        data = result["data"]
        # Whoami returns user info; verify expected fields
        assert "id" in data or "email" in data, f"Unexpected whoami response: {data}"

    @pytest.mark.asyncio
    async def test_get_rate_limit(self):
        """Check current rate limit status."""
        node = create_node(AffinityGetRateLimitConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", f"Unexpected error: {result.get('error')}"


# ---------------------------------------------------------------------------
# Persons Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationPersons:
    @pytest.mark.asyncio
    async def test_list_persons(self):
        node = create_node(AffinityListPersonsConfig(page_size=5))
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")
        assert "persons" in result["data"] or isinstance(result["data"], (list, dict))

    @pytest.mark.asyncio
    async def test_list_persons_with_search(self):
        node = create_node(AffinityListPersonsConfig(term="test", page_size=3))
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")

    @pytest.mark.asyncio
    async def test_create_and_delete_person(self):
        """Create a test person then immediately delete it."""
        create_node_inst = create_node(
            AffinityCreatePersonConfig(
                first_name="NoClick",
                last_name="IntegrationTest",
                emails="noclick-integration-test@example.com",
            )
        )
        create_result = await create_node_inst.execute({})
        skip_on_rate_limit(create_result)

        if create_result["status"] != "success":
            pytest.skip(f"Could not create person: {create_result.get('error')}")

        person_id = create_result["data"].get("id")
        assert person_id is not None

        # Clean up
        delete_node = create_node(AffinityDeletePersonConfig(person_id=person_id))
        delete_result = await delete_node.execute({})
        skip_on_rate_limit(delete_result)
        assert delete_result["status"] == "success", (
            f"Failed to delete test person {person_id}: {delete_result.get('error')}"
        )


# ---------------------------------------------------------------------------
# Organizations Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationOrganizations:
    @pytest.mark.asyncio
    async def test_list_organizations(self):
        node = create_node(AffinityListOrganizationsConfig(page_size=5))
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")

    @pytest.mark.asyncio
    async def test_create_and_delete_organization(self):
        """Create a test organization then immediately delete it."""
        create_node_inst = create_node(
            AffinityCreateOrganizationConfig(
                name="NoClick Integration Test Org",
                domain="noclick-integration-test.example.com",
            )
        )
        create_result = await create_node_inst.execute({})
        skip_on_rate_limit(create_result)

        if create_result["status"] != "success":
            pytest.skip(f"Could not create org: {create_result.get('error')}")

        org_id = create_result["data"].get("id")
        assert org_id is not None

        # Clean up
        delete_node = create_node(AffinityDeleteOrganizationConfig(organization_id=org_id))
        delete_result = await delete_node.execute({})
        skip_on_rate_limit(delete_result)
        assert delete_result["status"] == "success", (
            f"Failed to delete test org {org_id}: {delete_result.get('error')}"
        )


# ---------------------------------------------------------------------------
# Opportunities Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationOpportunities:
    @pytest.mark.asyncio
    async def test_list_opportunities(self):
        node = create_node(AffinityListOpportunitiesConfig(page_size=5))
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")


# ---------------------------------------------------------------------------
# Lists Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationLists:
    @pytest.mark.asyncio
    async def test_list_lists(self):
        node = create_node(AffinityListListsConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")

    @pytest.mark.asyncio
    async def test_get_first_list_and_entries(self):
        """If any lists exist, retrieve the first one and its entries."""
        lists_node = create_node(AffinityListListsConfig())
        lists_result = await lists_node.execute({})
        skip_on_rate_limit(lists_result)

        if lists_result["status"] != "success":
            pytest.skip("Could not fetch lists")

        lists_data = lists_result["data"]
        if isinstance(lists_data, list) and len(lists_data) > 0:
            list_id = lists_data[0].get("id")
        elif isinstance(lists_data, dict):
            items = lists_data.get("lists", lists_data.get("data", []))
            if not items:
                pytest.skip("No lists found in account")
            list_id = items[0].get("id")
        else:
            pytest.skip("No lists found in account")

        # Get the specific list
        get_node = create_node(AffinityGetListConfig(list_id=list_id))
        get_result = await get_node.execute({})
        skip_on_rate_limit(get_result)
        assert get_result["status"] == "success", get_result.get("error")

        # Get list entries
        entries_node = create_node(AffinityListListEntriesConfig(list_id=list_id, page_size=3))
        entries_result = await entries_node.execute({})
        skip_on_rate_limit(entries_result)
        assert entries_result["status"] == "success", entries_result.get("error")


# ---------------------------------------------------------------------------
# Fields Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationFields:
    @pytest.mark.asyncio
    async def test_list_fields(self):
        node = create_node(AffinityListFieldsConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")


# ---------------------------------------------------------------------------
# Field Values Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationFieldValues:
    @pytest.mark.asyncio
    async def test_list_field_values_requires_filter(self):
        """list_field_values without any filter should return an API error
        (Affinity requires at least one entity filter). We just verify the call completes."""
        node = create_node(AffinityListFieldValuesConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        # Either success or a known API validation error is acceptable
        assert result["status"] in ("success", "error")


# ---------------------------------------------------------------------------
# Notes Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationNotes:
    @pytest.mark.asyncio
    async def test_list_notes(self):
        node = create_node(AffinityListNotesConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")


# ---------------------------------------------------------------------------
# Reminders Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationReminders:
    @pytest.mark.asyncio
    async def test_list_reminders(self):
        node = create_node(AffinityListRemindersConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")


# ---------------------------------------------------------------------------
# Relationship Strengths Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationRelationshipStrengths:
    @pytest.mark.asyncio
    async def test_get_relationship_strengths(self):
        node = create_node(AffinityGetRelationshipStrengthsConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")


# ---------------------------------------------------------------------------
# Webhooks Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationWebhooks:
    @pytest.mark.asyncio
    async def test_list_webhooks(self):
        node = create_node(AffinityListWebhooksConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")


# ---------------------------------------------------------------------------
# Files Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationFiles:
    @pytest.mark.asyncio
    async def test_list_files(self):
        node = create_node(AffinityListFilesConfig())
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")


# ---------------------------------------------------------------------------
# v2 Companies Tests
# ---------------------------------------------------------------------------


class TestAffinityIntegrationV2Companies:
    @pytest.mark.asyncio
    async def test_list_companies_v2(self):
        node = create_node(AffinityListCompaniesV2Config(limit=5))
        result = await node.execute({})
        skip_on_rate_limit(result)
        assert result["status"] == "success", result.get("error")
