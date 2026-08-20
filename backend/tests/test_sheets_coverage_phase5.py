"""Google Sheets coverage phase 5 — developer metadata and connected data sources.

Developer metadata is the durable alternative to "the status column is column
R", which stops being true the moment someone inserts a column: the tag travels
with the row or column it is attached to.

Data source requests are unions — refresh takes exactly one of dataSourceId or
isAll, never both — which is the kind of thing the API rejects at request time
rather than explaining.

The five comment requests are deliberately unimplemented; see the module note
in google_sheets_node.py. This file pins that they stay out until their shapes
are publicly documented.
"""

import pytest

from nodes.google_sheets_node import (
    GoogleSheetsAddDataSourceConfig,
    GoogleSheetsCancelRefreshConfig,
    GoogleSheetsCreateMetadataConfig,
    GoogleSheetsDeleteDataSourceConfig,
    GoogleSheetsDeleteMetadataConfig,
    GoogleSheetsNode,
    GoogleSheetsNodeConfig,
    GoogleSheetsRefreshDataSourceConfig,
    GoogleSheetsUpdateDataSourceConfig,
    GoogleSheetsUpdateMetadataConfig,
)

SHEET_ID = 41


class _Recorder:
    def __init__(self, node, reply=None):
        self.requests = []
        self.reply = reply or {"replies": [{}]}
        node._send_batch_update = self._send
        node._get_sheet_id = self._sheet_id

    async def _send(self, spreadsheet_id, requests, access_token):
        self.requests.append(requests)
        return self.reply

    async def _sheet_id(self, spreadsheet_id, sheet_name, access_token):
        return SHEET_ID

    @property
    def only(self):
        assert len(self.requests) == 1 and len(self.requests[0]) == 1
        return self.requests[0][0]


def _node():
    return GoogleSheetsNode.__new__(GoogleSheetsNode)


