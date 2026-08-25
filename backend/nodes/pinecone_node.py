"""
Pinecone vector database automation node.

Provides workflow integration with Pinecone for vector operations:
- Vectors: query, upsert, fetch, delete, update, list
- Index management: list, describe, create, configure, delete
- Index stats: describe_index_stats
- Integrated inference (text-native): create_index_for_model, upsert_records, search_records
- Inference API: generate_embeddings, rerank
- Bulk import: start, list, describe, cancel
- Documents: upload_and_index (client-side embedding + upsert)

Authentication: API Key (``Api-Key`` header) — single method for all operations.
Control plane: https://api.pinecone.io
Data plane: per-index host, resolved on demand via describe-index and cached per execution
Inference API: https://api.pinecone.io/embed + /rerank
Docs: https://docs.pinecone.io/reference/api
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.document_ingest import DOCUMENT_ACCEPT, ingest_document
from utils.ssrf import (
    SSRFError,
    guarded_async_client,
    normalize_provider_subdomain,
)

logger = logging.getLogger(__name__)

PINECONE_CONTROL_BASE = "https://api.pinecone.io"
# 2025-10 is the current stable version; avoid *.alpha shapes.
PINECONE_API_VERSION = "2025-10"


def _pinecone_data_host(value: Any) -> str:
    """Return a canonical provider-owned Pinecone data-plane hostname."""
    raw_host = str(value or "").strip().rstrip(".")
    if not raw_host or "://" in raw_host:
        raise SSRFError("Pinecone returned an invalid data-plane host")
    try:
        parts = urlsplit(f"//{raw_host}")
        port = parts.port
    except ValueError as error:
        raise SSRFError("Pinecone returned an invalid data-plane host") from error
    host = (parts.hostname or "").lower().rstrip(".")
    if (
        parts.username is not None
        or parts.password is not None
        or port is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or not host.endswith(".pinecone.io")
        or host == "pinecone.io"
    ):
        raise SSRFError("Pinecone data-plane host must be under pinecone.io")
    tenant = normalize_provider_subdomain(
        host,
        "pinecone.io",
        field_name="Pinecone data-plane host",
        allow_nested_labels=True,
    )
    return f"{tenant}.pinecone.io"

_INDEX_FIELD_EXTRA = {
    "x-resource-type": "pinecone_index",
    "x-dynamic-options": {
        "field_name": "index",
        "placeholder": "Select an index...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type the index name",
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


class PineconeAPIKeyCredential(BaseModel):
    """API Key credential for Pinecone."""

    credential_type: Literal["pinecone_api_key"] = Field(
        "pinecone_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Pinecone API key from the console (App → API Keys)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.pinecone.io/organizations/-/keys"}
    )


PineconeCredential = PineconeAPIKeyCredential

# ============================================================================
# Operation Configs — Vectors
# ============================================================================


class PineconeQueryConfig(BaseModel):
    """Find the most similar vectors to a query vector (similarity search)."""

    operation: Literal["query"] = Field(
        "query",
        json_schema_extra={
            "const": "query",
            "ui:hidden": True,
            "x-category": "Vectors",
            "x-is-trigger": False,
            "x-display-name": "Query / Search",
            "x-keywords": ["search", "similarity search", "semantic search", "retrieve",
                           "nearest neighbors", "vector search", "rag"],
        },
        title="Query / Search",
    )
    index: str = Field(..., title="Index", description="Pinecone index to query",
                       json_schema_extra=_INDEX_FIELD_EXTRA)
    vector: Optional[str] = Field(
        None, title="Query Vector",
        description="Embedding to search with — a JSON array of numbers, e.g. [0.1, 0.2, ...]. Provide this OR a vector ID.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    id: Optional[str] = Field(
        None, title="By Vector ID",
        description="Instead of a vector, return neighbours of an existing vector by its ID",
    )
    top_k: int = Field(10, title="Top K", description="Number of most-similar matches to return")
    namespace: Optional[str] = Field(
        None, title="Namespace",
        description="Namespace to query (uses the default namespace if blank)",
    )
    filter: Optional[str] = Field(
        None, title="Metadata Filter",
        description='Optional JSON metadata filter, e.g. {"genre": {"$eq": "comedy"}}',
    )
    include_metadata: str = Field("true", title="Include Metadata", json_schema_extra=_BOOL_ENUM_EXTRA)
    include_values: str = Field("false", title="Include Values", json_schema_extra=_BOOL_ENUM_EXTRA)


class PineconeUpsertConfig(BaseModel):
    """Insert or overwrite vectors in an index."""

    operation: Literal["upsert"] = Field(
        "upsert",
        json_schema_extra={
            "const": "upsert", "ui:hidden": True,
            "x-category": "Vectors", "x-is-trigger": False,
            "x-display-name": "Upsert Vectors",
            "x-keywords": ["insert", "index", "add vectors", "store", "write", "embed"],
        },
        title="Upsert Vectors",
    )
    index: str = Field(..., title="Index", description="Pinecone index to write to",
                       json_schema_extra=_INDEX_FIELD_EXTRA)
    vectors: str = Field(
        ..., title="Vectors",
        description='JSON array of vectors: [{"id": "a", "values": [0.1, ...], "metadata": {"source": "doc1"}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    namespace: Optional[str] = Field(None, title="Namespace",
                                     description="Namespace to write to (default if blank)")


class PineconeFetchConfig(BaseModel):
    """Fetch vectors by their IDs."""

    operation: Literal["fetch"] = Field(
        "fetch",
        json_schema_extra={
            "const": "fetch", "ui:hidden": True,
            "x-category": "Vectors", "x-is-trigger": False,
            "x-display-name": "Fetch Vectors",
            "x-keywords": ["get", "lookup by id", "read vectors"],
        },
        title="Fetch Vectors",
    )
    index: str = Field(..., title="Index", description="Pinecone index",
                       json_schema_extra=_INDEX_FIELD_EXTRA)
    ids: str = Field(..., title="IDs", description="Vector IDs to fetch, comma-separated")
    namespace: Optional[str] = Field(None, title="Namespace")


class PineconeDeleteConfig(BaseModel):
    """Delete vectors by ID, by metadata filter, or clear a namespace."""

    operation: Literal["delete"] = Field(
        "delete",
        json_schema_extra={
            "const": "delete", "ui:hidden": True,
            "x-category": "Vectors", "x-is-trigger": False,
            "x-display-name": "Delete Vectors",
            "x-keywords": ["remove", "clear", "purge vectors"],
        },
        title="Delete Vectors",
    )
    index: str = Field(..., title="Index", description="Pinecone index",
                       json_schema_extra=_INDEX_FIELD_EXTRA)
    ids: Optional[str] = Field(None, title="IDs", description="Vector IDs to delete, comma-separated")
    delete_all: str = Field(
        "false", title="Delete All in Namespace",
        description="Delete every vector in the namespace",
        json_schema_extra=_BOOL_ENUM_EXTRA,
    )
    filter: Optional[str] = Field(
        None, title="Metadata Filter",
        description='Delete vectors matching a JSON metadata filter, e.g. {"source": {"$eq": "doc1"}}',
    )
    namespace: Optional[str] = Field(None, title="Namespace")


class PineconeUpdateVectorConfig(BaseModel):
    """Partially update values or metadata on a single existing vector."""

    operation: Literal["update_vector"] = Field(
        "update_vector",
        json_schema_extra={
            "const": "update_vector", "ui:hidden": True,
            "x-category": "Vectors", "x-is-trigger": False,
            "x-display-name": "Update Vector",
            "x-keywords": ["patch vector", "update metadata", "set metadata", "modify vector"],
        },
        title="Update Vector",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    id: str = Field(..., title="Vector ID", description="ID of the vector to update")
    values: Optional[str] = Field(
        None, title="New Values",
        description="Replacement float array as JSON, e.g. [0.1, 0.2, ...]. Omit to leave values unchanged.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    set_metadata: Optional[str] = Field(
        None, title="Set Metadata",
        description="JSON object of metadata keys to set/overwrite, e.g. {\"source\": \"v2\"}",
    )
    namespace: Optional[str] = Field(None, title="Namespace")


class PineconeListVectorsConfig(BaseModel):
    """List vector IDs in a namespace by prefix (serverless indexes only)."""

    operation: Literal["list_vectors"] = Field(
        "list_vectors",
        json_schema_extra={
            "const": "list_vectors", "ui:hidden": True,
            "x-category": "Vectors", "x-is-trigger": False,
            "x-display-name": "List Vectors",
            "x-keywords": ["list ids", "paginate vectors", "enumerate vectors"],
        },
        title="List Vectors",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    namespace: Optional[str] = Field(None, title="Namespace")
    prefix: Optional[str] = Field(None, title="ID Prefix", description="Only return IDs starting with this prefix")
    limit: int = Field(100, title="Limit", description="Max IDs to return (1–100)")
    pagination_token: Optional[str] = Field(None, title="Pagination Token",
                                            description="Token from a previous response to fetch the next page")


class PineconeDescribeIndexStatsConfig(BaseModel):
    """Get per-namespace vector counts, total dimension, and index fullness."""

    operation: Literal["describe_index_stats"] = Field(
        "describe_index_stats",
        json_schema_extra={
            "const": "describe_index_stats", "ui:hidden": True,
            "x-category": "Vectors", "x-is-trigger": False,
            "x-display-name": "Describe Index Stats",
            "x-keywords": ["stats", "vector count", "namespace count", "index fullness", "usage"],
        },
        title="Describe Index Stats",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    filter: Optional[str] = Field(
        None, title="Metadata Filter",
        description="Optional JSON metadata filter to scope the stats query",
    )


# ============================================================================
# Operation Configs — Index Management
# ============================================================================


class PineconeListIndexesConfig(BaseModel):
    """List all indexes in the project."""

    operation: Literal["list_indexes"] = Field(
        "list_indexes",
        json_schema_extra={
            "const": "list_indexes", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "List Indexes",
            "x-keywords": ["list", "show indexes", "describe"],
        },
        title="List Indexes",
    )


class PineconeDescribeIndexConfig(BaseModel):
    """Get full details for a single index: status, host, metric, dimension, spec."""

    operation: Literal["describe_index"] = Field(
        "describe_index",
        json_schema_extra={
            "const": "describe_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Describe Index",
            "x-keywords": ["get index", "index details", "index status", "index host"],
        },
        title="Describe Index",
    )
    index: str = Field(..., title="Index Name", description="Name of the index to describe",
                       json_schema_extra=_INDEX_FIELD_EXTRA)


class PineconeCreateIndexConfig(BaseModel):
    """Create a new serverless index."""

    operation: Literal["create_index"] = Field(
        "create_index",
        json_schema_extra={
            "const": "create_index", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "pinecone_index",
            "x-resource-id-path": "data.name",
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Create Index",
            "x-keywords": ["new index", "provision", "setup"],
        },
        title="Create Index",
    )
    name: str = Field(..., title="Name", description="Name for the new index")
    dimension: int = Field(..., title="Dimension",
                           description="Vector dimensionality (must match your embedding model)")
    metric: str = Field(
        "cosine", title="Metric", description="Distance metric",
        json_schema_extra={"enum": ["cosine", "euclidean", "dotproduct"], "x-enum-searchable": True},
    )
    cloud: str = Field(
        "aws", title="Cloud",
        json_schema_extra={"enum": ["aws", "gcp", "azure"], "x-enum-searchable": True},
    )
    region: str = Field("us-east-1", title="Region", description="Cloud region, e.g. us-east-1")
    deletion_protection: str = Field(
        "disabled", title="Deletion Protection",
        json_schema_extra={"enum": ["enabled", "disabled"], "x-enum-searchable": True},
    )


class PineconeConfigureIndexConfig(BaseModel):
    """Change deletion protection or pod replica/type on an existing index."""

    operation: Literal["configure_index"] = Field(
        "configure_index",
        json_schema_extra={
            "const": "configure_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Configure Index",
            "x-keywords": ["update index", "scale index", "deletion protection", "replicas"],
        },
        title="Configure Index",
    )
    index: str = Field(..., title="Index Name", json_schema_extra=_INDEX_FIELD_EXTRA)
    deletion_protection: Optional[str] = Field(
        None, title="Deletion Protection",
        json_schema_extra={"enum": ["enabled", "disabled"], "x-enum-searchable": True},
    )
    replicas: Optional[int] = Field(None, title="Replicas",
                                    description="Number of replicas (pod-based indexes only)")
    pod_type: Optional[str] = Field(None, title="Pod Type",
                                    description="Pod type for scale-up (pod-based indexes only), e.g. p1.x2")


class PineconeDeleteIndexConfig(BaseModel):
    """Delete an index and all its vectors permanently."""

    operation: Literal["delete_index"] = Field(
        "delete_index",
        json_schema_extra={
            "const": "delete_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Delete Index",
            "x-keywords": ["remove index", "drop index", "destroy index"],
        },
        title="Delete Index",
    )
    index: str = Field(..., title="Index Name",
                       description="Name of the index to delete. This is irreversible.",
                       json_schema_extra=_INDEX_FIELD_EXTRA)


# ============================================================================
# Operation Configs — Integrated Inference (text-native indexes)
# ============================================================================


class PineconeCreateIndexForModelConfig(BaseModel):
    """Create a text-native index that embeds content server-side (no dimension needed)."""

    operation: Literal["create_index_for_model"] = Field(
        "create_index_for_model",
        json_schema_extra={
            "const": "create_index_for_model", "ui:hidden": True,
            "x-category": "Integrated Inference", "x-is-trigger": False,
            "x-display-name": "Create Index for Model",
            "x-keywords": ["text native index", "integrated embedding", "create for model", "auto embed"],
        },
        title="Create Index for Model",
    )
    name: str = Field(..., title="Name", description="Name for the new index")
    embed_model: str = Field(
        "multilingual-e5-large", title="Embedding Model",
        description="Pinecone-hosted embedding model to use for this index",
        json_schema_extra={
            "enum": ["multilingual-e5-large", "llama-text-embed-v2"],
            "x-enum-searchable": True,
        },
    )
    field_map_text: str = Field(
        "text", title="Text Field",
        description="Name of the field in your records that holds the text to embed",
    )
    cloud: str = Field(
        "aws", title="Cloud",
        json_schema_extra={"enum": ["aws", "gcp", "azure"], "x-enum-searchable": True},
    )
    region: str = Field("us-east-1", title="Region")


class PineconeUpsertRecordsConfig(BaseModel):
    """Upsert text records into a text-native index (server-side embedding, no vectors needed)."""

    operation: Literal["upsert_records"] = Field(
        "upsert_records",
        json_schema_extra={
            "const": "upsert_records", "ui:hidden": True,
            "x-category": "Integrated Inference", "x-is-trigger": False,
            "x-display-name": "Upsert Records (Text-Native)",
            "x-keywords": ["upsert text", "text native upsert", "auto embed records", "insert records"],
        },
        title="Upsert Records (Text-Native)",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    namespace: str = Field(..., title="Namespace",
                           description="Namespace to write records into (required for text-native indexes)")
    records: str = Field(
        ..., title="Records",
        description='JSON array of records, e.g. [{"id": "r1", "text": "Hello world", "category": "greet"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class PineconeSearchRecordsConfig(BaseModel):
    """Search a text-native index with a text query (server-side embedding + optional rerank)."""

    operation: Literal["search_records"] = Field(
        "search_records",
        json_schema_extra={
            "const": "search_records", "ui:hidden": True,
            "x-category": "Integrated Inference", "x-is-trigger": False,
            "x-display-name": "Search Records (Text-Native)",
            "x-keywords": ["text search", "natural language search", "search records", "rerank"],
        },
        title="Search Records (Text-Native)",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    namespace: str = Field(..., title="Namespace")
    query_text: str = Field(..., title="Query Text",
                            description="Natural language query — the index embeds it server-side")
    top_k: int = Field(10, title="Top K")
    filter: Optional[str] = Field(None, title="Metadata Filter",
                                  description='JSON metadata filter, e.g. {"category": {"$eq": "greet"}}')
    rerank_model: Optional[str] = Field(
        None, title="Rerank Model",
        description="Optional: rerank results with this model, e.g. bge-reranker-v2-m3",
        json_schema_extra={"enum": ["bge-reranker-v2-m3", ""], "x-enum-searchable": True},
    )
    rerank_top_n: Optional[int] = Field(None, title="Rerank Top N",
                                        description="How many results to keep after reranking (defaults to top_k)")


# ============================================================================
# Operation Configs — Inference API (standalone, no index)
# ============================================================================


class PineconeGenerateEmbeddingsConfig(BaseModel):
    """Generate dense embeddings using Pinecone's hosted models."""

    operation: Literal["generate_embeddings"] = Field(
        "generate_embeddings",
        json_schema_extra={
            "const": "generate_embeddings", "ui:hidden": True,
            "x-category": "Inference", "x-is-trigger": False,
            "x-display-name": "Generate Embeddings",
            "x-keywords": ["embed", "vectorize", "embedding", "encode text", "pinecone inference"],
        },
        title="Generate Embeddings",
    )
    model: str = Field(
        "multilingual-e5-large", title="Model",
        json_schema_extra={
            "enum": ["multilingual-e5-large", "llama-text-embed-v2"],
            "x-enum-searchable": True,
        },
    )
    inputs: str = Field(
        ..., title="Inputs",
        description='JSON array of text strings to embed, e.g. ["Hello world", "Foo bar"]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    input_type: Optional[str] = Field(
        None, title="Input Type",
        description="passage (for indexing) or query (for search). Leave blank to let the model decide.",
        json_schema_extra={"enum": ["passage", "query", ""], "x-enum-searchable": True},
    )
    truncate: str = Field(
        "END", title="Truncate",
        description="How to handle inputs exceeding the model's token limit",
        json_schema_extra={"enum": ["NONE", "END"], "x-enum-searchable": True},
    )


