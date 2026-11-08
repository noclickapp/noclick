"""DataRobot Public API 2.50: one documented request per operation.

Uses a personal API token on app.datarobot.com. Collection reads return one
page; callers advance offset explicitly. Acknowledged writes are not read back,
and project creation is asynchronous. No prediction data is downloaded.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.datarobot.com"


class DataRobotAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="DataRobot API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.datarobot.com/en/docs/api/dev-learning/api-quickstart.html",
            "x-credential-instructions": "In DataRobot, select the user icon, then API keys and tools. Under Personal API keys, create or copy a key. Paste it here without the Bearer prefix. This integration connects to app.datarobot.com. Project access confirms the connection; each write still needs the corresponding account permission.",
        },
    )
    credential_type: Literal["datarobot_api_token"] = Field("datarobot_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not value or len(value) > 200 or any(c in value for c in "/\\?#%") or any(c.isspace() or ord(c) < 33 for c in value) or value in {".", ".."}:
                raise ValueError("Use a single DataRobot resource ID")
        return value


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100, description="Maximum records in this page. Use offset to retrieve another page.")
    offset: int = Field(0, ge=0, description="Number of records to skip; pagination links are returned as data and never followed.")


class _Project(_Input):
    project_id: str = Field(..., min_length=1, title="Project ID")


class _Model(_Project):
    model_id: str = Field(..., min_length=1, title="Model ID")


class _Dataset(_Input):
    dataset_id: str = Field(..., min_length=1, title="Dataset ID")


class _Deployment(_Input):
    deployment_id: str = Field(..., min_length=1, title="Deployment ID")


class _UseCase(_Input):
    use_case_id: str = Field(..., min_length=1, title="Use Case ID")


class DataRobotListProjects(_Page):
    """List projects."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})
    project_name: Optional[str] = Field(None, title="Project name filter")


class DataRobotGetProject(_Project):
    """Get project."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class DataRobotCreateProject(_Input):
    """Create project."""
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, description="Existing AI Catalog dataset to import. Creation starts an asynchronous ingestion job.")
    project_name: Optional[str] = Field(None, max_length=100)


class DataRobotUpdateProject(_Project):
    """Update project."""
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"ui:hidden": True})
    project_name: str = Field(..., min_length=1, max_length=100)
    project_description: Optional[str] = Field(None, max_length=500)


class DataRobotDeleteProject(_Project):
    """Delete the selected project and its models. This cannot be undone."""
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"ui:hidden": True})


class DataRobotGetProjectStatus(_Project):
    """Get project status."""
    operation: Literal["get_project_status"] = Field("get_project_status", json_schema_extra={"ui:hidden": True})


class DataRobotListModels(_Project):
    """List models."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = None
    order_by: Optional[Literal["metric", "-metric", "samplePct", "-samplePct"]] = None


class DataRobotGetModel(_Model):
    """Get model."""
    operation: Literal["get_model"] = Field("get_model", json_schema_extra={"ui:hidden": True})


class DataRobotUpdateModel(_Model):
    """Update model."""
    operation: Literal["update_model"] = Field("update_model", json_schema_extra={"ui:hidden": True})
    is_starred: StrictBool = Field(..., description="Star or unstar the selected model.")
    prediction_threshold: Optional[float] = Field(None, ge=0, le=1, description="Binary classification threshold.")


class DataRobotDeleteModel(_Model):
    """Delete model."""
    operation: Literal["delete_model"] = Field("delete_model", json_schema_extra={"ui:hidden": True})


class DataRobotListFeatures(_Project):
    """List features."""
    operation: Literal["list_features"] = Field("list_features", json_schema_extra={"ui:hidden": True})
    search_for: Optional[str] = Field(None, description="Feature name substring filter.")


class DataRobotListDatasets(_Page):
    """List datasets."""
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={"ui:hidden": True})
    category: Optional[Literal["TRAINING", "PREDICTION", "SAMPLE"]] = None


class DataRobotGetDataset(_Dataset):
    """Get dataset."""
    operation: Literal["get_dataset"] = Field("get_dataset", json_schema_extra={"ui:hidden": True})


