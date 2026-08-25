"""
Chroma vector database automation node.

Provides complete workflow integration with Chroma (Chroma Cloud or self-hosted):
- Records: query, search, add, upsert, update, get, delete, count
- Collection management: list, create, get (by name/id/crn), update, delete,
  count, fork, fork_count, indexing_status
- Attached functions: attach, get, add_input, detach
- Tenant management: get, create, update
- Database management: list, create, get, delete
- Utility: healthcheck, heartbeat, version, reset, get_user_identity
- Document upload: chunk + embed + add pipeline

Authentication: x-chroma-token header (Chroma Cloud / default) or HTTP Basic
auth (self-hosted deployments with CHROMA_SERVER_AUTHN_PROVIDER=basic).
Tenant + database + base URL live on the credential.
Docs: https://docs.trychroma.com/

Uses the v2 REST API. Record endpoints require the collection UUID; the node
resolves a collection NAME to its id via a direct GET and caches it per
execution. Records use Chroma's parallel-array shape (ids / embeddings /
documents / metadatas).
"""

import base64
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

CHROMA_CLOUD_BASE = "https://api.trychroma.com"

_COLLECTION_FIELD_EXTRA = {
    "x-resource-type": "chroma_collection",
    "x-dynamic-options": {
        "field_name": "collection",
        "placeholder": "Select a collection...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type the collection name",
    }
}

# ============================================================================
# Credential Schema
# ============================================================================


class ChromaCredential(BaseModel):
    """Token or Basic-auth credential for Chroma."""

    credential_type: Literal["chroma_token"] = Field(
        "chroma_token", json_schema_extra={"ui:hidden": True}
    )
    auth_type: str = Field(
        "token",
        title="Auth Method",
        description="Token auth (Chroma Cloud / default) or Basic auth (self-hosted with password auth enabled).",
        json_schema_extra={
            "enum": ["token", "basic"],
            "enumNames": ["Token (x-chroma-token)", "Basic (username + password)"],
            "x-enum-searchable": True,
        },
    )
    api_key: Optional[str] = Field(
        None,
        title="API Token",
        description="Chroma token — sent as x-chroma-token. Required when Auth Method is Token.",
        json_schema_extra={"ui:widget": "password"},
    )
    username: Optional[str] = Field(
        None,
        title="Username",
        description="Basic auth username. Required when Auth Method is Basic.",
    )
    password: Optional[str] = Field(
        None,
        title="Password",
        description="Basic auth password. Required when Auth Method is Basic.",
        json_schema_extra={"ui:widget": "password"},
    )
    tenant: str = Field(..., title="Tenant", description="Chroma tenant (id or 'default_tenant')")
    database: str = Field(..., title="Database", description="Chroma database name (or 'default_database')")
    base_url: Optional[str] = Field(
        None,
        title="Base URL",
        description="Override for self-hosted Chroma. Defaults to Chroma Cloud (https://api.trychroma.com).",
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://trychroma.com/"}
    )


# ============================================================================
# Operation Configs — Records
# ============================================================================


