"""POMA Grill v3 document ingestion, retrieval, projects and job automation.

Contract: https://api.poma-ai.com/api/v3/openapi.yaml (version 3.0.0).
Each operation sends one request; asynchronous ingestion and best-effort job
removal are acknowledgements, not claims of completed processing/deletion.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.poma-ai.com/v3"


class PomaGrillAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Poma Grill API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.poma-ai.com",
            "x-credential-instructions": "Paste an existing account API key generated with POST /generateApiKey. POMA recommends this over a short-lived session token. Account keys support the account, project and job operations; protected Grill projects require a project key. NoClick never generates or rotates your key."
        })
    credential_type: Literal["poma_grill_api_key"] = Field("poma_grill_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _ProjectScope(_Operation):
    project_id: UUID | None = Field(None, description="X-Project-ID for account credentials. Omit to use the account's default Grill project. Protected projects require a project API key.")


class _Document(_ProjectScope):
    doc_id: str = Field(..., min_length=1, max_length=512, description="Document identifier returned by Grill.")

    @field_validator("doc_id")
    @classmethod
    def path_identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use the document identifier returned by Grill")
        return value


class _Project(_Operation):
    project_id: UUID = Field(..., description="Project UUID, not the display name.")


class _Job(_Operation):
    job_id: UUID = Field(..., description="Processing job UUID returned by ingestion.")


class _Usage(_Operation):
    chart: bool = False
    chart_resolution: Literal["week", "month", "billing_period"] = "week"
    chart_product: Literal["all", "grill", "primecut"] = "all"


class AttributeFilter(_Operation):
    attr: str = Field(..., min_length=1)
    op: str = Field(..., min_length=1)
    value: Any = None


class _Search(_ProjectScope):
    query: str = Field(..., min_length=1, max_length=100000)
    format: Literal["json", "prompt_ready"] = "json"
    target_tokens: int = Field(5000, ge=100, le=500000)
    max_tokens: int = Field(15000, ge=100, le=500000)
    min_relevance: float | None = Field(None, ge=0, le=1)
    doc_ids: list[str] | None = None
    exclude_doc_ids: list[str] | None = None
    attribute_filters: list[AttributeFilter] | None = Field(None, max_length=32,
        description="AND-combined typed filters: attr, op, value. List attributes before choosing names; unknown names match nothing.")


class GetAccount(_Operation):
    """Retrieve account identity without exposing the API key."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class GetUsage(_Usage):
    """Read account usage and optional charts."""
    operation: Literal["get_usage"] = Field("get_usage", json_schema_extra={"ui:hidden": True})


class IngestDocument(_ProjectScope):
    """Submit a public document URL for asynchronous Grill ingestion."""
    operation: Literal["ingest_document"] = Field("ingest_document", json_schema_extra={"ui:hidden": True})
    remote_url: HttpUrl = Field(..., description="Public document URL for POMA to fetch through X-Remote-URL.")


class Search(_Search):
    """Search the selected Grill project for RAG context."""
    operation: Literal["search"] = Field("search", json_schema_extra={"ui:hidden": True})


class SearchDocument(_Search):
    """Search within one document."""
    operation: Literal["search_document"] = Field("search_document", json_schema_extra={"ui:hidden": True})
    doc_filter: str = Field(..., min_length=1, max_length=512)


class ListAttributes(_ProjectScope):
    """List typed attribute names in the Grill namespace."""
    operation: Literal["list_attributes"] = Field("list_attributes", json_schema_extra={"ui:hidden": True})


class ListDocuments(_ProjectScope):
    """Read one page of document metadata; pass next_cursor to continue."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, ge=1, le=500)
    cursor: str | None = Field(None, max_length=4096)


class GetDocument(_Document):
    """Retrieve document metadata."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})


class UpdateDocumentAttributes(_Document):
    """Set or remove attributes; null removes a value, omitted names stay unchanged."""
    operation: Literal["update_document_attributes"] = Field("update_document_attributes", json_schema_extra={"ui:hidden": True})
    attributes: dict[str, Any] = Field(..., description="Patch map. Null removes a value; attribute names remain permanent in the namespace.")
    attribute_schema: dict[str, dict[str, str]] | None = Field(None, description="Types for genuinely new attributes only; required for datetime and encrypted_text. Every declared name must also be set in attributes.")