class PineconeRerankConfig(BaseModel):
    """Rerank a set of documents against a query using Pinecone's reranking model."""

    operation: Literal["rerank"] = Field(
        "rerank",
        json_schema_extra={
            "const": "rerank", "ui:hidden": True,
            "x-category": "Inference", "x-is-trigger": False,
            "x-display-name": "Rerank Documents",
            "x-keywords": ["rerank", "cross-encoder", "result ranking", "relevance score"],
        },
        title="Rerank Documents",
    )
    model: str = Field(
        "bge-reranker-v2-m3", title="Model",
        json_schema_extra={"enum": ["bge-reranker-v2-m3"], "x-enum-searchable": True},
    )
    query: str = Field(..., title="Query", description="The search query to rank documents against")
    documents: str = Field(
        ..., title="Documents",
        description='JSON array of document strings or objects, e.g. ["Hello", "World"] or [{"text": "Hello"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    top_n: Optional[int] = Field(None, title="Top N",
                                 description="Number of top results to return (defaults to all)")
    rank_fields: Optional[str] = Field(
        None, title="Rank Fields",
        description="Comma-separated field names to use for ranking when documents are objects, e.g. text,title",
    )
    return_documents: str = Field(
        "true", title="Return Documents", json_schema_extra=_BOOL_ENUM_EXTRA
    )