class ChromaQueryConfig(BaseModel):
    """Similarity search by a query embedding vector."""

    operation: Literal["query"] = Field(
        "query",
        json_schema_extra={
            "const": "query",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Query (Vector)",
            "x-keywords": ["similarity search", "nearest neighbors", "vector search", "rag", "knn"],
        },
        title="Query (Vector)",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    vector: str = Field(
        ...,
        title="Query Vector",
        description="Embedding to search with — a JSON array of numbers",
        json_schema_extra={"ui:widget": "textarea"},
    )
    n_results: int = Field(10, title="N Results", description="Number of matches to return")
    where: Optional[str] = Field(
        None, title="Where", description='Optional JSON metadata filter, e.g. {"source": "doc1"}'
    )
    where_document: Optional[str] = Field(
        None,
        title="Where Document",
        description='Filter by document text content, e.g. {"$contains": "keyword"} or {"$not_contains": "word"}',
    )
    include: Optional[str] = Field(
        None,
        title="Include Fields",
        description='JSON array of fields to return. Default: ["distances","documents","metadatas"]. '
                    'Options: distances, documents, embeddings, metadatas, uris.',
    )


class ChromaSearchConfig(BaseModel):
    """Full-text / semantic search using query text — Chroma embeds it server-side via an attached function."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Search (Text)",
            "x-keywords": ["text search", "semantic search", "rag", "similarity", "find", "natural language", "no vector"],
        },
        title="Search (Text)",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    query_text: str = Field(
        ...,
        title="Query Text",
        description="Natural language query — Chroma embeds it server-side using the collection's attached function",
    )
    n_results: int = Field(10, title="N Results", description="Number of results to return")
    where: Optional[str] = Field(None, title="Where", description="Optional JSON metadata filter")
    where_document: Optional[str] = Field(
        None, title="Where Document", description='Filter by document text, e.g. {"$contains": "keyword"}'
    )
    include: Optional[str] = Field(
        None,
        title="Include Fields",
        description='JSON array of fields. Default: ["distances","documents","metadatas"]',
    )


class ChromaAddConfig(BaseModel):
    """Add records to a collection (fails if IDs already exist; use Upsert for insert-or-update)."""

    operation: Literal["add"] = Field(
        "add",
        json_schema_extra={
            "const": "add",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Add Records",
            "x-keywords": ["insert", "index", "store", "embed"],
        },
        title="Add Records",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    ids: str = Field(..., title="IDs", description="Record IDs, comma-separated")
    embeddings: str = Field(
        ...,
        title="Embeddings",
        description="JSON array of embedding vectors, one per ID: [[0.1, ...], [0.2, ...]]",
        json_schema_extra={"ui:widget": "textarea"},
    )
    documents: Optional[str] = Field(
        None,
        title="Documents",
        description="Optional JSON array of document texts, one per ID",
        json_schema_extra={"ui:widget": "textarea"},
    )
    metadatas: Optional[str] = Field(
        None,
        title="Metadatas",
        description="Optional JSON array of metadata objects, one per ID",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ChromaUpsertConfig(BaseModel):
    """Upsert records — inserts new IDs and updates existing ones (idempotent sync)."""

    operation: Literal["upsert"] = Field(
        "upsert",
        json_schema_extra={
            "const": "upsert",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Upsert Records",
            "x-keywords": ["insert or update", "sync", "idempotent", "overwrite", "reindex"],
        },
        title="Upsert Records",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    ids: str = Field(..., title="IDs", description="Record IDs, comma-separated")
    embeddings: str = Field(
        ...,
        title="Embeddings",
        description="JSON array of embedding vectors, one per ID: [[0.1, ...], [0.2, ...]]",
        json_schema_extra={"ui:widget": "textarea"},
    )
    documents: Optional[str] = Field(
        None,
        title="Documents",
        description="Optional JSON array of document texts, one per ID",
        json_schema_extra={"ui:widget": "textarea"},
    )
    metadatas: Optional[str] = Field(
        None,
        title="Metadatas",
        description="Optional JSON array of metadata objects, one per ID",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ChromaUpdateConfig(BaseModel):
    """Update existing records by ID (fails if an ID does not exist; use Upsert otherwise)."""

    operation: Literal["update"] = Field(
        "update",
        json_schema_extra={
            "const": "update",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Update Records",
            "x-keywords": ["edit", "patch", "modify", "change"],
        },
        title="Update Records",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    ids: str = Field(..., title="IDs", description="IDs of records to update, comma-separated")
    embeddings: Optional[str] = Field(
        None,
        title="Embeddings",
        description="New embedding vectors (JSON array), one per ID",
        json_schema_extra={"ui:widget": "textarea"},
    )
    documents: Optional[str] = Field(
        None,
        title="Documents",
        description="New document texts (JSON array), one per ID",
        json_schema_extra={"ui:widget": "textarea"},
    )
    metadatas: Optional[str] = Field(
        None,
        title="Metadatas",
        description="New metadata objects (JSON array), one per ID",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ChromaGetConfig(BaseModel):
    """Get records by ID or filter."""

    operation: Literal["get"] = Field(
        "get",
        json_schema_extra={
            "const": "get",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Get Records",
            "x-keywords": ["fetch", "lookup", "read"],
        },
        title="Get Records",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    ids: Optional[str] = Field(None, title="IDs", description="Record IDs to retrieve, comma-separated")
    where: Optional[str] = Field(None, title="Where", description="Optional JSON metadata filter")
    where_document: Optional[str] = Field(
        None,
        title="Where Document",
        description='Filter by document text content, e.g. {"$contains": "keyword"}',
    )
    limit: Optional[int] = Field(None, title="Limit", description="Max records to return")
    offset: Optional[int] = Field(None, title="Offset", description="Number of records to skip (pagination)")
    include: Optional[str] = Field(
        None,
        title="Include Fields",
        description='JSON array of fields to return. Default: ["documents","metadatas"]. '
                    'Options: documents, embeddings, metadatas, uris.',
    )


class ChromaCountConfig(BaseModel):
    """Count the number of records in a collection."""

    operation: Literal["count"] = Field(
        "count",
        json_schema_extra={
            "const": "count",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Count Records",
            "x-keywords": ["count", "size", "total", "how many"],
        },
        title="Count Records",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class ChromaDeleteConfig(BaseModel):
    """Delete records by ID, metadata filter, or document content filter."""

    operation: Literal["delete"] = Field(
        "delete",
        json_schema_extra={
            "const": "delete",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Delete Records",
            "x-keywords": ["remove", "purge", "clear"],
        },
        title="Delete Records",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    ids: Optional[str] = Field(None, title="IDs", description="Record IDs to delete, comma-separated")
    where: Optional[str] = Field(None, title="Where", description="Delete records matching a JSON metadata filter")
    where_document: Optional[str] = Field(
        None,
        title="Where Document",
        description='Delete records whose document text matches, e.g. {"$contains": "keyword"}',
    )


class ChromaUploadIndexConfig(BaseModel):
    """Upload a document file, chunk + embed it, and add the records."""

    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file", "add pdf"],
        },
        title="Upload & Index Document",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    document: str = Field(
        ...,
        title="Document",
        description="Upload a PDF/DOCX/TXT/MD/CSV file (or paste a URL / reference an upstream file). "
                    "It's chunked, embedded with text-embedding-3-small, and added as records.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": DOCUMENT_ACCEPT},
    )
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap", description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(
        None, title="ID Prefix", description="Optional prefix for chunk IDs (defaults to the filename)"
    )


# ============================================================================
# Operation Configs — Collection management
# ============================================================================


class ChromaListCollectionsConfig(BaseModel):
    """List collections in the tenant/database."""

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
    limit: Optional[int] = Field(None, title="Limit", description="Max collections to return")
    offset: Optional[int] = Field(None, title="Offset", description="Collections to skip for pagination")


class ChromaGetCollectionConfig(BaseModel):
    """Get a collection's metadata and configuration by name."""

    operation: Literal["get_collection"] = Field(
        "get_collection",
        json_schema_extra={
            "const": "get_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Get Collection",
            "x-keywords": ["describe collection", "collection info", "collection details", "inspect"],
        },
        title="Get Collection",
    )
    collection: str = Field(..., title="Collection Name", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class ChromaCreateCollectionConfig(BaseModel):
    """Create a collection."""

    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection",
            "x-creates-resource": True,
            "x-resource-type": "chroma_collection",
            "x-resource-id-path": "data.name",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Create Collection",
            "x-keywords": ["new collection", "provision", "setup"],
        },
        title="Create Collection",
    )
    name: str = Field(..., title="Name", description="Collection name")
    get_or_create: str = Field(
        "true",
        title="Get or Create",
        description="Return the existing collection if it already exists instead of raising an error",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    distance_metric: Optional[str] = Field(
        None,
        title="Distance Metric",
        description="Embedding distance function used for similarity queries (self-hosted; Chroma Cloud uses the collection's attached function)",
        json_schema_extra={
            "enum": ["", "l2", "cosine", "ip"],
            "enumNames": ["Default (l2)", "L2 (Euclidean)", "Cosine", "Inner Product (ip)"],
            "x-enum-searchable": True,
        },
    )
    metadata: Optional[str] = Field(
        None,
        title="Metadata",
        description="Optional JSON metadata object to attach to the collection",
    )


class ChromaUpdateCollectionConfig(BaseModel):
    """Rename a collection or replace its metadata."""

    operation: Literal["update_collection"] = Field(
        "update_collection",
        json_schema_extra={
            "const": "update_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Update Collection",
            "x-keywords": ["rename collection", "update metadata", "edit collection"],
        },
        title="Update Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    new_name: Optional[str] = Field(None, title="New Name", description="Rename the collection")
    metadata: Optional[str] = Field(
        None,
        title="New Metadata",
        description="Replacement JSON metadata for the collection (replaces existing metadata entirely)",
    )


class ChromaDeleteCollectionConfig(BaseModel):
    """Permanently delete a collection and all its records."""

    operation: Literal["delete_collection"] = Field(
        "delete_collection",
        json_schema_extra={
            "const": "delete_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Delete Collection",
            "x-keywords": ["drop collection", "remove collection", "destroy"],
        },
        title="Delete Collection",
    )
    collection: str = Field(..., title="Collection Name", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class ChromaCountCollectionsConfig(BaseModel):
    """Count the total number of collections in the database."""

    operation: Literal["count_collections"] = Field(
        "count_collections",
        json_schema_extra={
            "const": "count_collections",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Count Collections",
            "x-keywords": ["collection count", "how many collections", "total collections"],
        },
        title="Count Collections",
    )


class ChromaIndexingStatusConfig(BaseModel):
    """Get the indexing status of a collection (records indexed vs pending)."""

    operation: Literal["indexing_status"] = Field(
        "indexing_status",
        json_schema_extra={
            "const": "indexing_status",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Indexing Status",
            "x-keywords": ["index progress", "indexing", "background", "pending"],
        },
        title="Indexing Status",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class ChromaForkCollectionConfig(BaseModel):
    """Fork (copy) an existing collection into a new one."""

    operation: Literal["fork_collection"] = Field(
        "fork_collection",
        json_schema_extra={
            "const": "fork_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Fork Collection",
            "x-keywords": ["copy collection", "duplicate", "snapshot", "clone"],
        },
        title="Fork Collection",
    )
    collection: str = Field(..., title="Source Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    new_name: str = Field(..., title="New Name", description="Name for the forked collection")
    destination_database: Optional[str] = Field(
        None,
        title="Destination Database",
        description="Database for the fork (defaults to the same database as the source)",
    )


class ChromaForkCountConfig(BaseModel):
    """Get the number of times a collection has been forked."""

    operation: Literal["fork_count"] = Field(
        "fork_count",
        json_schema_extra={
            "const": "fork_count",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Fork Count",
            "x-keywords": ["fork count", "how many forks", "copies"],
        },
        title="Fork Count",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class ChromaGetCollectionByIdConfig(BaseModel):
    """Get a collection's metadata by its UUID."""

    operation: Literal["get_collection_by_id"] = Field(
        "get_collection_by_id",
        json_schema_extra={
            "const": "get_collection_by_id",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Get Collection by ID",
            "x-keywords": ["collection by uuid", "lookup by id", "find collection uuid"],
        },
        title="Get Collection by ID",
    )
    collection_id: str = Field(..., title="Collection UUID", description="The collection's UUID")


class ChromaGetCollectionByCrnConfig(BaseModel):
    """Get a collection by its Cloud Resource Name (CRN)."""

    operation: Literal["get_collection_by_crn"] = Field(
        "get_collection_by_crn",
        json_schema_extra={
            "const": "get_collection_by_crn",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Get Collection by CRN",
            "x-keywords": ["crn", "cloud resource name", "collection identifier"],
        },
        title="Get Collection by CRN",
    )
    crn: str = Field(..., title="CRN", description="Cloud Resource Name of the collection")


# ============================================================================
# Operation Configs — Attached Functions
# ============================================================================


class ChromaAttachFunctionConfig(BaseModel):
    """Attach an embedding or processing function to a collection."""

    operation: Literal["attach_function"] = Field(
        "attach_function",
        json_schema_extra={
            "const": "attach_function",
            "ui:hidden": True,
            "x-category": "Functions",
            "x-is-trigger": False,
            "x-display-name": "Attach Function",
            "x-keywords": ["embedding function", "attach model", "server-side embedding", "function"],
        },
        title="Attach Function",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    function_name: str = Field(
        ..., title="Function Name", description="Name of the function to attach (e.g. 'openai')"
    )
    function_config: Optional[str] = Field(
        None,
        title="Function Config",
        description="Optional JSON configuration for the function",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ChromaGetAttachedFunctionConfig(BaseModel):
    """Get details about a function attached to a collection."""

    operation: Literal["get_attached_function"] = Field(
        "get_attached_function",
        json_schema_extra={
            "const": "get_attached_function",
            "ui:hidden": True,
            "x-category": "Functions",
            "x-is-trigger": False,
            "x-display-name": "Get Attached Function",
            "x-keywords": ["embedding function details", "attached model", "function info"],
        },
        title="Get Attached Function",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    function_name: str = Field(..., title="Function Name", description="Name of the attached function")


class ChromaAddAttachedFunctionInputConfig(BaseModel):
    """Add input data to an attached function (e.g. provide documents to embed)."""

    operation: Literal["add_attached_function_input"] = Field(
        "add_attached_function_input",
        json_schema_extra={
            "const": "add_attached_function_input",
            "ui:hidden": True,
            "x-category": "Functions",
            "x-is-trigger": False,
            "x-display-name": "Add Function Input",
            "x-keywords": ["function input", "add embedding input", "feed data to function"],
        },
        title="Add Function Input",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    function_name: str = Field(..., title="Function Name", description="Name of the attached function")
    input: str = Field(
        ...,
        title="Input",
        description="JSON object to send as input to the function",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ChromaDetachFunctionConfig(BaseModel):
    """Detach (remove) a function from a collection."""

    operation: Literal["detach_function"] = Field(
        "detach_function",
        json_schema_extra={
            "const": "detach_function",
            "ui:hidden": True,
            "x-category": "Functions",
            "x-is-trigger": False,
            "x-display-name": "Detach Function",
            "x-keywords": ["remove function", "unattach", "detach model"],
        },
        title="Detach Function",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    function_name: str = Field(..., title="Function Name", description="Name of the function to detach")


# ============================================================================
# Operation Configs — Tenant Management
# ============================================================================


class ChromaGetTenantConfig(BaseModel):
    """Get metadata about a tenant."""

    operation: Literal["get_tenant"] = Field(
        "get_tenant",
        json_schema_extra={
            "const": "get_tenant",
            "ui:hidden": True,
            "x-category": "Tenant",
            "x-is-trigger": False,
            "x-display-name": "Get Tenant",
            "x-keywords": ["tenant info", "tenant details", "describe tenant"],
        },
        title="Get Tenant",
    )
    tenant_name: Optional[str] = Field(
        None,
        title="Tenant Name",
        description="Tenant to fetch (defaults to the tenant on the credential)",
    )


class ChromaCreateTenantConfig(BaseModel):
    """Create a new tenant."""

    operation: Literal["create_tenant"] = Field(
        "create_tenant",
        json_schema_extra={
            "const": "create_tenant",
            "ui:hidden": True,
            "x-category": "Tenant",
            "x-is-trigger": False,
            "x-display-name": "Create Tenant",
            "x-keywords": ["new tenant", "provision tenant", "create workspace"],
        },
        title="Create Tenant",
    )
    tenant_name: str = Field(..., title="Tenant Name", description="Name for the new tenant")


class ChromaUpdateTenantConfig(BaseModel):
    """Update a tenant's configuration."""

    operation: Literal["update_tenant"] = Field(
        "update_tenant",
        json_schema_extra={
            "const": "update_tenant",
            "ui:hidden": True,
            "x-category": "Tenant",
            "x-is-trigger": False,
            "x-display-name": "Update Tenant",
            "x-keywords": ["edit tenant", "modify tenant", "tenant config"],
        },
        title="Update Tenant",
    )
    tenant_name: Optional[str] = Field(
        None,
        title="Tenant Name",
        description="Tenant to update (defaults to the tenant on the credential)",
    )
    config: Optional[str] = Field(
        None,
        title="Config",
        description="Optional JSON config update for the tenant",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Database Management
# ============================================================================


class ChromaListDatabasesConfig(BaseModel):
    """List all databases in the tenant."""

    operation: Literal["list_databases"] = Field(
        "list_databases",
        json_schema_extra={
            "const": "list_databases",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "List Databases",
            "x-keywords": ["show databases", "list dbs", "all databases"],
        },
        title="List Databases",
    )


class ChromaCreateDatabaseConfig(BaseModel):
    """Create a new database in the tenant."""

    operation: Literal["create_database"] = Field(
        "create_database",
        json_schema_extra={
            "const": "create_database",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "Create Database",
            "x-keywords": ["new database", "provision database", "add db"],
        },
        title="Create Database",
    )
    database_name: str = Field(..., title="Database Name", description="Name for the new database")


class ChromaGetDatabaseConfig(BaseModel):
    """Get metadata about a database."""

    operation: Literal["get_database"] = Field(
        "get_database",
        json_schema_extra={
            "const": "get_database",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "Get Database",
            "x-keywords": ["database info", "describe database", "db details"],
        },
        title="Get Database",
    )
    database_name: Optional[str] = Field(
        None,
        title="Database Name",
        description="Database to fetch (defaults to the database on the credential)",
    )


class ChromaDeleteDatabaseConfig(BaseModel):
    """Delete a database and ALL its collections. DESTRUCTIVE."""

    operation: Literal["delete_database"] = Field(
        "delete_database",
        json_schema_extra={
            "const": "delete_database",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "Delete Database",
            "x-keywords": ["drop database", "remove database", "destroy db"],
        },
        title="Delete Database",
    )
    database_name: Optional[str] = Field(
        None,
        title="Database Name",
        description="Database to delete (defaults to the database on the credential). DESTRUCTIVE — permanently removes all collections and records.",
    )


# ============================================================================
# Operation Configs — Utility
# ============================================================================


class ChromaHealthcheckConfig(BaseModel):
    """Check whether the Chroma server is healthy."""

    operation: Literal["healthcheck"] = Field(
        "healthcheck",
        json_schema_extra={
            "const": "healthcheck",
            "ui:hidden": True,
            "x-category": "Utility",
            "x-is-trigger": False,
            "x-display-name": "Healthcheck",
            "x-keywords": ["health", "ping", "status", "is alive"],
        },
        title="Healthcheck",
    )


class ChromaHeartbeatConfig(BaseModel):
    """Get the server heartbeat (nanosecond timestamp)."""

    operation: Literal["heartbeat"] = Field(
        "heartbeat",
        json_schema_extra={
            "const": "heartbeat",
            "ui:hidden": True,
            "x-category": "Utility",
            "x-is-trigger": False,
            "x-display-name": "Heartbeat",
            "x-keywords": ["heartbeat", "ping", "latency", "timestamp"],
        },
        title="Heartbeat",
    )


class ChromaVersionConfig(BaseModel):
    """Get the Chroma server version string."""

    operation: Literal["version"] = Field(
        "version",
        json_schema_extra={
            "const": "version",
            "ui:hidden": True,
            "x-category": "Utility",
            "x-is-trigger": False,
            "x-display-name": "Get Version",
            "x-keywords": ["version", "server version", "chroma version"],
        },
        title="Get Version",
    )


class ChromaResetConfig(BaseModel):
    """Reset the Chroma server. DESTRUCTIVE — wipes ALL data across all tenants and databases."""

    operation: Literal["reset"] = Field(
        "reset",
        json_schema_extra={
            "const": "reset",
            "ui:hidden": True,
            "x-category": "Utility",
            "x-is-trigger": False,
            "x-display-name": "Reset Server",
            "x-keywords": ["reset", "wipe", "clear all", "factory reset"],
        },
        title="Reset Server",
    )


class ChromaGetUserIdentityConfig(BaseModel):
    """Get the identity of the currently authenticated user."""

    operation: Literal["get_user_identity"] = Field(
        "get_user_identity",
        json_schema_extra={
            "const": "get_user_identity",
            "ui:hidden": True,
            "x-category": "Utility",
            "x-is-trigger": False,
            "x-display-name": "Get User Identity",
            "x-keywords": ["identity", "who am i", "current user", "auth info"],
        },
        title="Get User Identity",
    )


# ============================================================================
# Discriminated Union (36 operations — full API coverage)
# ============================================================================


ChromaConfig = Annotated[
    Union[
        # Records
        ChromaQueryConfig,
        ChromaSearchConfig,
        ChromaAddConfig,
        ChromaUpsertConfig,
        ChromaUpdateConfig,
        ChromaGetConfig,
        ChromaCountConfig,
        ChromaDeleteConfig,
        ChromaUploadIndexConfig,
        # Collection management
        ChromaListCollectionsConfig,
        ChromaGetCollectionConfig,
        ChromaCreateCollectionConfig,
        ChromaUpdateCollectionConfig,
        ChromaDeleteCollectionConfig,
        ChromaCountCollectionsConfig,
        ChromaIndexingStatusConfig,
        ChromaForkCollectionConfig,
        ChromaForkCountConfig,
        ChromaGetCollectionByIdConfig,
        ChromaGetCollectionByCrnConfig,
        # Attached functions
        ChromaAttachFunctionConfig,
        ChromaGetAttachedFunctionConfig,
        ChromaAddAttachedFunctionInputConfig,
        ChromaDetachFunctionConfig,
        # Tenant management
        ChromaGetTenantConfig,
        ChromaCreateTenantConfig,
        ChromaUpdateTenantConfig,
        # Database management
        ChromaListDatabasesConfig,
        ChromaCreateDatabaseConfig,
        ChromaGetDatabaseConfig,
        ChromaDeleteDatabaseConfig,
        # Utility
        ChromaHealthcheckConfig,
        ChromaHeartbeatConfig,
        ChromaVersionConfig,
        ChromaResetConfig,
        ChromaGetUserIdentityConfig,
    ],
    Discriminator("operation"),
]


class ChromaNodeConfig(NodeConfig[ChromaConfig, ChromaCredential]):
    """Full configuration for the Chroma node including credentials."""

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


class ChromaNode(WorkflowNode):
    """Chroma vector database automation node."""

    edit_examples = [
        "Search a Chroma collection for the records most similar to a query embedding",
        "Add document embeddings with metadata to a Chroma collection",
        "Upsert records into Chroma (insert new, update existing)",
        "Count the number of records in a Chroma collection",
        "Delete a Chroma collection",
        "Fork a Chroma collection to create a snapshot",
        "Check the indexing status of a collection",
    ]

    @classmethod
    def get_config_model(cls):
        return ChromaNodeConfig

    @staticmethod
    def _base_url(credential: ChromaCredential) -> str:
        return (credential.base_url or CHROMA_CLOUD_BASE).rstrip("/")

    @staticmethod
    def _headers(credential: ChromaCredential) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "NoClick-Workflow/1.0",
        }
        if credential.auth_type == "basic":
            raw = f"{credential.username or ''}:{credential.password or ''}"
            encoded = base64.b64encode(raw.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        else:
            headers["x-chroma-token"] = credential.api_key or ""
        return headers

    @classmethod
    def _collections_base(cls, credential: ChromaCredential) -> str:
        return (
            f"{cls._base_url(credential)}/api/v2/tenants/{credential.tenant}"
            f"/databases/{credential.database}/collections"
        )

    @classmethod
    def _tenant_base(cls, credential: ChromaCredential) -> str:
        return f"{cls._base_url(credential)}/api/v2/tenants"

    @classmethod
    def _db_base(cls, credential: ChromaCredential, tenant: Optional[str] = None) -> str:
        t = tenant or credential.tenant
        return f"{cls._base_url(credential)}/api/v2/tenants/{t}/databases"

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Populate the collection dropdown."""
        if field_name != "collection":
            return []
        try:
            credential = ChromaCredential(**credential_data)
        except Exception:
            return []
        try:
            async with guarded_async_client(timeout=20.0) as client:
                resp = await client.get(
                    cls._collections_base(credential), headers=cls._headers(credential)
                )
        except httpx.HTTPError as e:
            logger.warning(f"[ChromaNode] Failed to list collections: {e}")
            return []
        if resp.status_code >= 400:
            logger.warning(f"[ChromaNode] List collections returned {resp.status_code}: {resp.text}")
            return []
        collections = resp.json() or []
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
        if not config or not isinstance(config, ChromaNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Chroma token, tenant, and database.")

        op_config = config.config
        handlers = {
            # Records
            "query": self._handle_query,
            "search": self._handle_search,
            "add": self._handle_add,
            "upsert": self._handle_upsert,
            "update": self._handle_update,
            "get": self._handle_get,
            "count": self._handle_count,
            "delete": self._handle_delete,
            "upload_and_index": self._handle_upload_and_index,
            # Collection management
            "list_collections": self._handle_list_collections,
            "get_collection": self._handle_get_collection,
            "create_collection": self._handle_create_collection,
            "update_collection": self._handle_update_collection,
            "delete_collection": self._handle_delete_collection,
            "count_collections": self._handle_count_collections,
            "indexing_status": self._handle_indexing_status,
            "fork_collection": self._handle_fork_collection,
            "fork_count": self._handle_fork_count,
            "get_collection_by_id": self._handle_get_collection_by_id,
            "get_collection_by_crn": self._handle_get_collection_by_crn,
            # Attached functions
            "attach_function": self._handle_attach_function,
            "get_attached_function": self._handle_get_attached_function,
            "add_attached_function_input": self._handle_add_attached_function_input,
            "detach_function": self._handle_detach_function,
            # Tenant management
            "get_tenant": self._handle_get_tenant,
            "create_tenant": self._handle_create_tenant,
            "update_tenant": self._handle_update_tenant,
            # Database management
            "list_databases": self._handle_list_databases,
            "create_database": self._handle_create_database,
            "get_database": self._handle_get_database,
            "delete_database": self._handle_delete_database,
            # Utility
            "healthcheck": self._handle_healthcheck,
            "heartbeat": self._handle_heartbeat,
            "version": self._handle_version,
            "reset": self._handle_reset,
            "get_user_identity": self._handle_get_user_identity,
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
        credential: ChromaCredential,
        json_body: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
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
                error_message = error_data.get("error", error_data.get("message", str(error_data)))
            except Exception:
                error_message = response.text
            logger.error(f"[ChromaNode] API error ({action_name}): {error_message}")
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

    async def _resolve_collection_id(self, name: str, credential: ChromaCredential) -> str:
        """Resolve a collection name to its UUID via direct GET (O(1), cached per execution)."""
        cache = getattr(self, "_id_cache", None)
        if cache is None:
            cache = {}
            self._id_cache = cache
        if name in cache:
            return cache[name]
        url = f"{self._collections_base(credential)}/{name}"
        async with guarded_async_client(timeout=20.0) as client:
            resp = await client.get(url, headers=self._headers(credential))
        if resp.status_code == 404:
            raise ValueError(f"Chroma collection '{name}' not found")
        if resp.status_code >= 400:
            raise ValueError(f"Could not get Chroma collection '{name}' (status {resp.status_code})")
        col_id = resp.json().get("id")
        if not col_id:
            raise ValueError(f"Chroma collection '{name}' returned no id")
        cache[name] = col_id
        return col_id

    async def _record_request(
        self,
        collection: str,
        endpoint: str,
        credential: ChromaCredential,
        json_body: Dict[str, Any],
        action_name: str,
        method: str = "POST",
    ) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(collection, credential)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": action_name, "error": str(e), "status_code": 404}
        url = f"{self._collections_base(credential)}/{col_id}/{endpoint}"
        return await self._request(method, url, credential, json_body=json_body, action_name=action_name)

    async def _collection_get_request(
        self,
        collection: str,
        endpoint: str,
        credential: ChromaCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """GET on a UUID-keyed collection sub-endpoint (no body)."""
        try:
            col_id = await self._resolve_collection_id(collection, credential)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": action_name, "error": str(e), "status_code": 404}
        url = f"{self._collections_base(credential)}/{col_id}/{endpoint}"
        return await self._request("GET", url, credential, action_name=action_name)

    # =========================================================================
    # Operation handlers — Records
    # =========================================================================

    async def _handle_query(self, config: ChromaQueryConfig, credentials) -> Dict[str, Any]:
        vector = _parse_json_list(config.vector)
        if vector is None:
            return {"status": "error", "action": "query", "error": "`vector` must be a JSON array of numbers"}
        body: Dict[str, Any] = {
            "query_embeddings": [vector],
            "n_results": config.n_results,
        }
        where = _parse_json_obj(config.where)
        if where:
            body["where"] = where
        where_doc = _parse_json_obj(config.where_document)
        if where_doc:
            body["where_document"] = where_doc
        include = _parse_json_list(config.include)
        body["include"] = include if include else ["metadatas", "documents", "distances"]
        return await self._record_request(config.collection, "query", credentials, body, "query")

    async def _handle_search(self, config: ChromaSearchConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "query": config.query_text,
            "n_results": config.n_results,
        }
        where = _parse_json_obj(config.where)
        if where:
            body["where"] = where
        where_doc = _parse_json_obj(config.where_document)
        if where_doc:
            body["where_document"] = where_doc
        include = _parse_json_list(config.include)
        body["include"] = include if include else ["metadatas", "documents", "distances"]
        return await self._record_request(config.collection, "search", credentials, body, "search")

    async def _handle_add(self, config: ChromaAddConfig, credentials) -> Dict[str, Any]:
        return await self._add_or_upsert(config, credentials, "add")

    async def _handle_upsert(self, config: ChromaUpsertConfig, credentials) -> Dict[str, Any]:
        return await self._add_or_upsert(config, credentials, "upsert")

    async def _add_or_upsert(self, config, credentials, endpoint: str) -> Dict[str, Any]:
        ids = _split_csv(config.ids)
        if not ids:
            return {"status": "error", "action": endpoint, "error": "Provide at least one record ID"}
        embeddings = _parse_json_list(config.embeddings)
        if embeddings is None:
            return {"status": "error", "action": endpoint, "error": "`embeddings` must be a JSON array of vectors"}
        body: Dict[str, Any] = {"ids": ids, "embeddings": embeddings}
        documents = _parse_json_list(config.documents)
        if documents is not None:
            body["documents"] = documents
        metadatas = _parse_json_list(config.metadatas)
        if metadatas is not None:
            body["metadatas"] = metadatas
        return await self._record_request(config.collection, endpoint, credentials, body, endpoint)

    async def _handle_update(self, config: ChromaUpdateConfig, credentials) -> Dict[str, Any]:
        ids = _split_csv(config.ids)
        if not ids:
            return {"status": "error", "action": "update", "error": "Provide at least one record ID to update"}
        body: Dict[str, Any] = {"ids": ids}
        embeddings = _parse_json_list(config.embeddings)
        if embeddings is not None:
            body["embeddings"] = embeddings
        documents = _parse_json_list(config.documents)
        if documents is not None:
            body["documents"] = documents
        metadatas = _parse_json_list(config.metadatas)
        if metadatas is not None:
            body["metadatas"] = metadatas
        return await self._record_request(config.collection, "update", credentials, body, "update")

    async def _handle_get(self, config: ChromaGetConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        ids = _split_csv(config.ids)
        if ids:
            body["ids"] = ids
        where = _parse_json_obj(config.where)
        if where:
            body["where"] = where
        where_doc = _parse_json_obj(config.where_document)
        if where_doc:
            body["where_document"] = where_doc
        if config.limit is not None:
            body["limit"] = config.limit
        if config.offset is not None:
            body["offset"] = config.offset
        include = _parse_json_list(config.include)
        body["include"] = include if include else ["metadatas", "documents"]
        return await self._record_request(config.collection, "get", credentials, body, "get")

    async def _handle_count(self, config: ChromaCountConfig, credentials) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(config.collection, credentials)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": "count", "error": str(e), "status_code": 404}
        url = f"{self._collections_base(credentials)}/{col_id}/count"
        start_time = time.time()
        try:
            async with guarded_async_client(timeout=30.0) as client:
                resp = await client.get(url, headers=self._headers(credentials))
        except httpx.HTTPError as e:
            return {"status": "error", "action": "count", "error": str(e), "status_code": 500}
        api_time = round((time.time() - start_time) * 1000, 2)
        if resp.status_code >= 400:
            return {"status": "error", "action": "count", "error": resp.text, "status_code": resp.status_code}
        return {
            "status": "success",
            "action": "count",
            "data": {"count": resp.json()},
            "status_code": resp.status_code,
            "timing_ms": {"api_request": api_time},
        }

    async def _handle_delete(self, config: ChromaDeleteConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        ids = _split_csv(config.ids)
        if ids:
            body["ids"] = ids
        where = _parse_json_obj(config.where)
        if where:
            body["where"] = where
        where_doc = _parse_json_obj(config.where_document)
        if where_doc:
            body["where_document"] = where_doc
        if not body:
            return {
                "status": "error",
                "action": "delete",
                "error": "Specify record IDs, a where metadata filter, or a where_document filter",
            }
        return await self._record_request(config.collection, "delete", credentials, body, "delete")

    async def _handle_upload_and_index(self, config: ChromaUploadIndexConfig, credentials) -> Dict[str, Any]:
        records, info = await ingest_document(
            self,
            config.document,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            id_prefix=config.id_prefix,
        )
        if not records:
            return {
                "status": "error",
                "action": "upload_and_index",
                "error": "No text could be extracted from the document",
            }
        body = {
            "ids": [r["id"] for r in records],
            "embeddings": [r["values"] for r in records],
            "documents": [r["metadata"]["text"] for r in records],
            "metadatas": [
                {"source": r["metadata"]["source"], "chunk_index": r["metadata"]["chunk_index"]}
                for r in records
            ],
        }
        result = await self._record_request(config.collection, "add", credentials, body, "upload_and_index")
        if result.get("status") == "success":
            result["data"] = {
                "chunks_indexed": len(records),
                "source": info.get("filename"),
                "raw": result.get("data"),
            }
        return result

    # =========================================================================
    # Operation handlers — Collections
    # =========================================================================

    async def _handle_list_collections(self, config: ChromaListCollectionsConfig, credentials) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if config.limit is not None:
            params["limit"] = config.limit
        if config.offset is not None:
            params["offset"] = config.offset
        return await self._request(
            "GET",
            self._collections_base(credentials),
            credentials,
            params=params or None,
            action_name="list_collections",
        )

    async def _handle_get_collection(self, config: ChromaGetCollectionConfig, credentials) -> Dict[str, Any]:
        url = f"{self._collections_base(credentials)}/{config.collection}"
        return await self._request("GET", url, credentials, action_name="get_collection")

    async def _handle_create_collection(self, config: ChromaCreateCollectionConfig, credentials) -> Dict[str, Any]:
        initial_meta = _parse_json_obj(config.metadata) or {}
        if config.distance_metric:
            initial_meta["hnsw:space"] = config.distance_metric
        body: Dict[str, Any] = {"name": config.name, "get_or_create": config.get_or_create == "true"}
        if initial_meta:
            body["metadata"] = initial_meta
        return await self._request(
            "POST", self._collections_base(credentials), credentials, json_body=body, action_name="create_collection"
        )

    async def _handle_update_collection(self, config: ChromaUpdateCollectionConfig, credentials) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(config.collection, credentials)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": "update_collection", "error": str(e), "status_code": 404}
        url = f"{self._collections_base(credentials)}/{col_id}"
        body: Dict[str, Any] = {}
        if config.new_name:
            body["new_name"] = config.new_name
        new_meta = _parse_json_obj(config.metadata)
        if new_meta is not None:
            body["new_metadata"] = new_meta
        return await self._request("PUT", url, credentials, json_body=body, action_name="update_collection")

    async def _handle_delete_collection(self, config: ChromaDeleteCollectionConfig, credentials) -> Dict[str, Any]:
        # Chroma's DELETE endpoint resolves by name (not UUID), same as GET.
        url = f"{self._collections_base(credentials)}/{config.collection}"
        return await self._request("DELETE", url, credentials, action_name="delete_collection")

    async def _handle_count_collections(self, config: ChromaCountCollectionsConfig, credentials) -> Dict[str, Any]:
        url = f"{self._db_base(credentials)}/{credentials.database}/collections_count"
        # collections_count is under the database path, not the collections path
        url = (
            f"{self._base_url(credentials)}/api/v2/tenants/{credentials.tenant}"
            f"/databases/{credentials.database}/collections_count"
        )
        return await self._request("GET", url, credentials, action_name="count_collections")

    async def _handle_indexing_status(self, config: ChromaIndexingStatusConfig, credentials) -> Dict[str, Any]:
        return await self._collection_get_request(
            config.collection, "indexing_status", credentials, "indexing_status"
        )

    async def _handle_fork_collection(self, config: ChromaForkCollectionConfig, credentials) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(config.collection, credentials)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": "fork_collection", "error": str(e), "status_code": 404}
        url = f"{self._collections_base(credentials)}/{col_id}/fork"
        body: Dict[str, Any] = {"name": config.new_name}
        if config.destination_database:
            body["destination_database"] = config.destination_database
        return await self._request("POST", url, credentials, json_body=body, action_name="fork_collection")

    async def _handle_fork_count(self, config: ChromaForkCountConfig, credentials) -> Dict[str, Any]:
        return await self._collection_get_request(
            config.collection, "fork_count", credentials, "fork_count"
        )

    async def _handle_get_collection_by_id(
        self, config: ChromaGetCollectionByIdConfig, credentials
    ) -> Dict[str, Any]:
        url = f"{self._collections_base(credentials)}/by-id/{config.collection_id}"
        return await self._request("GET", url, credentials, action_name="get_collection_by_id")

    async def _handle_get_collection_by_crn(
        self, config: ChromaGetCollectionByCrnConfig, credentials
    ) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/api/v2/collections/{config.crn}"
        return await self._request("GET", url, credentials, action_name="get_collection_by_crn")

    # =========================================================================
    # Operation handlers — Attached Functions
    # =========================================================================

    async def _handle_attach_function(self, config: ChromaAttachFunctionConfig, credentials) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(config.collection, credentials)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": "attach_function", "error": str(e), "status_code": 404}
        url = f"{self._collections_base(credentials)}/{col_id}/functions/attach"
        body: Dict[str, Any] = {"name": config.function_name}
        fn_cfg = _parse_json_obj(config.function_config)
        if fn_cfg:
            body["config"] = fn_cfg
        return await self._request("POST", url, credentials, json_body=body, action_name="attach_function")

    async def _handle_get_attached_function(
        self, config: ChromaGetAttachedFunctionConfig, credentials
    ) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(config.collection, credentials)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": "get_attached_function", "error": str(e), "status_code": 404}
        url = f"{self._collections_base(credentials)}/{col_id}/functions/{config.function_name}"
        return await self._request("GET", url, credentials, action_name="get_attached_function")

    async def _handle_add_attached_function_input(
        self, config: ChromaAddAttachedFunctionInputConfig, credentials
    ) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(config.collection, credentials)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": "add_attached_function_input", "error": str(e), "status_code": 404}
        url = (
            f"{self._collections_base(credentials)}/{col_id}"
            f"/attached_functions/{config.function_name}/add_input"
        )
        input_data = _parse_json_obj(config.input)
        if input_data is None:
            return {
                "status": "error",
                "action": "add_attached_function_input",
                "error": "`input` must be a valid JSON object",
            }
        return await self._request(
            "POST", url, credentials, json_body={"input": input_data}, action_name="add_attached_function_input"
        )

    async def _handle_detach_function(self, config: ChromaDetachFunctionConfig, credentials) -> Dict[str, Any]:
        try:
            col_id = await self._resolve_collection_id(config.collection, credentials)
        except (ValueError, httpx.HTTPError) as e:
            return {"status": "error", "action": "detach_function", "error": str(e), "status_code": 404}
        url = (
            f"{self._collections_base(credentials)}/{col_id}"
            f"/attached_functions/{config.function_name}/detach"
        )
        return await self._request("POST", url, credentials, json_body={}, action_name="detach_function")

    # =========================================================================
    # Operation handlers — Tenant Management
    # =========================================================================

    async def _handle_get_tenant(self, config: ChromaGetTenantConfig, credentials) -> Dict[str, Any]:
        name = config.tenant_name or credentials.tenant
        url = f"{self._tenant_base(credentials)}/{name}"
        return await self._request("GET", url, credentials, action_name="get_tenant")

    async def _handle_create_tenant(self, config: ChromaCreateTenantConfig, credentials) -> Dict[str, Any]:
        url = self._tenant_base(credentials)
        return await self._request(
            "POST", url, credentials, json_body={"name": config.tenant_name}, action_name="create_tenant"
        )

    async def _handle_update_tenant(self, config: ChromaUpdateTenantConfig, credentials) -> Dict[str, Any]:
        name = config.tenant_name or credentials.tenant
        url = f"{self._tenant_base(credentials)}/{name}"
        body: Dict[str, Any] = {}
        cfg = _parse_json_obj(config.config)
        if cfg:
            body["config"] = cfg
        return await self._request("PATCH", url, credentials, json_body=body, action_name="update_tenant")

    # =========================================================================
    # Operation handlers — Database Management
    # =========================================================================

    async def _handle_list_databases(self, config: ChromaListDatabasesConfig, credentials) -> Dict[str, Any]:
        url = self._db_base(credentials)
        return await self._request("GET", url, credentials, action_name="list_databases")

    async def _handle_create_database(self, config: ChromaCreateDatabaseConfig, credentials) -> Dict[str, Any]:
        url = self._db_base(credentials)
        return await self._request(
            "POST", url, credentials, json_body={"name": config.database_name}, action_name="create_database"
        )

    async def _handle_get_database(self, config: ChromaGetDatabaseConfig, credentials) -> Dict[str, Any]:
        name = config.database_name or credentials.database
        url = f"{self._db_base(credentials)}/{name}"
        return await self._request("GET", url, credentials, action_name="get_database")

    async def _handle_delete_database(self, config: ChromaDeleteDatabaseConfig, credentials) -> Dict[str, Any]:
        name = config.database_name or credentials.database
        url = f"{self._db_base(credentials)}/{name}"
        return await self._request("DELETE", url, credentials, action_name="delete_database")

    # =========================================================================
    # Operation handlers — Utility
    # =========================================================================

    async def _handle_healthcheck(self, config: ChromaHealthcheckConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/api/v2/healthcheck"
        return await self._request("GET", url, credentials, action_name="healthcheck")

    async def _handle_heartbeat(self, config: ChromaHeartbeatConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/api/v2/heartbeat"
        return await self._request("GET", url, credentials, action_name="heartbeat")

    async def _handle_version(self, config: ChromaVersionConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/api/v2/version"
        return await self._request("GET", url, credentials, action_name="version")

    async def _handle_reset(self, config: ChromaResetConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/api/v2/reset"
        return await self._request("POST", url, credentials, json_body={}, action_name="reset")

    async def _handle_get_user_identity(
        self, config: ChromaGetUserIdentityConfig, credentials
    ) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/api/v2/auth/identity"
        return await self._request("GET", url, credentials, action_name="get_user_identity")