class DeleteDocument(_Document):
    """Delete document vectors and storage from the selected namespace."""
    operation: Literal["delete_document"] = Field("delete_document", json_schema_extra={"ui:hidden": True})


class ListDocumentAssets(_Document):
    """List image and table metadata, including coverage and completeness."""
    operation: Literal["list_document_assets"] = Field("list_document_assets", json_schema_extra={"ui:hidden": True})


class ListProjects(_Operation):
    """List projects visible to the account key."""
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"ui:hidden": True})


class GetProject(_Project):
    """Retrieve a project by UUID."""
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"ui:hidden": True})


class RenameProject(_Project):
    """Rename a project."""
    operation: Literal["rename_project"] = Field("rename_project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=64)


class GetProjectUsage(_Usage):
    """Read project usage and optional charts."""
    operation: Literal["get_project_usage"] = Field("get_project_usage", json_schema_extra={"ui:hidden": True})
    project_id: UUID


class ListActiveJobs(_Operation):
    """List pending and processing jobs; each status is capped independently."""
    operation: Literal["list_active_jobs"] = Field("list_active_jobs", json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=100)


class GetJob(_Job):
    """Retrieve a processing job by UUID."""
    operation: Literal["get_job"] = Field("get_job", json_schema_extra={"ui:hidden": True})


class GetJobStatus(_Job):
    """Poll a job, including indexing, failure and blocked states."""
    operation: Literal["get_job_status"] = Field("get_job_status", json_schema_extra={"ui:hidden": True})


class GetJobResults(_Job):
    """Read processed chunks and chunksets as JSON."""
    operation: Literal["get_job_results"] = Field("get_job_results", json_schema_extra={"ui:hidden": True})


class DeleteJob(_Job):
    """Request best-effort cancellation and removal; acceptance does not guarantee deletion."""
    operation: Literal["delete_job"] = Field("delete_job", json_schema_extra={"ui:hidden": True})


# POMA Grill's own MCP server: agents get its tools through a person's POMA Grill sign-in.
PomaGrillMcpCredential = mcp_credential("poma_grill", "https://mcp.index4.ai", app="POMA Grill")
PomaGrillCredential = Union[PomaGrillAPIKeyCredential, PomaGrillMcpCredential]


PomaGrillConfig = Annotated[Union[GetAccount, GetUsage, IngestDocument, Search, SearchDocument, ListAttributes, ListDocuments, GetDocument, UpdateDocumentAttributes, DeleteDocument, ListDocumentAssets, ListProjects, GetProject, RenameProject, GetProjectUsage, ListActiveJobs, GetJob, GetJobStatus, GetJobResults, DeleteJob], Field(discriminator="operation")]


class PomaGrillFullConfig(NodeConfig[PomaGrillConfig, PomaGrillCredential]):
    pass


# Explicit routes keep each user operation mapped to exactly one contract operation.
ROUTES = {
    "get_account": ("GET", "/me"),
    "get_usage": ("GET", "/myUsage"),
    "ingest_document": ("POST", "/grill/ingest"),
    "search": ("POST", "/grill/search"),
    "search_document": ("POST", "/grill/searchInDoc"),
    "list_attributes": ("GET", "/grill/attributes"),
    "list_documents": ("GET", "/grill/docs"),
    "get_document": ("GET", "/grill/docs/{doc_id}"),
    "update_document_attributes": ("PATCH", "/grill/docs/{doc_id}"),
    "delete_document": ("DELETE", "/grill/docs/{doc_id}"),
    "list_document_assets": ("GET", "/grill/docs/{doc_id}/images"),
    "list_projects": ("GET", "/projects"),
    "get_project": ("GET", "/projects/{project_id}"),
    "rename_project": ("PUT", "/projects/{project_id}/name"),
    "get_project_usage": ("GET", "/projects/{project_id}/usage"),
    "list_active_jobs": ("GET", "/activeJobs"),
    "get_job": ("GET", "/jobs/{job_id}"),
    "get_job_status": ("GET", "/jobs/{job_id}/status"),
    "get_job_results": ("GET", "/jobs/{job_id}/results"),
    "delete_job": ("DELETE", "/jobs/{job_id}"),
}


def _redact(value, key):
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()
                if k.lower() not in {"api_key", "access_token", "refresh_token", "password"}}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value.replace(key, "[redacted]") if isinstance(value, str) else value