class DataRobotUpdateDataset(_Dataset):
    """Update dataset."""
    operation: Literal["update_dataset"] = Field("update_dataset", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="New dataset name")


class DataRobotDeleteDataset(_Dataset):
    """Delete dataset."""
    operation: Literal["delete_dataset"] = Field("delete_dataset", json_schema_extra={"ui:hidden": True})


class DataRobotListDeployments(_Page):
    """List deployments."""
    operation: Literal["list_deployments"] = Field("list_deployments", json_schema_extra={"ui:hidden": True})
    search: Optional[str] = Field(None, max_length=100)


class DataRobotGetDeployment(_Deployment):
    """Get deployment."""
    operation: Literal["get_deployment"] = Field("get_deployment", json_schema_extra={"ui:hidden": True})


class DataRobotUpdateDeployment(_Deployment):
    """Update deployment."""
    operation: Literal["update_deployment"] = Field("update_deployment", json_schema_extra={"ui:hidden": True})
    label: str = Field(..., min_length=1, max_length=512)
    description: Optional[str] = Field(None, max_length=10000)
    importance: Optional[Literal["CRITICAL", "HIGH", "MODERATE", "LOW"]] = None


class DataRobotListUseCases(_Page):
    """List use cases."""
    operation: Literal["list_use_cases"] = Field("list_use_cases", json_schema_extra={"ui:hidden": True})
    search: Optional[str] = None


class DataRobotGetUseCase(_UseCase):
    """Get use case."""
    operation: Literal["get_use_case"] = Field("get_use_case", json_schema_extra={"ui:hidden": True})


