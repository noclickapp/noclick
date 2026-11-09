"""Mem0 Platform memory and entity operations against the published v1 contract.

Each operation issues one request. Async acknowledgements and provider pagination
are returned intact so callers can poll events or request the next explicit page.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.mem0.ai"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


def _json(value: str, kind: type):
    try:
        result = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("Enter valid JSON") from None
    if not isinstance(result, kind):
        raise ValueError("Enter a JSON " + ("object" if kind is dict else "array"))
    return result


def _has_entity_filter(value):
    if not isinstance(value, dict):
        return False
    if any(value.get(key) for key in ("user_id", "agent_id", "app_id", "run_id")):
        return True
    for key in ("AND", "OR", "NOT"):
        nested = value.get(key)
        if isinstance(nested, dict) and _has_entity_filter(nested):
            return True
        if isinstance(nested, list) and any(_has_entity_filter(item) for item in nested):
            return True
    return False


class Mem0APIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mem0 API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.mem0.ai/dashboard/api-keys",
        "x-credential-instructions": "Create an API key in your Mem0 dashboard and paste the key here. NoClick sends it only to api.mem0.ai. The key selects your organization and project; connection checks read their entities.",
    })
    credential_type: Literal["mem0_api_key"] = Field("mem0_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Token prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def json_and_path_fields(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"metadata", "filters"}:
            parsed = _json(value, dict)
            if info.field_name == "filters" and not _has_entity_filter(parsed):
                raise ValueError("Filters must include a user, agent, app or run ID")
        if info.field_name in {"memory_id", "event_id"}:
            try:
                UUID(value)
            except (ValueError, TypeError):
                raise ValueError("Enter a UUID") from None
        if info.field_name == "entity_id" and (value in {".", ".."} or any(c in value for c in "/\\?#")):
            raise ValueError("Enter a single entity identifier")
        return value


class _Project(_Input):
    org_id: str | None = Field(None, title="Organization ID")
    project_id: str | None = Field(None, title="Project ID")


class _Scope(_Input):
    user_id: str | None = None
    agent_id: str | None = None
    app_id: str | None = None
    run_id: str | None = None


class AddMemories(_Scope):
    """Queue memories from conversation messages; poll the returned event ID."""
    operation: Literal["add_memories"] = Field("add_memories", json_schema_extra={"ui:hidden": True})
    messages: str = Field(..., description='JSON array, for example [{"role":"user","content":"I prefer tea"}].', json_schema_extra=JSON_EDITOR)
    metadata: str | None = Field(None, description="JSON metadata object.", json_schema_extra=JSON_EDITOR)
    infer: bool = True
    custom_instructions: str | None = None
    expiration_date: date | None = None

    @field_validator("messages")
    @classmethod
    def messages_json(cls, value):
        rows = _json(value, list)
        if not rows or any(not isinstance(row, dict) or row.get("role") not in ("user", "assistant", "system") or not isinstance(row.get("content"), str) or not row["content"].strip() for row in rows):
            raise ValueError("Supply message objects with role and nonempty content")
        if any(any(v is not None and not isinstance(v, str) for v in row.values()) for row in rows):
            raise ValueError("Message values must be strings or null")
        return value

    @model_validator(mode="after")
    def scoped(self):
        if not any([self.user_id, self.agent_id, self.app_id, self.run_id]):
            raise ValueError("Supply a user, agent, app or run ID for these memories")
        return self


class ListMemories(_Input):
    """Read a page of memories matching a JSON filter object."""
    operation: Literal["list_memories"] = Field("list_memories", json_schema_extra={"ui:hidden": True})
    filters: str = Field(..., description='JSON filters, for example {"user_id":"alex"}.', json_schema_extra=JSON_EDITOR)
    show_expired: bool = False
    start_date: date | None = None
    end_date: date | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(100, ge=1, le=1000)


class SearchMemories(_Input):
    """Search scoped memories by semantic query."""
    operation: Literal["search_memories"] = Field("search_memories", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)
    filters: str = Field(..., description='JSON filters, for example {"user_id":"alex"}.', json_schema_extra=JSON_EDITOR)
    top_k: int = Field(10, ge=1, le=1000)
    threshold: float = Field(0.1, ge=0, le=1)
    rerank: bool = False
    show_expired: bool = False


class GetMemory(_Input):
    """Read one memory by its UUID."""
    operation: Literal["get_memory"] = Field("get_memory", json_schema_extra={"ui:hidden": True})
    memory_id: str = Field(..., min_length=1, json_schema_extra={"format": "uuid"})


class UpdateMemory(_Input):
    """Update the text and optional metadata of a memory."""
    operation: Literal["update_memory"] = Field("update_memory", json_schema_extra={"ui:hidden": True})
    memory_id: str = Field(..., min_length=1, json_schema_extra={"format": "uuid"})
    text: str = Field(..., min_length=1)
    metadata: str | None = Field(None, json_schema_extra=JSON_EDITOR)
    expiration_date: date | None = None


class DeleteMemory(_Input):
    """Delete one memory; linked-memory deletion is opt-in."""
    operation: Literal["delete_memory"] = Field("delete_memory", json_schema_extra={"ui:hidden": True})
    memory_id: str = Field(..., min_length=1, json_schema_extra={"format": "uuid"})
    delete_linked: bool = False


class GetMemoryHistory(_Input):
    """Read a memory's change history."""
    operation: Literal["get_memory_history"] = Field("get_memory_history", json_schema_extra={"ui:hidden": True})
    memory_id: str = Field(..., min_length=1, json_schema_extra={"format": "uuid"})


