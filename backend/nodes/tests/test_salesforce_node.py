"""
Mocked unit tests for Salesforce REST API node.

Tests all 55 operations using mocked HTTP responses. No real Salesforce
credentials required - all API calls are mocked.

Operations tested:
- Query (3): query, query_more, search
- Record (5): get_record, create_record, update_record, delete_record, upsert_record
- Batch (3): create_records, update_records, delete_records
- Describe (3): list_objects, describe_object, describe_global
- Utility (4): get_limits, get_user_info, get_versions, get_tabs
- Approval Process (3): list_approval_processes, submit_for_approval, approve_reject
- File/Attachment (3): get_blob, create_attachment, create_content_version
- Composite (2): composite_request, sobject_tree
- Recently Viewed (1): get_recently_viewed
- Quick Actions (3): list_quick_actions, list_object_quick_actions, execute_quick_action
- Layouts (2): get_layouts, get_compact_layouts
- Bulk API 2.0 (7): create_bulk_job, upload_bulk_data, close_bulk_job, get_bulk_job_status,
                     get_bulk_job_results, abort_bulk_job, list_bulk_jobs
- Reports (3): list_reports, run_report, get_report_metadata
- Deleted/Updated Records (3): get_deleted, get_updated, query_all
- List Views (3): list_listviews, get_listview, execute_listview
- Dashboards (3): list_dashboards, get_dashboard, refresh_dashboard
- Invocable Actions (3): list_invocable_actions, get_invocable_action, execute_invocable_action
- Chatter (2): post_to_chatter, get_chatter_feed

Run: pytest nodes/tests/test_salesforce_node.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager
import httpx

from nodes.salesforce_node import (
    SalesforceNode,
    SalesforceNodeConfig,
    SalesforceOAuthCredential,
    # Query operations
    SalesforceQueryConfig,
    SalesforceQueryMoreConfig,
    SalesforceSearchConfig,
    # Record operations
    SalesforceGetRecordConfig,
    SalesforceCreateRecordConfig,
    SalesforceUpdateRecordConfig,
    SalesforceDeleteRecordConfig,
    SalesforceUpsertRecordConfig,
    # Batch operations
    SalesforceCreateRecordsConfig,
    SalesforceUpdateRecordsConfig,
    SalesforceDeleteRecordsConfig,
    # Describe operations
    SalesforceListObjectsConfig,
    SalesforceDescribeObjectConfig,
    SalesforceDescribeGlobalConfig,
    # Utility operations
    SalesforceGetLimitsConfig,
    SalesforceGetUserInfoConfig,
    SalesforceGetVersionsConfig,
    SalesforceGetTabsConfig,
    # Approval Process operations
    SalesforceListApprovalProcessesConfig,
    SalesforceSubmitForApprovalConfig,
    SalesforceApproveRejectConfig,
    # File/Attachment operations
    SalesforceGetBlobConfig,
    SalesforceDownloadContentVersionConfig,
    SalesforceCreateAttachmentConfig,
    SalesforceCreateContentVersionConfig,
    # Composite operations
    SalesforceCompositeRequestConfig,
    SalesforceSObjectTreeConfig,
    # Recently Viewed operations
    SalesforceGetRecentlyViewedConfig,
    # Quick Actions operations
    SalesforceListQuickActionsConfig,
    SalesforceListObjectQuickActionsConfig,
    SalesforceExecuteQuickActionConfig,
    # Layouts operations
    SalesforceGetLayoutsConfig,
    SalesforceGetCompactLayoutsConfig,
    # Bulk API 2.0 operations
    SalesforceCreateBulkJobConfig,
    SalesforceUploadBulkDataConfig,
    SalesforceCloseBulkJobConfig,
    SalesforceGetBulkJobStatusConfig,
    SalesforceGetBulkJobResultsConfig,
    SalesforceAbortBulkJobConfig,
    SalesforceListBulkJobsConfig,
    # Reports operations
    SalesforceListReportsConfig,
    SalesforceRunReportConfig,
    SalesforceGetReportMetadataConfig,
    # Deleted/Updated Records operations
    SalesforceGetDeletedConfig,
    SalesforceGetUpdatedConfig,
    SalesforceQueryAllConfig,
    # List Views operations
    SalesforceListListViewsConfig,
    SalesforceGetListViewConfig,
    SalesforceExecuteListViewConfig,
    # Dashboard operations
    SalesforceListDashboardsConfig,
    SalesforceGetDashboardConfig,
    SalesforceRefreshDashboardConfig,
    # Invocable Actions operations
    SalesforceListInvocableActionsConfig,
    SalesforceGetInvocableActionConfig,
    SalesforceExecuteInvocableActionConfig,
    # Chatter operations
    SalesforcePostToChatterConfig,
    SalesforceGetChatterFeedConfig,
)


# Test credentials (mock)
TEST_CREDENTIALS = SalesforceOAuthCredential(
    access_token="test_access_token",
    refresh_token="test_refresh_token",
    instance_url="https://test.salesforce.com",
    expires_at="2099-12-31T23:59:59Z",
    is_sandbox=False,
)


def create_node(config) -> SalesforceNode:
    """Create a SalesforceNode instance with mock credentials."""
    node_config = SalesforceNodeConfig(config=config, credentials=TEST_CREDENTIALS)
    return SalesforceNode(
        node_id="test-node",
        node_type="automation-salesforce",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
        user_id="test-user",
    )


def mock_api_response(data, status_code=200):
    """Create a mock httpx response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = data
    response.text = str(data)
    response.headers = {"Content-Type": "application/json"}
    response.content = b"test content"
    return response


