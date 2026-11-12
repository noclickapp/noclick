"""Seqera Cloud pipeline and workflow automation using a personal access token.

Wire operations follow the published Seqera API 1.257.0 contract. Lists return
one provider page; callers choose offsets explicitly. Writes are never retried.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.cloud.seqera.io"
CREDENTIAL_TYPE = "seqera_api_token"


class SeqeraAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Seqera API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://cloud.seqera.io/tokens",
            "x-credential-instructions": "In Seqera Cloud, open your user menu, choose Your tokens and create an access token. Copy it here. NoClick uses the token to read your account and run the operations you select with your permissions. Launching workflows consumes your compute resources.",
        })
    credential_type: Literal["seqera_api_token"] = Field("seqera_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal access token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Seqera token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_ids(cls, value, info):
        if info.field_name in {"workflow_id", "compute_env_id", "dataset_id"} and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Use a single Seqera resource identifier")
        return value


class _Workspace(_Input):
    workspace_id: int | None = Field(None, ge=1, description="Workspace ID. Omit to use your personal workspace.")


class _Page(_Workspace):
    max_results: int = Field(50, ge=1, le=100, description="Maximum results in this page.")
    offset: int = Field(0, ge=0, description="Number of records to skip. Increase by the previous page size.")
    search: str | None = Field(None, max_length=2000, description="Provider search query.")


class SeqeraLaunch(_Input):
    pipeline: str = Field(..., min_length=1, description="Pipeline repository URL or pipeline name.")
    compute_env_id: str = Field(..., alias="computeEnvId", min_length=1)
    work_dir: str = Field(..., alias="workDir", min_length=1, description="Cloud work directory, for example s3://your-bucket/work.")
    revision: str | None = None
    run_name: str | None = Field(None, alias="runName")
    params_text: str | None = Field(None, alias="paramsText", description="Nextflow parameters as JSON or YAML text.")
    config_profiles: list[str] | None = Field(None, alias="configProfiles")
    config_text: str | None = Field(None, alias="configText")
    resume: bool | None = None
    session_id: str | None = Field(None, alias="sessionId")
    nextflow_version: str | None = Field(None, alias="nextflowVersion")


class SeqeraGetUserConfig(_Input):
    """Get user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})


class SeqeraListOrganizationsConfig(_Input):
    """List organizations."""
    operation: Literal["list_organizations"] = Field("list_organizations", json_schema_extra={"ui:hidden": True})