class BatchUpdateMemories(_Input):
    """Update up to 1000 memories in one request."""
    operation: Literal["batch_update_memories"] = Field("batch_update_memories", json_schema_extra={"ui:hidden": True})
    memories: str = Field(..., description='JSON array of objects with memory_id and text or metadata.', json_schema_extra=JSON_EDITOR)

    @field_validator("memories")
    @classmethod
    def batch(cls, value):
        _batch(value, update=True)
        return value


class BatchDeleteMemories(_Input):
    """Delete up to 1000 explicitly identified memories."""
    operation: Literal["batch_delete_memories"] = Field("batch_delete_memories", json_schema_extra={"ui:hidden": True})
    memories: str = Field(..., description='JSON array of objects with memory_id.', json_schema_extra=JSON_EDITOR)

    @field_validator("memories")
    @classmethod
    def batch(cls, value):
        _batch(value, update=False)
        return value


def _batch(value, *, update):
    rows = _json(value, list)
    if not 1 <= len(rows) <= 1000:
        raise ValueError("Supply 1 to 1000 memory objects")
    for row in rows:
        if not isinstance(row, dict) or set(row) - ({"memory_id", "text", "metadata"} if update else {"memory_id"}):
            raise ValueError("Supply memory_id objects with only documented fields")
        try:
            UUID(row.get("memory_id", ""))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Every memory_id must be a UUID") from None
        if update and (not ("text" in row or "metadata" in row) or ("text" in row and not isinstance(row["text"], str)) or ("metadata" in row and not isinstance(row["metadata"], dict))):
            raise ValueError("Each update needs text or a metadata object")
    return rows


class ListEntities(_Project):
    """List the current project's users, agents, apps and runs."""
    operation: Literal["list_entities"] = Field("list_entities", json_schema_extra={"ui:hidden": True})


class GetEntity(_Input):
    """Read an entity using its string identifier."""
    operation: Literal["get_entity"] = Field("get_entity", json_schema_extra={"ui:hidden": True})
    entity_type: Literal["user", "agent", "app", "run"] = "user"
    entity_id: str = Field(..., min_length=1)


class DeleteEntity(_Input):
    """Queue deletion of an entity and its memories; poll its event ID."""
    operation: Literal["delete_entity"] = Field("delete_entity", json_schema_extra={"ui:hidden": True})
    entity_type: Literal["user", "agent", "app", "run"] = "user"
    entity_id: str = Field(..., min_length=1)


class CreateUser(_Input):
    """Create a user entity with optional metadata."""
    operation: Literal["create_user"] = Field("create_user", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1)
    metadata: str | None = Field(None, json_schema_extra=JSON_EDITOR)