def create_mock_client(mock_response):
    """Create a mock httpx.AsyncClient with context manager support."""
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.patch = AsyncMock(return_value=mock_response)
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.delete = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ============================================================================
# Query Operations Tests (3)
# ============================================================================


class TestQueryOperations:
    """Test query-related operations."""

    @pytest.mark.asyncio
    async def test_query(self):
        """Test SOQL query."""
        config = SalesforceQueryConfig(query="SELECT Id, Name FROM Account LIMIT 5")
        node = create_node(config)

        mock_data = {
            "totalSize": 2,
            "done": True,
            "records": [
                {"Id": "001xx001", "Name": "Test Account 1"},
                {"Id": "001xx002", "Name": "Test Account 2"},
            ],
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_soql_query"
        assert result["data"]["totalSize"] == 2

    @pytest.mark.asyncio
    async def test_query_more(self):
        """Test query pagination."""
        config = SalesforceQueryMoreConfig(
            next_records_url="/services/data/v59.0/query/abc123-next"
        )
        node = create_node(config)

        mock_data = {"totalSize": 100, "done": True, "records": [{"Id": "001xx003"}]}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_query_result_next_batch"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "next_url",
        [
            "@attacker.example/collect",
            "https://attacker.example/collect",
        ],
    )
    async def test_query_more_never_sends_bearer_off_instance_origin(self, next_url):
        from utils.ssrf import SSRFError

        node = create_node(SalesforceQueryMoreConfig(next_records_url=next_url))
        node._get_access_token = AsyncMock()

        with patch("httpx.AsyncClient") as client:
            with pytest.raises(SSRFError, match="outside"):
                await node.execute({})

        node._get_access_token.assert_not_awaited()
        client.assert_not_called()

    @pytest.mark.asyncio
    async def test_search(self):
        """Test SOSL search."""
        config = SalesforceSearchConfig(
            search_query="FIND {Test} IN ALL FIELDS RETURNING Account(Id, Name)"
        )
        node = create_node(config)

        mock_data = {"searchRecords": [{"Id": "001xx001", "Name": "Test"}]}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_sosl_search"


# ============================================================================
# Record Operations Tests (5)
# ============================================================================


