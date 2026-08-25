"""
Elasticsearch automation node.

Provides workflow integration with current Elasticsearch document, search,
vector-search, and index-management APIs for Elastic Cloud / Serverless or
self-hosted clusters.

Authentication supported by the official API docs:
- API key
- Basic auth
- Bearer auth

Docs: https://www.elastic.co/docs/api/doc/elasticsearch
"""

import json
import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.document_ingest import DOCUMENT_ACCEPT, ingest_document
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

RefreshPolicy = Literal["false", "true", "wait_for"]
ConflictPolicy = Literal["abort", "proceed"]

_TEXTAREA = {"ui:widget": "textarea"}
_INDEX_FIELD_EXTRA = {
    "x-resource-type": "elasticsearch_index",
    "x-dynamic-options": {
        "field_name": "index",
        "placeholder": "Select an index or enter a pattern...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type an index / alias / pattern",
    }
}


# ============================================================================
# Credential Schema
# ============================================================================


class ElasticsearchCredential(BaseModel):
    """Elasticsearch credential: cluster URL + API key."""

    credential_type: Literal["elasticsearch_api_key"] = Field(
        "elasticsearch_api_key",
        json_schema_extra={"ui:hidden": True},
    )
    url: str = Field(
        ...,
        title="Cluster URL",
        description="Your Elasticsearch endpoint, e.g. https://my-deployment.es.us-central1.gcp.cloud.es.io",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Encoded Elastic API key (the value shown after creating a key in Kibana → Stack Management → API Keys)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://www.elastic.co/docs/deploy-manage/api-keys/elasticsearch-api-keys",
            "x-credential-instructions": "Create an API key in Kibana → Stack Management → API Keys and paste the encoded value here.",
        }
    )


# ============================================================================
# Operation Configs
# ============================================================================


class ESSearchConfig(BaseModel):
    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search",
            "x-keywords": ["search", "vector search", "knn", "similarity search", "rag", "retrieve"],
        },
        title="Search",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern to search", json_schema_extra=_INDEX_FIELD_EXTRA)
    field: str = Field(..., title="Vector Field", description="The dense_vector field to search against")
    query_vector: Optional[str] = Field(
        None,
        title="Query Vector",
        description="JSON array of numbers used for kNN search",
        json_schema_extra=_TEXTAREA,
    )
    query_vector_builder: Optional[str] = Field(
        None,
        title="Query Vector Builder",
        description='Optional JSON object for server-side vector construction, e.g. {"text_embedding": {"model_id": "my-model", "model_text": "hello"}}',
        json_schema_extra=_TEXTAREA,
    )
    k: int = Field(10, title="K", description="Number of nearest neighbours to return")
    num_candidates: int = Field(100, title="Num Candidates", description="Candidates considered per shard (>= k)")
    similarity: Optional[float] = Field(None, title="Similarity Threshold", description="Optional minimum similarity score")
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description='Optional Query DSL filter JSON, e.g. {"term": {"category": "docs"}}',
        json_schema_extra=_TEXTAREA,
    )
    source: Optional[str] = Field(None, title="Source Fields", description="Fields to return, comma-separated")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")

    @model_validator(mode="after")
    def validate_query_input(self):
        if bool(self.query_vector) == bool(self.query_vector_builder):
            raise ValueError("Provide exactly one of Query Vector or Query Vector Builder")
        return self


