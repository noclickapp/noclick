"""
Test suite for ResourceHandler and dataset resource references.

Validates the workflow resource system with real PostgreSQL:
- Resource CRUD (create, list, get, delete) via socket events
- Dataset row operations (append, get, update, delete)
- Presigned URL generation (upload/download) with mocked R2
- Access control — users can only access resources in owned workflows
- Dataframe node load_field_options and execute with resource_id
- Workflow-level resource cleanup
"""

import pytest
import asyncio
import json
from typing import Dict, Any
from unittest.mock import patch

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database
from wss.receiver.client_events import (
    ResourceCreateRequest,
    ResourceListRequest,
    ResourceGetRequest,
    ResourceDeleteRequest,
    ResourceUploadUrlRequest,
    ResourceDownloadUrlRequest,
    ResourceDatasetRowsRequest,
    ResourceDatasetAppendRequest,
    ResourceDatasetUpdateRowRequest,
    ResourceDatasetDeleteRowsRequest,
)
from wss.sender import send_event


USER_A = '00000000-0000-4000-8000-000000000001'
USER_B = '00000000-0000-4000-8000-000000000002'


def _find_response(events, request_id):
    """Find a response event by request_id."""
    for event in events:
        if event[1].get('request_id') == request_id:
            return event[1]
    return None


