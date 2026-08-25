"""
Mock tests for the Snowflake REST API v2 node.

Exercises every operation with mocked HTTP responses (no live API calls):
- SQL: run statement, get statement, cancel statement
- Databases: list, create, fetch, delete
- Schemas / Tables: list schemas, list tables, fetch table
- Warehouses: list, create, resume, suspend, abort
- Tasks: list, create, execute, resume, suspend, history
- Users / Roles: list users, create user, delete user, list roles
- Stages: list stages
- Error handling: API errors, missing credentials
- Dynamic options: warehouse / database / role dropdowns
- Host normalization helper
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock

import typing

from nodes.snowflake_node import (
    SnowflakeNode,
    SnowflakeNodeConfig,
    SnowflakeConfig,
    SNOWFLAKE_OPERATION_CONFIGS,
    SNOWFLAKE_OPERATION_HANDLERS,
    SnowflakePatCredential,
    _account_host,
    SnowflakeRunStatementConfig,
    SnowflakeGetStatementConfig,
    SnowflakeCancelStatementConfig,
    SnowflakeListDatabasesConfig,
    SnowflakeCreateDatabaseConfig,
    SnowflakeFetchDatabaseConfig,
    SnowflakeDeleteDatabaseConfig,
    SnowflakeListSchemasConfig,
    SnowflakeListTablesConfig,
    SnowflakeFetchTableConfig,
    SnowflakeListWarehousesConfig,
    SnowflakeCreateWarehouseConfig,
    SnowflakeResumeWarehouseConfig,
    SnowflakeSuspendWarehouseConfig,
    SnowflakeAbortWarehouseConfig,
    SnowflakeListTasksConfig,
    SnowflakeCreateTaskConfig,
    SnowflakeExecuteTaskConfig,
    SnowflakeResumeTaskConfig,
    SnowflakeSuspendTaskConfig,
    SnowflakeTaskHistoryConfig,
    SnowflakeListUsersConfig,
    SnowflakeCreateUserConfig,
    SnowflakeDeleteUserConfig,
    SnowflakeListRolesConfig,
    SnowflakeListStagesConfig,
    SnowflakeOnQueryResultsConfig,
)


@pytest.fixture
def credentials():
    return SnowflakePatCredential(
        account_identifier="myorg-myaccount", token="pat_test_secret_12345"
    )


def create_snowflake_node(config):
    return SnowflakeNode(
        node_id="test-snowflake-node",
        node_type="automation-snowflake",
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


async def _run(config_obj, creds, status_code=200, json_data=None, node_state=None):
    """Build the node, patch httpx, run execute, return the result.

    The poll trigger persists its cursor high-water-mark via node state
    (workflow_node_state), so tests inject the prior cursor through `node_state`
    and read what execute() saved back from `result["__saved_state__"]`.
    """
    config = SnowflakeNodeConfig(config=config_obj, credentials=creds)
    node = create_snowflake_node(config)
    saved: dict = {}

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(node_state or {}))
        if new_state is not None:
            saved.clear()
            saved.update(new_state)
        return result

    node._update_node_state = _update

    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.snowflake_node.httpx.AsyncClient", return_value=mock_client):
        result = await node.execute({})
    if isinstance(result, dict):
        result["__saved_state__"] = saved
    return result


# ============================================================================
# Helper
# ============================================================================


class TestSnowflakeHostHelper:
    def test_bare_identifier(self):
        assert _account_host("myorg-myacct") == "https://myorg-myacct.snowflakecomputing.com"

    def test_full_host(self):
        assert (
            _account_host("https://myorg-myacct.snowflakecomputing.com/")
            == "https://myorg-myacct.snowflakecomputing.com"
        )

    @pytest.mark.parametrize(
        "identifier",
        [
            "xy12345.us-east-2.aws",
            "https://xy12345.us-east-2.aws.snowflakecomputing.com/",
        ],
    )
    def test_regional_identifier(self, identifier):
        assert (
            _account_host(identifier)
            == "https://xy12345.us-east-2.aws.snowflakecomputing.com"
        )


# ============================================================================
# SQL
# ============================================================================


class TestSnowflakeSqlMock:
    async def test_run_statement(self, credentials):
        result = await _run(
            SnowflakeRunStatementConfig(
                statement="SELECT 1", warehouse="WH", database="DB", role="ANALYST"
            ),
            credentials,
            200,
            {"statementHandle": "h1", "data": [["1"]]},
        )
        assert result["status"] == "success"
        assert result["action"] == "run_statement"
        assert result["data"]["statementHandle"] == "h1"

    async def test_run_statement_async(self, credentials):
        result = await _run(
            SnowflakeRunStatementConfig(statement="SELECT 1", run_async="true"),
            credentials,
            202,
            {"statementHandle": "h2"},
        )
        assert result["status"] == "success"
        assert result["status_code"] == 202

    async def test_get_statement(self, credentials):
        result = await _run(
            SnowflakeGetStatementConfig(statement_handle="h1", partition="0"),
            credentials,
            200,
            {"data": [["a"], ["b"]]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_statement"

    async def test_cancel_statement(self, credentials):
        result = await _run(
            SnowflakeCancelStatementConfig(statement_handle="h1"),
            credentials,
            200,
            {"message": "cancelled"},
        )
        assert result["status"] == "success"
        assert result["action"] == "cancel_statement"


# ============================================================================
# Databases
# ============================================================================


class TestSnowflakeDatabasesMock:
    async def test_list_databases(self, credentials):
        result = await _run(
            SnowflakeListDatabasesConfig(like="%"),
            credentials,
            200,
            [{"name": "DB1"}, {"name": "DB2"}],
        )
        assert result["status"] == "success"
        assert result["action"] == "list_databases"
        assert len(result["data"]) == 2

    async def test_create_database(self, credentials):
        result = await _run(
            SnowflakeCreateDatabaseConfig(name="NEW_DB", comment="created"),
            credentials,
            200,
            {"status": "Database NEW_DB successfully created."},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_database"

    async def test_fetch_database(self, credentials):
        result = await _run(
            SnowflakeFetchDatabaseConfig(name="DB1"),
            credentials,
            200,
            {"name": "DB1", "owner": "SYSADMIN"},
        )
        assert result["status"] == "success"
        assert result["action"] == "fetch_database"
        assert result["data"]["name"] == "DB1"

    async def test_delete_database(self, credentials):
        result = await _run(
            SnowflakeDeleteDatabaseConfig(name="DB1"), credentials, 200, {"status": "dropped"}
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_database"


# ============================================================================
# Schemas / Tables
# ============================================================================


class TestSnowflakeSchemasTablesMock:
    async def test_list_schemas(self, credentials):
        result = await _run(
            SnowflakeListSchemasConfig(database="DB1"),
            credentials,
            200,
            [{"name": "PUBLIC"}],
        )
        assert result["status"] == "success"
        assert result["action"] == "list_schemas"

    async def test_list_tables(self, credentials):
        result = await _run(
            SnowflakeListTablesConfig(database="DB1", schema_name="PUBLIC"),
            credentials,
            200,
            [{"name": "ORDERS"}, {"name": "USERS"}],
        )
        assert result["status"] == "success"
        assert result["action"] == "list_tables"
        assert len(result["data"]) == 2

    async def test_fetch_table(self, credentials):
        result = await _run(
            SnowflakeFetchTableConfig(database="DB1", schema_name="PUBLIC", name="ORDERS"),
            credentials,
            200,
            {"name": "ORDERS", "columns": []},
        )
        assert result["status"] == "success"
        assert result["action"] == "fetch_table"
        assert result["data"]["name"] == "ORDERS"


# ============================================================================
# Warehouses
# ============================================================================


class TestSnowflakeWarehousesMock:
    async def test_list_warehouses(self, credentials):
        result = await _run(
            SnowflakeListWarehousesConfig(), credentials, 200, [{"name": "WH"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_warehouses"

    async def test_create_warehouse(self, credentials):
        result = await _run(
            SnowflakeCreateWarehouseConfig(
                name="WH2", warehouse_size="SMALL", auto_suspend="60"
            ),
            credentials,
            200,
            {"status": "created"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_warehouse"

    async def test_resume_warehouse(self, credentials):
        result = await _run(
            SnowflakeResumeWarehouseConfig(name="WH"), credentials, 200, {"status": "resumed"}
        )
        assert result["status"] == "success"
        assert result["action"] == "resume_warehouse"

    async def test_suspend_warehouse(self, credentials):
        result = await _run(
            SnowflakeSuspendWarehouseConfig(name="WH"),
            credentials,
            200,
            {"status": "suspended"},
        )
        assert result["status"] == "success"
        assert result["action"] == "suspend_warehouse"

    async def test_abort_warehouse(self, credentials):
        result = await _run(
            SnowflakeAbortWarehouseConfig(name="WH"), credentials, 200, {"status": "aborted"}
        )
        assert result["status"] == "success"
        assert result["action"] == "abort_warehouse"


# ============================================================================
# Tasks
# ============================================================================


class TestSnowflakeTasksMock:
    async def test_list_tasks(self, credentials):
        result = await _run(
            SnowflakeListTasksConfig(database="DB1", schema_name="PUBLIC", root_only="true"),
            credentials,
            200,
            [{"name": "DAILY_TASK"}],
        )
        assert result["status"] == "success"
        assert result["action"] == "list_tasks"

    async def test_create_task(self, credentials):
        result = await _run(
            SnowflakeCreateTaskConfig(
                database="DB1",
                schema_name="PUBLIC",
                name="T1",
                definition="INSERT INTO log VALUES (1)",
                warehouse="WH",
                task_schedule="5 MINUTE",
            ),
            credentials,
            200,
            {"status": "created"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_task"

    async def test_execute_task(self, credentials):
        result = await _run(
            SnowflakeExecuteTaskConfig(database="DB1", schema_name="PUBLIC", name="T1"),
            credentials,
            200,
            {"status": "executed"},
        )
        assert result["status"] == "success"
        assert result["action"] == "execute_task"

    async def test_resume_task(self, credentials):
        result = await _run(
            SnowflakeResumeTaskConfig(database="DB1", schema_name="PUBLIC", name="T1"),
            credentials,
            200,
            {"status": "resumed"},
        )
        assert result["status"] == "success"
        assert result["action"] == "resume_task"

    async def test_suspend_task(self, credentials):
        result = await _run(
            SnowflakeSuspendTaskConfig(database="DB1", schema_name="PUBLIC", name="T1"),
            credentials,
            200,
            {"status": "suspended"},
        )
        assert result["status"] == "success"
        assert result["action"] == "suspend_task"

    async def test_task_history(self, credentials):
        result = await _run(
            SnowflakeTaskHistoryConfig(database="DB1", schema_name="PUBLIC", name="T1"),
            credentials,
            200,
            [{"runId": 1, "state": "SUCCEEDED"}],
        )
        assert result["status"] == "success"
        assert result["action"] == "task_history"


# ============================================================================
# Users / Roles
# ============================================================================


class TestSnowflakeUsersRolesMock:
    async def test_list_users(self, credentials):
        result = await _run(
            SnowflakeListUsersConfig(), credentials, 200, [{"name": "ALICE"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_users"

    async def test_create_user(self, credentials):
        result = await _run(
            SnowflakeCreateUserConfig(
                name="BOB", email="bob@example.com", default_role="ANALYST"
            ),
            credentials,
            200,
            {"status": "created"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_user"

    async def test_delete_user(self, credentials):
        result = await _run(
            SnowflakeDeleteUserConfig(name="BOB"), credentials, 200, {"status": "dropped"}
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_user"

    async def test_list_roles(self, credentials):
        result = await _run(
            SnowflakeListRolesConfig(), credentials, 200, [{"name": "ANALYST"}]
        )
        assert result["status"] == "success"
        assert result["action"] == "list_roles"


# ============================================================================
# Stages
# ============================================================================


class TestSnowflakeStagesMock:
    async def test_list_stages(self, credentials):
        result = await _run(
            SnowflakeListStagesConfig(database="DB1", schema_name="PUBLIC"),
            credentials,
            200,
            [{"name": "MY_STAGE"}],
        )
        assert result["status"] == "success"
        assert result["action"] == "list_stages"


# ============================================================================
# Error handling
# ============================================================================


class TestSnowflakeErrorHandlingMock:
    async def test_api_error(self, credentials):
        result = await _run(
            SnowflakeFetchDatabaseConfig(name="MISSING"),
            credentials,
            404,
            {"message": "Database 'MISSING' does not exist."},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "does not exist" in str(result["error"]).lower()

    async def test_rate_limited(self, credentials):
        result = await _run(
            SnowflakeListDatabasesConfig(),
            credentials,
            429,
            {"message": "Request rate exceeds max"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 429

    async def test_missing_credentials(self):
        config = SnowflakeNodeConfig(
            config=SnowflakeListDatabasesConfig(), credentials=None
        )
        node = create_snowflake_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestSnowflakeDynamicOptionsMock:
    """load_field_options receives the already-decrypted credential_data from the
    framework (no self-loading) — signature (field_name, credential_data, ...)."""

    PAT_CRED = {"account_identifier": "org-acct", "token": "pat"}

    async def test_load_warehouse_options(self):
        with patch(
            "nodes.snowflake_node._snowflake_request",
            return_value={"status": "success", "data": [{"name": "WH"}, {"name": "WH2"}]},
        ):
            result = await SnowflakeNode.load_field_options("warehouse", self.PAT_CRED)
        assert "options" in result
        assert result["options"][0]["value"] == "WH"
        assert len(result["options"]) == 2

    async def test_load_database_options(self):
        with patch(
            "nodes.snowflake_node._snowflake_request",
            return_value={"status": "success", "data": [{"name": "DB1"}]},
        ):
            result = await SnowflakeNode.load_field_options("database", self.PAT_CRED)
        assert result["options"][0]["value"] == "DB1"

    async def test_load_options_unknown_field(self):
        result = await SnowflakeNode.load_field_options("nonexistent", self.PAT_CRED)
        assert result == {"options": []}

    async def test_load_options_missing_credential(self):
        result = await SnowflakeNode.load_field_options("warehouse", None)
        assert result == {"options": []}


# ============================================================================
# Credential token-type header (PAT-only)
# ============================================================================


def _record_headers_client(json_data):
    """Mock httpx.AsyncClient that records the request headers so token-type and
    bearer routing can be asserted."""
    recorded = {}
    mock_response = create_mock_response(200, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        recorded["headers"] = kwargs.get("headers", {})
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client, recorded


class TestSnowflakeCredentialHeaderMock:
    async def test_pat_routes_pat_token_type_header(self):
        config = SnowflakeNodeConfig(
            config=SnowflakeListDatabasesConfig(),
            credentials=SnowflakePatCredential(
                account_identifier="myorg-myaccount", token="pat_secret"
            ),
        )
        node = create_snowflake_node(config)
        mock_client, recorded = _record_headers_client([{"name": "DB1"}])
        with patch("nodes.snowflake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert recorded["headers"]["Authorization"] == "Bearer pat_secret"
        assert (
            recorded["headers"]["X-Snowflake-Authorization-Token-Type"]
            == "PROGRAMMATIC_ACCESS_TOKEN"
        )

    def test_pat_is_the_only_credential_type(self):
        """Snowflake is PAT-only — the credential resolves to SnowflakePatCredential
        and there is no OAuth credential type."""
        config = SnowflakeNodeConfig(
            config=SnowflakeListDatabasesConfig(),
            credentials={
                "credential_type": "snowflake_pat",
                "account_identifier": "org-acct",
                "token": "pat",
            },
        )
        assert isinstance(config.credentials, SnowflakePatCredential)
        assert config.credentials.token == "pat"
        assert not hasattr(SnowflakeNode, "_ensure_fresh_token")


# ============================================================================
# Poll-based trigger (on_query_results)
# ============================================================================


def _sql_result(columns, rows):
    """Build a Snowflake SQL API response body (array-of-arrays + rowType)."""
    return {
        "resultSetMetaData": {
            "rowType": [{"name": col} for col in columns],
        },
        "data": rows,
    }


class TestSnowflakeTriggerResolvePayload:
    def test_resolve_returns_none_for_poll_op(self):
        """Poll triggers must return None so execute() runs and actually polls."""
        assert (
            SnowflakeNode.resolve_trigger_payload(
                {"some": "webhook_payload"}, {"operation": "on_query_results"}
            )
            is None
        )

    def test_resolve_passthrough_for_normal_op(self):
        """Non-trigger ops keep the default passthrough behavior."""
        payload = {"some": "webhook_payload"}
        assert (
            SnowflakeNode.resolve_trigger_payload(
                payload, {"operation": "run_statement"}
            )
            == payload
        )


class TestSnowflakeTriggerExecuteMock:
    async def test_poll_baselines_on_first_run(self, credentials):
        """First poll (no cursor) baselines: it records the current high-water
        mark and emits NOTHING, so enabling the trigger never floods the
        workflow with the entire existing result set."""
        result = await _run(
            SnowflakeOnQueryResultsConfig(
                statement="SELECT ID, EMAIL FROM signups ORDER BY ID",
                cursor_column="ID",
                warehouse="WH",
            ),
            credentials,
            200,
            _sql_result(
                ["ID", "EMAIL"],
                [["1", "a@x.com"], ["2", "b@x.com"], ["3", "c@x.com"]],
            ),
        )
        assert result["status"] == "success"
        assert result["operation"] == "on_query_results"
        assert result["new_count"] == 0
        assert result["items"] == []
        # Cursor is seeded to the max seen id AND persisted, so the NEXT poll
        # only emits rows added after this baseline.
        assert result["last_seen_cursor"] == "3"
        assert result["__saved_state__"] == {"last_seen_cursor": "3"}

    async def test_poll_null_cursor_stays_unbaselined(self, credentials):
        """A first poll where the cursor column is null on every row must NOT
        persist a null high-water-mark — doing so would make the next poll treat
        every row as new and flood. It stays unbaselined (no write) until a real
        cursor value appears."""
        result = await _run(
            SnowflakeOnQueryResultsConfig(
                statement="SELECT ID, EMAIL FROM signups",
                cursor_column="ID",
            ),
            credentials,
            200,
            _sql_result(["ID", "EMAIL"], [[None, "a@x.com"], [None, "b@x.com"]]),
        )
        assert result["new_count"] == 0
        assert result["items"] == []
        # Nothing persisted → next poll with real cursors will baseline properly.
        assert result["__saved_state__"] == {}

    async def test_poll_dedupes_already_seen_rows(self, credentials):
        """With a persisted cursor, only rows beyond the cursor are emitted."""
        result = await _run(
            SnowflakeOnQueryResultsConfig(
                statement="SELECT ID, EMAIL FROM signups ORDER BY ID",
                cursor_column="ID",
            ),
            credentials,
            200,
            _sql_result(
                ["ID", "EMAIL"],
                [["1", "a@x.com"], ["2", "b@x.com"], ["3", "c@x.com"]],
            ),
            node_state={"last_seen_cursor": "2"},
        )
        assert result["new_count"] == 1
        assert result["items"][0]["ID"] == "3"
        assert result["items"][0]["EMAIL"] == "c@x.com"
        assert result["last_seen_cursor"] == "3"
        assert result["__saved_state__"] == {"last_seen_cursor": "3"}

    async def test_poll_no_new_rows_skips_downstream(self, credentials):
        """When nothing is new, trigger_produced_no_event returns True so the
        executor halts downstream (and the cursor is not rewritten)."""
        config_obj = SnowflakeOnQueryResultsConfig(
            statement="SELECT ID FROM signups ORDER BY ID",
            cursor_column="ID",
        )
        config = SnowflakeNodeConfig(config=config_obj, credentials=credentials)
        node = create_snowflake_node(config)

        saved: dict = {}

        async def _update(mutator, *, max_retries=4, skip_result=None):
            new_state, result = mutator({"last_seen_cursor": "3"})
            if new_state is not None:
                saved.update(new_state)
            return result

        node._update_node_state = _update
        mock_client = create_mock_client(
            200, _sql_result(["ID"], [["1"], ["2"], ["3"]])
        )
        with patch("nodes.snowflake_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["new_count"] == 0
        assert node.trigger_produced_no_event(result) is True
        # Cursor unchanged → no rewrite.
        assert saved == {}

    async def test_poll_no_new_rows_returns_empty(self, credentials):
        """When every row is at or below the cursor, nothing is emitted and the
        cursor does not regress."""
        result = await _run(
            SnowflakeOnQueryResultsConfig(
                statement="SELECT ID FROM signups",
                cursor_column="ID",
            ),
            credentials,
            200,
            _sql_result(["ID"], [["1"], ["2"], ["3"]]),
            node_state={"last_seen_cursor": "3"},
        )
        assert result["new_count"] == 0
        assert result["items"] == []
        assert result["last_seen_cursor"] == "3"

    async def test_poll_advances_cursor_in_node_state(self, credentials):
        """The cursor is advanced in PERSISTED node state (not config) so the
        next headless poll dedupes — config mutation would be discarded."""
        result = await _run(
            SnowflakeOnQueryResultsConfig(
                statement="SELECT ID FROM signups",
                cursor_column="ID",
            ),
            credentials,
            200,
            _sql_result(["ID"], [["1"], ["2"], ["3"]]),
            node_state={"last_seen_cursor": "1"},
        )
        assert result["new_count"] == 2  # ids 2 and 3
        # Advanced cursor is written back to node state, surviving the run.
        assert result["__saved_state__"] == {"last_seen_cursor": "3"}

    async def test_poll_propagates_api_error(self, credentials):
        """A failed query is surfaced as an error, not an empty emit."""
        result = await _run(
            SnowflakeOnQueryResultsConfig(
                statement="SELECT bad", cursor_column="ID"
            ),
            credentials,
            400,
            {"message": "SQL compilation error"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 400

    async def test_trigger_teardown_deletes_schedule(self):
        """Removing the trigger node tears down the cron schedule (via
        ScheduledPollTriggerMixin) — otherwise the schedule leaks and POSTs the
        webhook forever. (The webhooks row itself is owned by the WebhookManager
        choke point, not this mixin.)"""
        with patch(
            "utils.cron_scheduler_client.delete_schedules_for_nodes",
            new_callable=AsyncMock,
        ) as del_sched:
            await SnowflakeNode.cleanup_external_webhook(
                pool=Mock(),
                workflow_id="wf-1",
                node_id="node-1",
                config={"operation": "on_query_results"},
            )
        del_sched.assert_awaited_once()


# ============================================================================
# Registry integrity (full control-plane REST API v2 coverage)
# ============================================================================


def _all_configs():
    return typing.get_args(typing.get_args(SnowflakeConfig)[0])


def _all_op_names():
    return [c.model_fields["operation"].default for c in _all_configs()]


class TestSnowflakeRegistryIntegrity:
    def test_full_coverage_size(self):
        """The node exposes the hand-written ops plus the full generated
        control-plane registry (200+ operations)."""
        ops = _all_op_names()
        assert len(ops) > 300
        # Generated registry is the bulk; hand-written SQL/CRUD/trigger the rest.
        assert len(SNOWFLAKE_OPERATION_CONFIGS) == len(SNOWFLAKE_OPERATION_HANDLERS)
        assert len(SNOWFLAKE_OPERATION_CONFIGS) > 300

    def test_operation_names_unique(self):
        ops = _all_op_names()
        assert len(set(ops)) == len(ops), "duplicate operation discriminators"

    def test_config_class_names_unique(self):
        names = [c.__name__ for c in _all_configs()]
        assert len(set(names)) == len(names), "duplicate config class names"

    def test_every_op_has_a_handler(self):
        """Every union member dispatches: it's either a hand-written bound handler
        or a generated module-level handler in the registry."""
        import inspect

        bound_src = inspect.getsource(SnowflakeNode.execute)
        for op in _all_op_names():
            has_bound = f'"{op}"' in bound_src
            has_gen = op in SNOWFLAKE_OPERATION_HANDLERS
            assert has_bound or has_gen, f"operation {op} has no handler"

    def test_generated_handler_signature(self):
        """Generated handlers take (node, c, account, token) so dispatch can pass
        the node for self._request token-type injection + node-state access."""
        import inspect

        for op, fn in list(SNOWFLAKE_OPERATION_HANDLERS.items())[:50]:
            params = list(inspect.signature(fn).parameters)
            assert params[:4] == ["node", "c", "account", "token"], (op, params)

    def test_config_schema_builds(self):
        schema = SnowflakeNode.get_config_schema()
        assert isinstance(schema, dict) and schema

    def test_representative_generated_ops_present(self):
        """Spot-check that key resources from the OpenAPI specs are covered."""
        ops = set(_all_op_names())
        for expected in [
            "create_pipe", "refresh_pipe", "list_views", "create_view",
            "create_stream", "list_secrets", "create_secret", "create_tag",
            "list_compute_pools", "create_compute_pool", "create_notebook",
            "execute_notebook", "create_or_alter_table", "list_procedures",
            "call_procedure", "clone_sequence", "list_dynamic_tables",
            "create_snowflake_managed_iceberg_table",
        ]:
            assert expected in ops, f"missing expected op {expected}"


# ============================================================================
# Generated-op body correctness (regressions found in live E2E)
# ============================================================================


class TestSnowflakeGeneratedBodies:
    def test_target_lag_converter(self):
        """Dynamic-table target_lag must serialize to the structured TargetLag
        object the REST API requires, not a raw string (live E2E bug)."""
        from nodes.snowflake_node import _sf_target_lag
        assert _sf_target_lag("1 hour") == {"type": "USER_DEFINED", "seconds": 3600}
        assert _sf_target_lag("90 seconds") == {"type": "USER_DEFINED", "seconds": 90}
        assert _sf_target_lag("2 days") == {"type": "USER_DEFINED", "seconds": 172800}
        assert _sf_target_lag("120") == {"type": "USER_DEFINED", "seconds": 120}
        assert _sf_target_lag("DOWNSTREAM") == {"type": "DOWNSTREAM"}
        assert _sf_target_lag(None) is None
        assert _sf_target_lag("") is None
        with pytest.raises(ValueError):
            _sf_target_lag("whenever")

    async def test_create_dynamic_table_sends_object_target_lag(self, credentials):
        """create_dynamic_table body carries target_lag as an object."""
        captured = {}

        async def _capture(account, token, method, endpoint, **kwargs):
            captured["body"] = kwargs.get("json_body")
            return {"status": "success", "action": "create_dynamic_table", "data": {}, "status_code": 200, "timing_ms": {}}

        configs = {c.model_fields["operation"].default: c for c in _all_configs()}
        cfg = SnowflakeNodeConfig(
            config=configs["create_dynamic_table"](
                database="DB", schema_name="PUBLIC", name="DT",
                warehouse="WH", query="SELECT 1", target_lag="1 hour",
            ),
            credentials=credentials,
        )
        node = create_snowflake_node(cfg)
        with patch("nodes.snowflake_node._snowflake_request", side_effect=_capture):
            result = await node.execute({})
        assert result["status"] == "success"
        assert captured["body"]["target_lag"] == {"type": "USER_DEFINED", "seconds": 3600}

    def test_task_schedule_converter(self):
        """create_task schedule must serialize to a TaskSchedule object, not a
        raw string (live E2E bug)."""
        from nodes.snowflake_node import _sf_task_schedule
        assert _sf_task_schedule("5 MINUTE") == {"schedule_type": "MINUTES_TYPE", "minutes": 5}
        assert _sf_task_schedule("60 minutes") == {"schedule_type": "MINUTES_TYPE", "minutes": 60}
        assert _sf_task_schedule("USING CRON 0 9 * * * UTC") == {
            "schedule_type": "CRON_TYPE", "cron_expr": "0 9 * * *", "timezone": "UTC",
        }
        assert _sf_task_schedule(None) is None
        with pytest.raises(ValueError):
            _sf_task_schedule("every so often")

    async def test_create_task_sends_object_schedule(self, credentials):
        captured = {}

        async def _capture(account, token, method, endpoint, **kwargs):
            captured["body"] = kwargs.get("json_body")
            return {"status": "success", "action": "create_task", "data": {}, "status_code": 200, "timing_ms": {}}

        cfg = SnowflakeNodeConfig(
            config=SnowflakeCreateTaskConfig(
                database="DB", schema_name="PUBLIC", name="T",
                definition="SELECT 1", warehouse="WH", task_schedule="5 MINUTE",
            ),
            credentials=credentials,
        )
        node = create_snowflake_node(cfg)
        with patch("nodes.snowflake_node._snowflake_request", side_effect=_capture):
            result = await node.execute({})
        assert result["status"] == "success"
        assert captured["body"]["schedule"] == {"schedule_type": "MINUTES_TYPE", "minutes": 5}
