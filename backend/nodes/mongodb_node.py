"""
MongoDB database automation node.

Provides workflow integration with MongoDB and MongoDB Atlas via the
async motor driver. Covers full CRUD, aggregation, index management,
Atlas Vector Search ($vectorSearch), and document upload/indexing for RAG.

Authentication: MongoDB connection string (mongodb:// or mongodb+srv://).
Library: motor[asyncio] for async MongoDB operations.
Atlas Vector Search docs: https://www.mongodb.com/docs/atlas/atlas-vector-search/
"""

import asyncio
import json
import logging
import re
import socket
from datetime import datetime, date
from typing import Any, Dict, List, Literal, Optional, Union, Annotated
from urllib.parse import unquote_plus, urlsplit
from pydantic import BaseModel, Field, ConfigDict, Discriminator

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.document_ingest import DOCUMENT_ACCEPT, ingest_document
from utils.ssrf import (
    SSRFError,
    allow_private_hosts,
    assert_host_allowed,
    is_blocked_ip,
)

logger = logging.getLogger(__name__)

_ATLAS_SRV_SUFFIX = ".mongodb.net"
_SAFE_MONGODB_AUTH_MECHANISMS = {
    "DEFAULT",
    "SCRAM-SHA-1",
    "SCRAM-SHA-256",
}
_MONGODB_LOCAL_CREDENTIAL_OPTIONS = {
    "tlscafile",
    "tlscertificatekeyfile",
    "tlscertificatekeyfilepassword",
    "tlscrlfile",
}
_MONGODB_PROXY_OPTIONS = {
    "proxyhost",
    "proxypassword",
    "proxyport",
    "proxyusername",
}


def _mongodb_driver_query(connection_string: str) -> str:
    """Extract options with PyMongo's first-raw-question-mark grammar."""
    _prefix, separator, query = connection_string.partition("?")
    return query if separator else ""


def _decoded_mongodb_query_options(query: str):
    """Yield decoded URI option names/values without consulting local files."""
    for raw_option in re.split(r"[&;]", query):
        if not raw_option:
            continue
        raw_name, separator, raw_value = raw_option.partition("=")
        try:
            name = unquote_plus(raw_name, errors="strict").lower()
            value = unquote_plus(raw_value, errors="strict") if separator else ""
        except UnicodeDecodeError as exc:
            raise SSRFError(
                "MongoDB connection string has invalid URI encoding"
            ) from exc
        yield name, value


def _assert_safe_mongodb_credential_options(query: str) -> None:
    """Reject URI options that can source credentials from the host runtime."""
    for name, value in _decoded_mongodb_query_options(query):
        if name == "authmechanismproperties":
            raise SSRFError(
                "MongoDB authMechanismProperties is not allowed by the outbound policy"
            )
        if name == "authmechanism":
            mechanism = value.strip().upper()
            if mechanism not in _SAFE_MONGODB_AUTH_MECHANISMS:
                raise SSRFError(
                    "MongoDB authMechanism must use DEFAULT, SCRAM-SHA-256, "
                    "or SCRAM-SHA-1"
                )
        if name in _MONGODB_LOCAL_CREDENTIAL_OPTIONS:
            raise SSRFError(f"MongoDB {name} is not allowed by the outbound policy")
        if name in _MONGODB_PROXY_OPTIONS:
            raise SSRFError("MongoDB proxy options are not allowed by the outbound policy")


def _pinned_pymongo_create_connection(original, address, options):
    """Resolve once, validate every answer, and make PyMongo dial IP literals.

    PyMongo keeps the original ``address`` for TLS SNI and hostname checking;
    this hook replaces only its raw-socket dial. Passing the validated literal
    to the original connector prevents a second attacker-controlled DNS answer.
    """
    if allow_private_hosts():
        return original(address, options)
    host, port = address
    if str(host).endswith(".sock"):
        raise SSRFError("MongoDB Unix sockets are not allowed by the outbound policy")
    try:
        infos = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except (OSError, UnicodeError) as error:
        raise SSRFError(f"Could not resolve MongoDB host '{host}': {error}") from error

    addresses = []
    for info in infos:
        resolved = info[4][0]
        if resolved in addresses:
            continue
        if is_blocked_ip(resolved):
            raise SSRFError(
                f"Refusing MongoDB connection to non-public address {resolved}"
            )
        addresses.append(resolved)
    if not addresses:
        raise SSRFError(f"MongoDB host '{host}' did not resolve to any address")

    last_error = None
    for resolved in addresses:
        try:
            return original((resolved, port), options)
        except OSError as error:
            last_error = error
    assert last_error is not None
    raise last_error


def _install_pymongo_socket_pin() -> None:
    """Install the process-wide PyMongo raw-socket guard exactly once."""
    from pymongo import pool_shared

    current = pool_shared._create_connection
    if getattr(current, "_noclick_ssrf_pinned", False):
        return

    def pinned(address, options):
        return _pinned_pymongo_create_connection(current, address, options)

    pinned._noclick_ssrf_pinned = True
    pool_shared._create_connection = pinned


def _mongodb_uri_parts(connection_string: str):
    """Parse only the user-authored URI surface; never resolve DNS here."""
    from pymongo.uri_parser_shared import split_options

    try:
        parts = urlsplit(connection_string)
        # PyMongo opens some TLS option paths while parsing and treats the first
        # raw question mark as its delimiter even when a standard URL parser
        # sees it inside a fragment. Inspect that exact option surface first.
        driver_query = _mongodb_driver_query(connection_string)
        _assert_safe_mongodb_credential_options(driver_query)
        # SRV URIs have exactly one seed; accessing these properties validates
        # its host/port syntax. Plain URIs may contain a comma-separated seed
        # list, which urllib does not understand and PyMongo validates below.
        if parts.scheme == "mongodb+srv":
            _ = parts.hostname
            _ = parts.port
        options = (
            {
                str(key).lower(): value
                for key, value in split_options(driver_query).items()
            }
            if driver_query
            else {}
        )
    except SSRFError:
        raise
    except Exception as e:
        raise SSRFError("MongoDB connection string is invalid") from e
    return parts, options


def _is_atlas_host(host: str) -> bool:
    normalized = str(host or "").lower().rstrip(".")
    return normalized.endswith(_ATLAS_SRV_SUFFIX) and normalized != _ATLAS_SRV_SUFFIX[1:]


def _plain_mongodb_uses_trusted_atlas_topology(connection_string: str) -> bool:
    """Whether every seed in a parsed plain URI is provider-controlled Atlas."""
    from pymongo.uri_parser import parse_uri

    parsed = parse_uri(connection_string)
    nodes = parsed.get("nodelist") or []
    return bool(nodes) and all(_is_atlas_host(str(host)) for host, _port in nodes)

# ============================================================================
# Dynamic-options field descriptors
# ============================================================================

_DATABASE_FIELD_EXTRA = {
    "x-dynamic-options": {
        "field_name": "database",
        "placeholder": "Select a database...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type the database name",
    }
}

_COLLECTION_FIELD_EXTRA = {
    "x-resource-type": "mongodb_collection",
    "x-dynamic-options": {
        "field_name": "collection",
        "placeholder": "Select a collection...",
        "searchable": True,
        "allow_custom": True,
        "depends_on": "database",
        "custom_placeholder": "Or type the collection name",
    }
}

_INDEX_FIELD_EXTRA = {
    "x-resource-type": "mongodb_index",
    "x-dynamic-options": {
        "field_name": "index_name",
        "placeholder": "Select an index...",
        "searchable": True,
        "allow_custom": True,
        "depends_on": "collection",
        "custom_placeholder": "Or type the index name",
    }
}

# For Atlas Search / Vector Search indexes (listed via list_search_indexes)
_SEARCH_INDEX_FIELD_EXTRA = {
    "x-dynamic-options": {
        "field_name": "search_index_name",
        "placeholder": "Select a search index...",
        "searchable": True,
        "allow_custom": True,
        "depends_on": "collection",
        "custom_placeholder": "Or type the index name (default = default)",
    }
}

# ============================================================================
# Credential Schema
# ============================================================================


class MongoDBCredential(BaseModel):
    """MongoDB connection string credential."""

    credential_type: Literal["mongodb_connection_string"] = Field(
        "mongodb_connection_string", json_schema_extra={"ui:hidden": True}
    )
    connection_string: str = Field(
        ...,
        title="Connection String",
        description=(
            "MongoDB URI, e.g. mongodb+srv://user:pass@cluster.mongodb.net/ "
            "or mongodb://localhost:27017/"
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://cloud.mongodb.com/",
            "x-credential-instructions": (
                "Go to MongoDB Atlas → Database → Connect → Drivers, "
                "copy the connection string, and replace <password> with "
                "your database user password. For self-hosted MongoDB use "
                "mongodb://user:pass@host:27017/."
            ),
        }
    )


# ============================================================================
# Operation Configs — Documents
# ============================================================================


