"""
Mock tests for the Google BigQuery REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Queries: run query, get query results
- Jobs: insert, get, list, cancel, delete
- Datasets: list, get, create, update, patch, delete
- Tables: list, get, create, patch, update, delete, stream insert, list data
- Routines: list, get, create
- Models: list, get, delete
- Project: get service account, list projects
- Error handling: API errors, missing credentials, invalid JSON
- Dynamic options: project / dataset / table dropdowns

The OAuth token refresh (`ensure_fresh_oauth_token`) is patched at its source so
no database is touched; HTTP is patched at `nodes.bigquery_node.httpx.AsyncClient`.
"""

import pytest
from unittest.mock import Mock, patch

from nodes.bigquery_node import (
    BigQueryNode,
    BigQueryNodeConfig,
    BigQueryOAuthCredential,
    BigQueryRunQueryConfig,
    BigQueryGetQueryResultsConfig,
    BigQueryOnQueryResultsConfig,
    BigQueryInsertJobConfig,
    BigQueryGetJobConfig,
    BigQueryListJobsConfig,
    BigQueryCancelJobConfig,
    BigQueryDeleteJobConfig,
    BigQueryListDatasetsConfig,
    BigQueryGetDatasetConfig,
    BigQueryCreateDatasetConfig,
    BigQueryUpdateDatasetConfig,
    BigQueryPatchDatasetConfig,
    BigQueryDeleteDatasetConfig,
    BigQueryListTablesConfig,
    BigQueryGetTableConfig,
    BigQueryCreateTableConfig,
    BigQueryPatchTableConfig,
    BigQueryUpdateTableConfig,
    BigQueryDeleteTableConfig,
    BigQueryStreamInsertConfig,
    BigQueryListTableDataConfig,
    BigQueryListRoutinesConfig,
    BigQueryGetRoutineConfig,
    BigQueryCreateRoutineConfig,
    BigQueryListModelsConfig,
    BigQueryGetModelConfig,
    BigQueryDeleteModelConfig,
    BigQueryGetServiceAccountConfig,
    BigQueryListProjectsConfig,
    BigQueryUndeleteDatasetConfig,
    BigQueryUpdateRoutineConfig,
    BigQueryDeleteRoutineConfig,
    BigQueryPatchModelConfig,
    BigQueryGetTableIamPolicyConfig,
    BigQuerySetTableIamPolicyConfig,
    BigQueryTestTableIamPermissionsConfig,
    BigQueryListRowAccessPoliciesConfig,
    BigQueryGetRowAccessPolicyConfig,
)


@pytest.fixture
def oauth_credentials():
    return BigQueryOAuthCredential(
        access_token="ya29.test-access-token",
        refresh_token="1//test-refresh-token",
        expires_at="2099-01-01T00:00:00Z",
        email="bq@example.com",
    )


