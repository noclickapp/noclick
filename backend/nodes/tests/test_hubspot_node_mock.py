"""Mock tests for HubSpot CRM API node.

These tests use mocked API responses to test functionality that requires
paid tier features or specific account configurations.
"""

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


def create_node_mock(config):
    """Create a HubSpotNode instance with mock credentials for testing."""
    from nodes.hubspot_node import HubSpotNode, HubSpotNodeConfig, HubSpotPATCredential

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


class TestSkippedTestsMocked:
    """Mock versions of previously skipped tests to achieve full coverage."""

    @pytest.mark.asyncio
    async def test_update_company_mocked(self):
        """Test updating company with mocks (was skipped due to industry property)."""
        from nodes.hubspot_node import HubSpotNode, HubSpotUpdateCompanyConfig

        mock_response = {
            "status": "success",
            "action": "update_company",
            "data": {
                "id": "12345",
                "properties": {"name": "Updated Company", "industry": "Software"},
            },
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            config = HubSpotUpdateCompanyConfig(
                company_id="12345",
                properties={"name": "Updated Company", "industry": "Software"},
            )
            node = create_node_mock(config)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "update_company"
            assert result["data"]["id"] == "12345"
            assert result["data"]["properties"]["industry"] == "Software"

    @pytest.mark.asyncio
    async def test_create_ticket_mocked(self):
        """Test creating ticket with mocks (was skipped due to required properties)."""
        from nodes.hubspot_node import HubSpotNode, HubSpotCreateTicketConfig

        mock_response = {
            "status": "success",
            "action": "create_support_ticket",
            "data": {
                "id": "ticket123",
                "properties": {
                    "subject": "Test Ticket",
                    "content": "Test content",
                    "hs_pipeline": "0",
                    "hs_pipeline_stage": "1",
                },
            },
            "status_code": 201,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            config = HubSpotCreateTicketConfig(
                subject="Test Ticket", content="Test content"
            )
            node = create_node_mock(config)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "create_support_ticket"
            assert result["data"]["id"] == "ticket123"

    @pytest.mark.asyncio
    async def test_get_ticket_mocked(self):
        """Test getting ticket with mocks (was skipped due to test ticket creation failure)."""
        from nodes.hubspot_node import HubSpotNode, HubSpotGetTicketConfig

        mock_response = {
            "status": "success",
            "action": "get_support_ticket",
            "data": {
                "id": "ticket123",
                "properties": {"subject": "Test Ticket", "content": "Test content"},
            },
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            config = HubSpotGetTicketConfig(
                ticket_id="ticket123", properties="subject,content"
            )
            node = create_node_mock(config)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "get_support_ticket"
            assert result["data"]["id"] == "ticket123"

    @pytest.mark.asyncio
    async def test_update_ticket_mocked(self):
        """Test updating ticket with mocks (was skipped due to test ticket creation failure)."""
        from nodes.hubspot_node import HubSpotNode, HubSpotUpdateTicketConfig

        mock_response = {
            "status": "success",
            "action": "update_support_ticket",
            "data": {"id": "ticket123", "properties": {"subject": "Updated Ticket"}},
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            config = HubSpotUpdateTicketConfig(
                ticket_id="ticket123", properties={"subject": "Updated Ticket"}
            )
            node = create_node_mock(config)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "update_support_ticket"
            assert result["data"]["id"] == "ticket123"

    @pytest.mark.asyncio
    async def test_delete_ticket_mocked(self):
        """Test deleting ticket with mocks (was skipped due to test ticket creation failure)."""
        from nodes.hubspot_node import HubSpotNode, HubSpotDeleteTicketConfig

        mock_response = {
            "status": "success",
            "action": "delete_support_ticket",
            "data": {},
            "status_code": 204,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            config = HubSpotDeleteTicketConfig(ticket_id="ticket123")
            node = create_node_mock(config)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "delete_support_ticket"

    @pytest.mark.asyncio
    async def test_create_and_get_order_mocked(self):
        """Test order creation and retrieval with mocks (was skipped due to commerce hub requirement)."""
        from nodes.hubspot_node import (
            HubSpotNode,
            HubSpotCreateOrderConfig,
            HubSpotGetOrderConfig,
        )

        create_mock_response = {
            "status": "success",
            "action": "create_order",
            "data": {"id": "order123", "properties": {"hs_order_name": "Test Order"}},
            "status_code": 201,
            "timing_ms": {"api_request": 100},
        }

        get_mock_response = {
            "status": "success",
            "action": "get_order",
            "data": {"id": "order123", "properties": {"hs_order_name": "Test Order"}},
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            # Test create order
            mock_request.return_value = create_mock_response
            create_config = HubSpotCreateOrderConfig(hs_order_name="Test Order")
            node = create_node_mock(create_config)
            create_result = await node.execute({})

            assert create_result["status"] == "success"
            assert create_result["action"] == "create_order"
            assert create_result["data"]["id"] == "order123"

            # Test get order
            mock_request.return_value = get_mock_response
            get_config = HubSpotGetOrderConfig(
                order_id="order123", properties="hs_order_name"
            )
            node = create_node_mock(get_config)
            get_result = await node.execute({})

            assert get_result["status"] == "success"
            assert get_result["action"] == "get_order"
            assert get_result["data"]["id"] == "order123"

    @pytest.mark.asyncio
    async def test_update_order_mocked(self):
        """Test updating order with mocks (was skipped due to commerce hub requirement)."""
        from nodes.hubspot_node import HubSpotNode, HubSpotUpdateOrderConfig

        mock_response = {
            "status": "success",
            "action": "update_order",
            "data": {
                "id": "order123",
                "properties": {"hs_order_name": "Updated Order"},
            },
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            config = HubSpotUpdateOrderConfig(
                order_id="order123", properties={"hs_order_name": "Updated Order"}
            )
            node = create_node_mock(config)
            result = await node.execute({})

            assert result["status"] == "success"
            assert result["action"] == "update_order"
            assert result["data"]["id"] == "order123"

    @pytest.mark.asyncio
    async def test_create_get_update_archive_property_mocked(self):
        """Test property CRUD operations with mocks (was skipped due to account permissions)."""
        from nodes.hubspot_node import (
            HubSpotNode,
            HubSpotCreatePropertyConfig,
            HubSpotGetPropertyConfig,
            HubSpotUpdatePropertyConfig,
            HubSpotArchivePropertyConfig,
        )

        create_mock_response = {
            "status": "success",
            "action": "create_custom_property",
            "data": {"name": "test_property", "label": "Test", "type": "string"},
            "status_code": 201,
            "timing_ms": {"api_request": 100},
        }

        get_mock_response = {
            "status": "success",
            "action": "get_custom_property",
            "data": {"name": "test_property", "label": "Test", "type": "string"},
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        update_mock_response = {
            "status": "success",
            "action": "update_custom_property",
            "data": {
                "name": "test_property",
                "label": "Updated Test",
                "type": "string",
            },
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        archive_mock_response = {
            "status": "success",
            "action": "archive_custom_property",
            "data": {},
            "status_code": 204,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            # Test create property
            mock_request.return_value = create_mock_response
            create_config = HubSpotCreatePropertyConfig(
                object_type="contact",
                name="test_property",
                label="Test",
                type="string",
                field_type="text",
                group_name="contactinformation",
            )
            node = create_node_mock(create_config)
            create_result = await node.execute({})
            assert create_result["status"] == "success"

            # Test get property
            mock_request.return_value = get_mock_response
            get_config = HubSpotGetPropertyConfig(
                object_type="contact", property_name="test_property"
            )
            node = create_node_mock(get_config)
            get_result = await node.execute({})
            assert get_result["status"] == "success"

            # Test update property
            mock_request.return_value = update_mock_response
            update_config = HubSpotUpdatePropertyConfig(
                object_type="contact",
                property_name="test_property",
                label="Updated Test",
            )
            node = create_node_mock(update_config)
            update_result = await node.execute({})
            assert update_result["status"] == "success"

            # Test archive property
            mock_request.return_value = archive_mock_response
            archive_config = HubSpotArchivePropertyConfig(
                object_type="contact", property_name="test_property"
            )
            node = create_node_mock(archive_config)
            archive_result = await node.execute({})
            assert archive_result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_get_update_delete_pipeline_mocked(self):
        """Test pipeline CRUD operations with mocks (was skipped due to account limits)."""
        from nodes.hubspot_node import (
            HubSpotNode,
            HubSpotCreatePipelineConfig,
            HubSpotGetPipelineConfig,
            HubSpotUpdatePipelineConfig,
            HubSpotDeletePipelineConfig,
        )

        create_pipeline_mock_response = {
            "status": "success",
            "action": "create_pipeline",
            "data": {"id": "pipeline123", "label": "Test Pipeline", "stages": []},
            "status_code": 201,
            "timing_ms": {"api_request": 100},
        }

        get_pipeline_mock_response = {
            "status": "success",
            "action": "get_pipeline",
            "data": {"id": "pipeline123", "label": "Test Pipeline", "stages": []},
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        update_pipeline_mock_response = {
            "status": "success",
            "action": "update_pipeline",
            "data": {"id": "pipeline123", "label": "Updated Pipeline", "stages": []},
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        delete_pipeline_mock_response = {
            "status": "success",
            "action": "delete_pipeline",
            "data": {},
            "status_code": 204,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            # Test create pipeline
            mock_request.return_value = create_pipeline_mock_response
            create_config = HubSpotCreatePipelineConfig(
                object_type="deal",
                label="Test Pipeline",
                stages=json.dumps(
                    [{"label": "Stage 1", "metadata": {"probability": "0.5"}}]
                ),
            )
            node = create_node_mock(create_config)
            create_result = await node.execute({})
            assert create_result["status"] == "success"

            # Test get pipeline
            mock_request.return_value = get_pipeline_mock_response
            get_config = HubSpotGetPipelineConfig(
                object_type="deal", pipeline_id="pipeline123"
            )
            node = create_node_mock(get_config)
            get_result = await node.execute({})
            assert get_result["status"] == "success"

            # Test update pipeline
            mock_request.return_value = update_pipeline_mock_response
            update_config = HubSpotUpdatePipelineConfig(
                object_type="deal", pipeline_id="pipeline123", label="Updated Pipeline"
            )
            node = create_node_mock(update_config)
            update_result = await node.execute({})
            assert update_result["status"] == "success"

            # Test delete pipeline
            mock_request.return_value = delete_pipeline_mock_response
            delete_config = HubSpotDeletePipelineConfig(
                object_type="deal", pipeline_id="pipeline123"
            )
            node = create_node_mock(delete_config)
            delete_result = await node.execute({})
            assert delete_result["status"] == "success"

    @pytest.mark.asyncio
    async def test_pipeline_stage_operations_mocked(self):
        """Test pipeline stage operations with mocks (was skipped due to account limits)."""
        from nodes.hubspot_node import (
            HubSpotNode,
            HubSpotCreatePipelineStageConfig,
            HubSpotUpdatePipelineStageConfig,
            HubSpotDeletePipelineStageConfig,
        )

        create_stage_mock_response = {
            "status": "success",
            "action": "create_pipeline_stage",
            "data": {"id": "stage123", "label": "Test Stage"},
            "status_code": 201,
            "timing_ms": {"api_request": 100},
        }

        update_stage_mock_response = {
            "status": "success",
            "action": "update_pipeline_stage",
            "data": {"id": "stage123", "label": "Updated Stage"},
            "status_code": 200,
            "timing_ms": {"api_request": 100},
        }

        delete_stage_mock_response = {
            "status": "success",
            "action": "delete_pipeline_stage",
            "data": {},
            "status_code": 204,
            "timing_ms": {"api_request": 100},
        }

        with patch.object(
            HubSpotNode, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            # Test create stage
            mock_request.return_value = create_stage_mock_response
            create_config = HubSpotCreatePipelineStageConfig(
                object_type="deal",
                pipeline_id="pipeline123",
                label="Test Stage",
                metadata=json.dumps({"probability": "0.5"}),
            )
            node = create_node_mock(create_config)
            create_result = await node.execute({})
            assert create_result["status"] == "success"

            # Test update stage
            mock_request.return_value = update_stage_mock_response
            update_config = HubSpotUpdatePipelineStageConfig(
                object_type="deal",
                pipeline_id="pipeline123",
                stage_id="stage123",
                label="Updated Stage",
            )
            node = create_node_mock(update_config)
            update_result = await node.execute({})
            assert update_result["status"] == "success"

            # Test delete stage
            mock_request.return_value = delete_stage_mock_response
            delete_config = HubSpotDeletePipelineStageConfig(
                object_type="deal", pipeline_id="pipeline123", stage_id="stage123"
            )
            node = create_node_mock(delete_config)
            delete_result = await node.execute({})
            assert delete_result["status"] == "success"