class TestRecordOperations:
    """Test record CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_record(self):
        """Test getting a single record."""
        config = SalesforceGetRecordConfig(
            sobject_type="Account", record_id="001xx001", fields=["Id", "Name"]
        )
        node = create_node(config)

        mock_data = {"Id": "001xx001", "Name": "Test Account"}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_single_record"
        assert result["data"]["Id"] == "001xx001"

    @pytest.mark.asyncio
    async def test_create_record(self):
        """Test creating a record."""
        config = SalesforceCreateRecordConfig(
            sobject_type="Account", fields={"Name": "New Account"}
        )
        node = create_node(config)

        mock_data = {"id": "001xx003", "success": True, "errors": []}

        mock_client = create_mock_client(mock_api_response(mock_data, 201))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_single_record"
        assert result["data"]["success"] == True

    @pytest.mark.asyncio
    async def test_update_record(self):
        """Test updating a record."""
        config = SalesforceUpdateRecordConfig(
            sobject_type="Account",
            record_id="001xx001",
            fields={"Name": "Updated Account"},
        )
        node = create_node(config)

        mock_client = create_mock_client(mock_api_response({}, 204))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_single_record"

    @pytest.mark.asyncio
    async def test_delete_record(self):
        """Test deleting a record."""
        config = SalesforceDeleteRecordConfig(
            sobject_type="Account", record_id="001xx001"
        )
        node = create_node(config)

        mock_client = create_mock_client(mock_api_response({}, 204))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_single_record"

    @pytest.mark.asyncio
    async def test_upsert_record(self):
        """Test upserting a record."""
        config = SalesforceUpsertRecordConfig(
            sobject_type="Account",
            external_id_field="External_Id__c",
            external_id_value="EXT001",
            fields={"Name": "Upserted Account"},
        )
        node = create_node(config)

        mock_data = {"id": "001xx004", "success": True, "created": True}

        mock_client = create_mock_client(mock_api_response(mock_data, 201))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upsert_record_by_external_id"


# ============================================================================
# Batch Operations Tests (3)
# ============================================================================


class TestBatchOperations:
    """Test batch operations."""

    @pytest.mark.asyncio
    async def test_create_records(self):
        """Test creating multiple records."""
        config = SalesforceCreateRecordsConfig(
            sobject_type="Account",
            records=[{"Name": "Account 1"}, {"Name": "Account 2"}],
            all_or_none=True,
        )
        node = create_node(config)

        mock_data = [
            {"id": "001xx005", "success": True},
            {"id": "001xx006", "success": True},
        ]

        mock_client = create_mock_client(mock_api_response(mock_data, 200))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_multiple_records"

    @pytest.mark.asyncio
    async def test_update_records(self):
        """Test updating multiple records."""
        config = SalesforceUpdateRecordsConfig(
            sobject_type="Account",
            records=[
                {"Id": "001xx001", "Name": "Updated 1"},
                {"Id": "001xx002", "Name": "Updated 2"},
            ],
        )
        node = create_node(config)

        mock_data = [
            {"id": "001xx001", "success": True},
            {"id": "001xx002", "success": True},
        ]

        mock_client = create_mock_client(mock_api_response(mock_data, 200))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_multiple_records"

    @pytest.mark.asyncio
    async def test_delete_records(self):
        """Test deleting multiple records."""
        config = SalesforceDeleteRecordsConfig(
            record_ids=["001xx001", "001xx002"], all_or_none=True
        )
        node = create_node(config)

        mock_data = [
            {"id": "001xx001", "success": True},
            {"id": "001xx002", "success": True},
        ]

        mock_client = create_mock_client(mock_api_response(mock_data, 200))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_multiple_records"


# ============================================================================
# Describe Operations Tests (3)
# ============================================================================


class TestDescribeOperations:
    """Test describe/metadata operations."""

    @pytest.mark.asyncio
    async def test_list_objects(self):
        """Test listing sObjects."""
        config = SalesforceListObjectsConfig()
        node = create_node(config)

        mock_data = {
            "sobjects": [
                {"name": "Account", "label": "Account"},
                {"name": "Contact", "label": "Contact"},
            ]
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_available_sobjects"
        assert "sobjects" in result["data"]

    @pytest.mark.asyncio
    async def test_describe_object(self):
        """Test describing a specific object."""
        config = SalesforceDescribeObjectConfig(sobject_type="Account")
        node = create_node(config)

        mock_data = {"name": "Account", "fields": [{"name": "Id"}, {"name": "Name"}]}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_sobject_metadata"
        assert "fields" in result["data"]

    @pytest.mark.asyncio
    async def test_describe_global(self):
        """Test global describe."""
        config = SalesforceDescribeGlobalConfig()
        node = create_node(config)

        mock_data = {"encoding": "UTF-8", "maxBatchSize": 200, "sobjects": []}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_org_global_metadata"


# ============================================================================
# Utility Operations Tests (4)
# ============================================================================


class TestUtilityOperations:
    """Test utility operations."""

    @pytest.mark.asyncio
    async def test_get_limits(self):
        """Test getting org limits."""
        config = SalesforceGetLimitsConfig()
        node = create_node(config)

        mock_data = {"DailyApiRequests": {"Max": 100000, "Remaining": 99000}}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_org_api_limits"
        assert "DailyApiRequests" in result["data"]

    @pytest.mark.asyncio
    async def test_get_user_info(self):
        """Test getting user info."""
        config = SalesforceGetUserInfoConfig()
        node = create_node(config)

        mock_data = {"user_id": "005xx001", "username": "test@example.com"}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_current_user_info"

    @pytest.mark.asyncio
    async def test_get_versions(self):
        """Test getting API versions."""
        config = SalesforceGetVersionsConfig()
        node = create_node(config)

        mock_data = [{"version": "59.0", "url": "/services/data/v59.0"}]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_available_api_versions"

    @pytest.mark.asyncio
    async def test_get_tabs(self):
        """Test getting tabs."""
        config = SalesforceGetTabsConfig()
        node = create_node(config)

        mock_data = [{"name": "Account", "label": "Accounts"}]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_user_available_tabs"


# ============================================================================
# Approval Process Operations Tests (3)
# ============================================================================


class TestApprovalProcessOperations:
    """Test approval process operations."""

    @pytest.mark.asyncio
    async def test_list_approval_processes(self):
        """Test listing approval processes."""
        config = SalesforceListApprovalProcessesConfig()
        node = create_node(config)

        mock_data = {"approvals": {"Account": []}}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_approval_processes"

    @pytest.mark.asyncio
    async def test_submit_for_approval(self):
        """Test submitting a record for approval."""
        config = SalesforceSubmitForApprovalConfig(
            record_id="001xx001", comments="Please approve"
        )
        node = create_node(config)

        mock_data = [
            {"success": True, "instanceId": "04gxx001", "newWorkitemIds": ["04ixx001"]}
        ]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "submit_record_for_approval"

    @pytest.mark.asyncio
    async def test_approve_reject(self):
        """Test approving/rejecting approval requests."""
        config = SalesforceApproveRejectConfig(
            work_item_ids=["04ixx001"], action_type="Approve", comments="Approved"
        )
        node = create_node(config)

        mock_data = [{"success": True}]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "approve_or_reject_approval_request"


# ============================================================================
# File/Attachment Operations Tests (3)
# ============================================================================


class TestFileOperations:
    """Test file/attachment operations."""

    @pytest.mark.asyncio
    async def test_get_blob(self):
        """Test getting blob data: bytes are stored to R2 and resolved to a ref."""
        config = SalesforceGetBlobConfig(
            sobject_type="Attachment", record_id="00Pxx001", blob_field="Body"
        )
        node = create_node(config)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b"test file content"
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.json.return_value = {}
        mock_response.text = ""

        fake_create = AsyncMock(
            return_value={
                "download_url": "https://assets.test/00Pxx001_Body.pdf",
                "mime_type": "application/pdf",
                "name": "00Pxx001_Body.pdf",
                "size_bytes": len(b"test file content"),
            }
        )

        mock_client = create_mock_client(mock_response)
        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "nodes.core.binary_output.create_resource_from_bytes", fake_create
        ):
            result = await node.run({})

        assert result["status"] == "success"
        assert result["action"] == "get_blob_field_content"
        assert result["data"]["content_type"] == "application/pdf"
        blob = result["data"]["blob"]
        assert blob["url"] == "https://assets.test/00Pxx001_Body.pdf"
        assert blob["mime_type"] == "application/pdf"
        assert blob["name"] == "00Pxx001_Body.pdf"
        assert blob["size_bytes"] == len(b"test file content")
        assert "base64" not in blob
        # the raw bytes are handed to the resource store, not base64-encoded inline
        assert fake_create.await_args.kwargs["body"] == b"test file content"

    @pytest.mark.asyncio
    async def test_download_content_version(self):
        """ContentVersion download returns a usable BinaryOutput (R2 ref), not an
        inline base64 blob — bytes go to the resource store."""
        config = SalesforceDownloadContentVersionConfig(version_id="068xx001")
        node = create_node(config)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b"pdf-bytes"
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.json.return_value = {}
        mock_response.text = ""

        fake_create = AsyncMock(
            return_value={
                "download_url": "https://assets.test/068xx001.pdf",
                "mime_type": "application/pdf",
                "name": "068xx001.pdf",
                "size_bytes": len(b"pdf-bytes"),
            }
        )
        mock_client = create_mock_client(mock_response)
        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "nodes.core.binary_output.create_resource_from_bytes", fake_create
        ):
            result = await node.run({})

        assert result["status"] == "success"
        assert result["action"] == "download_content_version"
        blob = result["data"]["blob"]
        assert blob["url"] == "https://assets.test/068xx001.pdf"
        assert blob["mime_type"] == "application/pdf"
        assert blob["name"] == "068xx001.pdf"
        assert blob["size_bytes"] == len(b"pdf-bytes")
        assert "base64" not in result["data"]  # no inline base64 anywhere
        assert fake_create.await_args.kwargs["body"] == b"pdf-bytes"

    @pytest.mark.asyncio
    async def test_create_attachment(self):
        """Test creating an attachment."""
        config = SalesforceCreateAttachmentConfig(
            parent_id="001xx001",
            name="test.pdf",
            body="dGVzdCBjb250ZW50",  # base64 "test content"
            content_type="application/pdf",
        )
        node = create_node(config)

        mock_data = {"id": "00Pxx002", "success": True}

        mock_client = create_mock_client(mock_api_response(mock_data, 201))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_record_attachment"

    @pytest.mark.asyncio
    async def test_create_content_version(self):
        """Test uploading a file."""
        config = SalesforceCreateContentVersionConfig(
            title="Test File",
            path_on_client="test.pdf",
            version_data="dGVzdCBjb250ZW50",
        )
        node = create_node(config)

        mock_data = {"id": "068xx001", "success": True}

        mock_client = create_mock_client(mock_api_response(mock_data, 201))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upload_file_as_content_version"


# ============================================================================
# Composite Operations Tests (2)
# ============================================================================


class TestCompositeOperations:
    """Test composite operations."""

    @pytest.mark.asyncio
    async def test_composite_request(self):
        """Test composite request."""
        config = SalesforceCompositeRequestConfig(
            composite_requests=[
                {
                    "method": "GET",
                    "url": "/services/data/v59.0/sobjects/Account/001xx001",
                    "referenceId": "ref1",
                }
            ],
            all_or_none=True,
        )
        node = create_node(config)

        mock_data = {
            "compositeResponse": [{"httpStatusCode": 200, "body": {"Id": "001xx001"}}]
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_composite_api_request"

    @pytest.mark.asyncio
    async def test_sobject_tree(self):
        """Test sObject tree creation."""
        config = SalesforceSObjectTreeConfig(
            sobject_type="Account",
            records=[
                {
                    "attributes": {"type": "Account", "referenceId": "ref1"},
                    "Name": "Parent Account",
                    "Contacts": {
                        "records": [
                            {
                                "attributes": {
                                    "type": "Contact",
                                    "referenceId": "ref2",
                                },
                                "LastName": "Smith",
                            }
                        ]
                    },
                }
            ],
        )
        node = create_node(config)

        mock_data = {
            "hasErrors": False,
            "results": [{"referenceId": "ref1", "id": "001xx007"}],
        }

        mock_client = create_mock_client(mock_api_response(mock_data, 201))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_nested_record_tree"


# ============================================================================
# Recently Viewed Operations Tests (1)
# ============================================================================


class TestRecentlyViewedOperations:
    """Test recently viewed operations."""

    @pytest.mark.asyncio
    async def test_get_recently_viewed(self):
        """Test getting recently viewed records."""
        config = SalesforceGetRecentlyViewedConfig(limit=10)
        node = create_node(config)

        mock_data = [{"Id": "001xx001", "Name": "Test Account"}]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_recently_viewed_records"


# ============================================================================
# Quick Actions Operations Tests (3)
# ============================================================================


class TestQuickActionsOperations:
    """Test quick actions operations."""

    @pytest.mark.asyncio
    async def test_list_quick_actions(self):
        """Test listing global quick actions."""
        config = SalesforceListQuickActionsConfig()
        node = create_node(config)

        mock_data = [{"name": "NewCase", "label": "New Case"}]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_global_quick_actions"

    @pytest.mark.asyncio
    async def test_list_object_quick_actions(self):
        """Test listing object-specific quick actions."""
        config = SalesforceListObjectQuickActionsConfig(sobject_type="Account")
        node = create_node(config)

        mock_data = [{"name": "Account.NewContact", "label": "New Contact"}]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_object_quick_actions"

    @pytest.mark.asyncio
    async def test_execute_quick_action(self):
        """Test executing a quick action."""
        config = SalesforceExecuteQuickActionConfig(
            quick_action_name="NewCase", record={"Subject": "Test Case"}
        )
        node = create_node(config)

        mock_data = {"id": "500xx001", "success": True}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_quick_action"


# ============================================================================
# Layouts Operations Tests (2)
# ============================================================================


class TestLayoutsOperations:
    """Test layouts operations."""

    @pytest.mark.asyncio
    async def test_get_layouts(self):
        """Test getting page layouts."""
        config = SalesforceGetLayoutsConfig(sobject_type="Account")
        node = create_node(config)

        mock_data = {"layouts": [{"id": "00hxx001"}]}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_sobject_page_layouts"

    @pytest.mark.asyncio
    async def test_get_compact_layouts(self):
        """Test getting compact layouts."""
        config = SalesforceGetCompactLayoutsConfig(sobject_type="Account")
        node = create_node(config)

        mock_data = {"compactLayouts": []}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_sobject_compact_layouts"


# ============================================================================
# Bulk API 2.0 Operations Tests (7)
# ============================================================================


class TestBulkAPIOperations:
    """Test Bulk API 2.0 operations."""

    @pytest.mark.asyncio
    async def test_create_bulk_job(self):
        """Test creating a bulk job."""
        config = SalesforceCreateBulkJobConfig(
            bulk_operation="insert", sobject_type="Account"
        )
        node = create_node(config)

        mock_data = {
            "id": "750xx001",
            "operation": "insert",
            "object": "Account",
            "state": "Open",
        }

        mock_client = create_mock_client(mock_api_response(mock_data, 201))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_bulk_data_job"

    @pytest.mark.asyncio
    async def test_upload_bulk_data(self):
        """Test uploading bulk data."""
        config = SalesforceUploadBulkDataConfig(
            job_id="750xx001", csv_data="Name\nAccount 1\nAccount 2"
        )
        node = create_node(config)

        mock_client = create_mock_client(mock_api_response({}, 201))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upload_csv_to_bulk_job"

    @pytest.mark.asyncio
    async def test_close_bulk_job(self):
        """Test closing a bulk job."""
        config = SalesforceCloseBulkJobConfig(job_id="750xx001")
        node = create_node(config)

        mock_data = {"id": "750xx001", "state": "UploadComplete"}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "close_bulk_data_job"

    @pytest.mark.asyncio
    async def test_get_bulk_job_status(self):
        """Test getting bulk job status."""
        config = SalesforceGetBulkJobStatusConfig(job_id="750xx001")
        node = create_node(config)

        mock_data = {
            "id": "750xx001",
            "state": "JobComplete",
            "numberRecordsProcessed": 100,
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_bulk_job_status"

    @pytest.mark.asyncio
    async def test_get_bulk_job_results(self):
        """Test getting bulk job results."""
        config = SalesforceGetBulkJobResultsConfig(
            job_id="750xx001", result_type="successful"
        )
        node = create_node(config)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "sf__Id,sf__Created\n001xx001,true\n001xx002,true"
        mock_response.json.return_value = {}
        mock_response.headers = {"Content-Type": "text/csv"}
        mock_response.content = b"sf__Id,sf__Created\n001xx001,true\n001xx002,true"

        mock_client = create_mock_client(mock_response)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_bulk_job_results"
        assert "csv_data" in result["data"]

    @pytest.mark.asyncio
    async def test_abort_bulk_job(self):
        """Test aborting a bulk job."""
        config = SalesforceAbortBulkJobConfig(job_id="750xx001")
        node = create_node(config)

        mock_data = {"id": "750xx001", "state": "Aborted"}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "abort_bulk_data_job"

    @pytest.mark.asyncio
    async def test_list_bulk_jobs(self):
        """Test listing bulk jobs."""
        config = SalesforceListBulkJobsConfig()
        node = create_node(config)

        mock_data = {"done": True, "records": [{"id": "750xx001"}]}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_bulk_data_jobs"


# ============================================================================
# Reports Operations Tests (3)
# ============================================================================


class TestReportsOperations:
    """Test reports operations."""

    @pytest.mark.asyncio
    async def test_list_reports(self):
        """Test listing reports."""
        config = SalesforceListReportsConfig()
        node = create_node(config)

        mock_data = {
            "totalSize": 1,
            "records": [{"Id": "00Oxx001", "Name": "Test Report"}],
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_available_reports"

    @pytest.mark.asyncio
    async def test_run_report(self):
        """Test running a report."""
        config = SalesforceRunReportConfig(report_id="00Oxx001", include_details=True)
        node = create_node(config)

        mock_data = {
            "factMap": {"T!T": {"aggregates": [], "rows": []}},
            "reportMetadata": {"name": "Test Report"},
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_report_and_get_results"

    @pytest.mark.asyncio
    async def test_get_report_metadata(self):
        """Test getting report metadata."""
        config = SalesforceGetReportMetadataConfig(report_id="00Oxx001")
        node = create_node(config)

        mock_data = {
            "reportMetadata": {"name": "Test Report", "reportType": {"type": "Account"}}
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_report_metadata"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_api_error(self):
        """Test handling API errors."""
        config = SalesforceGetRecordConfig(
            sobject_type="Account", record_id="invalid-id"
        )
        node = create_node(config)

        error_data = [{"errorCode": "NOT_FOUND", "message": "Record not found"}]

        mock_client = create_mock_client(mock_api_response(error_data, 404))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test error when credentials are missing."""
        config = SalesforceGetRecordConfig(sobject_type="Account", record_id="001xx001")
        node_config = SalesforceNodeConfig(config=config, credentials=None)
        node = SalesforceNode(
            node_id="test-node",
            node_type="automation-salesforce",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Timing Information Tests
# ============================================================================


class TestTimingInfo:
    """Test timing information in responses."""

    @pytest.mark.asyncio
    async def test_timing_info_included(self):
        """Test that timing info is included in responses."""
        config = SalesforceGetLimitsConfig()
        node = create_node(config)

        mock_data = {"DailyApiRequests": {"Max": 100000}}

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["total"] > 0


# ============================================================================
# Deleted/Updated Records Operations Tests (3)
# ============================================================================


class TestDeletedUpdatedRecordsOperations:
    """Test deleted and updated records operations."""

    @pytest.mark.asyncio
    async def test_get_deleted(self):
        """Test getting deleted records in a time range."""
        config = SalesforceGetDeletedConfig(
            sobject_type="Account",
            start="2024-01-01T00:00:00Z",
            end="2024-01-31T23:59:59Z",
        )
        node = create_node(config)

        mock_data = {
            "deletedRecords": [
                {"id": "001xx001", "deletedDate": "2024-01-15T10:30:00Z"},
                {"id": "001xx002", "deletedDate": "2024-01-20T14:45:00Z"},
            ],
            "earliestDateAvailable": "2024-01-01T00:00:00Z",
            "latestDateCovered": "2024-01-31T23:59:59Z",
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_deleted_records_in_range"
        assert "deletedRecords" in result["data"]

    @pytest.mark.asyncio
    async def test_get_updated(self):
        """Test getting updated records in a time range."""
        config = SalesforceGetUpdatedConfig(
            sobject_type="Account",
            start="2024-01-01T00:00:00Z",
            end="2024-01-31T23:59:59Z",
        )
        node = create_node(config)

        mock_data = {
            "ids": ["001xx001", "001xx002", "001xx003"],
            "latestDateCovered": "2024-01-31T23:59:59Z",
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_updated_records_in_range"
        assert "ids" in result["data"]

    @pytest.mark.asyncio
    async def test_query_all(self):
        """Test SOQL query including deleted records."""
        config = SalesforceQueryAllConfig(
            query="SELECT Id, Name, IsDeleted FROM Account WHERE IsDeleted = true"
        )
        node = create_node(config)

        mock_data = {
            "totalSize": 2,
            "done": True,
            "records": [
                {"Id": "001xx001", "Name": "Deleted Account 1", "IsDeleted": True},
                {"Id": "001xx002", "Name": "Deleted Account 2", "IsDeleted": True},
            ],
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_soql_query_including_deleted"
        assert result["data"]["totalSize"] == 2


# ============================================================================
# List Views Operations Tests (3)
# ============================================================================


class TestListViewsOperations:
    """Test list views operations."""

    @pytest.mark.asyncio
    async def test_list_listviews(self):
        """Test listing list views for an object."""
        config = SalesforceListListViewsConfig(sobject_type="Account")
        node = create_node(config)

        mock_data = {
            "done": True,
            "listviews": [
                {
                    "id": "00Bxx001",
                    "developerName": "AllAccounts",
                    "label": "All Accounts",
                },
                {
                    "id": "00Bxx002",
                    "developerName": "MyAccounts",
                    "label": "My Accounts",
                },
            ],
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_object_list_views"

    @pytest.mark.asyncio
    async def test_get_listview(self):
        """Test getting a specific list view."""
        config = SalesforceGetListViewConfig(
            sobject_type="Account", listview_id="00Bxx001"
        )
        node = create_node(config)

        mock_data = {
            "id": "00Bxx001",
            "developerName": "AllAccounts",
            "label": "All Accounts",
            "soqlCompatible": True,
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_list_view_details"

    @pytest.mark.asyncio
    async def test_execute_listview(self):
        """Test executing a list view."""
        config = SalesforceExecuteListViewConfig(
            sobject_type="Account", listview_id="00Bxx001", limit=10
        )
        node = create_node(config)

        mock_data = {
            "columns": [{"fieldApiName": "Name"}, {"fieldApiName": "Industry"}],
            "records": [
                {"columns": [{"value": "Acme Corp"}, {"value": "Technology"}]},
            ],
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_list_view_query"


# ============================================================================
# Dashboard Operations Tests (3)
# ============================================================================


class TestDashboardOperations:
    """Test dashboard operations."""

    @pytest.mark.asyncio
    async def test_list_dashboards(self):
        """Test listing dashboards."""
        config = SalesforceListDashboardsConfig()
        node = create_node(config)

        mock_data = {
            "dashboards": [
                {"id": "01Zxx001", "name": "Sales Dashboard"},
                {"id": "01Zxx002", "name": "Marketing Dashboard"},
            ]
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_available_dashboards"

    @pytest.mark.asyncio
    async def test_get_dashboard(self):
        """Test getting a dashboard."""
        config = SalesforceGetDashboardConfig(dashboard_id="01Zxx001")
        node = create_node(config)

        mock_data = {
            "id": "01Zxx001",
            "name": "Sales Dashboard",
            "components": [{"id": "cmp001", "type": "Chart"}],
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_dashboard_data"

    @pytest.mark.asyncio
    async def test_refresh_dashboard(self):
        """Test refreshing a dashboard."""
        config = SalesforceRefreshDashboardConfig(dashboard_id="01Zxx001")
        node = create_node(config)

        mock_data = {
            "id": "01Zxx001",
            "name": "Sales Dashboard",
            "refreshDate": "2024-01-15T10:30:00Z",
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "refresh_dashboard_data"


# ============================================================================
# Invocable Actions Operations Tests (3)
# ============================================================================


class TestInvocableActionsOperations:
    """Test invocable actions operations."""

    @pytest.mark.asyncio
    async def test_list_invocable_actions(self):
        """Test listing invocable actions."""
        config = SalesforceListInvocableActionsConfig(action_type="standard")
        node = create_node(config)

        mock_data = {
            "actions": [
                {"name": "chatterPost", "label": "Post to Chatter"},
                {"name": "emailSimple", "label": "Send Email"},
            ]
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_invocable_actions"

    @pytest.mark.asyncio
    async def test_get_invocable_action(self):
        """Test getting invocable action details."""
        config = SalesforceGetInvocableActionConfig(
            action_type="standard", action_name="chatterPost"
        )
        node = create_node(config)

        mock_data = {
            "name": "chatterPost",
            "label": "Post to Chatter",
            "inputs": [{"name": "text", "type": "String", "required": True}],
            "outputs": [{"name": "feedItemId", "type": "String"}],
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_invocable_action_details"

    @pytest.mark.asyncio
    async def test_execute_invocable_action(self):
        """Test executing an invocable action."""
        config = SalesforceExecuteInvocableActionConfig(
            action_type="standard",
            action_name="chatterPost",
            inputs=[{"text": "Hello from API!", "subjectId": "005xx001"}],
        )
        node = create_node(config)

        mock_data = [{"isSuccess": True, "outputValues": {"feedItemId": "0D5xx001"}}]

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_invocable_action"


# ============================================================================
# Chatter Operations Tests (2)
# ============================================================================


class TestChatterOperations:
    """Test Chatter operations."""

    @pytest.mark.asyncio
    async def test_post_to_chatter(self):
        """Test posting to Chatter feed."""
        config = SalesforcePostToChatterConfig(
            text="Hello from API!", subject_id="001xx001"
        )
        node = create_node(config)

        mock_data = {
            "id": "0D5xx001",
            "body": {"text": "Hello from API!"},
            "type": "TextPost",
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "post_message_to_chatter_feed"

    @pytest.mark.asyncio
    async def test_get_chatter_feed(self):
        """Test getting Chatter feed."""
        config = SalesforceGetChatterFeedConfig(feed_type="news", page_size=10)
        node = create_node(config)

        mock_data = {
            "elements": [
                {"id": "0D5xx001", "body": {"text": "Post 1"}},
                {"id": "0D5xx002", "body": {"text": "Post 2"}},
            ],
            "nextPageUrl": None,
        }

        mock_client = create_mock_client(mock_api_response(mock_data))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_chatter_feed_items"

    @pytest.mark.asyncio
    async def test_get_chatter_feed_record_without_subject_id(self):
        """Test that record feed type requires subject_id."""
        config = SalesforceGetChatterFeedConfig(feed_type="record", subject_id=None)
        node = create_node(config)

        # No mock needed - should fail validation before API call
        result = await node.execute({})

        assert result["status"] == "error"
        assert "subject_id is required" in result["error"]
