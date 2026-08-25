"""
Upstash Vector database automation node.

Provides workflow integration with Upstash Vector (serverless, HTTP-native):
- Vectors: query, upsert, fetch, delete
- Text (server-side embedding): query by text, upsert text
- Index: info

Authentication: Bearer token + the database's own REST URL (both stored on
the credential — Upstash has no global endpoint, each database has its own).
Docs: https://upstash.com/docs/vector/api/endpoints

Upstash can embed text server-side when the database was created with an
embedding model — the ``query_text`` / ``upsert_text`` operations use that, so
this node works as a text-in retrieval tool for agents with no separate
embedding step.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.document_ingest import DOCUMENT_ACCEPT, ingest_document_text
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

_BOOL_ENUM_EXTRA = {
    "enum": ["true", "false"],
    "enumNames": ["Yes", "No"],
    "x-enum-searchable": True,
}

# ============================================================================
# Credential Schema
# ============================================================================


class UpstashVectorCredential(BaseModel):
    """REST URL + token credential for an Upstash Vector database."""

    credential_type: Literal["upstash_vector"] = Field(
        "upstash_vector", json_schema_extra={"ui:hidden": True}
    )
    url: str = Field(
        ...,
        title="REST URL",
        description="Your database's UPSTASH_VECTOR_REST_URL, e.g. https://xxx-12345-us1-vector.upstash.io",
    )
    token: str = Field(
        ...,
        title="REST Token",
        description="Your database's UPSTASH_VECTOR_REST_TOKEN",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://console.upstash.com/vector"}
    )


# ============================================================================
# Operation Configs
# ============================================================================


class UpstashQueryConfig(BaseModel):
    """Find the most similar vectors to a query vector."""

    operation: Literal["query"] = Field(
        "query",
        json_schema_extra={
            "const": "query",
            "ui:hidden": True,
            "x-category": "Vectors",
            "x-is-trigger": False,
            "x-display-name": "Query / Search",
            "x-keywords": ["search", "similarity search", "nearest neighbors", "vector search"],
        },
        title="Query / Search",
    )
    vector: str = Field(
        ...,
        title="Query Vector",
        description="Embedding to search with — a JSON array of numbers",
        json_schema_extra={"ui:widget": "textarea"},
    )
    top_k: int = Field(10, title="Top K", description="Number of matches to return")
    namespace: Optional[str] = Field(
        None, title="Namespace", description="Namespace (default if blank)"
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description="Upstash metadata filter string, e.g. country = 'US' AND population > 1000000",
    )
    include_metadata: str = Field("true", title="Include Metadata", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_vectors: str = Field("false", title="Include Vectors", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_data: str = Field("true", title="Include Data", json_schema_extra=_BOOL_ENUM_EXTRA)


class UpstashQueryTextConfig(BaseModel):
    """Search by text — Upstash embeds the text server-side (requires an
    embedding-enabled database)."""

    operation: Literal["query_text"] = Field(
        "query_text",
        json_schema_extra={
            "const": "query_text",
            "ui:hidden": True,
            "x-category": "Text",
            "x-is-trigger": False,
            "x-display-name": "Query by Text",
            "x-keywords": ["search text", "semantic search", "rag", "ask", "retrieve documents"],
        },
        title="Query by Text",
    )
    data: str = Field(
        ...,
        title="Query Text",
        description="Text to search with — embedded server-side by the database's model",
        json_schema_extra={"ui:widget": "textarea"},
    )
    top_k: int = Field(10, title="Top K", description="Number of matches to return")
    namespace: Optional[str] = Field(None, title="Namespace")
    filter: Optional[str] = Field(
        None, title="Filter", description="Upstash metadata filter string"
    )
    include_metadata: str = Field("true", title="Include Metadata", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_vectors: str = Field("false", title="Include Vectors", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_data: str = Field("true", title="Include Data", json_schema_extra=_BOOL_ENUM_EXTRA)


class UpstashUpsertConfig(BaseModel):
    """Insert or overwrite vectors."""

    operation: Literal["upsert"] = Field(
        "upsert",
        json_schema_extra={
            "const": "upsert",
            "ui:hidden": True,
            "x-category": "Vectors",
            "x-is-trigger": False,
            "x-display-name": "Upsert Vectors",
            "x-keywords": ["insert", "index", "add vectors", "store", "write"],
        },
        title="Upsert Vectors",
    )
    vectors: str = Field(
        ...,
        title="Vectors",
        description='JSON array: [{"id": "a", "vector": [0.1, ...], "metadata": {...}, "data": "..."}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    namespace: Optional[str] = Field(None, title="Namespace")


class UpstashUpsertTextConfig(BaseModel):
    """Insert text records — Upstash embeds them server-side (requires an
    embedding-enabled database)."""

    operation: Literal["upsert_text"] = Field(
        "upsert_text",
        json_schema_extra={
            "const": "upsert_text",
            "ui:hidden": True,
            "x-category": "Text",
            "x-is-trigger": False,
            "x-display-name": "Upsert Text",
            "x-keywords": ["insert text", "index documents", "embed", "store text"],
        },
        title="Upsert Text",
    )
    items: str = Field(
        ...,
        title="Text Records",
        description='JSON array: [{"id": "a", "data": "the text to embed", "metadata": {...}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    namespace: Optional[str] = Field(None, title="Namespace")


class UpstashFetchConfig(BaseModel):
    """Fetch vectors by ID."""

    operation: Literal["fetch"] = Field(
        "fetch",
        json_schema_extra={
            "const": "fetch",
            "ui:hidden": True,
            "x-category": "Vectors",
            "x-is-trigger": False,
            "x-display-name": "Fetch Vectors",
            "x-keywords": ["get", "lookup by id", "read vectors"],
        },
        title="Fetch Vectors",
    )
    ids: str = Field(..., title="IDs", description="Vector IDs to fetch, comma-separated")
    namespace: Optional[str] = Field(None, title="Namespace")
    include_metadata: str = Field("true", title="Include Metadata", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_vectors: str = Field("false", title="Include Vectors", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_data: str = Field("true", title="Include Data", json_schema_extra=_BOOL_ENUM_EXTRA)


class UpstashDeleteConfig(BaseModel):
    """Delete vectors by ID."""

    operation: Literal["delete"] = Field(
        "delete",
        json_schema_extra={
            "const": "delete",
            "ui:hidden": True,
            "x-category": "Vectors",
            "x-is-trigger": False,
            "x-display-name": "Delete Vectors",
            "x-keywords": ["remove", "clear", "purge"],
        },
        title="Delete Vectors",
    )
    ids: str = Field(..., title="IDs", description="Vector IDs to delete, comma-separated")
    namespace: Optional[str] = Field(None, title="Namespace")


class UpstashInfoConfig(BaseModel):
    """Get database stats (vector count, dimension, similarity function)."""

    operation: Literal["info"] = Field(
        "info",
        json_schema_extra={
            "const": "info",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Database Info",
            "x-keywords": ["stats", "describe", "count"],
        },
        title="Database Info",
    )


class UpstashResetConfig(BaseModel):
    """Delete all vectors from a namespace (or the entire index if no namespace given)."""

    operation: Literal["reset"] = Field(
        "reset",
        json_schema_extra={
            "const": "reset",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Reset Namespace",
            "x-keywords": ["clear all", "wipe", "truncate", "empty namespace"],
        },
        title="Reset Namespace",
    )
    namespace: Optional[str] = Field(
        None, title="Namespace", description="Namespace to reset (entire index if blank)"
    )


class UpstashRangeConfig(BaseModel):
    """Scroll / paginate through all vectors in a namespace using a cursor."""

    operation: Literal["range"] = Field(
        "range",
        json_schema_extra={
            "const": "range",
            "ui:hidden": True,
            "x-category": "Vectors",
            "x-is-trigger": False,
            "x-display-name": "List Vectors (Range)",
            "x-keywords": ["scroll", "paginate", "list all", "iterate", "cursor"],
        },
        title="List Vectors (Range)",
    )
    cursor: str = Field(
        "0", title="Cursor", description="Pagination cursor — use '0' to start from the beginning"
    )
    limit: int = Field(100, title="Limit", description="Number of vectors per page (max 1000)")
    namespace: Optional[str] = Field(None, title="Namespace")
    include_metadata: str = Field("true", title="Include Metadata", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_vectors: str = Field("false", title="Include Vectors", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_data: str = Field("true", title="Include Data", json_schema_extra=_BOOL_ENUM_EXTRA)


class UpstashUpdateConfig(BaseModel):
    """Update the metadata and/or data field of an existing vector without re-supplying the embedding."""

    operation: Literal["update"] = Field(
        "update",
        json_schema_extra={
            "const": "update",
            "ui:hidden": True,
            "x-category": "Vectors",
            "x-is-trigger": False,
            "x-display-name": "Update Vector Metadata",
            "x-keywords": ["patch metadata", "edit", "modify", "update data"],
        },
        title="Update Vector Metadata",
    )
    id: str = Field(..., title="Vector ID", description="ID of the vector to update")
    metadata: Optional[str] = Field(
        None, title="Metadata", description="JSON object to set as the new metadata (replaces existing)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    data: Optional[str] = Field(
        None, title="Data", description="New text data field value (for embedding-enabled databases)"
    )
    namespace: Optional[str] = Field(None, title="Namespace")


class UpstashUploadIndexConfig(BaseModel):
    """Upload a document, chunk it, and index it with server-side embedding."""

    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index",
            "ui:hidden": True,
            "x-category": "Text",
            "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file", "add pdf"],
        },
        title="Upload & Index Document",
    )
    document: str = Field(
        ...,
        title="Document",
        description="Upload a PDF/DOCX/TXT/MD/CSV file (or paste a URL / reference an upstream file). It's chunked and upserted as text — Upstash embeds it server-side (the database must have an embedding model).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": DOCUMENT_ACCEPT},
    )
    namespace: Optional[str] = Field(None, title="Namespace")
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap", description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(
        None, title="ID Prefix", description="Optional prefix for chunk IDs (defaults to the filename)"
    )


# ============================================================================
# Discriminated Union
# ============================================================================


UpstashVectorConfig = Annotated[
    Union[
        UpstashQueryConfig,
        UpstashQueryTextConfig,
        UpstashUpsertConfig,
        UpstashUpsertTextConfig,
        UpstashFetchConfig,
        UpstashDeleteConfig,
        UpstashInfoConfig,
        UpstashResetConfig,
        UpstashRangeConfig,
        UpstashUpdateConfig,
        UpstashUploadIndexConfig,
    ],
    Discriminator("operation"),
]


class UpstashVectorNodeConfig(NodeConfig[UpstashVectorConfig, UpstashVectorCredential]):
    """Full configuration for the Upstash Vector node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _parse_json_list(value: Any) -> Optional[List[Any]]:
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


