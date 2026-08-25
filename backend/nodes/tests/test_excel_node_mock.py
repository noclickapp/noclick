"""Mock tests for Excel node.

These tests use mocked Microsoft Graph API responses to test functionality without requiring
actual Microsoft OAuth credentials or making real API calls.

Tests cover all 43 operations across:
- Session operations (3): create_session, close_session, refresh_session
- Calculation operations (2): calculate, execute_function
- Worksheet operations (5): list_worksheets, get_worksheet, add_worksheet, update_worksheet, delete_worksheet
- Range operations (10): get_used_range, get_range, update_range, clear_range, insert_range, delete_range, merge_range, unmerge_range, sort_range, format_range
- Table operations (12): list_tables, get_table, add_table, delete_table, convert_table_to_range, list_table_rows, add_table_row, delete_table_row, list_table_columns, add_table_column, delete_table_column, sort_table
- Filter operations (2): apply_filter, clear_filter
- Chart operations (6): list_charts, get_chart, add_chart, update_chart, delete_chart, get_chart_image
- Named Item operations (3): list_named_items, get_named_item, add_named_item
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def create_node_mock(config):
    """Create an ExcelNode instance with mock credentials for testing."""
    from nodes.excel_node import ExcelNode, ExcelNodeConfig, ExcelOAuthCredential

    mock_credentials = ExcelOAuthCredential(
        access_token="mock_access_token_12345",
        refresh_token="mock_refresh_token_67890",
        expires_at="2099-12-31T23:59:59Z",
        scope="Files.ReadWrite.All User.Read",
        email="test@example.com",
    )

    node_config = ExcelNodeConfig(config=config, credentials=mock_credentials)
    node = ExcelNode(
        node_id="test-excel-node",
        node_type="automation-excel",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Session Operations Tests
# ============================================================================


class TestExcelSessionOperations:
    """Test Excel session management operations with mocks."""

    @pytest.mark.asyncio
    async def test_create_session_mocked(self):
        """Test creating a workbook session with mock response."""
        from nodes.excel_node import ExcelCreateSessionConfig

        mock_response_data = {"id": "session_abc123", "persistChanges": True}

        config = ExcelCreateSessionConfig(
            operation="create_workbook_session",
            workbook_id="01ABCDEF1234567890",
            persist_changes="true",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 201

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert "session_id" in result["data"]

    @pytest.mark.asyncio
    async def test_close_session_mocked(self):
        """Test closing a workbook session with mock response."""
        from nodes.excel_node import ExcelCloseSessionConfig

        config = ExcelCloseSessionConfig(
            operation="close_workbook_session",
            workbook_id="01ABCDEF1234567890",
            session_id="session_abc123",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_refresh_session_mocked(self):
        """Test refreshing a workbook session with mock response."""
        from nodes.excel_node import ExcelRefreshSessionConfig

        mock_response_data = {"@odata.context": "refreshed"}

        config = ExcelRefreshSessionConfig(
            operation="refresh_workbook_session",
            workbook_id="01ABCDEF1234567890",
            session_id="session_abc123",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"


# ============================================================================
# Calculation Operations Tests
# ============================================================================


class TestExcelCalculationOperations:
    """Test Excel calculation operations with mocks."""

    @pytest.mark.asyncio
    async def test_calculate_mocked(self):
        """Test workbook calculation with mock response."""
        from nodes.excel_node import ExcelCalculateConfig

        config = ExcelCalculateConfig(
            operation="recalculate_workbook",
            workbook_id="01ABCDEF1234567890",
            calculation_type="Recalculate",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_execute_function_mocked(self):
        """Test executing a function with mock response."""
        from nodes.excel_node import ExcelExecuteFunctionConfig

        mock_response_data = {"value": 42.5}

        config = ExcelExecuteFunctionConfig(
            operation="execute_excel_function",
            workbook_id="01ABCDEF1234567890",
            function_name="AVERAGE",
            parameters=json.dumps([[10, 20, 30, 100]]),
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["result"] == 42.5


# ============================================================================
# Worksheet Operations Tests
# ============================================================================


class TestExcelWorksheetOperations:
    """Test Worksheet API operations with mocks."""

    @pytest.mark.asyncio
    async def test_list_worksheets_mocked(self):
        """Test listing worksheets in a workbook with mock response."""
        from nodes.excel_node import ExcelListWorksheetsConfig

        mock_response_data = {
            "value": [
                {
                    "id": "sheet1",
                    "name": "Summary",
                    "position": 0,
                    "visibility": "Visible",
                },
                {
                    "id": "sheet2",
                    "name": "Details",
                    "position": 1,
                    "visibility": "Visible",
                },
                {
                    "id": "sheet3",
                    "name": "Archive",
                    "position": 2,
                    "visibility": "Hidden",
                },
            ]
        }

        config = ExcelListWorksheetsConfig(
            operation="list_workbook_worksheets", workbook_id="01ABCDEF1234567890"
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert len(result["data"]["worksheets"]) == 3
            assert result["data"]["worksheets"][0]["name"] == "Summary"

    @pytest.mark.asyncio
    async def test_get_worksheet_mocked(self):
        """Test getting worksheet metadata with mock response."""
        from nodes.excel_node import ExcelGetWorksheetConfig

        mock_response_data = {
            "id": "sheet1",
            "name": "Summary",
            "position": 0,
            "visibility": "Visible",
        }

        config = ExcelGetWorksheetConfig(
            operation="get_worksheet",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Summary",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "Summary"

    @pytest.mark.asyncio
    async def test_add_worksheet_mocked(self):
        """Test adding a new worksheet with mock response."""
        from nodes.excel_node import ExcelAddWorksheetConfig

        mock_response_data = {
            "id": "new_sheet_123",
            "name": "Q2 Report",
            "position": 3,
            "visibility": "Visible",
        }

        config = ExcelAddWorksheetConfig(
            operation="add_worksheet",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Q2 Report",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 201

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "Q2 Report"

    @pytest.mark.asyncio
    async def test_update_worksheet_mocked(self):
        """Test updating worksheet properties with mock response."""
        from nodes.excel_node import ExcelUpdateWorksheetConfig

        mock_response_data = {
            "id": "sheet1",
            "name": "Updated Name",
            "position": 0,
            "visibility": "Visible",
        }

        config = ExcelUpdateWorksheetConfig(
            operation="update_worksheet",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="OldName",
            new_name="Updated Name",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_worksheet_mocked(self):
        """Test deleting a worksheet with mock response."""
        from nodes.excel_node import ExcelDeleteWorksheetConfig

        config = ExcelDeleteWorksheetConfig(
            operation="delete_worksheet",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="OldData",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"


# ============================================================================
# Range Operations Tests
# ============================================================================


class TestExcelRangeOperations:
    """Test Range API operations with mocks."""

    @pytest.mark.asyncio
    async def test_get_used_range_mocked(self):
        """Test getting used range with mock response."""
        from nodes.excel_node import ExcelGetUsedRangeConfig

        mock_response_data = {
            "address": "Sheet1!A1:D10",
            "values": [["Header1", "Header2", "Header3", "Header4"]],
        }

        config = ExcelGetUsedRangeConfig(
            operation="get_worksheet_used_range",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["address"] == "Sheet1!A1:D10"

    @pytest.mark.asyncio
    async def test_get_range_mocked(self):
        """Test getting range data with mock response."""
        from nodes.excel_node import ExcelGetRangeConfig

        mock_response_data = {
            "address": "Sheet1!A1:C3",
            "values": [
                ["Header1", "Header2", "Header3"],
                [100, 200, 300],
                [150, 250, 350],
            ],
            "formulas": [
                ["Header1", "Header2", "Header3"],
                ["100", "200", "=A2+B2"],
                ["150", "250", "=A3+B3"],
            ],
        }

        config = ExcelGetRangeConfig(
            operation="get_range_values",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:C3",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["address"] == "Sheet1!A1:C3"
            assert len(result["data"]["values"]) == 3

    @pytest.mark.asyncio
    async def test_update_range_mocked(self):
        """Test updating range data with mock response."""
        from nodes.excel_node import ExcelUpdateRangeConfig

        mock_response_data = {
            "address": "Sheet1!A1:B2",
            "values": [["Product", "Price"], ["Laptop", 999]],
        }

        config = ExcelUpdateRangeConfig(
            operation="update_range_values",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:B2",
            values=json.dumps([["Product", "Price"], ["Laptop", 999]]),
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["address"] == "Sheet1!A1:B2"

    @pytest.mark.asyncio
    async def test_clear_range_mocked(self):
        """Test clearing range with mock response."""
        from nodes.excel_node import ExcelClearRangeConfig

        config = ExcelClearRangeConfig(
            operation="clear_range_contents",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:Z100",
            apply_to="All",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_insert_range_mocked(self):
        """Test inserting range with mock response."""
        from nodes.excel_node import ExcelInsertRangeConfig

        mock_response_data = {"address": "Sheet1!A1:A5"}

        config = ExcelInsertRangeConfig(
            operation="insert_blank_cells_in_range",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:A5",
            shift="Down",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_range_mocked(self):
        """Test deleting range with mock response."""
        from nodes.excel_node import ExcelDeleteRangeConfig

        config = ExcelDeleteRangeConfig(
            operation="delete_range_and_shift_cells",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:A5",
            shift="Up",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_merge_range_mocked(self):
        """Test merging cells with mock response."""
        from nodes.excel_node import ExcelMergeRangeConfig

        config = ExcelMergeRangeConfig(
            operation="merge_range_cells",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:D1",
            across="false",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unmerge_range_mocked(self):
        """Test unmerging cells with mock response."""
        from nodes.excel_node import ExcelUnmergeRangeConfig

        config = ExcelUnmergeRangeConfig(
            operation="unmerge_range_cells",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:D1",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_sort_range_mocked(self):
        """Test sorting range with mock response."""
        from nodes.excel_node import ExcelSortRangeConfig

        config = ExcelSortRangeConfig(
            operation="sort_range_by_column",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:D10",
            fields=json.dumps([{"key": 0, "ascending": True}]),
            has_headers="true",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_format_range_mocked(self):
        """Test formatting range with mock response."""
        from nodes.excel_node import ExcelFormatRangeConfig

        config = ExcelFormatRangeConfig(
            operation="format_range",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:A10",
            font_bold=True,
            background_color="#FFFF00",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"


# ============================================================================
# Table Operations Tests
# ============================================================================


class TestExcelTableOperations:
    """Test Table API operations with mocks."""

    @pytest.mark.asyncio
    async def test_list_tables_mocked(self):
        """Test listing tables in a worksheet with mock response."""
        from nodes.excel_node import ExcelListTablesConfig

        mock_response_data = {
            "value": [
                {"id": "table1", "name": "SalesData", "showHeaders": True},
                {"id": "table2", "name": "Inventory", "showHeaders": True},
            ]
        }

        config = ExcelListTablesConfig(
            operation="list_workbook_tables",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert len(result["data"]["tables"]) == 2
            assert result["data"]["tables"][0]["name"] == "SalesData"

    @pytest.mark.asyncio
    async def test_get_table_mocked(self):
        """Test getting table details with mock response."""
        from nodes.excel_node import ExcelGetTableConfig

        mock_response_data = {
            "id": "table1",
            "name": "SalesData",
            "showHeaders": True,
            "style": "TableStyleMedium2",
        }

        config = ExcelGetTableConfig(
            operation="get_table",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "SalesData"

    @pytest.mark.asyncio
    async def test_add_table_mocked(self):
        """Test adding a table with mock response."""
        from nodes.excel_node import ExcelAddTableConfig

        mock_response_data = {
            "id": "new_table_123",
            "name": "ProductCatalog",
            "showHeaders": True,
        }

        config = ExcelAddTableConfig(
            operation="create_table_from_range",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            range_address="A1:D10",
            has_headers="true",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 201

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "ProductCatalog"

    @pytest.mark.asyncio
    async def test_delete_table_mocked(self):
        """Test deleting a table with mock response."""
        from nodes.excel_node import ExcelDeleteTableConfig

        config = ExcelDeleteTableConfig(
            operation="delete_table",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="OldTable",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_convert_table_to_range_mocked(self):
        """Test converting table to range with mock response."""
        from nodes.excel_node import ExcelConvertTableToRangeConfig

        mock_response_data = {"address": "Sheet1!A1:D10"}

        config = ExcelConvertTableToRangeConfig(
            operation="convert_table_to_range",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_table_rows_mocked(self):
        """Test listing table rows with mock response."""
        from nodes.excel_node import ExcelListTableRowsConfig

        mock_response_data = {
            "value": [
                {"index": 0, "values": [["Product A", 100, 9.99]]},
                {"index": 1, "values": [["Product B", 200, 19.99]]},
            ]
        }

        config = ExcelListTableRowsConfig(
            operation="list_table_rows",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert len(result["data"]["rows"]) == 2

    @pytest.mark.asyncio
    async def test_add_table_row_mocked(self):
        """Test adding a row to a table with mock response."""
        from nodes.excel_node import ExcelAddTableRowConfig

        mock_response_data = {
            "index": 5,
            "values": [["Widget", "Electronics", 299.99, 150]],
        }

        config = ExcelAddTableRowConfig(
            operation="add_table_row",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
            values=json.dumps([["Widget", "Electronics", 299.99, 150]]),
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 201

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["index"] == 5

    @pytest.mark.asyncio
    async def test_delete_table_row_mocked(self):
        """Test deleting a table row with mock response."""
        from nodes.excel_node import ExcelDeleteTableRowConfig

        config = ExcelDeleteTableRowConfig(
            operation="delete_table_row",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
            index=5,
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_table_columns_mocked(self):
        """Test listing table columns with mock response."""
        from nodes.excel_node import ExcelListTableColumnsConfig

        mock_response_data = {
            "value": [
                {"id": "col1", "name": "Product", "index": 0},
                {"id": "col2", "name": "Price", "index": 1},
            ]
        }

        config = ExcelListTableColumnsConfig(
            operation="list_table_columns",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert len(result["data"]["columns"]) == 2

    @pytest.mark.asyncio
    async def test_add_table_column_mocked(self):
        """Test adding a column to a table with mock response."""
        from nodes.excel_node import ExcelAddTableColumnConfig

        mock_response_data = {"id": "col_new", "name": "NewColumn", "index": 3}

        config = ExcelAddTableColumnConfig(
            operation="add_table_column",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
            index=3,
            column_name="NewColumn",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 201

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "NewColumn"

    @pytest.mark.asyncio
    async def test_delete_table_column_mocked(self):
        """Test deleting a table column with mock response."""
        from nodes.excel_node import ExcelDeleteTableColumnConfig

        config = ExcelDeleteTableColumnConfig(
            operation="delete_table_column",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
            column_name="OldColumn",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_sort_table_mocked(self):
        """Test sorting a table with mock response."""
        from nodes.excel_node import ExcelSortTableConfig

        config = ExcelSortTableConfig(
            operation="sort_table_by_column",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
            column_name="Region",
            ascending=True,
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"


# ============================================================================
# Filter Operations Tests
# ============================================================================


class TestExcelFilterOperations:
    """Test filter operations with mocks."""

    @pytest.mark.asyncio
    async def test_apply_filter_mocked(self):
        """Test applying filter with mock response."""
        from nodes.excel_node import ExcelApplyFilterConfig

        config = ExcelApplyFilterConfig(
            operation="apply_table_column_filter",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
            column_name="Region",
            filter_values=json.dumps(["North", "East"]),
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_clear_filter_mocked(self):
        """Test clearing filter with mock response."""
        from nodes.excel_node import ExcelClearFilterConfig

        config = ExcelClearFilterConfig(
            operation="clear_table_column_filter",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            table_name="SalesData",
            column_name="Region",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"


# ============================================================================
# Chart Operations Tests
# ============================================================================


class TestExcelChartOperations:
    """Test Chart API operations with mocks."""

    @pytest.mark.asyncio
    async def test_list_charts_mocked(self):
        """Test listing charts with mock response."""
        from nodes.excel_node import ExcelListChartsConfig

        mock_response_data = {
            "value": [
                {"id": "chart1", "name": "Sales Trend", "chartType": "Line"},
                {"id": "chart2", "name": "Revenue Breakdown", "chartType": "Pie"},
            ]
        }

        config = ExcelListChartsConfig(
            operation="list_worksheet_charts",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Dashboard",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert len(result["data"]["charts"]) == 2
            assert result["data"]["charts"][0]["name"] == "Sales Trend"

    @pytest.mark.asyncio
    async def test_get_chart_mocked(self):
        """Test getting chart details with mock response."""
        from nodes.excel_node import ExcelGetChartConfig

        mock_response_data = {
            "id": "chart1",
            "name": "Sales Trend",
            "chartType": "Line",
            "height": 300,
            "width": 500,
        }

        config = ExcelGetChartConfig(
            operation="get_chart",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Dashboard",
            chart_name="Sales Trend",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "Sales Trend"

    @pytest.mark.asyncio
    async def test_add_chart_mocked(self):
        """Test adding a chart with mock response."""
        from nodes.excel_node import ExcelAddChartConfig

        mock_response_data = {
            "id": "new_chart_123",
            "name": "Chart 1",
            "chartType": "ColumnClustered",
        }

        config = ExcelAddChartConfig(
            operation="create_chart",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            chart_type="ColumnClustered",
            source_data_range="A1:B12",
            series_by="Auto",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 201

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["type"] == "ColumnClustered"

    @pytest.mark.asyncio
    async def test_update_chart_mocked(self):
        """Test updating a chart with mock response."""
        from nodes.excel_node import ExcelUpdateChartConfig

        mock_response_data = {
            "id": "chart1",
            "name": "Updated Chart",
            "chartType": "ColumnClustered",
        }

        config = ExcelUpdateChartConfig(
            operation="update_chart",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            chart_name="Chart 1",
            new_name="Updated Chart",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "Updated Chart"

    @pytest.mark.asyncio
    async def test_delete_chart_mocked(self):
        """Test deleting a chart with mock response."""
        from nodes.excel_node import ExcelDeleteChartConfig

        config = ExcelDeleteChartConfig(
            operation="delete_chart",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Sheet1",
            chart_name="Old Chart",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.delete = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_chart_image_mocked(self):
        """Test getting chart image with mock response."""
        from nodes.excel_node import ExcelGetChartImageConfig

        mock_response_data = b"fake_image_bytes_here"

        config = ExcelGetChartImageConfig(
            operation="get_chart_image",
            workbook_id="01ABCDEF1234567890",
            worksheet_name="Dashboard",
            chart_name="Sales Trend",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.content = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert "image_base64" in result["data"] or "image" in result["data"]


# ============================================================================
# Named Item Operations Tests
# ============================================================================


class TestExcelNamedItemOperations:
    """Test Named Item API operations with mocks."""

    @pytest.mark.asyncio
    async def test_list_named_items_mocked(self):
        """Test listing named items with mock response."""
        from nodes.excel_node import ExcelListNamedItemsConfig

        mock_response_data = {
            "value": [
                {"name": "TaxRate", "type": "Range", "value": "0.08"},
                {"name": "CompanyName", "type": "String", "value": "Acme Corp"},
            ]
        }

        config = ExcelListNamedItemsConfig(
            operation="list_named_items", workbook_id="01ABCDEF1234567890"
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert len(result["data"]["named_items"]) == 2
            assert result["data"]["named_items"][0]["name"] == "TaxRate"

    @pytest.mark.asyncio
    async def test_get_named_item_mocked(self):
        """Test getting a named item with mock response."""
        from nodes.excel_node import ExcelGetNamedItemConfig

        mock_response_data = {
            "name": "TaxRate",
            "type": "Range",
            "value": "0.08",
            "visible": True,
        }

        config = ExcelGetNamedItemConfig(
            operation="get_named_item", workbook_id="01ABCDEF1234567890", name="TaxRate"
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "TaxRate"

    @pytest.mark.asyncio
    async def test_add_named_item_mocked(self):
        """Test adding a named item with mock response."""
        from nodes.excel_node import ExcelAddNamedItemConfig

        mock_response_data = {"name": "DiscountRate", "type": "Range", "value": "0.15"}

        config = ExcelAddNamedItemConfig(
            operation="create_named_item",
            workbook_id="01ABCDEF1234567890",
            name="DiscountRate",
            reference="Sheet1!$A$1",
            comment="Standard discount rate",
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 201

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["data"]["name"] == "DiscountRate"


# ============================================================================
# Dynamic Field Loading Tests
# ============================================================================


class TestExcelDynamicFieldLoading:
    """Test dynamic field loading for dropdowns."""

    @pytest.mark.asyncio
    async def test_load_workbooks_mocked(self):
        """Test loading workbook list with mock response."""
        from nodes.excel_node import ExcelNode

        mock_response_data = {
            "value": [
                {
                    "id": "wb1",
                    "name": "Sales Report.xlsx",
                    "lastModifiedDateTime": "2025-01-20T10:00:00Z",
                    "createdBy": {"user": {"displayName": "Alice"}},
                },
                {
                    "id": "wb2",
                    "name": "Budget 2025.xlsx",
                    "lastModifiedDateTime": "2025-01-15T14:30:00Z",
                    "createdBy": {"user": {"displayName": "Bob"}},
                },
            ]
        }

        credential_data = {
            "access_token": "mock_token",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await ExcelNode.load_field_options(
                field_name="workbook_id", credential_data=credential_data
            )

            assert len(result["options"]) == 2
            assert result["options"][0]["value"] == "wb1"
            assert result["options"][0]["label"] == "Sales Report.xlsx"

    @pytest.mark.asyncio
    async def test_load_worksheets_mocked(self):
        """Test loading worksheet list with mock response."""
        from nodes.excel_node import ExcelNode

        mock_response_data = {
            "value": [
                {"id": "sheet1", "name": "Summary", "position": 0},
                {"id": "sheet2", "name": "Details", "position": 1},
            ]
        }

        credential_data = {
            "access_token": "mock_token",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        context = {"workbook_id": "wb1"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await ExcelNode.load_field_options(
                field_name="worksheet_name",
                credential_data=credential_data,
                context=context,
            )

            assert len(result["options"]) == 2
            assert result["options"][0]["value"] == "Summary"
            assert result["options"][0]["label"] == "Summary"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestExcelErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test error when credentials are missing."""
        from nodes.excel_node import (
            ExcelNode,
            ExcelNodeConfig,
            ExcelListWorksheetsConfig,
        )

        config = ExcelListWorksheetsConfig(
            operation="list_workbook_worksheets", workbook_id="test-id"
        )

        node_config = ExcelNodeConfig(config=config, credentials=None)
        node = ExcelNode(
            node_id="test-node",
            node_type="automation-excel",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Excel credentials required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_error_404(self):
        """Test handling of 404 not found errors."""
        from nodes.excel_node import ExcelListWorksheetsConfig
        import httpx

        config = ExcelListWorksheetsConfig(
            operation="list_workbook_worksheets", workbook_id="NONEXISTENT_ID"
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Workbook not found"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=mock_response
            )

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "error"
            assert result["status_code"] == 404
            assert "Workbook not found" in result["message"]

    @pytest.mark.asyncio
    async def test_api_error_401(self):
        """Test handling of 401 unauthorized errors."""
        from nodes.excel_node import ExcelListWorksheetsConfig
        import httpx

        config = ExcelListWorksheetsConfig(
            operation="list_workbook_worksheets", workbook_id="test-id"
        )
        node = create_node_mock(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = "Invalid authentication token"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=mock_response
            )

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "error"
            assert result["status_code"] == 401
            assert "Invalid authentication token" in result["message"]