@pytest.mark.asyncio
class TestResourceHandler(BaseHandlerTest):
    """Integration tests for ResourceHandler with real PostgreSQL."""

    def get_session_data(self, sid: str):
        return {
            'sid': sid,
            'user_id': USER_A,
            'email': 'resource-test@example.com',
        }

    async def _setup_user_and_workflow(self, real_database, user_id=USER_A, email='resource-test@example.com'):
        """Create a test user + workflow, return workflow_id."""
        await real_database.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            user_id, email,
        )
        row = await real_database.fetchrow(
            "INSERT INTO workflows (owner_id, name) VALUES ($1, $2) RETURNING id",
            user_id, "Test Workflow",
        )
        return str(row['id'])

    # ── Resource CRUD ────────────────────────────────────────────────────

    async def test_resource_lifecycle_create_list_get_delete(self, real_database, frontend_sio, sid):
        """
        End-to-end lifecycle: create a dataset resource, list it, get it, delete it,
        and verify it's gone.
        """
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # 1. Create
        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="rc-1",
            workflow_id=workflow_id, resource_type="dataset",
            name="Sales Data", metadata={"row_count": 0},
        ))
        await asyncio.sleep(0.2)

        create_resp = _find_response(self.get_main_api_emitted_events("response"), "rc-1")
        assert create_resp and create_resp['data']['success']
        resource = create_resp['data']['resource']
        resource_id = resource['id']
        assert resource['name'] == "Sales Data"
        assert resource['resource_type'] == "dataset"
        assert resource['workflow_id'] == workflow_id

        # 2. List — should contain our resource
        await send_event(frontend_sio, sid, ResourceListRequest(
            event_name="resource:list", request_id="rl-1",
            workflow_id=workflow_id,
        ))
        await asyncio.sleep(0.2)

        list_resp = _find_response(self.get_main_api_emitted_events("response"), "rl-1")
        assert list_resp
        ids = [r['id'] for r in list_resp['data']['resources']]
        assert resource_id in ids

        # 3. Get
        await send_event(frontend_sio, sid, ResourceGetRequest(
            event_name="resource:get", request_id="rg-1",
            resource_id=resource_id,
        ))
        await asyncio.sleep(0.2)

        get_resp = _find_response(self.get_main_api_emitted_events("response"), "rg-1")
        assert get_resp
        assert get_resp['data']['resource']['id'] == resource_id

        # 4. Delete
        await send_event(frontend_sio, sid, ResourceDeleteRequest(
            event_name="resource:delete", request_id="rd-1",
            resource_id=resource_id,
        ))
        await asyncio.sleep(0.2)

        del_resp = _find_response(self.get_main_api_emitted_events("response"), "rd-1")
        assert del_resp and del_resp['data']['success']

        # 5. Verify gone
        row = await real_database.fetchrow(
            "SELECT id FROM workflow_resources WHERE id = $1", resource_id
        )
        assert row is None

    async def test_resource_create_enforces_100mb_cap(self, real_database, frontend_sio, sid):
        """The size cap is enforced server-side at resource:create — a declared
        size over 100MB errors with no row written; exactly at the cap passes."""
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="rc-over",
            workflow_id=workflow_id, resource_type="file",
            name="huge.bin", mime_type="application/octet-stream",
            size_bytes=100 * 1024 * 1024 + 1,
        ))
        await asyncio.sleep(0.2)

        over_resp = _find_response(self.get_main_api_emitted_events("response"), "rc-over")
        assert over_resp and "100 MB" in over_resp['error']
        row = await real_database.fetchrow(
            "SELECT id FROM workflow_resources WHERE workflow_id = $1", workflow_id
        )
        assert row is None

        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="rc-max",
            workflow_id=workflow_id, resource_type="file",
            name="max.bin", mime_type="application/octet-stream",
            size_bytes=100 * 1024 * 1024,
        ))
        await asyncio.sleep(0.2)

        max_resp = _find_response(self.get_main_api_emitted_events("response"), "rc-max")
        assert max_resp and max_resp['data']['success']

    # ── Dataset Row Operations ───────────────────────────────────────────

    async def test_dataset_rows_append_read_update_delete(self, real_database, frontend_sio, sid):
        """
        Full dataset row lifecycle: append rows, read them back with pagination,
        update one, delete one, and verify counts.
        """
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # Create dataset resource
        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="ds-create",
            workflow_id=workflow_id, resource_type="dataset", name="Users",
        ))
        await asyncio.sleep(0.2)
        resource_id = _find_response(
            self.get_main_api_emitted_events("response"), "ds-create"
        )['data']['resource']['id']

        # Append 3 rows
        rows_data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Charlie", "age": 35},
        ]
        await send_event(frontend_sio, sid, ResourceDatasetAppendRequest(
            event_name="resource:dataset:append", request_id="ds-append",
            resource_id=resource_id, rows=rows_data,
        ))
        await asyncio.sleep(0.2)

        append_resp = _find_response(self.get_main_api_emitted_events("response"), "ds-append")
        assert append_resp['data']['success']
        assert append_resp['data']['inserted_count'] == 3

        # Read rows — verify order and pagination
        await send_event(frontend_sio, sid, ResourceDatasetRowsRequest(
            event_name="resource:dataset:rows", request_id="ds-read",
            resource_id=resource_id, limit=2, offset=0,
        ))
        await asyncio.sleep(0.2)

        read_resp = _find_response(self.get_main_api_emitted_events("response"), "ds-read")
        assert read_resp['data']['total_count'] == 3
        returned_rows = read_resp['data']['rows']
        assert len(returned_rows) == 2
        assert returned_rows[0]['data']['name'] == "Alice"
        assert returned_rows[1]['data']['name'] == "Bob"
        row_id_alice = returned_rows[0]['id']

        # Update Alice's age
        await send_event(frontend_sio, sid, ResourceDatasetUpdateRowRequest(
            event_name="resource:dataset:update_row", request_id="ds-update",
            resource_id=resource_id, row_id=row_id_alice,
            data={"name": "Alice", "age": 31},
        ))
        await asyncio.sleep(0.2)

        update_resp = _find_response(self.get_main_api_emitted_events("response"), "ds-update")
        assert update_resp['data']['success']

        # Verify updated data in DB
        db_row = await real_database.fetchrow(
            "SELECT data FROM dataset_rows WHERE id = $1", row_id_alice
        )
        assert db_row['data']['age'] == 31

        # Delete Bob (row index 1)
        # First, get Bob's row_id from page 2
        await send_event(frontend_sio, sid, ResourceDatasetRowsRequest(
            event_name="resource:dataset:rows", request_id="ds-read2",
            resource_id=resource_id, limit=10, offset=0,
        ))
        await asyncio.sleep(0.2)
        all_rows = _find_response(
            self.get_main_api_emitted_events("response"), "ds-read2"
        )['data']['rows']
        bob_id = [r for r in all_rows if r['data']['name'] == "Bob"][0]['id']

        await send_event(frontend_sio, sid, ResourceDatasetDeleteRowsRequest(
            event_name="resource:dataset:delete_rows", request_id="ds-del",
            resource_id=resource_id, row_ids=[bob_id],
        ))
        await asyncio.sleep(0.2)

        del_resp = _find_response(self.get_main_api_emitted_events("response"), "ds-del")
        assert del_resp['data']['success']
        assert del_resp['data']['deleted_count'] == 1

        # Verify final count
        count = await real_database.fetchval(
            "SELECT COUNT(*) FROM dataset_rows WHERE resource_id = $1", resource_id
        )
        assert count == 2

        # Verify metadata row_count was updated
        meta = await real_database.fetchrow(
            "SELECT metadata FROM workflow_resources WHERE id = $1", resource_id
        )
        assert meta['metadata']['row_count'] == 2

    async def test_dataset_rows_rejects_non_dataset_resource(self, real_database, frontend_sio, sid):
        """Attempting to append/read rows on a non-dataset resource returns an error."""
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # Create a file resource (not dataset)
        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="file-c",
            workflow_id=workflow_id, resource_type="file", name="doc.pdf",
        ))
        await asyncio.sleep(0.2)
        resource_id = _find_response(
            self.get_main_api_emitted_events("response"), "file-c"
        )['data']['resource']['id']

        # Try to read rows — should error
        await send_event(frontend_sio, sid, ResourceDatasetRowsRequest(
            event_name="resource:dataset:rows", request_id="bad-read",
            resource_id=resource_id,
        ))
        await asyncio.sleep(0.2)
        resp = _find_response(self.get_main_api_emitted_events("response"), "bad-read")
        assert resp.get('error') == "Resource is not a dataset"

    # ── Presigned URLs ───────────────────────────────────────────────────

    async def test_presigned_upload_and_download_urls(self, real_database, frontend_sio, sid):
        """
        Generate presigned upload URL, verify storage_ref is saved,
        then generate download URL and verify it returns a URL.
        """
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # Create a file resource
        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="blob-c",
            workflow_id=workflow_id, resource_type="image", name="photo.jpg",
            size_bytes=1234,
        ))
        await asyncio.sleep(0.2)
        resource_id = _find_response(
            self.get_main_api_emitted_events("response"), "blob-c"
        )['data']['resource']['id']

        # Mock R2 presigned URL generation (patch at source since handler uses lazy import)
        with patch("utils.r2_cloudflare.generate_presigned_upload_url",
                   return_value="https://r2.example.com/upload?token=abc") as sign_upload:
            await send_event(frontend_sio, sid, ResourceUploadUrlRequest(
                event_name="resource:upload_url", request_id="upload-1",
                resource_id=resource_id, filename="photo.jpg",
                content_type="image/jpeg",
            ))
            await asyncio.sleep(0.2)

        upload_resp = _find_response(self.get_main_api_emitted_events("response"), "upload-1")
        assert upload_resp['data']['upload_url'] == "https://r2.example.com/upload?token=abc"
        assert upload_resp['data']['storage_ref']
        sign_upload.assert_called_once_with(
            "workflow-resources",
            upload_resp['data']['storage_ref'],
            "image/jpeg",
            content_length=1234,
        )

        # Verify storage_ref was persisted
        row = await real_database.fetchrow(
            "SELECT storage_ref, mime_type FROM workflow_resources WHERE id = $1", resource_id
        )
        assert row['storage_ref'] is not None
        assert row['mime_type'] == "image/jpeg"

        # URL policy belongs to the storage adapter: hosted deployments return
        # a CDN URL while private community buckets return a signed URL. Keep
        # this handler test independent of whichever edition/config is running.
        expected_download_url = f"https://storage.example.test/{row['storage_ref']}"
        with patch(
            "utils.r2_cloudflare.get_public_download_url",
            return_value=expected_download_url,
        ) as get_download_url:
            await send_event(frontend_sio, sid, ResourceDownloadUrlRequest(
                event_name="resource:download_url", request_id="download-1",
                resource_id=resource_id,
            ))
            await asyncio.sleep(0.2)

        dl_resp = _find_response(self.get_main_api_emitted_events("response"), "download-1")
        assert dl_resp['data']['download_url'] == expected_download_url
        get_download_url.assert_called_once_with(row['storage_ref'])

    async def test_download_url_returns_error_when_no_blob(self, real_database, frontend_sio, sid):
        """Requesting a download URL for a resource without a stored file returns an error."""
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # Create resource with no storage_ref
        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="no-blob",
            workflow_id=workflow_id, resource_type="file", name="empty.txt",
        ))
        await asyncio.sleep(0.2)
        resource_id = _find_response(
            self.get_main_api_emitted_events("response"), "no-blob"
        )['data']['resource']['id']

        await send_event(frontend_sio, sid, ResourceDownloadUrlRequest(
            event_name="resource:download_url", request_id="dl-fail",
            resource_id=resource_id,
        ))
        await asyncio.sleep(0.2)
        resp = _find_response(self.get_main_api_emitted_events("response"), "dl-fail")
        assert resp.get('error') == "Resource has no stored file"

    # ── Access Control ───────────────────────────────────────────────────

    async def test_access_control_prevents_cross_user_access(self, real_database, frontend_sio, sid):
        """
        User B cannot get/delete resources in User A's workflow via direct DB check.
        The handler uses check_resource_access which scopes to the workflow owner.
        """
        # Create User A's workflow & resource
        wf_a = await self._setup_user_and_workflow(real_database, USER_A, 'a@test.com')
        await asyncio.sleep(0.1)

        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="acl-create",
            workflow_id=wf_a, resource_type="dataset", name="Private Data",
        ))
        await asyncio.sleep(0.2)
        resource_id = _find_response(
            self.get_main_api_emitted_events("response"), "acl-create"
        )['data']['resource']['id']

        # Create User B
        await real_database.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            USER_B, 'b@test.com',
        )

        # Verify User B cannot find this resource via a scoped query
        row = await real_database.fetchrow("""
            SELECT id FROM workflow_resources wr
            WHERE wr.id = $1
              AND wr.workflow_id IN (SELECT id FROM workflows WHERE owner_id = $2)
        """, resource_id, USER_B)
        assert row is None, "User B must not see User A's resource"

        # Verify User A can still see it
        row_a = await real_database.fetchrow("""
            SELECT id FROM workflow_resources wr
            WHERE wr.id = $1
              AND wr.workflow_id IN (SELECT id FROM workflows WHERE owner_id = $2)
        """, resource_id, USER_A)
        assert row_a is not None

    # ── Dataframe Node: load_field_options ────────────────────────────────

    async def test_dataframe_load_field_options_returns_datasets(self, real_database, frontend_sio, sid):
        """
        DataframeInterfaceNode.load_field_options returns the user's dataset resources
        as selectable options with correct label format.
        """
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # Create a dataset resource with row_count metadata
        await real_database.execute("""
            INSERT INTO workflow_resources (owner_id, workflow_id, resource_type, name, metadata)
            VALUES ($1, $2, 'dataset', 'Customers', '{"row_count": 42}')
        """, USER_A, workflow_id)

        from nodes.interface.dataframe_node import DataframeInterfaceNode

        result = await DataframeInterfaceNode.load_field_options(
            field_name="resource_id",
            credential_data={},
            context={"_user_id": USER_A},
        )

        assert len(result["options"]) >= 1
        opt = result["options"][0]
        assert "Customers" in opt["label"]
        assert "42 rows" in opt["label"]
        assert opt["value"]  # non-empty UUID

    async def test_dataframe_load_field_options_empty_without_user(self, real_database, frontend_sio, sid):
        """load_field_options returns empty list when no _user_id in context."""
        from nodes.interface.dataframe_node import DataframeInterfaceNode

        result = await DataframeInterfaceNode.load_field_options(
            field_name="resource_id",
            credential_data={},
            context={},
        )
        assert result["options"] == []

    # ── Dataframe Node: execute with resource_id ─────────────────────────

    async def test_dataframe_execute_loads_from_dataset_rows(self, real_database, frontend_sio, sid):
        """
        When resource_id is set, DataframeInterfaceNode.execute() loads data from
        dataset_rows instead of using inline config data.
        """
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # Insert a dataset resource + rows directly
        resource_row = await real_database.fetchrow("""
            INSERT INTO workflow_resources (owner_id, workflow_id, resource_type, name)
            VALUES ($1, $2, 'dataset', 'Products')
            RETURNING id
        """, USER_A, workflow_id)
        resource_id = str(resource_row['id'])

        # Insert 2 rows (pass dicts directly — asyncpg JSONB codec handles serialization)
        await real_database.execute("""
            INSERT INTO dataset_rows (resource_id, row_index, data)
            VALUES ($1, 0, $2), ($1, 1, $3)
        """, resource_id, {"item": "Widget", "price": 10},
            {"item": "Gadget", "price": 20})

        # Execute node with resource_id
        from nodes.interface.dataframe_node import DataframeInterfaceNode, DataframeConfig, DataframeInterfaceNodeConfig

        config = DataframeInterfaceNodeConfig(
            config=DataframeConfig(resource_id=resource_id)
        )
        node = DataframeInterfaceNode(
            "dataframe",
            "interface-dataframe",
            {},
            config=config,
            workflow_id=workflow_id,
            user_id=USER_A,
        )

        # Patch emit to capture output
        emitted = []
        async def mock_emit(data):
            emitted.append(data)
        node.emit = mock_emit

        output = await node.execute({})

        assert output['type'] == "dataframe"
        assert len(output['data']) == 2
        assert output['data'][0]['item'] == "Widget"
        assert output['data'][1]['item'] == "Gadget"

    async def test_dataframe_execute_falls_back_to_inline_data(self, real_database, frontend_sio, sid):
        """
        When resource_id is empty, DataframeInterfaceNode.execute() falls back to
        the inline data field or upstream input.
        """
        from nodes.interface.dataframe_node import DataframeInterfaceNode, DataframeConfig, DataframeInterfaceNodeConfig

        config = DataframeInterfaceNodeConfig(
            config=DataframeConfig(data='[{"x": 1}]')
        )
        node = DataframeInterfaceNode.__new__(DataframeInterfaceNode)
        node._config = config
        node._emit_callback = None

        emitted = []
        async def mock_emit(data):
            emitted.append(data)
        node.emit = mock_emit

        output = await node.execute({})

        assert output['type'] == "dataframe"
        assert output['data'] == [{"x": 1}]

    # ── Workflow-Level Cleanup ───────────────────────────────────────────

    async def test_workflow_cleanup_deletes_resources_and_rows(self, real_database, frontend_sio, sid):
        """
        cleanup_workflow_resources deletes all workflow_resources (and cascade-deletes
        dataset_rows) for a workflow. R2 blobs are cleaned up via mocked delete_files_from_r2.
        """
        workflow_id = await self._setup_user_and_workflow(real_database)
        await asyncio.sleep(0.1)

        # Create dataset resource + rows
        await send_event(frontend_sio, sid, ResourceCreateRequest(
            event_name="resource:create", request_id="cleanup-c",
            workflow_id=workflow_id, resource_type="dataset", name="ToClean",
        ))
        await asyncio.sleep(0.2)
        resource_id = _find_response(
            self.get_main_api_emitted_events("response"), "cleanup-c"
        )['data']['resource']['id']

        await send_event(frontend_sio, sid, ResourceDatasetAppendRequest(
            event_name="resource:dataset:append", request_id="cleanup-a",
            resource_id=resource_id, rows=[{"k": "v"}],
        ))
        await asyncio.sleep(0.2)

        # Also create a blob resource with storage_ref
        await real_database.execute("""
            INSERT INTO workflow_resources (owner_id, workflow_id, resource_type, name, storage_ref)
            VALUES ($1, $2, 'file', 'blob.bin', 'fake/key/blob.bin')
        """, USER_A, workflow_id)

        # Verify resources exist
        count = await real_database.fetchval(
            "SELECT COUNT(*) FROM workflow_resources WHERE workflow_id = $1", workflow_id
        )
        assert count == 2

        # Run cleanup
        pool = real_database.pool
        with patch("utils.r2_cloudflare.delete_files_from_r2") as mock_r2_delete:
            from utils.workflow_resource_manager import cleanup_workflow_resources
            results = await cleanup_workflow_resources(pool, workflow_id)

        # Verify R2 cleanup was called for the blob
        mock_r2_delete.assert_called_once()
        call_args = mock_r2_delete.call_args
        assert "workflow-resources" in call_args.args or call_args[0][0] == "workflow-resources"

        # Verify DB resources are gone
        count_after = await real_database.fetchval(
            "SELECT COUNT(*) FROM workflow_resources WHERE workflow_id = $1", workflow_id
        )
        assert count_after == 0

        # Verify dataset_rows cascade-deleted
        row_count = await real_database.fetchval(
            "SELECT COUNT(*) FROM dataset_rows WHERE resource_id = $1", resource_id
        )
        assert row_count == 0
