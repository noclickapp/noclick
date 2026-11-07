"""Meilisearch search, indexing, and administration workflow node.

Reference: https://www.meilisearch.com/docs/reference/api
Writes enqueue asynchronous tasks; their taskUid is returned to the workflow.
"""

import json
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, normalize_https_origin


_INDEX_FIELD = {
    "x-resource-type": "meilisearch_index",
    "x-dynamic-options": {
        "field_name": "index_uid",
        "placeholder": "Select an index...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or type an index UID",
    },
}
_JSON_FIELD = {"ui:widget": "textarea"}


class MeilisearchCredential(BaseModel):
    """HTTPS instance URL and an API key with the required action permissions."""

    credential_type: Literal["meilisearch_api_key"] = Field(
        "meilisearch_api_key", json_schema_extra={"ui:hidden": True}
    )
    url: str = Field(..., title="Instance URL", description="The HTTPS origin of your Meilisearch Cloud or self-hosted instance")
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    model_config = ConfigDict(
        title="Meilisearch API Key",
        json_schema_extra={"x-credential-url": "https://cloud.meilisearch.com/"}
    )


def _op(name: str, category: str, label: str):
    return Field(
        name,
        title=label,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-category": category,
            "x-display-name": label,
            "x-is-trigger": False,
        },
    )


class ListIndexes(BaseModel):
    operation: Literal["list_indexes"] = _op("list_indexes", "Indexes", "List Indexes")
    limit: int = Field(20, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class GetIndex(BaseModel):
    operation: Literal["get_index"] = _op("get_index", "Indexes", "Get Index")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)


class CreateIndex(BaseModel):
    operation: Literal["create_index"] = _op("create_index", "Indexes", "Create Index")
    index_uid: str = Field(..., title="New Index UID")
    primary_key: Optional[str] = Field(None, title="Primary Key")


class UpdateIndex(BaseModel):
    operation: Literal["update_index"] = _op("update_index", "Indexes", "Update Index")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    primary_key: str = Field(..., title="Primary Key", description="Can only be set if the index has none")


class DeleteIndex(BaseModel):
    operation: Literal["delete_index"] = _op("delete_index", "Indexes", "Delete Index")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)


class SwapIndexes(BaseModel):
    operation: Literal["swap_indexes"] = _op("swap_indexes", "Indexes", "Swap Indexes")
    swaps_json: str = Field(..., title="Swaps (JSON)", description='Array such as [{"indexes":["products","products_new"]}]', json_schema_extra=_JSON_FIELD)


class ListDocuments(BaseModel):
    operation: Literal["list_documents"] = _op("list_documents", "Documents", "List Documents")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    limit: int = Field(20, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    fields: Optional[str] = Field(None, title="Fields", description="Comma-separated attributes to return")


class GetDocument(BaseModel):
    operation: Literal["get_document"] = _op("get_document", "Documents", "Get Document")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    document_id: str = Field(..., title="Document ID")


class AddDocuments(BaseModel):
    operation: Literal["add_documents"] = _op("add_documents", "Documents", "Add or Replace Documents")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    documents_json: str = Field(..., title="Documents (JSON)", description="Array of document objects; existing documents are replaced", json_schema_extra=_JSON_FIELD)
    primary_key: Optional[str] = Field(None, title="Primary Key", description="Used if the index has no primary key")


class UpdateDocuments(BaseModel):
    operation: Literal["update_documents"] = _op("update_documents", "Documents", "Update Documents")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    documents_json: str = Field(..., title="Documents (JSON)", description="Array of document objects with primary keys; attributes are merged", json_schema_extra=_JSON_FIELD)
    primary_key: Optional[str] = Field(None, title="Primary Key", description="Used if the index has no primary key")


class DeleteDocument(BaseModel):
    operation: Literal["delete_document"] = _op("delete_document", "Documents", "Delete Document")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    document_id: str = Field(..., title="Document ID")


class DeleteDocumentsBatch(BaseModel):
    operation: Literal["delete_documents_batch"] = _op("delete_documents_batch", "Documents", "Delete Documents by ID")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    ids_json: str = Field(..., title="Document IDs (JSON)", description="Array of document IDs", json_schema_extra=_JSON_FIELD)


class DeleteDocumentsByFilter(BaseModel):
    operation: Literal["delete_documents_by_filter"] = _op("delete_documents_by_filter", "Documents", "Delete Documents by Filter")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    filter_json: str = Field(..., title="Filter (JSON)", description='A filter string or array, such as "genre = Horror"', json_schema_extra=_JSON_FIELD)


class DeleteAllDocuments(BaseModel):
    operation: Literal["delete_all_documents"] = _op("delete_all_documents", "Documents", "Delete All Documents")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)