class PomaGrillNode(WorkflowNode):
    integration_type = "automation-poma-grill"
    credential_provider_labels = {"poma_grill": "POMA Grill Account"}
    connection_evidence = ConnectionEvidence(noun="account", operation="get_account",
        label_keys=("username", "email", "account_id"))

    @classmethod
    def get_config_model(cls):
        return PomaGrillFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Poma Grill account API key")
        op = self.config.config
        key = self.config.credentials.api_key
        action = op.operation
        method, route = ROUTES[action]
        values = op.model_dump(mode="json", exclude_none=True)
        for name in ("doc_id", "job_id", "project_id"):
            route = route.replace("{" + name + "}", quote(str(values.get(name, "")), safe=""))
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        if route.startswith("/grill/") and values.get("project_id"):
            headers["X-Project-ID"] = values["project_id"]
        params, body = {}, None
        if action in {"get_usage", "get_project_usage"}:
            params = {"chart": str(op.chart).lower(), "chartResolution": op.chart_resolution, "chartProduct": op.chart_product}
        elif action == "list_documents":
            params = {"limit": op.limit, **({"cursor": op.cursor} if op.cursor else {})}
        elif action == "list_active_jobs":
            params = {"limit": op.limit}
        elif action in {"search", "search_document"}:
            body = {k: v for k, v in values.items() if k not in {"operation", "project_id"}}
            body["return_assets"] = False
        elif action == "ingest_document":
            headers["X-Remote-URL"] = str(op.remote_url)
            headers["Content-Type"] = "application/octet-stream"
        elif action == "update_document_attributes":
            body = {"attributes": op.attributes}
            if op.attribute_schema is not None:
                body["attribute_schema"] = op.attribute_schema
        elif action == "rename_project":
            body = {"name": op.name}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, headers=headers, params=params,
                                                **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Poma Grill request did not complete; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            return _redact({"status": "error", "operation": action, "http_status": response.status_code,
                "error": response.text[:4000]}, key)
        if action == "delete_job":
            if response.status_code != 204:
                raise ValueError("Poma Grill did not confirm the removal request")
            return {"status": "success", "operation": action, "accepted": True,
                    "best_effort": True, "deletion_verified": False}
        if len(response.content) > 20_000_000:
            raise ValueError("Poma Grill JSON response exceeds 20 MB")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Poma Grill returned invalid JSON") from None
        if action == "list_projects":
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Poma Grill project list is invalid")
        elif not isinstance(data, dict) or "error" in data:
            raise ValueError("Poma Grill did not return the documented result")
        required = {
            "get_account": ("account_id", "username", "email", "plan"),
            "get_usage": ("grill", "primecut"), "get_project_usage": ("grill", "primecut"),
            "ingest_document": ("job_id", "created_at"),
            "list_documents": ("documents", "namespace", "total_documents", "has_more", "degraded"),
            "list_attributes": ("attributes", "max_names"),
            "get_document": ("doc_id",),
            "update_document_attributes": ("doc_id", "attributes", "attribute_schema"),
            "delete_document": ("doc_id", "vectors_deleted", "storage_deleted"),
            "list_document_assets": ("doc_id", "coverage", "complete", "images", "tables"),
            "get_job": ("job_id", "created_at"), "get_job_status": ("job_id", "status", "code"),
            "search": ("query", "namespace", "result_count"),
            "search_document": ("query", "namespace", "result_count"),
        }.get(action, ())
        if any(name not in data for name in required):
            raise ValueError("Poma Grill response is missing documented result fields")
        if action == "get_account" and any(not isinstance(data[name], str) or not data[name].strip()
                for name in ("account_id", "username", "email", "plan")):
            raise ValueError("Poma Grill account identity has an unexpected shape")
        # Preserve pagination, degradation, coverage and job-state signals verbatim.
        return {"status": "success", "operation": action, "data": _redact(data, key)}