class CreateAgent(_Input):
    """Create an agent entity with a display name."""
    operation: Literal["create_agent"] = Field("create_agent", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    metadata: str | None = Field(None, json_schema_extra=JSON_EDITOR)


class CreateApp(_Input):
    """Create an application entity with a display name."""
    operation: Literal["create_app"] = Field("create_app", json_schema_extra={"ui:hidden": True})
    app_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    metadata: str | None = Field(None, json_schema_extra=JSON_EDITOR)


class CreateRun(_Input):
    """Create a run entity with a display name."""
    operation: Literal["create_run"] = Field("create_run", json_schema_extra={"ui:hidden": True})
    run_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    metadata: str | None = Field(None, json_schema_extra=JSON_EDITOR)


class GetEvent(_Input):
    """Read the status and results of an asynchronous operation."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, json_schema_extra={"format": "uuid"})


class GetStatistics(_Input):
    """Read memory and retrieval usage statistics for this account."""
    operation: Literal["get_statistics"] = Field("get_statistics", json_schema_extra={"ui:hidden": True})


class CheckConnection(_Input):
    """Resolve the key's organization, project and account email."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class SubmitFeedback(_Input):
    """Record positive or negative feedback on a memory."""
    operation: Literal["submit_feedback"] = Field("submit_feedback", json_schema_extra={"ui:hidden": True})
    memory_id: str = Field(..., min_length=1, json_schema_extra={"format": "uuid"})
    feedback: Literal["POSITIVE", "NEGATIVE", "VERY_NEGATIVE"]
    feedback_reason: str | None = None


Mem0Operation = Annotated[Union[AddMemories, ListMemories, SearchMemories, GetMemory,
    UpdateMemory, DeleteMemory, GetMemoryHistory, BatchUpdateMemories, BatchDeleteMemories,
    ListEntities, GetEntity, DeleteEntity, CreateUser, CreateAgent, CreateApp, CreateRun,
    GetEvent, GetStatistics, CheckConnection, SubmitFeedback], Field(discriminator="operation")]


class Mem0Config(NodeConfig[Mem0Operation, Mem0APIKeyCredential]):
    pass


# These fixed routes each identify exactly one operation in docs.mem0.ai/openapi.json.
ROUTES = {
    "add_memories": ("POST", "/v3/memories/add/"),
    "list_memories": ("POST", "/v3/memories/"),
    "search_memories": ("POST", "/v3/memories/search/"),
    "get_memory": ("GET", "/v1/memories/{memory_id}/"),
    "update_memory": ("PUT", "/v1/memories/{memory_id}/"),
    "delete_memory": ("DELETE", "/v1/memories/{memory_id}/"),
    "get_memory_history": ("GET", "/v1/memories/{memory_id}/history/"),
    "batch_update_memories": ("PUT", "/v1/batch/"),
    "batch_delete_memories": ("DELETE", "/v1/batch/"),
    "list_entities": ("GET", "/v1/entities/"),
    "get_entity": ("GET", "/v2/entities/{entity_type}/{entity_id}/"),
    "delete_entity": ("DELETE", "/v2/entities/{entity_type}/{entity_id}/"),
    "create_user": ("POST", "/v1/users/"),
    "create_agent": ("POST", "/v1/agents/"),
    "create_app": ("POST", "/v1/apps/"),
    "create_run": ("POST", "/v1/runs/"),
    "get_event": ("GET", "/v1/event/{event_id}/"),
    "get_statistics": ("GET", "/v1/stats/"),
    "check_connection": ("GET", "/v1/ping/"),
    "submit_feedback": ("POST", "/v1/feedback/"),
}


class Mem0Node(WorkflowNode):
    integration_type = "automation-mem0"
    connection_evidence = ConnectionEvidence(noun="Mem0 entities", operation="list_entities",
        identity_operation="check_connection", identity_keys=("user_email", "project_id", "org_id"))

    @classmethod
    def get_config_model(cls):
        return Mem0Config

    async def execute(self, input_data: Any):
        config = self.config
        if not isinstance(config, Mem0Config) or not config.credentials:
            raise ValueError("Connect a Mem0 API key")
        op, credential = config.config, config.credentials
        method, route = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        for field in ("memory_id", "event_id", "entity_type", "entity_id"):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", quote(values.pop(field), safe=""))
        for field in ("messages", "memories", "filters", "metadata"):
            if field in values:
                values[field] = json.loads(values[field])
        query = values if method == "GET" or isinstance(op, DeleteMemory) else None
        if query is not None:
            query = {k: str(v).lower() if isinstance(v, bool) else v for k, v in query.items()}
        body = values if query is None and values else None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Token " + credential.api_key, "Accept": "application/json"},
                    params=query, json=body)
            try:
                payload = response.json()
            except ValueError:
                return {"status": "error", "error": "Mem0 returned a non-JSON response", "http_status": response.status_code}
            # Error text is provider-authored, with the credential removed if echoed.
            if not 200 <= response.status_code < 300:
                detail = payload.get("detail", payload.get("error", payload.get("message", payload))) if isinstance(payload, dict) else payload
                return {"status": "error", "error": str(detail).replace(credential.api_key, "[redacted]"), "http_status": response.status_code}
            if not isinstance(payload, (dict, list)):
                return {"status": "error", "error": "Mem0 returned an unexpected JSON shape"}
            if not isinstance(op, GetEvent) and isinstance(payload, dict) and (payload.get("error") or payload.get("detail")):
                return {"status": "error", "error": str(payload.get("error") or payload["detail"]).replace(credential.api_key, "[redacted]")}
            # Never infer completion from the HTTP status: async PENDING/event_id survives.
            return {"status": "success", "data": payload, "http_status": response.status_code}
        except httpx.HTTPError:
            return {"status": "error", "error": "Mem0 request could not be completed; inspect the event or account before retrying a write"}