class DataRobotCreateUseCase(_Input):
    """Create use case."""
    operation: Literal["create_use_case"] = Field("create_use_case", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class DataRobotUpdateUseCase(_UseCase):
    """Update use case."""
    operation: Literal["update_use_case"] = Field("update_use_case", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class DataRobotDeleteUseCase(_UseCase):
    """Delete use case."""
    operation: Literal["delete_use_case"] = Field("delete_use_case", json_schema_extra={"ui:hidden": True})


DataRobotOperation = Annotated[Union[
    DataRobotListProjects,
    DataRobotGetProject,
    DataRobotCreateProject,
    DataRobotUpdateProject,
    DataRobotDeleteProject,
    DataRobotGetProjectStatus,
    DataRobotListModels,
    DataRobotGetModel,
    DataRobotUpdateModel,
    DataRobotDeleteModel,
    DataRobotListFeatures,
    DataRobotListDatasets,
    DataRobotGetDataset,
    DataRobotUpdateDataset,
    DataRobotDeleteDataset,
    DataRobotListDeployments,
    DataRobotGetDeployment,
    DataRobotUpdateDeployment,
    DataRobotListUseCases,
    DataRobotGetUseCase,
    DataRobotCreateUseCase,
    DataRobotUpdateUseCase,
    DataRobotDeleteUseCase,
], Field(discriminator="operation")]


class DataRobotConfig(NodeConfig[DataRobotOperation, DataRobotAPITokenCredential]):
    pass


# method, path, body fields, query fields, documented success status.
OPERATIONS = {
    'list_projects': ('GET', '/api/v2/projects/', {}, {'limit': 'limit', 'offset': 'offset', 'project_name': 'projectName'}, 200),
    'get_project': ('GET', '/api/v2/projects/{project_id}/', {}, {}, 200),
    'create_project': ('POST', '/api/v2/projects/', {'dataset_id': 'datasetId', 'project_name': 'projectName'}, {}, 202),
    'update_project': ('PATCH', '/api/v2/projects/{project_id}/', {'project_name': 'projectName', 'project_description': 'projectDescription'}, {}, 200),
    'delete_project': ('DELETE', '/api/v2/projects/{project_id}/', {}, {}, 204),
    'get_project_status': ('GET', '/api/v2/projects/{project_id}/status/', {}, {}, 200),
    'list_models': ('GET', '/api/v2/projects/{project_id}/models/', {}, {'name': 'name', 'order_by': 'orderBy'}, 200),
    'get_model': ('GET', '/api/v2/projects/{project_id}/models/{model_id}/', {}, {}, 200),
    'update_model': ('PATCH', '/api/v2/projects/{project_id}/models/{model_id}/', {'is_starred': 'isStarred', 'prediction_threshold': 'predictionThreshold'}, {}, 204),
    'delete_model': ('DELETE', '/api/v2/projects/{project_id}/models/{model_id}/', {}, {}, 204),
    'list_features': ('GET', '/api/v2/projects/{project_id}/features/', {}, {'search_for': 'searchFor'}, 200),
    'list_datasets': ('GET', '/api/v2/datasets/', {}, {'limit': 'limit', 'offset': 'offset', 'category': 'category'}, 200),
    'get_dataset': ('GET', '/api/v2/datasets/{dataset_id}/', {}, {}, 200),
    'update_dataset': ('PATCH', '/api/v2/datasets/{dataset_id}/', {'name': 'name'}, {}, 200),
    'delete_dataset': ('DELETE', '/api/v2/datasets/{dataset_id}/', {}, {}, 204),
    'list_deployments': ('GET', '/api/v2/deployments/', {}, {'limit': 'limit', 'offset': 'offset', 'search': 'search'}, 200),
    'get_deployment': ('GET', '/api/v2/deployments/{deployment_id}/', {}, {}, 200),
    'update_deployment': ('PATCH', '/api/v2/deployments/{deployment_id}/', {'label': 'label', 'description': 'description', 'importance': 'importance'}, {}, 204),
    'list_use_cases': ('GET', '/api/v2/useCases/', {}, {'limit': 'limit', 'offset': 'offset', 'search': 'search'}, 200),
    'get_use_case': ('GET', '/api/v2/useCases/{use_case_id}/', {}, {}, 200),
    'create_use_case': ('POST', '/api/v2/useCases/', {'name': 'name', 'description': 'description'}, {}, 200),
    'update_use_case': ('PATCH', '/api/v2/useCases/{use_case_id}/', {'name': 'name', 'description': 'description'}, {}, 204),
    'delete_use_case': ('DELETE', '/api/v2/useCases/{use_case_id}/', {}, {}, 204),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class DataRobotNode(WorkflowNode):
    integration_type = "automation-datarobot"
    connection_evidence = ConnectionEvidence(
        noun="projects", operation="list_projects", label_keys=("projectName", "name", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return DataRobotConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a DataRobot API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, template, body_fields, query_fields, success_status = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        path = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {target: values[source] for source, target in query_fields.items() if source in values}
        if op.operation == "list_use_cases":
            # Both ordering fields and usecaseType are required in the pinned contract.
            params.update(sort="id", orderBy="id", usecaseType="all")
        body = {target: values[source] for source, target in body_fields.items() if source in values}
        kwargs = {"params": params, "headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}}
        if body_fields:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, **kwargs)
        except Exception:
            # A write may already have been accepted; do not retry automatically.
            raise ValueError("DataRobot request could not be confirmed; inspect writes before retrying") from None
        if response.status_code != success_status:
            output = {"status": "error", "success": False, "status_code": response.status_code,
                      "message": _redact(response.text[:4000], token) or "DataRobot request was not confirmed"}
        else:
            data = None
            if response.status_code != 204 and response.content:
                if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Expected bounded DataRobot JSON; write outcome may require inspection")
                try:
                    data = response.json()
                except ValueError:
                    raise ValueError("DataRobot returned invalid JSON; write outcome may require inspection") from None
                if not isinstance(data, (dict, list)):
                    raise ValueError("Expected a DataRobot JSON object or list")
            elif method == "GET" or op.operation in {"create_project", "create_use_case", "update_dataset"}:
                raise ValueError("DataRobot returned no JSON data")
            output = {"status": "success", "success": True, "operation": op.operation,
                      "status_code": response.status_code, "data": _redact(data, token)}
            if method != "GET":
                output.update(request_accepted=True, readback_verified=False)
                if response.status_code == 202:
                    output.update(pending=True, completed=False)
        await self.emit(output)
        return output