def create_bigquery_node(config):
    return BigQueryNode(
        node_id="test-bigquery-node",
        node_type="automation-bigquery",
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


async def _fake_token(*args, **kwargs):
    return "ya29.test-access-token"


async def _run(node, status_code=200, json_data=None):
    """Run node.execute with HTTP + token refresh mocked. Returns the result.

    The OAuth token refresh is bypassed by patching the node's
    ``_ensure_fresh_token`` (which otherwise reads the DB to rotate the token).
    """
    mock_client = create_mock_client(status_code, json_data)
    with patch(
        "nodes.bigquery_node.httpx.AsyncClient", return_value=mock_client
    ), patch.object(BigQueryNode, "_ensure_fresh_token", new=_fake_token):
        return await node.execute({})


class TestBigQueryQueriesMock:
    @pytest.mark.asyncio
    async def test_run_query(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryRunQueryConfig(project_id="proj-1", query="SELECT 1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(
            node, 200, {"jobComplete": True, "rows": [{"f": [{"v": "1"}]}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "run_query"
        assert result["data"]["jobComplete"] is True

    @pytest.mark.asyncio
    async def test_get_query_results(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetQueryResultsConfig(project_id="proj-1", job_id="job-1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"jobComplete": True, "totalRows": "5"})
        assert result["status"] == "success"
        assert result["action"] == "get_query_results"
        assert result["data"]["totalRows"] == "5"


class TestBigQueryJobsMock:
    @pytest.mark.asyncio
    async def test_insert_job(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryInsertJobConfig(
                project_id="proj-1",
                configuration='{"query": {"query": "SELECT 1", "useLegacySql": false}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"jobReference": {"jobId": "job-9"}})
        assert result["status"] == "success"
        assert result["action"] == "insert_job"
        assert result["data"]["jobReference"]["jobId"] == "job-9"

    @pytest.mark.asyncio
    async def test_get_job(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetJobConfig(project_id="proj-1", job_id="job-9"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"status": {"state": "DONE"}})
        assert result["status"] == "success"
        assert result["action"] == "get_job"
        assert result["data"]["status"]["state"] == "DONE"

    @pytest.mark.asyncio
    async def test_list_jobs(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryListJobsConfig(project_id="proj-1", state_filter="done"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"jobs": [{"id": "job-1"}, {"id": "job-2"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_jobs"
        assert len(result["data"]["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_cancel_job(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryCancelJobConfig(project_id="proj-1", job_id="job-9"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"job": {"status": {"state": "RUNNING"}}})
        assert result["status"] == "success"
        assert result["action"] == "cancel_job"

    @pytest.mark.asyncio
    async def test_delete_job(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryDeleteJobConfig(project_id="proj-1", job_id="job-9"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_job"
        assert result["data"]["success"] is True


class TestBigQueryDatasetsMock:
    @pytest.mark.asyncio
    async def test_list_datasets(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryListDatasetsConfig(project_id="proj-1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(
            node, 200, {"datasets": [{"datasetReference": {"datasetId": "ds1"}}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "list_datasets"
        assert len(result["data"]["datasets"]) == 1

    @pytest.mark.asyncio
    async def test_get_dataset(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetDatasetConfig(project_id="proj-1", dataset_id="ds1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"id": "proj-1:ds1"})
        assert result["status"] == "success"
        assert result["action"] == "get_dataset"
        assert result["data"]["id"] == "proj-1:ds1"

    @pytest.mark.asyncio
    async def test_create_dataset(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryCreateDatasetConfig(
                project_id="proj-1", dataset_id="ds_new", location="US"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(
            node, 200, {"datasetReference": {"datasetId": "ds_new"}}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_dataset"
        assert result["data"]["datasetReference"]["datasetId"] == "ds_new"

    @pytest.mark.asyncio
    async def test_update_dataset(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryUpdateDatasetConfig(
                project_id="proj-1",
                dataset_id="ds1",
                resource='{"description": "Updated"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"description": "Updated"})
        assert result["status"] == "success"
        assert result["action"] == "update_dataset"
        assert result["data"]["description"] == "Updated"

    @pytest.mark.asyncio
    async def test_patch_dataset(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryPatchDatasetConfig(
                project_id="proj-1",
                dataset_id="ds1",
                resource='{"friendlyName": "Patched"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"friendlyName": "Patched"})
        assert result["status"] == "success"
        assert result["action"] == "patch_dataset"
        assert result["data"]["friendlyName"] == "Patched"

    @pytest.mark.asyncio
    async def test_delete_dataset(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryDeleteDatasetConfig(
                project_id="proj-1", dataset_id="ds1", delete_contents="true"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_dataset"


class TestBigQueryTablesMock:
    @pytest.mark.asyncio
    async def test_list_tables(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryListTablesConfig(project_id="proj-1", dataset_id="ds1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(
            node, 200, {"tables": [{"tableReference": {"tableId": "t1"}}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "list_tables"
        assert len(result["data"]["tables"]) == 1

    @pytest.mark.asyncio
    async def test_get_table(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetTableConfig(
                project_id="proj-1", dataset_id="ds1", table_id="t1"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"id": "proj-1:ds1.t1"})
        assert result["status"] == "success"
        assert result["action"] == "get_table"
        assert result["data"]["id"] == "proj-1:ds1.t1"

    @pytest.mark.asyncio
    async def test_create_table(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryCreateTableConfig(
                project_id="proj-1",
                dataset_id="ds1",
                table_id="t_new",
                output_schema='{"fields": [{"name": "id", "type": "INTEGER"}]}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(
            node, 200, {"tableReference": {"tableId": "t_new"}}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_table"
        assert result["data"]["tableReference"]["tableId"] == "t_new"

    @pytest.mark.asyncio
    async def test_patch_table(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryPatchTableConfig(
                project_id="proj-1",
                dataset_id="ds1",
                table_id="t1",
                resource='{"description": "Patched table"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"description": "Patched table"})
        assert result["status"] == "success"
        assert result["action"] == "patch_table"

    @pytest.mark.asyncio
    async def test_update_table(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryUpdateTableConfig(
                project_id="proj-1",
                dataset_id="ds1",
                table_id="t1",
                resource='{"tableReference": {"projectId": "proj-1", "datasetId": "ds1", "tableId": "t1"}}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"id": "proj-1:ds1.t1"})
        assert result["status"] == "success"
        assert result["action"] == "update_table"

    @pytest.mark.asyncio
    async def test_delete_table(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryDeleteTableConfig(
                project_id="proj-1", dataset_id="ds1", table_id="t1"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_table"

    @pytest.mark.asyncio
    async def test_stream_insert(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryStreamInsertConfig(
                project_id="proj-1",
                dataset_id="ds1",
                table_id="t1",
                rows='[{"id": 1, "name": "Ada"}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"kind": "bigquery#tableDataInsertAllResponse"})
        assert result["status"] == "success"
        assert result["action"] == "stream_insert"
        assert result["data"]["kind"] == "bigquery#tableDataInsertAllResponse"

    @pytest.mark.asyncio
    async def test_stream_insert_invalid_rows_type(self, oauth_credentials):
        """Rows must be a JSON array — a non-array raises a clear error."""
        config = BigQueryNodeConfig(
            config=BigQueryStreamInsertConfig(
                project_id="proj-1",
                dataset_id="ds1",
                table_id="t1",
                rows='{"id": 1}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        with pytest.raises(ValueError, match="Rows must be a JSON array"):
            await _run(node, 200, {})

    @pytest.mark.asyncio
    async def test_list_table_data(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryListTableDataConfig(
                project_id="proj-1", dataset_id="ds1", table_id="t1"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"rows": [{"f": [{"v": "1"}]}], "totalRows": "1"})
        assert result["status"] == "success"
        assert result["action"] == "list_table_data"
        assert result["data"]["totalRows"] == "1"


class TestBigQueryRoutinesMock:
    @pytest.mark.asyncio
    async def test_list_routines(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryListRoutinesConfig(project_id="proj-1", dataset_id="ds1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"routines": [{"routineReference": {"routineId": "r1"}}]})
        assert result["status"] == "success"
        assert result["action"] == "list_routines"

    @pytest.mark.asyncio
    async def test_get_routine(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetRoutineConfig(
                project_id="proj-1", dataset_id="ds1", routine_id="r1"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"routineReference": {"routineId": "r1"}})
        assert result["status"] == "success"
        assert result["action"] == "get_routine"

    @pytest.mark.asyncio
    async def test_create_routine(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryCreateRoutineConfig(
                project_id="proj-1",
                dataset_id="ds1",
                resource='{"routineReference": {"routineId": "r_new"}, "routineType": "SCALAR_FUNCTION", "definitionBody": "1"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"routineReference": {"routineId": "r_new"}})
        assert result["status"] == "success"
        assert result["action"] == "create_routine"


class TestBigQueryModelsMock:
    @pytest.mark.asyncio
    async def test_list_models(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryListModelsConfig(project_id="proj-1", dataset_id="ds1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"models": [{"modelReference": {"modelId": "m1"}}]})
        assert result["status"] == "success"
        assert result["action"] == "list_models"

    @pytest.mark.asyncio
    async def test_get_model(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetModelConfig(
                project_id="proj-1", dataset_id="ds1", model_id="m1"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"modelReference": {"modelId": "m1"}})
        assert result["status"] == "success"
        assert result["action"] == "get_model"

    @pytest.mark.asyncio
    async def test_delete_model(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryDeleteModelConfig(
                project_id="proj-1", dataset_id="ds1", model_id="m1"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 204, None)
        assert result["status"] == "success"
        assert result["action"] == "delete_model"


class TestBigQueryProjectMock:
    @pytest.mark.asyncio
    async def test_get_service_account(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetServiceAccountConfig(project_id="proj-1"),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 200, {"email": "bq-sa@proj-1.iam.gserviceaccount.com"})
        assert result["status"] == "success"
        assert result["action"] == "get_service_account"
        assert "iam.gserviceaccount.com" in result["data"]["email"]

    @pytest.mark.asyncio
    async def test_list_projects(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryListProjectsConfig(),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(
            node, 200, {"projects": [{"id": "proj-1", "friendlyName": "Project One"}]}
        )
        assert result["status"] == "success"
        assert result["action"] == "list_projects"
        assert len(result["data"]["projects"]) == 1


class TestBigQueryErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryGetTableConfig(
                project_id="proj-1", dataset_id="ds1", table_id="missing"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        result = await _run(node, 404, {"error": {"message": "Not found: Table missing"}})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_invalid_job_configuration_json(self, oauth_credentials):
        config = BigQueryNodeConfig(
            config=BigQueryInsertJobConfig(
                project_id="proj-1", configuration="{not valid json"
            ),
            credentials=oauth_credentials,
        )
        node = create_bigquery_node(config)
        with pytest.raises(ValueError, match="Invalid JSON in Job Configuration"):
            await _run(node, 200, {})

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = BigQueryNodeConfig(
            config=BigQueryListProjectsConfig(), credentials=None
        )
        node = create_bigquery_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


_OAUTH_CRED_DATA = {"credential_type": "bigquery_oauth", "access_token": "ya29.x"}


class TestBigQueryDynamicOptionsMock:
    """Dropdowns use the canonical load_field_options signature: credential_data
    arrives pre-decrypted/freshened, and sibling fields come via context."""

    @pytest.mark.asyncio
    async def test_load_project_options(self):
        with patch(
            "nodes.bigquery_node._bigquery_request",
            return_value={
                "status": "success",
                "data": {"projects": [{"id": "proj-1", "friendlyName": "Project One"}]},
            },
        ):
            result = await BigQueryNode.load_field_options(
                "project_id", _OAUTH_CRED_DATA, context={}
            )
        assert result["options"][0]["value"] == "proj-1"
        assert result["options"][0]["label"] == "Project One"

    @pytest.mark.asyncio
    async def test_load_dataset_options(self):
        with patch(
            "nodes.bigquery_node._bigquery_request",
            return_value={
                "status": "success",
                "data": {"datasets": [{"datasetReference": {"datasetId": "ds1"}}]},
            },
        ):
            result = await BigQueryNode.load_field_options(
                "dataset_id", _OAUTH_CRED_DATA, context={"project_id": "proj-1"}
            )
        assert result["options"][0]["value"] == "ds1"

    @pytest.mark.asyncio
    async def test_load_table_options(self):
        with patch(
            "nodes.bigquery_node._bigquery_request",
            return_value={
                "status": "success",
                "data": {"tables": [{"tableReference": {"tableId": "t1"}}]},
            },
        ):
            result = await BigQueryNode.load_field_options(
                "table_id",
                _OAUTH_CRED_DATA,
                context={"project_id": "proj-1", "dataset_id": "ds1"},
            )
        assert result["options"][0]["value"] == "t1"

    @pytest.mark.asyncio
    async def test_load_job_options(self):
        with patch(
            "nodes.bigquery_node._bigquery_request",
            return_value={
                "status": "success",
                "data": {
                    "jobs": [
                        {
                            "jobReference": {"jobId": "job-1"},
                            "status": {"state": "DONE"},
                        }
                    ]
                },
            },
        ):
            result = await BigQueryNode.load_field_options(
                "job_id", _OAUTH_CRED_DATA, context={"project_id": "proj-1"}
            )
        assert result["options"][0]["value"] == "job-1"
        assert result["options"][0]["label"] == "job-1 (DONE)"

    @pytest.mark.asyncio
    async def test_load_routine_options(self):
        with patch(
            "nodes.bigquery_node._bigquery_request",
            return_value={
                "status": "success",
                "data": {"routines": [{"routineReference": {"routineId": "r1"}}]},
            },
        ):
            result = await BigQueryNode.load_field_options(
                "routine_id",
                _OAUTH_CRED_DATA,
                context={"project_id": "proj-1", "dataset_id": "ds1"},
            )
        assert result["options"][0]["value"] == "r1"

    @pytest.mark.asyncio
    async def test_load_model_options(self):
        with patch(
            "nodes.bigquery_node._bigquery_request",
            return_value={
                "status": "success",
                "data": {"models": [{"modelReference": {"modelId": "m1"}}]},
            },
        ):
            result = await BigQueryNode.load_field_options(
                "model_id",
                _OAUTH_CRED_DATA,
                context={"project_id": "proj-1", "dataset_id": "ds1"},
            )
        assert result["options"][0]["value"] == "m1"

    @pytest.mark.asyncio
    async def test_load_options_no_credential(self):
        result = await BigQueryNode.load_field_options(
            "project_id", {}, context={}
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_dataset_options_service_account(self):
        """A service-account credential mints a token and (when no project is in
        context) falls back to the project from its own key."""
        sa_data = {
            "credential_type": "bigquery_service_account",
            "service_account_json": '{"type":"service_account","project_id":"sa-proj"}',
        }
        with patch(
            "nodes.bigquery_node._mint_service_account_access_token",
            return_value="ya29.sa",
        ), patch(
            "nodes.bigquery_node._project_id_from_credential_data",
            return_value="sa-proj",
        ), patch(
            "nodes.bigquery_node._bigquery_request",
            return_value={
                "status": "success",
                "data": {"datasets": [{"datasetReference": {"datasetId": "ds-sa"}}]},
            },
        ) as mock_req:
            result = await BigQueryNode.load_field_options(
                "dataset_id", sa_data, context={}
            )
        assert result["options"][0]["value"] == "ds-sa"
        # project fell back to the SA key's project in the request path
        assert "sa-proj" in mock_req.call_args[0][2]


def _bq_rows(field, values):
    """Build a BigQuery F/V row envelope for a single-column query result."""
    return {
        "jobComplete": True,
        "schema": {"fields": [{"name": field, "type": "STRING"}]},
        "rows": [{"f": [{"v": v}]} for v in values],
    }


class TestBigQueryTriggerPayloadResolution:
    def test_resolve_trigger_payload_poll_returns_none(self):
        """Poll trigger: webhook POST is a wake-up signal, so execute() must run."""
        payload = {"some": "webhook-body"}
        result = BigQueryNode.resolve_trigger_payload(
            payload, {"operation": "on_query_results"}
        )
        assert result is None

    def test_resolve_trigger_payload_normal_op_passthrough(self):
        """Non-trigger ops keep the incoming payload (push semantics)."""
        payload = {"some": "webhook-body"}
        result = BigQueryNode.resolve_trigger_payload(
            payload, {"operation": "run_query"}
        )
        assert result == payload


async def _run_poll(node, json_data, node_state=None):
    """Run a poll-trigger execute() with HTTP + token mocked and node state
    faked in-memory (mirrors the snowflake test): the concurrency-safe mutator
    is applied to `node_state` and whatever it persists is captured back in
    `result["__saved_state__"]`. `node_state=None` models the FIRST poll (the
    key is absent), which the node baselines instead of flooding."""
    saved: dict = {}

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(node_state or {}))
        if new_state is not None:
            saved.clear()
            saved.update(new_state)
        return result

    node._update_node_state = _update

    mock_client = create_mock_client(200, json_data)
    with patch(
        "nodes.bigquery_node.httpx.AsyncClient", return_value=mock_client
    ), patch.object(BigQueryNode, "_ensure_fresh_token", new=_fake_token):
        result = await node.execute({})
    if isinstance(result, dict):
        result["__saved_state__"] = saved
    return result


class TestBigQueryTriggerPollMock:
    def _make_node(self):
        config = BigQueryNodeConfig(
            config=BigQueryOnQueryResultsConfig(
                project_id="proj-1",
                query="SELECT id FROM `proj-1.ds1.events` ORDER BY id",
                cursor_column="id",
            ),
            credentials=BigQueryOAuthCredential(
                access_token="ya29.test-access-token",
                refresh_token="1//test-refresh-token",
                expires_at="2099-01-01T00:00:00Z",
                email="bq@example.com",
            ),
        )
        return create_bigquery_node(config)

    @pytest.mark.asyncio
    async def test_poll_baselines_on_first_run(self):
        """First poll (no stored cursor) BASELINES: it records the max cursor and
        emits NOTHING, so enabling the trigger never floods the whole result set."""
        node = self._make_node()
        result = await _run_poll(node, _bq_rows("id", ["1", "2", "3"]), node_state=None)

        assert result["status"] == "success"
        assert result["operation"] == "on_query_results"
        assert result["new_count"] == 0
        assert result["items"] == []
        # Cursor is seeded to the max seen id AND persisted, so the NEXT poll only
        # emits rows added after this baseline.
        assert result["last_cursor"] == "3"
        assert result["__saved_state__"] == {"last_cursor": "3"}
        # Baseline emits nothing → downstream is skipped.
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_poll_null_cursor_stays_unbaselined(self):
        """A first poll whose cursor column is null on every row must NOT persist
        a null high-water-mark — that would make the next poll treat every row as
        new and flood. It stays unbaselined (no write) until a real value appears."""
        node = self._make_node()
        result = await _run_poll(node, _bq_rows("id", [None, None]), node_state=None)

        assert result["new_count"] == 0
        assert result["items"] == []
        # Nothing persisted → next poll with real cursors baselines properly.
        assert result["__saved_state__"] == {}
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_poll_dedupes_already_seen_rows_via_cursor(self):
        """Second poll (with a seeded node-state cursor) only emits rows beyond it."""
        node = self._make_node()
        # Query returns rows 1..4; cursor is at 2, so only 3 and 4 are new.
        result = await _run_poll(
            node, _bq_rows("id", ["1", "2", "3", "4"]), node_state={"last_cursor": "2"}
        )

        assert result["new_count"] == 2
        assert [r["id"] for r in result["items"]] == ["3", "4"]
        assert result["last_cursor"] == "4"
        assert result["__saved_state__"] == {"last_cursor": "4"}
        assert node.trigger_produced_no_event(result) is False

    @pytest.mark.asyncio
    async def test_poll_no_new_rows_signals_no_event(self):
        """When every row is at/below the cursor, nothing is emitted, the cursor
        is not rewritten, and the executor is told to skip downstream nodes."""
        node = self._make_node()
        result = await _run_poll(
            node, _bq_rows("id", ["1", "2", "3"]), node_state={"last_cursor": "5"}
        )

        assert result["new_count"] == 0
        assert result["items"] == []
        assert result["last_cursor"] == "5"
        assert result["__saved_state__"] == {}  # nothing new → no write
        assert node.trigger_produced_no_event(result) is True


async def _run_capture(node, status_code=200, json_data=None):
    """Run node.execute with HTTP + token mocked, capturing the request kwargs
    (method/url/json) so tests can assert the exact endpoint that was called."""
    captured = {}
    mock_response = create_mock_response(status_code, json_data)

    async def async_request(*args, **kwargs):
        captured.update(kwargs)
        return mock_response

    mock_client = Mock()
    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *a):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    with patch(
        "nodes.bigquery_node.httpx.AsyncClient", return_value=mock_client
    ), patch.object(BigQueryNode, "_ensure_fresh_token", new=_fake_token):
        result = await node.execute({})
    return result, captured


class TestBigQueryAdditionalOpsMock:
    """New operations added for full v2 coverage, asserting the exact endpoint."""

    @pytest.mark.asyncio
    async def test_delete_job_uses_delete_suffix(self, oauth_credentials):
        """jobs.delete requires a trailing /delete on the resource path."""
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryDeleteJobConfig(project_id="p", job_id="job-9"),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 204, None)
        assert result["status"] == "success"
        assert captured["method"] == "DELETE"
        assert captured["url"].endswith("/projects/p/jobs/job-9/delete")

    @pytest.mark.asyncio
    async def test_undelete_dataset(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryUndeleteDatasetConfig(project_id="p", dataset_id="d"),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"datasetReference": {"datasetId": "d"}})
        assert result["status"] == "success"
        assert captured["method"] == "POST"
        assert captured["url"].endswith("/projects/p/datasets/d:undelete")

    @pytest.mark.asyncio
    async def test_update_routine(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryUpdateRoutineConfig(
                    project_id="p", dataset_id="d", routine_id="r",
                    resource='{"definitionBody": "x + 1"}',
                ),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"routineReference": {"routineId": "r"}})
        assert result["status"] == "success"
        assert captured["method"] == "PUT"
        assert captured["url"].endswith("/projects/p/datasets/d/routines/r")

    @pytest.mark.asyncio
    async def test_delete_routine(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryDeleteRoutineConfig(project_id="p", dataset_id="d", routine_id="r"),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 204, None)
        assert result["status"] == "success"
        assert captured["method"] == "DELETE"
        assert captured["url"].endswith("/projects/p/datasets/d/routines/r")

    @pytest.mark.asyncio
    async def test_patch_model(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryPatchModelConfig(
                    project_id="p", dataset_id="d", model_id="m",
                    resource='{"description": "x"}',
                ),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"modelReference": {"modelId": "m"}})
        assert result["status"] == "success"
        assert captured["method"] == "PATCH"
        assert captured["url"].endswith("/projects/p/datasets/d/models/m")

    @pytest.mark.asyncio
    async def test_get_table_iam_policy(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryGetTableIamPolicyConfig(project_id="p", dataset_id="d", table_id="t"),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"version": 1})
        assert result["status"] == "success"
        assert captured["method"] == "POST"
        assert captured["url"].endswith("/projects/p/datasets/d/tables/t:getIamPolicy")

    @pytest.mark.asyncio
    async def test_set_table_iam_policy(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQuerySetTableIamPolicyConfig(
                    project_id="p", dataset_id="d", table_id="t",
                    policy='{"bindings": []}',
                ),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"version": 1})
        assert result["status"] == "success"
        assert captured["url"].endswith("/projects/p/datasets/d/tables/t:setIamPolicy")
        assert captured["json"]["policy"] == {"bindings": []}

    @pytest.mark.asyncio
    async def test_test_table_iam_permissions(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryTestTableIamPermissionsConfig(
                    project_id="p", dataset_id="d", table_id="t",
                    permissions='["bigquery.tables.get"]',
                ),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"permissions": ["bigquery.tables.get"]})
        assert result["status"] == "success"
        assert captured["url"].endswith("/projects/p/datasets/d/tables/t:testIamPermissions")
        assert captured["json"]["permissions"] == ["bigquery.tables.get"]

    @pytest.mark.asyncio
    async def test_list_row_access_policies(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryListRowAccessPoliciesConfig(project_id="p", dataset_id="d", table_id="t"),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"rowAccessPolicies": []})
        assert result["status"] == "success"
        assert captured["method"] == "GET"
        assert captured["url"].endswith("/projects/p/datasets/d/tables/t/rowAccessPolicies")

    @pytest.mark.asyncio
    async def test_get_row_access_policy(self, oauth_credentials):
        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryGetRowAccessPolicyConfig(
                    project_id="p", dataset_id="d", table_id="t", policy_id="rap1",
                ),
                credentials=oauth_credentials,
            )
        )
        result, captured = await _run_capture(node, 200, {"rowAccessPolicyReference": {"policyId": "rap1"}})
        assert result["status"] == "success"
        assert captured["url"].endswith("/projects/p/datasets/d/tables/t/rowAccessPolicies/rap1")


class TestBigQueryServiceAccountAuthMock:
    """Service-account credential mode mints a token and runs like OAuth."""

    @pytest.mark.asyncio
    async def test_service_account_execute(self):
        from nodes.bigquery_node import BigQueryServiceAccountCredential

        node = create_bigquery_node(
            BigQueryNodeConfig(
                config=BigQueryRunQueryConfig(project_id="p", query="SELECT 1"),
                credentials=BigQueryServiceAccountCredential(
                    service_account_json='{"type":"service_account","project_id":"p"}'
                ),
            )
        )
        mock_client = create_mock_client(200, {"rows": [{"f": [{"v": "1"}]}]})
        with patch(
            "nodes.bigquery_node.httpx.AsyncClient", return_value=mock_client
        ), patch(
            "nodes.bigquery_node._mint_service_account_access_token",
            new=_fake_token,
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "run_query"
