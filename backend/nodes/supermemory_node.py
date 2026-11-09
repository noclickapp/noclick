"""Supermemory v5 namespace-scoped memory automation.

Wire contract: https://api.supermemory.ai/openapi.json (5.0.0).
Each operation makes one request; pagination and asynchronous processing states
are returned unchanged so workflows can explicitly continue or poll.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.supermemory.ai"

class SupermemoryAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Supermemory API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://console.supermemory.ai",
            "x-credential-instructions": "Create an API key in the Supermemory console and paste it here. Give the key read/write access to the namespaces your workflow uses. NoClick checks it by listing your namespaces."})
    credential_type: Literal["supermemory_api_key"] = Field("supermemory_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

Namespace = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_:-]+$")]
ResourceID = Annotated[str, Field(min_length=1, max_length=255)]
Bucket = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
Metadata = dict[str, Union[str, float, bool, list[str]]]

class _Namespace(_Input):
    namespace: Namespace = Field(..., description="Namespace identifier, for example user_alex. Namespaces isolate users or projects.")

class _Page(_Input):
    page: int = Field(1, ge=1, description="One-based page; return pagination is preserved.")
    limit: int = Field(10, ge=1, le=100)

class _Document(_Input):
    content: str = Field(..., description="Plain text or a URL to supported content.")
    id: ResourceID | None = Field(None, description="Optional caller-defined document ID.")
    supportingContext: str | None = Field(None, max_length=1500)
    metadata: Metadata | None = None
    group: Metadata | None = None
    date: str | None = Field(None, description="Source content date in ISO 8601 format.")

class _Pipeline(_Input):
    taskType: Literal["memory", "superrag"] | None = None
    dreaming: Literal["dynamic", "instant"] | None = Field(None, description="Instant processes independently and bills an extra operation per document.")

class _DocumentID(_Namespace):
    id: ResourceID

    @field_validator("id")
    @classmethod
    def path_id(cls, value):
        if value in {".", ".."}:
            raise ValueError("Use a resource ID, not a dot path segment")
        return value

class _ConnectorID(_DocumentID):
    id: str = Field(..., min_length=1)

class SupermemoryAddDocumentConfig(_Namespace, _Document, _Pipeline):
    """POST /ns/{namespace}/document."""
    operation: Literal["add_document"] = Field("add_document", json_schema_extra={"ui:hidden": True})

class SupermemoryBatchAddDocumentsConfig(_Namespace, _Pipeline):
    """POST /ns/{namespace}/document/batch."""
    operation: Literal["batch_add_documents"] = Field("batch_add_documents", json_schema_extra={"ui:hidden": True})
    documents: list[_Document] = Field(..., min_length=1, max_length=600)

class SupermemoryGetDocumentConfig(_DocumentID):
    """GET /ns/{namespace}/document/{id}."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})
    include: list[Literal["chunks", "memories"]] | None = None

class SupermemoryUpdateDocumentConfig(_DocumentID, _Pipeline):
    """PATCH /ns/{namespace}/document/{id}."""
    operation: Literal["update_document"] = Field("update_document", json_schema_extra={"ui:hidden": True})
    content: str | None = None
    supportingContext: str | None = Field(None, max_length=1500)
    metadata: Metadata | None = None
    group: Metadata | None = None
    date: str | None = None

class SupermemoryDeleteDocumentsConfig(_Namespace):
    """DELETE /ns/{namespace}/document."""
    operation: Literal["delete_documents"] = Field("delete_documents", json_schema_extra={"ui:hidden": True})
    ids: list[ResourceID] = Field(..., min_length=1, max_length=100)

class SupermemorySearchConfig(_Namespace):
    """POST /ns/{namespace}/search."""
    operation: Literal["search"] = Field("search", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)
    searchMode: Literal["hybrid", "memories", "chunks"] = "hybrid"
    limit: int = Field(10, ge=1, le=100)
    threshold: float = Field(0.3, ge=0, le=1)
    rerank: Literal["none", "order", "aggregate"] = "none"
    rewriteQuery: bool = False

