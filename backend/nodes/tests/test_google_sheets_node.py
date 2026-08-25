"""
Unit tests for Google Sheets node.

Tests the Google Sheets node functionality with mocked API responses.
All 19 operations are tested: read, write, append, clear, create, get_metadata,
batch_get, batch_update, add_sheet, delete_sheet, copy_sheet, rename_sheet,
duplicate_sheet, find_replace, insert_rows, delete_rows, batch_clear,
insert_columns, delete_columns.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from nodes.google_sheets_node import (
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsOAuthCredential,
    # Basic operations
    GoogleSheetsReadConfig,
    GoogleSheetsWriteConfig,
    GoogleSheetsAppendConfig,
    GoogleSheetsClearConfig,
    GoogleSheetsCreateConfig,
    GoogleSheetsGetMetadataConfig,
    # Batch operations
    GoogleSheetsBatchGetConfig,
    GoogleSheetsBatchUpdateConfig,
    GoogleSheetsBatchClearConfig,
    # Sheet management
    GoogleSheetsAddSheetConfig,
    GoogleSheetsDeleteSheetConfig,
    GoogleSheetsCopySheetConfig,
    GoogleSheetsRenameSheetConfig,
    GoogleSheetsDuplicateSheetConfig,
    # Data manipulation
    GoogleSheetsFindReplaceConfig,
    GoogleSheetsInsertRowsConfig,
    GoogleSheetsDeleteRowsConfig,
    GoogleSheetsInsertColumnsConfig,
    GoogleSheetsDeleteColumnsConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials."""
    return GoogleSheetsOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create_response(status_code: int, json_data: dict):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_data
        response.text = json.dumps(json_data)
        response.content = json.dumps(json_data).encode()
        return response

    return _create_response


