"""
Mock tests for the Databricks REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- SQL: run statement, get statement, cancel statement
- SQL Warehouses: list, get, start, stop
- Jobs: list, get, create, run now, submit run, list runs, get run,
  get run output, cancel run, delete
- Clusters: list, get, create, start, terminate
- Unity Catalog: list catalogs, list schemas, list tables, get table
- Workspace: list, export, import
- Secrets: list scopes
- Triggers: one per job event; passthrough + per-event filter routing
- Error handling: API errors, missing credentials
- Dynamic options: warehouse / job / cluster / catalog dropdowns
"""

import pytest
from unittest.mock import Mock, patch

from nodes.databricks_node import (
    DatabricksNode,
    DatabricksNodeConfig,
    DatabricksTokenCredential,
    DatabricksRunStatementConfig,
    DatabricksGetStatementConfig,
    DatabricksCancelStatementConfig,
    DatabricksListWarehousesConfig,
    DatabricksGetWarehouseConfig,
    DatabricksStartWarehouseConfig,
    DatabricksStopWarehouseConfig,
    DatabricksListJobsConfig,
    DatabricksGetJobConfig,
    DatabricksCreateJobConfig,
    DatabricksRunNowConfig,
    DatabricksSubmitRunConfig,
    DatabricksListRunsConfig,
    DatabricksGetRunConfig,
    DatabricksGetRunOutputConfig,
    DatabricksCancelRunConfig,
    DatabricksDeleteJobConfig,
    DatabricksListClustersConfig,
    DatabricksGetClusterConfig,
    DatabricksCreateClusterConfig,
    DatabricksStartClusterConfig,
    DatabricksTerminateClusterConfig,
    DatabricksListCatalogsConfig,
    DatabricksListSchemasConfig,
    DatabricksListTablesConfig,
    DatabricksGetTableConfig,
    DatabricksListWorkspaceConfig,
    DatabricksExportWorkspaceConfig,
    DatabricksImportWorkspaceConfig,
    DatabricksListSecretScopesConfig,
    DATABRICKS_TRIGGER_CONFIGS,
    DATABRICKS_TRIGGER_EVENT,
)


@pytest.fixture
def credentials():
    return DatabricksTokenCredential(
        workspace_url="https://dbc-a1b2345c-d6e7.cloud.databricks.com",
        access_token="dapi_test_token_12345",
    )


