"""
Comprehensive mock tests for PostgreSQL Node - ALL 47 Operations.

Tests all PostgreSQL node operations using mocked asyncpg connections.
Organized by operation category for easy navigation.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from nodes.postgres_node import (
    PostgresNode,
    PostgresNodeConfig,
    PostgresConnectionStringCredential,
    PostgresCredentialsCredential,
    # Query & Execute Operations
    PostgresQueryConfig,
    PostgresExecuteConfig,
    PostgresExecuteManyConfig,
    PostgresQueryCursorConfig,
    PostgresCopyToTableConfig,
    PostgresCopyFromTableConfig,
    # Table Operations
    PostgresListTablesConfig,
    PostgresListColumnsConfig,
    PostgresGetTableInfoConfig,
    PostgresCreateTableConfig,
    PostgresDropTableConfig,
    PostgresTruncateTableConfig,
    # Schema Operations
    PostgresListSchemasConfig,
    PostgresCreateSchemaConfig,
    PostgresDropSchemaConfig,
    # Database Operations
    PostgresListDatabasesConfig,
    # Index Operations
    PostgresListIndexesConfig,
    PostgresCreateIndexConfig,
    PostgresDropIndexConfig,
    # View Operations
    PostgresListViewsConfig,
    PostgresCreateViewConfig,
    PostgresDropViewConfig,
    # Sequence Operations
    PostgresListSequencesConfig,
    PostgresGetNextSequenceValueConfig,
    PostgresGetCurrentSequenceValueConfig,
    PostgresSetSequenceValueConfig,
    # Function Operations
    PostgresListFunctionsConfig,
    PostgresCallFunctionConfig,
    # Constraint Operations
    PostgresListConstraintsConfig,
    # Trigger Operations
    PostgresListTriggersConfig,
    # Extension Operations
    PostgresListExtensionsConfig,
    PostgresCreateExtensionConfig,
    # Table Management
    # User/Role Operations
    PostgresListUsersConfig,
    PostgresListRolesConfig,
    # Performance Operations
    PostgresExplainQueryConfig,
    PostgresVacuumTableConfig,
    PostgresAnalyzeTableConfig,
    # Transaction Operations
    PostgresBeginTransactionConfig,
    PostgresCommitTransactionConfig,
    PostgresRollbackTransactionConfig,
)


@pytest.fixture(autouse=True)
def allow_mock_private_database(monkeypatch):
    """Mock credentials intentionally point at localhost."""
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")


class TestPostgresNodeMock:
    """Comprehensive mock tests for all PostgreSQL node operations."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock asyncpg connection."""
        conn = AsyncMock()
        conn.fetch = AsyncMock()
        conn.fetchrow = AsyncMock()
        conn.fetchval = AsyncMock()
        conn.execute = AsyncMock(return_value="SELECT 1")
        conn.executemany = AsyncMock()
        conn.cursor = AsyncMock()
        conn.copy_records_to_table = AsyncMock()
        conn.transaction = MagicMock()
        conn.close = AsyncMock()
        return conn

    @pytest.fixture
    def connection_string_credential(self):
        """Create connection string credential."""
        return PostgresConnectionStringCredential(
            connection_string="postgresql://user:password@localhost:5432/testdb"
        )

    @pytest.fixture
    def individual_credentials(self):
        """Create individual credentials."""
        return PostgresCredentialsCredential(
            host="localhost",
            port=5432,
            database="testdb",
            user="testuser",
            password="testpass"
        )

    def create_node(self, config, credential):
        """Helper to create a PostgresNode."""
        node_config = PostgresNodeConfig(config=config, credentials=credential)
        return PostgresNode(
            node_id="test-node",
            node_type="automation-postgres",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow"
        )

    # =========================================================================
    # Query & Execute Operations Tests (6 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_query_operation(self, mock_connection, connection_string_credential):
        """Test query operation."""
        # Setup mock
        mock_connection.fetch.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ]

        config = PostgresQueryConfig(
            query="SELECT * FROM users",
            params=None,
            limit=1000
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "run_select_query"
        assert result["data"]["row_count"] == 2
        assert len(result["data"]["rows"]) == 2
        assert "timing_ms" in result

    @pytest.mark.asyncio
    async def test_execute_operation(self, mock_connection, connection_string_credential):
        """Test execute operation."""
        mock_connection.execute.return_value = "INSERT 0 5"

        config = PostgresExecuteConfig(
            statement="INSERT INTO users (name) VALUES ($1)",
            params=["Charlie"],
            return_rows=False
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_sql_statement"
        assert result["data"]["affected_rows"] == 5

    @pytest.mark.asyncio
    async def test_execute_many_operation(self, mock_connection, connection_string_credential):
        """Test execute_many operation."""
        config = PostgresExecuteManyConfig(
            statement="INSERT INTO users (name, email) VALUES ($1, $2)",
            params_list=[["Alice", "alice@example.com"], ["Bob", "bob@example.com"]]
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "execute_batch_statements"
        assert result["data"]["executed_count"] == 2

    @pytest.mark.asyncio
    async def test_query_cursor_operation(self, mock_connection, connection_string_credential):
        """Test query_cursor operation."""
        # Mock cursor
        mock_cursor = AsyncMock()
        mock_cursor.fetch = AsyncMock(side_effect=[
            [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            []  # No more rows
        ])
        mock_connection.cursor.return_value = mock_cursor

        # Mock transaction
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=mock_transaction)
        mock_transaction.__aexit__ = AsyncMock()
        mock_transaction.start = AsyncMock()
        mock_connection.transaction.return_value = mock_transaction

        config = PostgresQueryCursorConfig(
            query="SELECT * FROM large_table",
            params=None,
            batch_size=1000,
            max_rows=10000
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "run_query_with_cursor"
        assert result["data"]["row_count"] == 2

    @pytest.mark.asyncio
    async def test_copy_to_table_operation(self, mock_connection, connection_string_credential):
        """Test copy_to_table operation."""
        config = PostgresCopyToTableConfig(
            table_name="users",
            columns=["name", "email"],
            data=[["Alice", "alice@test.com"], ["Bob", "bob@test.com"]],
            schema_name="public"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "copy_data_to_table"
        assert result["data"]["rows_imported"] == 2

    @pytest.mark.asyncio
    async def test_copy_from_table_operation(self, mock_connection, connection_string_credential):
        """Test copy_from_table operation."""
        mock_connection.fetch.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ]

        config = PostgresCopyFromTableConfig(
            table_name="users",
            columns=["id", "name"],
            where_clause="id > 0",
            limit=100,
            schema_name="public"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "copy_data_from_table"
        assert result["data"]["row_count"] == 2

    # =========================================================================
    # Table Operations Tests (6 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_tables_operation(self, mock_connection, connection_string_credential):
        """Test list_tables operation."""
        mock_connection.fetch.return_value = [
            {"table_name": "users", "table_type": "BASE TABLE"},
            {"table_name": "orders", "table_type": "BASE TABLE"}
        ]

        config = PostgresListTablesConfig(schema_name="public", include_views=False)
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_schema_tables"
        assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_list_columns_operation(self, mock_connection, connection_string_credential):
        """Test list_columns operation."""
        mock_connection.fetch.return_value = [
            {
                "column_name": "id",
                "data_type": "integer",
                "character_maximum_length": None,
                "numeric_precision": 32,
                "numeric_scale": 0,
                "is_nullable": "NO",
                "column_default": "nextval('users_id_seq'::regclass)",
                "ordinal_position": 1
            }
        ]

        config = PostgresListColumnsConfig(table_name="users", schema_name="public")
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_table_columns"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_get_table_info_operation(self, mock_connection, connection_string_credential):
        """Test get_table_info operation."""
        mock_connection.fetch.side_effect = [
            [{"column_name": "id", "data_type": "integer", "is_nullable": "NO", "column_default": None}],  # columns
            [{"column_name": "id"}],  # primary key
            [],  # foreign keys
            []   # indexes
        ]
        mock_connection.fetchrow.return_value = {"estimate": 1000}

        config = PostgresGetTableInfoConfig(table_name="users", schema_name="public")
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_table_info"
        assert "columns" in result["data"]

    @pytest.mark.asyncio
    async def test_create_table_operation(self, mock_connection, connection_string_credential):
        """Test create_table operation."""
        config = PostgresCreateTableConfig(
            table_name="test_table",
            columns="id SERIAL PRIMARY KEY, name TEXT NOT NULL",
            schema_name="public",
            if_not_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_table"
        assert result["data"]["created"] is True

    @pytest.mark.asyncio
    async def test_drop_table_operation(self, mock_connection, connection_string_credential):
        """Test drop_table operation."""
        config = PostgresDropTableConfig(
            table_name="test_table",
            schema_name="public",
            cascade=False,
            if_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "drop_table"
        assert result["data"]["dropped"] is True

    @pytest.mark.asyncio
    async def test_truncate_table_operation(self, mock_connection, connection_string_credential):
        """Test truncate_table operation."""
        config = PostgresTruncateTableConfig(
            table_name="test_table",
            schema_name="public",
            restart_identity=True,
            cascade=False
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "truncate_table"
        assert result["data"]["truncated"] is True

    # =========================================================================
    # Schema Operations Tests (3 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_schemas_operation(self, mock_connection, connection_string_credential):
        """Test list_schemas operation."""
        mock_connection.fetch.return_value = [
            {"schema_name": "public"},
            {"schema_name": "custom_schema"}
        ]

        config = PostgresListSchemasConfig()
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_schemas"
        assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_create_schema_operation(self, mock_connection, connection_string_credential):
        """Test create_schema operation."""
        config = PostgresCreateSchemaConfig(
            schema_name="new_schema",
            if_not_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_schema"
        assert result["data"]["created"] is True

    @pytest.mark.asyncio
    async def test_drop_schema_operation(self, mock_connection, connection_string_credential):
        """Test drop_schema operation."""
        config = PostgresDropSchemaConfig(
            schema_name="old_schema",
            cascade=True,
            if_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "drop_schema"
        assert result["data"]["dropped"] is True

    # =========================================================================
    # Database Operations Tests (1 operation)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_databases_operation(self, mock_connection, connection_string_credential):
        """Test list_databases operation."""
        mock_connection.fetch.return_value = [
            {"datname": "postgres", "owner": "postgres", "size": "8 MB"},
            {"datname": "testdb", "owner": "testuser", "size": "12 MB"}
        ]

        config = PostgresListDatabasesConfig()
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_databases"
        assert result["data"]["count"] == 2

    # =========================================================================
    # Index Operations Tests (3 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_indexes_operation(self, mock_connection, connection_string_credential):
        """Test list_indexes operation."""
        mock_connection.fetch.return_value = [
            {"indexname": "users_pkey", "tablename": "users", "indexdef": "CREATE UNIQUE INDEX..."}
        ]

        config = PostgresListIndexesConfig(schema_name="public", table_name="users")
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_schema_indexes"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_create_index_operation(self, mock_connection, connection_string_credential):
        """Test create_index operation."""
        config = PostgresCreateIndexConfig(
            index_name="idx_users_email",
            table_name="users",
            columns=["email"],
            schema_name="public",
            unique=True,
            if_not_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_index"
        assert result["data"]["created"] is True

    @pytest.mark.asyncio
    async def test_drop_index_operation(self, mock_connection, connection_string_credential):
        """Test drop_index operation."""
        config = PostgresDropIndexConfig(
            index_name="idx_users_email",
            schema_name="public",
            if_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "drop_index"
        assert result["data"]["dropped"] is True

    # =========================================================================
    # View Operations Tests (3 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_views_operation(self, mock_connection, connection_string_credential):
        """Test list_views operation."""
        mock_connection.fetch.return_value = [
            {"table_name": "active_users", "view_definition": "SELECT..."}
        ]

        config = PostgresListViewsConfig(schema_name="public")
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_schema_views"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_create_view_operation(self, mock_connection, connection_string_credential):
        """Test create_view operation."""
        config = PostgresCreateViewConfig(
            view_name="active_users",
            query="SELECT * FROM users WHERE active = true",
            schema_name="public",
            or_replace=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_view"
        assert result["data"]["created"] is True

    @pytest.mark.asyncio
    async def test_drop_view_operation(self, mock_connection, connection_string_credential):
        """Test drop_view operation."""
        config = PostgresDropViewConfig(
            view_name="active_users",
            schema_name="public",
            if_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "drop_view"
        assert result["data"]["dropped"] is True

    # =========================================================================
    # Sequence Operations Tests (4 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_sequences_operation(self, mock_connection, connection_string_credential):
        """Test list_sequences operation."""
        mock_connection.fetch.return_value = [
            {"sequence_name": "users_id_seq"},
            {"sequence_name": "orders_id_seq"}
        ]

        config = PostgresListSequencesConfig(schema_name="public")
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_schema_sequences"
        assert result["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_get_next_sequence_value_operation(self, mock_connection, connection_string_credential):
        """Test get_next_sequence_value operation."""
        mock_connection.fetchval.return_value = 42

        config = PostgresGetNextSequenceValueConfig(
            sequence_name="users_id_seq",
            schema_name="public"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_sequence_next_value"
        assert result["data"]["value"] == 42

    @pytest.mark.asyncio
    async def test_get_current_sequence_value_operation(self, mock_connection, connection_string_credential):
        """Test get_current_sequence_value operation."""
        mock_connection.fetchval.return_value = 41

        config = PostgresGetCurrentSequenceValueConfig(
            sequence_name="users_id_seq",
            schema_name="public"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_sequence_current_value"
        assert result["data"]["value"] == 41

    @pytest.mark.asyncio
    async def test_set_sequence_value_operation(self, mock_connection, connection_string_credential):
        """Test set_sequence_value operation."""
        config = PostgresSetSequenceValueConfig(
            sequence_name="users_id_seq",
            value=100,
            schema_name="public",
            is_called=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "set_sequence_value"
        assert result["data"]["value"] == 100

    # =========================================================================
    # Function Operations Tests (2 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_functions_operation(self, mock_connection, connection_string_credential):
        """Test list_functions operation."""
        mock_connection.fetch.return_value = [
            {"routine_name": "calculate_total", "routine_type": "FUNCTION"}
        ]

        config = PostgresListFunctionsConfig(schema_name="public")
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_schema_functions"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_call_function_operation(self, mock_connection, connection_string_credential):
        """Test call_function operation."""
        mock_connection.fetch.return_value = [{"result": 150}]

        config = PostgresCallFunctionConfig(
            function_name="calculate_total",
            params=[10, 15],
            schema_name="public"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "call_database_function"
        assert result["data"]["row_count"] == 1

    # =========================================================================
    # Constraint, Trigger, Extension Operations Tests (4 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_constraints_operation(self, mock_connection, connection_string_credential):
        """Test list_constraints operation."""
        mock_connection.fetch.return_value = [
            {"constraint_name": "users_pkey", "constraint_type": "PRIMARY KEY"}
        ]

        config = PostgresListConstraintsConfig(
            table_name="users",
            schema_name="public"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_table_constraints"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_list_triggers_operation(self, mock_connection, connection_string_credential):
        """Test list_triggers operation."""
        mock_connection.fetch.return_value = [
            {"trigger_name": "update_timestamp", "event_object_table": "users", "action_statement": "..."}
        ]

        config = PostgresListTriggersConfig(
            schema_name="public",
            table_name="users"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_schema_triggers"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_list_extensions_operation(self, mock_connection, connection_string_credential):
        """Test list_extensions operation."""
        mock_connection.fetch.return_value = [
            {"extname": "uuid-ossp", "extversion": "1.1", "extrelocatable": True}
        ]

        config = PostgresListExtensionsConfig()
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_extensions"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_create_extension_operation(self, mock_connection, connection_string_credential):
        """Test create_extension operation."""
        config = PostgresCreateExtensionConfig(
            extension_name="uuid-ossp",
            schema_name="public",
            if_not_exists=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "install_extension"
        assert result["data"]["created"] is True

    # =========================================================================
    # User/Role Operations Tests (2 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_users_operation(self, mock_connection, connection_string_credential):
        """Test list_users operation."""
        mock_connection.fetch.return_value = [
            {"usename": "testuser", "usesuper": False, "usecreatedb": True, "usecreaterole": False}
        ]

        config = PostgresListUsersConfig()
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_database_users"
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_list_roles_operation(self, mock_connection, connection_string_credential):
        """Test list_roles operation."""
        mock_connection.fetch.return_value = [
            {"rolname": "admin", "rolsuper": True, "rolcreatedb": True, "rolcreaterole": True}
        ]

        config = PostgresListRolesConfig()
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_database_roles"
        assert result["data"]["count"] == 1

    # =========================================================================
    # Performance/Maintenance Operations Tests (3 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_explain_query_operation(self, mock_connection, connection_string_credential):
        """Test explain_query operation."""
        mock_connection.fetch.return_value = [
            ("Seq Scan on users  (cost=0.00..35.50 rows=2550 width=36)",),
            ("  Filter: (active = true)",)
        ]

        config = PostgresExplainQueryConfig(
            query="SELECT * FROM users WHERE active = true",
            analyze=False,
            verbose=False
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "explain_query_plan"
        assert len(result["data"]["plan"]) == 2

    @pytest.mark.asyncio
    async def test_vacuum_table_operation(self, mock_connection, connection_string_credential):
        """Test vacuum_table operation."""
        config = PostgresVacuumTableConfig(
            table_name="users",
            schema_name="public",
            full=False,
            analyze=True
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "vacuum_table"
        assert result["data"]["vacuumed"] is True

    @pytest.mark.asyncio
    async def test_analyze_table_operation(self, mock_connection, connection_string_credential):
        """Test analyze_table operation."""
        config = PostgresAnalyzeTableConfig(
            table_name="users",
            schema_name="public"
        )
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "analyze_table_statistics"
        assert result["data"]["analyzed"] is True

    # =========================================================================
    # Transaction Operations Tests (3 operations)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_begin_transaction_operation(self, connection_string_credential):
        """Test begin_transaction operation - should return error."""
        config = PostgresBeginTransactionConfig(isolation_level=None)
        node = self.create_node(config, connection_string_credential)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "begin_transaction"
        assert "not supported" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_commit_transaction_operation(self, connection_string_credential):
        """Test commit_transaction operation - should return error."""
        config = PostgresCommitTransactionConfig()
        node = self.create_node(config, connection_string_credential)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "commit_transaction"
        assert "not supported" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rollback_transaction_operation(self, connection_string_credential):
        """Test rollback_transaction operation - should return error."""
        config = PostgresRollbackTransactionConfig()
        node = self.create_node(config, connection_string_credential)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "rollback_transaction"
        assert "not supported" in result["error"].lower()

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_connection_error_handling(self, connection_string_credential):
        """Test error handling when connection fails."""
        config = PostgresQueryConfig(query="SELECT 1", params=None, limit=1000)
        node = self.create_node(config, connection_string_credential)

        with patch('nodes.postgres_node.asyncpg.connect', side_effect=Exception("Connection failed")):
            result = await node.execute({})

        assert result["status"] == "error"
        assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_individual_credentials_connection(self, mock_connection, individual_credentials):
        """Test connection with individual credentials."""
        mock_connection.fetch.return_value = [{"result": 1}]

        config = PostgresQueryConfig(query="SELECT 1 as result", params=None, limit=1000)
        node = self.create_node(config, individual_credentials)

        with patch('nodes.postgres_node.asyncpg.connect', return_value=mock_connection):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "run_select_query"
