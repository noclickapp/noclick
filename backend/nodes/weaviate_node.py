"""
Weaviate vector database automation node.

Provides workflow integration with Weaviate:
- Search (GraphQL): query (nearVector), query_text (nearText), hybrid_search (BM25+vector),
  generative_search (RAG — retrieve + LLM generate)
- Analytics (GraphQL): aggregate (count/mean/topOccurrences over a class)
- Objects (REST): insert, get, update (PATCH), delete, batch_delete
- Schema (REST): list_collections, create_collection, delete_collection

Authentication: API key as a Bearer token + cluster URL on the credential
(Weaviate Cloud or self-hosted). Optional per-request module headers let
Weaviate call vectorizer/generative APIs server-side:
  X-OpenAI-Api-Key, X-Cohere-Api-Key, X-HuggingFace-Api-Key,
  X-Anthropic-Api-Key, X-Google-Api-Key, X-Mistral-Api-Key
Docs: https://weaviate.io/developers/weaviate/api

Vector/hybrid search and generative search use Weaviate's GraphQL Get API;
aggregate uses GraphQL Aggregate; CRUD and schema use the REST API.
Where filters (JSON WhereFilter objects) are inlined as GraphQL argument syntax
(Weaviate v1.38+ does not expose WhereFilter as a named variable type).
Named vectors (multi-vector collections) are supported via the optional
target_vector field on all three search operations.
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
    "x-resource-type": "weaviate_collection",
    "x-dynamic-options": {
        "field_name": "collection",
        "placeholder": "Select a collection...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type the class name",
    }
}

# ============================================================================
# Credential Schema
# ============================================================================


class WeaviateCredential(BaseModel):
    """API key + cluster URL credential for Weaviate."""

    credential_type: Literal["weaviate_api_key"] = Field(
        "weaviate_api_key", json_schema_extra={"ui:hidden": True}
    )
    url: str = Field(
        ...,
        title="Cluster URL",
        description="Your Weaviate REST endpoint, e.g. https://my-cluster.weaviate.network",
    )
    api_key: Optional[str] = Field(
        None,
        title="API Key",
        description="Weaviate API key (required for Weaviate Cloud; optional for an unsecured instance)",
        json_schema_extra={"ui:widget": "password"},
    )
    openai_api_key: Optional[str] = Field(
        None,
        title="OpenAI API Key",
        description="Sent as X-OpenAI-Api-Key — required when your collection uses text2vec-openai or generative-openai",
        json_schema_extra={"ui:widget": "password"},
    )
    cohere_api_key: Optional[str] = Field(
        None,
        title="Cohere API Key",
        description="Sent as X-Cohere-Api-Key — required when your collection uses text2vec-cohere or generative-cohere",
        json_schema_extra={"ui:widget": "password"},
    )
    huggingface_api_key: Optional[str] = Field(
        None,
        title="HuggingFace API Key",
        description="Sent as X-HuggingFace-Api-Key — required when your collection uses text2vec-huggingface",
        json_schema_extra={"ui:widget": "password"},
    )
    anthropic_api_key: Optional[str] = Field(
        None,
        title="Anthropic API Key",
        description="Sent as X-Anthropic-Api-Key — required when your collection uses generative-anthropic",
        json_schema_extra={"ui:widget": "password"},
    )
    google_api_key: Optional[str] = Field(
        None,
        title="Google API Key",
        description="Sent as X-Google-Api-Key — required when your collection uses generative-google (Gemini/PaLM)",
        json_schema_extra={"ui:widget": "password"},
    )
    mistral_api_key: Optional[str] = Field(
        None,
        title="Mistral API Key",
        description="Sent as X-Mistral-Api-Key — required when your collection uses generative-mistral",
        json_schema_extra={"ui:widget": "password"},
    )
    weaviate_embedding_api_key: Optional[str] = Field(
        None,
        title="Weaviate Embeddings API Key",
        description="Sent as X-Weaviate-Api-Key — required when your collection uses text2vec-weaviate (Weaviate Embeddings / Engram). Get one at console.weaviate.cloud → Embeddings.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://console.weaviate.cloud/"}
    )


# ============================================================================
# Operation Configs
# ============================================================================


class WeaviateQueryConfig(BaseModel):
    """Vector similarity search (GraphQL nearVector)."""

    operation: Literal["query"] = Field(
        "query",
        json_schema_extra={
            "const": "query",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Query / Search",
            "x-keywords": ["search", "similarity search", "nearest neighbors", "vector search"],
        },
        title="Query / Search",
    )
    collection: str = Field(
        ..., title="Collection", description="Class to search", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    vector: str = Field(
        ...,
        title="Query Vector",
        description="Embedding to search with — a JSON array of numbers",
        json_schema_extra={"ui:widget": "textarea"},
    )
    properties: Optional[str] = Field(
        None,
        title="Return Properties",
        description="Object properties to return, comma-separated (e.g. title,content). id + distance are always included.",
    )
    limit: int = Field(10, title="Limit", description="Number of matches to return")
    where: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description='Weaviate WhereFilter JSON object, e.g. {"path":["category"],"operator":"Equal","valueText":"news"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_vector: Optional[str] = Field(
        None,
        title="Target Vector",
        description="Named vector to search (for multi-vector collections). Leave blank for the default vector.",
    )


class WeaviateQueryTextConfig(BaseModel):
    """Semantic search by text (GraphQL nearText — requires the class to have a
    text2vec vectorizer module)."""

    operation: Literal["query_text"] = Field(
        "query_text",
        json_schema_extra={
            "const": "query_text",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Query by Text",
            "x-keywords": ["search text", "semantic search", "rag", "retrieve documents", "ask"],
        },
        title="Query by Text",
    )
    collection: str = Field(
        ..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    text: str = Field(
        ...,
        title="Query Text",
        description="Text to search with — vectorised server-side by the class's module",
        json_schema_extra={"ui:widget": "textarea"},
    )
    properties: Optional[str] = Field(
        None,
        title="Return Properties",
        description="Object properties to return, comma-separated. id + distance always included.",
    )
    limit: int = Field(10, title="Limit", description="Number of matches to return")
    where: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description='Weaviate WhereFilter JSON object, e.g. {"path":["status"],"operator":"Equal","valueText":"published"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_vector: Optional[str] = Field(
        None,
        title="Target Vector",
        description="Named vector to search (for multi-vector collections). Leave blank for the default vector.",
    )


class WeaviateHybridSearchConfig(BaseModel):
    """Hybrid BM25 + vector search (GraphQL hybrid)."""

    operation: Literal["hybrid_search"] = Field(
        "hybrid_search",
        json_schema_extra={
            "const": "hybrid_search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Hybrid Search",
            "x-keywords": ["hybrid", "bm25", "keyword", "semantic", "rag", "rank fusion"],
        },
        title="Hybrid Search",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    query: str = Field(..., title="Query Text", description="Text query — combined BM25 + vector by Weaviate")
    alpha: float = Field(
        0.75,
        title="Alpha",
        description="Balance between BM25 (0) and vector search (1). Default 0.75 weights toward semantic.",
    )
    vector: Optional[str] = Field(
        None,
        title="Query Vector",
        description="Optional JSON array to use instead of re-encoding the query text",
        json_schema_extra={"ui:widget": "textarea"},
    )
    properties: Optional[str] = Field(
        None,
        title="Return Properties",
        description="Object properties to return, comma-separated. id + score always included.",
    )
    limit: int = Field(10, title="Limit")
    where: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description='Weaviate WhereFilter JSON object to restrict the hybrid search results',
        json_schema_extra={"ui:widget": "textarea"},
    )
    target_vector: Optional[str] = Field(
        None,
        title="Target Vector",
        description="Named vector to search (for multi-vector collections). Leave blank for the default vector.",
    )


class WeaviateGenerativeSearchConfig(BaseModel):
    """Generative search (RAG): retrieve objects then generate text with an LLM (GraphQL generate).

    The collection must have a generative module configured in its schema
    (e.g. generative-openai, generative-anthropic, generative-cohere). Pass the
    corresponding API key in the credential. Provide single_prompt, group_task, or both.
    """

    operation: Literal["generative_search"] = Field(
        "generative_search",
        json_schema_extra={
            "const": "generative_search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Generative Search (RAG)",
            "x-keywords": ["rag", "generate", "llm", "summarize", "answer", "gpt", "claude", "cohere", "gemini"],
        },
        title="Generative Search (RAG)",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    search_type: str = Field(
        "nearVector",
        title="Search Type",
        description="How to retrieve objects before generating",
        json_schema_extra={
            "enum": ["nearVector", "nearText", "hybrid"],
            "enumNames": ["Vector (nearVector)", "Text (nearText)", "Hybrid (BM25+vector)"],
            "x-enum-searchable": True,
        },
    )
    vector: Optional[str] = Field(
        None,
        title="Query Vector",
        description="JSON array of numbers — required for nearVector; optional for hybrid",
        json_schema_extra={"ui:widget": "textarea"},
    )
    text: Optional[str] = Field(
        None,
        title="Query Text",
        description="Text query — required for nearText and hybrid",
        json_schema_extra={"ui:widget": "textarea"},
    )
    alpha: float = Field(
        0.75,
        title="Hybrid Alpha",
        description="BM25 (0) to vector (1) balance — only used with hybrid search type",
    )
    properties: Optional[str] = Field(
        None,
        title="Return Properties",
        description="Object properties to return alongside generated text, comma-separated",
    )
    limit: int = Field(5, title="Limit", description="Number of objects to retrieve and feed to the LLM")
    where: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description="Optional WhereFilter JSON to restrict which objects are fed to the LLM",
        json_schema_extra={"ui:widget": "textarea"},
    )
    single_prompt: Optional[str] = Field(
        None,
        title="Single Prompt",
        description='Prompt template applied to each object individually. Reference object properties with {propertyName}, e.g. "Summarize this article: {content}"',
        json_schema_extra={"ui:widget": "textarea"},
    )
    group_task: Optional[str] = Field(
        None,
        title="Group Task",
        description='Task applied once to ALL retrieved objects combined, e.g. "What do these articles have in common?"',
        json_schema_extra={"ui:widget": "textarea"},
    )


class WeaviateAggregateConfig(BaseModel):
    """Aggregate statistics over a collection (GraphQL Aggregate — count, mean, topOccurrences, etc.)."""

    operation: Literal["aggregate"] = Field(
        "aggregate",
        json_schema_extra={
            "const": "aggregate",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Aggregate",
            "x-keywords": ["count", "stats", "statistics", "aggregate", "average", "mean", "sum", "group by", "analytics"],
        },
        title="Aggregate",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    properties: Optional[str] = Field(
        None,
        title="Properties (JSON)",
        description=(
            'JSON array of property aggregation definitions. Each entry specifies a property name and '
            'the stats to compute. Numeric properties support stats: ["mean","maximum","minimum","sum","count"]. '
            'Text properties support topOccurrences (number). '
            'E.g. [{"name":"score","stats":["mean","maximum"]},{"name":"category","topOccurrences":5}]. '
            'meta.count is always included.'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    where: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description="WhereFilter JSON to restrict which objects are aggregated",
        json_schema_extra={"ui:widget": "textarea"},
    )
    group_by: Optional[str] = Field(
        None,
        title="Group By",
        description='Property name to group results by (e.g. "category"). Adds groupedBy { value path } to the selection.',
    )
    limit: Optional[int] = Field(
        None,
        title="Limit",
        description="Max number of groups returned when using Group By",
    )


class WeaviateInsertConfig(BaseModel):
    """Insert an object (REST)."""

    operation: Literal["insert"] = Field(
        "insert",
        json_schema_extra={
            "const": "insert",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Insert Object",
            "x-keywords": ["add", "create object", "index", "store", "upsert"],
        },
        title="Insert Object",
    )
    collection: str = Field(
        ..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    properties: str = Field(
        ...,
        title="Properties",
        description='JSON object of the object\'s properties, e.g. {"title": "Doc", "content": "..."}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    vector: Optional[str] = Field(
        None,
        title="Vector",
        description="Optional JSON array embedding (omit if the class has a vectorizer)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    id: Optional[str] = Field(None, title="ID", description="Optional UUID for the object")


class WeaviateGetConfig(BaseModel):
    """Get an object by ID (REST)."""

    operation: Literal["get"] = Field(
        "get",
        json_schema_extra={
            "const": "get",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Get Object",
            "x-keywords": ["fetch", "lookup by id", "read"],
        },
        title="Get Object",
    )
    collection: str = Field(
        ..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    id: str = Field(..., title="ID", description="Object UUID")


class WeaviateDeleteConfig(BaseModel):
    """Delete an object by ID (REST)."""

    operation: Literal["delete"] = Field(
        "delete",
        json_schema_extra={
            "const": "delete",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Delete Object",
            "x-keywords": ["remove", "purge"],
        },
        title="Delete Object",
    )
    collection: str = Field(
        ..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    id: str = Field(..., title="ID", description="Object UUID")


class WeaviateListCollectionsConfig(BaseModel):
    """List collections (schema classes)."""

    operation: Literal["list_collections"] = Field(
        "list_collections",
        json_schema_extra={
            "const": "list_collections",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "List Collections",
            "x-keywords": ["list", "show classes", "schema"],
        },
        title="List Collections",
    )


class WeaviateCreateCollectionConfig(BaseModel):
    """Create a collection (schema class)."""

    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection",
            "x-creates-resource": True,
            "x-resource-type": "weaviate_collection",
            "x-resource-id-path": "data.class",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "Create Collection",
            "x-keywords": ["new class", "provision", "setup"],
        },
        title="Create Collection",
    )
    name: str = Field(..., title="Name", description="Class name (Weaviate capitalises it)")
    vectorizer: str = Field(
        "none",
        title="Vectorizer",
        description="Embedding module, or 'none' for bring-your-own vectors",
        json_schema_extra={
            "enum": ["none", "text2vec-weaviate", "text2vec-openai", "text2vec-cohere", "text2vec-huggingface"],
            "x-enum-searchable": True,
        },
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description='Optional JSON array of property defs, e.g. [{"name": "title", "dataType": ["text"]}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class WeaviateUpdateConfig(BaseModel):
    """Partial update (PATCH /v1/objects/{class}/{id}) — merges provided fields."""

    operation: Literal["update"] = Field(
        "update",
        json_schema_extra={
            "const": "update",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Update Object",
            "x-keywords": ["patch", "modify", "edit", "merge properties"],
        },
        title="Update Object",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    id: str = Field(..., title="ID", description="Object UUID")
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="JSON object of properties to merge in (only listed fields change)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    vector: Optional[str] = Field(
        None,
        title="Vector",
        description="Optional JSON array replacement vector",
        json_schema_extra={"ui:widget": "textarea"},
    )


class WeaviateDeleteCollectionConfig(BaseModel):
    """Drop a collection and ALL of its objects — permanent."""

    operation: Literal["delete_collection"] = Field(
        "delete_collection",
        json_schema_extra={
            "const": "delete_collection",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "Delete Collection",
            "x-keywords": ["drop class", "remove schema", "purge collection", "truncate"],
        },
        title="Delete Collection",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class WeaviateBatchDeleteConfig(BaseModel):
    """Batch-delete objects matching a where filter (up to 10,000 per call)."""

    operation: Literal["batch_delete"] = Field(
        "batch_delete",
        json_schema_extra={
            "const": "batch_delete",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Batch Delete Objects",
            "x-keywords": ["bulk delete", "delete by filter", "purge", "clean up"],
        },
        title="Batch Delete Objects",
    )
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    where: str = Field(
        ...,
        title="Filter (JSON)",
        description='WhereFilter JSON, e.g. {"path":["category"],"operator":"Equal","valueText":"old"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    dry_run: str = Field(
        "false",
        title="Dry Run",
        description="If true, reports how many objects would be deleted without actually deleting them",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["Delete (live)", "Dry run (preview only)"],
            "x-enum-searchable": True,
        },
    )


class WeaviateUploadIndexConfig(BaseModel):
    """Upload a document file, chunk + embed it, and batch-insert objects."""

    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index",
            "ui:hidden": True,
            "x-category": "Objects",
            "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file", "add pdf"],
        },
        title="Upload & Index Document",
    )
    collection: str = Field(
        ..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA
    )
    document: str = Field(
        ...,
        title="Document",
        description="Upload a PDF/DOCX/TXT/MD/CSV file (or paste a URL / reference an upstream file). It's chunked, embedded with text-embedding-3-small, and batch-inserted as objects (text/source/chunk_index properties + explicit vector).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": DOCUMENT_ACCEPT},
    )
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap", description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(
        None, title="ID Prefix", description="Optional prefix for chunk IDs (defaults to the filename)"
    )


# ============================================================================
# Discriminated Union
# ============================================================================


WeaviateConfig = Annotated[
    Union[
        WeaviateQueryConfig,
        WeaviateQueryTextConfig,
        WeaviateHybridSearchConfig,
        WeaviateGenerativeSearchConfig,
        WeaviateAggregateConfig,
        WeaviateInsertConfig,
        WeaviateGetConfig,
        WeaviateUpdateConfig,
        WeaviateDeleteConfig,
        WeaviateListCollectionsConfig,
        WeaviateCreateCollectionConfig,
        WeaviateDeleteCollectionConfig,
        WeaviateBatchDeleteConfig,
        WeaviateUploadIndexConfig,
    ],
    Discriminator("operation"),
]


class WeaviateNodeConfig(NodeConfig[WeaviateConfig, WeaviateCredential]):
    """Full configuration for the Weaviate node including credentials."""

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


def _property_fields(properties: Optional[str]) -> str:
    """Comma-separated property names → space-separated GraphQL field selection."""
    if not properties:
        return ""
    names = [p.strip() for p in properties.split(",") if p.strip()]
    return " ".join(names)


def _where_filter_to_gql(obj: Dict[str, Any]) -> str:
    """Recursively convert a Weaviate WhereFilter dict to inline GraphQL argument syntax.

    GraphQL differs from JSON: object keys are unquoted, operator/geo values are enums
    (unquoted), and nested operands must recurse. This avoids the GraphQL variables path
    whose type name (`WhereFilter`) is not exposed in all Weaviate server versions.
    """
    _ENUM_KEYS = {"operator", "moveAwayFrom", "moveTo"}
    parts = []
    for key, val in obj.items():
        if key == "operands" and isinstance(val, list):
            inner = ", ".join(f"{{{_where_filter_to_gql(o)}}}" for o in val)
            parts.append(f"{key}: [{inner}]")
        elif key == "path" and isinstance(val, list):
            arr = ", ".join(f'"{p}"' for p in val)
            parts.append(f"{key}: [{arr}]")
        elif key in _ENUM_KEYS and isinstance(val, str):
            parts.append(f"{key}: {val}")  # enum — no quotes
        elif isinstance(val, bool):
            parts.append(f"{key}: {str(val).lower()}")
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            parts.append(f"{key}: {val}")
        elif isinstance(val, str):
            parts.append(f'{key}: "{val}"')
        elif isinstance(val, dict):
            parts.append(f"{key}: {{{_where_filter_to_gql(val)}}}")
    return ", ".join(parts)


def _parse_where_filter(value: Optional[str]):
    """Parse a where filter JSON string → (dict, gql_inline_str) or (False, None) on error, (None, None) when empty."""
    if not value or not value.strip():
        return None, None
    obj = _parse_json_obj(value)
    if obj is None:
        return False, None
    return obj, _where_filter_to_gql(obj)


def _build_get_query(
    class_name: str, near_clause: str, props: str, limit: int, where_gql: Optional[str] = None
) -> str:
    """Assemble a Weaviate GraphQL Get query string with optional inline where filter."""
    selection = f"{props} _additional {{ id distance }}".strip() if props else "_additional { id distance }"
    where = f", where: {{{where_gql}}}" if where_gql else ""
    return f'{{ Get {{ {class_name}({near_clause}{where}, limit: {limit}) {{ {selection} }} }} }}'


def _build_generative_query(
    class_name: str,
    near_clause: str,
    props: str,
    limit: int,
    where_gql: Optional[str] = None,
    single_prompt: Optional[str] = None,
    group_task: Optional[str] = None,
) -> str:
    """Assemble a GraphQL Get query with a generate(...) block in _additional."""
    generate_args = []
    if single_prompt:
        escaped = single_prompt.replace("\\", "\\\\").replace('"', '\\"')
        generate_args.append(f'singleResult: {{ prompt: "{escaped}" }}')
    if group_task:
        escaped = group_task.replace("\\", "\\\\").replace('"', '\\"')
        generate_args.append(f'groupedResult: {{ task: "{escaped}" }}')
    generate_gql = f'generate({", ".join(generate_args)}) {{ singleResult groupedResult error }}'
    additional = f"_additional {{ id distance {generate_gql} }}"
    selection = f"{props} {additional}".strip() if props else additional
    where = f", where: {{{where_gql}}}" if where_gql else ""
    return f"{{ Get {{ {class_name}({near_clause}{where}, limit: {limit}) {{ {selection} }} }} }}"


def _build_aggregate_query(
    class_name: str,
    properties_json: Optional[str] = None,
    where_gql: Optional[str] = None,
    group_by: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Assemble a Weaviate GraphQL Aggregate query."""
    prop_parts = ["meta { count }"]
    if group_by:
        prop_parts.append("groupedBy { value path }")

    if properties_json:
        props = _parse_json_list(properties_json)
        if props:
            for prop in props:
                name = prop.get("name")
                if not name:
                    continue
                field_parts = list(prop.get("stats", []))
                top_occ = prop.get("topOccurrences")
                if top_occ is not None:
                    field_parts.append(f"topOccurrences(limit: {int(top_occ)}) {{ value occurs }}")
                if field_parts:
                    prop_parts.append(f"{name} {{ {' '.join(field_parts)} }}")

    prop_selection = " ".join(prop_parts)

    args = []
    if where_gql:
        args.append(f"where: {{{where_gql}}}")
    if group_by:
        args.append(f'groupBy: ["{group_by}"]')
    if limit is not None:
        args.append(f"limit: {limit}")

    args_str = f"({', '.join(args)})" if args else ""
    return f"{{ Aggregate {{ {class_name}{args_str} {{ {prop_selection} }} }} }}"