# ============================================================================
# Node Implementation
# ============================================================================


class UpstashVectorNode(WorkflowNode):
    """Upstash Vector database automation node."""

    edit_examples = [
        "Search an Upstash Vector database by text (server-side embedding) for the most relevant documents",
        "Upsert text records into Upstash so they're embedded and indexed automatically",
        "Query an Upstash database with a precomputed embedding vector",
        "Fetch vectors by ID to inspect their metadata",
        "Delete stale vectors from a namespace",
    ]

    @classmethod
    def get_config_model(cls):
        return UpstashVectorNodeConfig

    @staticmethod
    def _base_url(credential: UpstashVectorCredential) -> str:
        return (credential.url or "").rstrip("/")

    @staticmethod
    def _headers(credential: UpstashVectorCredential) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {credential.token}",
            "Content-Type": "application/json",
            "User-Agent": "NoClick-Workflow/1.0",
        }

    def _endpoint(self, credential, path: str, namespace: Optional[str]) -> str:
        """Build the endpoint URL, appending the namespace path segment when set."""
        url = f"{self._base_url(credential)}/{path}"
        if namespace:
            url = f"{url}/{namespace}"
        return url

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, UpstashVectorNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Upstash Vector REST URL and token.")

        op_config = config.config
        handlers = {
            "query": self._handle_query,
            "query_text": self._handle_query_text,
            "upsert": self._handle_upsert,
            "upsert_text": self._handle_upsert_text,
            "fetch": self._handle_fetch,
            "delete": self._handle_delete,
            "info": self._handle_info,
            "reset": self._handle_reset,
            "range": self._handle_range,
            "update": self._handle_update,
            "upload_and_index": self._handle_upload_and_index,
        }
        handler = handlers.get(op_config.operation)
        if not handler:
            raise ValueError(f"Unknown action: {op_config.operation}")

        result = await handler(op_config, credentials)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # =========================================================================
    # HTTP helper
    # =========================================================================

    async def _request(
        self,
        method: str,
        url: str,
        credential: UpstashVectorCredential,
        json_body: Optional[Any] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        start_time = time.time()
        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers(credential),
                    json=json_body,
                )
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
            }
        except httpx.HTTPError as e:
            return {
                "status": "error",
                "action": action_name,
                "error": str(e),
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
            }

        api_time = round((time.time() - start_time) * 1000, 2)
        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_message = error_data.get("error", str(error_data))
            except Exception:
                error_message = response.text
            logger.error(f"[UpstashVectorNode] API error ({action_name}): {error_message}")
            return {
                "status": "error",
                "action": action_name,
                "error": error_message,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_time},
            }

        if response.status_code == 204 or not response.content:
            data: Any = {"success": True}
        else:
            try:
                data = response.json()
            except Exception:
                data = {"raw": response.text}

        return {
            "status": "success",
            "action": action_name,
            "data": data,
            "status_code": response.status_code,
            "timing_ms": {"api_request": api_time},
        }

    # =========================================================================
    # Operation handlers
    # =========================================================================

    async def _handle_query(self, config: UpstashQueryConfig, credentials) -> Dict[str, Any]:
        vector = _parse_json_list(config.vector)
        if not vector:
            return {"status": "error", "action": "query", "error": "`vector` must be a non-empty JSON array of numbers"}
        body: Dict[str, Any] = {
            "vector": vector,
            "topK": config.top_k,
            "includeMetadata": config.include_metadata == "true",
            "includeVectors": config.include_vectors == "true",
            "includeData": config.include_data == "true",
        }
        if config.filter:
            body["filter"] = config.filter
        url = self._endpoint(credentials, "query", config.namespace)
        return await self._request("POST", url, credentials, json_body=body, action_name="query")

    async def _handle_query_text(self, config: UpstashQueryTextConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "data": config.data,
            "topK": config.top_k,
            "includeMetadata": config.include_metadata == "true",
            "includeVectors": config.include_vectors == "true",
            "includeData": config.include_data == "true",
        }
        if config.filter:
            body["filter"] = config.filter
        url = self._endpoint(credentials, "query-data", config.namespace)
        return await self._request("POST", url, credentials, json_body=body, action_name="query_text")

    async def _handle_upsert(self, config: UpstashUpsertConfig, credentials) -> Dict[str, Any]:
        vectors = _parse_json_list(config.vectors)
        if not vectors:
            return {
                "status": "error",
                "action": "upsert",
                "error": "`vectors` must be a non-empty JSON array of {id, vector, metadata, data} objects",
            }
        url = self._endpoint(credentials, "upsert", config.namespace)
        return await self._request("POST", url, credentials, json_body=vectors, action_name="upsert")

    async def _handle_upsert_text(self, config: UpstashUpsertTextConfig, credentials) -> Dict[str, Any]:
        items = _parse_json_list(config.items)
        if not items:
            return {
                "status": "error",
                "action": "upsert_text",
                "error": "`items` must be a non-empty JSON array of {id, data, metadata} objects",
            }
        url = self._endpoint(credentials, "upsert-data", config.namespace)
        return await self._request("POST", url, credentials, json_body=items, action_name="upsert_text")

    async def _handle_fetch(self, config: UpstashFetchConfig, credentials) -> Dict[str, Any]:
        ids = _split_csv(config.ids)
        if not ids:
            return {"status": "error", "action": "fetch", "error": "Provide at least one vector ID"}
        body = {
            "ids": ids,
            "includeMetadata": config.include_metadata == "true",
            "includeVectors": config.include_vectors == "true",
            "includeData": config.include_data == "true",
        }
        url = self._endpoint(credentials, "fetch", config.namespace)
        return await self._request("POST", url, credentials, json_body=body, action_name="fetch")

    async def _handle_delete(self, config: UpstashDeleteConfig, credentials) -> Dict[str, Any]:
        ids = _split_csv(config.ids)
        if not ids:
            return {"status": "error", "action": "delete", "error": "Provide at least one vector ID"}
        url = self._endpoint(credentials, "delete", config.namespace)
        return await self._request("DELETE", url, credentials, json_body={"ids": ids}, action_name="delete")

    async def _handle_info(self, config: UpstashInfoConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/info"
        return await self._request("GET", url, credentials, action_name="info")

    async def _handle_reset(self, config: UpstashResetConfig, credentials) -> Dict[str, Any]:
        url = self._endpoint(credentials, "reset", config.namespace)
        return await self._request("DELETE", url, credentials, action_name="reset")

    async def _handle_range(self, config: UpstashRangeConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "cursor": config.cursor,
            "limit": config.limit,
            "includeMetadata": config.include_metadata == "true",
            "includeVectors": config.include_vectors == "true",
            "includeData": config.include_data == "true",
        }
        url = self._endpoint(credentials, "range", config.namespace)
        return await self._request("GET", url, credentials, json_body=body, action_name="range")

    async def _handle_update(self, config: UpstashUpdateConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"id": config.id}
        if config.metadata:
            try:
                body["metadata"] = json.loads(config.metadata)
            except (json.JSONDecodeError, ValueError):
                return {"status": "error", "action": "update", "error": "`metadata` must be a valid JSON object"}
        if config.data:
            body["data"] = config.data
        if len(body) == 1:
            return {"status": "error", "action": "update", "error": "Provide at least one of metadata or data to update"}
        url = self._endpoint(credentials, "update", config.namespace)
        return await self._request("POST", url, credentials, json_body=body, action_name="update")

    async def _handle_upload_and_index(self, config: UpstashUploadIndexConfig, credentials) -> Dict[str, Any]:
        records, info = await ingest_document_text(
            config.document, chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap, id_prefix=config.id_prefix
        )
        if not records:
            return {"status": "error", "action": "upload_and_index", "error": "No text could be extracted from the document"}
        items = [{"id": r["id"], "data": r["text"], "metadata": r["metadata"]} for r in records]
        url = self._endpoint(credentials, "upsert-data", config.namespace)
        result = await self._request("POST", url, credentials, json_body=items, action_name="upload_and_index")
        if result.get("status") == "success":
            result["data"] = {"chunks_indexed": len(records), "source": info.get("filename"), "raw": result.get("data")}
        return result