class SupermemoryGetProfileConfig(_Namespace):
    """POST /ns/{namespace}/profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})
    buckets: list[Bucket] | None = Field(None, max_length=50)

class SupermemoryGetProfileBucketsConfig(_Namespace):
    """GET /ns/{namespace}/profile/buckets."""
    operation: Literal["get_profile_buckets"] = Field("get_profile_buckets", json_schema_extra={"ui:hidden": True})

class SupermemoryUpsertProfileBucketsConfig(_Namespace):
    """PUT /ns/{namespace}/profile/buckets."""
    operation: Literal["upsert_profile_buckets"] = Field("upsert_profile_buckets", json_schema_extra={"ui:hidden": True})
    buckets: dict[Bucket, Annotated[str, Field(max_length=2000)]]

class SupermemoryDeleteProfileBucketsConfig(_Namespace):
    """DELETE /ns/{namespace}/profile/buckets."""
    operation: Literal["delete_profile_buckets"] = Field("delete_profile_buckets", json_schema_extra={"ui:hidden": True})
    buckets: list[Bucket] = Field(..., min_length=1, max_length=50)

class SupermemoryForgetMemoriesConfig(_Namespace):
    """DELETE /ns/{namespace}/memories."""
    operation: Literal["forget_memories"] = Field("forget_memories", json_schema_extra={"ui:hidden": True})
    ids: list[Annotated[str, Field(min_length=1)]] = Field(..., min_length=1, max_length=500)

class SupermemoryForgetMemoriesSemanticConfig(_Namespace):
    """DELETE /ns/{namespace}/memories/semantic."""
    operation: Literal["forget_memories_semantic"] = Field("forget_memories_semantic", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=2000)
    dryRun: bool = Field(True, description="Preview matching memories; set false explicitly to forget them.")

class SupermemoryListResourcesConfig(_Namespace, _Page):
    """POST /ns/{namespace}/list/{type}."""
    operation: Literal["list_resources"] = Field("list_resources", json_schema_extra={"ui:hidden": True})
    type: Literal["documents", "chunks", "memories"] = Field(..., title="Resource type")
    cursor: str | None = Field(None, min_length=1, max_length=2048)
    sort: Literal["createdAt", "updatedAt", "position"] = "createdAt"
    order: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def position_only_for_chunks(self):
        if self.sort == "position" and self.type != "chunks":
            raise ValueError("Position sorting is available only for chunks")
        return self

class SupermemoryListConnectorsConfig(_Namespace, _Page):
    """GET /ns/{namespace}/connectors."""
    operation: Literal["list_connectors"] = Field("list_connectors", json_schema_extra={"ui:hidden": True})
    provider: Literal["notion", "google-drive", "onedrive", "gmail", "github", "web-crawler", "s3", "granola"] | None = None

class SupermemoryGetConnectorConfig(_ConnectorID):
    """GET /ns/{namespace}/connectors/{id}."""
    operation: Literal["get_connector"] = Field("get_connector", json_schema_extra={"ui:hidden": True})

class SupermemoryDeleteConnectorConfig(_ConnectorID):
    deleteDocuments: bool = Field(True, description="Also permanently delete imported documents. Set false to keep them.")
    """DELETE /ns/{namespace}/connectors/{id}."""
    operation: Literal["delete_connector"] = Field("delete_connector", json_schema_extra={"ui:hidden": True})

class SupermemorySyncConnectorConfig(_ConnectorID):
    """POST /ns/{namespace}/connectors/{id}/sync."""
    operation: Literal["sync_connector"] = Field("sync_connector", json_schema_extra={"ui:hidden": True})

class SupermemoryListNamespacesConfig(_Page):
    """GET /ns."""
    operation: Literal["list_namespaces"] = Field("list_namespaces", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, max_length=100)

class SupermemoryGetNamespaceConfig(_Namespace):
    """GET /ns/{namespace}."""
    operation: Literal["get_namespace"] = Field("get_namespace", json_schema_extra={"ui:hidden": True})

class SupermemoryUpdateNamespaceConfig(_Namespace):
    """PATCH /ns/{namespace}."""
    operation: Literal["update_namespace"] = Field("update_namespace", json_schema_extra={"ui:hidden": True})
    supportingContext: str | None = Field(..., max_length=1500, description="Set null to clear context.")

class SupermemoryGetOrganizationConfig(_Input):
    """GET /organization."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})

class SupermemoryGetMemoryConfig(_DocumentID):
    """GET /ns/{namespace}/memories/{id}."""
    operation: Literal["get_memory"] = Field("get_memory", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1)
    include: list[Literal["related", "documents"]] | None = None
    relatedLimit: int = Field(10, ge=1, le=100)

class SupermemoryCountDocumentMemoriesConfig(_Namespace):
    """POST /ns/{namespace}/list/documents/memory-counts."""
    operation: Literal["count_document_memories"] = Field("count_document_memories", json_schema_extra={"ui:hidden": True})
    ids: list[ResourceID] = Field(..., min_length=1, max_length=100)

SupermemoryConfig = Annotated[Union[
    SupermemoryAddDocumentConfig,
    SupermemoryBatchAddDocumentsConfig,
    SupermemoryGetDocumentConfig,
    SupermemoryUpdateDocumentConfig,
    SupermemoryDeleteDocumentsConfig,
    SupermemorySearchConfig,
    SupermemoryGetProfileConfig,
    SupermemoryGetProfileBucketsConfig,
    SupermemoryUpsertProfileBucketsConfig,
    SupermemoryDeleteProfileBucketsConfig,
    SupermemoryForgetMemoriesConfig,
    SupermemoryForgetMemoriesSemanticConfig,
    SupermemoryListResourcesConfig,
    SupermemoryListConnectorsConfig,
    SupermemoryGetConnectorConfig,
    SupermemoryDeleteConnectorConfig,
    SupermemorySyncConnectorConfig,
    SupermemoryListNamespacesConfig,
    SupermemoryGetNamespaceConfig,
    SupermemoryUpdateNamespaceConfig,
    SupermemoryGetOrganizationConfig,
    SupermemoryGetMemoryConfig,
    SupermemoryCountDocumentMemoriesConfig,
], Field(discriminator="operation")]

