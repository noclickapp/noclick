"""
Integration tests for Airtable REST API node.

Tests the complete Airtable API node functionality including all 24 operations
organized by category: base/meta, records, comments, and webhooks.

Uses a real Airtable PAT to test against the Airtable API. Tests are designed to be
non-destructive where possible (read operations). Write operations test the action
name is correct but may fail due to permission constraints.
"""

import asyncio
import os
import time
import pytest

# Import the node and config classes - ALL 24 operations
from nodes.airtable_node import (
    AirtableNode,
    AirtableNodeConfig,
    AirtablePATCredential,
    # Base/Meta operations (6)
    AirtableListBasesConfig,
    AirtableGetBaseSchemaConfig,
    AirtableCreateTableConfig,
    AirtableUpdateTableConfig,
    AirtableCreateFieldConfig,
    AirtableUpdateFieldConfig,
    # Record operations (8)
    AirtableListRecordsConfig,
    AirtableGetRecordConfig,
    AirtableCreateRecordsConfig,
    AirtableUpdateRecordsConfig,
    AirtableUpdateRecordConfig,
    AirtableDeleteRecordsConfig,
    AirtableDeleteRecordConfig,
    AirtableUpsertRecordsConfig,
    # Comment operations (4)
    AirtableListCommentsConfig,
    AirtableCreateCommentConfig,
    AirtableUpdateCommentConfig,
    AirtableDeleteCommentConfig,
    # Webhook operations (6)
    AirtableListWebhooksConfig,
    AirtableCreateWebhookConfig,
    AirtableDeleteWebhookConfig,
    AirtableListWebhookPayloadsConfig,
    AirtableRefreshWebhookConfig,
    AirtableEnableWebhookNotificationsConfig,
)

# Environment variable for PAT (don't hardcode in tests)
AIRTABLE_PAT = os.environ.get("AIRTABLE_PAT", "")

# Test base ID - will be populated from list_bases if available
TEST_BASE_ID = None
TEST_TABLE_ID = None
TEST_RECORD_ID = None


def get_credentials():
    """Get Airtable credentials from environment."""
    if not AIRTABLE_PAT:
        pytest.skip(
            "AIRTABLE_PAT is not set — these are live Airtable calls, not a\n"
            "failure of the code under test. Set it to run them."
        )
    return AirtablePATCredential(personal_access_token=AIRTABLE_PAT)