class SeqeraListWorkspacesConfig(_Input):
    """List workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})
    org_id: int = Field(..., ge=1)


class SeqeraListPipelinesConfig(_Page):
    """List pipelines."""
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra={"ui:hidden": True})


class SeqeraGetPipelineConfig(_Workspace):
    """Get pipeline."""
    operation: Literal["get_pipeline"] = Field("get_pipeline", json_schema_extra={"ui:hidden": True})
    pipeline_id: int = Field(..., ge=1)


class SeqeraGetPipelineLaunchConfig(_Workspace):
    """Get pipeline launch."""
    operation: Literal["get_pipeline_launch"] = Field("get_pipeline_launch", json_schema_extra={"ui:hidden": True})
    pipeline_id: int = Field(..., ge=1)


class SeqeraCreatePipelineConfig(_Workspace):
    """Create pipeline."""
    operation: Literal["create_pipeline"] = Field("create_pipeline", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    launch: SeqeraLaunch


class SeqeraUpdatePipelineConfig(_Workspace):
    """Update pipeline."""
    operation: Literal["update_pipeline"] = Field("update_pipeline", json_schema_extra={"ui:hidden": True})
    pipeline_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class SeqeraDeletePipelineConfig(_Workspace):
    """Delete pipeline."""
    operation: Literal["delete_pipeline"] = Field("delete_pipeline", json_schema_extra={"ui:hidden": True})
    pipeline_id: int = Field(..., ge=1)


class SeqeraLaunchWorkflowConfig(_Workspace):
    """Launch workflow."""
    operation: Literal["launch_workflow"] = Field("launch_workflow", json_schema_extra={"ui:hidden": True})
    launch: SeqeraLaunch


class SeqeraListWorkflowsConfig(_Page):
    """List workflows."""
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra={"ui:hidden": True})


class SeqeraGetWorkflowConfig(_Workspace):
    """Get workflow."""
    operation: Literal["get_workflow"] = Field("get_workflow", json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(..., min_length=1)


class SeqeraCancelWorkflowConfig(_Workspace):
    """Cancel workflow."""
    operation: Literal["cancel_workflow"] = Field("cancel_workflow", json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(..., min_length=1)
    force: bool = Field(False, description="Also cancel on Platform if the compute provider cannot cancel it.")


class SeqeraGetWorkflowProgressConfig(_Workspace):
    """Get workflow progress."""
    operation: Literal["get_workflow_progress"] = Field("get_workflow_progress", json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(..., min_length=1)


class SeqeraListWorkflowTasksConfig(_Page):
    """List workflow tasks."""
    operation: Literal["list_workflow_tasks"] = Field("list_workflow_tasks", json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(..., min_length=1)


class SeqeraListComputeEnvironmentsConfig(_Workspace):
    """List compute environments."""
    operation: Literal["list_compute_environments"] = Field("list_compute_environments", json_schema_extra={"ui:hidden": True})
    status: str | None = None


class SeqeraGetComputeEnvironmentConfig(_Workspace):
    """Get compute environment."""
    operation: Literal["get_compute_environment"] = Field("get_compute_environment", json_schema_extra={"ui:hidden": True})
    compute_env_id: str = Field(..., min_length=1)


class SeqeraListDatasetsConfig(_Page):
    """List datasets."""
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={"ui:hidden": True})


class SeqeraCreateDatasetConfig(_Workspace):
    """Create dataset."""
    operation: Literal["create_dataset"] = Field("create_dataset", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    source_type: Literal["UPLOADED", "LINKED"] = "UPLOADED"


class SeqeraDeleteDatasetConfig(_Workspace):
    """Delete dataset."""
    operation: Literal["delete_dataset"] = Field("delete_dataset", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1)


class SeqeraListLabelsConfig(_Page):
    """List labels."""
    operation: Literal["list_labels"] = Field("list_labels", json_schema_extra={"ui:hidden": True})


class SeqeraCreateLabelConfig(_Workspace):
    """Create label."""
    operation: Literal["create_label"] = Field("create_label", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)


# Seqera's own MCP server: agents get its tools through a person's Seqera sign-in.
SeqeraMcpCredential = mcp_credential("seqera", "https://mcp.seqera.io/mcp", app="Seqera")
SeqeraCredential = Union[SeqeraAPITokenCredential, SeqeraMcpCredential]


SeqeraConfig = Annotated[Union[
    SeqeraGetUserConfig,
    SeqeraListOrganizationsConfig,
    SeqeraListWorkspacesConfig,
    SeqeraListPipelinesConfig,
    SeqeraGetPipelineConfig,
    SeqeraGetPipelineLaunchConfig,
    SeqeraCreatePipelineConfig,
    SeqeraUpdatePipelineConfig,
    SeqeraDeletePipelineConfig,
    SeqeraLaunchWorkflowConfig,
    SeqeraListWorkflowsConfig,
    SeqeraGetWorkflowConfig,
    SeqeraCancelWorkflowConfig,
    SeqeraGetWorkflowProgressConfig,
    SeqeraListWorkflowTasksConfig,
    SeqeraListComputeEnvironmentsConfig,
    SeqeraGetComputeEnvironmentConfig,
    SeqeraListDatasetsConfig,
    SeqeraCreateDatasetConfig,
    SeqeraDeleteDatasetConfig,
    SeqeraListLabelsConfig,
    SeqeraCreateLabelConfig
], Field(discriminator="operation")]


class SeqeraFullConfig(NodeConfig[SeqeraConfig, SeqeraCredential]):
    pass


ROUTES = {'get_user': ('GET', '/user-info', {}, None),
 'list_organizations': ('GET', '/orgs', {}, None),
 'list_workspaces': ('GET', '/orgs/{org_id}/workspaces', {}, None),
 'list_pipelines': ('GET', '/pipelines', {}, None),
 'get_pipeline': ('GET', '/pipelines/{pipeline_id}', {}, None),
 'get_pipeline_launch': ('GET', '/pipelines/{pipeline_id}/launch', {}, None),
 'create_pipeline': ('POST', '/pipelines', {}, 'pipeline'),
 'update_pipeline': ('PUT', '/pipelines/{pipeline_id}', {}, 'pipeline'),
 'delete_pipeline': ('DELETE', '/pipelines/{pipeline_id}', {}, None),
 'launch_workflow': ('POST', '/workflow/launch', {}, 'launch'),
 'list_workflows': ('GET', '/workflow', {}, None),
 'get_workflow': ('GET', '/workflow/{workflow_id}', {}, None),
 'cancel_workflow': ('POST', '/workflow/{workflow_id}/cancel', {'force': 'force'}, 'empty'),
 'get_workflow_progress': ('GET', '/workflow/{workflow_id}/progress', {}, None),
 'list_workflow_tasks': ('GET', '/workflow/{workflow_id}/tasks', {}, None),
 'list_compute_environments': ('GET', '/compute-envs', {'status': 'status'}, None),
 'get_compute_environment': ('GET', '/compute-envs/{compute_env_id}', {}, None),
 'list_datasets': ('GET', '/datasets', {}, None),
 'create_dataset': ('POST', '/datasets', {}, 'dataset'),
 'delete_dataset': ('DELETE', '/datasets/{dataset_id}', {}, None),
 'list_labels': ('GET', '/labels', {}, None),
 'create_label': ('POST', '/labels', {}, 'label')}


class SeqeraNode(WorkflowNode):
    integration_type = "automation-seqera"
    credential_provider_labels = {"seqera": "Seqera Account"}
    connection_evidence = ConnectionEvidence(identity_operation="get_user", noun="Seqera account")

    @classmethod
    def get_config_model(cls):
        return SeqeraFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Seqera API token")
        op = self.config.config
        method, path, extra_query, body_kind = ROUTES[op.operation]
        fields = op.model_dump(exclude_none=True)
        for key, value in fields.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {}
        if isinstance(op, _Workspace) and op.workspace_id is not None:
            params["workspaceId"] = op.workspace_id
        if isinstance(op, _Page):
            params.update({"max": op.max_results, "offset": op.offset})
            if op.search is not None:
                params["search"] = op.search
        for key, wire in extra_query.items():
            if fields.get(key) is not None:
                value = fields[key]
                params[wire] = str(value).lower() if isinstance(value, bool) else value
        body = None
        if body_kind == "empty":
            body = {}
        elif body_kind == "launch":
            body = {"launch": op.launch.model_dump(by_alias=True, exclude_none=True)}
        elif body_kind == "pipeline":
            body = {"name": op.name}
            if op.description is not None:
                body["description"] = op.description
            if isinstance(op, SeqeraCreatePipelineConfig):
                body["launch"] = op.launch.model_dump(by_alias=True, exclude_none=True)
        elif body_kind == "dataset":
            body = {"name": op.name, "sourceType": op.source_type}
            if op.description is not None:
                body["description"] = op.description
        elif body_kind == "label":
            body = {"name": op.name, "resource": False}
        token = self.config.credentials.api_token
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json", "Accept-Version": "1"},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = "Seqera request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000].replace(token, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "acknowledged": True}
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Expected a Seqera JSON object")
        if "error" in result or "errors" in result:
            return {"status": "error", "error": "Seqera returned an error envelope"}
        return {"status": "success", **result}