class SupermemoryFullConfig(NodeConfig[SupermemoryConfig, SupermemoryAPIKeyCredential]):
    pass

ROUTES = {'add_document': ('POST', '/ns/{namespace}/document'),
 'batch_add_documents': ('POST', '/ns/{namespace}/document/batch'),
 'get_document': ('GET', '/ns/{namespace}/document/{id}'),
 'update_document': ('PATCH', '/ns/{namespace}/document/{id}'),
 'delete_documents': ('DELETE', '/ns/{namespace}/document'),
 'search': ('POST', '/ns/{namespace}/search'),
 'get_profile': ('POST', '/ns/{namespace}/profile'),
 'get_profile_buckets': ('GET', '/ns/{namespace}/profile/buckets'),
 'upsert_profile_buckets': ('PUT', '/ns/{namespace}/profile/buckets'),
 'delete_profile_buckets': ('DELETE', '/ns/{namespace}/profile/buckets'),
 'forget_memories': ('DELETE', '/ns/{namespace}/memories'),
 'forget_memories_semantic': ('DELETE', '/ns/{namespace}/memories/semantic'),
 'list_resources': ('POST', '/ns/{namespace}/list/{type}'),
 'list_connectors': ('GET', '/ns/{namespace}/connectors'),
 'get_connector': ('GET', '/ns/{namespace}/connectors/{id}'),
 'delete_connector': ('DELETE', '/ns/{namespace}/connectors/{id}'),
 'sync_connector': ('POST', '/ns/{namespace}/connectors/{id}/sync'),
 'list_namespaces': ('GET', '/ns'),
 'get_namespace': ('GET', '/ns/{namespace}'),
 'update_namespace': ('PATCH', '/ns/{namespace}'),
 'get_organization': ('GET', '/organization'),
 'get_memory': ('GET', '/ns/{namespace}/memories/{id}'),
 'count_document_memories': ('POST', '/ns/{namespace}/list/documents/memory-counts')}

# Query parameters are explicitly separated from JSON body fields.
QUERY_FIELDS = {
    "delete_connector": ("deleteDocuments",), "get_document": ("include",), "get_memory": ("include", "relatedLimit"),
    "list_namespaces": ("page", "limit", "q"),
    "list_resources": ("page", "limit", "cursor", "sort", "order"),
    "list_connectors": ("page", "limit", "provider"),
}

class SupermemoryNode(WorkflowNode):
    integration_type = "automation-supermemory"
    connection_evidence = ConnectionEvidence(
        noun="namespaces", operation="list_namespaces", label_keys=("namespace", "id"))

    @classmethod
    def get_config_model(cls):
        return SupermemoryFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Supermemory API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        fields = config.model_dump(exclude_none=True, exclude={"operation"})
        # Namespace context is explicitly nullable: null clears it.
        if config.operation == "update_namespace":
            fields["supportingContext"] = config.supportingContext
        for key in ("namespace", "id", "type"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(fields.pop(key), safe=""))
        params = {key: fields.pop(key) for key in QUERY_FIELDS.get(config.operation, ()) if key in fields}
        for key, value in params.items():
            if isinstance(value, bool):
                params[key] = str(value).lower()
            elif isinstance(value, list):
                params[key] = ",".join(value)
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"},
                params=params, **({"json": fields} if method in {"POST", "PUT", "PATCH", "DELETE"} and
                    (fields or config.operation in {"get_profile", "list_resources", "update_document"}) else {}))
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for connection evidence; never echo the key.
            message = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"Supermemory HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {"http_status": 204}
        if len(response.content) > 20_000_000:
            raise ValueError("Supermemory response exceeds 20 MB")
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Supermemory returned an unexpected response or error envelope")
        per_item = config.operation in {"delete_documents", "forget_memories", "forget_memories_semantic"}
        if "errors" in data and not (per_item and isinstance(data.get("errors"), list)
                and type(data.get("count")) is int):
            raise ValueError("Supermemory returned an unexpected error envelope")
        if config.operation == "list_namespaces" and not (
                isinstance(data.get("namespaces"), list) and isinstance(data.get("pagination"), dict)):
            raise ValueError("Supermemory namespace listing is missing its rows or pagination")
        # Preserve processing statuses, pagination and provider-specific result shapes.
        return data