# ============================================================================
# Operation Configs — Bulk Import
# ============================================================================


class PineconeStartImportConfig(BaseModel):
    """Start an async bulk import of Parquet vectors from S3, GCS, or Azure Blob."""

    operation: Literal["start_import"] = Field(
        "start_import",
        json_schema_extra={
            "const": "start_import", "ui:hidden": True,
            "x-category": "Bulk Import", "x-is-trigger": False,
            "x-display-name": "Start Import",
            "x-keywords": ["bulk import", "parquet", "s3 import", "batch upsert", "large scale"],
        },
        title="Start Import",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    uri: str = Field(
        ..., title="Source URI",
        description="URI of the Parquet file or folder: s3://bucket/path, gs://bucket/path, or https://…",
    )
    error_mode: str = Field(
        "continue", title="On Error",
        description="What to do when a record fails to import",
        json_schema_extra={"enum": ["continue", "abort"], "x-enum-searchable": True},
    )
    integration_id: Optional[str] = Field(
        None, title="Integration ID",
        description="Optional Pinecone storage integration ID for private buckets",
    )


class PineconeListImportsConfig(BaseModel):
    """List all bulk import operations for an index."""

    operation: Literal["list_imports"] = Field(
        "list_imports",
        json_schema_extra={
            "const": "list_imports", "ui:hidden": True,
            "x-category": "Bulk Import", "x-is-trigger": False,
            "x-display-name": "List Imports",
            "x-keywords": ["list bulk imports", "import status", "import jobs"],
        },
        title="List Imports",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    limit: int = Field(20, title="Limit", description="Max results to return (1–100)")
    pagination_token: Optional[str] = Field(None, title="Pagination Token")


class PineconeDescribeImportConfig(BaseModel):
    """Get the status and details of a specific bulk import operation."""

    operation: Literal["describe_import"] = Field(
        "describe_import",
        json_schema_extra={
            "const": "describe_import", "ui:hidden": True,
            "x-category": "Bulk Import", "x-is-trigger": False,
            "x-display-name": "Describe Import",
            "x-keywords": ["import status", "check import", "import details"],
        },
        title="Describe Import",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    import_id: str = Field(..., title="Import ID", description="ID returned by Start Import")


class PineconeCancelImportConfig(BaseModel):
    """Cancel a pending or in-progress bulk import operation."""

    operation: Literal["cancel_import"] = Field(
        "cancel_import",
        json_schema_extra={
            "const": "cancel_import", "ui:hidden": True,
            "x-category": "Bulk Import", "x-is-trigger": False,
            "x-display-name": "Cancel Import",
            "x-keywords": ["cancel bulk import", "stop import", "abort import"],
        },
        title="Cancel Import",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    import_id: str = Field(..., title="Import ID", description="ID of the import to cancel")


# ============================================================================
# Operation Configs — Documents
# ============================================================================


class PineconeUploadIndexConfig(BaseModel):
    """Upload a document file, chunk + embed it with text-embedding-3-small, and upsert."""

    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file", "add pdf"],
        },
        title="Upload & Index Document",
    )
    index: str = Field(..., title="Index", description="Pinecone index to write to",
                       json_schema_extra=_INDEX_FIELD_EXTRA)
    document: str = Field(
        ..., title="Document",
        description="Upload a PDF/DOCX/TXT/MD/CSV file (or paste a URL). It's chunked, embedded with text-embedding-3-small, and upserted.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": DOCUMENT_ACCEPT},
    )
    namespace: Optional[str] = Field(None, title="Namespace")
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap", description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(None, title="ID Prefix",
                                     description="Optional prefix for chunk IDs (defaults to the filename)")