class ESCountConfig(BaseModel):
    operation: Literal["count"] = Field(
        "count",
        json_schema_extra={
            "const": "count",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Count Documents",
            "x-keywords": ["count", "count documents", "how many"],
        },
        title="Count Documents",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern to count", json_schema_extra=_INDEX_FIELD_EXTRA)
    query: Optional[str] = Field(
        None,
        title="Query",
        description='Optional Query DSL JSON. If blank, counts all documents in the target index pattern.',
        json_schema_extra=_TEXTAREA,
    )
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")


class ESMultiSearchConfig(BaseModel):
    operation: Literal["multi_search"] = Field(
        "multi_search",
        json_schema_extra={
            "const": "multi_search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Multi Search",
            "x-keywords": ["msearch", "multi search", "batch search", "search many"],
        },
        title="Multi Search",
    )
    index: Optional[str] = Field(
        None,
        title="Default Index",
        description="Optional default index for each search request",
        json_schema_extra=_INDEX_FIELD_EXTRA,
    )
    searches: str = Field(
        ...,
        title="Searches",
        description='JSON array. Each item may be {"body": {...}} or {"header": {...}, "body": {...}}.',
        json_schema_extra=_TEXTAREA,
    )


class ESIndexDocConfig(BaseModel):
    operation: Literal["index_document"] = Field(
        "index_document",
        json_schema_extra={
            "const": "index_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Index Document",
            "x-keywords": ["index", "insert", "add", "upsert", "store", "write"],
        },
        title="Index Document",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    document: str = Field(
        ...,
        title="Document",
        description='JSON object, e.g. {"content": "...", "contentVector": [0.1, ...]}',
        json_schema_extra=_TEXTAREA,
    )
    id: Optional[str] = Field(None, title="ID", description="Document _id (auto-generated if blank)")
    pipeline: Optional[str] = Field(None, title="Ingest Pipeline", description="Optional ingest pipeline ID")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")
    refresh: RefreshPolicy = Field("wait_for", title="Refresh Policy", description="When the write becomes visible to search")


class ESCreateDocConfig(BaseModel):
    operation: Literal["create_document"] = Field(
        "create_document",
        json_schema_extra={
            "const": "create_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Create Document",
            "x-keywords": ["create", "insert if absent", "create only", "dedupe write"],
        },
        title="Create Document",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    id: str = Field(..., title="ID", description="Document _id. The request fails if this ID already exists.")
    document: str = Field(
        ...,
        title="Document",
        description='JSON object to create, e.g. {"content": "..."}',
        json_schema_extra=_TEXTAREA,
    )
    pipeline: Optional[str] = Field(None, title="Ingest Pipeline", description="Optional ingest pipeline ID")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")
    refresh: RefreshPolicy = Field("wait_for", title="Refresh Policy", description="When the write becomes visible to search")


class ESBulkIndexConfig(BaseModel):
    operation: Literal["bulk_index"] = Field(
        "bulk_index",
        json_schema_extra={
            "const": "bulk_index",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Bulk Index",
            "x-keywords": ["bulk", "batch insert", "ingest", "index many"],
        },
        title="Bulk Index",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    documents: str = Field(
        ...,
        title="Documents",
        description='JSON array of documents. Each may include "_id".',
        json_schema_extra=_TEXTAREA,
    )
    pipeline: Optional[str] = Field(None, title="Ingest Pipeline", description="Optional ingest pipeline ID")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")
    refresh: RefreshPolicy = Field("wait_for", title="Refresh Policy", description="When the writes become visible to search")


class ESBulkWriteConfig(BaseModel):
    operation: Literal["bulk_write"] = Field(
        "bulk_write",
        json_schema_extra={
            "const": "bulk_write",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Bulk Write",
            "x-keywords": ["bulk", "batch write", "bulk create", "bulk update", "bulk delete"],
        },
        title="Bulk Write",
    )
    index: Optional[str] = Field(
        None,
        title="Default Index",
        description="Optional default index for actions that do not specify _index",
        json_schema_extra=_INDEX_FIELD_EXTRA,
    )
    actions: str = Field(
        ...,
        title="Actions",
        description='JSON array of action objects. Example: [{"action":"index","_id":"1","document":{"content":"a"}},{"action":"delete","_id":"2"}].',
        json_schema_extra=_TEXTAREA,
    )
    pipeline: Optional[str] = Field(None, title="Ingest Pipeline", description="Optional ingest pipeline ID")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")
    refresh: RefreshPolicy = Field("wait_for", title="Refresh Policy", description="When the writes become visible to search")


class ESGetDocConfig(BaseModel):
    operation: Literal["get_document"] = Field(
        "get_document",
        json_schema_extra={
            "const": "get_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Get Document",
            "x-keywords": ["get", "fetch", "lookup by id", "read"],
        },
        title="Get Document",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    id: str = Field(..., title="ID", description="Document _id")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")


class ESGetDocSourceConfig(BaseModel):
    operation: Literal["get_document_source"] = Field(
        "get_document_source",
        json_schema_extra={
            "const": "get_document_source",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Get Document Source",
            "x-keywords": ["source", "get source", "document source"],
        },
        title="Get Document Source",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    id: str = Field(..., title="ID", description="Document _id")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")


class ESDocumentExistsConfig(BaseModel):
    operation: Literal["document_exists"] = Field(
        "document_exists",
        json_schema_extra={
            "const": "document_exists",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Document Exists",
            "x-keywords": ["exists", "head", "document exists"],
        },
        title="Document Exists",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    id: str = Field(..., title="ID", description="Document _id")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")


class ESMultiGetConfig(BaseModel):
    operation: Literal["multi_get"] = Field(
        "multi_get",
        json_schema_extra={
            "const": "multi_get",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Multi Get",
            "x-keywords": ["mget", "multi get", "fetch many"],
        },
        title="Multi Get",
    )
    index: Optional[str] = Field(None, title="Index", description="Optional default index for the request", json_schema_extra=_INDEX_FIELD_EXTRA)
    items: str = Field(
        ...,
        title="Items",
        description='JSON array. With Index set, use ["1","2"] or [{"_id":"1"}]. Without Index set, use [{"_index":"docs","_id":"1"}].',
        json_schema_extra=_TEXTAREA,
    )


class ESUpdateDocConfig(BaseModel):
    operation: Literal["update_document"] = Field(
        "update_document",
        json_schema_extra={
            "const": "update_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Update Document",
            "x-keywords": ["update", "partial update", "scripted update"],
        },
        title="Update Document",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    id: str = Field(..., title="ID", description="Document _id")
    document: Optional[str] = Field(
        None,
        title="Partial Document",
        description='Optional JSON object merged into the existing document, e.g. {"status": "done"}',
        json_schema_extra=_TEXTAREA,
    )
    script: Optional[str] = Field(
        None,
        title="Script",
        description='Optional Painless script JSON, e.g. {"source": "ctx._source.count += params.n", "params": {"n": 1}}',
        json_schema_extra=_TEXTAREA,
    )
    upsert: Optional[str] = Field(
        None,
        title="Upsert Document",
        description="Optional JSON object used if the document does not exist",
        json_schema_extra=_TEXTAREA,
    )
    scripted_upsert: bool = Field(False, title="Scripted Upsert", description="Run the script even when the document does not exist")
    doc_as_upsert: bool = Field(False, title="Doc As Upsert", description="Treat Partial Document as the upsert document")
    retry_on_conflict: Optional[int] = Field(None, title="Retry On Conflict", description="Number of version-conflict retries")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")
    refresh: RefreshPolicy = Field("wait_for", title="Refresh Policy", description="When the update becomes visible to search")

    @model_validator(mode="after")
    def validate_update_input(self):
        if not self.document and not self.script:
            raise ValueError("Provide at least one of Partial Document or Script")
        return self


class ESDeleteDocConfig(BaseModel):
    operation: Literal["delete_document"] = Field(
        "delete_document",
        json_schema_extra={
            "const": "delete_document",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Delete Document",
            "x-keywords": ["delete", "remove", "purge"],
        },
        title="Delete Document",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    id: str = Field(..., title="ID", description="Document _id")
    routing: Optional[str] = Field(None, title="Routing", description="Optional custom shard routing value")
    refresh: RefreshPolicy = Field("wait_for", title="Refresh Policy", description="When the deletion becomes visible to search")


class ESDeleteByQueryConfig(BaseModel):
    operation: Literal["delete_by_query"] = Field(
        "delete_by_query",
        json_schema_extra={
            "const": "delete_by_query",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Delete By Query",
            "x-keywords": ["delete by query", "bulk delete", "remove matching"],
        },
        title="Delete By Query",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    query: str = Field(..., title="Query", description="Query DSL JSON selecting documents to delete", json_schema_extra=_TEXTAREA)
    conflicts: ConflictPolicy = Field("proceed", title="Conflicts", description="How version conflicts are handled")
    refresh: bool = Field(True, title="Refresh", description="Refresh affected shards after completion")
    wait_for_completion: bool = Field(True, title="Wait For Completion", description="Wait for the task to finish before returning")
    requests_per_second: Optional[float] = Field(None, title="Requests Per Second", description="Throttle rate for the operation")


class ESUpdateByQueryConfig(BaseModel):
    operation: Literal["update_by_query"] = Field(
        "update_by_query",
        json_schema_extra={
            "const": "update_by_query",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Update By Query",
            "x-keywords": ["update by query", "bulk update", "mutate matching"],
        },
        title="Update By Query",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    query: str = Field(..., title="Query", description="Query DSL JSON selecting documents to update", json_schema_extra=_TEXTAREA)
    script: str = Field(..., title="Script", description="Painless script JSON", json_schema_extra=_TEXTAREA)
    conflicts: ConflictPolicy = Field("proceed", title="Conflicts", description="How version conflicts are handled")
    refresh: bool = Field(True, title="Refresh", description="Refresh affected shards after completion")
    wait_for_completion: bool = Field(True, title="Wait For Completion", description="Wait for the task to finish before returning")
    requests_per_second: Optional[float] = Field(None, title="Requests Per Second", description="Throttle rate for the operation")


class ESReindexConfig(BaseModel):
    operation: Literal["reindex_documents"] = Field(
        "reindex_documents",
        json_schema_extra={
            "const": "reindex_documents",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Reindex Documents",
            "x-keywords": ["reindex", "copy documents", "migrate index"],
        },
        title="Reindex Documents",
    )
    source_index: str = Field(..., title="Source Index", description="Index, alias, or pattern to read from")
    dest_index: str = Field(..., title="Destination Index", description="Destination index or alias")
    query: Optional[str] = Field(None, title="Source Query", description="Optional source Query DSL JSON", json_schema_extra=_TEXTAREA)
    script: Optional[str] = Field(None, title="Script", description="Optional transform script JSON", json_schema_extra=_TEXTAREA)
    max_docs: Optional[int] = Field(None, title="Max Docs", description="Maximum number of documents to reindex")
    dest_pipeline: Optional[str] = Field(None, title="Destination Pipeline", description="Optional destination ingest pipeline ID")
    conflicts: ConflictPolicy = Field("proceed", title="Conflicts", description="How version conflicts are handled")
    refresh: bool = Field(True, title="Refresh", description="Refresh the destination after completion")
    wait_for_completion: bool = Field(True, title="Wait For Completion", description="Wait for the task to finish before returning")


class ESListIndicesConfig(BaseModel):
    operation: Literal["list_indices"] = Field(
        "list_indices",
        json_schema_extra={
            "const": "list_indices",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "List Indices",
            "x-keywords": ["list indices", "show indices"],
        },
        title="List Indices",
    )


class ESIndexExistsConfig(BaseModel):
    operation: Literal["index_exists"] = Field(
        "index_exists",
        json_schema_extra={
            "const": "index_exists",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Index Exists",
            "x-keywords": ["index exists", "check index", "head index"],
        },
        title="Index Exists",
    )
    index: str = Field(..., title="Index", description="Index, alias, data stream, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)


class ESGetIndexConfig(BaseModel):
    operation: Literal["get_index"] = Field(
        "get_index",
        json_schema_extra={
            "const": "get_index",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Get Index",
            "x-keywords": ["get index", "index info", "describe index"],
        },
        title="Get Index",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)
    include_defaults: bool = Field(False, title="Include Defaults", description="Include default settings in the response")
    flat_settings: bool = Field(False, title="Flat Settings", description="Return settings in flat format")


class ESCreateIndexConfig(BaseModel):
    operation: Literal["create_index"] = Field(
        "create_index",
        json_schema_extra={
            "const": "create_index",
            "x-creates-resource": True,
            "x-resource-type": "elasticsearch_index",
            "x-resource-id-path": "data.index",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Create Index",
            "x-keywords": ["create index", "new index", "provision index", "mapping"],
        },
        title="Create Index",
    )
    index: str = Field(..., title="Index", description="Name for the new index")
    mappings: str = Field(..., title="Mappings", description="JSON mappings object", json_schema_extra=_TEXTAREA)
    settings: Optional[str] = Field(None, title="Settings", description="Optional JSON index settings object", json_schema_extra=_TEXTAREA)
    aliases: Optional[str] = Field(None, title="Aliases", description="Optional JSON aliases object", json_schema_extra=_TEXTAREA)


class ESDeleteIndexConfig(BaseModel):
    operation: Literal["delete_index"] = Field(
        "delete_index",
        json_schema_extra={
            "const": "delete_index",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Delete Index",
            "x-keywords": ["delete index", "remove index"],
        },
        title="Delete Index",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)


class ESRefreshIndexConfig(BaseModel):
    operation: Literal["refresh_index"] = Field(
        "refresh_index",
        json_schema_extra={
            "const": "refresh_index",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Refresh Index",
            "x-keywords": ["refresh index", "make searchable"],
        },
        title="Refresh Index",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)


class ESGetMappingConfig(BaseModel):
    operation: Literal["get_mapping"] = Field(
        "get_mapping",
        json_schema_extra={
            "const": "get_mapping",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Get Mapping",
            "x-keywords": ["get mapping", "mapping info", "field mapping"],
        },
        title="Get Mapping",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)


class ESUpdateMappingConfig(BaseModel):
    operation: Literal["update_mapping"] = Field(
        "update_mapping",
        json_schema_extra={
            "const": "update_mapping",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Update Mapping",
            "x-keywords": ["update mapping", "put mapping", "add field"],
        },
        title="Update Mapping",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)
    mappings: str = Field(..., title="Mappings", description="JSON mappings object", json_schema_extra=_TEXTAREA)


class ESGetSettingsConfig(BaseModel):
    operation: Literal["get_settings"] = Field(
        "get_settings",
        json_schema_extra={
            "const": "get_settings",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Get Settings",
            "x-keywords": ["get settings", "index settings"],
        },
        title="Get Settings",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)
    include_defaults: bool = Field(False, title="Include Defaults", description="Include default settings in the response")
    flat_settings: bool = Field(False, title="Flat Settings", description="Return settings in flat format")


class ESUpdateSettingsConfig(BaseModel):
    operation: Literal["update_settings"] = Field(
        "update_settings",
        json_schema_extra={
            "const": "update_settings",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Update Settings",
            "x-keywords": ["update settings", "put settings", "index settings"],
        },
        title="Update Settings",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)
    settings: str = Field(..., title="Settings", description="JSON settings object", json_schema_extra=_TEXTAREA)
    preserve_existing: bool = Field(False, title="Preserve Existing", description="Only set values that are not already configured")


class ESListAliasesConfig(BaseModel):
    operation: Literal["list_aliases"] = Field(
        "list_aliases",
        json_schema_extra={
            "const": "list_aliases",
            "ui:hidden": True,
            "x-category": "Aliases",
            "x-is-trigger": False,
            "x-display-name": "List Aliases",
            "x-keywords": ["aliases", "list aliases", "get aliases"],
        },
        title="List Aliases",
    )
    index: str = Field("*", title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)
    name: Optional[str] = Field(None, title="Alias Name", description="Optional alias name or pattern")


class ESAliasExistsConfig(BaseModel):
    operation: Literal["alias_exists"] = Field(
        "alias_exists",
        json_schema_extra={
            "const": "alias_exists",
            "ui:hidden": True,
            "x-category": "Aliases",
            "x-is-trigger": False,
            "x-display-name": "Alias Exists",
            "x-keywords": ["alias exists", "check alias", "head alias"],
        },
        title="Alias Exists",
    )
    name: str = Field(..., title="Alias Name", description="Alias name or pattern to check")
    index: Optional[str] = Field(
        None,
        title="Index",
        description="Optional index pattern to limit the alias check",
        json_schema_extra=_INDEX_FIELD_EXTRA,
    )


class ESUpdateAliasesConfig(BaseModel):
    operation: Literal["update_aliases"] = Field(
        "update_aliases",
        json_schema_extra={
            "const": "update_aliases",
            "ui:hidden": True,
            "x-category": "Aliases",
            "x-is-trigger": False,
            "x-display-name": "Update Aliases",
            "x-keywords": ["alias", "update aliases", "add alias", "remove alias"],
        },
        title="Update Aliases",
    )
    actions: str = Field(
        ...,
        title="Actions",
        description='JSON array for the _aliases API, e.g. [{"add": {"index": "docs", "alias": "docs-live"}}]',
        json_schema_extra=_TEXTAREA,
    )


class ESGetIndexStatsConfig(BaseModel):
    operation: Literal["get_index_stats"] = Field(
        "get_index_stats",
        json_schema_extra={
            "const": "get_index_stats",
            "ui:hidden": True,
            "x-category": "Index",
            "x-is-trigger": False,
            "x-display-name": "Get Index Stats",
            "x-keywords": ["stats", "index stats", "index metrics"],
        },
        title="Get Index Stats",
    )
    index: str = Field(..., title="Index", description="Index, alias, or pattern", json_schema_extra=_INDEX_FIELD_EXTRA)
    metrics: Optional[str] = Field(None, title="Metrics", description="Optional comma-separated metric list, e.g. docs,store,indexing")


class ESUploadIndexConfig(BaseModel):
    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index",
            "ui:hidden": True,
            "x-category": "Documents",
            "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file"],
        },
        title="Upload & Index Document",
    )
    index: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD_EXTRA)
    document: str = Field(
        ...,
        title="Document",
        description="Upload a PDF/DOCX/TXT/MD/CSV/JSON/HTML file (or pass a URL / upstream file reference). It is chunked, embedded with text-embedding-3-small, and bulk-indexed.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": DOCUMENT_ACCEPT},
    )
    vector_field: str = Field("vector", title="Vector Field", description="The index dense_vector field name")
    text_field: str = Field("text", title="Text Field", description="The index field that stores chunk text")
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap", description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(None, title="ID Prefix", description="Optional prefix for chunk IDs")
    pipeline: Optional[str] = Field(None, title="Ingest Pipeline", description="Optional ingest pipeline ID")
    refresh: RefreshPolicy = Field("wait_for", title="Refresh Policy", description="When the writes become visible to search")


# ============================================================================
# Discriminated Union
# ============================================================================


ElasticsearchConfig = Annotated[
    Union[
        ESSearchConfig,
        ESCountConfig,
        ESMultiSearchConfig,
        ESIndexDocConfig,
        ESCreateDocConfig,
        ESBulkIndexConfig,
        ESBulkWriteConfig,
        ESGetDocConfig,
        ESGetDocSourceConfig,
        ESDocumentExistsConfig,
        ESMultiGetConfig,
        ESUpdateDocConfig,
        ESDeleteDocConfig,
        ESDeleteByQueryConfig,
        ESUpdateByQueryConfig,
        ESReindexConfig,
        ESListIndicesConfig,
        ESIndexExistsConfig,
        ESGetIndexConfig,
        ESCreateIndexConfig,
        ESDeleteIndexConfig,
        ESRefreshIndexConfig,
        ESGetMappingConfig,
        ESUpdateMappingConfig,
        ESGetSettingsConfig,
        ESUpdateSettingsConfig,
        ESListAliasesConfig,
        ESAliasExistsConfig,
        ESUpdateAliasesConfig,
        ESGetIndexStatsConfig,
        ESUploadIndexConfig,
    ],
    Discriminator("operation"),
]


class ElasticsearchNodeConfig(NodeConfig[ElasticsearchConfig, ElasticsearchCredential]):
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


def _csv_fields(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    fields = [part.strip() for part in value.split(",") if part.strip()]
    return fields or None


def _request_params(**params: Any) -> Optional[Dict[str, Any]]:
    cleaned = {key: value for key, value in params.items() if value not in (None, "")}
    if "refresh" in cleaned and isinstance(cleaned["refresh"], bool):
        cleaned["refresh"] = str(cleaned["refresh"]).lower()
    if "wait_for_completion" in cleaned and isinstance(cleaned["wait_for_completion"], bool):
        cleaned["wait_for_completion"] = str(cleaned["wait_for_completion"]).lower()
    if "include_defaults" in cleaned and isinstance(cleaned["include_defaults"], bool):
        cleaned["include_defaults"] = str(cleaned["include_defaults"]).lower()
    if "flat_settings" in cleaned and isinstance(cleaned["flat_settings"], bool):
        cleaned["flat_settings"] = str(cleaned["flat_settings"]).lower()
    if "preserve_existing" in cleaned and isinstance(cleaned["preserve_existing"], bool):
        cleaned["preserve_existing"] = str(cleaned["preserve_existing"]).lower()
    return cleaned or None


# ============================================================================
# Node Implementation
# ============================================================================


class ElasticsearchNode(WorkflowNode):
    """Elasticsearch automation node."""

    edit_examples = [
        "kNN-search an Elasticsearch index for the documents most similar to a query embedding",
        "Index or bulk-index documents into Elasticsearch and search them immediately",
        "Update matching documents with update_by_query, or delete them with delete_by_query",
        "Reindex documents from one Elasticsearch index into another",
        "Inspect mappings, settings, aliases, and stats for an Elasticsearch index",
    ]

    @classmethod
    def get_config_model(cls):
        return ElasticsearchNodeConfig

    @staticmethod
    def _base_url(credential: ElasticsearchCredential) -> str:
        return (credential.url or "").rstrip("/")

    @staticmethod
    def _auth_header(credential: ElasticsearchCredential) -> Dict[str, str]:
        return {"Authorization": f"ApiKey {credential.api_key}", "User-Agent": "NoClick-Workflow/1.0"}

    @classmethod
    def _normalize_resolved_indices(cls, payload: Any) -> List[Dict[str, Any]]:
        rows = payload.get("indices") if isinstance(payload, dict) else []
        results: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if not name or name.startswith("."):
                continue
            results.append(
                {
                    "name": name,
                    "attributes": row.get("attributes") or [],
                    "aliases": row.get("aliases") or [],
                    "data_stream": row.get("data_stream"),
                    "mode": row.get("mode"),
                }
            )
        return results

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Populate the index dropdown from the resolve-index API."""
        if field_name != "index":
            return []
        try:
            credential = ElasticsearchCredential.model_validate(credential_data or {})
        except Exception:
            return []

        try:
            async with guarded_async_client(timeout=20.0) as client:
                response = await client.get(
                    f"{cls._base_url(credential)}/_resolve/index/*",
                    headers=cls._auth_header(credential),
                    params={
                        "expand_wildcards": "open,closed",
                        "ignore_unavailable": "true",
                        "allow_no_indices": "true",
                    },
                )
        except httpx.HTTPError as e:
            logger.warning(f"[ElasticsearchNode] Failed to list indices: {e}")
            return []

        if response.status_code >= 400:
            logger.warning(f"[ElasticsearchNode] List indices returned {response.status_code}: {response.text}")
            return []

        options = []
        for row in cls._normalize_resolved_indices(response.json() or {}):
            name = row["name"]
            if search and search.lower() not in name.lower():
                continue
            options.append({"value": name, "label": name})
        return options

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, ElasticsearchNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Elasticsearch URL and authentication details.")

        handlers = {
            "search": self._handle_search,
            "count": self._handle_count,
            "multi_search": self._handle_multi_search,
            "index_document": self._handle_index_document,
            "create_document": self._handle_create_document,
            "bulk_index": self._handle_bulk_index,
            "bulk_write": self._handle_bulk_write,
            "get_document": self._handle_get_document,
            "get_document_source": self._handle_get_document_source,
            "document_exists": self._handle_document_exists,
            "multi_get": self._handle_multi_get,
            "update_document": self._handle_update_document,
            "delete_document": self._handle_delete_document,
            "delete_by_query": self._handle_delete_by_query,
            "update_by_query": self._handle_update_by_query,
            "reindex_documents": self._handle_reindex_documents,
            "list_indices": self._handle_list_indices,
            "index_exists": self._handle_index_exists,
            "get_index": self._handle_get_index,
            "create_index": self._handle_create_index,
            "delete_index": self._handle_delete_index,
            "refresh_index": self._handle_refresh_index,
            "get_mapping": self._handle_get_mapping,
            "update_mapping": self._handle_update_mapping,
            "get_settings": self._handle_get_settings,
            "update_settings": self._handle_update_settings,
            "list_aliases": self._handle_list_aliases,
            "alias_exists": self._handle_alias_exists,
            "update_aliases": self._handle_update_aliases,
            "get_index_stats": self._handle_get_index_stats,
            "upload_and_index": self._handle_upload_and_index,
        }

        op_config = config.config
        handler = handlers.get(op_config.operation)
        if not handler:
            raise ValueError(f"Unknown action: {op_config.operation}")

        result = await handler(op_config, credentials)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    async def _request(
        self,
        method: str,
        url: str,
        credential: ElasticsearchCredential,
        *,
        json_body: Optional[Any] = None,
        content: Optional[str] = None,
        content_type: str = "application/json",
        params: Optional[Dict[str, Any]] = None,
        action_name: str,
    ) -> Dict[str, Any]:
        start_time = time.time()
        headers = self._auth_header(credential)
        if json_body is not None or content is not None:
            headers["Content-Type"] = content_type

        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_body if content is None else None,
                    content=content,
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
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code >= 400:
            error_message = response.text
            if isinstance(data, dict) and isinstance(data.get("error"), dict):
                err = data["error"]
                error_message = err.get("reason", err.get("type", response.text))
            logger.error(f"[ElasticsearchNode] API error ({action_name}): {error_message}")
            return {
                "status": "error",
                "action": action_name,
                "error": error_message,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_time},
            }

        return {
            "status": "success",
            "action": action_name,
            "data": data,
            "status_code": response.status_code,
            "timing_ms": {"api_request": api_time},
        }

    async def _head_request(
        self,
        url: str,
        credential: ElasticsearchCredential,
        *,
        params: Optional[Dict[str, Any]],
        action_name: str,
    ) -> Dict[str, Any]:
        start_time = time.time()
        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.request(
                    method="HEAD",
                    url=url,
                    headers=self._auth_header(credential),
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
        if response.status_code == 404:
            return {
                "status": "success",
                "action": action_name,
                "data": {"exists": False},
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_time},
            }
        if response.status_code >= 400:
            return {
                "status": "error",
                "action": action_name,
                "error": response.text or f"HTTP {response.status_code}",
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_time},
            }
        return {
            "status": "success",
            "action": action_name,
            "data": {"exists": True},
            "status_code": response.status_code,
            "timing_ms": {"api_request": api_time},
        }

    async def _handle_search(self, config: ESSearchConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        knn: Dict[str, Any] = {
            "field": config.field,
            "k": config.k,
            "num_candidates": config.num_candidates,
        }
        if config.query_vector_builder:
            query_vector_builder = _parse_json_obj(config.query_vector_builder)
            if query_vector_builder is None:
                return {"status": "error", "action": "search", "error": "`query_vector_builder` must be a JSON object"}
            knn["query_vector_builder"] = query_vector_builder
        else:
            query_vector = _parse_json_list(config.query_vector)
            if query_vector is None:
                return {"status": "error", "action": "search", "error": "`query_vector` must be a JSON array of numbers"}
            knn["query_vector"] = query_vector
        if config.similarity is not None:
            knn["similarity"] = config.similarity
        metadata_filter = _parse_json_obj(config.filter)
        if metadata_filter:
            knn["filter"] = metadata_filter
        body: Dict[str, Any] = {"knn": knn}
        source = _csv_fields(config.source)
        if source:
            body["_source"] = source
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/{config.index}/_search",
            credentials,
            json_body=body,
            params=_request_params(routing=config.routing),
            action_name="search",
        )

    async def _handle_count(self, config: ESCountConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        body = None
        if config.query:
            query = _parse_json_obj(config.query)
            if query is None:
                return {"status": "error", "action": "count", "error": "`query` must be a JSON object"}
            body = {"query": query}
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/{config.index}/_count",
            credentials,
            json_body=body,
            params=_request_params(routing=config.routing),
            action_name="count",
        )

    async def _handle_multi_search(self, config: ESMultiSearchConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        searches = _parse_json_list(config.searches)
        if searches is None:
            return {"status": "error", "action": "multi_search", "error": "`searches` must be a JSON array"}

        lines: List[str] = []
        for item in searches:
            if not isinstance(item, dict):
                return {"status": "error", "action": "multi_search", "error": "Each search item must be a JSON object"}
            header = item.get("header", {})
            body = item.get("body")
            if body is None:
                body = {key: value for key, value in item.items() if key != "header"}
            if not isinstance(header, dict) or not isinstance(body, dict):
                return {"status": "error", "action": "multi_search", "error": "Each search item must contain object `header`/`body` values"}
            lines.append(json.dumps(header))
            lines.append(json.dumps(body))

        if not lines:
            return {"status": "error", "action": "multi_search", "error": "No valid search requests were provided"}

        path = f"{self._base_url(credentials)}/{config.index}/_msearch" if config.index else f"{self._base_url(credentials)}/_msearch"
        return await self._request(
            "POST",
            path,
            credentials,
            content="\n".join(lines) + "\n",
            content_type="application/x-ndjson",
            action_name="multi_search",
        )

    async def _handle_index_document(self, config: ESIndexDocConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        document = _parse_json_obj(config.document)
        if document is None:
            return {"status": "error", "action": "index_document", "error": "`document` must be a JSON object"}
        if config.id:
            method = "PUT"
            url = f"{self._base_url(credentials)}/{config.index}/_doc/{config.id}"
        else:
            method = "POST"
            url = f"{self._base_url(credentials)}/{config.index}/_doc"
        return await self._request(
            method,
            url,
            credentials,
            json_body=document,
            params=_request_params(pipeline=config.pipeline, routing=config.routing, refresh=config.refresh),
            action_name="index_document",
        )

    async def _handle_create_document(self, config: ESCreateDocConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        document = _parse_json_obj(config.document)
        if document is None:
            return {"status": "error", "action": "create_document", "error": "`document` must be a JSON object"}
        return await self._request(
            "PUT",
            f"{self._base_url(credentials)}/{config.index}/_create/{config.id}",
            credentials,
            json_body=document,
            params=_request_params(pipeline=config.pipeline, routing=config.routing, refresh=config.refresh),
            action_name="create_document",
        )

    async def _handle_bulk_index(self, config: ESBulkIndexConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        documents = _parse_json_list(config.documents)
        if documents is None:
            return {"status": "error", "action": "bulk_index", "error": "`documents` must be a JSON array"}
        lines: List[str] = []
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            doc_copy = dict(doc)
            doc_id = doc_copy.pop("_id", None)
            action: Dict[str, Any] = {"_index": config.index}
            if doc_id is not None:
                action["_id"] = doc_id
            lines.append(json.dumps({"index": action}))
            lines.append(json.dumps(doc_copy))
        if not lines:
            return {"status": "error", "action": "bulk_index", "error": "No valid documents to index"}
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/_bulk",
            credentials,
            content="\n".join(lines) + "\n",
            content_type="application/x-ndjson",
            params=_request_params(pipeline=config.pipeline, routing=config.routing, refresh=config.refresh),
            action_name="bulk_index",
        )

    async def _handle_bulk_write(self, config: ESBulkWriteConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        actions = _parse_json_list(config.actions)
        if actions is None:
            return {"status": "error", "action": "bulk_write", "error": "`actions` must be a JSON array"}

        lines: List[str] = []
        for item in actions:
            if not isinstance(item, dict):
                return {"status": "error", "action": "bulk_write", "error": "Each action must be a JSON object"}
            action = item.get("action")
            if action not in {"index", "create", "delete", "update"}:
                return {"status": "error", "action": "bulk_write", "error": f"Unsupported bulk action: {action}"}

            meta: Dict[str, Any] = {}
            action_index = item.get("_index")
            if action_index:
                meta["_index"] = action_index
            elif not config.index:
                return {
                    "status": "error",
                    "action": "bulk_write",
                    "error": f"Bulk action `{action}` is missing `_index`, and no Default Index was provided",
                }
            if item.get("_id") is not None:
                meta["_id"] = item["_id"]
            if item.get("routing") is not None:
                meta["routing"] = item["routing"]

            if action == "delete" and "_id" not in meta:
                return {"status": "error", "action": "bulk_write", "error": "Bulk delete actions require `_id`"}
            if action == "create" and "_id" not in meta:
                return {"status": "error", "action": "bulk_write", "error": "Bulk create actions require `_id`"}

            lines.append(json.dumps({action: meta}))

            if action in {"index", "create"}:
                document = item.get("document")
                if not isinstance(document, dict):
                    return {
                        "status": "error",
                        "action": "bulk_write",
                        "error": f"Bulk `{action}` actions require a JSON object `document`",
                    }
                lines.append(json.dumps(document))
            elif action == "update":
                body: Dict[str, Any] = {}
                document = item.get("document", item.get("doc"))
                if document is not None:
                    if not isinstance(document, dict):
                        return {"status": "error", "action": "bulk_write", "error": "Bulk update `document` must be a JSON object"}
                    body["doc"] = document
                script = item.get("script")
                if script is not None:
                    if not isinstance(script, dict):
                        return {"status": "error", "action": "bulk_write", "error": "Bulk update `script` must be a JSON object"}
                    body["script"] = script
                upsert = item.get("upsert")
                if upsert is not None:
                    if not isinstance(upsert, dict):
                        return {"status": "error", "action": "bulk_write", "error": "Bulk update `upsert` must be a JSON object"}
                    body["upsert"] = upsert
                if item.get("doc_as_upsert") is not None:
                    body["doc_as_upsert"] = item["doc_as_upsert"]
                if item.get("scripted_upsert") is not None:
                    body["scripted_upsert"] = item["scripted_upsert"]
                if not body:
                    return {
                        "status": "error",
                        "action": "bulk_write",
                        "error": "Bulk update actions require at least one of `document`, `script`, or `upsert`",
                    }
                lines.append(json.dumps(body))

        if not lines:
            return {"status": "error", "action": "bulk_write", "error": "No valid bulk actions were provided"}

        path = f"{self._base_url(credentials)}/{config.index}/_bulk" if config.index else f"{self._base_url(credentials)}/_bulk"
        return await self._request(
            "POST",
            path,
            credentials,
            content="\n".join(lines) + "\n",
            content_type="application/x-ndjson",
            params=_request_params(pipeline=config.pipeline, routing=config.routing, refresh=config.refresh),
            action_name="bulk_write",
        )

    async def _handle_get_document(self, config: ESGetDocConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"{self._base_url(credentials)}/{config.index}/_doc/{config.id}",
            credentials,
            params=_request_params(routing=config.routing),
            action_name="get_document",
        )

    async def _handle_get_document_source(self, config: ESGetDocSourceConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"{self._base_url(credentials)}/{config.index}/_source/{config.id}",
            credentials,
            params=_request_params(routing=config.routing),
            action_name="get_document_source",
        )

    async def _handle_document_exists(self, config: ESDocumentExistsConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._head_request(
            f"{self._base_url(credentials)}/{config.index}/_doc/{config.id}",
            credentials,
            params=_request_params(routing=config.routing),
            action_name="document_exists",
        )

    async def _handle_multi_get(self, config: ESMultiGetConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        items = _parse_json_list(config.items)
        if items is None:
            return {"status": "error", "action": "multi_get", "error": "`items` must be a JSON array"}
        if config.index:
            if all(not isinstance(item, dict) for item in items):
                body: Dict[str, Any] = {"ids": items}
            else:
                docs = []
                for item in items:
                    if isinstance(item, dict):
                        docs.append(item)
                    else:
                        docs.append({"_id": item})
                body = {"docs": docs}
            url = f"{self._base_url(credentials)}/{config.index}/_mget"
        else:
            docs = [item for item in items if isinstance(item, dict)]
            if not docs:
                return {
                    "status": "error",
                    "action": "multi_get",
                    "error": "When Index is blank, `items` must be an array of document descriptors with _index and _id",
                }
            body = {"docs": docs}
            url = f"{self._base_url(credentials)}/_mget"
        return await self._request("POST", url, credentials, json_body=body, action_name="multi_get")

    async def _handle_update_document(self, config: ESUpdateDocConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "scripted_upsert": config.scripted_upsert,
            "doc_as_upsert": config.doc_as_upsert,
        }
        if config.document:
            document = _parse_json_obj(config.document)
            if document is None:
                return {"status": "error", "action": "update_document", "error": "`document` must be a JSON object"}
            body["doc"] = document
        if config.script:
            script = _parse_json_obj(config.script)
            if script is None:
                return {"status": "error", "action": "update_document", "error": "`script` must be a JSON object"}
            body["script"] = script
        if config.upsert:
            upsert = _parse_json_obj(config.upsert)
            if upsert is None:
                return {"status": "error", "action": "update_document", "error": "`upsert` must be a JSON object"}
            body["upsert"] = upsert
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/{config.index}/_update/{config.id}",
            credentials,
            json_body=body,
            params=_request_params(
                routing=config.routing,
                refresh=config.refresh,
                retry_on_conflict=config.retry_on_conflict,
            ),
            action_name="update_document",
        )

    async def _handle_delete_document(self, config: ESDeleteDocConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "DELETE",
            f"{self._base_url(credentials)}/{config.index}/_doc/{config.id}",
            credentials,
            params=_request_params(routing=config.routing, refresh=config.refresh),
            action_name="delete_document",
        )

    async def _handle_delete_by_query(self, config: ESDeleteByQueryConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        query = _parse_json_obj(config.query)
        if query is None:
            return {"status": "error", "action": "delete_by_query", "error": "`query` must be a JSON object"}
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/{config.index}/_delete_by_query",
            credentials,
            json_body={"query": query},
            params=_request_params(
                conflicts=config.conflicts,
                refresh=config.refresh,
                wait_for_completion=config.wait_for_completion,
                requests_per_second=config.requests_per_second,
            ),
            action_name="delete_by_query",
        )

    async def _handle_update_by_query(self, config: ESUpdateByQueryConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        query = _parse_json_obj(config.query)
        script = _parse_json_obj(config.script)
        if query is None:
            return {"status": "error", "action": "update_by_query", "error": "`query` must be a JSON object"}
        if script is None:
            return {"status": "error", "action": "update_by_query", "error": "`script` must be a JSON object"}
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/{config.index}/_update_by_query",
            credentials,
            json_body={"query": query, "script": script},
            params=_request_params(
                conflicts=config.conflicts,
                refresh=config.refresh,
                wait_for_completion=config.wait_for_completion,
                requests_per_second=config.requests_per_second,
            ),
            action_name="update_by_query",
        )

    async def _handle_reindex_documents(self, config: ESReindexConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "source": {"index": config.source_index},
            "dest": {"index": config.dest_index},
            "conflicts": config.conflicts,
        }
        if config.query:
            query = _parse_json_obj(config.query)
            if query is None:
                return {"status": "error", "action": "reindex_documents", "error": "`query` must be a JSON object"}
            body["source"]["query"] = query
        if config.script:
            script = _parse_json_obj(config.script)
            if script is None:
                return {"status": "error", "action": "reindex_documents", "error": "`script` must be a JSON object"}
            body["script"] = script
        if config.max_docs is not None:
            body["max_docs"] = config.max_docs
        if config.dest_pipeline:
            body["dest"]["pipeline"] = config.dest_pipeline
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/_reindex",
            credentials,
            json_body=body,
            params=_request_params(
                refresh=config.refresh,
                wait_for_completion=config.wait_for_completion,
            ),
            action_name="reindex_documents",
        )

    async def _handle_list_indices(self, config: ESListIndicesConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        result = await self._request(
            "GET",
            f"{self._base_url(credentials)}/_resolve/index/*",
            credentials,
            params={
                "expand_wildcards": "open,closed",
                "ignore_unavailable": "true",
                "allow_no_indices": "true",
            },
            action_name="list_indices",
        )
        if result.get("status") == "success":
            result["data"] = self._normalize_resolved_indices(result.get("data") or {})
        return result

    async def _handle_index_exists(self, config: ESIndexExistsConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._head_request(
            f"{self._base_url(credentials)}/{config.index}",
            credentials,
            params=None,
            action_name="index_exists",
        )

    async def _handle_get_index(self, config: ESGetIndexConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"{self._base_url(credentials)}/{config.index}",
            credentials,
            params=_request_params(include_defaults=config.include_defaults, flat_settings=config.flat_settings),
            action_name="get_index",
        )

    async def _handle_create_index(self, config: ESCreateIndexConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        mappings = _parse_json_obj(config.mappings)
        if mappings is None:
            return {"status": "error", "action": "create_index", "error": "`mappings` must be a JSON object"}
        body: Dict[str, Any] = {"mappings": mappings}
        if config.settings:
            settings = _parse_json_obj(config.settings)
            if settings is None:
                return {"status": "error", "action": "create_index", "error": "`settings` must be a JSON object"}
            body["settings"] = settings
        if config.aliases:
            aliases = _parse_json_obj(config.aliases)
            if aliases is None:
                return {"status": "error", "action": "create_index", "error": "`aliases` must be a JSON object"}
            body["aliases"] = aliases
        return await self._request(
            "PUT",
            f"{self._base_url(credentials)}/{config.index}",
            credentials,
            json_body=body,
            action_name="create_index",
        )

    async def _handle_delete_index(self, config: ESDeleteIndexConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "DELETE",
            f"{self._base_url(credentials)}/{config.index}",
            credentials,
            action_name="delete_index",
        )

    async def _handle_refresh_index(self, config: ESRefreshIndexConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/{config.index}/_refresh",
            credentials,
            action_name="refresh_index",
        )

    async def _handle_get_mapping(self, config: ESGetMappingConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"{self._base_url(credentials)}/{config.index}/_mapping",
            credentials,
            action_name="get_mapping",
        )

    async def _handle_update_mapping(self, config: ESUpdateMappingConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        mappings = _parse_json_obj(config.mappings)
        if mappings is None:
            return {"status": "error", "action": "update_mapping", "error": "`mappings` must be a JSON object"}
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/{config.index}/_mapping",
            credentials,
            json_body=mappings,
            action_name="update_mapping",
        )

    async def _handle_get_settings(self, config: ESGetSettingsConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"{self._base_url(credentials)}/{config.index}/_settings",
            credentials,
            params=_request_params(include_defaults=config.include_defaults, flat_settings=config.flat_settings),
            action_name="get_settings",
        )

    async def _handle_update_settings(self, config: ESUpdateSettingsConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        settings = _parse_json_obj(config.settings)
        if settings is None:
            return {"status": "error", "action": "update_settings", "error": "`settings` must be a JSON object"}
        return await self._request(
            "PUT",
            f"{self._base_url(credentials)}/{config.index}/_settings",
            credentials,
            json_body=settings,
            params=_request_params(preserve_existing=config.preserve_existing),
            action_name="update_settings",
        )

    async def _handle_list_aliases(self, config: ESListAliasesConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        suffix = f"/_alias/{config.name}" if config.name else "/_alias"
        return await self._request(
            "GET",
            f"{self._base_url(credentials)}/{config.index}{suffix}",
            credentials,
            action_name="list_aliases",
        )

    async def _handle_alias_exists(self, config: ESAliasExistsConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        if config.index:
            url = f"{self._base_url(credentials)}/{config.index}/_alias/{config.name}"
        else:
            url = f"{self._base_url(credentials)}/_alias/{config.name}"
        return await self._head_request(url, credentials, params=None, action_name="alias_exists")

    async def _handle_update_aliases(self, config: ESUpdateAliasesConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        actions = _parse_json_list(config.actions)
        if actions is None:
            return {"status": "error", "action": "update_aliases", "error": "`actions` must be a JSON array"}
        return await self._request(
            "POST",
            f"{self._base_url(credentials)}/_aliases",
            credentials,
            json_body={"actions": actions},
            action_name="update_aliases",
        )

    async def _handle_get_index_stats(self, config: ESGetIndexStatsConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        metric_path = ""
        metrics = _csv_fields(config.metrics)
        if metrics:
            metric_path = "/" + ",".join(metrics)
        return await self._request(
            "GET",
            f"{self._base_url(credentials)}/{config.index}/_stats{metric_path}",
            credentials,
            action_name="get_index_stats",
        )

    async def _handle_upload_and_index(self, config: ESUploadIndexConfig, credentials: ElasticsearchCredential) -> Dict[str, Any]:
        records, info = await ingest_document(
            self,
            config.document,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            id_prefix=config.id_prefix,
        )
        if not records:
            return {"status": "error", "action": "upload_and_index", "error": "No text could be extracted from the document"}

        lines: List[str] = []
        for record in records:
            lines.append(json.dumps({"index": {"_index": config.index, "_id": record["id"]}}))
            lines.append(
                json.dumps(
                    {
                        config.vector_field: record["values"],
                        config.text_field: record["metadata"]["text"],
                        "source": record["metadata"]["source"],
                        "chunk_index": record["metadata"]["chunk_index"],
                    }
                )
            )

        result = await self._request(
            "POST",
            f"{self._base_url(credentials)}/_bulk",
            credentials,
            content="\n".join(lines) + "\n",
            content_type="application/x-ndjson",
            params=_request_params(pipeline=config.pipeline, refresh=config.refresh),
            action_name="upload_and_index",
        )
        if result.get("status") == "success":
            result["data"] = {
                "chunks_indexed": len(records),
                "source": info.get("filename"),
                "raw": result.get("data"),
            }
        return result
