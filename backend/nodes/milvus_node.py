"""
Milvus / Zilliz Cloud vector database automation node.

Provides workflow integration via the Milvus REST v2 API (Milvus 2.4+ / Zilliz
Cloud). All v2 endpoints are POST. Milvus returns {"code": 0, "data": ...} on
success and a non-zero ``code`` with a ``message`` on logical errors (often
still HTTP 200) — those are promoted to error results.

Authentication: Bearer token + cluster URI on the credential (Zilliz Cloud API
key, or a Milvus "user:password" token — both work with Authorization: Bearer).
Docs: https://milvus.io/api-reference/restful/v2.5.x/About.md
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

_COLLECTION_FIELD_EXTRA = {
    "x-resource-type": "milvus_collection",
    "x-dynamic-options": {
        "field_name": "collection",
        "placeholder": "Select a collection...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type the collection name",
    }
}

_INDEX_NAME_FIELD_EXTRA = {
    "x-resource-type": "milvus_index",
    "x-dynamic-options": {
        "field_name": "index_name",
        "placeholder": "Select an index...",
        "searchable": True,
        "allow_custom": True,
        "depends_on": "collection",
        "custom_placeholder": "Or type index name",
    }
}

_PARTITION_FIELD_EXTRA = {
    "x-resource-type": "milvus_partition",
    "x-dynamic-options": {
        "field_name": "partition_name",
        "placeholder": "Select a partition...",
        "searchable": True,
        "allow_custom": True,
        "depends_on": "collection",
        "custom_placeholder": "Or type partition name",
    }
}

_ALIAS_FIELD_EXTRA = {
    "x-resource-type": "milvus_alias",
    "x-dynamic-options": {
        "field_name": "alias_name",
        "placeholder": "Select an alias...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type alias name",
    }
}

_DB_NAME_FIELD_EXTRA = {
    "x-resource-type": "milvus_database",
    "x-dynamic-options": {
        "field_name": "db_name",
        "placeholder": "Select a database...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type database name",
    }
}

# ============================================================================
# Credential Schema
# ============================================================================


class MilvusCredential(BaseModel):
    """Bearer token + cluster URI credential for Milvus / Zilliz Cloud."""

    credential_type: Literal["milvus_token"] = Field(
        "milvus_token", json_schema_extra={"ui:hidden": True}
    )
    uri: str = Field(
        ...,
        title="Cluster URI",
        description="Your Milvus/Zilliz endpoint, e.g. https://in03-xxxx.api.gcp-us-west1.zillizcloud.com",
    )
    token: str = Field(
        ...,
        title="Token",
        description="Zilliz API key, or a Milvus 'user:password' token",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://cloud.zilliz.com/"}
    )


# ============================================================================
# Operation Configs — Entities
# ============================================================================


class MilvusSearchConfig(BaseModel):
    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Search",
            "x-keywords": ["similarity search", "nearest neighbors", "vector search", "rag", "ann"],
        },
        title="Search",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    vector: str = Field(
        ..., title="Query Vector",
        description="Embedding to search with — a JSON array of numbers",
        json_schema_extra={"ui:widget": "textarea"},
    )
    anns_field: Optional[str] = Field(None, title="Vector Field",
        description="Name of the vector field to search (omit for single-vector collections)")
    limit: int = Field(10, title="Limit", description="Number of matches to return (max 1024)")
    filter: Optional[str] = Field(None, title="Filter",
        description='Optional boolean expression, e.g. color == "red"')
    output_fields: Optional[str] = Field(None, title="Output Fields",
        description="Fields to return, comma-separated")
    partition_names: Optional[str] = Field(None, title="Partition Names",
        description="Comma-separated partition names to search within")
    db_name: Optional[str] = Field(None, title="Database Name",
        description="Database name (for multi-DB Milvus; leave blank for default)")


class MilvusHybridSearchConfig(BaseModel):
    operation: Literal["hybrid_search"] = Field(
        "hybrid_search",
        json_schema_extra={
            "const": "hybrid_search", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Hybrid Search",
            "x-keywords": ["multi-vector", "hybrid", "rerank", "sparse dense"],
        },
        title="Hybrid Search",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    requests: str = Field(
        ..., title="Search Requests",
        description='JSON array of AnnSearchRequest objects, each with field, data, limit, and optional params/filter',
        json_schema_extra={"ui:widget": "textarea"},
    )
    rerank: str = Field(
        '{"strategy": "rrf", "params": {"k": 60}}',
        title="Rerank Strategy",
        description='Reranker config, e.g. {"strategy": "rrf", "params": {"k": 60}} or {"strategy": "weighted", "weights": [0.4, 0.6]}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    limit: int = Field(10, title="Limit", description="Number of final results")
    output_fields: Optional[str] = Field(None, title="Output Fields",
        description="Fields to return, comma-separated")
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusGetConfig(BaseModel):
    operation: Literal["get"] = Field(
        "get",
        json_schema_extra={
            "const": "get", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Get Entities",
            "x-keywords": ["fetch by id", "get by primary key"],
        },
        title="Get Entities",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    ids: str = Field(..., title="IDs",
        description="Comma-separated primary key values to fetch, e.g. 1,2,3 or id1,id2")
    output_fields: Optional[str] = Field(None, title="Output Fields",
        description="Fields to return, comma-separated")
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusInsertConfig(BaseModel):
    operation: Literal["insert"] = Field(
        "insert",
        json_schema_extra={
            "const": "insert", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Insert",
            "x-keywords": ["add", "index", "store", "write"],
        },
        title="Insert",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    data: str = Field(
        ..., title="Data",
        description='JSON array of entities, e.g. [{"id": 1, "vector": [0.1, ...], "color": "red"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    partition_name: Optional[str] = Field(None, title="Partition Name",
        json_schema_extra=_PARTITION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusUpsertConfig(BaseModel):
    operation: Literal["upsert"] = Field(
        "upsert",
        json_schema_extra={
            "const": "upsert", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Upsert",
            "x-keywords": ["insert or update", "overwrite", "store"],
        },
        title="Upsert",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    data: str = Field(
        ..., title="Data",
        description='JSON array of entities to upsert',
        json_schema_extra={"ui:widget": "textarea"},
    )
    partition_name: Optional[str] = Field(None, title="Partition Name",
        json_schema_extra=_PARTITION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusQueryConfig(BaseModel):
    operation: Literal["query"] = Field(
        "query",
        json_schema_extra={
            "const": "query", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Query",
            "x-keywords": ["filter", "scalar query", "fetch by expression"],
        },
        title="Query",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(..., title="Filter",
        description='Boolean expression, e.g. id in [1, 2, 3]')
    output_fields: Optional[str] = Field(None, title="Output Fields",
        description="Fields to return, comma-separated")
    limit: Optional[int] = Field(None, title="Limit", description="Max entities to return")
    offset: Optional[int] = Field(None, title="Offset", description="Pagination offset")
    partition_names: Optional[str] = Field(None, title="Partition Names",
        description="Comma-separated partition names to query")
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDeleteConfig(BaseModel):
    operation: Literal["delete"] = Field(
        "delete",
        json_schema_extra={
            "const": "delete", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Delete Entities",
            "x-keywords": ["remove", "purge", "clear"],
        },
        title="Delete Entities",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(..., title="Filter",
        description='Boolean expression selecting rows to delete, e.g. id in [1, 2]')
    partition_name: Optional[str] = Field(None, title="Partition Name",
        json_schema_extra=_PARTITION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


# ============================================================================
# Operation Configs — Collections
# ============================================================================


class MilvusListCollectionsConfig(BaseModel):
    operation: Literal["list_collections"] = Field(
        "list_collections",
        json_schema_extra={
            "const": "list_collections", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "List Collections",
            "x-keywords": ["list", "show collections"],
        },
        title="List Collections",
    )
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusCreateCollectionConfig(BaseModel):
    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection", "x-creates-resource": True, "x-resource-type": "milvus_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Create Collection",
            "x-keywords": ["new collection", "provision", "setup"],
        },
        title="Create Collection",
    )
    name: str = Field(..., title="Name", description="Collection name")
    dimension: str = Field(
        "1536", title="Dimension", description="Vector dimensionality",
        json_schema_extra={
            "enum": ["64", "128", "256", "384", "512", "768", "1024", "1536", "2048", "3072"],
            "enumNames": [
                "64", "128", "256",
                "384 — all-MiniLM-L6-v2",
                "512",
                "768 — BERT base, many sentence-transformers",
                "1024 — Cohere embed-v3 (English)",
                "1536 — OpenAI text-embedding-3-small / ada-002 ★",
                "2048",
                "3072 — OpenAI text-embedding-3-large",
            ],
            "x-enum-searchable": True,
        },
    )
    metric_type: str = Field(
        "COSINE", title="Metric Type",
        json_schema_extra={"enum": ["COSINE", "L2", "IP"], "x-enum-searchable": True},
    )
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDescribeCollectionConfig(BaseModel):
    operation: Literal["describe_collection"] = Field(
        "describe_collection",
        json_schema_extra={
            "const": "describe_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Describe Collection",
            "x-keywords": ["schema", "collection info", "fields"],
        },
        title="Describe Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDropCollectionConfig(BaseModel):
    operation: Literal["drop_collection"] = Field(
        "drop_collection",
        json_schema_extra={
            "const": "drop_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Drop Collection",
            "x-keywords": ["delete collection", "remove collection"],
        },
        title="Drop Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusRenameCollectionConfig(BaseModel):
    operation: Literal["rename_collection"] = Field(
        "rename_collection",
        json_schema_extra={
            "const": "rename_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Rename Collection",
            "x-keywords": ["rename", "move collection"],
        },
        title="Rename Collection",
    )
    collection: str = Field(..., title="Collection Name", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    new_name: str = Field(..., title="New Name")
    db_name: Optional[str] = Field(None, title="Database Name")
    new_db_name: Optional[str] = Field(None, title="New Database Name",
        description="Move the collection to a different database (optional)")


class MilvusLoadCollectionConfig(BaseModel):
    operation: Literal["load_collection"] = Field(
        "load_collection",
        json_schema_extra={
            "const": "load_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Load Collection",
            "x-keywords": ["load into memory", "ready"],
        },
        title="Load Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusReleaseCollectionConfig(BaseModel):
    operation: Literal["release_collection"] = Field(
        "release_collection",
        json_schema_extra={
            "const": "release_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Release Collection",
            "x-keywords": ["unload", "free memory"],
        },
        title="Release Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusGetLoadStateConfig(BaseModel):
    operation: Literal["get_load_state"] = Field(
        "get_load_state",
        json_schema_extra={
            "const": "get_load_state", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Get Load State",
            "x-keywords": ["load status", "ready check", "is loaded"],
        },
        title="Get Load State",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusGetCollectionStatsConfig(BaseModel):
    operation: Literal["get_collection_stats"] = Field(
        "get_collection_stats",
        json_schema_extra={
            "const": "get_collection_stats", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Get Collection Stats",
            "x-keywords": ["row count", "entity count", "statistics"],
        },
        title="Get Collection Stats",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusFlushConfig(BaseModel):
    operation: Literal["flush"] = Field(
        "flush",
        json_schema_extra={
            "const": "flush", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Flush Collection",
            "x-keywords": ["flush", "persist", "durability"],
        },
        title="Flush Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusCompactConfig(BaseModel):
    operation: Literal["compact"] = Field(
        "compact",
        json_schema_extra={
            "const": "compact", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Compact Collection",
            "x-keywords": ["compact", "optimize", "defrag"],
        },
        title="Compact Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusHasCollectionConfig(BaseModel):
    operation: Literal["has_collection"] = Field(
        "has_collection",
        json_schema_extra={
            "const": "has_collection", "ui:hidden": True,
            "x-category": "Collection", "x-is-trigger": False,
            "x-display-name": "Has Collection",
            "x-keywords": ["check collection exists", "collection exists"],
        },
        title="Has Collection",
    )
    collection: str = Field(..., title="Collection Name",
        description="Collection name to check for existence")
    db_name: Optional[str] = Field(None, title="Database Name")


# ============================================================================
# Operation Configs — Indexes
# ============================================================================


class MilvusListIndexesConfig(BaseModel):
    operation: Literal["list_indexes"] = Field(
        "list_indexes",
        json_schema_extra={
            "const": "list_indexes", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "List Indexes",
            "x-keywords": ["list indexes", "show indexes"],
        },
        title="List Indexes",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusCreateIndexConfig(BaseModel):
    operation: Literal["create_index"] = Field(
        "create_index",
        json_schema_extra={
            "const": "create_index", "x-creates-resource": True, "x-resource-type": "milvus_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Create Index",
            "x-keywords": ["build index", "hnsw", "ivf"],
        },
        title="Create Index",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    field_name: str = Field(..., title="Field Name", description="The field to create the index on")
    index_name: Optional[str] = Field(None, title="Index Name",
        description="Optional custom name for the index (defaults to field name)")
    index_type: str = Field(
        "AUTOINDEX", title="Index Type",
        json_schema_extra={
            "enum": ["AUTOINDEX", "FLAT", "IVF_FLAT", "IVF_SQ8", "IVF_PQ", "HNSW", "SCANN",
                     "BIN_FLAT", "BIN_IVF_FLAT", "SPARSE_INVERTED_INDEX"],
            "x-enum-searchable": True,
        },
    )
    metric_type: str = Field(
        "COSINE", title="Metric Type",
        json_schema_extra={"enum": ["COSINE", "L2", "IP", "HAMMING", "JACCARD"], "x-enum-searchable": True},
    )
    params: Optional[str] = Field(None, title="Index Params",
        description='Optional JSON object of index-specific params, e.g. {"M": 16, "efConstruction": 200}',
        json_schema_extra={"ui:widget": "textarea"})
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDropIndexConfig(BaseModel):
    operation: Literal["drop_index"] = Field(
        "drop_index",
        json_schema_extra={
            "const": "drop_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Drop Index",
            "x-keywords": ["delete index", "remove index"],
        },
        title="Drop Index",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field(..., title="Index Name", json_schema_extra=_INDEX_NAME_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDescribeIndexConfig(BaseModel):
    operation: Literal["describe_index"] = Field(
        "describe_index",
        json_schema_extra={
            "const": "describe_index", "ui:hidden": True,
            "x-category": "Index", "x-is-trigger": False,
            "x-display-name": "Describe Index",
            "x-keywords": ["index info", "index details"],
        },
        title="Describe Index",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field(..., title="Index Name", json_schema_extra=_INDEX_NAME_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


# ============================================================================
# Operation Configs — Partitions
# ============================================================================


class MilvusListPartitionsConfig(BaseModel):
    operation: Literal["list_partitions"] = Field(
        "list_partitions",
        json_schema_extra={
            "const": "list_partitions", "ui:hidden": True,
            "x-category": "Partition", "x-is-trigger": False,
            "x-display-name": "List Partitions",
        },
        title="List Partitions",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusCreatePartitionConfig(BaseModel):
    operation: Literal["create_partition"] = Field(
        "create_partition",
        json_schema_extra={
            "const": "create_partition", "x-creates-resource": True, "x-resource-type": "milvus_partition", "ui:hidden": True,
            "x-category": "Partition", "x-is-trigger": False,
            "x-display-name": "Create Partition",
        },
        title="Create Partition",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    partition_name: str = Field(..., title="Partition Name")
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDropPartitionConfig(BaseModel):
    operation: Literal["drop_partition"] = Field(
        "drop_partition",
        json_schema_extra={
            "const": "drop_partition", "ui:hidden": True,
            "x-category": "Partition", "x-is-trigger": False,
            "x-display-name": "Drop Partition",
        },
        title="Drop Partition",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    partition_name: str = Field(..., title="Partition Name", json_schema_extra=_PARTITION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusHasPartitionConfig(BaseModel):
    operation: Literal["has_partition"] = Field(
        "has_partition",
        json_schema_extra={
            "const": "has_partition", "ui:hidden": True,
            "x-category": "Partition", "x-is-trigger": False,
            "x-display-name": "Has Partition",
            "x-keywords": ["check partition exists"],
        },
        title="Has Partition",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    partition_name: str = Field(..., title="Partition Name", json_schema_extra=_PARTITION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


# ============================================================================
# Operation Configs — Aliases
# ============================================================================


class MilvusListAliasesConfig(BaseModel):
    operation: Literal["list_aliases"] = Field(
        "list_aliases",
        json_schema_extra={
            "const": "list_aliases", "ui:hidden": True,
            "x-category": "Alias", "x-is-trigger": False,
            "x-display-name": "List Aliases",
        },
        title="List Aliases",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusCreateAliasConfig(BaseModel):
    operation: Literal["create_alias"] = Field(
        "create_alias",
        json_schema_extra={
            "const": "create_alias", "x-creates-resource": True, "x-resource-type": "milvus_alias", "ui:hidden": True,
            "x-category": "Alias", "x-is-trigger": False,
            "x-display-name": "Create Alias",
            "x-keywords": ["alias", "collection alias", "zero downtime swap"],
        },
        title="Create Alias",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    alias_name: str = Field(..., title="Alias Name")
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDropAliasConfig(BaseModel):
    operation: Literal["drop_alias"] = Field(
        "drop_alias",
        json_schema_extra={
            "const": "drop_alias", "ui:hidden": True,
            "x-category": "Alias", "x-is-trigger": False,
            "x-display-name": "Drop Alias",
        },
        title="Drop Alias",
    )
    alias_name: str = Field(..., title="Alias Name", json_schema_extra=_ALIAS_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusDescribeAliasConfig(BaseModel):
    operation: Literal["describe_alias"] = Field(
        "describe_alias",
        json_schema_extra={
            "const": "describe_alias", "ui:hidden": True,
            "x-category": "Alias", "x-is-trigger": False,
            "x-display-name": "Describe Alias",
        },
        title="Describe Alias",
    )
    alias_name: str = Field(..., title="Alias Name", json_schema_extra=_ALIAS_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


class MilvusAlterAliasConfig(BaseModel):
    operation: Literal["alter_alias"] = Field(
        "alter_alias",
        json_schema_extra={
            "const": "alter_alias", "ui:hidden": True,
            "x-category": "Alias", "x-is-trigger": False,
            "x-display-name": "Alter Alias",
            "x-keywords": ["reassign alias", "swap collection alias"],
        },
        title="Alter Alias",
    )
    collection: str = Field(..., title="New Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA,
        description="The collection the alias should point to after the update")
    alias_name: str = Field(..., title="Alias Name", json_schema_extra=_ALIAS_FIELD_EXTRA)
    db_name: Optional[str] = Field(None, title="Database Name")


# ============================================================================
# Operation Configs — Databases
# ============================================================================


class MilvusListDatabasesConfig(BaseModel):
    operation: Literal["list_databases"] = Field(
        "list_databases",
        json_schema_extra={
            "const": "list_databases", "ui:hidden": True,
            "x-category": "Database", "x-is-trigger": False,
            "x-display-name": "List Databases",
        },
        title="List Databases",
    )


class MilvusCreateDatabaseConfig(BaseModel):
    operation: Literal["create_database"] = Field(
        "create_database",
        json_schema_extra={
            "const": "create_database", "x-creates-resource": True, "x-resource-type": "milvus_database", "ui:hidden": True,
            "x-category": "Database", "x-is-trigger": False,
            "x-display-name": "Create Database",
        },
        title="Create Database",
    )
    db_name: str = Field(..., title="Database Name")


class MilvusDropDatabaseConfig(BaseModel):
    operation: Literal["drop_database"] = Field(
        "drop_database",
        json_schema_extra={
            "const": "drop_database", "ui:hidden": True,
            "x-category": "Database", "x-is-trigger": False,
            "x-display-name": "Drop Database",
        },
        title="Drop Database",
    )
    db_name: str = Field(..., title="Database Name", json_schema_extra=_DB_NAME_FIELD_EXTRA)


class MilvusDescribeDatabaseConfig(BaseModel):
    operation: Literal["describe_database"] = Field(
        "describe_database",
        json_schema_extra={
            "const": "describe_database", "ui:hidden": True,
            "x-category": "Database", "x-is-trigger": False,
            "x-display-name": "Describe Database",
        },
        title="Describe Database",
    )
    db_name: str = Field(..., title="Database Name", json_schema_extra=_DB_NAME_FIELD_EXTRA)


# ============================================================================
# Operation Configs — Document ingest
# ============================================================================


class MilvusUploadIndexConfig(BaseModel):
    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index", "ui:hidden": True,
            "x-category": "Entities", "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file", "add pdf"],
        },
        title="Upload & Index Document",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    document: str = Field(
        ..., title="Document",
        description="Upload a PDF/DOCX/TXT/MD/CSV file (or paste a URL / reference an upstream file). It's chunked, embedded with text-embedding-3-small, and upserted. source/chunk_index ride as dynamic fields.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": DOCUMENT_ACCEPT},
    )
    pk_field: str = Field("id", title="Primary Key Field",
        description="The collection's Int64 primary key field")
    vector_field: str = Field("vector", title="Vector Field",
        description="The collection's vector field name")
    text_field: str = Field("text", title="Text Field",
        description="Field to store the chunk text")
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap",
        description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(None, title="ID Prefix",
        description="Optional prefix for chunk IDs (defaults to the filename)")
    db_name: Optional[str] = Field(None, title="Database Name")


# ============================================================================
# Discriminated Union (36 operations)
# ============================================================================


MilvusConfig = Annotated[
    Union[
        # Entities
        MilvusSearchConfig,
        MilvusHybridSearchConfig,
        MilvusGetConfig,
        MilvusInsertConfig,
        MilvusUpsertConfig,
        MilvusQueryConfig,
        MilvusDeleteConfig,
        MilvusUploadIndexConfig,
        # Collections
        MilvusListCollectionsConfig,
        MilvusCreateCollectionConfig,
        MilvusDescribeCollectionConfig,
        MilvusDropCollectionConfig,
        MilvusRenameCollectionConfig,
        MilvusLoadCollectionConfig,
        MilvusReleaseCollectionConfig,
        MilvusGetLoadStateConfig,
        MilvusGetCollectionStatsConfig,
        MilvusFlushConfig,
        MilvusCompactConfig,
        MilvusHasCollectionConfig,
        # Indexes
        MilvusListIndexesConfig,
        MilvusCreateIndexConfig,
        MilvusDropIndexConfig,
        MilvusDescribeIndexConfig,
        # Partitions
        MilvusListPartitionsConfig,
        MilvusCreatePartitionConfig,
        MilvusDropPartitionConfig,
        MilvusHasPartitionConfig,
        # Aliases
        MilvusListAliasesConfig,
        MilvusCreateAliasConfig,
        MilvusDropAliasConfig,
        MilvusDescribeAliasConfig,
        MilvusAlterAliasConfig,
        # Databases
        MilvusListDatabasesConfig,
        MilvusCreateDatabaseConfig,
        MilvusDropDatabaseConfig,
        MilvusDescribeDatabaseConfig,
    ],
    Discriminator("operation"),
]


class MilvusNodeConfig(NodeConfig[MilvusConfig, MilvusCredential]):
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


def _parse_json_obj(value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _output_fields(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    fields = [p.strip() for p in value.split(",") if p.strip()]
    return fields or None


def _split_csv(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _with_db(body: Dict[str, Any], db_name: Optional[str]) -> Dict[str, Any]:
    if db_name:
        body["dbName"] = db_name
    return body


# ============================================================================
# Node Implementation
# ============================================================================


class MilvusNode(WorkflowNode):
    """Milvus / Zilliz Cloud vector database automation node."""

    edit_examples = [
        "Search a Milvus collection for the entities most similar to a query embedding",
        "Insert document embeddings into a Milvus collection",
        "Query a Milvus collection with a boolean filter expression",
        "Delete entities matching a filter from a Milvus collection",
        "Create a new Milvus collection for a 1536-dimension embedding model",
        "Hybrid-search across two vector fields with RRF reranking",
    ]

    @classmethod
    def get_config_model(cls):
        return MilvusNodeConfig

    @staticmethod
    def _base_url(credential: MilvusCredential) -> str:
        return (credential.uri or "").rstrip("/")

    @staticmethod
    def _headers(credential: MilvusCredential) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {credential.token}",
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
        uri = (credential_data or {}).get("uri")
        token = (credential_data or {}).get("token")
        if not uri or not token:
            return []
        ctx = context or {}

        async def _list(endpoint: str, body: Dict[str, Any]) -> List[str]:
            try:
                async with guarded_async_client(timeout=20.0) as client:
                    resp = await client.post(
                        f"{uri.rstrip('/')}{endpoint}",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json=body,
                    )
            except httpx.HTTPError as e:
                logger.warning(f"[MilvusNode] load_field_options ({endpoint}): {e}")
                return []
            if resp.status_code >= 400:
                return []
            data = resp.json().get("data", []) or []
            return [d if isinstance(d, str) else d.get("name", "") for d in data if d]

        def _filter(names: List[str]) -> List[Dict[str, Any]]:
            return [
                {"value": n, "label": n} for n in names
                if isinstance(n, str) and n and (not search or search.lower() in n.lower())
            ]

        if field_name == "collection":
            return _filter(await _list("/v2/vectordb/collections/list", {}))

        if field_name == "index_name":
            collection = ctx.get("collection")
            if not collection:
                return []
            names = await _list("/v2/vectordb/indexes/list", {"collectionName": collection})
            return _filter(names)

        if field_name == "partition_name":
            collection = ctx.get("collection")
            if not collection:
                return []
            names = await _list("/v2/vectordb/partitions/list", {"collectionName": collection})
            return _filter(names)

        if field_name == "alias_name":
            # List all aliases globally (collectionName omitted → all aliases)
            try:
                async with guarded_async_client(timeout=20.0) as client:
                    resp = await client.post(
                        f"{uri.rstrip('/')}/v2/vectordb/aliases/list",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={},
                    )
            except httpx.HTTPError as e:
                logger.warning(f"[MilvusNode] load_field_options (aliases/list): {e}")
                return []
            if resp.status_code >= 400:
                return []
            data = resp.json().get("data", []) or []
            names = data if isinstance(data, list) else []
            return _filter(names)

        if field_name == "db_name":
            names = await _list("/v2/vectordb/databases/list", {})
            return _filter(names)

        return []

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, MilvusNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Milvus/Zilliz URI and token.")

        op_config = config.config
        handlers = {
            # Entities
            "search": self._handle_search,
            "hybrid_search": self._handle_hybrid_search,
            "get": self._handle_get,
            "insert": self._handle_insert,
            "upsert": self._handle_upsert,
            "query": self._handle_query,
            "delete": self._handle_delete,
            "upload_and_index": self._handle_upload_and_index,
            # Collections
            "list_collections": self._handle_list_collections,
            "create_collection": self._handle_create_collection,
            "describe_collection": self._handle_describe_collection,
            "drop_collection": self._handle_drop_collection,
            "rename_collection": self._handle_rename_collection,
            "load_collection": self._handle_load_collection,
            "release_collection": self._handle_release_collection,
            "get_load_state": self._handle_get_load_state,
            "get_collection_stats": self._handle_get_collection_stats,
            "flush": self._handle_flush,
            "compact": self._handle_compact,
            "has_collection": self._handle_has_collection,
            # Indexes
            "list_indexes": self._handle_list_indexes,
            "create_index": self._handle_create_index,
            "drop_index": self._handle_drop_index,
            "describe_index": self._handle_describe_index,
            # Partitions
            "list_partitions": self._handle_list_partitions,
            "create_partition": self._handle_create_partition,
            "drop_partition": self._handle_drop_partition,
            "has_partition": self._handle_has_partition,
            # Aliases
            "list_aliases": self._handle_list_aliases,
            "create_alias": self._handle_create_alias,
            "drop_alias": self._handle_drop_alias,
            "describe_alias": self._handle_describe_alias,
            "alter_alias": self._handle_alter_alias,
            # Databases
            "list_databases": self._handle_list_databases,
            "create_database": self._handle_create_database,
            "drop_database": self._handle_drop_database,
            "describe_database": self._handle_describe_database,
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

    async def _post(
        self, endpoint: str, credential: MilvusCredential, body: Dict[str, Any], action_name: str
    ) -> Dict[str, Any]:
        start_time = time.time()
        url = f"{self._base_url(credential)}{endpoint}"
        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.post(url, headers=self._headers(credential), json=body)
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
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        code = data.get("code") if isinstance(data, dict) else None
        if response.status_code >= 400 or (code is not None and code != 0):
            message = data.get("message", response.text) if isinstance(data, dict) else response.text
            logger.error(f"[MilvusNode] API error ({action_name}): {message}")
            return {
                "status": "error", "action": action_name,
                "error": message, "status_code": response.status_code,
                "code": code,
                "timing_ms": {"api_request": api_time},
            }

        return {
            "status": "success", "action": action_name,
            "data": data.get("data", data) if isinstance(data, dict) else data,
            "status_code": response.status_code,
            "timing_ms": {"api_request": api_time},
        }

    # =========================================================================
    # Entity handlers
    # =========================================================================

    async def _handle_search(self, config: MilvusSearchConfig, credentials) -> Dict[str, Any]:
        vector = _parse_json_list(config.vector)
        if vector is None:
            return {"status": "error", "action": "search", "error": "`vector` must be a JSON array of numbers"}
        body: Dict[str, Any] = {
            "collectionName": config.collection,
            "data": [vector],
            "limit": config.limit,
        }
        if config.anns_field:
            body["annsField"] = config.anns_field
        if config.filter:
            body["filter"] = config.filter
        output_fields = _output_fields(config.output_fields)
        if output_fields:
            body["outputFields"] = output_fields
        partition_names = _split_csv(config.partition_names)
        if partition_names:
            body["partitionNames"] = partition_names
        return await self._post("/v2/vectordb/entities/search", credentials, _with_db(body, config.db_name), "search")

    async def _handle_hybrid_search(self, config: MilvusHybridSearchConfig, credentials) -> Dict[str, Any]:
        requests = _parse_json_list(config.requests)
        if requests is None:
            return {"status": "error", "action": "hybrid_search", "error": "`requests` must be a JSON array"}
        rerank = _parse_json_obj(config.rerank)
        if rerank is None:
            return {"status": "error", "action": "hybrid_search", "error": "`rerank` must be a JSON object"}
        body: Dict[str, Any] = {
            "collectionName": config.collection,
            "search": requests,
            "rerank": rerank,
            "limit": config.limit,
        }
        output_fields = _output_fields(config.output_fields)
        if output_fields:
            body["outputFields"] = output_fields
        return await self._post("/v2/vectordb/entities/hybrid_search", credentials, _with_db(body, config.db_name), "hybrid_search")

    async def _handle_get(self, config: MilvusGetConfig, credentials) -> Dict[str, Any]:
        raw_ids = _split_csv(config.ids)
        if not raw_ids:
            return {"status": "error", "action": "get", "error": "`ids` must be a non-empty comma-separated list"}
        # Try numeric IDs first (Int64 PKs), fall back to strings
        ids: List[Any] = []
        for item in raw_ids:
            try:
                ids.append(int(item))
            except ValueError:
                ids.append(item)
        body: Dict[str, Any] = {"collectionName": config.collection, "id": ids}
        output_fields = _output_fields(config.output_fields)
        if output_fields:
            body["outputFields"] = output_fields
        return await self._post("/v2/vectordb/entities/get", credentials, _with_db(body, config.db_name), "get")

    async def _handle_insert(self, config: MilvusInsertConfig, credentials) -> Dict[str, Any]:
        data = _parse_json_list(config.data)
        if data is None:
            return {"status": "error", "action": "insert", "error": "`data` must be a JSON array of entities"}
        body: Dict[str, Any] = {"collectionName": config.collection, "data": data}
        if config.partition_name:
            body["partitionName"] = config.partition_name
        return await self._post("/v2/vectordb/entities/insert", credentials, _with_db(body, config.db_name), "insert")

    async def _handle_upsert(self, config: MilvusUpsertConfig, credentials) -> Dict[str, Any]:
        data = _parse_json_list(config.data)
        if data is None:
            return {"status": "error", "action": "upsert", "error": "`data` must be a JSON array of entities"}
        body: Dict[str, Any] = {"collectionName": config.collection, "data": data}
        if config.partition_name:
            body["partitionName"] = config.partition_name
        return await self._post("/v2/vectordb/entities/upsert", credentials, _with_db(body, config.db_name), "upsert")

    async def _handle_query(self, config: MilvusQueryConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"collectionName": config.collection, "filter": config.filter}
        output_fields = _output_fields(config.output_fields)
        if output_fields:
            body["outputFields"] = output_fields
        if config.limit is not None:
            body["limit"] = config.limit
        if config.offset is not None:
            body["offset"] = config.offset
        partition_names = _split_csv(config.partition_names)
        if partition_names:
            body["partitionNames"] = partition_names
        return await self._post("/v2/vectordb/entities/query", credentials, _with_db(body, config.db_name), "query")

    async def _handle_delete(self, config: MilvusDeleteConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"collectionName": config.collection, "filter": config.filter}
        if config.partition_name:
            body["partitionName"] = config.partition_name
        return await self._post("/v2/vectordb/entities/delete", credentials, _with_db(body, config.db_name), "delete")

    async def _handle_upload_and_index(self, config: MilvusUploadIndexConfig, credentials) -> Dict[str, Any]:
        records, info = await ingest_document(
            self, config.document,
            chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap,
            id_prefix=config.id_prefix,
        )
        if not records:
            return {"status": "error", "action": "upload_and_index", "error": "No text could be extracted from the document"}
        data = [
            {
                config.pk_field: int(r["id"].replace("-", "")[:15], 16),
                config.vector_field: r["values"],
                config.text_field: r["metadata"]["text"],
                "source": r["metadata"]["source"],
                "chunk_index": r["metadata"]["chunk_index"],
            }
            for r in records
        ]
        body: Dict[str, Any] = {"collectionName": config.collection, "data": data}
        result = await self._post("/v2/vectordb/entities/upsert", credentials, _with_db(body, config.db_name), "upload_and_index")
        if result.get("status") == "success":
            result["data"] = {"chunks_indexed": len(records), "source": info.get("filename"), "raw": result.get("data")}
        return result

    # =========================================================================
    # Collection handlers
    # =========================================================================

    async def _handle_list_collections(self, config: MilvusListCollectionsConfig, credentials) -> Dict[str, Any]:
        return await self._post("/v2/vectordb/collections/list", credentials, _with_db({}, config.db_name), "list_collections")

    async def _handle_create_collection(self, config: MilvusCreateCollectionConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "collectionName": config.name,
            "dimension": int(config.dimension),
            "metricType": config.metric_type,
        }
        return await self._post("/v2/vectordb/collections/create", credentials, _with_db(body, config.db_name), "create_collection")

    async def _handle_describe_collection(self, config: MilvusDescribeCollectionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/describe", credentials, _with_db(body, config.db_name), "describe_collection")

    async def _handle_drop_collection(self, config: MilvusDropCollectionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/drop", credentials, _with_db(body, config.db_name), "drop_collection")

    async def _handle_rename_collection(self, config: MilvusRenameCollectionConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "collectionName": config.collection,
            "newCollectionName": config.new_name,
        }
        if config.new_db_name:
            body["newDbName"] = config.new_db_name
        return await self._post("/v2/vectordb/collections/rename", credentials, _with_db(body, config.db_name), "rename_collection")

    async def _handle_load_collection(self, config: MilvusLoadCollectionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/load", credentials, _with_db(body, config.db_name), "load_collection")

    async def _handle_release_collection(self, config: MilvusReleaseCollectionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/release", credentials, _with_db(body, config.db_name), "release_collection")

    async def _handle_get_load_state(self, config: MilvusGetLoadStateConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/get_load_state", credentials, _with_db(body, config.db_name), "get_load_state")

    async def _handle_get_collection_stats(self, config: MilvusGetCollectionStatsConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/get_stats", credentials, _with_db(body, config.db_name), "get_collection_stats")

    async def _handle_flush(self, config: MilvusFlushConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/flush", credentials, _with_db(body, config.db_name), "flush")

    async def _handle_compact(self, config: MilvusCompactConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/compact", credentials, _with_db(body, config.db_name), "compact")

    async def _handle_has_collection(self, config: MilvusHasCollectionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/collections/has", credentials, _with_db(body, config.db_name), "has_collection")

    # =========================================================================
    # Index handlers
    # =========================================================================

    async def _handle_list_indexes(self, config: MilvusListIndexesConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/indexes/list", credentials, _with_db(body, config.db_name), "list_indexes")

    async def _handle_create_index(self, config: MilvusCreateIndexConfig, credentials) -> Dict[str, Any]:
        # Milvus REST v2 wraps index params in an indexParams array
        index_param: Dict[str, Any] = {
            "fieldName": config.field_name,
            "indexType": config.index_type,
            "metricType": config.metric_type,
        }
        if config.index_name:
            index_param["indexName"] = config.index_name
        params = _parse_json_obj(config.params)
        if params:
            index_param["params"] = params
        body = {"collectionName": config.collection, "indexParams": [index_param]}
        return await self._post("/v2/vectordb/indexes/create", credentials, _with_db(body, config.db_name), "create_index")

    async def _handle_drop_index(self, config: MilvusDropIndexConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection, "indexName": config.index_name}
        return await self._post("/v2/vectordb/indexes/drop", credentials, _with_db(body, config.db_name), "drop_index")

    async def _handle_describe_index(self, config: MilvusDescribeIndexConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection, "indexName": config.index_name}
        return await self._post("/v2/vectordb/indexes/describe", credentials, _with_db(body, config.db_name), "describe_index")

    # =========================================================================
    # Partition handlers
    # =========================================================================

    async def _handle_list_partitions(self, config: MilvusListPartitionsConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/partitions/list", credentials, _with_db(body, config.db_name), "list_partitions")

    async def _handle_create_partition(self, config: MilvusCreatePartitionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection, "partitionName": config.partition_name}
        return await self._post("/v2/vectordb/partitions/create", credentials, _with_db(body, config.db_name), "create_partition")

    async def _handle_drop_partition(self, config: MilvusDropPartitionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection, "partitionName": config.partition_name}
        return await self._post("/v2/vectordb/partitions/drop", credentials, _with_db(body, config.db_name), "drop_partition")

    async def _handle_has_partition(self, config: MilvusHasPartitionConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection, "partitionName": config.partition_name}
        return await self._post("/v2/vectordb/partitions/has", credentials, _with_db(body, config.db_name), "has_partition")

    # =========================================================================
    # Alias handlers
    # =========================================================================

    async def _handle_list_aliases(self, config: MilvusListAliasesConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection}
        return await self._post("/v2/vectordb/aliases/list", credentials, _with_db(body, config.db_name), "list_aliases")

    async def _handle_create_alias(self, config: MilvusCreateAliasConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection, "aliasName": config.alias_name}
        return await self._post("/v2/vectordb/aliases/create", credentials, _with_db(body, config.db_name), "create_alias")

    async def _handle_drop_alias(self, config: MilvusDropAliasConfig, credentials) -> Dict[str, Any]:
        body = {"aliasName": config.alias_name}
        return await self._post("/v2/vectordb/aliases/drop", credentials, _with_db(body, config.db_name), "drop_alias")

    async def _handle_describe_alias(self, config: MilvusDescribeAliasConfig, credentials) -> Dict[str, Any]:
        body = {"aliasName": config.alias_name}
        return await self._post("/v2/vectordb/aliases/describe", credentials, _with_db(body, config.db_name), "describe_alias")

    async def _handle_alter_alias(self, config: MilvusAlterAliasConfig, credentials) -> Dict[str, Any]:
        body = {"collectionName": config.collection, "aliasName": config.alias_name}
        return await self._post("/v2/vectordb/aliases/alter", credentials, _with_db(body, config.db_name), "alter_alias")

    # =========================================================================
    # Database handlers
    # =========================================================================

    async def _handle_list_databases(self, config: MilvusListDatabasesConfig, credentials) -> Dict[str, Any]:
        return await self._post("/v2/vectordb/databases/list", credentials, {}, "list_databases")

    async def _handle_create_database(self, config: MilvusCreateDatabaseConfig, credentials) -> Dict[str, Any]:
        return await self._post("/v2/vectordb/databases/create", credentials, {"dbName": config.db_name}, "create_database")

    async def _handle_drop_database(self, config: MilvusDropDatabaseConfig, credentials) -> Dict[str, Any]:
        return await self._post("/v2/vectordb/databases/drop", credentials, {"dbName": config.db_name}, "drop_database")

    async def _handle_describe_database(self, config: MilvusDescribeDatabaseConfig, credentials) -> Dict[str, Any]:
        return await self._post("/v2/vectordb/databases/describe", credentials, {"dbName": config.db_name}, "describe_database")