# ============================================================================
# Discriminated Union
# ============================================================================


PineconeConfig = Annotated[
    Union[
        # Vectors
        PineconeQueryConfig,
        PineconeUpsertConfig,
        PineconeFetchConfig,
        PineconeDeleteConfig,
        PineconeUpdateVectorConfig,
        PineconeListVectorsConfig,
        PineconeDescribeIndexStatsConfig,
        # Index management
        PineconeListIndexesConfig,
        PineconeDescribeIndexConfig,
        PineconeCreateIndexConfig,
        PineconeConfigureIndexConfig,
        PineconeDeleteIndexConfig,
        # Integrated inference (text-native)
        PineconeCreateIndexForModelConfig,
        PineconeUpsertRecordsConfig,
        PineconeSearchRecordsConfig,
        # Inference API
        PineconeGenerateEmbeddingsConfig,
        PineconeRerankConfig,
        # Bulk import
        PineconeStartImportConfig,
        PineconeListImportsConfig,
        PineconeDescribeImportConfig,
        PineconeCancelImportConfig,
        # Documents
        PineconeUploadIndexConfig,
    ],
    Discriminator("operation"),
]


class PineconeNodeConfig(NodeConfig[PineconeConfig, PineconeCredential]):
    """Full configuration for the Pinecone node including credentials."""
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


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


