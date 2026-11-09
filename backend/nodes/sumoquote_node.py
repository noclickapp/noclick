"""SumoQuote public API v2: one documented request per operation.

API keys are generated in SumoQuote and sent only to api.sumoquote.com.
List results expose the provider continuation token; no implicit pagination.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SumoQuoteAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SumoQuote API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.sumoquote.com/",
            "x-credential-instructions": "Generate an API key in your SumoQuote account and paste it here. NoClick sends it in the sq-api-key header to the SumoQuote API.",
        })
    credential_type: Literal["sumoquote_api_key"] = Field("sumoquote_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def check_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    continuation: str | None = Field(None, title="Continuation token", description="The continuation value returned by the previous page; sent as X-SQ-Continuation.")


class SearchProjects(_Page):
    operation: Literal["search_projects"] = Field("search_projects", title="Search Projects", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, title="Search", description="Search projects across SumoQuote users in your account.")


class ListProjects(_Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List User Projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., min_length=1, title="Project ID", description="Project ID accepted by SumoQuote.")


class _Project(_Input):
    project_id: UUID = Field(..., title="Project UUID")


class DeleteProject(_Project):
    operation: Literal["delete_project"] = Field("delete_project", title="Delete Project", description="Delete the selected project.", json_schema_extra={"ui:hidden": True})


class ListReports(_Project, _Page):
    operation: Literal["list_reports"] = Field("list_reports", title="List Project Reports", json_schema_extra={"ui:hidden": True})


class _Report(_Project):
    report_id: UUID = Field(..., title="Report UUID")


class GetReport(_Report):
    operation: Literal["get_report"] = Field("get_report", title="Get Report", json_schema_extra={"ui:hidden": True})


class GetSignatureDetails(_Report):
    operation: Literal["get_signature_details"] = Field("get_signature_details", title="Get Report Signature Details", json_schema_extra={"ui:hidden": True})


class DownloadReport(_Report):
    operation: Literal["download_report"] = Field("download_report", title="Get Report PDF Download URL", description="Return the provider fileUrl without downloading or following it.", json_schema_extra={"ui:hidden": True})


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})


class GetProfile(_Input):
    operation: Literal["get_profile"] = Field("get_profile", title="Get My Profile", json_schema_extra={"ui:hidden": True})


class SumoMetadata(_Input):
    key: str | None = None
    value: str | None = None


class ProjectIntegration(_Input):
    companyCamProjectId: str | None = None
    jobNimbusProjectId: str | None = None
    jobNimbusProjectType: str | None = None
    jobProgressProjectId: str | None = None
    jobProgressProjectType: str | None = None
    acculynxJobId: str | None = None
    dynamicProjectId: str | None = None
    roofLinkProjectId: str | None = None
    hoverProjectId: str | None = None
    roofleProjectId: str | None = None


class CreateProject(_Input):
    operation: Literal["create_project"] = Field("create_project", title="Create Project", json_schema_extra={"ui:hidden": True})
    id: str | None = None
    projectId: str | None = None
    customerFirstName: str = Field(..., min_length=1)
    customerLastName: str | None = None
    phoneNumber: str | None = None
    emailAddress: str | None = None
    addressLine1: str = Field(..., min_length=1)
    addressLine2: str | None = None
    city: str | None = None
    province: str | None = None
    postalCode: str | None = None
    projectIntegration: ProjectIntegration | None = None
    salespersonId: str | None = None
    layoutId: str | None = None
    salespersonEmail: str | None = None
    intakeDate: datetime | None = None
    metadata: list[SumoMetadata] | None = None
    projectType: Literal[0, 1] | None = None
    companyName: str | None = None


class UpdateProject(_Project):
    operation: Literal["update_project"] = Field("update_project", title="Update Project", description="Update supplied fields; omitted or empty fields keep their existing values.", json_schema_extra={"ui:hidden": True})
    id: UUID | None = None
    customerFirstName: str | None = None
    customerLastName: str | None = None
    postalCode: str | None = None
    city: str | None = None
    addressLine1: str | None = None
    province: str | None = None
    emailAddress: str | None = None
    phoneNumber: str | None = None
    intakeDate: datetime | None = None
    nextCallback: datetime | None = None
    wonDate: datetime | None = None
    lostDate: datetime | None = None
    estimate: float | None = None
    estimator: str | None = None
    salesperson: str | None = None
    estimatorId: str | None = None
    primaryContact: str | None = None
    primaryContactId: str | None = None
    projectState: str | None = None
    metadata: list[SumoMetadata] | None = None


Operation = Annotated[Union[SearchProjects, ListProjects, GetProject, CreateProject,
    UpdateProject, DeleteProject, ListReports, GetReport, GetSignatureDetails,
    DownloadReport, ListUsers, GetProfile], Field(discriminator="operation")]


class SumoQuoteConfig(NodeConfig[Operation, SumoQuoteAPIKeyCredential]):
    pass


class SumoQuoteNode(WorkflowNode):
    integration_type = "automation-sumoquote"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return SumoQuoteConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a SumoQuote API key")
        config = self.config.config
        operation = config.operation
        method, path = "GET", "/v2/Project"
        params, body = {}, None
        if operation == "search_projects":
            if config.q is not None:
                params["q"] = config.q
        elif operation == "list_projects":
            path += "/all"
        elif operation == "create_project":
            method = "POST"
            body = config.model_dump(mode="json", exclude={"operation"}, exclude_unset=True)
        elif operation in {"get_project", "update_project", "delete_project"}:
            path += "/" + quote(str(config.project_id), safe="")
            if operation == "update_project":
                method = "PUT"
                body = config.model_dump(mode="json", exclude={"operation", "project_id"}, exclude_unset=True)
            elif operation == "delete_project":
                method = "DELETE"
        elif operation in {"list_reports", "get_report", "get_signature_details", "download_report"}:
            path += "/" + str(config.project_id) + "/Report"
            if operation != "list_reports":
                path += "/" + str(config.report_id)
                path += {"get_report": "", "get_signature_details": "/signingDetail", "download_report": "/download"}[operation]
        elif operation == "list_users":
            path = "/v2/User"
        elif operation == "get_profile":
            path = "/v2/User/me"
        else:
            raise ValueError("Unsupported SumoQuote operation")
        key = self.config.credentials.api_key
        headers = {"sq-api-key": key, "Accept": "application/json"}
        continuation = getattr(config, "continuation", None)
        if continuation is not None:
            headers["X-SQ-Continuation"] = continuation
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.sumoquote.com" + path,
                headers=headers, params=params, **({"json": body} if body is not None else {}))
        if not response.is_success:
            # Preserve the provider rejection for connection evidence; do not echo the key.
            raise ValueError(f"SumoQuote HTTP {response.status_code}: {response.text.replace(key, '[redacted]')[:2000]}")
        if response.status_code == 204:
            return {"status": "success", "operation": operation, "http_status": 204}
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("SumoQuote returned an invalid JSON envelope")
        if result.get("errors"):
            raise ValueError(str(result["errors"]).replace(key, "[redacted]"))
        return {**result, "status": "success", "operation": operation, "http_status": response.status_code}