class TestDeveloperMetadata:
    @pytest.mark.asyncio
    async def test_sheet_scoped_tag(self):
        node = _node()
        rec = _Recorder(
            node,
            {"replies": [{"createDeveloperMetadata": {"developerMetadata": {"metadataId": 9}}}]},
        )
        out = await node._create_developer_metadata(
            GoogleSheetsCreateMetadataConfig(
                spreadsheet_id="ss", sheet_name="Sheet1",
                metadata_key="status_column", metadata_value="R",
            ),
            "token",
        )
        metadata = rec.only["createDeveloperMetadata"]["developerMetadata"]
        assert metadata["metadataKey"] == "status_column"
        assert metadata["metadataValue"] == "R"
        assert metadata["location"] == {"sheetId": SHEET_ID}
        assert metadata["visibility"] == "DOCUMENT"
        assert out["metadata_id"] == 9

    @pytest.mark.asyncio
    async def test_spreadsheet_scoped_tag(self):
        node = _node()
        rec = _Recorder(node)
        await node._create_developer_metadata(
            GoogleSheetsCreateMetadataConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", metadata_key="k",
                attach_to="SPREADSHEET",
            ),
            "token",
        )
        assert rec.only["createDeveloperMetadata"]["developerMetadata"]["location"] == {
            "spreadsheet": True
        }

    @pytest.mark.asyncio
    async def test_column_tag_converts_to_a_half_open_dimension_range(self):
        """This is the point of the feature: the tag follows column R if it moves."""
        node = _node()
        rec = _Recorder(node)
        await node._create_developer_metadata(
            GoogleSheetsCreateMetadataConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", metadata_key="status_column",
                attach_to="COLUMN", start_index=18,
            ),
            "token",
        )
        location = rec.only["createDeveloperMetadata"]["developerMetadata"]["location"]
        assert location["dimensionRange"] == {
            "sheetId": SHEET_ID,
            "dimension": "COLUMNS",
            "startIndex": 17,
            "endIndex": 18,
        }

    @pytest.mark.asyncio
    async def test_row_tag_spanning_several_rows(self):
        node = _node()
        rec = _Recorder(node)
        await node._create_developer_metadata(
            GoogleSheetsCreateMetadataConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", metadata_key="batch",
                attach_to="ROW", start_index=2, end_index=13,
            ),
            "token",
        )
        location = rec.only["createDeveloperMetadata"]["developerMetadata"]["location"]
        assert location["dimensionRange"]["dimension"] == "ROWS"
        assert location["dimensionRange"]["startIndex"] == 1
        assert location["dimensionRange"]["endIndex"] == 13

    @pytest.mark.asyncio
    async def test_column_tag_without_an_index_is_rejected(self):
        node = _node()
        rec = _Recorder(node)
        with pytest.raises(ValueError, match="needs From"):
            await node._create_developer_metadata(
                GoogleSheetsCreateMetadataConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", metadata_key="k",
                    attach_to="COLUMN",
                ),
                "token",
            )
        assert rec.requests == []

    @pytest.mark.asyncio
    async def test_reversed_range_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="comes before the start"):
            await node._create_developer_metadata(
                GoogleSheetsCreateMetadataConfig(
                    spreadsheet_id="ss", sheet_name="Sheet1", metadata_key="k",
                    attach_to="ROW", start_index=13, end_index=2,
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_update_targets_by_key_with_a_value_only_mask(self):
        node = _node()
        rec = _Recorder(
            node,
            {"replies": [{"updateDeveloperMetadata": {"developerMetadata": [{}, {}]}}]},
        )
        out = await node._update_developer_metadata(
            GoogleSheetsUpdateMetadataConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", metadata_key="status_column",
                metadata_value="V",
            ),
            "token",
        )
        request = rec.only["updateDeveloperMetadata"]
        assert request["dataFilters"] == [
            {"developerMetadataLookup": {"metadataKey": "status_column"}}
        ]
        assert request["fields"] == "metadataValue"
        assert out["entries_updated"] == 2

    @pytest.mark.asyncio
    async def test_delete_targets_by_key(self):
        node = _node()
        rec = _Recorder(
            node,
            {"replies": [{"deleteDeveloperMetadata": {"deletedDeveloperMetadata": [{}]}}]},
        )
        out = await node._delete_developer_metadata(
            GoogleSheetsDeleteMetadataConfig(
                spreadsheet_id="ss", sheet_name="Sheet1", metadata_key="status_column"
            ),
            "token",
        )
        assert rec.only["deleteDeveloperMetadata"]["dataFilter"] == {
            "developerMetadataLookup": {"metadataKey": "status_column"}
        }
        assert out["entries_deleted"] == 1


class TestDataSources:
    @pytest.mark.asyncio
    async def test_table_source(self):
        node = _node()
        rec = _Recorder(
            node, {"replies": [{"addDataSource": {"dataSource": {"dataSourceId": "d1"}}}]}
        )
        out = await node._add_data_source(
            GoogleSheetsAddDataSourceConfig(
                spreadsheet_id="ss", project_id="my-gcp-project",
                dataset_id="analytics", table_id="events",
            ),
            "token",
        )
        bigquery = rec.only["addDataSource"]["dataSource"]["spec"]["bigQuery"]
        assert bigquery["projectId"] == "my-gcp-project"
        assert bigquery["tableSpec"] == {
            "datasetId": "analytics",
            "tableId": "events",
            "tableProjectId": "my-gcp-project",
        }
        assert "querySpec" not in bigquery
        assert out["data_source_id"] == "d1"

    @pytest.mark.asyncio
    async def test_table_project_defaults_to_the_billing_project(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_data_source(
            GoogleSheetsAddDataSourceConfig(
                spreadsheet_id="ss", project_id="billing", dataset_id="d", table_id="t",
                table_project_id="other",
            ),
            "token",
        )
        spec = rec.only["addDataSource"]["dataSource"]["spec"]["bigQuery"]["tableSpec"]
        assert spec["tableProjectId"] == "other"

    @pytest.mark.asyncio
    async def test_query_source(self):
        node = _node()
        rec = _Recorder(node)
        await node._add_data_source(
            GoogleSheetsAddDataSourceConfig(
                spreadsheet_id="ss", project_id="p", source_type="query",
                query="SELECT 1",
            ),
            "token",
        )
        bigquery = rec.only["addDataSource"]["dataSource"]["spec"]["bigQuery"]
        assert bigquery["querySpec"] == {"rawQuery": "SELECT 1"}
        assert "tableSpec" not in bigquery

    @pytest.mark.asyncio
    async def test_table_source_without_dataset_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="Dataset and Table are both required"):
            await node._add_data_source(
                GoogleSheetsAddDataSourceConfig(spreadsheet_id="ss", project_id="p"), "token"
            )

    @pytest.mark.asyncio
    async def test_query_source_without_a_query_is_rejected(self):
        node = _node()
        _Recorder(node)
        with pytest.raises(ValueError, match="Query is required"):
            await node._add_data_source(
                GoogleSheetsAddDataSourceConfig(
                    spreadsheet_id="ss", project_id="p", source_type="query"
                ),
                "token",
            )

    @pytest.mark.asyncio
    async def test_update_carries_the_id_and_masks_spec(self):
        node = _node()
        rec = _Recorder(node)
        await node._update_data_source(
            GoogleSheetsUpdateDataSourceConfig(
                spreadsheet_id="ss", data_source_id="d1", project_id="p",
                source_type="query", query="SELECT 2",
            ),
            "token",
        )
        request = rec.only["updateDataSource"]
        assert request["dataSource"]["dataSourceId"] == "d1"
        assert request["fields"] == "spec"

    @pytest.mark.asyncio
    async def test_delete(self):
        node = _node()
        rec = _Recorder(node)
        await node._delete_data_source(
            GoogleSheetsDeleteDataSourceConfig(spreadsheet_id="ss", data_source_id="d1"), "token"
        )
        assert rec.only["deleteDataSource"] == {"dataSourceId": "d1"}

    @pytest.mark.asyncio
    async def test_refresh_one_source_sends_no_is_all(self):
        """The request is a union — sending both fields is rejected by the API."""
        node = _node()
        rec = _Recorder(node)
        await node._refresh_data_source(
            GoogleSheetsRefreshDataSourceConfig(spreadsheet_id="ss", data_source_id="d1"), "token"
        )
        request = rec.only["refreshDataSource"]
        assert request["dataSourceId"] == "d1"
        assert "isAll" not in request

    @pytest.mark.asyncio
    async def test_refresh_all_sends_no_data_source_id(self):
        node = _node()
        rec = _Recorder(node)
        out = await node._refresh_data_source(
            GoogleSheetsRefreshDataSourceConfig(spreadsheet_id="ss", force="true"), "token"
        )
        request = rec.only["refreshDataSource"]
        assert request["isAll"] is True
        assert "dataSourceId" not in request
        assert request["force"] is True
        assert out["refreshed_all"] is True

    @pytest.mark.asyncio
    async def test_cancel_is_the_same_union(self):
        node = _node()
        rec = _Recorder(node)
        await node._cancel_data_source_refresh(
            GoogleSheetsCancelRefreshConfig(spreadsheet_id="ss"), "token"
        )
        assert rec.only["cancelDataSourceRefresh"] == {"isAll": True}


class TestCommentsAreDeliberatelyAbsent:
    """The five comment requests are gated behind the Developer Preview Program
    and their CommentThread/Post payloads are not publicly documented. Shipping
    guessed shapes for operations nobody can call would be worse than shipping
    nothing, so this pins the decision rather than leaving it to drift."""

    COMMENT_REQUESTS = [
        "insertComment",
        "addCommentReply",
        "updateCommentPost",
        "deleteComment",
        "deleteCommentReply",
    ]

    @pytest.mark.parametrize("request_name", COMMENT_REQUESTS)
    def test_not_emitted_anywhere(self, request_name):
        import inspect

        source = inspect.getsource(GoogleSheetsNode)
        assert f'"{request_name}"' not in source

    def test_the_reason_is_recorded_in_the_module(self):
        """A future reader should find WHY, not just an absence."""
        import inspect

        import nodes.google_sheets_node as module

        assert "Developer Preview" in inspect.getsource(module)


class TestConfigParsing:
    NEW_OPERATIONS = [
        ("create_developer_metadata", {"metadata_key": "k"}),
        ("update_developer_metadata", {"metadata_key": "k", "metadata_value": "v"}),
        ("delete_developer_metadata", {"metadata_key": "k"}),
    ]
    SPREADSHEET_ONLY = [
        ("add_data_source", {"project_id": "p", "dataset_id": "d", "table_id": "t"}),
        ("repoint_data_source", {"data_source_id": "d1", "project_id": "p",
                                "dataset_id": "d", "table_id": "t"}),
        ("delete_data_source", {"data_source_id": "d1"}),
        ("refresh_data_source", {}),
        ("cancel_data_source_refresh", {}),
    ]

    @pytest.mark.parametrize("operation,extra", NEW_OPERATIONS)
    def test_sheet_scoped_operation_parses_and_dispatches(self, operation, extra):
        import inspect

        parsed = GoogleSheetsNodeConfig(
            config={
                "operation": operation,
                "spreadsheet_id": "ss",
                "sheet_name": "Sheet1",
                **extra,
            }
        ).config
        assert parsed.operation == operation
        source = inspect.getsource(GoogleSheetsNode.execute)
        assert f"isinstance(config, {type(parsed).__name__})" in source

    @pytest.mark.parametrize("operation,extra", SPREADSHEET_ONLY)
    def test_spreadsheet_scoped_operation_needs_no_sheet(self, operation, extra):
        import inspect

        parsed = GoogleSheetsNodeConfig(
            config={"operation": operation, "spreadsheet_id": "ss", **extra}
        ).config
        assert parsed.operation == operation
        assert not hasattr(parsed, "sheet_name")
        source = inspect.getsource(GoogleSheetsNode.execute)
        assert f"isinstance(config, {type(parsed).__name__})" in source

    def test_all_new_operations_are_in_the_schema(self):
        schema = GoogleSheetsNode.get_config_schema()
        defs = schema.get("$defs", schema.get("definitions", {}))
        found = set()
        for entry in defs.values():
            operation = entry.get("properties", {}).get("operation", {})
            for value in operation.get("enum", []) or [operation.get("const")]:
                if value:
                    found.add(value)
        for operation, _ in self.NEW_OPERATIONS + self.SPREADSHEET_ONLY:
            assert operation in found