def create_node(config, credentials) -> GoogleSheetsNode:
    """Create a GoogleSheetsNode instance with the given config."""
    node_config = GoogleSheetsNodeConfig(config=config, credentials=credentials)
    return GoogleSheetsNode(
        node_id="test-node",
        node_type="automation-google-sheets",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


# ============================================================================
# Read Operation Tests
# ============================================================================


class TestReadOperation:
    """Test Google Sheets read operation."""

    @pytest.mark.asyncio
    async def test_read_success(self, mock_credentials, mock_httpx_response):
        """Test reading data from a sheet."""
        config = GoogleSheetsReadConfig(
            spreadsheet_id="spreadsheet123", sheet_name="Sheet1", range="A1:D10"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "values": [
                    ["Name", "Age", "City"],
                    ["Alice", "30", "NYC"],
                    ["Bob", "25", "LA"],
                ],
                "range": "Sheet1!A1:D10",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "read_sheet_data"
            assert len(result["values"]) == 3

    @pytest.mark.asyncio
    async def test_read_empty_sheet(self, mock_credentials, mock_httpx_response):
        """Test reading from an empty sheet."""
        config = GoogleSheetsReadConfig(
            spreadsheet_id="spreadsheet123",
            range="Sheet1!A1:Z100",  # Specify range to avoid metadata call
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["values"] == []

    @pytest.mark.asyncio
    async def test_read_with_sheet_name_only(
        self, mock_credentials, mock_httpx_response
    ):
        """Test reading entire sheet when only sheet_name is provided."""
        config = GoogleSheetsReadConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet2",
            range=None,  # No range - should read entire Sheet2
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {"values": [["Data", "From"], ["Sheet", "Two"]], "range": "Sheet2!A1:B2"},
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            result = await node.execute({})

            # Verify the URL contains Sheet2, not Sheet1
            call_args = mock_get.call_args
            called_url = call_args[0][0]
            assert "Sheet2" in called_url
            assert result["status"] == "success"
            assert result["range"] == "Sheet2"

    @pytest.mark.asyncio
    async def test_read_with_sheet_name_and_range(
        self, mock_credentials, mock_httpx_response
    ):
        """Test reading specific range from specific sheet."""
        config = GoogleSheetsReadConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet3",
            range="C5:E10",  # Should construct "Sheet3!C5:E10"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"values": [["A", "B", "C"]], "range": "Sheet3!C5:E10"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            result = await node.execute({})

            # Verify the URL contains "Sheet3!C5:E10"
            call_args = mock_get.call_args
            called_url = call_args[0][0]
            assert "Sheet3%21C5%3AE10" in called_url or "Sheet3!C5:E10" in called_url
            assert result["status"] == "success"
            assert result["range"] == "Sheet3!C5:E10"

    @pytest.mark.asyncio
    async def test_read_range_already_has_sheet_name(
        self, mock_credentials, mock_httpx_response
    ):
        """Test that range with embedded sheet name is used as-is."""
        config = GoogleSheetsReadConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name=None,  # No sheet_name
            range="CustomSheet!A1:B2",  # Sheet name already in range
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"values": [["X", "Y"]], "range": "CustomSheet!A1:B2"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get

            result = await node.execute({})

            # Verify the URL uses the range as-is
            call_args = mock_get.call_args
            called_url = call_args[0][0]
            assert "CustomSheet" in called_url
            assert result["status"] == "success"


# ============================================================================
# Write Operation Tests
# ============================================================================


class TestWriteOperation:
    """Test Google Sheets write operation."""

    @pytest.mark.asyncio
    async def test_write_success(self, mock_credentials, mock_httpx_response):
        """Test writing data to a sheet."""
        config = GoogleSheetsWriteConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet1",
            range="A1",
            values='[["Name", "Age"], ["Alice", "30"]]',  # JSON string
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "updatedRange": "Sheet1!A1:B2",
                "updatedRows": 2,
                "updatedColumns": 2,
                "updatedCells": 4,
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.put = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "write_sheet_data"
            assert result["updated_cells"] == 4

    @pytest.mark.asyncio
    async def test_write_to_specific_sheet(self, mock_credentials, mock_httpx_response):
        """Test writing to a specific sheet with sheet_name."""
        config = GoogleSheetsWriteConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="DataSheet",
            range="A1:B2",
            values='[["X", "Y"], ["1", "2"]]',
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200, {"updatedRange": "DataSheet!A1:B2", "updatedCells": 4}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_put = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.put = mock_put

            result = await node.execute({})

            # Verify the URL contains "DataSheet!A1:B2"
            call_args = mock_put.call_args
            called_url = call_args[0][0]
            assert "DataSheet" in called_url
            assert result["status"] == "success"
            assert result["range"] == "DataSheet!A1:B2"


# ============================================================================
# Append Operation Tests
# ============================================================================


class TestAppendOperation:
    """Test Google Sheets append operation."""

    @pytest.mark.asyncio
    async def test_append_success(self, mock_credentials, mock_httpx_response):
        """Test appending data to a sheet."""
        config = GoogleSheetsAppendConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet1",
            range="A:C",
            values='[["Charlie", "35", "Chicago"]]',  # JSON string
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "updates": {
                    "updatedRange": "Sheet1!A4:C4",
                    "updatedRows": 1,
                    "updatedCells": 3,
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "append_rows_to_sheet"

    @pytest.mark.asyncio
    async def test_append_to_specific_sheet(
        self, mock_credentials, mock_httpx_response
    ):
        """Test appending to a specific sheet with sheet_name."""
        config = GoogleSheetsAppendConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="LogSheet",
            range="A:D",
            values='[["Event1", "10:30", "User123", "Success"]]',
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "updates": {
                    "updatedRange": "LogSheet!A10:D10",
                    "updatedRows": 1,
                    "updatedCells": 4,
                }
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            # Verify the URL contains "LogSheet!A:D"
            call_args = mock_post.call_args
            called_url = call_args[0][0]
            assert "LogSheet" in called_url
            assert result["status"] == "success"
            assert result["range"] == "LogSheet!A:D"


# ============================================================================
# Clear Operation Tests
# ============================================================================


class TestClearOperation:
    """Test Google Sheets clear operation."""

    @pytest.mark.asyncio
    async def test_clear_success(self, mock_credentials, mock_httpx_response):
        """Test clearing a range."""
        config = GoogleSheetsClearConfig(
            spreadsheet_id="spreadsheet123", sheet_name="Sheet1", range="A1:D10"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"clearedRange": "Sheet1!A1:D10"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "clear_sheet_range"

    @pytest.mark.asyncio
    async def test_clear_specific_sheet(self, mock_credentials, mock_httpx_response):
        """Test clearing a range on a specific sheet."""
        config = GoogleSheetsClearConfig(
            spreadsheet_id="spreadsheet123", sheet_name="TempData", range="B5:E20"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(200, {"clearedRange": "TempData!B5:E20"})

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            # Verify the URL contains "TempData!B5:E20"
            call_args = mock_post.call_args
            called_url = call_args[0][0]
            assert "TempData" in called_url
            assert result["status"] == "success"


# ============================================================================
# Create Operation Tests
# ============================================================================


class TestCreateOperation:
    """Test Google Sheets create operation."""

    @pytest.mark.asyncio
    async def test_create_spreadsheet(self, mock_credentials, mock_httpx_response):
        """Test creating a new spreadsheet."""
        config = GoogleSheetsCreateConfig(title="New Spreadsheet")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "spreadsheetId": "new_spreadsheet_123",
                "properties": {"title": "New Spreadsheet"},
                "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/new_spreadsheet_123",
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_new_spreadsheet"
            assert result["spreadsheet_id"] == "new_spreadsheet_123"


# ============================================================================
# Get Metadata Operation Tests
# ============================================================================


class TestGetMetadataOperation:
    """Test Google Sheets get metadata operation."""

    @pytest.mark.asyncio
    async def test_get_metadata(self, mock_credentials, mock_httpx_response):
        """Test getting spreadsheet metadata."""
        config = GoogleSheetsGetMetadataConfig(spreadsheet_id="spreadsheet123")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "spreadsheetId": "spreadsheet123",
                "properties": {"title": "My Spreadsheet"},
                "sheets": [
                    {"properties": {"sheetId": 0, "title": "Sheet1"}},
                    {"properties": {"sheetId": 1, "title": "Sheet2"}},
                ],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "fetch_spreadsheet_metadata"
            assert len(result["sheets"]) == 2


# ============================================================================
# Batch Get Operation Tests
# ============================================================================


class TestBatchGetOperation:
    """Test Google Sheets batch get operation."""

    @pytest.mark.asyncio
    async def test_batch_get(self, mock_credentials, mock_httpx_response):
        """Test getting multiple ranges."""
        config = GoogleSheetsBatchGetConfig(
            spreadsheet_id="spreadsheet123",
            ranges="Sheet1!A1:B5, Sheet1!D1:E5",  # Comma-separated string
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "spreadsheetId": "spreadsheet123",
                "valueRanges": [
                    {"range": "Sheet1!A1:B5", "values": [["A", "B"]]},
                    {"range": "Sheet1!D1:E5", "values": [["D", "E"]]},
                ],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "read_multiple_sheet_ranges"
            assert len(result["value_ranges"]) == 2


# ============================================================================
# Batch Update Operation Tests
# ============================================================================


class TestBatchUpdateOperation:
    """Test Google Sheets batch update operation."""

    @pytest.mark.asyncio
    async def test_batch_update(self, mock_credentials, mock_httpx_response):
        """Test updating multiple ranges."""
        config = GoogleSheetsBatchUpdateConfig(
            spreadsheet_id="spreadsheet123",
            data='[{"range": "Sheet1!A1:B2", "values": [["X", "Y"]]}, {"range": "Sheet1!D1:E2", "values": [["W", "Z"]]}]',  # JSON string
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "spreadsheetId": "spreadsheet123",
                "totalUpdatedCells": 4,
                "responses": [],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "write_to_multiple_sheet_ranges"
            assert result["total_updated_cells"] == 4


# ============================================================================
# Batch Clear Operation Tests
# ============================================================================


class TestBatchClearOperation:
    """Test Google Sheets batch clear operation."""

    @pytest.mark.asyncio
    async def test_batch_clear(self, mock_credentials, mock_httpx_response):
        """Test clearing multiple ranges."""
        config = GoogleSheetsBatchClearConfig(
            spreadsheet_id="spreadsheet123", ranges=["Sheet1!A1:B10", "Sheet1!D1:E10"]
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "spreadsheetId": "spreadsheet123",
                "clearedRanges": ["Sheet1!A1:B10", "Sheet1!D1:E10"],
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "clear_multiple_sheet_ranges"
            assert len(result["cleared_ranges"]) == 2


# ============================================================================
# Add Sheet Operation Tests
# ============================================================================


class TestAddSheetOperation:
    """Test Google Sheets add sheet operation."""

    @pytest.mark.asyncio
    async def test_add_sheet(self, mock_credentials, mock_httpx_response):
        """Test adding a new sheet."""
        config = GoogleSheetsAddSheetConfig(
            spreadsheet_id="spreadsheet123",
            sheet_title="New Sheet",  # Correct field name
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "replies": [
                    {
                        "addSheet": {
                            "properties": {"sheetId": 123456, "title": "New Sheet"}
                        }
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "add_spreadsheet_sheet"
            assert result["sheet_id"] == 123456


# ============================================================================
# Delete Sheet Operation Tests
# ============================================================================


class TestDeleteSheetOperation:
    """Test Google Sheets delete sheet operation."""

    @pytest.mark.asyncio
    async def test_delete_sheet(self, mock_credentials, mock_httpx_response):
        """Test deleting a sheet."""
        config = GoogleSheetsDeleteSheetConfig(
            spreadsheet_id="spreadsheet123", sheet_name="Sheet2"
        )
        node = create_node(config, mock_credentials)

        # First call returns metadata, second call deletes
        metadata_response = mock_httpx_response(
            200,
            {
                "sheets": [
                    {"properties": {"sheetId": 0, "title": "Sheet1"}},
                    {"properties": {"sheetId": 123, "title": "Sheet2"}},
                ]
            },
        )
        delete_response = mock_httpx_response(200, {"replies": [{}]})

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=delete_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_spreadsheet_sheet"


# ============================================================================
# Copy Sheet Operation Tests
# ============================================================================


class TestCopySheetOperation:
    """Test Google Sheets copy sheet operation."""

    @pytest.mark.asyncio
    async def test_copy_sheet(self, mock_credentials, mock_httpx_response):
        """Test copying a sheet to another spreadsheet."""
        config = GoogleSheetsCopySheetConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet1",
            destination_spreadsheet_id="dest_spreadsheet_456",
        )
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200, {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
        )
        copy_response = mock_httpx_response(
            200, {"sheetId": 789, "title": "Copy of Sheet1"}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=copy_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "copy_sheet_to_spreadsheet"


# ============================================================================
# Rename Sheet Operation Tests
# ============================================================================


class TestRenameSheetOperation:
    """Test Google Sheets rename sheet operation."""

    @pytest.mark.asyncio
    async def test_rename_sheet(self, mock_credentials, mock_httpx_response):
        """Test renaming a sheet."""
        config = GoogleSheetsRenameSheetConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet1",
            new_name="Renamed Sheet",
        )
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200, {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
        )
        rename_response = mock_httpx_response(200, {"replies": [{}]})

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=rename_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "rename_spreadsheet_sheet"
            assert result["new_name"] == "Renamed Sheet"


# ============================================================================
# Duplicate Sheet Operation Tests
# ============================================================================


class TestDuplicateSheetOperation:
    """Test Google Sheets duplicate sheet operation."""

    @pytest.mark.asyncio
    async def test_duplicate_sheet(self, mock_credentials, mock_httpx_response):
        """Test duplicating a sheet."""
        config = GoogleSheetsDuplicateSheetConfig(
            spreadsheet_id="spreadsheet123", sheet_name="Sheet1", new_name="Sheet1 Copy"
        )
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200, {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
        )
        duplicate_response = mock_httpx_response(
            200,
            {
                "replies": [
                    {
                        "duplicateSheet": {
                            "properties": {"sheetId": 999, "title": "Sheet1 Copy"}
                        }
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=duplicate_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "duplicate_sheet_in_spreadsheet"


# ============================================================================
# Find Replace Operation Tests
# ============================================================================


class TestFindReplaceOperation:
    """Test Google Sheets find replace operation."""

    @pytest.mark.asyncio
    async def test_find_replace(self, mock_credentials, mock_httpx_response):
        """Test find and replace in a sheet."""
        config = GoogleSheetsFindReplaceConfig(
            spreadsheet_id="spreadsheet123", find="old_value", replacement="new_value"
        )
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            200,
            {
                "replies": [
                    {
                        "findReplace": {
                            "occurrencesChanged": 5,
                            "rowsChanged": 3,
                            "sheetsChanged": 1,
                        }
                    }
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "find_and_replace_in_spreadsheet"
            assert result["occurrences_changed"] == 5


# ============================================================================
# Insert Rows Operation Tests
# ============================================================================


class TestInsertRowsOperation:
    """Test Google Sheets insert rows operation."""

    @pytest.mark.asyncio
    async def test_insert_rows(self, mock_credentials, mock_httpx_response):
        """Test inserting rows."""
        config = GoogleSheetsInsertRowsConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet1",
            start_row=5,
            num_rows=3,
        )
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200, {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
        )
        insert_response = mock_httpx_response(200, {"replies": [{}]})

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=insert_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "insert_sheet_rows"
            assert result["num_rows"] == 3


# ============================================================================
# Delete Rows Operation Tests
# ============================================================================


class TestDeleteRowsOperation:
    """Test Google Sheets delete rows operation."""

    @pytest.mark.asyncio
    async def test_delete_rows(self, mock_credentials, mock_httpx_response):
        """Test deleting rows."""
        config = GoogleSheetsDeleteRowsConfig(
            spreadsheet_id="spreadsheet123", sheet_name="Sheet1", start_row=5, end_row=7
        )
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200, {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
        )
        delete_response = mock_httpx_response(200, {"replies": [{}]})

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=delete_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_sheet_rows"
            assert result["rows_deleted"] == 3


# ============================================================================
# Insert Columns Operation Tests
# ============================================================================


class TestInsertColumnsOperation:
    """Test Google Sheets insert columns operation."""

    @pytest.mark.asyncio
    async def test_insert_columns(self, mock_credentials, mock_httpx_response):
        """Test inserting columns."""
        config = GoogleSheetsInsertColumnsConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet1",
            start_column=3,
            num_columns=2,
        )
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200, {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
        )
        insert_response = mock_httpx_response(200, {"replies": [{}]})

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=insert_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "insert_sheet_columns"
            assert result["num_columns"] == 2


# ============================================================================
# Delete Columns Operation Tests
# ============================================================================


class TestDeleteColumnsOperation:
    """Test Google Sheets delete columns operation."""

    @pytest.mark.asyncio
    async def test_delete_columns(self, mock_credentials, mock_httpx_response):
        """Test deleting columns."""
        config = GoogleSheetsDeleteColumnsConfig(
            spreadsheet_id="spreadsheet123",
            sheet_name="Sheet1",
            start_column=3,
            end_column=5,
        )
        node = create_node(config, mock_credentials)

        metadata_response = mock_httpx_response(
            200, {"sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]}
        )
        delete_response = mock_httpx_response(200, {"replies": [{}]})

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=metadata_response)
            mock_post = AsyncMock(return_value=delete_response)
            mock_client.return_value.__aenter__.return_value.get = mock_get
            mock_client.return_value.__aenter__.return_value.post = mock_post

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_sheet_columns"
            assert result["columns_deleted"] == 3


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = GoogleSheetsReadConfig(spreadsheet_id="spreadsheet123")
        node_config = GoogleSheetsNodeConfig(config=config, credentials=None)
        node = GoogleSheetsNode(
            node_id="test-node",
            node_type="automation-google-sheets",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_config(self):
        """Test handling of missing config."""
        node = GoogleSheetsNode(
            node_id="test-node",
            node_type="automation-google-sheets",
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Configuration is required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_error(self, mock_credentials, mock_httpx_response):
        """Test handling of API errors."""
        config = GoogleSheetsReadConfig(spreadsheet_id="invalid_id")
        node = create_node(config, mock_credentials)

        mock_response = mock_httpx_response(
            404, {"error": {"code": 404, "message": "Spreadsheet not found"}}
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ValueError, match="Spreadsheet not found"):
                await node.execute({})


# ============================================================================
# Dynamic Options Tests
# ============================================================================


class TestDynamicOptions:
    """Test dynamic field options loading."""

    @pytest.mark.asyncio
    async def test_load_spreadsheet_options(self, mock_httpx_response):
        """Test loading spreadsheet options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
        }

        mock_response = mock_httpx_response(
            200,
            {
                "files": [
                    {"id": "sheet1", "name": "Sales Report"},
                    {"id": "sheet2", "name": "Inventory"},
                ]
            },
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await GoogleSheetsNode.load_field_options(
                "spreadsheet_id", credential_data, None
            )

            # Returns dict with options and next_page_token for pagination support
            assert isinstance(result, dict)
            assert "options" in result
            assert "next_page_token" in result
            assert len(result["options"]) == 2
            assert all("value" in opt and "label" in opt for opt in result["options"])


# ============================================================================
# Schema Generation Tests
# ============================================================================


class TestSchemaGeneration:
    """Test JSON schema generation."""

    def test_config_schema_generated(self):
        """Test that config schema is properly generated."""
        schema = GoogleSheetsNode.get_config_schema()

        assert schema is not None
        assert "properties" in schema or "$defs" in schema

    def test_config_model_defined(self):
        """Test that config model is defined."""
        model = GoogleSheetsNode.get_config_model()

        assert model is not None
        assert model == GoogleSheetsNodeConfig


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
