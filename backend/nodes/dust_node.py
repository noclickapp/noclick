"""Dust API v1: provider OpenAPI 1.0.2, https://dust.tt/api/doc.

Document polling watches semantic search results and caller-supplied timestamps.
"""
from __future__ import annotations
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASES = {"us": "https://dust.tt", "eu": "https://eu.dust.tt"}


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or value.strip() in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Paste a nonempty Dust resource ID without control characters")
    return value.strip()


class DustAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dust API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.dust.tt/docs/user-documentation/admins/api-keys",
        "x-credential-instructions": "In Dust, open Admin > Developers > API keys. Paste your API key and the workspace ID after /w/ in your Dust URL. Choose your workspace's US or EU region. Reads and conversations work with a read-only key; resource writes need an Admin key with access to the selected space.",
    })
    credential_type: Literal["dust_api_key"] = Field("dust_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, json_schema_extra={"ui:widget": "password"})
    workspace_id: str = Field(..., title="Workspace ID")
    region: Literal["us", "eu"] = Field("us", title="Region")
    _workspace = field_validator("workspace_id", mode="before")(identifier)

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class DustInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def ids(cls, value, info):
        return identifier(value) if info.field_name.endswith("_id") and value is not None else value


def text(title, maximum=100000):
    return (str, Field(..., title=title, min_length=1, max_length=maximum))


def optional_text(title):
    return (str | None, Field(None, title=title, max_length=100000))


SPACE = {"space_id": text("Space ID", 512)}
SOURCE = {**SPACE, "data_source_id": text("Data source ID", 512)}
DOC = {**SOURCE, "document_id": text("Document ID", 512)}
TABLE = {**SOURCE, "table_id": text("Table ID", 512)}
ROW = {**TABLE, "row_id": text("Row ID", 512)}
AGENT = {"agent_id": text("Agent ID", 512)}
CONVERSATION = {"conversation_id": text("Conversation ID", 512)}
PAGE = {"limit": (int, Field(100, ge=1, le=1000)), "offset": (int, Field(0, ge=0))}
TAGS = {"tags_json": (str | None, Field(None, title="Tags (JSON array)", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))}
SEARCH = {**SOURCE, "query": text("Search query"), "top_k": (int, Field(100, ge=1, le=1000)),
          "full_text": (bool, Field(True)), "timestamp_gt": (float | None, Field(None, ge=0, allow_inf_nan=False)),
          "timestamp_lt": (float | None, Field(None, ge=0, allow_inf_nan=False))}
MESSAGE = {**AGENT, "content": text("Message content")}


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: dict
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


S = "/spaces/{space_id}/data_sources/{data_source_id}"
D = S + "/documents/{document_id}"
T = S + "/tables/{table_id}"
A = "/assistant/agent_configurations"
C = "/assistant/conversations"
OPERATIONS = {
    "list_agents": Operation("List Agents", "Agents", "GET", A, {}),
    "get_agent": Operation("Get Agent", "Agents", "GET", A + "/{agent_id}", AGENT),
    "update_agent": Operation("Update Agent Instructions", "Agents", "PATCH", A + "/{agent_id}", {**AGENT, "instructions": text("Instructions")}, body=("instructions",)),
    "archive_agent": Operation("Archive Agent", "Agents", "DELETE", A + "/{agent_id}", AGENT),
    "list_spaces": Operation("List Spaces", "Spaces", "GET", "/spaces", {}),
    "list_data_sources": Operation("List Data Sources", "Knowledge", "GET", "/spaces/{space_id}/data_sources", SPACE),
    "list_documents": Operation("List Documents", "Knowledge", "GET", S + "/documents", {**SOURCE, **PAGE}, query=("limit", "offset")),
    "get_document": Operation("Get Document", "Knowledge", "GET", D, DOC),
    "upsert_document": Operation("Upsert Document", "Knowledge", "POST", D, {**DOC, "title": text("Title"), "text": text("Document text"), "source_url": optional_text("Source URL"), **TAGS, "timestamp": (float | None, Field(None, ge=0, allow_inf_nan=False, description="Unix milliseconds. Advance the timestamp when updating documents watched by the poll trigger."))}, body=("title", "text", "source_url", "tags_json", "timestamp")),
    "delete_document": Operation("Delete Document", "Knowledge", "DELETE", D, DOC),
    "search_documents": Operation("Search Documents", "Knowledge", "GET", S + "/search", SEARCH, query=("query", "top_k", "full_text", "timestamp_gt", "timestamp_lt")),
    "list_tables": Operation("List Tables", "Tables", "GET", S + "/tables", SOURCE),
    "get_table": Operation("Get Table", "Tables", "GET", T, TABLE),
    "upsert_table": Operation("Upsert Table", "Tables", "POST", S + "/tables", {**TABLE, "name": text("Name"), "title": text("Title"), "description": optional_text("Description"), **TAGS}, body=("table_id", "name", "title", "description", "tags_json")),
    "delete_table": Operation("Delete Table", "Tables", "DELETE", T, TABLE),
    "list_rows": Operation("List Rows", "Tables", "GET", T + "/rows", {**TABLE, **PAGE}, query=("limit", "offset")),
    "get_row": Operation("Get Row", "Tables", "GET", T + "/rows/{row_id}", ROW),
    "upsert_rows": Operation("Upsert Rows", "Tables", "POST", T + "/rows", {**TABLE, "rows_json": (str, Field(..., title="Rows (JSON array)", description='Array of {"row_id": "id", "value": {"column": "value"}} objects.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))}, body=("rows_json",)),
    "delete_row": Operation("Delete Row", "Tables", "DELETE", T + "/rows/{row_id}", ROW),
    "create_conversation": Operation("Create Conversation", "Conversations", "POST", C, {**MESSAGE, "title": optional_text("Title"), "blocking": (bool, Field(False, description="Wait for the first agent answer. Long runs can time out; inspect Dust before retrying a timed out write."))}, body=("title", "blocking")),
    "get_conversation": Operation("Get Conversation", "Conversations", "GET", C + "/{conversation_id}", CONVERSATION),
    "rename_conversation": Operation("Rename Conversation", "Conversations", "PATCH", C + "/{conversation_id}", {**CONVERSATION, "title": text("Title", 512)}, body=("title",)),
    "create_message": Operation("Create Message", "Conversations", "POST", C + "/{conversation_id}/messages", {**CONVERSATION, **MESSAGE}),
}


def make_config(name, op):
    return create_model("Dust" + "".join(p.title() for p in name.split("_")) + "Config", __base__=DustInput,
        operation=(Literal[name], Field(name, title=op.label, json_schema_extra={"ui:hidden": True, "x-display-name": op.label, "x-category": op.category})), **op.fields)


CONFIGS = {name: make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIGS.values()})


class DustOnDocumentUpdatedConfig(PollTriggerConfigBase, DustInput):
    operation: Literal["on_new_or_updated_document"] = Field("on_new_or_updated_document", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New or Updated Matching Document"})
    space_id: str = Field(..., min_length=1, max_length=512)
    data_source_id: str = Field(..., min_length=1, max_length=512)
    query: str = Field(..., min_length=1, description="Semantic search query defining which documents to watch. This watches matching results, not the whole data source.")
    since_timestamp: float = Field(0, ge=0, allow_inf_nan=False, description="Only documents with a newer document timestamp (Unix milliseconds). Writers must advance that timestamp for updates. Existing results are baselined when armed.")
    top_k: int = Field(100, ge=1, le=1000, description="Maximum matching documents. If results fill this bound, narrow the query or raise the limit before polling can continue.")


DustConfig = Annotated[Union[tuple(CONFIGS.values()) + (DustOnDocumentUpdatedConfig,)], Field(discriminator="operation")]


class DustNodeConfig(NodeConfig[DustConfig, DustAPIKeyCredential]):
    pass


def json_field(value, name):
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a JSON array") from None
    if not isinstance(data, list):
        raise ValueError(f"{name} must be a JSON array")
    if name == "tags_json" and not all(isinstance(item, str) for item in data):
        raise ValueError("Tags must be an array of strings")
    if name == "rows_json":
        if not data or len(data) > 1000:
            raise ValueError("Provide between 1 and 1000 rows")
        for item in data:
            if not isinstance(item, dict) or set(item) != {"row_id", "value"} or not isinstance(item["value"], dict):
                raise ValueError("Each row needs row_id and a value object")
            identifier(item["row_id"])
            for cell in item["value"].values():
                if type(cell) in {str, bool} or type(cell) in {int, float} and math.isfinite(cell):
                    continue
                if isinstance(cell, dict) and set(cell) == {"type", "epoch"} and cell["type"] == "datetime" and type(cell["epoch"]) in {int, float} and math.isfinite(cell["epoch"]):
                    continue
                raise ValueError("Row values must be strings, finite numbers, booleans, or {type: datetime, epoch: number}")
        if len({row["row_id"] for row in data}) != len(data):
            raise ValueError("Row IDs must be unique within a write")
    return data


class DustNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-dust"
    connection_evidence = ConnectionEvidence(operation="list_spaces", noun="spaces")

    @classmethod
    def get_config_model(cls):
        return DustNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        url = BASES[credential.region] + "/api/v1/w/" + quote(identifier(credential.workspace_id), safe="") + path
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                response = await client.request(method, url, headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, params=params, json=body)
        except httpx.RequestError:
            raise ValueError("Dust could not be reached. A write may have succeeded; inspect Dust before retrying.") from None
        if not response.is_success:
            detail = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Dust HTTP {response.status_code}: {detail}")
        if not response.content:
            return None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Dust returned an unexpected non-JSON response") from None
        if isinstance(data, dict) and "error" in data and data["error"]:
            detail = json.dumps(data["error"], ensure_ascii=False).replace(credential.api_key, "[redacted]")
            raise ValueError("Dust rejected the request: " + detail[:2000])
        return data

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_document_count")) if config.get("operation") == "on_new_or_updated_document" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "documents" not in output:
            return super().resolve_agent_event(output)
        rows = output["documents"]
        if not rows:
            return None
        lines = [f"- {row['title']} (document {row['id']}, timestamp {row['timestamp']}): {row['content'][:2000]}" for row in rows[:10]]
        return {"text": f"Dust: {len(rows)} new or updated matching document(s) in space {output['space_id']}, data source {output['data_source_id']}.\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Dust API key")
        cfg = self.config.config
        if isinstance(cfg, DustOnDocumentUpdatedConfig):
            path = S.format(space_id=quote(identifier(cfg.space_id), safe=""), data_source_id=quote(identifier(cfg.data_source_id), safe="")) + "/search"
            data = await self._request(credential, "GET", path, params={"query": cfg.query, "top_k": cfg.top_k, "full_text": "true", "timestamp_gt": cfg.since_timestamp})
            if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
                raise ValueError("Dust search returned no document list")
            rows = data["documents"]
            if len(rows) >= cfg.top_k:
                raise ValueError("Dust search filled the poll result bound. Narrow the query or increase top_k; no events were consumed.")
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or type(row.get("timestamp")) not in {int, float} or not math.isfinite(row["timestamp"]):
                    raise ValueError("Dust search document is missing its ID or timestamp")
                if not isinstance(row.get("title"), str) or not isinstance(row.get("content"), str):
                    raise ValueError("Dust search document is missing title or content")
            fresh = await self._filter_unseen(rows, lambda row: hashlib.sha256(json.dumps([row["id"], row["timestamp"]]).encode()).hexdigest())
            return {"documents": fresh, "new_document_count": len(fresh), "space_id": cfg.space_id, "data_source_id": cfg.data_source_id}
        op = OPERATIONS[cfg.operation]
        values = cfg.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for name, value in values.items():
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(identifier(value), safe=""))
        params = {name: (str(values[name]).lower() if type(values[name]) is bool else values[name]) for name in op.query if name in values}
        body = {}
        for name in op.body:
            if name in values:
                body[name.removesuffix("_json")] = json_field(values[name], name) if name.endswith("_json") else values[name]
        if cfg.operation in {"create_conversation", "create_message"}:
            message = {"content": cfg.content, "mentions": [{"configurationId": cfg.agent_id}]}
            body = {**body, "message": message} if cfg.operation == "create_conversation" else message
        data = await self._request(credential, op.method, path, params=params or None, body=body if op.method in {"POST", "PATCH"} else None)
        return {"status": "success", "operation": cfg.operation, "data": data}