# ============================================================================
# Node Implementation
# ============================================================================


class PineconeNode(WorkflowNode):
    """Pinecone vector database automation node."""

    edit_examples = [
        "Search a Pinecone index for the vectors most similar to a query embedding",
        "Upsert document embeddings into a Pinecone index with metadata",
        "Delete all vectors in a namespace before re-indexing",
        "Fetch specific vectors by ID to inspect their metadata",
        "Create a new serverless index for a 1536-dimension embedding model",
        "Generate embeddings with Pinecone's multilingual-e5-large model",
        "Rerank search results against a query using bge-reranker-v2-m3",
        "Bulk-import a Parquet file of vectors from S3 into a Pinecone index",
    ]

    @classmethod
    def get_config_model(cls):
        return PineconeNodeConfig

    @staticmethod
    def _headers(api_key: str) -> Dict[str, str]:
        return {
            "Api-Key": api_key,
            "X-Pinecone-API-Version": PINECONE_API_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "NoClick-Workflow/1.0",
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
        """Populate the index dropdown from the user's Pinecone project."""
        if field_name != "index":
            return []
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{PINECONE_CONTROL_BASE}/indexes", headers=cls._headers(api_key)
                )
        except httpx.HTTPError as e:
            logger.warning(f"[PineconeNode] Failed to list indexes: {e}")
            return []
        if resp.status_code >= 400:
            logger.warning(f"[PineconeNode] List indexes returned {resp.status_code}: {resp.text}")
            return []
        indexes = resp.json().get("indexes", []) or []
        options = []
        for idx in indexes:
            name = idx.get("name")
            if not name:
                continue
            if search and search.lower() not in name.lower():
                continue
            options.append({
                "value": name,
                "label": name,
                "metadata": {"host": idx.get("host"), "dimension": idx.get("dimension")},
            })
        return options

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, PineconeNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Pinecone API key.")

        op_config = config.config
        handlers = {
            "query": self._handle_query,
            "upsert": self._handle_upsert,
            "fetch": self._handle_fetch,
            "delete": self._handle_delete,
            "update_vector": self._handle_update_vector,
            "list_vectors": self._handle_list_vectors,
            "describe_index_stats": self._handle_describe_index_stats,
            "list_indexes": self._handle_list_indexes,
            "describe_index": self._handle_describe_index,
            "create_index": self._handle_create_index,
            "configure_index": self._handle_configure_index,
            "delete_index": self._handle_delete_index,
            "create_index_for_model": self._handle_create_index_for_model,
            "upsert_records": self._handle_upsert_records,
            "search_records": self._handle_search_records,
            "generate_embeddings": self._handle_generate_embeddings,
            "rerank": self._handle_rerank,
            "start_import": self._handle_start_import,
            "list_imports": self._handle_list_imports,
            "describe_import": self._handle_describe_import,
            "cancel_import": self._handle_cancel_import,
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
    # HTTP helpers
    # =========================================================================

    async def _request(
        self,
        method: str,
        url: str,
        api_key: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        content: Optional[bytes] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        start_time = time.time()
        if json_body is not None:
            json_body = {k: v for k, v in json_body.items() if v is not None}
        headers = self._headers(api_key)
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with guarded_async_client(timeout=30.0) as client:
                if content is not None:
                    response = await client.request(
                        method=method, url=url, headers=headers, content=content, params=params
                    )
                else:
                    response = await client.request(
                        method=method, url=url, headers=headers, json=json_body, params=params
                    )
        except httpx.TimeoutException:
            return {
                "status": "error", "action": action_name,
                "error": "Request timed out", "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
            }
        except httpx.HTTPError as e:
            return {
                "status": "error", "action": action_name,
                "error": str(e), "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
            }

        api_time = round((time.time() - start_time) * 1000, 2)
        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_message = error_data.get("message", error_data.get("error", str(error_data)))
            except Exception:
                error_message = response.text
            logger.error(f"[PineconeNode] API error ({action_name}): {error_message}")
            return {
                "status": "error", "action": action_name,
                "error": error_message, "status_code": response.status_code,
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
            "status": "success", "action": action_name,
            "data": data, "status_code": response.status_code,
            "timing_ms": {"api_request": api_time},
        }

    async def _resolve_host(self, index: str, api_key: str) -> str:
        """Resolve an index name to its data-plane host (cached per execution)."""
        cache = getattr(self, "_host_cache", None)
        if cache is None:
            cache = {}
            self._host_cache = cache
        if index in cache:
            return cache[index]
        async with guarded_async_client(timeout=20.0) as client:
            resp = await client.get(
                f"{PINECONE_CONTROL_BASE}/indexes/{index}", headers=self._headers(api_key)
            )
        if resp.status_code >= 400:
            raise ValueError(f"Could not resolve Pinecone index '{index}' (status {resp.status_code})")
        host = resp.json().get("host")
        if not host:
            raise ValueError(f"Pinecone index '{index}' has no host yet (still initializing?)")
        host = _pinecone_data_host(host)
        cache[index] = host
        return host

    async def _data_request(
        self,
        index: str,
        method: str,
        endpoint: str,
        api_key: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        content: Optional[bytes] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        try:
            host = _pinecone_data_host(await self._resolve_host(index, api_key))
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": action_name, "error": str(e), "status_code": 404}
        return await self._request(
            method, f"https://{host}{endpoint}", api_key,
            json_body=json_body, params=params, action_name=action_name,
            content=content, extra_headers=extra_headers,
        )

    # =========================================================================
    # Vector operations
    # =========================================================================

    async def _handle_query(self, config: PineconeQueryConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "topK": config.top_k,
            "includeMetadata": config.include_metadata == "true",
            "includeValues": config.include_values == "true",
        }
        if config.namespace:
            body["namespace"] = config.namespace
        if config.vector:
            vector = _parse_json_list(config.vector)
            if vector is None:
                return {"status": "error", "action": "query",
                        "error": "`vector` must be a JSON array of numbers"}
            body["vector"] = vector
        elif config.id:
            body["id"] = config.id
        else:
            return {"status": "error", "action": "query",
                    "error": "Provide a query vector or a vector ID"}
        metadata_filter = _parse_json_obj(config.filter)
        if metadata_filter:
            body["filter"] = metadata_filter
        return await self._data_request(
            config.index, "POST", "/query", credentials.api_key, json_body=body, action_name="query"
        )

    async def _handle_upsert(self, config: PineconeUpsertConfig, credentials) -> Dict[str, Any]:
        vectors = _parse_json_list(config.vectors)
        if vectors is None:
            return {"status": "error", "action": "upsert",
                    "error": "`vectors` must be a JSON array of {id, values, metadata} objects"}
        body: Dict[str, Any] = {"vectors": vectors}
        if config.namespace:
            body["namespace"] = config.namespace
        return await self._data_request(
            config.index, "POST", "/vectors/upsert", credentials.api_key, json_body=body, action_name="upsert"
        )

    async def _handle_fetch(self, config: PineconeFetchConfig, credentials) -> Dict[str, Any]:
        ids = _split_csv(config.ids)
        if not ids:
            return {"status": "error", "action": "fetch", "error": "Provide at least one vector ID"}
        params: Dict[str, Any] = {"ids": ids}
        if config.namespace:
            params["namespace"] = config.namespace
        return await self._data_request(
            config.index, "GET", "/vectors/fetch", credentials.api_key, params=params, action_name="fetch"
        )

    async def _handle_delete(self, config: PineconeDeleteConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        ids = _split_csv(config.ids)
        if config.delete_all == "true":
            body["deleteAll"] = True
        elif ids:
            body["ids"] = ids
        else:
            metadata_filter = _parse_json_obj(config.filter)
            if not metadata_filter:
                return {"status": "error", "action": "delete",
                        "error": "Specify ids, a metadata filter, or enable Delete All in Namespace"}
            body["filter"] = metadata_filter
        if config.namespace:
            body["namespace"] = config.namespace
        return await self._data_request(
            config.index, "POST", "/vectors/delete", credentials.api_key, json_body=body, action_name="delete"
        )

    async def _handle_update_vector(self, config: PineconeUpdateVectorConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"id": config.id}
        if config.values:
            values = _parse_json_list(config.values)
            if values is None:
                return {"status": "error", "action": "update_vector",
                        "error": "`values` must be a JSON array of numbers"}
            body["values"] = values
        if config.set_metadata:
            metadata = _parse_json_obj(config.set_metadata)
            if metadata is None:
                return {"status": "error", "action": "update_vector",
                        "error": "`set_metadata` must be a JSON object"}
            body["setMetadata"] = metadata
        if not config.values and not config.set_metadata:
            return {"status": "error", "action": "update_vector",
                    "error": "Provide at least one of: values or set_metadata"}
        if config.namespace:
            body["namespace"] = config.namespace
        return await self._data_request(
            config.index, "POST", "/vectors/update", credentials.api_key, json_body=body, action_name="update_vector"
        )

    async def _handle_list_vectors(self, config: PineconeListVectorsConfig, credentials) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": config.limit}
        if config.namespace:
            params["namespace"] = config.namespace
        if config.prefix:
            params["prefix"] = config.prefix
        if config.pagination_token:
            params["paginationToken"] = config.pagination_token
        return await self._data_request(
            config.index, "GET", "/vectors/list", credentials.api_key, params=params, action_name="list_vectors"
        )

    async def _handle_describe_index_stats(self, config: PineconeDescribeIndexStatsConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        metadata_filter = _parse_json_obj(config.filter)
        if metadata_filter:
            body["filter"] = metadata_filter
        return await self._data_request(
            config.index, "POST", "/describe_index_stats", credentials.api_key,
            json_body=body if body else None, action_name="describe_index_stats"
        )

    # =========================================================================
    # Index management (control plane)
    # =========================================================================

    async def _handle_list_indexes(self, config: PineconeListIndexesConfig, credentials) -> Dict[str, Any]:
        return await self._request(
            "GET", f"{PINECONE_CONTROL_BASE}/indexes", credentials.api_key, action_name="list_indexes"
        )

    async def _handle_describe_index(self, config: PineconeDescribeIndexConfig, credentials) -> Dict[str, Any]:
        return await self._request(
            "GET", f"{PINECONE_CONTROL_BASE}/indexes/{config.index}", credentials.api_key,
            action_name="describe_index"
        )

    async def _handle_create_index(self, config: PineconeCreateIndexConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "name": config.name,
            "dimension": config.dimension,
            "metric": config.metric,
            "spec": {"serverless": {"cloud": config.cloud, "region": config.region}},
        }
        if config.deletion_protection != "disabled":
            body["deletion_protection"] = config.deletion_protection
        return await self._request(
            "POST", f"{PINECONE_CONTROL_BASE}/indexes", credentials.api_key,
            json_body=body, action_name="create_index"
        )

    async def _handle_configure_index(self, config: PineconeConfigureIndexConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if config.deletion_protection is not None:
            body["deletion_protection"] = config.deletion_protection
        if config.replicas is not None or config.pod_type is not None:
            spec_pod: Dict[str, Any] = {}
            if config.replicas is not None:
                spec_pod["replicas"] = config.replicas
            if config.pod_type is not None:
                spec_pod["pod_type"] = config.pod_type
            body["spec"] = {"pod": spec_pod}
        if not body:
            return {"status": "error", "action": "configure_index",
                    "error": "Provide at least one setting to change: deletion_protection, replicas, or pod_type"}
        return await self._request(
            "PATCH", f"{PINECONE_CONTROL_BASE}/indexes/{config.index}", credentials.api_key,
            json_body=body, action_name="configure_index"
        )

    async def _handle_delete_index(self, config: PineconeDeleteIndexConfig, credentials) -> Dict[str, Any]:
        return await self._request(
            "DELETE", f"{PINECONE_CONTROL_BASE}/indexes/{config.index}", credentials.api_key,
            action_name="delete_index"
        )

    # =========================================================================
    # Integrated inference (text-native indexes)
    # =========================================================================

    async def _handle_create_index_for_model(self, config: PineconeCreateIndexForModelConfig, credentials) -> Dict[str, Any]:
        body = {
            "name": config.name,
            "cloud": config.cloud,
            "region": config.region,
            "embed": {
                "model": config.embed_model,
                "field_map": {"text": config.field_map_text},
            },
        }
        return await self._request(
            "POST", f"{PINECONE_CONTROL_BASE}/indexes/create-for-model", credentials.api_key,
            json_body=body, action_name="create_index_for_model"
        )

    async def _handle_upsert_records(self, config: PineconeUpsertRecordsConfig, credentials) -> Dict[str, Any]:
        records = _parse_json_list(config.records)
        if records is None:
            return {"status": "error", "action": "upsert_records",
                    "error": "`records` must be a JSON array of objects"}
        # Text-native upsert uses ndjson (one JSON object per line)
        ndjson_body = "\n".join(json.dumps(r) for r in records).encode()
        return await self._data_request(
            config.index, "POST", f"/records/namespaces/{config.namespace}/upsert",
            credentials.api_key, content=ndjson_body,
            extra_headers={"Content-Type": "application/x-ndjson"},
            action_name="upsert_records",
        )

    async def _handle_search_records(self, config: PineconeSearchRecordsConfig, credentials) -> Dict[str, Any]:
        inputs: Dict[str, Any] = {"text": config.query_text}
        body: Dict[str, Any] = {"query": {"inputs": inputs, "top_k": config.top_k}}
        metadata_filter = _parse_json_obj(config.filter)
        if metadata_filter:
            body["query"]["filter"] = metadata_filter
        if config.rerank_model:
            rerank: Dict[str, Any] = {"model": config.rerank_model, "query": config.query_text}
            if config.rerank_top_n:
                rerank["top_n"] = config.rerank_top_n
            body["rerank"] = rerank
        return await self._data_request(
            config.index, "POST", f"/records/namespaces/{config.namespace}/search",
            credentials.api_key, json_body=body, action_name="search_records"
        )

    # =========================================================================
    # Inference API (standalone)
    # =========================================================================

    async def _handle_generate_embeddings(self, config: PineconeGenerateEmbeddingsConfig, credentials) -> Dict[str, Any]:
        inputs_list = _parse_json_list(config.inputs)
        if inputs_list is None:
            return {"status": "error", "action": "generate_embeddings",
                    "error": "`inputs` must be a JSON array of strings"}
        body: Dict[str, Any] = {
            "model": config.model,
            "inputs": [{"text": t} if isinstance(t, str) else t for t in inputs_list],
            "parameters": {"truncate": config.truncate},
        }
        if config.input_type:
            body["parameters"]["input_type"] = config.input_type
        return await self._request(
            "POST", f"{PINECONE_CONTROL_BASE}/embed", credentials.api_key,
            json_body=body, action_name="generate_embeddings"
        )

    async def _handle_rerank(self, config: PineconeRerankConfig, credentials) -> Dict[str, Any]:
        docs_raw = _parse_json_list(config.documents)
        if docs_raw is None:
            return {"status": "error", "action": "rerank",
                    "error": "`documents` must be a JSON array of strings or objects"}
        # Pinecone rerank expects objects with a text field if strings are passed
        documents = [{"text": d} if isinstance(d, str) else d for d in docs_raw]
        body: Dict[str, Any] = {
            "model": config.model,
            "query": config.query,
            "documents": documents,
            "return_documents": config.return_documents == "true",
        }
        if config.top_n:
            body["top_n"] = config.top_n
        if config.rank_fields:
            body["rank_fields"] = _split_csv(config.rank_fields)
        return await self._request(
            "POST", f"{PINECONE_CONTROL_BASE}/rerank", credentials.api_key,
            json_body=body, action_name="rerank"
        )

    # =========================================================================
    # Bulk import
    # =========================================================================

    async def _handle_start_import(self, config: PineconeStartImportConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"uri": config.uri, "errorMode": {"onError": config.error_mode}}
        if config.integration_id:
            body["integrationId"] = config.integration_id
        return await self._data_request(
            config.index, "POST", "/bulk/imports", credentials.api_key,
            json_body=body, action_name="start_import"
        )

    async def _handle_list_imports(self, config: PineconeListImportsConfig, credentials) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": config.limit}
        if config.pagination_token:
            params["paginationToken"] = config.pagination_token
        return await self._data_request(
            config.index, "GET", "/bulk/imports", credentials.api_key,
            params=params, action_name="list_imports"
        )

    async def _handle_describe_import(self, config: PineconeDescribeImportConfig, credentials) -> Dict[str, Any]:
        return await self._data_request(
            config.index, "GET", f"/bulk/imports/{config.import_id}", credentials.api_key,
            action_name="describe_import"
        )

    async def _handle_cancel_import(self, config: PineconeCancelImportConfig, credentials) -> Dict[str, Any]:
        return await self._data_request(
            config.index, "DELETE", f"/bulk/imports/{config.import_id}", credentials.api_key,
            action_name="cancel_import"
        )

    # =========================================================================
    # Documents
    # =========================================================================

    async def _handle_upload_and_index(self, config: PineconeUploadIndexConfig, credentials) -> Dict[str, Any]:
        records, info = await ingest_document(
            self, config.document, chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap, id_prefix=config.id_prefix
        )
        if not records:
            return {"status": "error", "action": "upload_and_index",
                    "error": "No text could be extracted from the document"}
        body: Dict[str, Any] = {
            "vectors": [{"id": r["id"], "values": r["values"], "metadata": r["metadata"]} for r in records]
        }
        if config.namespace:
            body["namespace"] = config.namespace
        result = await self._data_request(
            config.index, "POST", "/vectors/upsert", credentials.api_key,
            json_body=body, action_name="upload_and_index"
        )
        if result.get("status") == "success":
            result["data"] = {**(result.get("data") or {}),
                              "chunks_indexed": len(records), "source": info.get("filename")}
        return result