class Search(BaseModel):
    operation: Literal["search"] = _op("search", "Search", "Search Documents")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    query: str = Field("", title="Query", description="Leave empty for a placeholder search")
    filter_json: Optional[str] = Field(None, title="Filter (JSON)", description='A filter string or array, such as "genre = Horror"', json_schema_extra=_JSON_FIELD)
    sort: Optional[str] = Field(None, title="Sort", description="Comma-separated sort rules, e.g. price:asc,rating:desc")
    limit: int = Field(20, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    attributes_to_retrieve: Optional[str] = Field(None, title="Attributes to Retrieve", description="Comma-separated field names")


class MultiSearch(BaseModel):
    operation: Literal["multi_search"] = _op("multi_search", "Search", "Multi-search")
    queries_json: str = Field(..., title="Queries (JSON)", description='Array such as [{"indexUid":"movies","q":"alien"}]', json_schema_extra=_JSON_FIELD)
    federation_json: Optional[str] = Field(None, title="Federation (JSON)", description="Optional federation object for merged hits", json_schema_extra=_JSON_FIELD)


class GetSettings(BaseModel):
    operation: Literal["get_settings"] = _op("get_settings", "Settings", "Get Settings")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)


class UpdateSettings(BaseModel):
    operation: Literal["update_settings"] = _op("update_settings", "Settings", "Update Settings")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)
    settings_json: str = Field(..., title="Settings (JSON)", description='Object such as {"filterableAttributes":["genre"]}', json_schema_extra=_JSON_FIELD)


class ResetSettings(BaseModel):
    operation: Literal["reset_settings"] = _op("reset_settings", "Settings", "Reset Settings")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)


class GetIndexStats(BaseModel):
    operation: Literal["get_index_stats"] = _op("get_index_stats", "Indexes", "Get Index Stats")
    index_uid: str = Field(..., title="Index", json_schema_extra=_INDEX_FIELD)


class GetTask(BaseModel):
    operation: Literal["get_task"] = _op("get_task", "Tasks", "Get Task")
    task_uid: int = Field(..., ge=0, title="Task UID")


class ListTasks(BaseModel):
    operation: Literal["list_tasks"] = _op("list_tasks", "Tasks", "List Tasks")
    limit: int = Field(20, ge=1, le=1000)
    from_uid: Optional[int] = Field(None, ge=0, title="From Task UID")
    statuses: Optional[str] = Field(None, title="Statuses", description="Comma-separated statuses")
    index_uids: Optional[str] = Field(None, title="Index UIDs", description="Comma-separated index UIDs")


MeilisearchConfig = Annotated[
    Union[
        ListIndexes, GetIndex, CreateIndex, UpdateIndex, DeleteIndex, SwapIndexes,
        ListDocuments, GetDocument, AddDocuments, UpdateDocuments, DeleteDocument,
        DeleteDocumentsBatch, DeleteDocumentsByFilter, DeleteAllDocuments,
        Search, MultiSearch, GetSettings, UpdateSettings, ResetSettings,
        GetIndexStats, GetTask, ListTasks,
    ],
    Discriminator("operation"),
]


class MeilisearchNodeConfig(NodeConfig[MeilisearchConfig, MeilisearchCredential]):
    pass


def _json_value(raw: str, kind: Any, field: str) -> Any:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be valid JSON") from exc
    if not isinstance(value, kind):
        expected = "string or array" if isinstance(kind, tuple) else kind.__name__
        raise ValueError(f"{field} must be a JSON {expected}")
    return value


def _path_part(value: Any) -> str:
    if not str(value):
        raise ValueError("An index UID or document ID is required")
    return quote(str(value), safe="")


def _csv(value: Optional[str]) -> Optional[List[str]]:
    return [part.strip() for part in value.split(",") if part.strip()] if value else None