class MongoDBFindConfig(BaseModel):
    operation: Literal["find"] = Field(
        "find",
        json_schema_extra={
            "const": "find", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Find Documents",
            "x-keywords": ["query", "list", "search", "filter", "get many", "fetch"],
        },
        title="Find Documents",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: Optional[str] = Field(
        None, title="Filter",
        description='MongoDB query filter as JSON, e.g. {"status": "active"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    projection: Optional[str] = Field(
        None, title="Projection",
        description='Fields to include/exclude as JSON, e.g. {"name": 1, "_id": 0}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    sort: Optional[str] = Field(
        None, title="Sort",
        description='Sort specification as JSON, e.g. {"createdAt": -1}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    skip: int = Field(0, title="Skip", description="Number of documents to skip")
    limit: int = Field(100, title="Limit", description="Maximum documents to return (0 = no limit)")
    hint: Optional[str] = Field(
        None, title="Index Hint",
        description='Force a specific index, e.g. {"email": 1} or "email_1" (index name)',
        json_schema_extra={"ui:widget": "textarea"},
    )
    collation: Optional[str] = Field(
        None, title="Collation",
        description='Language-specific string comparison, e.g. {"locale": "en", "strength": 2}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBFindOneConfig(BaseModel):
    operation: Literal["find_one"] = Field(
        "find_one",
        json_schema_extra={
            "const": "find_one", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Find One Document",
            "x-keywords": ["get", "fetch single", "find by id"],
        },
        title="Find One Document",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        description='MongoDB query filter as JSON, e.g. {"_id": "abc"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    projection: Optional[str] = Field(
        None, title="Projection",
        description='Fields to include/exclude as JSON, e.g. {"name": 1}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    hint: Optional[str] = Field(
        None, title="Index Hint",
        description='Force a specific index, e.g. {"email": 1} or "email_1" (index name)',
        json_schema_extra={"ui:widget": "textarea"},
    )
    collation: Optional[str] = Field(
        None, title="Collation",
        description='Language-specific string comparison, e.g. {"locale": "en", "strength": 2}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBInsertOneConfig(BaseModel):
    operation: Literal["insert_one"] = Field(
        "insert_one",
        json_schema_extra={
            "const": "insert_one", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Insert One Document",
            "x-keywords": ["create", "add", "write", "save", "insert"],
        },
        title="Insert One Document",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    document: str = Field(
        ..., title="Document",
        description='Document to insert as JSON, e.g. {"name": "Alice", "age": 30}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBInsertManyConfig(BaseModel):
    operation: Literal["insert_many"] = Field(
        "insert_many",
        json_schema_extra={
            "const": "insert_many", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Insert Many Documents",
            "x-keywords": ["bulk insert", "batch create", "import", "add multiple"],
        },
        title="Insert Many Documents",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    documents: str = Field(
        ..., title="Documents",
        description='JSON array of documents, e.g. [{"name": "Alice"}, {"name": "Bob"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    ordered: str = Field(
        "false", title="Ordered",
        description="If true, aborts on first error. If false (recommended for imports), attempts all and collects errors.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes (abort on first error)", "No (attempt all, recommended)"], "x-enum-searchable": True},
    )


class MongoDBUpdateOneConfig(BaseModel):
    operation: Literal["update_one"] = Field(
        "update_one",
        json_schema_extra={
            "const": "update_one", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Update One Document",
            "x-keywords": ["edit", "patch", "modify", "set field"],
        },
        title="Update One Document",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        description='Query filter as JSON, e.g. {"_id": "abc"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    update: str = Field(
        ..., title="Update",
        description='Update operations as JSON, e.g. {"$set": {"status": "active"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    upsert: str = Field(
        "false", title="Upsert",
        description="Insert if no document matches the filter",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    array_filters: Optional[str] = Field(
        None, title="Array Filters",
        description='Filters for positional $[elem] operators as JSON array, e.g. [{"elem.score": {"$gte": 80}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    hint: Optional[str] = Field(
        None, title="Index Hint",
        description='Index to use for the filter query, e.g. {"status": 1}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    collation: Optional[str] = Field(
        None, title="Collation",
        description='Language-specific string comparison as JSON',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBUpdateManyConfig(BaseModel):
    operation: Literal["update_many"] = Field(
        "update_many",
        json_schema_extra={
            "const": "update_many", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Update Many Documents",
            "x-keywords": ["bulk update", "update all", "batch edit", "modify multiple"],
        },
        title="Update Many Documents",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        description='Query filter as JSON',
        json_schema_extra={"ui:widget": "textarea"},
    )
    update: str = Field(
        ..., title="Update",
        description='Update operations as JSON, e.g. {"$set": {"status": "archived"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    upsert: str = Field(
        "false", title="Upsert",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    array_filters: Optional[str] = Field(
        None, title="Array Filters",
        description='Filters for positional $[elem] operators as JSON array, e.g. [{"elem.score": {"$gte": 80}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    hint: Optional[str] = Field(
        None, title="Index Hint",
        description='Index to use for the filter query, e.g. {"status": 1}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    collation: Optional[str] = Field(
        None, title="Collation",
        description='Language-specific string comparison as JSON',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBReplaceOneConfig(BaseModel):
    operation: Literal["replace_one"] = Field(
        "replace_one",
        json_schema_extra={
            "const": "replace_one", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Replace One Document",
            "x-keywords": ["overwrite", "put", "replace document"],
        },
        title="Replace One Document",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        description='Query filter as JSON',
        json_schema_extra={"ui:widget": "textarea"},
    )
    replacement: str = Field(
        ..., title="Replacement",
        description='Full replacement document as JSON (no update operators)',
        json_schema_extra={"ui:widget": "textarea"},
    )
    upsert: str = Field(
        "false", title="Upsert",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class MongoDBDeleteOneConfig(BaseModel):
    operation: Literal["delete_one"] = Field(
        "delete_one",
        json_schema_extra={
            "const": "delete_one", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Delete One Document",
            "x-keywords": ["remove", "destroy", "delete by id"],
        },
        title="Delete One Document",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        description='Query filter as JSON, e.g. {"_id": "abc"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    hint: Optional[str] = Field(
        None, title="Index Hint",
        json_schema_extra={"ui:widget": "textarea"},
    )
    collation: Optional[str] = Field(
        None, title="Collation",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBDeleteManyConfig(BaseModel):
    operation: Literal["delete_many"] = Field(
        "delete_many",
        json_schema_extra={
            "const": "delete_many", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Delete Many Documents",
            "x-keywords": ["bulk delete", "remove all", "purge", "clear collection"],
        },
        title="Delete Many Documents",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        description='Query filter as JSON — use {} with caution (deletes all documents)',
        json_schema_extra={"ui:widget": "textarea"},
    )
    hint: Optional[str] = Field(
        None, title="Index Hint",
        json_schema_extra={"ui:widget": "textarea"},
    )
    collation: Optional[str] = Field(
        None, title="Collation",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBCountDocumentsConfig(BaseModel):
    operation: Literal["count_documents"] = Field(
        "count_documents",
        json_schema_extra={
            "const": "count_documents", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Count Documents",
            "x-keywords": ["count", "total", "how many", "size"],
        },
        title="Count Documents",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: Optional[str] = Field(
        None, title="Filter",
        description='Optional query filter as JSON (omit to count all documents)',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBBulkWriteConfig(BaseModel):
    operation: Literal["bulk_write"] = Field(
        "bulk_write",
        json_schema_extra={
            "const": "bulk_write", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Bulk Write",
            "x-keywords": ["batch", "bulk operations", "mixed writes", "transaction-like"],
        },
        title="Bulk Write",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    operations: str = Field(
        ..., title="Operations",
        description=(
            'JSON array of write-operation dicts, e.g. '
            '[{"insertOne": {"document": {"x": 1}}}, '
            '{"updateOne": {"filter": {"x": 1}, "update": {"$set": {"y": 2}}}}]'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    ordered: str = Field(
        "false", title="Ordered",
        description="If true, aborts on first error. If false (recommended for imports), attempts all and collects errors.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes (abort on first error)", "No (attempt all, recommended)"], "x-enum-searchable": True},
    )


class MongoDBFindOneAndUpdateConfig(BaseModel):
    operation: Literal["find_one_and_update"] = Field(
        "find_one_and_update",
        json_schema_extra={
            "const": "find_one_and_update", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Find One and Update",
            "x-keywords": ["atomic update", "find and modify", "update and return"],
        },
        title="Find One and Update",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        json_schema_extra={"ui:widget": "textarea"},
    )
    update: str = Field(
        ..., title="Update",
        description='Update operations as JSON, e.g. {"$set": {"status": "done"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    upsert: str = Field(
        "false", title="Upsert",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    return_document: str = Field(
        "after", title="Return Document",
        description="Whether to return the document before or after the update",
        json_schema_extra={"enum": ["before", "after"], "enumNames": ["Before", "After"], "x-enum-searchable": True},
    )
    projection: Optional[str] = Field(
        None, title="Projection",
        json_schema_extra={"ui:widget": "textarea"},
    )
    sort: Optional[str] = Field(
        None, title="Sort",
        description='Sort to determine which document to operate on when multiple match, e.g. {"createdAt": 1}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBFindOneAndDeleteConfig(BaseModel):
    operation: Literal["find_one_and_delete"] = Field(
        "find_one_and_delete",
        json_schema_extra={
            "const": "find_one_and_delete", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Find One and Delete",
            "x-keywords": ["atomic delete", "find and remove", "delete and return"],
        },
        title="Find One and Delete",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        json_schema_extra={"ui:widget": "textarea"},
    )
    projection: Optional[str] = Field(
        None, title="Projection",
        json_schema_extra={"ui:widget": "textarea"},
    )
    sort: Optional[str] = Field(
        None, title="Sort",
        description='Sort to determine which document to operate on when multiple match, e.g. {"createdAt": 1}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBFindOneAndReplaceConfig(BaseModel):
    operation: Literal["find_one_and_replace"] = Field(
        "find_one_and_replace",
        json_schema_extra={
            "const": "find_one_and_replace", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Find One and Replace",
            "x-keywords": ["atomic replace", "find and overwrite", "replace and return"],
        },
        title="Find One and Replace",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    filter: str = Field(
        ..., title="Filter",
        json_schema_extra={"ui:widget": "textarea"},
    )
    replacement: str = Field(
        ..., title="Replacement",
        description='Full replacement document as JSON (no update operators)',
        json_schema_extra={"ui:widget": "textarea"},
    )
    upsert: str = Field(
        "false", title="Upsert",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    return_document: str = Field(
        "after", title="Return Document",
        json_schema_extra={"enum": ["before", "after"], "enumNames": ["Before", "After"], "x-enum-searchable": True},
    )
    projection: Optional[str] = Field(
        None, title="Projection",
        json_schema_extra={"ui:widget": "textarea"},
    )
    sort: Optional[str] = Field(
        None, title="Sort",
        description='Sort to determine which document to operate on when multiple match, e.g. {"createdAt": 1}',
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Aggregation
# ============================================================================


class MongoDBAggregatConfig(BaseModel):
    operation: Literal["aggregate"] = Field(
        "aggregate",
        json_schema_extra={
            "const": "aggregate", "ui:hidden": True,
            "x-category": "Aggregation", "x-is-trigger": False,
            "x-display-name": "Aggregate",
            "x-keywords": ["pipeline", "group by", "join", "lookup", "unwind", "facet"],
        },
        title="Aggregate",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    pipeline: str = Field(
        ..., title="Pipeline",
        description='Aggregation pipeline as a JSON array, e.g. [{"$match": {"active": true}}, {"$group": {"_id": "$category", "count": {"$sum": 1}}}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    allow_disk_use: str = Field(
        "false", title="Allow Disk Use",
        description="Allow MongoDB to write temporary files to disk for large aggregations exceeding 100MB memory limit",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


# ============================================================================
# Operation Configs — Collections
# ============================================================================


class MongoDBListCollectionsConfig(BaseModel):
    operation: Literal["list_collections"] = Field(
        "list_collections",
        json_schema_extra={
            "const": "list_collections", "ui:hidden": True,
            "x-category": "Collections", "x-is-trigger": False,
            "x-display-name": "List Collections",
            "x-keywords": ["show collections", "list tables"],
        },
        title="List Collections",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    filter: Optional[str] = Field(
        None, title="Filter",
        description='Optional filter for collection names as JSON',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBCreateCollectionConfig(BaseModel):
    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "mongodb_collection",
            "x-resource-id-path": "collection",
            "x-category": "Collections", "x-is-trigger": False,
            "x-display-name": "Create Collection",
            "x-keywords": ["new collection", "provision", "create table"],
        },
        title="Create Collection",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    name: str = Field(..., title="Collection Name", description="Name of the new collection")
    capped: str = Field(
        "false", title="Capped",
        description="Create a fixed-size capped collection",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    size: Optional[int] = Field(
        None, title="Max Size (bytes)",
        description="Maximum size in bytes for a capped collection",
    )
    max: Optional[int] = Field(
        None, title="Max Documents",
        description="Maximum number of documents in a capped collection",
    )
    validator: Optional[str] = Field(
        None, title="Schema Validator",
        description='JSON Schema validation document, e.g. {"$jsonSchema": {"bsonType": "object", "required": ["name"], "properties": {"name": {"bsonType": "string"}}}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    validation_level: Optional[str] = Field(
        None, title="Validation Level",
        json_schema_extra={"enum": ["strict", "moderate", "off"], "enumNames": ["Strict", "Moderate", "Off"], "x-enum-searchable": True},
    )
    validation_action: Optional[str] = Field(
        None, title="Validation Action",
        json_schema_extra={"enum": ["error", "warn"], "enumNames": ["Error (reject)", "Warn (allow + log)"], "x-enum-searchable": True},
    )
    time_field: Optional[str] = Field(
        None, title="Time Field (Timeseries)",
        description="Field containing the date/time for time series collections (MongoDB 5.0+)",
    )
    meta_field: Optional[str] = Field(
        None, title="Meta Field (Timeseries)",
        description="Field for time series metadata (labels/tags)",
    )
    granularity: Optional[str] = Field(
        None, title="Granularity (Timeseries)",
        json_schema_extra={"enum": ["seconds", "minutes", "hours"], "enumNames": ["Seconds", "Minutes", "Hours"], "x-enum-searchable": True},
    )


class MongoDBDropCollectionConfig(BaseModel):
    operation: Literal["drop_collection"] = Field(
        "drop_collection",
        json_schema_extra={
            "const": "drop_collection", "ui:hidden": True,
            "x-category": "Collections", "x-is-trigger": False,
            "x-display-name": "Drop Collection",
            "x-keywords": ["delete collection", "remove collection", "drop table"],
        },
        title="Drop Collection",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class MongoDBRenameCollectionConfig(BaseModel):
    operation: Literal["rename_collection"] = Field(
        "rename_collection",
        json_schema_extra={
            "const": "rename_collection", "ui:hidden": True,
            "x-category": "Collections", "x-is-trigger": False,
            "x-display-name": "Rename Collection",
            "x-keywords": ["rename", "move collection", "rename table"],
        },
        title="Rename Collection",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    new_name: str = Field(..., title="New Name", description="New collection name")
    drop_target: str = Field(
        "false", title="Drop Target",
        description="Drop the target collection if it already exists",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


# ============================================================================
# Operation Configs — Indexes
# ============================================================================


class MongoDBCreateIndexConfig(BaseModel):
    operation: Literal["create_index"] = Field(
        "create_index",
        json_schema_extra={
            "const": "create_index", "ui:hidden": True,
            "x-creates-resource": True,
            "x-resource-type": "mongodb_index",
            "x-resource-id-path": "index_name",
            "x-category": "Indexes", "x-is-trigger": False,
            "x-display-name": "Create Index",
            "x-keywords": ["build index", "add index", "compound index", "ttl index", "text index", "geospatial", "hashed", "partial", "sparse"],
        },
        title="Create Index",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    keys: str = Field(
        ..., title="Keys",
        description=(
            'Index key specification as JSON object. Use 1/-1 for ascending/descending, '
            '"text" for text search, "hashed" for hash sharding, "2dsphere"/"2d" for geospatial. '
            'Examples: {"email": 1} {"field1": 1, "field2": -1} {"content": "text"} {"loc": "2dsphere"}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    name: Optional[str] = Field(None, title="Index Name", description="Optional custom index name")
    unique: str = Field(
        "false", title="Unique",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    sparse: str = Field(
        "false", title="Sparse",
        description="Only index documents that contain the indexed field",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    hidden: str = Field(
        "false", title="Hidden",
        description="Hide from query planner without dropping (MongoDB 4.4+)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    expire_after_seconds: Optional[int] = Field(
        None, title="Expire After Seconds (TTL)",
        description="Automatically delete documents after N seconds (TTL index). Must be on a Date field.",
    )
    partial_filter_expression: Optional[str] = Field(
        None, title="Partial Filter Expression",
        description='Only index documents matching this filter, e.g. {"status": "active"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    collation: Optional[str] = Field(
        None, title="Collation",
        description='Language-specific string comparison rules as JSON, e.g. {"locale": "en", "strength": 2}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBListIndexesConfig(BaseModel):
    operation: Literal["list_indexes"] = Field(
        "list_indexes",
        json_schema_extra={
            "const": "list_indexes", "ui:hidden": True,
            "x-category": "Indexes", "x-is-trigger": False,
            "x-display-name": "List Indexes",
            "x-keywords": ["show indexes", "get indexes"],
        },
        title="List Indexes",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class MongoDBDropIndexConfig(BaseModel):
    operation: Literal["drop_index"] = Field(
        "drop_index",
        json_schema_extra={
            "const": "drop_index", "ui:hidden": True,
            "x-category": "Indexes", "x-is-trigger": False,
            "x-display-name": "Drop Index",
            "x-keywords": ["delete index", "remove index"],
        },
        title="Drop Index",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field(..., title="Index Name", json_schema_extra=_INDEX_FIELD_EXTRA)


# ============================================================================
# Operation Configs — Atlas Vector Search
# ============================================================================


class MongoDBVectorSearchConfig(BaseModel):
    operation: Literal["vector_search"] = Field(
        "vector_search",
        json_schema_extra={
            "const": "vector_search", "ui:hidden": True,
            "x-category": "Atlas Vector Search", "x-is-trigger": False,
            "x-display-name": "Vector Search",
            "x-keywords": ["rag", "semantic search", "similarity search", "nearest neighbors", "knn", "ann", "embedding search"],
        },
        title="Vector Search",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field(..., title="Vector Search Index Name", json_schema_extra=_SEARCH_INDEX_FIELD_EXTRA)
    path: str = Field(..., title="Vector Field Path", description="Name of the field containing the vector embeddings")
    query_vector: str = Field(
        ..., title="Query Vector",
        description="Embedding to search with as a JSON array of numbers",
        json_schema_extra={"ui:widget": "textarea"},
    )
    num_candidates: int = Field(100, title="Num Candidates",
        description="Candidates to consider per shard (≥ limit). Ignored when Exact Search is enabled.")
    limit: int = Field(10, title="Limit", description="Number of results to return")
    exact: str = Field(
        "false", title="Exact Search",
        description="Use exact nearest-neighbor (ENN) instead of approximate (ANN). Slower but 100% accurate. Ignores Num Candidates.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes (ENN)", "No (ANN, recommended)"], "x-enum-searchable": True},
    )
    filter: Optional[str] = Field(
        None, title="Pre-Filter",
        description='MQL filter on indexed filter-type fields, e.g. {"category": "news"}. Only fields indexed as type "filter" can be used here.',
        json_schema_extra={"ui:widget": "textarea"},
    )
    project: Optional[str] = Field(
        None, title="Projection",
        description='Fields to include in results. To include the relevance score: {"title": 1, "score": {"$meta": "vectorSearchScore"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    score_details: str = Field(
        "false", title="Score Details",
        description="Include detailed score breakdown per result (accessible via {$meta: 'vectorSearchScoreDetails'})",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class MongoDBCreateVectorSearchIndexConfig(BaseModel):
    operation: Literal["create_vector_search_index"] = Field(
        "create_vector_search_index",
        json_schema_extra={
            "const": "create_vector_search_index", "ui:hidden": True,
            "x-category": "Atlas Vector Search", "x-is-trigger": False,
            "x-display-name": "Create Vector Search Index",
            "x-keywords": ["create vector index", "knn index", "atlas search index", "setup embeddings", "vectorSearch"],
        },
        title="Create Vector Search Index",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field(..., title="Index Name", description="Name for the vector search index")
    path: str = Field(..., title="Vector Field", description="Name of the field storing the embedding vectors")
    num_dimensions: int = Field(1536, title="Dimensions",
        description="Number of dimensions in the embedding vectors (e.g. 1536 for text-embedding-3-small, 3072 for text-embedding-3-large, 768 for nomic-embed)")
    similarity: str = Field(
        "cosine", title="Similarity Function",
        json_schema_extra={
            "enum": ["euclidean", "cosine", "dotProduct"],
            "enumNames": ["Euclidean", "Cosine", "Dot Product"],
            "x-enum-searchable": True,
        },
    )
    filter_fields: Optional[str] = Field(
        None, title="Filter Fields",
        description=(
            'Comma-separated field names to index as filter-type (for pre-filtering in vector search). '
            'E.g. "category,status,user_id". These fields must be boolean, date, number, objectId, string, or UUID.'
        ),
    )


class MongoDBListSearchIndexesConfig(BaseModel):
    operation: Literal["list_search_indexes"] = Field(
        "list_search_indexes",
        json_schema_extra={
            "const": "list_search_indexes", "ui:hidden": True,
            "x-category": "Atlas Vector Search", "x-is-trigger": False,
            "x-display-name": "List Search Indexes",
            "x-keywords": ["show vector indexes", "atlas search indexes"],
        },
        title="List Search Indexes",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class MongoDBUpdateSearchIndexConfig(BaseModel):
    operation: Literal["update_search_index"] = Field(
        "update_search_index",
        json_schema_extra={
            "const": "update_search_index", "ui:hidden": True,
            "x-category": "Atlas Vector Search", "x-is-trigger": False,
            "x-display-name": "Update Search Index",
            "x-keywords": ["modify vector index", "reconfigure search index"],
        },
        title="Update Search Index",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field(..., title="Index Name", json_schema_extra=_SEARCH_INDEX_FIELD_EXTRA)
    definition: str = Field(
        ..., title="Index Definition",
        description='New index definition as JSON, e.g. {"mappings": {"dynamic": true}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBDeleteSearchIndexConfig(BaseModel):
    operation: Literal["delete_search_index"] = Field(
        "delete_search_index",
        json_schema_extra={
            "const": "delete_search_index", "ui:hidden": True,
            "x-category": "Atlas Vector Search", "x-is-trigger": False,
            "x-display-name": "Delete Search Index",
            "x-keywords": ["drop vector index", "remove atlas search index"],
        },
        title="Delete Search Index",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field(..., title="Index Name", json_schema_extra=_SEARCH_INDEX_FIELD_EXTRA)


# ============================================================================
# Operation Configs — Database
# ============================================================================


class MongoDBListDatabasesConfig(BaseModel):
    operation: Literal["list_databases"] = Field(
        "list_databases",
        json_schema_extra={
            "const": "list_databases", "ui:hidden": True,
            "x-category": "Database", "x-is-trigger": False,
            "x-display-name": "List Databases",
            "x-keywords": ["show databases", "list dbs"],
        },
        title="List Databases",
    )


class MongoDBDropDatabaseConfig(BaseModel):
    operation: Literal["drop_database"] = Field(
        "drop_database",
        json_schema_extra={
            "const": "drop_database", "ui:hidden": True,
            "x-category": "Database", "x-is-trigger": False,
            "x-display-name": "Drop Database",
            "x-keywords": ["delete database", "remove database"],
        },
        title="Drop Database",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)


class MongoDBCommandConfig(BaseModel):
    operation: Literal["command"] = Field(
        "command",
        json_schema_extra={
            "const": "command", "ui:hidden": True,
            "x-category": "Database", "x-is-trigger": False,
            "x-display-name": "Run Command",
            "x-keywords": ["admin command", "db command", "raw command", "ping", "serverStatus"],
        },
        title="Run Command",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    command: str = Field(
        ..., title="Command",
        description='Database command as JSON, e.g. {"ping": 1} or {"serverStatus": 1}',
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Upload & Index (RAG)
# ============================================================================


class MongoDBUploadAndIndexConfig(BaseModel):
    operation: Literal["upload_and_index"] = Field(
        "upload_and_index",
        json_schema_extra={
            "const": "upload_and_index", "ui:hidden": True,
            "x-category": "Atlas Vector Search", "x-is-trigger": False,
            "x-display-name": "Upload & Index Document",
            "x-keywords": ["upload", "ingest", "index document", "rag", "embed file", "add pdf", "vector store"],
        },
        title="Upload & Index Document",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    document: str = Field(
        ..., title="Document",
        description=(
            "Upload a PDF/DOCX/TXT/MD/CSV file (or paste a URL / reference an upstream file). "
            "It is chunked, embedded with text-embedding-3-small, and inserted."
        ),
        json_schema_extra={"ui:widget": "media_upload", "accept": DOCUMENT_ACCEPT},
    )
    vector_field: str = Field("embedding", title="Vector Field", description="Field to store embedding vectors")
    text_field: str = Field("text", title="Text Field", description="Field to store the chunk text")
    metadata_field: str = Field("metadata", title="Metadata Field", description="Field to store chunk metadata")
    chunk_size: int = Field(1000, title="Chunk Size", description="Characters per chunk")
    chunk_overlap: int = Field(200, title="Chunk Overlap", description="Overlapping characters between chunks")
    id_prefix: Optional[str] = Field(None, title="ID Prefix", description="Optional prefix for chunk IDs (defaults to the filename)")


class MongoDBDistinctConfig(BaseModel):
    operation: Literal["distinct"] = Field(
        "distinct",
        json_schema_extra={
            "const": "distinct", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Distinct Values",
            "x-keywords": ["unique values", "enum field values", "list distinct", "unique"],
        },
        title="Distinct Values",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    field: str = Field(..., title="Field Name", description='Field to get distinct values for, e.g. "status" or "tags"')
    filter: Optional[str] = Field(
        None, title="Filter",
        description='Optional query filter to restrict which documents are considered, e.g. {"active": true}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBEstimatedDocumentCountConfig(BaseModel):
    operation: Literal["estimated_document_count"] = Field(
        "estimated_document_count",
        json_schema_extra={
            "const": "estimated_document_count", "ui:hidden": True,
            "x-category": "Documents", "x-is-trigger": False,
            "x-display-name": "Estimated Document Count",
            "x-keywords": ["fast count", "approximate count", "collection size", "total documents"],
        },
        title="Estimated Document Count",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class MongoDBDropIndexesConfig(BaseModel):
    operation: Literal["drop_indexes"] = Field(
        "drop_indexes",
        json_schema_extra={
            "const": "drop_indexes", "ui:hidden": True,
            "x-category": "Indexes", "x-is-trigger": False,
            "x-display-name": "Drop All Indexes",
            "x-keywords": ["remove all indexes", "reset indexes", "clear indexes"],
        },
        title="Drop All Indexes",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)


class MongoDBCreateAtlasSearchIndexConfig(BaseModel):
    operation: Literal["create_atlas_search_index"] = Field(
        "create_atlas_search_index",
        json_schema_extra={
            "const": "create_atlas_search_index", "ui:hidden": True,
            "x-category": "Atlas Search", "x-is-trigger": False,
            "x-display-name": "Create Atlas Search Index",
            "x-keywords": ["full text search", "lucene", "autocomplete", "facet", "atlas search index"],
        },
        title="Create Atlas Search Index",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field("default", title="Index Name", description='Name for the search index (use "default" to make it the default)')
    dynamic: str = Field(
        "true", title="Dynamic Mapping",
        description="Auto-index all string fields when enabled. Disable to specify field mappings manually.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Dynamic (auto-index all strings)", "Static (specify fields)"], "x-enum-searchable": True},
    )
    field_mappings: Optional[str] = Field(
        None, title="Field Mappings",
        description=(
            'Field mapping definitions as JSON array per field (used when Dynamic Mapping is disabled). '
            'E.g. {"title": [{"type": "string", "analyzer": "lucene.standard"}], "plot": [{"type": "string"}]}. '
            'Use "type": "token" for fields used in string facets (required by Atlas facet search).'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    analyzer: Optional[str] = Field(
        None, title="Analyzer",
        description='Default analyzer for string fields, e.g. "lucene.standard", "lucene.english", "lucene.whitespace"',
    )


class MongoDBAtlasTextSearchConfig(BaseModel):
    operation: Literal["atlas_text_search"] = Field(
        "atlas_text_search",
        json_schema_extra={
            "const": "atlas_text_search", "ui:hidden": True,
            "x-category": "Atlas Search", "x-is-trigger": False,
            "x-display-name": "Atlas Text Search",
            "x-keywords": ["full text search", "$search", "lucene", "autocomplete", "fuzzy", "phrase search", "atlas search"],
        },
        title="Atlas Text Search",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field("default", title="Index Name", json_schema_extra=_SEARCH_INDEX_FIELD_EXTRA)
    query: str = Field(..., title="Search Query", description="Text to search for")
    search_operator: Optional[str] = Field(
        None, title="Search Operator (Advanced)",
        description=(
            'Full $search operator as JSON for compound, phrase, autocomplete, range, etc. '
            'When provided, overrides the Query and Search Fields above. '
            'E.g. {"compound": {"must": [{"text": {"query": "coffee", "path": "name"}}], '
            '"should": [{"text": {"query": "organic", "path": "tags"}}]}}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    search_fields: Optional[str] = Field(
        None, title="Search Fields",
        description='Comma-separated field names to search in, e.g. "title,plot,description". Leave blank to search all indexed fields.',
    )
    fuzzy: str = Field(
        "false", title="Fuzzy Search",
        description="Enable fuzzy matching to tolerate typos and spelling variations",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    limit: int = Field(10, title="Limit", description="Maximum number of results to return")
    projection: Optional[str] = Field(
        None, title="Projection",
        description='Fields to include/exclude, e.g. {"title": 1, "plot": 1, "score": {"$meta": "searchScore"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBAtlasFacetSearchConfig(BaseModel):
    operation: Literal["atlas_facet_search"] = Field(
        "atlas_facet_search",
        json_schema_extra={
            "const": "atlas_facet_search", "ui:hidden": True,
            "x-category": "Atlas Search", "x-is-trigger": False,
            "x-display-name": "Atlas Facet Search",
            "x-keywords": ["facets", "aggregations", "counts", "faceted navigation", "searchMeta"],
        },
        title="Atlas Facet Search",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    index_name: str = Field("default", title="Index Name", json_schema_extra=_SEARCH_INDEX_FIELD_EXTRA)
    query: str = Field(..., title="Search Query", description="Text to search for")
    facets: str = Field(
        ..., title="Facets",
        description=(
            'Facet definitions as JSON. String facet: {"genre": {"type": "string", "path": "genre"}} — '
            'IMPORTANT: the indexed field must use "type": "token" in the Atlas Search index (not "string"). '
            'Numeric: {"price": {"type": "number", "path": "price", "boundaries": [0, 50, 100, 200]}}. '
            'Date: {"year": {"type": "date", "path": "date", "boundaries": ["2020-01-01", "2021-01-01"]}}'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class MongoDBCreateIndexesConfig(BaseModel):
    operation: Literal["create_indexes"] = Field(
        "create_indexes",
        json_schema_extra={
            "const": "create_indexes", "ui:hidden": True,
            "x-category": "Indexes", "x-is-trigger": False,
            "x-display-name": "Create Multiple Indexes",
            "x-keywords": ["batch indexes", "multiple indexes", "setup indexes"],
        },
        title="Create Multiple Indexes",
    )
    database: str = Field(..., title="Database", json_schema_extra=_DATABASE_FIELD_EXTRA)
    collection: str = Field(..., title="Collection", json_schema_extra=_COLLECTION_FIELD_EXTRA)
    indexes: str = Field(
        ..., title="Index Specifications",
        description=(
            'JSON array of index spec objects, each with "keys" (required) and optional "name", "unique", '
            '"sparse", "expireAfterSeconds", "partialFilterExpression". '
            'E.g. [{"keys": {"email": 1}, "unique": true}, {"keys": {"createdAt": 1}, "expireAfterSeconds": 3600}]'
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Discriminated Union (38 operations)
# ============================================================================


MongoDBConfig = Annotated[
    Union[
        # Documents
        MongoDBFindConfig,
        MongoDBFindOneConfig,
        MongoDBInsertOneConfig,
        MongoDBInsertManyConfig,
        MongoDBUpdateOneConfig,
        MongoDBUpdateManyConfig,
        MongoDBReplaceOneConfig,
        MongoDBDeleteOneConfig,
        MongoDBDeleteManyConfig,
        MongoDBCountDocumentsConfig,
        MongoDBEstimatedDocumentCountConfig,
        MongoDBDistinctConfig,
        MongoDBBulkWriteConfig,
        MongoDBFindOneAndUpdateConfig,
        MongoDBFindOneAndDeleteConfig,
        MongoDBFindOneAndReplaceConfig,
        # Aggregation
        MongoDBAggregatConfig,
        # Collections
        MongoDBListCollectionsConfig,
        MongoDBCreateCollectionConfig,
        MongoDBDropCollectionConfig,
        MongoDBRenameCollectionConfig,
        # Indexes
        MongoDBCreateIndexConfig,
        MongoDBListIndexesConfig,
        MongoDBDropIndexConfig,
        MongoDBDropIndexesConfig,
        # Atlas Vector Search
        MongoDBVectorSearchConfig,
        MongoDBCreateVectorSearchIndexConfig,
        MongoDBListSearchIndexesConfig,
        MongoDBUpdateSearchIndexConfig,
        MongoDBDeleteSearchIndexConfig,
        # Atlas Search (full-text)
        MongoDBAtlasTextSearchConfig,
        MongoDBCreateAtlasSearchIndexConfig,
        MongoDBAtlasFacetSearchConfig,
        # Database
        MongoDBListDatabasesConfig,
        MongoDBDropDatabaseConfig,
        MongoDBCommandConfig,
        # Upload & Index
        MongoDBUploadAndIndexConfig,
        # Indexes (batch)
        MongoDBCreateIndexesConfig,
    ],
    Discriminator("operation"),
]


class MongoDBNodeConfig(NodeConfig[MongoDBConfig, MongoDBCredential]):
    pass


# ============================================================================
# Helpers
# ============================================================================


def _parse_json(s: Any, name: str) -> Any:
    """Parse a JSON string, raising a descriptive ValueError on failure."""
    if isinstance(s, (dict, list)):
        return s
    if not s:
        raise ValueError(f"`{name}` is required and must be valid JSON")
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"`{name}` must be valid JSON: {exc}") from exc


def _parse_json_opt(s: Optional[str], name: str) -> Optional[Any]:
    """Parse a JSON string if present, returning None for empty/None input."""
    if not s or not s.strip():
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"`{name}` must be valid JSON: {exc}") from exc


def _bool_field(value: str) -> bool:
    return value == "true"


def _serialize_doc(doc: Any) -> Any:
    """Recursively convert MongoDB-specific types to JSON-serializable form."""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [_serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        return {k: _serialize_doc(v) for k, v in doc.items()}
    # ObjectId, Decimal128, etc. — convert via str
    type_name = type(doc).__name__
    if type_name in ("ObjectId", "Decimal128", "Int64", "Int32", "Binary"):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    if isinstance(doc, date):
        return doc.isoformat()
    if isinstance(doc, bytes):
        return doc.hex()
    return doc


def _serialize(docs: Any) -> Any:
    """Top-level serializer for cursor results (list or single doc)."""
    return _serialize_doc(docs)


# ============================================================================
# Node Implementation
# ============================================================================


class MongoDBNode(WorkflowNode):
    """MongoDB database automation node."""

    edit_examples = [
        "Find all active users in a MongoDB collection",
        "Insert a new document into a MongoDB collection",
        "Update documents matching a filter with new field values",
        "Run a MongoDB aggregation pipeline with $group and $sort",
        "Perform Atlas Vector Search on an embeddings collection",
        "Upload a PDF and index it for RAG retrieval in MongoDB Atlas",
    ]

    @classmethod
    def get_config_model(cls):
        return MongoDBNodeConfig

    @staticmethod
    def _get_client(credential_data: Dict[str, Any]):
        """Create a fresh AsyncIOMotorClient from the connection string."""
        from motor.motor_asyncio import AsyncIOMotorClient
        conn_str = (credential_data or {}).get("connection_string", "")
        if not conn_str:
            raise ValueError("MongoDB connection string is required")
        _install_pymongo_socket_pin()
        private_hosts_allowed = allow_private_hosts()
        if not private_hosts_allowed:
            # Keep this guard at the constructor boundary as well as in the
            # async topology check. Motor/PyMongo may otherwise source cloud
            # credentials, open TLS key files, or route via an unguarded proxy
            # while constructing the client.
            _assert_safe_mongodb_credential_options(
                _mongodb_driver_query(conn_str)
            )
        kwargs: Dict[str, Any] = {"serverSelectionTimeoutMS": 10000}
        # A plain URI is constrained to one seed by the policy check. Pinning
        # direct mode stops a public seed's `hello` response from adding private
        # replica-set members behind the SSRF guard. Atlas SRV topology remains
        # available because its DNS and advertised hosts stay under the
        # provider-owned mongodb.net boundary and TLS verification is required.
        if (
            not private_hosts_allowed
            and conn_str.startswith("mongodb://")
            and not _plain_mongodb_uses_trusted_atlas_topology(conn_str)
        ):
            kwargs["directConnection"] = True
        return AsyncIOMotorClient(conn_str, **kwargs)

    @staticmethod
    async def _assert_connection_allowed(connection_string: str) -> None:
        """Validate the complete MongoDB connection/topology trust boundary."""
        if not connection_string.startswith(("mongodb://", "mongodb+srv://")):
            raise SSRFError("MongoDB connection string must use mongodb:// or mongodb+srv://")
        if allow_private_hosts():
            return

        parts, raw_options = _mongodb_uri_parts(connection_string)
        is_srv = parts.scheme == "mongodb+srv"
        if is_srv:
            seed_host = (parts.hostname or "").lower().rstrip(".")
            if not seed_host:
                raise SSRFError("MongoDB connection string has no host")
            # Arbitrary SRV domains and independently sampled srvMaxHosts sets
            # let a public seed steer Motor to an unvalidated topology. Atlas is
            # the managed topology this integration supports without an egress
            # firewall: SRV answers and hello-advertised hosts remain beneath a
            # provider-owned suffix, with certificate/hostname checks intact.
            if not _is_atlas_host(seed_host):
                raise SSRFError(
                    "MongoDB SRV connections must use MongoDB Atlas (*.mongodb.net); "
                    "other SRV topologies require OUTBOUND_ALLOW_PRIVATE_IPS on a "
                    "trusted network"
                )
            if "srvmaxhosts" in raw_options:
                raise SSRFError("MongoDB srvMaxHosts is not allowed by the outbound policy")
            if "srvservicename" in raw_options:
                raise SSRFError(
                    "MongoDB custom SRV service names are not allowed by the outbound policy"
                )
            if raw_options.get("tls") is False:
                raise SSRFError("MongoDB Atlas connections must keep TLS enabled")
        if any(
            raw_options.get(name) is True
            for name in (
                "tlsinsecure",
                "tlsallowinvalidcertificates",
                "tlsallowinvalidhostnames",
            )
        ):
            raise SSRFError(
                "MongoDB connections must verify TLS certificates and hostnames"
            )

        from pymongo.uri_parser import parse_uri

        try:
            parsed = await asyncio.to_thread(
                parse_uri,
                connection_string,
                connect_timeout=5.0,
            )
        except Exception as e:
            raise SSRFError(
                "MongoDB connection string is invalid or its SRV target could not be resolved"
            ) from e
        nodes = parsed.get("nodelist") or []
        if not nodes:
            raise SSRFError("MongoDB connection string did not resolve to any host")
        parsed_options = {
            str(key).lower(): value
            for key, value in (parsed.get("options") or {}).items()
        }
        if parsed_options.get("tls") is not True:
            raise SSRFError("Public MongoDB connections must use TLS")

        trusted_atlas_topology = all(
            _is_atlas_host(str(host)) for host, _port in nodes
        )
        if is_srv and not trusted_atlas_topology:
            raise SSRFError(
                "MongoDB Atlas SRV resolution left the trusted mongodb.net domain"
            )
        if not is_srv and not trusted_atlas_topology:
            if len(nodes) != 1:
                raise SSRFError(
                    "Plain MongoDB connections are limited to one direct seed host"
                )
            if "replicaset" in parsed_options or parsed_options.get("loadbalanced") is True:
                raise SSRFError(
                    "Plain MongoDB connections are limited to direct single-host mode; "
                    "use an Atlas URI for managed replica topology"
                )
            if parsed_options.get("directconnection") is False:
                raise SSRFError(
                    "Plain MongoDB connections must not disable directConnection"
                )
        for host, port in nodes:
            await assert_host_allowed(str(host), int(port))

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ctx = context or {}

        def _filter(names: List[str]) -> List[Dict[str, Any]]:
            return [
                {"value": n, "label": n}
                for n in names
                if isinstance(n, str) and n and (not search or search.lower() in n.lower())
            ]

        client = None
        try:
            await cls._assert_connection_allowed(
                (credential_data or {}).get("connection_string", "")
            )
            client = cls._get_client(credential_data)

            if field_name == "database":
                names = await client.list_database_names()
                return _filter(names)

            if field_name == "collection":
                db_name = ctx.get("database")
                if not db_name:
                    return []
                names = await client[db_name].list_collection_names()
                return _filter(names)

            if field_name == "index_name":
                db_name = ctx.get("database")
                coll_name = ctx.get("collection")
                if not db_name or not coll_name:
                    return []
                collection = client[db_name][coll_name]
                cursor = collection.list_indexes()
                names = [idx.get("name", "") async for idx in cursor if idx.get("name")]
                return _filter(names)

            if field_name == "search_index_name":
                db_name = ctx.get("database")
                coll_name = ctx.get("collection")
                if not db_name or not coll_name:
                    return []
                collection = client[db_name][coll_name]
                names = [
                    idx.get("name", "")
                    async for idx in collection.list_search_indexes()
                    if idx.get("name")
                ]
                return _filter(names)

            return []
        except Exception as exc:
            logger.warning(f"[MongoDBNode] load_field_options ({field_name}): {exc}")
            return []
        finally:
            if client is not None:
                client.close()

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not config or not isinstance(config, MongoDBNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your MongoDB connection string.")

        op_config = config.config
        credential_data = credentials.model_dump()
        await self._assert_connection_allowed(credentials.connection_string)

        handlers = {
            # Documents
            "find": self._handle_find,
            "find_one": self._handle_find_one,
            "insert_one": self._handle_insert_one,
            "insert_many": self._handle_insert_many,
            "update_one": self._handle_update_one,
            "update_many": self._handle_update_many,
            "replace_one": self._handle_replace_one,
            "delete_one": self._handle_delete_one,
            "delete_many": self._handle_delete_many,
            "count_documents": self._handle_count_documents,
            "estimated_document_count": self._handle_estimated_document_count,
            "distinct": self._handle_distinct,
            "bulk_write": self._handle_bulk_write,
            "find_one_and_update": self._handle_find_one_and_update,
            "find_one_and_delete": self._handle_find_one_and_delete,
            "find_one_and_replace": self._handle_find_one_and_replace,
            # Aggregation
            "aggregate": self._handle_aggregate,
            # Collections
            "list_collections": self._handle_list_collections,
            "create_collection": self._handle_create_collection,
            "drop_collection": self._handle_drop_collection,
            "rename_collection": self._handle_rename_collection,
            # Indexes
            "create_index": self._handle_create_index,
            "list_indexes": self._handle_list_indexes,
            "drop_index": self._handle_drop_index,
            "drop_indexes": self._handle_drop_indexes,
            # Atlas Vector Search
            "vector_search": self._handle_vector_search,
            "create_vector_search_index": self._handle_create_vector_search_index,
            "list_search_indexes": self._handle_list_search_indexes,
            "update_search_index": self._handle_update_search_index,
            "delete_search_index": self._handle_delete_search_index,
            # Atlas Search (full-text)
            "atlas_text_search": self._handle_atlas_text_search,
            "create_atlas_search_index": self._handle_create_atlas_search_index,
            "atlas_facet_search": self._handle_atlas_facet_search,
            # Database
            "list_databases": self._handle_list_databases,
            "drop_database": self._handle_drop_database,
            "command": self._handle_command,
            # Upload & Index
            "upload_and_index": self._handle_upload_and_index,
            # Indexes (batch)
            "create_indexes": self._handle_create_indexes,
        }
        handler = handlers.get(op_config.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op_config.operation}")

        return await handler(op_config, credential_data)

    # =========================================================================
    # Document handlers
    # =========================================================================

    async def _handle_find(self, config: MongoDBFindConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json_opt(config.filter, "filter") or {}
            projection = _parse_json_opt(config.projection, "projection")
            sort_doc = _parse_json_opt(config.sort, "sort")
            hint_doc = _parse_json_opt(config.hint, "hint")
            collation_doc = _parse_json_opt(config.collation, "collation")
            cursor = coll.find(filter_doc, projection)
            if sort_doc:
                cursor = cursor.sort(list(sort_doc.items()))
            if config.skip:
                cursor = cursor.skip(config.skip)
            if config.limit:
                cursor = cursor.limit(config.limit)
            if hint_doc:
                cursor = cursor.hint(hint_doc)
            if collation_doc:
                cursor = cursor.collation(collation_doc)
            docs = await cursor.to_list(length=config.limit or None)
            return {"status": "success", "action": "find", "documents": _serialize(docs), "count": len(docs)}
        finally:
            client.close()

    async def _handle_find_one(self, config: MongoDBFindOneConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            projection = _parse_json_opt(config.projection, "projection")
            hint_doc = _parse_json_opt(config.hint, "hint")
            collation_doc = _parse_json_opt(config.collation, "collation")
            kwargs: Dict[str, Any] = {}
            if hint_doc:
                kwargs["hint"] = hint_doc
            if collation_doc:
                kwargs["collation"] = collation_doc
            doc = await coll.find_one(filter_doc, projection, **kwargs)
            return {"status": "success", "action": "find_one", "document": _serialize(doc), "found": doc is not None}
        finally:
            client.close()

    async def _handle_insert_one(self, config: MongoDBInsertOneConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            document = _parse_json(config.document, "document")
            result = await coll.insert_one(document)
            return {"status": "success", "action": "insert_one", "inserted_id": str(result.inserted_id)}
        finally:
            client.close()

    async def _handle_insert_many(self, config: MongoDBInsertManyConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            documents = _parse_json(config.documents, "documents")
            if not isinstance(documents, list):
                raise ValueError("`documents` must be a JSON array")
            result = await coll.insert_many(documents, ordered=_bool_field(config.ordered))
            return {
                "status": "success", "action": "insert_many",
                "inserted_count": len(result.inserted_ids),
                "inserted_ids": [str(oid) for oid in result.inserted_ids],
            }
        finally:
            client.close()

    async def _handle_update_one(self, config: MongoDBUpdateOneConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            update_doc = _parse_json(config.update, "update")
            array_filters = _parse_json_opt(config.array_filters, "array_filters")
            hint_doc = _parse_json_opt(config.hint, "hint")
            collation_doc = _parse_json_opt(config.collation, "collation")
            kwargs: Dict[str, Any] = {"upsert": _bool_field(config.upsert)}
            if array_filters is not None:
                kwargs["array_filters"] = array_filters
            if hint_doc:
                kwargs["hint"] = hint_doc
            if collation_doc:
                kwargs["collation"] = collation_doc
            result = await coll.update_one(filter_doc, update_doc, **kwargs)
            return {
                "status": "success", "action": "update_one",
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_id": str(result.upserted_id) if result.upserted_id else None,
            }
        finally:
            client.close()

    async def _handle_update_many(self, config: MongoDBUpdateManyConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            update_doc = _parse_json(config.update, "update")
            array_filters = _parse_json_opt(config.array_filters, "array_filters")
            hint_doc = _parse_json_opt(config.hint, "hint")
            collation_doc = _parse_json_opt(config.collation, "collation")
            kwargs: Dict[str, Any] = {"upsert": _bool_field(config.upsert)}
            if array_filters is not None:
                kwargs["array_filters"] = array_filters
            if hint_doc:
                kwargs["hint"] = hint_doc
            if collation_doc:
                kwargs["collation"] = collation_doc
            result = await coll.update_many(filter_doc, update_doc, **kwargs)
            return {
                "status": "success", "action": "update_many",
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_id": str(result.upserted_id) if result.upserted_id else None,
            }
        finally:
            client.close()

    async def _handle_replace_one(self, config: MongoDBReplaceOneConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            replacement = _parse_json(config.replacement, "replacement")
            result = await coll.replace_one(filter_doc, replacement, upsert=_bool_field(config.upsert))
            return {
                "status": "success", "action": "replace_one",
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_id": str(result.upserted_id) if result.upserted_id else None,
            }
        finally:
            client.close()

    async def _handle_delete_one(self, config: MongoDBDeleteOneConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            hint_doc = _parse_json_opt(config.hint, "hint")
            collation_doc = _parse_json_opt(config.collation, "collation")
            kwargs: Dict[str, Any] = {}
            if hint_doc:
                kwargs["hint"] = hint_doc
            if collation_doc:
                kwargs["collation"] = collation_doc
            result = await coll.delete_one(filter_doc, **kwargs)
            return {"status": "success", "action": "delete_one", "deleted_count": result.deleted_count}
        finally:
            client.close()

    async def _handle_delete_many(self, config: MongoDBDeleteManyConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            hint_doc = _parse_json_opt(config.hint, "hint")
            collation_doc = _parse_json_opt(config.collation, "collation")
            kwargs: Dict[str, Any] = {}
            if hint_doc:
                kwargs["hint"] = hint_doc
            if collation_doc:
                kwargs["collation"] = collation_doc
            result = await coll.delete_many(filter_doc, **kwargs)
            return {"status": "success", "action": "delete_many", "deleted_count": result.deleted_count}
        finally:
            client.close()

    async def _handle_count_documents(self, config: MongoDBCountDocumentsConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json_opt(config.filter, "filter") or {}
            count = await coll.count_documents(filter_doc)
            return {"status": "success", "action": "count_documents", "count": count}
        finally:
            client.close()

    async def _handle_estimated_document_count(self, config: MongoDBEstimatedDocumentCountConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            count = await coll.estimated_document_count()
            return {"status": "success", "action": "estimated_document_count", "count": count}
        finally:
            client.close()

    async def _handle_distinct(self, config: MongoDBDistinctConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json_opt(config.filter, "filter")
            values = await coll.distinct(config.field, filter=filter_doc)
            return {"status": "success", "action": "distinct", "field": config.field, "values": _serialize(values), "count": len(values)}
        finally:
            client.close()

    async def _handle_bulk_write(self, config: MongoDBBulkWriteConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        from pymongo import InsertOne, UpdateOne, UpdateMany, ReplaceOne, DeleteOne, DeleteMany
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            raw_ops = _parse_json(config.operations, "operations")
            if not isinstance(raw_ops, list):
                raise ValueError("`operations` must be a JSON array")

            # Map JSON op dicts to pymongo WriteOperation objects
            op_map = {
                "insertOne": lambda d: InsertOne(d["document"]),
                "updateOne": lambda d: UpdateOne(d["filter"], d["update"], upsert=d.get("upsert", False)),
                "updateMany": lambda d: UpdateMany(d["filter"], d["update"], upsert=d.get("upsert", False)),
                "replaceOne": lambda d: ReplaceOne(d["filter"], d["replacement"], upsert=d.get("upsert", False)),
                "deleteOne": lambda d: DeleteOne(d["filter"]),
                "deleteMany": lambda d: DeleteMany(d["filter"]),
            }
            ops = []
            for raw in raw_ops:
                if not isinstance(raw, dict) or len(raw) != 1:
                    raise ValueError(f"Each bulk operation must be a dict with a single key, got: {raw}")
                op_type, op_body = next(iter(raw.items()))
                builder = op_map.get(op_type)
                if not builder:
                    raise ValueError(f"Unknown bulk write operation type: {op_type}")
                ops.append(builder(op_body))

            result = await coll.bulk_write(ops, ordered=_bool_field(config.ordered))
            return {
                "status": "success", "action": "bulk_write",
                "inserted_count": result.inserted_count,
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "deleted_count": result.deleted_count,
                "upserted_count": result.upserted_count,
            }
        finally:
            client.close()

    async def _handle_find_one_and_update(self, config: MongoDBFindOneAndUpdateConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        from pymongo import ReturnDocument
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            update_doc = _parse_json(config.update, "update")
            projection = _parse_json_opt(config.projection, "projection")
            sort_doc = _parse_json_opt(config.sort, "sort")
            return_doc = ReturnDocument.AFTER if config.return_document == "after" else ReturnDocument.BEFORE
            kwargs: Dict[str, Any] = {
                "upsert": _bool_field(config.upsert),
                "return_document": return_doc,
                "projection": projection,
            }
            if sort_doc:
                kwargs["sort"] = list(sort_doc.items())
            doc = await coll.find_one_and_update(filter_doc, update_doc, **kwargs)
            return {"status": "success", "action": "find_one_and_update", "document": _serialize(doc), "found": doc is not None}
        finally:
            client.close()

    async def _handle_find_one_and_delete(self, config: MongoDBFindOneAndDeleteConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            projection = _parse_json_opt(config.projection, "projection")
            sort_doc = _parse_json_opt(config.sort, "sort")
            kwargs: Dict[str, Any] = {"projection": projection}
            if sort_doc:
                kwargs["sort"] = list(sort_doc.items())
            doc = await coll.find_one_and_delete(filter_doc, **kwargs)
            return {"status": "success", "action": "find_one_and_delete", "document": _serialize(doc), "found": doc is not None}
        finally:
            client.close()

    async def _handle_find_one_and_replace(self, config: MongoDBFindOneAndReplaceConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        from pymongo import ReturnDocument
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            filter_doc = _parse_json(config.filter, "filter")
            replacement = _parse_json(config.replacement, "replacement")
            projection = _parse_json_opt(config.projection, "projection")
            sort_doc = _parse_json_opt(config.sort, "sort")
            return_doc = ReturnDocument.AFTER if config.return_document == "after" else ReturnDocument.BEFORE
            kwargs: Dict[str, Any] = {
                "upsert": _bool_field(config.upsert),
                "return_document": return_doc,
                "projection": projection,
            }
            if sort_doc:
                kwargs["sort"] = list(sort_doc.items())
            doc = await coll.find_one_and_replace(filter_doc, replacement, **kwargs)
            return {"status": "success", "action": "find_one_and_replace", "document": _serialize(doc), "found": doc is not None}
        finally:
            client.close()

    # =========================================================================
    # Aggregation handler
    # =========================================================================

    async def _handle_aggregate(self, config: MongoDBAggregatConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            pipeline = _parse_json(config.pipeline, "pipeline")
            if not isinstance(pipeline, list):
                raise ValueError("`pipeline` must be a JSON array of aggregation stages")
            docs = await coll.aggregate(pipeline, allowDiskUse=_bool_field(config.allow_disk_use)).to_list(length=None)
            return {"status": "success", "action": "aggregate", "documents": _serialize(docs), "count": len(docs)}
        finally:
            client.close()

    # =========================================================================
    # Collection handlers
    # =========================================================================

    async def _handle_list_collections(self, config: MongoDBListCollectionsConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            db = client[config.database]
            filter_doc = _parse_json_opt(config.filter, "filter")
            kwargs = {"filter": filter_doc} if filter_doc else {}
            names = await db.list_collection_names(**kwargs)
            return {"status": "success", "action": "list_collections", "collections": names, "count": len(names)}
        finally:
            client.close()

    async def _handle_create_collection(self, config: MongoDBCreateCollectionConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            db = client[config.database]
            kwargs: Dict[str, Any] = {}
            if _bool_field(config.capped):
                kwargs["capped"] = True
                if config.size is not None:
                    kwargs["size"] = config.size
                if config.max is not None:
                    kwargs["max"] = config.max
            validator_doc = _parse_json_opt(config.validator, "validator")
            if validator_doc:
                kwargs["validator"] = validator_doc
            if config.validation_level:
                kwargs["validationLevel"] = config.validation_level
            if config.validation_action:
                kwargs["validationAction"] = config.validation_action
            if config.time_field:
                timeseries: Dict[str, Any] = {"timeField": config.time_field}
                if config.meta_field:
                    timeseries["metaField"] = config.meta_field
                if config.granularity:
                    timeseries["granularity"] = config.granularity
                kwargs["timeseries"] = timeseries
            await db.create_collection(config.name, **kwargs)
            return {"status": "success", "action": "create_collection", "collection": config.name}
        finally:
            client.close()

    async def _handle_drop_collection(self, config: MongoDBDropCollectionConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            await client[config.database].drop_collection(config.collection)
            return {"status": "success", "action": "drop_collection", "collection": config.collection}
        finally:
            client.close()

    async def _handle_rename_collection(self, config: MongoDBRenameCollectionConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            await coll.rename(config.new_name, dropTarget=_bool_field(config.drop_target))
            return {
                "status": "success", "action": "rename_collection",
                "old_name": config.collection, "new_name": config.new_name,
            }
        finally:
            client.close()

    # =========================================================================
    # Index handlers
    # =========================================================================

    async def _handle_create_index(self, config: MongoDBCreateIndexConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            keys = _parse_json(config.keys, "keys")
            if not isinstance(keys, dict):
                raise ValueError("`keys` must be a JSON object, e.g. {\"email\": 1}")
            kwargs: Dict[str, Any] = {
                "unique": _bool_field(config.unique),
                "sparse": _bool_field(config.sparse),
                "hidden": _bool_field(config.hidden),
            }
            if config.name:
                kwargs["name"] = config.name
            if config.expire_after_seconds is not None:
                kwargs["expireAfterSeconds"] = config.expire_after_seconds
            partial = _parse_json_opt(config.partial_filter_expression, "partial_filter_expression")
            if partial:
                kwargs["partialFilterExpression"] = partial
            collation = _parse_json_opt(config.collation, "collation")
            if collation:
                kwargs["collation"] = collation
            index_name = await coll.create_index(list(keys.items()), **kwargs)
            return {"status": "success", "action": "create_index", "index_name": index_name}
        finally:
            client.close()

    async def _handle_list_indexes(self, config: MongoDBListIndexesConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            indexes = await coll.index_information()
            return {"status": "success", "action": "list_indexes", "indexes": _serialize(indexes), "count": len(indexes)}
        finally:
            client.close()

    async def _handle_drop_index(self, config: MongoDBDropIndexConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            await coll.drop_index(config.index_name)
            return {"status": "success", "action": "drop_index", "index_name": config.index_name}
        finally:
            client.close()

    async def _handle_drop_indexes(self, config: MongoDBDropIndexesConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            await coll.drop_indexes()
            return {"status": "success", "action": "drop_indexes", "collection": config.collection, "note": "All non-_id indexes dropped"}
        finally:
            client.close()

    # =========================================================================
    # Atlas Vector Search handlers
    # =========================================================================

    async def _handle_vector_search(self, config: MongoDBVectorSearchConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            query_vector = _parse_json(config.query_vector, "query_vector")
            if not isinstance(query_vector, list):
                raise ValueError("`query_vector` must be a JSON array of numbers")
            filter_doc = _parse_json_opt(config.filter, "filter")
            project_doc = _parse_json_opt(config.project, "project")
            exact = _bool_field(config.exact)

            vector_search_stage: Dict[str, Any] = {
                "index": config.index_name,
                "path": config.path,
                "queryVector": query_vector,
                "limit": config.limit,
            }
            if exact:
                vector_search_stage["exact"] = True
            else:
                vector_search_stage["numCandidates"] = config.num_candidates
            if filter_doc:
                vector_search_stage["filter"] = filter_doc
            if _bool_field(config.score_details):
                vector_search_stage["scoreDetails"] = True

            pipeline: List[Any] = [{"$vectorSearch": vector_search_stage}]
            if project_doc:
                pipeline.append({"$project": project_doc})

            docs = await coll.aggregate(pipeline).to_list(length=None)
            return {"status": "success", "action": "vector_search", "documents": _serialize(docs), "count": len(docs)}
        finally:
            client.close()

    async def _handle_create_vector_search_index(self, config: MongoDBCreateVectorSearchIndexConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        from pymongo.operations import SearchIndexModel
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            # Use the current Atlas Vector Search index format (type="vectorSearch", numDimensions)
            fields: List[Dict[str, Any]] = [{
                "type": "vector",
                "path": config.path,
                "numDimensions": config.num_dimensions,
                "similarity": config.similarity,
            }]
            # Append any filter fields for pre-filtering support
            if config.filter_fields:
                for fname in [f.strip() for f in config.filter_fields.split(",") if f.strip()]:
                    fields.append({"type": "filter", "path": fname})

            model = SearchIndexModel(
                definition={"fields": fields},
                name=config.index_name,
                type="vectorSearch",
            )
            await coll.create_search_index(model=model)
            return {
                "status": "success", "action": "create_vector_search_index",
                "index_name": config.index_name,
                "field": config.path,
                "num_dimensions": config.num_dimensions,
                "similarity": config.similarity,
                "filter_fields": [f.strip() for f in config.filter_fields.split(",") if f.strip()] if config.filter_fields else [],
            }
        finally:
            client.close()

    async def _handle_list_search_indexes(self, config: MongoDBListSearchIndexesConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            indexes = await coll.list_search_indexes().to_list(length=None)
            return {"status": "success", "action": "list_search_indexes", "indexes": _serialize(indexes), "count": len(indexes)}
        finally:
            client.close()

    async def _handle_update_search_index(self, config: MongoDBUpdateSearchIndexConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            definition = _parse_json(config.definition, "definition")
            await coll.update_search_index(config.index_name, definition)
            return {"status": "success", "action": "update_search_index", "index_name": config.index_name}
        finally:
            client.close()

    async def _handle_delete_search_index(self, config: MongoDBDeleteSearchIndexConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            await coll.drop_search_index(config.index_name)
            return {"status": "success", "action": "delete_search_index", "index_name": config.index_name}
        finally:
            client.close()

    # =========================================================================
    # Atlas Search (full-text) handlers
    # =========================================================================

    async def _handle_create_atlas_search_index(self, config: MongoDBCreateAtlasSearchIndexConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        from pymongo.operations import SearchIndexModel
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            mappings: Dict[str, Any] = {"dynamic": _bool_field(config.dynamic)}
            field_defs = _parse_json_opt(config.field_mappings, "field_mappings")
            if field_defs:
                mappings["fields"] = field_defs
            definition: Dict[str, Any] = {"mappings": mappings}
            if config.analyzer:
                definition["analyzer"] = config.analyzer
            model = SearchIndexModel(
                definition=definition,
                name=config.index_name,
                type="search",
            )
            await coll.create_search_index(model=model)
            return {
                "status": "success", "action": "create_atlas_search_index",
                "index_name": config.index_name,
                "dynamic": _bool_field(config.dynamic),
            }
        finally:
            client.close()

    async def _handle_atlas_text_search(self, config: MongoDBAtlasTextSearchConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            project_doc = _parse_json_opt(config.projection, "projection")

            search_body: Dict[str, Any] = {"index": config.index_name}
            operator_doc = _parse_json_opt(config.search_operator, "search_operator")
            if operator_doc:
                # Advanced: use the raw operator directly
                search_body.update(operator_doc)
            else:
                # Simple text query
                fuzzy = _bool_field(config.fuzzy)
                text_query: Dict[str, Any] = {"query": config.query}
                if config.search_fields:
                    fields = [f.strip() for f in config.search_fields.split(",") if f.strip()]
                    if fields:
                        text_query["path"] = fields[0] if len(fields) == 1 else fields
                else:
                    text_query["path"] = {"wildcard": "*"}
                if fuzzy:
                    text_query["fuzzy"] = {}
                search_body["text"] = text_query

            pipeline: List[Any] = [{"$search": search_body}, {"$limit": config.limit}]
            if project_doc:
                pipeline.append({"$project": project_doc})

            docs = await coll.aggregate(pipeline).to_list(length=None)
            return {"status": "success", "action": "atlas_text_search", "documents": _serialize(docs), "count": len(docs)}
        finally:
            client.close()

    # =========================================================================
    # Database handlers
    # =========================================================================

    async def _handle_list_databases(self, config: MongoDBListDatabasesConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            dbs = await client.list_database_names()
            return {"status": "success", "action": "list_databases", "databases": dbs, "count": len(dbs)}
        finally:
            client.close()

    async def _handle_drop_database(self, config: MongoDBDropDatabaseConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            await client.drop_database(config.database)
            return {"status": "success", "action": "drop_database", "database": config.database}
        finally:
            client.close()

    async def _handle_command(self, config: MongoDBCommandConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            db = client[config.database]
            command = _parse_json(config.command, "command")
            if not isinstance(command, dict):
                raise ValueError("`command` must be a JSON object, e.g. {\"ping\": 1}")
            result = await db.command(command)
            return {"status": "success", "action": "command", "result": _serialize(result)}
        finally:
            client.close()

    # =========================================================================
    # Atlas Facet Search handler
    # =========================================================================

    async def _handle_atlas_facet_search(self, config: MongoDBAtlasFacetSearchConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            facets_doc = _parse_json(config.facets, "facets")
            pipeline: List[Any] = [{
                "$searchMeta": {
                    "index": config.index_name,
                    "facet": {
                        "operator": {"text": {"query": config.query, "path": {"wildcard": "*"}}},
                        "facets": facets_doc,
                    }
                }
            }]
            result = await coll.aggregate(pipeline).to_list(length=None)
            return {"status": "success", "action": "atlas_facet_search", "result": _serialize(result)}
        finally:
            client.close()

    # =========================================================================
    # Create Multiple Indexes handler
    # =========================================================================

    async def _handle_create_indexes(self, config: MongoDBCreateIndexesConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        from pymongo import IndexModel
        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            specs = _parse_json(config.indexes, "indexes")
            if not isinstance(specs, list):
                raise ValueError("`indexes` must be a JSON array of index spec objects")
            models = []
            for spec in specs:
                if not isinstance(spec, dict) or "keys" not in spec:
                    raise ValueError(f"Each index spec must be an object with a 'keys' field, got: {spec}")
                keys = spec["keys"]
                if not isinstance(keys, dict):
                    raise ValueError(f"'keys' must be a JSON object, got: {keys}")
                idx_kwargs: Dict[str, Any] = {}
                if spec.get("name"):
                    idx_kwargs["name"] = spec["name"]
                if spec.get("unique"):
                    idx_kwargs["unique"] = spec["unique"]
                if spec.get("sparse"):
                    idx_kwargs["sparse"] = spec["sparse"]
                if spec.get("expireAfterSeconds") is not None:
                    idx_kwargs["expireAfterSeconds"] = spec["expireAfterSeconds"]
                if spec.get("partialFilterExpression"):
                    idx_kwargs["partialFilterExpression"] = spec["partialFilterExpression"]
                models.append(IndexModel(list(keys.items()), **idx_kwargs))
            names = await coll.create_indexes(models)
            return {"status": "success", "action": "create_indexes", "created_indexes": names, "count": len(names)}
        finally:
            client.close()

    # =========================================================================
    # Upload & Index handler
    # =========================================================================

    async def _handle_upload_and_index(self, config: MongoDBUploadAndIndexConfig, cred: Dict[str, Any]) -> Dict[str, Any]:
        records, info = await ingest_document(
            self, config.document,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            id_prefix=config.id_prefix,
        )
        if not records:
            return {"status": "error", "action": "upload_and_index", "error": "No text could be extracted from the document"}

        docs = [
            {
                "_id": record["id"],
                config.vector_field: record["values"],
                config.text_field: record["metadata"]["text"],
                config.metadata_field: record["metadata"],
            }
            for record in records
        ]

        client = self._get_client(cred)
        try:
            coll = client[config.database][config.collection]
            result = await coll.insert_many(docs, ordered=False)
            return {
                "status": "success", "action": "upload_and_index",
                "chunks_indexed": len(result.inserted_ids),
                "source": info.get("filename"),
                "collection": config.collection,
                "database": config.database,
            }
        finally:
            client.close()