# ============================================================================
# Node Implementation
# ============================================================================


class WeaviateNode(WorkflowNode):
    """Weaviate vector database automation node."""

    edit_examples = [
        "Semantically search a Weaviate class by text for the most relevant objects",
        "Vector-search a Weaviate class with a precomputed query embedding",
        "Insert a document object into Weaviate with its embedding",
        "Create a Weaviate class with an OpenAI vectorizer for automatic embedding",
        "Delete an object by its UUID",
        "Use generative search to summarize retrieved documents with GPT-4",
        "Aggregate object counts grouped by category",
    ]

    @classmethod
    def get_config_model(cls):
        return WeaviateNodeConfig

    @staticmethod
    def _base_url(credential: WeaviateCredential) -> str:
        return (credential.url or "").rstrip("/")

    @staticmethod
    def _headers(credential: WeaviateCredential) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": "NoClick-Workflow/1.0"}
        if credential.api_key:
            headers["Authorization"] = f"Bearer {credential.api_key}"
        if credential.openai_api_key:
            headers["X-OpenAI-Api-Key"] = credential.openai_api_key
        if credential.cohere_api_key:
            headers["X-Cohere-Api-Key"] = credential.cohere_api_key
        if credential.huggingface_api_key:
            headers["X-HuggingFace-Api-Key"] = credential.huggingface_api_key
        if credential.anthropic_api_key:
            headers["X-Anthropic-Api-Key"] = credential.anthropic_api_key
        if credential.google_api_key:
            headers["X-Google-Api-Key"] = credential.google_api_key
        if credential.mistral_api_key:
            headers["X-Mistral-Api-Key"] = credential.mistral_api_key
        if credential.weaviate_embedding_api_key:
            headers["X-Weaviate-Api-Key"] = credential.weaviate_embedding_api_key
            headers["X-Weaviate-Cluster-Url"] = credential.url  # required by text2vec-weaviate
        return headers

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Populate the collection dropdown from the Weaviate schema."""
        if field_name != "collection":
            return []
        url = (credential_data or {}).get("url")
        if not url:
            return []
        headers = {"Content-Type": "application/json"}
        if credential_data.get("api_key"):
            headers["Authorization"] = f"Bearer {credential_data['api_key']}"
        try:
            async with guarded_async_client(timeout=20.0) as client:
                resp = await client.get(f"{url.rstrip('/')}/v1/schema", headers=headers)
        except httpx.HTTPError as e:
            logger.warning(f"[WeaviateNode] Failed to list schema: {e}")
            return []
        if resp.status_code >= 400:
            logger.warning(f"[WeaviateNode] Schema returned {resp.status_code}: {resp.text}")
            return []
        classes = resp.json().get("classes", []) or []
        options = []
        for cls_def in classes:
            name = cls_def.get("class")
            if not name:
                continue
            if search and search.lower() not in name.lower():
                continue
            options.append({"value": name, "label": name})
        return options

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, WeaviateNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Weaviate URL and API key.")

        op_config = config.config
        handlers = {
            "query": self._handle_query,
            "query_text": self._handle_query_text,
            "hybrid_search": self._handle_hybrid_search,
            "generative_search": self._handle_generative_search,
            "aggregate": self._handle_aggregate,
            "insert": self._handle_insert,
            "get": self._handle_get,
            "update": self._handle_update,
            "delete": self._handle_delete,
            "list_collections": self._handle_list_collections,
            "create_collection": self._handle_create_collection,
            "delete_collection": self._handle_delete_collection,
            "batch_delete": self._handle_batch_delete,
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
        credential: WeaviateCredential,
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
                error_message = error_data.get("error", error_data.get("message", str(error_data)))
            except Exception:
                error_message = response.text
            logger.error(f"[WeaviateNode] API error ({action_name}): {error_message}")
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

        # GraphQL surfaces errors in a 200 body — promote them to an error result.
        if isinstance(data, dict) and data.get("errors"):
            return {
                "status": "error",
                "action": action_name,
                "error": data["errors"],
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

    # =========================================================================
    # Operation handlers
    # =========================================================================

    async def _handle_query(self, config: WeaviateQueryConfig, credentials) -> Dict[str, Any]:
        vector = _parse_json_list(config.vector)
        if not vector:
            return {"status": "error", "action": "query", "error": "`vector` must be a non-empty JSON array of numbers"}
        tv_part = f', targetVectors: ["{config.target_vector}"]' if config.target_vector else ""
        near = f"nearVector: {{vector: {json.dumps(vector)}{tv_part}}}"
        where_obj, where_gql = _parse_where_filter(config.where)
        if where_obj is False:
            return {"status": "error", "action": "query", "error": "`where` must be a valid JSON WhereFilter object"}
        gql = _build_get_query(config.collection, near, _property_fields(config.properties), config.limit, where_gql=where_gql)
        url = f"{self._base_url(credentials)}/v1/graphql"
        return await self._request("POST", url, credentials, json_body={"query": gql}, action_name="query")

    async def _handle_query_text(self, config: WeaviateQueryTextConfig, credentials) -> Dict[str, Any]:
        tv_part = f', targetVectors: ["{config.target_vector}"]' if config.target_vector else ""
        near = f"nearText: {{concepts: {json.dumps([config.text])}{tv_part}}}"
        where_obj, where_gql = _parse_where_filter(config.where)
        if where_obj is False:
            return {"status": "error", "action": "query_text", "error": "`where` must be a valid JSON WhereFilter object"}
        gql = _build_get_query(config.collection, near, _property_fields(config.properties), config.limit, where_gql=where_gql)
        url = f"{self._base_url(credentials)}/v1/graphql"
        return await self._request("POST", url, credentials, json_body={"query": gql}, action_name="query_text")

    async def _handle_insert(self, config: WeaviateInsertConfig, credentials) -> Dict[str, Any]:
        properties = _parse_json_obj(config.properties)
        if properties is None:
            return {"status": "error", "action": "insert", "error": "`properties` must be a JSON object"}
        body: Dict[str, Any] = {"class": config.collection, "properties": properties}
        if config.vector:
            vector = _parse_json_list(config.vector)
            if not vector:
                return {"status": "error", "action": "insert", "error": "`vector` must be a non-empty JSON array of numbers"}
            body["vector"] = vector
        if config.id:
            body["id"] = config.id
        url = f"{self._base_url(credentials)}/v1/objects"
        return await self._request("POST", url, credentials, json_body=body, action_name="insert")

    async def _handle_get(self, config: WeaviateGetConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/v1/objects/{config.collection}/{config.id}"
        return await self._request("GET", url, credentials, action_name="get")

    async def _handle_delete(self, config: WeaviateDeleteConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/v1/objects/{config.collection}/{config.id}"
        return await self._request("DELETE", url, credentials, action_name="delete")

    async def _handle_update(self, config: WeaviateUpdateConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if config.properties:
            props = _parse_json_obj(config.properties)
            if props is None:
                return {"status": "error", "action": "update", "error": "`properties` must be a JSON object"}
            body["properties"] = props
        if config.vector:
            vec = _parse_json_list(config.vector)
            if not vec:
                return {"status": "error", "action": "update", "error": "`vector` must be a non-empty JSON array"}
            body["vector"] = vec
        if not body:
            return {"status": "error", "action": "update", "error": "Provide at least one of `properties` or `vector` to update"}
        url = f"{self._base_url(credentials)}/v1/objects/{config.collection}/{config.id}"
        return await self._request("PATCH", url, credentials, json_body=body, action_name="update")

    async def _handle_hybrid_search(self, config: WeaviateHybridSearchConfig, credentials) -> Dict[str, Any]:
        hybrid_parts = [f'query: {json.dumps(config.query)}', f"alpha: {config.alpha}"]
        if config.vector:
            vec = _parse_json_list(config.vector)
            if not vec:
                return {"status": "error", "action": "hybrid_search", "error": "`vector` must be a non-empty JSON array"}
            hybrid_parts.append(f"vector: {json.dumps(vec)}")
        if config.target_vector:
            hybrid_parts.append(f'targetVectors: ["{config.target_vector}"]')
        near = f"hybrid: {{{', '.join(hybrid_parts)}}}"
        where_obj, where_gql = _parse_where_filter(config.where)
        if where_obj is False:
            return {"status": "error", "action": "hybrid_search", "error": "`where` must be a valid JSON WhereFilter object"}
        # Hybrid uses score (not distance) in _additional
        selection = _property_fields(config.properties)
        score_additional = "_additional { id score }"
        full_selection = f"{selection} {score_additional}".strip() if selection else score_additional
        where = f", where: {{{where_gql}}}" if where_gql else ""
        gql = f'{{ Get {{ {config.collection}({near}{where}, limit: {config.limit}) {{ {full_selection} }} }} }}'
        url = f"{self._base_url(credentials)}/v1/graphql"
        return await self._request("POST", url, credentials, json_body={"query": gql}, action_name="hybrid_search")

    async def _handle_generative_search(self, config: WeaviateGenerativeSearchConfig, credentials) -> Dict[str, Any]:
        if not config.single_prompt and not config.group_task:
            return {
                "status": "error", "action": "generative_search",
                "error": "Provide at least one of `single_prompt` or `group_task`",
            }

        where_obj, where_gql = _parse_where_filter(config.where)
        if where_obj is False:
            return {"status": "error", "action": "generative_search", "error": "`where` must be a valid JSON WhereFilter object"}

        if config.search_type == "nearVector":
            vector = _parse_json_list(config.vector)
            if not vector:
                return {"status": "error", "action": "generative_search", "error": "`vector` is required and must be a non-empty JSON array for nearVector search"}
            near = f"nearVector: {{vector: {json.dumps(vector)}}}"
        elif config.search_type == "nearText":
            if not config.text:
                return {"status": "error", "action": "generative_search", "error": "`text` is required for nearText search"}
            near = f"nearText: {{concepts: {json.dumps([config.text])}}}"
        elif config.search_type == "hybrid":
            if not config.text:
                return {"status": "error", "action": "generative_search", "error": "`text` is required for hybrid search"}
            hybrid_parts = [f'query: {json.dumps(config.text)}', f"alpha: {config.alpha}"]
            if config.vector:
                vec = _parse_json_list(config.vector)
                if not vec:
                    return {"status": "error", "action": "generative_search", "error": "`vector` must be a non-empty JSON array"}
                hybrid_parts.append(f"vector: {json.dumps(vec)}")
            near = f"hybrid: {{{', '.join(hybrid_parts)}}}"
        else:
            return {"status": "error", "action": "generative_search", "error": f"Unknown search_type: {config.search_type!r}"}

        gql = _build_generative_query(
            config.collection, near, _property_fields(config.properties), config.limit,
            where_gql=where_gql, single_prompt=config.single_prompt, group_task=config.group_task,
        )
        url = f"{self._base_url(credentials)}/v1/graphql"
        return await self._request("POST", url, credentials, json_body={"query": gql}, action_name="generative_search")

    async def _handle_aggregate(self, config: WeaviateAggregateConfig, credentials) -> Dict[str, Any]:
        where_obj, where_gql = _parse_where_filter(config.where)
        if where_obj is False:
            return {"status": "error", "action": "aggregate", "error": "`where` must be a valid JSON WhereFilter object"}

        gql = _build_aggregate_query(
            config.collection,
            properties_json=config.properties,
            where_gql=where_gql,
            group_by=config.group_by,
            limit=config.limit,
        )
        url = f"{self._base_url(credentials)}/v1/graphql"
        return await self._request("POST", url, credentials, json_body={"query": gql}, action_name="aggregate")

    async def _handle_delete_collection(self, config: WeaviateDeleteCollectionConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/v1/schema/{config.collection}"
        return await self._request("DELETE", url, credentials, action_name="delete_collection")

    async def _handle_batch_delete(self, config: WeaviateBatchDeleteConfig, credentials) -> Dict[str, Any]:
        where_obj = _parse_json_obj(config.where)
        if where_obj is None:
            return {"status": "error", "action": "batch_delete", "error": "`where` must be a valid JSON WhereFilter object"}
        body: Dict[str, Any] = {
            "match": {"class": config.collection, "where": where_obj},
            "dryRun": config.dry_run == "true",
            "output": "verbose",
        }
        url = f"{self._base_url(credentials)}/v1/batch/objects"
        return await self._request("DELETE", url, credentials, json_body=body, action_name="batch_delete")

    async def _handle_list_collections(self, config: WeaviateListCollectionsConfig, credentials) -> Dict[str, Any]:
        url = f"{self._base_url(credentials)}/v1/schema"
        return await self._request("GET", url, credentials, action_name="list_collections")

    async def _handle_create_collection(self, config: WeaviateCreateCollectionConfig, credentials) -> Dict[str, Any]:
        body: Dict[str, Any] = {"class": config.name, "vectorizer": config.vectorizer}
        properties = _parse_json_list(config.properties)
        if properties is not None:
            body["properties"] = properties
        url = f"{self._base_url(credentials)}/v1/schema"
        return await self._request("POST", url, credentials, json_body=body, action_name="create_collection")

    async def _handle_upload_and_index(self, config: WeaviateUploadIndexConfig, credentials) -> Dict[str, Any]:
        records, info = await ingest_document(
            self, config.document, chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap, id_prefix=config.id_prefix
        )
        if not records:
            return {"status": "error", "action": "upload_and_index", "error": "No text could be extracted from the document"}
        objects = [
            {
                "class": config.collection,
                "id": r["id"],
                "vector": r["values"],
                "properties": {
                    "text": r["metadata"]["text"],
                    "source": r["metadata"]["source"],
                    "chunk_index": r["metadata"]["chunk_index"],
                },
            }
            for r in records
        ]
        url = f"{self._base_url(credentials)}/v1/batch/objects"
        result = await self._request("POST", url, credentials, json_body={"objects": objects}, action_name="upload_and_index")
        if result.get("status") == "success":
            result["data"] = {"chunks_indexed": len(records), "source": info.get("filename"), "raw": result.get("data")}
        return result
