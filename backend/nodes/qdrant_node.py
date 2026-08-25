"""
Qdrant vector database automation node.

Provides workflow integration with Qdrant for vector operations:
- Points: query (similarity search), upsert, retrieve, delete
- Collection management: list collections, create collection

Authentication: API key (``api-key`` header) + cluster URL stored on the
credential (Qdrant Cloud or a self-hosted instance).
Docs: https://api.qdrant.tech/

Writes pass ``?wait=true`` so the next workflow step reads its own write back.
Point IDs must be unsigned integers or UUIDs — numeric strings are coerced to
ints, everything else is passed through as a UUID string.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.document_ingest import DOCUMENT_ACCEPT, ingest_document
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

# Reused across every operation that targets a specific collection.
_COLLECTION_FIELD_EXTRA = {
    "x-resource-type": "qdrant_collection",
    "x-dynamic-options": {
        "field_name": "collection",
        "placeholder": "Select a collection...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type the collection name",
    }
}

_BOOL_ENUM_EXTRA = {
    "enum": ["true", "false"],
    "enumNames": ["Yes", "No"],
    "x-enum-searchable": True,
}

# ============================================================================
# Credential Schema
# ============================================================================


class QdrantCredential(BaseModel):
    """API key + cluster URL credential for Qdrant."""

    credential_type: Literal["qdrant_api_key"] = Field(
        "qdrant_api_key", json_schema_extra={"ui:hidden": True}
    )
    url: str = Field(
        ...,
        title="Cluster URL",
        description="Your Qdrant endpoint, e.g. https://xyz-abc.region.aws.cloud.qdrant.io:6333",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Qdrant API key from your cluster dashboard",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://cloud.qdrant.io/"}
    )


# ============================================================================
# Operation Configs
# ============================================================================


class QdrantQueryConfig(BaseModel):
    """Find the most similar points to a query vector (similarity search)."""

    operation: Literal["query"] = Field(
        "query",
        json_schema_extra={
            "const": "query",
            "ui:hidden": True,
            "x-category": "Points",
            "x-is-trigger": False,
            "x-display-name": "Query / Search",
            "x-keywords": [
                "search",
                "similarity search",
                "semantic search",
                "retrieve",
                "nearest neighbors",
                "vector search",
                "rag",
            ],
        },
        title="Query / Search",
    )
    collection: str = Field(
        ...,
        title="Collection",
        description="Collection to query",
        json_schema_extra=_COLLECTION_FIELD_EXTRA,
    )
    vector: str = Field(
        ...,
        title="Query Vector",
        description="Embedding to search with — a JSON array of numbers, e.g. [0.1, 0.2, ...]",
        json_schema_extra={"ui:widget": "textarea"},
    )
    limit: int = Field(10, title="Limit", description="Number of matches to return")
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description='Optional Qdrant JSON filter, e.g. {"must": [{"key": "city", "match": {"value": "London"}}]}',
    )
    with_payload: str = Field(
        "true", title="Include Payload", json_schema_extra=_BOOL_ENUM_EXTRA
    )
    with_vector: str = Field(
        "false", title="Include Vector", json_schema_extra=_BOOL_ENUM_EXTRA
    )


class QdrantUpsertConfig(BaseModel):
    """Insert or overwrite points in a collection."""

    operation: Literal["upsert"] = Field(
        "upsert",
        json_schema_extra={
            "const": "upsert",
            "ui:hidden": True,
            "x-category": "Points",
            "x-is-trigger": False,
            "x-display-name": "Upsert Points",
            "x-keywords": ["insert", "index", "add points", "store", "write", "embed"],
        },
        title="Upsert Points",
    )
    collection: str = Field(
        ...,
        title="Collection",
        description="Collection to write to",
        json_schema_extra=_COLLECTION_FIELD_EXTRA,
    )
    points: str = Field(
        ...,
        title="Points",
        description='JSON array of points: [{"id": 1, "vector": [0.1, ...], "payload": {"source": "doc1"}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class QdrantRetrieveConfig(BaseModel):
    """Retrieve points by their IDs."""

    operation: Literal["retrieve"] = Field(
        "retrieve",
        json_schema_extra={
            "const": "retrieve",
            "ui:hidden": True,
            "x-category": "Points",
            "x-is-trigger": False,
            "x-display-name": "Retrieve Points",
            "x-keywords": ["get", "lookup by id", "read points"],
        },
        title="Retrieve Points",
    )
    collection: str = Field(
        ..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    ids: str = Field(
        ..., title="IDs", description="Point IDs to retrieve, comma-separated"
    )
    with_payload: str = Field(
        "true", title="Include Payload", json_schema_extra=_BOOL_ENUM_EXTRA
    )
    with_vector: str = Field(
        "false", title="Include Vector", json_schema_extra=_BOOL_ENUM_EXTRA
    )


class QdrantDeleteConfig(BaseModel):
    """Delete points by ID or by filter."""

    operation: Literal["delete"] = Field(
        "delete",
        json_schema_extra={
            "const": "delete",
            "ui:hidden": True,
            "x-category": "Points",
            "x-is-trigger": False,
            "x-display-name": "Delete Points",
            "x-keywords": ["remove", "clear", "purge points"],
        },
        title="Delete Points",
    )
    collection: str = Field(
        ..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    ids: Optional[str] = Field(
        None, title="IDs", description="Point IDs to delete, comma-separated"
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description='Delete points matching a Qdrant JSON filter instead of by ID',
    )


class QdrantListCollectionsConfig(BaseModel):
    """List all collections."""

    operation: Literal["list_collections"] = Field(
        "list_collections",
        json_schema_extra={
            "const": "list_collections",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "List Collections",
            "x-keywords": ["list", "show collections"],
        },
        title="List Collections",
    )


class QdrantCreateCollectionConfig(BaseModel):
    """Create a new collection."""

    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection",
            "x-creates-resource": True,
            "x-resource-type": "qdrant_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Create Collection",
            "x-keywords": ["new collection", "provision", "setup"],
        },
        title="Create Collection",
    )
    name: str = Field(..., title="Name", description="Name for the new collection")
    size: int = Field(
        ..., title="Vector Size", description="Vector dimensionality (must match your embedding model)"
    )
    distance: str = Field(
        "Cosine",
        title="Distance",
        json_schema_extra={
            "enum": ["Cosine", "Euclid", "Dot", "Manhattan"],
            "x-enum-searchable": True,
        },
    )


class QdrantUploadIndexConfig(BaseModel):
    """Upload a document file, chunk + embed it, and upsert the points."""

    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index",
            "ui:hidden": True,
            "x-category": "Points",
            "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file", "add pdf"],
        },
        title="Upload & Index Document",
    )
    collection: str = Field(
        ..., title="Collection", description="Collection to write to", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    document: str = Field(
        ...,
        title="Document",
        description="Upload a PDF/DOCX/TXT/MD/CSV file (or paste a URL / reference an upstream file). It's chunked, embedded with text-embedding-3-small, and upserted as points.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": DOCUMENT_ACCEPT},
    )
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap", description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(
        None, title="ID Prefix", description="Optional prefix for chunk IDs (defaults to the filename)"
    )


# ============================================================================
# Collection management — additional ops
# ============================================================================


class QdrantGetCollectionConfig(BaseModel):
    """Get detailed info and stats for a single collection."""

    operation: Literal["get_collection"] = Field(
        "get_collection",
        json_schema_extra={
            "const": "get_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Get Collection Info",
            "x-keywords": ["describe collection", "collection info", "collection status", "collection stats"],
        },
        title="Get Collection Info",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class QdrantUpdateCollectionConfig(BaseModel):
    """Update collection parameters (optimizers, HNSW, quantization)."""

    operation: Literal["update_collection"] = Field(
        "update_collection",
        json_schema_extra={
            "const": "update_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Update Collection",
            "x-keywords": ["configure collection", "collection settings", "optimizers", "hnsw config"],
        },
        title="Update Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    optimizers_config: Optional[str] = Field(
        None, title="Optimizers Config",
        description='JSON object with optimizer settings, e.g. {"indexing_threshold": 20000}',
    )
    hnsw_config: Optional[str] = Field(
        None, title="HNSW Config",
        description='JSON object with HNSW settings, e.g. {"m": 16, "ef_construct": 100}',
    )


class QdrantDeleteCollectionConfig(BaseModel):
    """Delete a collection and all its points permanently."""

    operation: Literal["delete_collection"] = Field(
        "delete_collection",
        json_schema_extra={
            "const": "delete_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Delete Collection",
            "x-keywords": ["remove collection", "drop collection", "destroy collection"],
        },
        title="Delete Collection",
    )
    collection: str = Field(
        ..., title="Collection",
        description="Name of the collection to delete. This is irreversible.",
        json_schema_extra=_COLLECTION_FIELD_EXTRA,
    )


# ============================================================================
# Point operations — additional ops
# ============================================================================


class QdrantScrollConfig(BaseModel):
    """Scroll through all points in a collection with optional filter and cursor-based pagination."""

    operation: Literal["scroll"] = Field(
        "scroll",
        json_schema_extra={
            "const": "scroll", "ui:hidden": True,
            "x-category": "Points", "x-is-trigger": False,
            "x-display-name": "Scroll Points",
            "x-keywords": ["list points", "iterate points", "browse collection", "paginate", "all points"],
        },
        title="Scroll Points",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    limit: int = Field(10, title="Limit", description="Number of points to return per page")
    offset: Optional[str] = Field(
        None, title="Offset",
        description="Point ID to start from (use next_page_offset from previous response for pagination)",
    )
    filter: Optional[str] = Field(
        None, title="Filter",
        description='Optional Qdrant JSON filter to select only matching points',
    )
    with_payload: str = Field("true", title="Include Payload", json_schema_extra=_BOOL_ENUM_EXTRA)
    with_vector: str = Field("false", title="Include Vector", json_schema_extra=_BOOL_ENUM_EXTRA)
    order_by: Optional[str] = Field(
        None, title="Order By",
        description="Payload field name to sort by, e.g. \"created_at\"",
    )


class QdrantCountConfig(BaseModel):
    """Count points in a collection, with optional filter."""

    operation: Literal["count"] = Field(
        "count",
        json_schema_extra={
            "const": "count", "ui:hidden": True,
            "x-category": "Points", "x-is-trigger": False,
            "x-display-name": "Count Points",
            "x-keywords": ["count points", "collection size", "how many points", "filter count"],
        },
        title="Count Points",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: Optional[str] = Field(
        None, title="Filter",
        description="Optional Qdrant JSON filter — counts only matching points if provided",
    )
    exact: str = Field(
        "true", title="Exact Count",
        description="Use exact count (slower) vs approximate count (faster for large collections)",
        json_schema_extra=_BOOL_ENUM_EXTRA,
    )


class QdrantRecommendConfig(BaseModel):
    """Find points similar to positive examples and dissimilar from negative examples."""

    operation: Literal["recommend"] = Field(
        "recommend",
        json_schema_extra={
            "const": "recommend", "ui:hidden": True,
            "x-category": "Points", "x-is-trigger": False,
            "x-display-name": "Recommend Points",
            "x-keywords": ["recommend", "similar items", "positive negative examples", "collaborative filtering", "more like this"],
        },
        title="Recommend Points",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    positive: str = Field(
        ..., title="Positive Examples",
        description="JSON array of point IDs or vectors to use as positive examples, e.g. [1, 2] or [[0.1, ...]]",
        json_schema_extra={"ui:widget": "textarea"},
    )
    negative: Optional[str] = Field(
        None, title="Negative Examples",
        description="JSON array of point IDs or vectors to push results away from",
    )
    limit: int = Field(10, title="Limit", description="Number of results to return")
    filter: Optional[str] = Field(None, title="Filter", description="Optional Qdrant JSON filter")
    with_payload: str = Field("true", title="Include Payload", json_schema_extra=_BOOL_ENUM_EXTRA)
    with_vector: str = Field("false", title="Include Vector", json_schema_extra=_BOOL_ENUM_EXTRA)
    score_threshold: Optional[float] = Field(None, title="Score Threshold", description="Minimum score cutoff")
    strategy: str = Field(
        "average_vector", title="Strategy",
        json_schema_extra={"enum": ["average_vector", "best_score"], "x-enum-searchable": True},
    )


# ============================================================================
# Payload operations
# ============================================================================


class QdrantSetPayloadConfig(BaseModel):
    """Set (merge) payload fields on points selected by IDs or filter."""

    operation: Literal["set_payload"] = Field(
        "set_payload",
        json_schema_extra={
            "const": "set_payload", "ui:hidden": True,
            "x-category": "Payload", "x-is-trigger": False,
            "x-display-name": "Set Payload",
            "x-keywords": ["update payload", "add metadata", "set fields", "update point metadata"],
        },
        title="Set Payload",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    payload: str = Field(
        ..., title="Payload",
        description='JSON object with fields to set/merge, e.g. {"status": "processed", "score": 0.9}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    ids: Optional[str] = Field(None, title="Point IDs", description="Comma-separated point IDs to update")
    filter: Optional[str] = Field(None, title="Filter", description="Qdrant JSON filter — update matching points instead of by ID")


class QdrantDeletePayloadConfig(BaseModel):
    """Delete specific payload keys from points."""

    operation: Literal["delete_payload"] = Field(
        "delete_payload",
        json_schema_extra={
            "const": "delete_payload", "ui:hidden": True,
            "x-category": "Payload", "x-is-trigger": False,
            "x-display-name": "Delete Payload Keys",
            "x-keywords": ["remove payload fields", "delete metadata keys", "clear fields"],
        },
        title="Delete Payload Keys",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    keys: str = Field(
        ..., title="Keys",
        description="Comma-separated payload field names to remove, e.g. temp_field,legacy_tag",
    )
    ids: Optional[str] = Field(None, title="Point IDs", description="Comma-separated point IDs")
    filter: Optional[str] = Field(None, title="Filter", description="Qdrant JSON filter — update matching points instead of by ID")


class QdrantClearPayloadConfig(BaseModel):
    """Remove all payload from points selected by IDs or filter."""

    operation: Literal["clear_payload"] = Field(
        "clear_payload",
        json_schema_extra={
            "const": "clear_payload", "ui:hidden": True,
            "x-category": "Payload", "x-is-trigger": False,
            "x-display-name": "Clear Payload",
            "x-keywords": ["wipe payload", "remove all metadata", "clear all fields"],
        },
        title="Clear Payload",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    ids: Optional[str] = Field(None, title="Point IDs", description="Comma-separated point IDs")
    filter: Optional[str] = Field(None, title="Filter", description="Qdrant JSON filter — clear payload on matching points")


# ============================================================================
# Payload index operations
# ============================================================================


class QdrantCreatePayloadIndexConfig(BaseModel):
    """Create a payload field index to speed up filtered searches."""

    operation: Literal["create_payload_index"] = Field(
        "create_payload_index",
        json_schema_extra={
            "const": "create_payload_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Create Payload Index",
            "x-keywords": ["index field", "add index", "filter performance", "payload index"],
        },
        title="Create Payload Index",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    field_name: str = Field(..., title="Field Name", description="Payload field to index, e.g. category")
    field_schema: str = Field(
        "keyword", title="Field Type",
        description="Index type matching the field's data type",
        json_schema_extra={
            "enum": ["keyword", "integer", "float", "bool", "geo", "text", "datetime", "uuid"],
            "x-enum-searchable": True,
        },
    )


class QdrantDeletePayloadIndexConfig(BaseModel):
    """Delete a payload field index."""

    operation: Literal["delete_payload_index"] = Field(
        "delete_payload_index",
        json_schema_extra={
            "const": "delete_payload_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Delete Payload Index",
            "x-keywords": ["remove index", "drop index", "delete field index"],
        },
        title="Delete Payload Index",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    field_name: str = Field(..., title="Field Name", description="Name of the payload field whose index to delete")


# ============================================================================
# Discriminated Union
# ============================================================================


QdrantConfig = Annotated[
    Union[
        QdrantQueryConfig,
        QdrantUpsertConfig,
        QdrantRetrieveConfig,
        QdrantDeleteConfig,
        QdrantScrollConfig,
        QdrantCountConfig,
        QdrantRecommendConfig,
        QdrantListCollectionsConfig,
        QdrantGetCollectionConfig,
        QdrantCreateCollectionConfig,
        QdrantUpdateCollectionConfig,
        QdrantDeleteCollectionConfig,
        QdrantSetPayloadConfig,
        QdrantDeletePayloadConfig,
        QdrantClearPayloadConfig,
        QdrantCreatePayloadIndexConfig,
        QdrantDeletePayloadIndexConfig,
        QdrantUploadIndexConfig,
    ],
    Discriminator("operation"),
]


class QdrantNodeConfig(NodeConfig[QdrantConfig, QdrantCredential]):
    """Full configuration for the Qdrant node including credentials."""

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


def _parse_json_obj(value: Any) -> Optional[Dict[str, Any]]:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _coerce_point_ids(raw: Optional[str]) -> List[Any]:
    """Qdrant point IDs are unsigned ints or UUID strings. Numeric strings →
    int; everything else passes through as a string."""
    ids: List[Any] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        ids.append(int(part) if part.isdigit() else part)
    return ids


# ============================================================================
# Node Implementation
# ============================================================================


class QdrantNode(WorkflowNode):
    """Qdrant vector database automation node."""

    edit_examples = [
        "Search a Qdrant collection for the points most similar to a query embedding",
        "Upsert document embeddings into a Qdrant collection with payload metadata",
        "Delete points matching a payload filter before re-indexing",
        "Retrieve specific points by ID to inspect their payload",
        "Create a new collection for a 1536-dimension embedding model",
    ]

    @classmethod
    def get_config_model(cls):
        return QdrantNodeConfig

    @staticmethod
    def _base_url(credential: QdrantCredential) -> str:
        return (credential.url or "").rstrip("/")

    @staticmethod
    def _headers(credential: QdrantCredential) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": "NoClick-Workflow/1.0",
            "api-key": credential.api_key,
        }

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Populate the collection dropdown from the Qdrant cluster."""
        if field_name != "collection":
            return []
        url = (credential_data or {}).get("url")
        if not url:
            return []
        headers = {"Content-Type": "application/json"}
        if credential_data.get("api_key"):
            headers["api-key"] = credential_data["api_key"]
        try:
            async with guarded_async_client(timeout=20.0) as client:
                resp = await client.get(f"{url.rstrip('/')}/collections", headers=headers)
        except httpx.HTTPError as e:
            logger.warning(f"[QdrantNode] Failed to list collections: {e}")
            return []
        if resp.status_code >= 400:
            logger.warning(f"[QdrantNode] List collections returned {resp.status_code}: {resp.text}")
            return []
        collections = (resp.json().get("result") or {}).get("collections", []) or []
        options = []
        for col in collections:
            name = col.get("name")
            if not name:
                continue
            if search and search.lower() not in name.lower():
                continue
            options.append({"value": name, "label": name})
        return options

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, QdrantNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Qdrant URL and API key.")

        op_config = config.config
        handlers = {
            "query": self._handle_query,
            "upsert": self._handle_upsert,
            "retrieve": self._handle_retrieve,
            "delete": self._handle_delete,
            "scroll": self._handle_scroll,
            "count": self._handle_count,
            "recommend": self._handle_recommend,
            "list_collections": self._handle_list_collections,
            "get_collection": self._handle_get_collection,
            "create_collection": self._handle_create_collection,
            "update_collection": self._handle_update_collection,
            "delete_collection": self._handle_delete_collection,
            "set_payload": self._handle_set_payload,
            "delete_payload": self._handle_delete_payload,
            "clear_payload": self._handle_clear_payload,
            "create_payload_index": self._handle_create_payload_index,
            "delete_payload_index": self._handle_delete_payload_index,
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
        credential: QdrantCredential,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        start_time = time.time()
        if json_body is not None:
            json_body = {k: v for k, v in json_body.items() if v is not None}
        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers(credential),
                    json=json_body,
                    params=params,
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
                status_obj = error_data.get("status")
                if isinstance(status_obj, dict):
                    error_message = status_obj.get("error", str(error_data))
                else:
                    error_message = error_data.get("error", str(error_data))
            except Exception:
                error_message = response.text
            logger.error(f"[QdrantNode] API error ({action_name}): {error_message}")
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

    async def _handle_query(self, config: QdrantQueryConfig, credentials) -> Dict[str, Any]:
        vector = _parse_json_list(config.vector)
        if vector is None:
            return {
                "status": "error",
                "action": "query",
                "error": "`vector` must be a JSON array of numbers",
            }
        body: Dict[str, Any] = {
            "query": vector,
            "limit": config.limit,
            "with_payload": config.with_payload == "true",
            "with_vector": config.with_vector == "true",
        }
        metadata_filter = _parse_json_obj(config.filter)
        if metadata_filter:
            body["filter"] = metadata_filter
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/query"
        return await self._request("POST", url, credentials, json_body=body, action_name="query")

    async def _handle_upsert(self, config: QdrantUpsertConfig, credentials) -> Dict[str, Any]:
        points = _parse_json_list(config.points)
        if points is None:
            return {
                "status": "error",
                "action": "upsert",
                "error": "`points` must be a JSON array of {id, vector, payload} objects",
            }
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points"
        return await self._request(
            "PUT", url, credentials, json_body={"points": points}, params={"wait": "true"}, action_name="upsert"
        )

    async def _handle_retrieve(self, config: QdrantRetrieveConfig, credentials) -> Dict[str, Any]:
        ids = _coerce_point_ids(config.ids)
        if not ids:
            return {"status": "error", "action": "retrieve", "error": "Provide at least one point ID"}
        body = {
            "ids": ids,
            "with_payload": config.with_payload == "true",
            "with_vector": config.with_vector == "true",
        }
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points"
        return await self._request("POST", url, credentials, json_body=body, action_name="retrieve")

    async def _handle_delete(self, config: QdrantDeleteConfig, credentials) -> Dict[str, Any]:
        ids = _coerce_point_ids(config.ids)
        if ids:
            body: Dict[str, Any] = {"points": ids}
        else:
            metadata_filter = _parse_json_obj(config.filter)
            if not metadata_filter:
                return {
                    "status": "error",
                    "action": "delete",
                    "error": "Specify point IDs or a filter to delete",
                }
            body = {"filter": metadata_filter}
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/delete"
        return await self._request(
            "POST", url, credentials, json_body=body, params={"wait": "true"}, action_name="delete"
        )

    async def _handle_scroll(self, config: QdrantScrollConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "limit": config.limit,
            "with_payload": config.with_payload == "true",
            "with_vector": config.with_vector == "true",
        }
        if config.offset:
            raw = config.offset.strip()
            body["offset"] = int(raw) if raw.isdigit() else raw
        if config.filter:
            f = _parse_json_obj(config.filter)
            if f:
                body["filter"] = f
        if config.order_by:
            body["order_by"] = config.order_by
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/scroll"
        return await self._request("POST", url, credentials, json_body=body, action_name="scroll")

    async def _handle_count(self, config: QdrantCountConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"exact": config.exact == "true"}
        if config.filter:
            f = _parse_json_obj(config.filter)
            if f:
                body["filter"] = f
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/count"
        return await self._request("POST", url, credentials, json_body=body, action_name="count")

    async def _handle_recommend(self, config: QdrantRecommendConfig, credentials) -> Dict[str, Any]:
        positive = _parse_json_list(config.positive)
        if positive is None:
            return {"status": "error", "action": "recommend",
                    "error": "`positive` must be a JSON array of point IDs or vectors"}
        body: Dict[str, Any] = {
            "positive": positive,
            "limit": config.limit,
            "with_payload": config.with_payload == "true",
            "with_vector": config.with_vector == "true",
            "strategy": config.strategy,
        }
        if config.negative:
            neg = _parse_json_list(config.negative)
            if neg:
                body["negative"] = neg
        if config.filter:
            f = _parse_json_obj(config.filter)
            if f:
                body["filter"] = f
        if config.score_threshold is not None:
            body["score_threshold"] = config.score_threshold
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/recommend"
        return await self._request("POST", url, credentials, json_body=body, action_name="recommend")

    async def _handle_list_collections(self, config: QdrantListCollectionsConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/collections"
        return await self._request("GET", url, credentials, action_name="list_collections")

    async def _handle_get_collection(self, config: QdrantGetCollectionConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/collections/{config.collection}"
        return await self._request("GET", url, credentials, action_name="get_collection")

    async def _handle_create_collection(self, config: QdrantCreateCollectionConfig, credentials) -> Dict[str, Any]:
        body = {"vectors": {"size": config.size, "distance": config.distance}}
        url = f"{self._base_url(credentials)}/collections/{config.name}"
        return await self._request("PUT", url, credentials, json_body=body, action_name="create_collection")

    async def _handle_update_collection(self, config: QdrantUpdateCollectionConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if config.optimizers_config:
            obj = _parse_json_obj(config.optimizers_config)
            if obj:
                body["optimizers_config"] = obj
        if config.hnsw_config:
            obj = _parse_json_obj(config.hnsw_config)
            if obj:
                body["hnsw_config"] = obj
        if not body:
            return {"status": "error", "action": "update_collection",
                    "error": "Provide at least one setting to update: optimizers_config or hnsw_config"}
        url = f"{self._base_url(credentials)}/collections/{config.collection}"
        return await self._request("PATCH", url, credentials, json_body=body, action_name="update_collection")

    async def _handle_delete_collection(self, config: QdrantDeleteCollectionConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/collections/{config.collection}"
        return await self._request("DELETE", url, credentials, action_name="delete_collection")

    async def _handle_set_payload(self, config: QdrantSetPayloadConfig, credentials) -> Dict[str, Any]:
        payload_obj = _parse_json_obj(config.payload)
        if payload_obj is None:
            return {"status": "error", "action": "set_payload",
                    "error": "`payload` must be a JSON object of key-value fields"}
        body: Dict[str, Any] = {"payload": payload_obj}
        ids = _coerce_point_ids(config.ids)
        if ids:
            body["points"] = ids
        elif config.filter:
            f = _parse_json_obj(config.filter)
            if f:
                body["filter"] = f
            else:
                return {"status": "error", "action": "set_payload",
                        "error": "Provide point IDs or a valid filter"}
        else:
            return {"status": "error", "action": "set_payload",
                    "error": "Specify point IDs or a filter to target"}
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/payload"
        return await self._request("POST", url, credentials, json_body=body,
                                   params={"wait": "true"}, action_name="set_payload")

    async def _handle_delete_payload(self, config: QdrantDeletePayloadConfig, credentials) -> Dict[str, Any]:
        keys = [k.strip() for k in config.keys.split(",") if k.strip()]
        if not keys:
            return {"status": "error", "action": "delete_payload", "error": "Provide at least one key to delete"}
        body: Dict[str, Any] = {"keys": keys}
        ids = _coerce_point_ids(config.ids)
        if ids:
            body["points"] = ids
        elif config.filter:
            f = _parse_json_obj(config.filter)
            if f:
                body["filter"] = f
            else:
                return {"status": "error", "action": "delete_payload",
                        "error": "Provide point IDs or a valid filter"}
        else:
            return {"status": "error", "action": "delete_payload",
                    "error": "Specify point IDs or a filter to target"}
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/payload/delete"
        return await self._request("POST", url, credentials, json_body=body,
                                   params={"wait": "true"}, action_name="delete_payload")

    async def _handle_clear_payload(self, config: QdrantClearPayloadConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        ids = _coerce_point_ids(config.ids)
        if ids:
            body["points"] = ids
        elif config.filter:
            f = _parse_json_obj(config.filter)
            if f:
                body["filter"] = f
            else:
                return {"status": "error", "action": "clear_payload",
                        "error": "Provide point IDs or a valid filter"}
        else:
            return {"status": "error", "action": "clear_payload",
                    "error": "Specify point IDs or a filter to target"}
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points/payload/clear"
        return await self._request("POST", url, credentials, json_body=body,
                                   params={"wait": "true"}, action_name="clear_payload")

    async def _handle_create_payload_index(self, config: QdrantCreatePayloadIndexConfig, credentials) -> Dict[str, Any]:
        body = {"field_name": config.field_name, "field_schema": config.field_schema}
        url = f"{self._base_url(credentials)}/collections/{config.collection}/index"
        return await self._request("PUT", url, credentials, json_body=body,
                                   params={"wait": "true"}, action_name="create_payload_index")

    async def _handle_delete_payload_index(self, config: QdrantDeletePayloadIndexConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/collections/{config.collection}/index/{config.field_name}"
        return await self._request("DELETE", url, credentials,
                                   params={"wait": "true"}, action_name="delete_payload_index")

    async def _handle_upload_and_index(self, config: QdrantUploadIndexConfig, credentials) -> Dict[str, Any]:
        records, info = await ingest_document(
            self, config.document, chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap, id_prefix=config.id_prefix
        )
        if not records:
            return {"status": "error", "action": "upload_and_index", "error": "No text could be extracted from the document"}
        points = [{"id": r["id"], "vector": r["values"], "payload": r["metadata"]} for r in records]
        url = f"{self._base_url(credentials)}/collections/{config.collection}/points"
        result = await self._request(
            "PUT", url, credentials, json_body={"points": points}, params={"wait": "true"}, action_name="upload_and_index"
        )
        if result.get("status") == "success":
            result["data"] = {"chunks_indexed": len(records), "source": info.get("filename"), "raw": result.get("data")}
        return result