def create_databricks_node(config):
    return DatabricksNode(
        node_id="test-databricks-node",
        node_type="automation-databricks",
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
    mock_response.text = "" if json_data is None else "{}"
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


async def _run(config_obj, credentials, status_code, json_data):
    node = create_databricks_node(
        DatabricksNodeConfig(config=config_obj, credentials=credentials)
    )
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.databricks_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
class TestDatabricksSqlMock:
    @pytest.mark.asyncio
    async def test_run_statement(self, credentials):
        result = await _run(
            DatabricksRunStatementConfig(warehouse_id="wh1", statement="SELECT 1"),
            credentials,
            200,
            {"statement_id": "st_1", "status": {"state": "SUCCEEDED"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "run_statement"
        assert result["data"]["statement_id"] == "st_1"

    @pytest.mark.asyncio
    async def test_get_statement(self, credentials):
        result = await _run(
            DatabricksGetStatementConfig(statement_id="st_1"),
            credentials,
            200,
            {"statement_id": "st_1", "status": {"state": "SUCCEEDED"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_statement"

    @pytest.mark.asyncio
    async def test_cancel_statement(self, credentials):
        result = await _run(
            DatabricksCancelStatementConfig(statement_id="st_1"), credentials, 200, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "cancel_statement"


# ---------------------------------------------------------------------------
# SQL Warehouses
# ---------------------------------------------------------------------------
class TestDatabricksWarehousesMock:
    @pytest.mark.asyncio
    async def test_list_warehouses(self, credentials):
        result = await _run(
            DatabricksListWarehousesConfig(),
            credentials,
            200,
            {"warehouses": [{"id": "wh1", "name": "Serverless"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_warehouses"
        assert result["data"]["warehouses"][0]["id"] == "wh1"

    @pytest.mark.asyncio
    async def test_get_warehouse(self, credentials):
        result = await _run(
            DatabricksGetWarehouseConfig(warehouse_id="wh1"),
            credentials,
            200,
            {"id": "wh1", "state": "RUNNING"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_warehouse"

    @pytest.mark.asyncio
    async def test_start_warehouse(self, credentials):
        result = await _run(
            DatabricksStartWarehouseConfig(warehouse_id="wh1"), credentials, 200, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "start_warehouse"

    @pytest.mark.asyncio
    async def test_stop_warehouse(self, credentials):
        result = await _run(
            DatabricksStopWarehouseConfig(warehouse_id="wh1"), credentials, 200, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "stop_warehouse"


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class TestDatabricksJobsMock:
    @pytest.mark.asyncio
    async def test_list_jobs(self, credentials):
        result = await _run(
            DatabricksListJobsConfig(limit="10"),
            credentials,
            200,
            {"jobs": [{"job_id": 1, "settings": {"name": "ETL"}}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_jobs"

    @pytest.mark.asyncio
    async def test_get_job(self, credentials):
        result = await _run(
            DatabricksGetJobConfig(job_id="1"),
            credentials,
            200,
            {"job_id": 1, "settings": {"name": "ETL"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_job"
        assert result["data"]["job_id"] == 1

    @pytest.mark.asyncio
    async def test_create_job(self, credentials):
        result = await _run(
            DatabricksCreateJobConfig(
                name="New job",
                tasks_json='[{"task_key": "t1", "notebook_task": {"notebook_path": "/n"}}]',
            ),
            credentials,
            200,
            {"job_id": 42},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_job"
        assert result["data"]["job_id"] == 42

    @pytest.mark.asyncio
    async def test_run_now(self, credentials):
        result = await _run(
            DatabricksRunNowConfig(job_id="1"),
            credentials,
            200,
            {"run_id": 100, "number_in_job": 1},
        )
        assert result["status"] == "success"
        assert result["action"] == "run_now"
        assert result["data"]["run_id"] == 100

    @pytest.mark.asyncio
    async def test_submit_run(self, credentials):
        result = await _run(
            DatabricksSubmitRunConfig(
                run_name="adhoc",
                tasks_json='[{"task_key": "t1", "notebook_task": {"notebook_path": "/n"}}]',
            ),
            credentials,
            200,
            {"run_id": 101},
        )
        assert result["status"] == "success"
        assert result["action"] == "submit_run"

    @pytest.mark.asyncio
    async def test_list_runs(self, credentials):
        result = await _run(
            DatabricksListRunsConfig(job_id="1", limit="5"),
            credentials,
            200,
            {"runs": [{"run_id": 100}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_runs"

    @pytest.mark.asyncio
    async def test_get_run(self, credentials):
        result = await _run(
            DatabricksGetRunConfig(run_id="100"),
            credentials,
            200,
            {"run_id": 100, "state": {"life_cycle_state": "TERMINATED"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_run"

    @pytest.mark.asyncio
    async def test_get_run_output(self, credentials):
        result = await _run(
            DatabricksGetRunOutputConfig(run_id="100"),
            credentials,
            200,
            {"notebook_output": {"result": "ok"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_run_output"

    @pytest.mark.asyncio
    async def test_cancel_run(self, credentials):
        result = await _run(
            DatabricksCancelRunConfig(run_id="100"), credentials, 200, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "cancel_run"

    @pytest.mark.asyncio
    async def test_delete_job(self, credentials):
        result = await _run(
            DatabricksDeleteJobConfig(job_id="1"), credentials, 200, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_job"


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------
class TestDatabricksClustersMock:
    @pytest.mark.asyncio
    async def test_list_clusters(self, credentials):
        result = await _run(
            DatabricksListClustersConfig(),
            credentials,
            200,
            {"clusters": [{"cluster_id": "c1", "cluster_name": "shared"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_clusters"

    @pytest.mark.asyncio
    async def test_get_cluster(self, credentials):
        result = await _run(
            DatabricksGetClusterConfig(cluster_id="c1"),
            credentials,
            200,
            {"cluster_id": "c1", "state": "RUNNING"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_cluster"

    @pytest.mark.asyncio
    async def test_create_cluster(self, credentials):
        result = await _run(
            DatabricksCreateClusterConfig(
                cluster_name="ad-hoc",
                spark_version="13.3.x-scala2.12",
                node_type_id="i3.xlarge",
                num_workers="2",
            ),
            credentials,
            200,
            {"cluster_id": "c2"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_cluster"
        assert result["data"]["cluster_id"] == "c2"

    @pytest.mark.asyncio
    async def test_start_cluster(self, credentials):
        result = await _run(
            DatabricksStartClusterConfig(cluster_id="c1"), credentials, 200, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "start_cluster"

    @pytest.mark.asyncio
    async def test_terminate_cluster(self, credentials):
        result = await _run(
            DatabricksTerminateClusterConfig(cluster_id="c1"), credentials, 200, {}
        )
        assert result["status"] == "success"
        assert result["action"] == "terminate_cluster"


# ---------------------------------------------------------------------------
# Unity Catalog
# ---------------------------------------------------------------------------
class TestDatabricksUnityCatalogMock:
    @pytest.mark.asyncio
    async def test_list_catalogs(self, credentials):
        result = await _run(
            DatabricksListCatalogsConfig(),
            credentials,
            200,
            {"catalogs": [{"name": "main"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_catalogs"

    @pytest.mark.asyncio
    async def test_list_schemas(self, credentials):
        result = await _run(
            DatabricksListSchemasConfig(catalog_name="main"),
            credentials,
            200,
            {"schemas": [{"name": "default"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_schemas"

    @pytest.mark.asyncio
    async def test_list_tables(self, credentials):
        result = await _run(
            DatabricksListTablesConfig(catalog_name="main", schema_name="default"),
            credentials,
            200,
            {"tables": [{"name": "events"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_tables"

    @pytest.mark.asyncio
    async def test_get_table(self, credentials):
        result = await _run(
            DatabricksGetTableConfig(full_name="main.default.events"),
            credentials,
            200,
            {"name": "events", "full_name": "main.default.events"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_table"
        assert result["data"]["full_name"] == "main.default.events"


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
class TestDatabricksWorkspaceMock:
    @pytest.mark.asyncio
    async def test_list_workspace(self, credentials):
        result = await _run(
            DatabricksListWorkspaceConfig(path="/Users/me"),
            credentials,
            200,
            {"objects": [{"path": "/Users/me/nb", "object_type": "NOTEBOOK"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_workspace"

    @pytest.mark.asyncio
    async def test_export_workspace(self, credentials):
        result = await _run(
            DatabricksExportWorkspaceConfig(path="/Users/me/nb", export_format="SOURCE"),
            credentials,
            200,
            {"content": "cHJpbnQoMSk=", "file_type": "py"},
        )
        assert result["status"] == "success"
        assert result["action"] == "export_workspace"

    @pytest.mark.asyncio
    async def test_import_workspace(self, credentials):
        result = await _run(
            DatabricksImportWorkspaceConfig(
                path="/Users/me/nb2",
                content="cHJpbnQoMSk=",
                import_format="SOURCE",
                language="PYTHON",
                overwrite="true",
            ),
            credentials,
            200,
            {},
        )
        assert result["status"] == "success"
        assert result["action"] == "import_workspace"


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
class TestDatabricksSecretsMock:
    @pytest.mark.asyncio
    async def test_list_secret_scopes(self, credentials):
        result = await _run(
            DatabricksListSecretScopesConfig(),
            credentials,
            200,
            {"scopes": [{"name": "my-scope", "backend_type": "DATABRICKS"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_secret_scopes"


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------
class TestDatabricksTriggerMock:
    def test_one_trigger_per_event(self):
        """The single receive-webhook trigger is decomposed into one op per event."""
        assert len(DATABRICKS_TRIGGER_CONFIGS) == 5
        for op, cls in DATABRICKS_TRIGGER_CONFIGS.items():
            assert "event_types" not in cls.model_fields  # no dropdown
            extra = cls.model_fields["operation"].json_schema_extra
            assert extra["const"] == op
            assert extra["x-is-trigger"] is True

    @pytest.mark.parametrize("op", list(DATABRICKS_TRIGGER_CONFIGS))
    @pytest.mark.asyncio
    async def test_trigger_passthrough(self, op):
        """Each per-event trigger passes the inbound webhook payload through."""
        config = DatabricksNodeConfig(
            config=DATABRICKS_TRIGGER_CONFIGS[op](webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_databricks_node(config)
        payload = {"event_type": "jobs.on_failure", "run_id": 100}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == op
        assert result["data"]["event_type"] == "jobs.on_failure"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"


class TestDatabricksTriggerEventFilterMock:
    """The webhook destination has no per-subscription filter, so each per-event
    trigger matches the payload's event_type at runtime in filter_trigger_payload."""

    @pytest.mark.parametrize("op,event", [
        ("on_job_start", "jobs.on_start"),
        ("on_job_success", "jobs.on_success"),
        ("on_job_failure", "jobs.on_failure"),
        ("on_job_duration_warning", "jobs.on_duration_warning_threshold_exceeded"),
    ])
    def test_trigger_fires_only_on_its_event(self, op, event):
        cfg = {"operation": op}
        # its own event passes
        assert DatabricksNode.filter_trigger_payload({"event_type": event}, cfg) is True
        # every other event is filtered out
        for other in DATABRICKS_TRIGGER_EVENT.values():
            if other not in (event, "*"):
                assert DatabricksNode.filter_trigger_payload({"event_type": other}, cfg) is False

    def test_on_any_job_event_passes_everything(self):
        cfg = {"operation": "on_any_job_event"}
        for et in ("jobs.on_start", "jobs.on_success", "jobs.on_failure",
                   "jobs.on_duration_warning_threshold_exceeded"):
            assert DatabricksNode.filter_trigger_payload({"event_type": et}, cfg) is True

    def test_unknown_operation_passes(self):
        """An unknown operation never silently drops every event."""
        assert DatabricksNode.filter_trigger_payload(
            {"event_type": "jobs.on_failure"}, {"operation": "receive_webhook"}
        ) is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestDatabricksErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        result = await _run(
            DatabricksGetJobConfig(job_id="999"),
            credentials,
            404,
            {"error_code": "RESOURCE_DOES_NOT_EXIST", "message": "Job 999 does not exist."},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "does not exist" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = DatabricksNodeConfig(
            config=DatabricksListWarehousesConfig(), credentials=None
        )
        node = create_databricks_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ---------------------------------------------------------------------------
# Dynamic options
# ---------------------------------------------------------------------------
class TestDatabricksDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_warehouse_options(self):
        with patch(
            "nodes.databricks_node._databricks_request",
            return_value={
                "status": "success",
                "data": {"warehouses": [{"id": "wh1", "name": "Serverless"}]},
            },
        ):
            result = await DatabricksNode.load_field_options(
                "warehouse_id",
                {"workspace_url": "https://x.cloud.databricks.com", "access_token": "t"},
            )
        assert result["options"][0]["value"] == "wh1"
        assert result["options"][0]["label"] == "Serverless"

    @pytest.mark.asyncio
    async def test_load_job_options(self):
        with patch(
            "nodes.databricks_node._databricks_request",
            return_value={
                "status": "success",
                "data": {"jobs": [{"job_id": 7, "settings": {"name": "Nightly"}}]},
            },
        ):
            result = await DatabricksNode.load_field_options(
                "job_id",
                {"workspace_url": "https://x.cloud.databricks.com", "access_token": "t"},
            )
        assert result["options"][0]["value"] == "7"
        assert result["options"][0]["label"] == "Nightly"

    @pytest.mark.asyncio
    async def test_load_cluster_options(self):
        with patch(
            "nodes.databricks_node._databricks_request",
            return_value={
                "status": "success",
                "data": {"clusters": [{"cluster_id": "c1", "cluster_name": "shared"}]},
            },
        ):
            result = await DatabricksNode.load_field_options(
                "cluster_id",
                {"workspace_url": "https://x.cloud.databricks.com", "access_token": "t"},
            )
        assert result["options"][0]["value"] == "c1"
        assert result["options"][0]["label"] == "shared"

    @pytest.mark.asyncio
    async def test_load_catalog_options(self):
        with patch(
            "nodes.databricks_node._databricks_request",
            return_value={
                "status": "success",
                "data": {"catalogs": [{"name": "main"}]},
            },
        ):
            result = await DatabricksNode.load_field_options(
                "catalog_name",
                {"workspace_url": "https://x.cloud.databricks.com", "access_token": "t"},
            )
        assert result["options"][0]["value"] == "main"

    @pytest.mark.asyncio
    async def test_load_options_no_credential(self):
        result = await DatabricksNode.load_field_options("warehouse_id", {})
        assert result == {"options": []}


# ============================================================================
# Full-coverage dispatch tests — every registry operation (356 generated +
# curated) builds a minimal config, mocks the HTTP layer, runs execute(), and
# must dispatch cleanly to _databricks_request with matching action + a
# resolved /api/... endpoint. Guards against handler/field drift.
# ============================================================================

from typing import get_args
import nodes.databricks_node as _dbx
from nodes.databricks_node import DatabricksConfig, DatabricksTokenCredential, DATABRICKS_TRIGGER_CONFIGS

_MEMBERS = {m.model_fields["operation"].default: m for m in get_args(get_args(DatabricksConfig)[0])}
_ACTION_OPS = [op for op in _MEMBERS if op not in DATABRICKS_TRIGGER_CONFIGS]
_CRED = DatabricksTokenCredential(workspace_url="https://x.cloud.databricks.com", access_token="pat")


def _build_min_config(model):
    kwargs = {}
    for name, field in model.model_fields.items():
        if name == "operation" or not field.is_required():
            continue
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        enum = extra.get("enum")
        kwargs[name] = enum[0] if enum else ("{}" if name.endswith("_json") else "1")
    return model(**kwargs)


@pytest.mark.parametrize("op", _ACTION_OPS)
@pytest.mark.asyncio
async def test_operation_dispatches(op):
    captured = {}

    async def fake_request(host, token, method, endpoint, params=None, json_body=None,
                           action_name="request", content_type="application/json", data=None):
        captured["endpoint"] = endpoint
        captured["method"] = method
        return {"status": "success", "action": action_name, "data": {}}

    node = DatabricksNode(
        node_id="cov", node_type="automation-databricks", node_data={},
        config=DatabricksNodeConfig(config=_build_min_config(_MEMBERS[op]), credentials=_CRED),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )
    with patch.object(_dbx, "_databricks_request", side_effect=fake_request):
        result = await node.execute({})
    assert result["status"] == "success", f"{op}: {result.get('error')}"
    assert result["action"] == op
    assert captured.get("endpoint", "").startswith("/api/"), f"{op}: bad endpoint {captured.get('endpoint')}"
    assert "{" not in captured["endpoint"], f"{op}: unresolved path template {captured['endpoint']}"


def test_full_coverage_op_count():
    """Lock in the full stable-API surface (356 registry + 31 curated = 386 actions)."""
    assert len(_dbx.OPERATION_CONFIGS) == len(_dbx.OPERATION_HANDLERS) == 356
    assert len(_ACTION_OPS) == 386  # 391 total minus the 5 per-event triggers
    assert len(DATABRICKS_TRIGGER_CONFIGS) == 5


@pytest.mark.parametrize("op", ["get_current_user", "create_user", "list_groups", "patch_service_principal"])
@pytest.mark.asyncio
async def test_scim_ops_use_scim_content_type(op):
    """SCIM identity ops must send application/scim+json."""
    seen = {}

    async def fake_request(host, token, method, endpoint, params=None, json_body=None,
                           action_name="request", content_type="application/json", data=None):
        seen["ct"] = content_type
        return {"status": "success", "action": action_name, "data": {}}

    node = DatabricksNode(
        node_id="scim", node_type="automation-databricks", node_data={},
        config=DatabricksNodeConfig(config=_build_min_config(_MEMBERS[op]), credentials=_CRED),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )
    with patch.object(_dbx, "_databricks_request", side_effect=fake_request):
        await node.execute({})
    assert seen["ct"] == "application/scim+json"


@pytest.mark.asyncio
async def test_upload_file_uses_raw_body():
    """Files API upload must send a raw body, not JSON."""
    seen = {}

    async def fake_request(host, token, method, endpoint, params=None, json_body=None,
                           action_name="request", content_type="application/json", data=None):
        seen["data"] = data
        return {"status": "success", "action": action_name, "data": {}}

    node = DatabricksNode(
        node_id="up", node_type="automation-databricks", node_data={},
        config=DatabricksNodeConfig(config=_build_min_config(_MEMBERS["upload_file"]), credentials=_CRED),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )
    with patch.object(_dbx, "_databricks_request", side_effect=fake_request):
        await node.execute({})
    assert seen["data"] is not None