class MeilisearchNode(WorkflowNode):
    """Operate a user-owned Meilisearch instance via its REST API."""

    integration_type = "automation-meilisearch"

    connection_evidence = ConnectionEvidence(field="index_uid", operation="list_indexes", noun="indexes")
    edit_examples = [
        "Search the product index for running shoes",
        "Add new documents to the knowledge base index",
        "Set genre as a filterable attribute before running filtered searches",
        "Check whether an indexing task has finished",
        "Swap a newly built index into production",
    ]

    @classmethod
    def get_config_model(cls):
        return MeilisearchNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if field_name != "index_uid" or not credential_data:
            return []
        credential = MeilisearchCredential.model_validate(credential_data)
        base = normalize_https_origin(credential.url, field_name="Meilisearch instance URL")
        async with guarded_async_client(timeout=20.0) as client:
            response = await client.get(f"{base}/indexes", headers={"Authorization": f"Bearer {credential.api_key}"}, params={"limit": 1000})
        response.raise_for_status()
        indexes = response.json().get("results", [])
        return [
            {"value": item["uid"], "label": item["uid"]}
            for item in indexes
            if isinstance(item, dict) and item.get("uid") and (not search or search.lower() in item["uid"].lower())
        ]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, MeilisearchNodeConfig) or not self.config.credentials:
            raise ValueError("Meilisearch credentials are required")
        credential = self.config.credentials
        config = self.config.config
        operation = config.operation
        base = normalize_https_origin(credential.url, field_name="Meilisearch instance URL")
        index = f"/indexes/{_path_part(config.index_uid)}" if hasattr(config, "index_uid") else ""
        params: Dict[str, Any] = {}
        body: Any = None
        method = "GET"
        path = ""

        if operation == "list_indexes":
            path, params = "/indexes", {"limit": config.limit, "offset": config.offset}
        elif operation == "get_index":
            path = index
        elif operation == "create_index":
            method, path = "POST", "/indexes"
            body = {"uid": config.index_uid}
            if config.primary_key:
                body["primaryKey"] = config.primary_key
        elif operation == "update_index":
            method, path, body = "PATCH", index, {"primaryKey": config.primary_key}
        elif operation == "delete_index":
            method, path = "DELETE", index
        elif operation == "swap_indexes":
            method, path = "POST", "/swap-indexes"
            body = _json_value(config.swaps_json, list, "Swaps")
            if not body or any(not isinstance(swap, dict) or not isinstance(swap.get("indexes"), list) or len(swap["indexes"]) != 2 for swap in body):
                raise ValueError("Swaps must contain pairs of index UIDs")
        elif operation == "list_documents":
            path, params = f"{index}/documents", {"limit": config.limit, "offset": config.offset}
            if config.fields:
                params["fields"] = config.fields
        elif operation == "get_document":
            path = f"{index}/documents/{_path_part(config.document_id)}"
        elif operation in ("add_documents", "update_documents"):
            method, path = ("POST" if operation == "add_documents" else "PUT"), f"{index}/documents"
            body = _json_value(config.documents_json, list, "Documents")
            if not body or any(not isinstance(item, dict) for item in body):
                raise ValueError("Documents must be a non-empty array of objects")
            if config.primary_key:
                params["primaryKey"] = config.primary_key
        elif operation == "delete_document":
            method, path = "DELETE", f"{index}/documents/{_path_part(config.document_id)}"
        elif operation == "delete_documents_batch":
            method, path = "POST", f"{index}/documents/delete-batch"
            body = _json_value(config.ids_json, list, "Document IDs")
            if not body or any(not isinstance(item, (str, int)) or isinstance(item, bool) for item in body):
                raise ValueError("Document IDs must be a non-empty array of strings or integers")
        elif operation == "delete_documents_by_filter":
            method, path = "POST", f"{index}/documents/delete"
            body = {"filter": _json_value(config.filter_json, (str, list), "Filter")}
        elif operation == "delete_all_documents":
            method, path = "DELETE", f"{index}/documents"
        elif operation == "search":
            method, path = "POST", f"{index}/search"
            body = {"q": config.query, "limit": config.limit, "offset": config.offset}
            if config.filter_json:
                body["filter"] = _json_value(config.filter_json, (str, list), "Filter")
            if config.sort:
                body["sort"] = _csv(config.sort)
            if config.attributes_to_retrieve:
                body["attributesToRetrieve"] = _csv(config.attributes_to_retrieve)
        elif operation == "multi_search":
            method, path = "POST", "/multi-search"
            queries = _json_value(config.queries_json, list, "Queries")
            if not queries or any(not isinstance(query, dict) or not query.get("indexUid") for query in queries):
                raise ValueError("Queries must be a non-empty array with indexUid on every query")
            body = {"queries": queries}
            if config.federation_json:
                body["federation"] = _json_value(config.federation_json, dict, "Federation")
        elif operation == "get_settings":
            path = f"{index}/settings"
        elif operation == "update_settings":
            method, path = "PATCH", f"{index}/settings"
            body = _json_value(config.settings_json, dict, "Settings")
        elif operation == "reset_settings":
            method, path = "DELETE", f"{index}/settings"
        elif operation == "get_index_stats":
            path = f"{index}/stats"
        elif operation == "get_task":
            path = f"/tasks/{config.task_uid}"
        elif operation == "list_tasks":
            path, params = "/tasks", {"limit": config.limit}
            if config.from_uid is not None:
                params["from"] = config.from_uid
            if config.statuses:
                params["statuses"] = config.statuses
            if config.index_uids:
                params["indexUids"] = config.index_uids
        else:
            raise ValueError(f"Unsupported Meilisearch operation: {operation}")

        headers = {"Authorization": f"Bearer {credential.api_key}", "Content-Type": "application/json"}
        async with guarded_async_client(timeout=30.0) as client:
            response = await client.request(method, f"{base}{path}", headers=headers, params=params, json=body)
        if response.is_error:
            try:
                error = response.json()
                message = error.get("message") if isinstance(error, dict) else None
            except ValueError:
                message = None
            return {"status": "error", "operation": operation, "status_code": response.status_code, "error": message or f"Meilisearch returned HTTP {response.status_code}"}
        data = response.json() if response.content else None
        return {"status": "success", "operation": operation, "data": data, "task_uid": data.get("taskUid") if isinstance(data, dict) else None}
