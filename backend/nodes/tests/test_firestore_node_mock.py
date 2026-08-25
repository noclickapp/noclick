"""
Mock tests for the Google Cloud Firestore REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Documents: get, list, create, update/upsert, delete
- Batch: batch get, batch write
- Queries: run query, run aggregation query, list collection IDs
- Transactions: begin, commit, rollback
- Databases: get, list
- Indexes: list
- Operations: get operation
- Error handling: API errors, missing credentials
- Dynamic options: database picker

The OAuth token never expires in these tests (expires_at far in the future),
so `_ensure_fresh_token` short-circuits without a DB pool. All HTTP traffic is
intercepted by patching `nodes.firestore_node.httpx.AsyncClient`.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.firestore_node import (
    FirestoreNode,
    FirestoreNodeConfig,
    FirestoreOAuthCredential,
    FirestoreServiceAccountCredential,
    FirestoreFirebaseIdTokenCredential,
    FirestoreGetDocumentConfig,
    FirestoreListDocumentsConfig,
    FirestoreCreateDocumentConfig,
    FirestoreUpdateDocumentConfig,
    FirestoreDeleteDocumentConfig,
    FirestoreBatchGetConfig,
    FirestoreBatchWriteConfig,
    FirestoreRunQueryConfig,
    FirestoreRunAggregationQueryConfig,
    FirestoreListCollectionIdsConfig,
    FirestoreBeginTransactionConfig,
    FirestoreCommitConfig,
    FirestoreRollbackConfig,
    FirestoreExecutePipelineConfig,
    FirestoreListenConfig,
    FirestoreWriteConfig,
    FirestoreGetDatabaseConfig,
    FirestoreListDatabasesConfig,
    FirestoreCreateDatabaseConfig,
    FirestoreCloneDatabaseConfig,
    FirestoreRestoreDatabaseConfig,
    FirestoreUpdateDatabaseConfig,
    FirestoreDeleteDatabaseConfig,
    FirestoreCreateBackupScheduleConfig,
    FirestoreGetBackupScheduleConfig,
    FirestoreListBackupSchedulesConfig,
    FirestoreUpdateBackupScheduleConfig,
    FirestoreDeleteBackupScheduleConfig,
    FirestoreExportDocumentsConfig,
    FirestoreImportDocumentsConfig,
    FirestoreBulkDeleteDocumentsConfig,
    FirestoreListIndexesConfig,
    FirestoreGetIndexConfig,
    FirestoreDeleteIndexConfig,
    FirestoreCreateUserCredsConfig,
    FirestoreGetUserCredsConfig,
    FirestoreListUserCredsConfig,
    FirestoreEnableUserCredsConfig,
    FirestoreDisableUserCredsConfig,
    FirestoreDeleteUserCredsConfig,
    FirestoreResetUserCredsPasswordConfig,
    FirestoreListFieldsConfig,
    FirestoreGetFieldConfig,
    FirestoreUpdateFieldConfig,
    FirestoreGetOperationConfig,
    FirestoreListOperationsConfig,
    FirestoreCancelOperationConfig,
    FirestoreDeleteOperationConfig,
    FirestoreGetLocationConfig,
    FirestoreListLocationsConfig,
    FirestoreGetBackupConfig,
    FirestoreListBackupsConfig,
    FirestoreDeleteBackupConfig,
    FirestorePartitionQueryConfig,
    FirestoreCustomApiCallConfig,
    FirestoreOnDocumentChangedConfig,
)


@pytest.fixture
def oauth_credentials():
    return FirestoreOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )


def create_firestore_node(config):
    return FirestoreNode(
        node_id="test-firestore-node",
        node_type="automation-firestore",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.content = b"{}"
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def create_capturing_mock_client(status_code=200, json_data=None):
    """Mock AsyncClient that records the request kwargs."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()
    captured = {}

    async def async_request(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client, captured


# ============================================================================
# Document operations
# ============================================================================


class TestFirestoreDocumentsMock:
    @pytest.mark.asyncio
    async def test_get_document(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreGetDocumentConfig(
                project_id="proj", collection_path="users", document_id="abc"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"name": "projects/proj/databases/(default)/documents/users/abc"}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_document"
        assert "users/abc" in result["data"]["name"]

    @pytest.mark.asyncio
    async def test_list_documents(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreListDocumentsConfig(
                project_id="proj", collection_path="users", page_size="10"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"documents": [{"name": "users/a"}, {"name": "users/b"}]}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_documents"
        assert len(result["data"]["documents"]) == 2

    @pytest.mark.asyncio
    async def test_create_document(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreCreateDocumentConfig(
                project_id="proj",
                collection_path="users",
                document_id="abc",
                fields='{"name": {"stringValue": "Ada"}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"name": "projects/proj/databases/(default)/documents/users/abc"}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_document"

    @pytest.mark.asyncio
    async def test_update_document(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreUpdateDocumentConfig(
                project_id="proj",
                collection_path="users",
                document_id="abc",
                fields='{"age": {"integerValue": "31"}}',
                update_mask="age",
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"name": "users/abc"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_document"

    @pytest.mark.asyncio
    async def test_delete_document(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreDeleteDocumentConfig(
                project_id="proj", collection_path="users", document_id="abc"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_document"


# ============================================================================
# Batch operations
# ============================================================================


class TestFirestoreBatchMock:
    @pytest.mark.asyncio
    async def test_batch_get_documents(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreBatchGetConfig(
                project_id="proj", document_paths="users/a, users/b"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, [{"found": {"name": "users/a"}}, {"found": {"name": "users/b"}}]
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "batch_get_documents"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_batch_write(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreBatchWriteConfig(
                project_id="proj",
                writes='[{"update": {"name": "projects/proj/databases/(default)/documents/users/a", "fields": {}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"writeResults": [{}], "status": [{}]})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "batch_write"


# ============================================================================
# Query operations
# ============================================================================


class TestFirestoreQueriesMock:
    @pytest.mark.asyncio
    async def test_run_query(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreRunQueryConfig(
                project_id="proj",
                structured_query='{"from": [{"collectionId": "users"}], "limit": 5}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, [{"document": {"name": "users/a"}}])
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_query"

    @pytest.mark.asyncio
    async def test_partition_query(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestorePartitionQueryConfig(
                project_id="proj",
                structured_query='{"from": [{"collectionId": "users"}]}',
                partition_count="4",
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"partitions": [{"values": []}, {"values": []}]}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "partition_query"

    @pytest.mark.asyncio
    async def test_run_aggregation_query(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreRunAggregationQueryConfig(
                project_id="proj",
                structured_aggregation_query='{"structuredQuery": {"from": [{"collectionId": "users"}]}, "aggregations": [{"count": {}, "alias": "total"}]}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, [{"result": {"aggregateFields": {"total": {"integerValue": "42"}}}}]
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_aggregation_query"

    @pytest.mark.asyncio
    async def test_list_collection_ids(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreListCollectionIdsConfig(project_id="proj", page_size="50"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"collectionIds": ["users", "orders"]})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_collection_ids"
        assert "users" in result["data"]["collectionIds"]

    @pytest.mark.asyncio
    async def test_execute_pipeline(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreExecutePipelineConfig(
                project_id="proj",
                pipeline_request='{"structuredPipeline": {"stages": [{"db": {}}]}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"results": [{"name": "users/a"}]})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "execute_pipeline"


class TestFirestoreStreamingMock:
    @pytest.mark.asyncio
    async def test_listen_stream(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreListenConfig(
                project_id="proj",
                listen_request='{"addTarget": {"documents": {"documents": ["projects/proj/databases/(default)/documents/users/a"]}, "targetId": 1}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client, captured = create_capturing_mock_client(
            200, {"targetChange": {"targetIds": [1]}}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "listen"
        assert (
            captured["kwargs"]["url"]
            == "https://firestore.googleapis.com/v1/projects/proj/databases/(default)/documents:listen"
        )

    @pytest.mark.asyncio
    async def test_write_stream(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreWriteConfig(
                project_id="proj",
                write_request='{"streamId": "stream-1", "writes": []}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client, captured = create_capturing_mock_client(
            200, {"streamId": "stream-1"}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "write"
        assert captured["kwargs"]["json"]["streamId"] == "stream-1"


# ============================================================================
# Transaction operations
# ============================================================================


class TestFirestoreTransactionsMock:
    @pytest.mark.asyncio
    async def test_begin_transaction(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreBeginTransactionConfig(project_id="proj"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"transaction": "txn_abc"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "begin_transaction"
        assert result["data"]["transaction"] == "txn_abc"

    @pytest.mark.asyncio
    async def test_commit(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreCommitConfig(
                project_id="proj",
                writes='[{"update": {"name": "projects/proj/databases/(default)/documents/users/a", "fields": {}}}]',
                transaction="txn_abc",
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"writeResults": [{}]})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "commit"

    @pytest.mark.asyncio
    async def test_rollback(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreRollbackConfig(project_id="proj", transaction="txn_abc"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "rollback"


# ============================================================================
# Database / index / operation operations
# ============================================================================


class TestFirestoreAdminMock:
    @pytest.mark.asyncio
    async def test_get_database(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreGetDatabaseConfig(project_id="proj"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"name": "projects/proj/databases/(default)", "type": "FIRESTORE_NATIVE"}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_database"
        assert result["data"]["type"] == "FIRESTORE_NATIVE"

    @pytest.mark.asyncio
    async def test_list_databases(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreListDatabasesConfig(project_id="proj"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"databases": [{"name": "projects/proj/databases/(default)"}]}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_databases"
        assert len(result["data"]["databases"]) == 1

    @pytest.mark.asyncio
    async def test_create_database(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreCreateDatabaseConfig(
                project_id="proj",
                new_database_id="analytics",
                database='{"locationId": "us-central", "type": "FIRESTORE_NATIVE"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client, captured = create_capturing_mock_client(200, {"name": "op_create"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_database"
        assert captured["kwargs"]["params"]["databaseId"] == "analytics"

    @pytest.mark.asyncio
    async def test_clone_database(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreCloneDatabaseConfig(
                project_id="proj",
                new_database_id="clone-db",
                clone_request='{"pitrSnapshot": {"sourceDatabase": "projects/proj/databases/(default)", "snapshotTime": "2026-06-20T00:00:00Z"}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client, captured = create_capturing_mock_client(200, {"name": "op_clone"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "clone_database"
        assert captured["kwargs"]["json"]["databaseId"] == "clone-db"

    @pytest.mark.asyncio
    async def test_restore_database(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreRestoreDatabaseConfig(
                project_id="proj",
                new_database_id="restore-db",
                restore_request='{"backup": "projects/proj/locations/us/backups/backup-1"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client, captured = create_capturing_mock_client(200, {"name": "op_restore"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "restore_database"
        assert captured["kwargs"]["json"]["databaseId"] == "restore-db"

    @pytest.mark.asyncio
    async def test_list_indexes(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreListIndexesConfig(project_id="proj", collection_id="users"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client, captured = create_capturing_mock_client(
            200, {"indexes": [{"name": "idx_1"}]}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_indexes"
        assert (
            captured["kwargs"]["url"]
            == "https://firestore.googleapis.com/v1/projects/proj/databases/(default)/collectionGroups/users/indexes"
        )

    @pytest.mark.asyncio
    async def test_get_index(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreGetIndexConfig(
                project_id="proj", collection_id="users", index_id="idx_1"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"name": "idx_1"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_index"

    @pytest.mark.asyncio
    async def test_delete_index(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreDeleteIndexConfig(
                project_id="proj", collection_id="users", index_id="idx_1"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_index"

    @pytest.mark.asyncio
    async def test_update_database(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreUpdateDatabaseConfig(
                project_id="proj",
                database='{"type": "FIRESTORE_NATIVE"}',
                update_mask="deleteProtectionState",
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"name": "projects/proj/databases/(default)"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_database"

    @pytest.mark.asyncio
    async def test_delete_database(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreDeleteDatabaseConfig(project_id="proj"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"name": "op_1"})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_database"

    @pytest.mark.asyncio
    async def test_export_import_bulk_delete(self, oauth_credentials):
        configs = [
            FirestoreExportDocumentsConfig(
                project_id="proj",
                output_uri_prefix="gs://bucket/export",
                collection_ids="users,orders",
            ),
            FirestoreImportDocumentsConfig(
                project_id="proj",
                input_uri_prefix="gs://bucket/export",
                collection_ids="users",
            ),
            FirestoreBulkDeleteDocumentsConfig(
                project_id="proj",
                collection_ids="users",
            ),
        ]
        actions = ["export_documents", "import_documents", "bulk_delete_documents"]
        for cfg, action in zip(configs, actions):
            node = create_firestore_node(
                FirestoreNodeConfig(config=cfg, credentials=oauth_credentials)
            )
            mock_client = create_mock_client(200, {"name": "op_1"})
            with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
                result = await node.execute({})
            assert result["status"] == "success"
            assert result["action"] == action

    @pytest.mark.asyncio
    async def test_backup_schedule_operations(self, oauth_credentials):
        cases = [
            (
                FirestoreCreateBackupScheduleConfig(
                    project_id="proj",
                    backup_schedule='{"retention": "604800s", "dailyRecurrence": {}}',
                ),
                "create_backup_schedule",
            ),
            (
                FirestoreGetBackupScheduleConfig(
                    project_id="proj", backup_schedule_id="sched_1"
                ),
                "get_backup_schedule",
            ),
            (
                FirestoreListBackupSchedulesConfig(project_id="proj"),
                "list_backup_schedules",
            ),
            (
                FirestoreUpdateBackupScheduleConfig(
                    project_id="proj",
                    backup_schedule_id="sched_1",
                    backup_schedule='{"retention": "1209600s"}',
                    update_mask="retention",
                ),
                "update_backup_schedule",
            ),
            (
                FirestoreDeleteBackupScheduleConfig(
                    project_id="proj", backup_schedule_id="sched_1"
                ),
                "delete_backup_schedule",
            ),
        ]
        for cfg, action in cases:
            node = create_firestore_node(
                FirestoreNodeConfig(config=cfg, credentials=oauth_credentials)
            )
            mock_client = create_mock_client(200, {"name": action})
            with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
                result = await node.execute({})
            assert result["status"] == "success"
            assert result["action"] == action

    @pytest.mark.asyncio
    async def test_field_operations(self, oauth_credentials):
        cases = [
            (
                FirestoreListFieldsConfig(project_id="proj", collection_id="users"),
                "list_fields",
            ),
            (
                FirestoreGetFieldConfig(project_id="proj", collection_id="users", field_path="age"),
                "get_field",
            ),
            (
                FirestoreUpdateFieldConfig(
                    project_id="proj",
                    collection_id="users",
                    field_path="age",
                    field='{"indexConfig": {"indexes": []}}',
                    update_mask="indexConfig",
                ),
                "update_field",
            ),
        ]
        for cfg, action in cases:
            node = create_firestore_node(
                FirestoreNodeConfig(config=cfg, credentials=oauth_credentials)
            )
            mock_client = create_mock_client(200, {"name": action})
            with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
                result = await node.execute({})
            assert result["status"] == "success"
            assert result["action"] == action

    @pytest.mark.asyncio
    async def test_user_creds_operations(self, oauth_credentials):
        cases = [
            (
                FirestoreCreateUserCredsConfig(
                    project_id="proj",
                    user_creds_id="appuser1",
                    user_creds='{"userName": "app_user", "userSecret": "secret"}',
                ),
                "create_user_creds",
            ),
            (
                FirestoreGetUserCredsConfig(project_id="proj", user_creds_id="appuser1"),
                "get_user_creds",
            ),
            (
                FirestoreListUserCredsConfig(project_id="proj"),
                "list_user_creds",
            ),
            (
                FirestoreEnableUserCredsConfig(project_id="proj", user_creds_id="appuser1"),
                "enable_user_creds",
            ),
            (
                FirestoreDisableUserCredsConfig(project_id="proj", user_creds_id="appuser1"),
                "disable_user_creds",
            ),
            (
                FirestoreDeleteUserCredsConfig(project_id="proj", user_creds_id="appuser1"),
                "delete_user_creds",
            ),
            (
                FirestoreResetUserCredsPasswordConfig(
                    project_id="proj", user_creds_id="appuser1"
                ),
                "reset_user_creds_password",
            ),
        ]
        for cfg, action in cases:
            node = create_firestore_node(
                FirestoreNodeConfig(config=cfg, credentials=oauth_credentials)
            )
            mock_client = create_mock_client(200, {"name": action})
            with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
                result = await node.execute({})
            assert result["status"] == "success"
            assert result["action"] == action

    @pytest.mark.asyncio
    async def test_get_operation(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreGetOperationConfig(project_id="proj", operation_id="op_123"),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(200, {"name": "op_123", "done": True})
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_operation"
        assert result["data"]["done"] is True

    @pytest.mark.asyncio
    async def test_operation_management(self, oauth_credentials):
        cases = [
            (
                FirestoreListOperationsConfig(project_id="proj", filter="done=false"),
                "list_operations",
            ),
            (
                FirestoreCancelOperationConfig(project_id="proj", operation_id="op_123"),
                "cancel_operation",
            ),
            (
                FirestoreDeleteOperationConfig(project_id="proj", operation_id="op_123"),
                "delete_operation",
            ),
            (
                FirestoreCustomApiCallConfig(
                    method="GET",
                    path="projects/proj/databases/(default)",
                    query_params='{"mask": "type"}',
                ),
                "custom_api_call",
            ),
        ]
        for cfg, action in cases:
            node = create_firestore_node(
                FirestoreNodeConfig(config=cfg, credentials=oauth_credentials)
            )
            mock_client = create_mock_client(200, {"name": action})
            with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
                result = await node.execute({})
            assert result["status"] == "success"
            assert result["action"] == action

    @pytest.mark.asyncio
    async def test_location_and_backup_operations(self, oauth_credentials):
        cases = [
            (
                FirestoreGetLocationConfig(project_id="proj", location_id="us-central1"),
                "get_location",
            ),
            (
                FirestoreListLocationsConfig(project_id="proj"),
                "list_locations",
            ),
            (
                FirestoreGetBackupConfig(
                    project_id="proj", location_id="us", backup_id="backup-1"
                ),
                "get_backup",
            ),
            (
                FirestoreListBackupsConfig(project_id="proj", location_id="us"),
                "list_backups",
            ),
            (
                FirestoreDeleteBackupConfig(
                    project_id="proj", location_id="us", backup_id="backup-1"
                ),
                "delete_backup",
            ),
        ]
        for cfg, action in cases:
            node = create_firestore_node(
                FirestoreNodeConfig(config=cfg, credentials=oauth_credentials)
            )
            mock_client = create_mock_client(200, {"name": action})
            with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
                result = await node.execute({})
            assert result["status"] == "success"
            assert result["action"] == action


# ============================================================================
# Error handling
# ============================================================================


class TestFirestoreErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreGetDocumentConfig(
                project_id="proj", collection_path="users", document_id="missing"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            404, {"error": {"message": "Document not found", "status": "NOT_FOUND"}}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = FirestoreNodeConfig(
            config=FirestoreListDatabasesConfig(project_id="proj"), credentials=None
        )
        node = create_firestore_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_service_account_auth(self):
        credentials = FirestoreServiceAccountCredential(
            client_email="svc@example.iam.gserviceaccount.com",
            private_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
        )
        config = FirestoreNodeConfig(
            config=FirestoreGetDocumentConfig(
                project_id="proj", collection_path="users", document_id="abc"
            ),
            credentials=credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"name": "projects/proj/databases/(default)/documents/users/abc"}
        )
        with patch(
            "nodes.firestore_node._exchange_service_account_access_token",
            return_value="svc_token",
        ), patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_firebase_id_token_refresh(self):
        """Firebase ID token refresh goes through ensure_fresh_oauth_token (persists to DB)."""
        credentials = FirestoreFirebaseIdTokenCredential(
            id_token="old_token",
            refresh_token="refresh_token",
            api_key="firebase_api_key",
            expires_at="2000-01-01T00:00:00Z",
        )
        config = FirestoreNodeConfig(
            config=FirestoreGetDocumentConfig(
                project_id="proj", collection_path="users", document_id="abc"
            ),
            credentials=credentials,
        )
        node = create_firestore_node(config)
        mock_client = create_mock_client(
            200, {"name": "projects/proj/databases/(default)/documents/users/abc"}
        )

        async def mock_ensure_fresh(*args, **kwargs):
            # Simulate persist-aware refresh: mutate the credential dict in place.
            kwargs["credential"]["id_token"] = "fresh_id_token"
            kwargs["credential"]["expires_at"] = "2099-01-01T00:00:00Z"
            return "fresh_id_token"

        with patch(
            "nodes.core.oauth_refresh.ensure_fresh_oauth_token",
            side_effect=mock_ensure_fresh,
        ), patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"


# ============================================================================
# Dynamic options
# ============================================================================


class TestFirestoreDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_database_options(self):
        with patch(
            "nodes.firestore_node._firestore_request",
            return_value={
                "status": "success",
                "data": {
                    "databases": [
                        {"name": "projects/proj/databases/(default)"},
                        {"name": "projects/proj/databases/analytics"},
                    ]
                },
            },
        ):
            result = await FirestoreNode.load_field_options(
                "database_id",
                {"access_token": "mock_token"},
                context={"project_id": "proj"},
            )
        assert "options" in result
        values = [o["value"] for o in result["options"]]
        assert "(default)" in values
        assert "analytics" in values

    @pytest.mark.asyncio
    async def test_load_database_options_search_filters(self):
        with patch(
            "nodes.firestore_node._firestore_request",
            return_value={
                "status": "success",
                "data": {
                    "databases": [
                        {"name": "projects/proj/databases/(default)"},
                        {"name": "projects/proj/databases/analytics"},
                    ]
                },
            },
        ):
            result = await FirestoreNode.load_field_options(
                "database_id",
                {"access_token": "mock_token"},
                context={"project_id": "proj"},
                search="analyt",
            )
        values = [o["value"] for o in result["options"]]
        assert values == ["analytics"]

    @pytest.mark.asyncio
    async def test_load_database_options_no_project(self):
        result = await FirestoreNode.load_field_options(
            "database_id",
            {"access_token": "mock_token"},
            context={},
        )
        assert result == {"options": [], "next_page_token": None}

    @pytest.mark.asyncio
    async def test_load_collection_path_options(self):
        captured = {}

        async def fake_request(token, method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = kwargs.get("json_body")
            return {
                "status": "success",
                "data": {"collectionIds": ["users", "orders", "audit_logs"]},
            }

        with patch("nodes.firestore_node._firestore_request", side_effect=fake_request):
            result = await FirestoreNode.load_field_options(
                "collection_path",
                {"access_token": "mock_token"},
                context={"project_id": "proj", "database_id": "(default)"},
            )
        # Hits the listCollectionIds endpoint under the chosen db root.
        assert captured["method"] == "POST"
        assert captured["path"].endswith(":listCollectionIds")
        assert "projects/proj/databases/(default)/documents" in captured["path"]
        values = [o["value"] for o in result["options"]]
        assert values == ["users", "orders", "audit_logs"]
        assert all(o["label"] == o["value"] for o in result["options"])

    @pytest.mark.asyncio
    async def test_load_collection_path_options_search_filters(self):
        with patch(
            "nodes.firestore_node._firestore_request",
            return_value={
                "status": "success",
                "data": {"collectionIds": ["users", "orders", "audit_logs"]},
            },
        ):
            result = await FirestoreNode.load_field_options(
                "collection_path",
                {"access_token": "mock_token"},
                context={"project_id": "proj", "database_id": "(default)"},
                search="aud",
            )
        values = [o["value"] for o in result["options"]]
        assert values == ["audit_logs"]

    @pytest.mark.asyncio
    async def test_load_collection_path_defaults_database(self):
        captured = {}

        async def fake_request(token, method, path, **kwargs):
            captured["path"] = path
            return {"status": "success", "data": {"collectionIds": ["users"]}}

        with patch("nodes.firestore_node._firestore_request", side_effect=fake_request):
            result = await FirestoreNode.load_field_options(
                "collection_path",
                {"access_token": "mock_token"},
                context={"project_id": "proj"},  # no database_id -> (default)
            )
        assert "projects/proj/databases/(default)/documents" in captured["path"]
        assert [o["value"] for o in result["options"]] == ["users"]

    @pytest.mark.asyncio
    async def test_load_collection_id_options(self):
        """The list-indexes collection-group field reuses the collection-ids list."""
        with patch(
            "nodes.firestore_node._firestore_request",
            return_value={
                "status": "success",
                "data": {"collectionIds": ["users", "orders"]},
            },
        ):
            result = await FirestoreNode.load_field_options(
                "collection_id",
                {"access_token": "mock_token"},
                context={"project_id": "proj", "database_id": "(default)"},
            )
        values = [o["value"] for o in result["options"]]
        assert values == ["users", "orders"]

    @pytest.mark.asyncio
    async def test_load_collection_options_no_credential(self):
        result = await FirestoreNode.load_field_options(
            "collection_path",
            {},
            context={"project_id": "proj", "database_id": "(default)"},
        )
        assert result == {"options": [], "next_page_token": None}

    @pytest.mark.asyncio
    async def test_load_unknown_field_returns_empty(self):
        result = await FirestoreNode.load_field_options(
            "document_id",
            {"access_token": "mock_token"},
            context={"project_id": "proj"},
        )
        assert result == {"options": [], "next_page_token": None}


# ============================================================================
# Poll-based trigger (on_document_changed)
# ============================================================================


def _doc(name: str, update_time: str) -> dict:
    """A Firestore document object from documents.list."""
    return {
        "name": f"projects/proj/databases/(default)/documents/users/{name}",
        "fields": {"name": {"stringValue": name}},
        "updateTime": update_time,
    }


def _install_node_state(node, initial=None):
    """Install a fake `_update_node_state` mirroring the base CAS contract:
    run the pure mutator against a copy of the current store, persist any
    non-None new_state, and return the store dict so tests can assert the
    persisted cursor (like ``test_snowflake_node_mock._run``)."""
    saved = dict(initial or {})

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(saved))
        if new_state is not None:
            saved.clear()
            saved.update(new_state)
        return result

    node._update_node_state = _update
    return saved


class TestFirestoreTriggerMock:
    def test_resolve_trigger_payload_runs_execute_for_poll_op(self):
        """The scheduled webhook is a wake-up signal — return None so execute() polls."""
        assert (
            FirestoreNode.resolve_trigger_payload(
                {"some": "payload"}, {"operation": "on_document_changed"}
            )
            is None
        )

    def test_resolve_trigger_payload_passthrough_for_normal_op(self):
        """Non-trigger ops never go through the poll path — payload passes through."""
        payload = {"some": "payload"}
        assert (
            FirestoreNode.resolve_trigger_payload(payload, {"operation": "get_document"})
            is payload
        )

    @pytest.mark.asyncio
    async def test_poll_baselines_on_first_run(self, oauth_credentials):
        """First poll (no cursor) BASELINES: it records the newest updateTime and
        emits NOTHING, so enabling the trigger never floods the workflow with the
        collection's existing backlog."""
        config = FirestoreNodeConfig(
            config=FirestoreOnDocumentChangedConfig(
                project_id="proj", collection_path="users"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        saved_state = _install_node_state(node)  # no prior cursor

        mock_client = create_mock_client(
            200,
            {"documents": [
                _doc("b", "2026-06-19T12:00:00.000000Z"),
                _doc("a", "2026-06-19T11:00:00.000000Z"),
            ]},
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["operation"] == "on_document_changed"
        assert result["new_count"] == 0
        assert result["items"] == []
        assert node.trigger_produced_no_event(result) is True
        # Cursor seeded to the newest updateTime and persisted, so the NEXT poll
        # only emits documents changed after this baseline.
        assert result["last_polled_at"] == "2026-06-19T12:00:00.000000Z"
        assert saved_state["last_polled_at"] == "2026-06-19T12:00:00.000000Z"

    @pytest.mark.asyncio
    async def test_poll_dedupes_already_seen_documents(self, oauth_credentials):
        """A second poll (seeded node-state cursor) only emits docs newer than
        the stored cursor; the boundary doc (== cursor) is not re-emitted."""
        config = FirestoreNodeConfig(
            config=FirestoreOnDocumentChangedConfig(
                project_id="proj", collection_path="users"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)

        # Cursor already at b's updateTime — only the newer doc "c" should emit.
        saved_state = _install_node_state(
            node, {"last_polled_at": "2026-06-19T12:00:00.000000Z"}
        )

        mock_client = create_mock_client(
            200,
            {"documents": [
                _doc("c", "2026-06-19T13:00:00.000000Z"),  # new
                _doc("b", "2026-06-19T12:00:00.000000Z"),  # already seen (== cursor)
                _doc("a", "2026-06-19T11:00:00.000000Z"),  # already seen (< cursor)
            ]},
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["new_count"] == 1
        names = [d["fields"]["name"]["stringValue"] for d in result["items"]]
        assert names == ["c"]
        assert result["last_polled_at"] == "2026-06-19T13:00:00.000000Z"
        assert saved_state["last_polled_at"] == "2026-06-19T13:00:00.000000Z"

    @pytest.mark.asyncio
    async def test_poll_no_new_documents_reports_no_event(self, oauth_credentials):
        """When nothing is newer than the cursor, emit nothing and signal no-event."""
        config = FirestoreNodeConfig(
            config=FirestoreOnDocumentChangedConfig(
                project_id="proj", collection_path="users"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)

        saved_state = _install_node_state(
            node, {"last_polled_at": "2026-06-19T13:00:00.000000Z"}
        )

        mock_client = create_mock_client(
            200, {"documents": [_doc("b", "2026-06-19T12:00:00.000000Z")]}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["new_count"] == 0
        assert result["items"] == []
        assert node.trigger_produced_no_event(result) is True
        # Cursor must not regress when nothing new appeared.
        assert saved_state["last_polled_at"] == "2026-06-19T13:00:00.000000Z"

    @pytest.mark.asyncio
    async def test_poll_null_cursor_stays_unbaselined(self, oauth_credentials):
        """A first poll where no document carries a usable updateTime must NOT
        persist a null cursor — doing so would make the next poll treat every
        doc as new and flood. It stays unbaselined (no write)."""
        config = FirestoreNodeConfig(
            config=FirestoreOnDocumentChangedConfig(
                project_id="proj", collection_path="users"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        saved_state = _install_node_state(node)  # no prior cursor

        mock_client = create_mock_client(
            200,
            {"documents": [
                {"name": "projects/proj/databases/(default)/documents/users/x",
                 "fields": {}},  # no updateTime / createTime
            ]},
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["new_count"] == 0
        assert result["items"] == []
        assert result["last_polled_at"] is None
        # Nothing persisted → next poll with real timestamps baselines properly.
        assert saved_state == {}

    @pytest.mark.asyncio
    async def test_poll_baseline_then_emits_new_docs_on_second_run(self, oauth_credentials):
        """End-to-end over a single persisted store: run 1 baselines (emits
        nothing), run 2 emits only the document added after the baseline."""
        config = FirestoreNodeConfig(
            config=FirestoreOnDocumentChangedConfig(
                project_id="proj", collection_path="users"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        saved_state = _install_node_state(node)  # shared store across both runs

        first_client = create_mock_client(
            200,
            {"documents": [
                _doc("b", "2026-06-19T12:00:00.000000Z"),
                _doc("a", "2026-06-19T11:00:00.000000Z"),
            ]},
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=first_client):
            first = await node.execute({})
        assert first["new_count"] == 0
        assert saved_state["last_polled_at"] == "2026-06-19T12:00:00.000000Z"

        # Second poll: a newer doc "c" appears; only it should emit.
        second_client = create_mock_client(
            200,
            {"documents": [
                _doc("c", "2026-06-19T13:00:00.000000Z"),
                _doc("b", "2026-06-19T12:00:00.000000Z"),
            ]},
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=second_client):
            second = await node.execute({})
        assert second["new_count"] == 1
        names = [d["fields"]["name"]["stringValue"] for d in second["items"]]
        assert names == ["c"]
        assert saved_state["last_polled_at"] == "2026-06-19T13:00:00.000000Z"

    @pytest.mark.asyncio
    async def test_poll_nested_collection_uses_exact_parent_path(self, oauth_credentials):
        config = FirestoreNodeConfig(
            config=FirestoreOnDocumentChangedConfig(
                project_id="proj", collection_path="users/abc/orders"
            ),
            credentials=oauth_credentials,
        )
        node = create_firestore_node(config)
        _install_node_state(node)

        mock_client, captured = create_capturing_mock_client(
            200, {"documents": []}
        )
        with patch("nodes.firestore_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert (
            captured["kwargs"]["url"]
            == "https://firestore.googleapis.com/v1/projects/proj/databases/(default)/documents/users/abc/orders"
        )
        assert captured["kwargs"]["params"]["orderBy"] == "updateTime desc, __name__ desc"

    @pytest.mark.asyncio
    async def test_load_field_value_provisions_webhook_and_schedule(self):
        """webhook_url provisioning (family loader → reconcile_node) returns
        the webhook + schedule operational values."""
        import uuid as uuid_module
        from unittest.mock import MagicMock

        async def fake_get_or_create_webhook(*args, **kwargs):
            return {"webhook_id": "wh_1", "webhook_url": "https://hook.example/abc"}

        async def fake_create_schedule(**kwargs):
            return {"id": "sched_1", "next_run": "2026-06-19T12:05:00Z"}

        async def fake_delete_schedules(*args, **kwargs):
            return {"deleted": 0}

        async def load_owner_nodes(p, wf_uuid, include_nodes=True):
            return "owner-1", []

        from utils.webhook_manager import WebhookManager
        from utils import cron_scheduler_client

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch.object(
            WebhookManager, "get_or_create_webhook", side_effect=fake_get_or_create_webhook
        ), patch(
            "utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes,
        ), patch.object(
            WebhookManager, "persist_registration_state", AsyncMock(),
        ), patch.object(
            WebhookManager, "merge_node_config_patch", AsyncMock(),
        ), patch.object(
            cron_scheduler_client, "is_cron_scheduler_enabled", return_value=True
        ), patch.object(
            cron_scheduler_client, "create_schedule", side_effect=fake_create_schedule
        ), patch.object(
            cron_scheduler_client, "delete_schedules_for_nodes", side_effect=fake_delete_schedules
        ), patch(
            "utils.async_helpers.spawn",
            side_effect=lambda coro, name=None: coro.close(),
        ), patch(
            "utils.redis_client.get_shared_redis", lambda: None,
        ):
            result = await FirestoreNode.load_field_value(
                "webhook_url",
                user_id="user_1",
                workflow_id=str(uuid_module.uuid4()),
                node_id="node_1",
                pool=pool,
                context={"operation": "on_document_changed",
                         "project_id": "proj-1",
                         "collection_path": "users",
                         "schedule": {"frequency": "minutes", "interval": 5}},
            )

        values = result["values"]
        assert values["webhook_id"] == "wh_1"
        assert values["webhook_url"] == "https://hook.example/abc"
        assert values["schedule_id"] == "sched_1"
        assert values["next_run"] == "2026-06-19T12:05:00Z"
        assert values["interval_ms"] == 5 * 60 * 1000
        assert values["is_active"] is True
        assert values["trigger_registered"] is True

    @pytest.mark.asyncio
    async def test_load_field_value_non_webhook_field_returns_none(self):
        result = await FirestoreNode.load_field_value(
            "schedule",
            user_id="user_1",
            workflow_id="wf_1",
            node_id="node_1",
            pool=Mock(),
            context={},
        )
        assert result == {"value": None}