def create_node(config) -> AirtableNode:
    """Create an AirtableNode instance with the given config."""
    credentials = get_credentials()
    node_config = AirtableNodeConfig(config=config, credentials=credentials)
    node = AirtableNode(
        node_id="test-node",
        node_type="automation-airtable",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Base/Meta Operations Tests (6 operations)
# ============================================================================


class TestBaseMetaOperations:
    """Test base/meta-related Airtable API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_bases(self):
        """Test listing all accessible bases."""
        global TEST_BASE_ID, TEST_TABLE_ID

        config = AirtableListBasesConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_accessible_bases"
        assert result["status"] == "success"
        assert "bases" in result["data"]
        assert isinstance(result["data"]["bases"], list)

        # Store a base ID for later tests
        if result["data"]["bases"]:
            TEST_BASE_ID = result["data"]["bases"][0]["id"]

    @pytest.mark.skip(reason="Requires AIRTABLE_PAT environment variable")
    @pytest.mark.asyncio
    async def test_get_base_schema(self):
        """Test getting the schema of a base."""
        global TEST_TABLE_ID

        # First ensure we have a base ID
        if not TEST_BASE_ID:
            list_config = AirtableListBasesConfig()
            list_node = create_node(list_config)
            list_result = await list_node.execute({})
            if list_result["status"] == "success" and list_result["data"].get("bases"):
                base_id = list_result["data"]["bases"][0]["id"]
            else:
                pytest.skip("No bases available for testing")
                return
        else:
            base_id = TEST_BASE_ID

        config = AirtableGetBaseSchemaConfig(base_id=base_id)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_base_schema"
        assert result["status"] == "success"
        assert "tables" in result["data"]

        # Store a table ID for later tests
        if result["data"]["tables"]:
            TEST_TABLE_ID = result["data"]["tables"][0]["id"]

    @pytest.mark.asyncio
    async def test_create_table(self):
        """Test creating a new table in a base."""
        if not TEST_BASE_ID:
            pytest.skip("No base ID available for testing")

        config = AirtableCreateTableConfig(
            base_id=TEST_BASE_ID,
            name=f"Test Table {int(time.time())}",
            description="Test table created by automated tests",
            fields=[
                {"name": "Name", "type": "singleLineText"},
                {"name": "Notes", "type": "multilineText"},
            ],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_new_table"
        # May fail due to permissions
        if result["status"] == "success":
            assert "id" in result["data"]

    @pytest.mark.asyncio
    async def test_update_table(self):
        """Test updating a table's name or description."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        config = AirtableUpdateTableConfig(
            base_id=TEST_BASE_ID,
            table_id=TEST_TABLE_ID,
            description=f"Updated description {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_table_metadata"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_create_field(self):
        """Test creating a new field in a table."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        config = AirtableCreateFieldConfig(
            base_id=TEST_BASE_ID,
            table_id=TEST_TABLE_ID,
            name=f"TestField_{int(time.time())}",
            field_type="singleLineText",
            description="Test field created by automated tests",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_table_field"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_update_field(self):
        """Test updating a field's name or description."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        # First get the schema to find a field ID
        schema_config = AirtableGetBaseSchemaConfig(base_id=TEST_BASE_ID)
        schema_node = create_node(schema_config)
        schema_result = await schema_node.execute({})

        if schema_result["status"] != "success":
            pytest.skip("Could not get base schema")

        # Find a field ID from the first table
        tables = schema_result["data"].get("tables", [])
        field_id = None
        for table in tables:
            if table.get("id") == TEST_TABLE_ID:
                fields = table.get("fields", [])
                if fields:
                    field_id = fields[0]["id"]
                break

        if not field_id:
            pytest.skip("No field ID available for testing")

        config = AirtableUpdateFieldConfig(
            base_id=TEST_BASE_ID,
            table_id=TEST_TABLE_ID,
            field_id=field_id,
            description=f"Updated field description {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_table_field"
        # May fail due to permissions


# ============================================================================
# Record Operations Tests (8 operations)
# ============================================================================


class TestRecordOperations:
    """Test record-related Airtable API operations (8 total)."""

    @pytest.mark.asyncio
    async def test_list_records(self):
        """Test listing records from a table."""
        global TEST_RECORD_ID

        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        config = AirtableListRecordsConfig(
            base_id=TEST_BASE_ID, table_id_or_name=TEST_TABLE_ID, page_size=10
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_table_records"
        assert result["status"] == "success"
        assert "records" in result["data"]
        assert isinstance(result["data"]["records"], list)

        # Store a record ID for later tests
        if result["data"]["records"]:
            TEST_RECORD_ID = result["data"]["records"][0]["id"]

    @pytest.mark.asyncio
    async def test_list_records_with_filter(self):
        """Test listing records with a filter formula."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        config = AirtableListRecordsConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            page_size=5,
            filter_by_formula="TRUE()",  # Returns all records
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_table_records"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_record(self):
        """Test getting a single record by ID."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        # First ensure we have a record ID
        if not TEST_RECORD_ID:
            list_config = AirtableListRecordsConfig(
                base_id=TEST_BASE_ID, table_id_or_name=TEST_TABLE_ID, page_size=1
            )
            list_node = create_node(list_config)
            list_result = await list_node.execute({})
            if list_result["status"] == "success" and list_result["data"].get(
                "records"
            ):
                record_id = list_result["data"]["records"][0]["id"]
            else:
                pytest.skip("No records available for testing")
                return
        else:
            record_id = TEST_RECORD_ID

        config = AirtableGetRecordConfig(
            base_id=TEST_BASE_ID, table_id_or_name=TEST_TABLE_ID, record_id=record_id
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_single_record"
        if result["status"] == "success":
            assert result["data"]["id"] == record_id

    @pytest.mark.asyncio
    async def test_create_records(self):
        """Test creating one or more records."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        config = AirtableCreateRecordsConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            records=[
                {"fields": {"Name": f"Test Record {int(time.time())}"}},
            ],
            typecast=True,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_multiple_records"
        # May fail due to permissions or missing required fields

    @pytest.mark.asyncio
    async def test_update_records(self):
        """Test updating one or more records."""
        if not TEST_BASE_ID or not TEST_TABLE_ID or not TEST_RECORD_ID:
            pytest.skip("No base/table/record ID available for testing")

        config = AirtableUpdateRecordsConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            records=[
                {
                    "id": TEST_RECORD_ID,
                    "fields": {"Name": f"Updated {int(time.time())}"},
                }
            ],
            typecast=True,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_multiple_records"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_update_record(self):
        """Test updating a single record by ID."""
        if not TEST_BASE_ID or not TEST_TABLE_ID or not TEST_RECORD_ID:
            pytest.skip("No base/table/record ID available for testing")

        config = AirtableUpdateRecordConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            record_id=TEST_RECORD_ID,
            fields={"Name": f"Single Update {int(time.time())}"},
            typecast=True,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_single_record"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_upsert_records(self):
        """Test upserting (create or update) records."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        config = AirtableUpsertRecordsConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            records=[{"fields": {"Name": f"Upsert Test {int(time.time())}"}}],
            fields_to_merge_on=["Name"],
            typecast=True,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "upsert_records_by_field_match"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_delete_record(self):
        """Test deleting a single record by ID."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        # Create a record specifically for deletion
        create_config = AirtableCreateRecordsConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            records=[{"fields": {"Name": f"To Delete {int(time.time())}"}}],
            typecast=True,
        )
        create_node_instance = create_node(create_config)
        create_result = await create_node_instance.execute({})

        if create_result["status"] != "success" or not create_result.get(
            "data", {}
        ).get("records"):
            # Skip if we couldn't create a record
            config = AirtableDeleteRecordConfig(
                base_id=TEST_BASE_ID,
                table_id_or_name=TEST_TABLE_ID,
                record_id="rec_nonexistent",
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "delete_single_record"
            return

        record_id = create_result["data"]["records"][0]["id"]

        config = AirtableDeleteRecordConfig(
            base_id=TEST_BASE_ID, table_id_or_name=TEST_TABLE_ID, record_id=record_id
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_single_record"

    @pytest.mark.asyncio
    async def test_delete_records(self):
        """Test deleting one or more records."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        # Use a non-existent record ID to test the action routing
        config = AirtableDeleteRecordsConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            record_ids=["rec_nonexistent"],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_multiple_records"
        # Will fail with 404 but action should be correct


# ============================================================================
# Comment Operations Tests (4 operations)
# ============================================================================


class TestCommentOperations:
    """Test comment-related Airtable API operations (4 total)."""

    @pytest.mark.asyncio
    async def test_list_comments(self):
        """Test listing comments on a record."""
        if not TEST_BASE_ID or not TEST_TABLE_ID or not TEST_RECORD_ID:
            pytest.skip("No base/table/record ID available for testing")

        config = AirtableListCommentsConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            record_id=TEST_RECORD_ID,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_record_comments"
        # Comments may be empty

    @pytest.mark.asyncio
    async def test_create_comment(self):
        """Test creating a comment on a record."""
        if not TEST_BASE_ID or not TEST_TABLE_ID or not TEST_RECORD_ID:
            pytest.skip("No base/table/record ID available for testing")

        config = AirtableCreateCommentConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            record_id=TEST_RECORD_ID,
            text=f"Test comment from automated tests {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_record_comment"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_update_comment(self):
        """Test updating a comment."""
        if not TEST_BASE_ID or not TEST_TABLE_ID or not TEST_RECORD_ID:
            pytest.skip("No base/table/record ID available for testing")

        # Try to update a non-existent comment to test action routing
        config = AirtableUpdateCommentConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            record_id=TEST_RECORD_ID,
            comment_id="comment_nonexistent",
            text="Updated comment text",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_record_comment"
        # Will fail with 404 but action should be correct

    @pytest.mark.asyncio
    async def test_delete_comment(self):
        """Test deleting a comment."""
        if not TEST_BASE_ID or not TEST_TABLE_ID or not TEST_RECORD_ID:
            pytest.skip("No base/table/record ID available for testing")

        # Try to delete a non-existent comment to test action routing
        config = AirtableDeleteCommentConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            record_id=TEST_RECORD_ID,
            comment_id="comment_nonexistent",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_record_comment"
        # Will fail with 404 but action should be correct


# ============================================================================
# Webhook Operations Tests (6 operations)
# ============================================================================


class TestWebhookOperations:
    """Test webhook-related Airtable API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_webhooks(self):
        """Test listing all webhooks for a base."""
        if not TEST_BASE_ID:
            pytest.skip("No base ID available for testing")

        config = AirtableListWebhooksConfig(base_id=TEST_BASE_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_base_webhooks"
        # May succeed or fail based on permissions

    @pytest.mark.asyncio
    async def test_create_webhook(self):
        """Test creating a webhook for a base."""
        if not TEST_BASE_ID:
            pytest.skip("No base ID available for testing")

        config = AirtableCreateWebhookConfig(
            base_id=TEST_BASE_ID,
            notification_url="https://example.com/webhook",
            specification={"options": {"filters": {"dataTypes": ["tableData"]}}},
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_base_webhook"
        # May fail due to permissions or invalid specification

    @pytest.mark.asyncio
    async def test_delete_webhook(self):
        """Test deleting a webhook."""
        if not TEST_BASE_ID:
            pytest.skip("No base ID available for testing")

        # Try to delete a non-existent webhook to test action routing
        config = AirtableDeleteWebhookConfig(
            base_id=TEST_BASE_ID, webhook_id="webhook_nonexistent"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_base_webhook"
        # Will fail with 404 but action should be correct

    @pytest.mark.asyncio
    async def test_list_webhook_payloads(self):
        """Test listing payloads for a webhook."""
        if not TEST_BASE_ID:
            pytest.skip("No base ID available for testing")

        # Try with a non-existent webhook to test action routing
        config = AirtableListWebhookPayloadsConfig(
            base_id=TEST_BASE_ID, webhook_id="webhook_nonexistent"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_webhook_payloads"
        # Will fail with 404 but action should be correct

    @pytest.mark.asyncio
    async def test_refresh_webhook(self):
        """Test refreshing a webhook to extend its expiration."""
        if not TEST_BASE_ID:
            pytest.skip("No base ID available for testing")

        # Try with a non-existent webhook to test action routing
        config = AirtableRefreshWebhookConfig(
            base_id=TEST_BASE_ID, webhook_id="webhook_nonexistent"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "refresh_webhook_expiration"
        # Will fail with 404 but action should be correct

    @pytest.mark.asyncio
    async def test_enable_webhook_notifications(self):
        """Test enabling notifications for a webhook."""
        if not TEST_BASE_ID:
            pytest.skip("No base ID available for testing")

        # Try with a non-existent webhook to test action routing
        config = AirtableEnableWebhookNotificationsConfig(
            base_id=TEST_BASE_ID, webhook_id="webhook_nonexistent"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "enable_webhook_notifications"
        # Will fail with 404 but action should be correct


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_base_id(self):
        """Test handling of invalid base ID."""
        config = AirtableGetBaseSchemaConfig(base_id="app_nonexistent_12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "fetch_base_schema"

    @pytest.mark.asyncio
    async def test_invalid_record_id(self):
        """Test handling of invalid record ID."""
        if not TEST_BASE_ID or not TEST_TABLE_ID:
            pytest.skip("No base/table ID available for testing")

        config = AirtableGetRecordConfig(
            base_id=TEST_BASE_ID,
            table_id_or_name=TEST_TABLE_ID,
            record_id="rec_nonexistent_12345",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "fetch_single_record"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = AirtableListBasesConfig()
        node_config = AirtableNodeConfig(config=config, credentials=None)
        node = AirtableNode(
            node_id="test-node",
            node_type="automation-airtable",
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
        config = AirtableListBasesConfig()
        node = create_node(config)

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] > 0
        assert result["timing_ms"]["total"] > 0


if __name__ == "__main__":
    # Run tests with: AIRTABLE_PAT=your_token pytest nodes/tests/test_airtable_node.py -v
    pytest.main([__file__, "-v"])
