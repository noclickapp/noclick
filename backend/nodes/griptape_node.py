"""Griptape Cloud operations against the published 2023-09-19 API contract.

Each operation makes one request. Runs return immediately, without polling or
retries. The /api prefix is included once, matching Griptape's official SDK.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://cloud.griptape.ai"
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class GriptapeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Griptape API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.griptape.ai/en/articles/10509294-api-keys",
            "x-credential-instructions": "Create an API key in Griptape Cloud and paste it here. NoClick sends it as a Bearer token only to cloud.griptape.ai. The connection check lists your conversation threads. The key must have access to the resources your workflow uses.",
        })
    credential_type: Literal["griptape_api_key"] = Field("griptape_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Paged(_Input):
    page: int = Field(1, ge=1, description="Page number. Use data.pagination.next_page to continue; only one page is returned.")
    page_size: int = Field(20, ge=1, le=100)


class GriptapeListStructuresConfig(_Paged):
    """List deployed structures in one page."""
    operation: Literal["list_structures"] = Field("list_structures", json_schema_extra={"ui:hidden": True})


class GriptapeGetStructureConfig(_Input):
    """Get a structure configuration."""
    operation: Literal["get_structure"] = Field("get_structure", json_schema_extra={"ui:hidden": True})
    structure_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeListStructureRunsConfig(_Paged):
    """List one page of runs for a structure."""
    operation: Literal["list_structure_runs"] = Field("list_structure_runs", json_schema_extra={"ui:hidden": True})
    structure_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeCreateStructureRunConfig(_Input):
    """Start a structure run; returns immediately and may incur provider charges."""
    operation: Literal["create_structure_run"] = Field("create_structure_run", json_schema_extra={"ui:hidden": True})
    structure_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")
    args: str = Field("[]", description="JSON array of string arguments, for example [\"arg1\"].", json_schema_extra={**JSON_EDITOR, "contentMediaType": "application/json", "contentSchema": {"type": "array", "items": {"type": "string"}}})

    @field_validator("args")
    @classmethod
    def arguments(cls, value):
        try:
            parsed = json.loads(value)
        except ValueError:
            raise ValueError("Enter a JSON array of strings") from None
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise ValueError("Enter a JSON array of strings")
        return value


class GriptapeGetStructureRunConfig(_Input):
    """Get a run status and output."""
    operation: Literal["get_structure_run"] = Field("get_structure_run", json_schema_extra={"ui:hidden": True})
    structure_run_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeCancelStructureRunConfig(_Input):
    """Request cancellation of a structure run."""
    operation: Literal["cancel_structure_run"] = Field("cancel_structure_run", json_schema_extra={"ui:hidden": True})
    structure_run_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeListStructureRunEventsConfig(_Input):
    """Read a bounded page of structure run events."""
    operation: Literal["list_structure_run_events"] = Field("list_structure_run_events", json_schema_extra={"ui:hidden": True})
    structure_run_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class GriptapeListAssistantsConfig(_Paged):
    """List one page of assistants."""
    operation: Literal["list_assistants"] = Field("list_assistants", json_schema_extra={"ui:hidden": True})


class GriptapeGetAssistantConfig(_Input):
    """Get an assistant configuration."""
    operation: Literal["get_assistant"] = Field("get_assistant", json_schema_extra={"ui:hidden": True})
    assistant_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeCreateAssistantRunConfig(_Input):
    """Start a non-streaming assistant run; may incur provider charges."""
    operation: Literal["create_assistant_run"] = Field("create_assistant_run", json_schema_extra={"ui:hidden": True})
    assistant_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")
    input: str = Field(..., description="Prompt to send to the assistant.")
    thread_id: str | None = Field(None, pattern=UUID_PATTERN)
    new_thread: bool = Field(False, description="Create a thread if no thread_id is supplied.")


class GriptapeGetAssistantRunConfig(_Input):
    """Get an assistant run and its output."""
    operation: Literal["get_assistant_run"] = Field("get_assistant_run", json_schema_extra={"ui:hidden": True})
    assistant_run_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeCancelAssistantRunConfig(_Input):
    """Request cancellation of an assistant run."""
    operation: Literal["cancel_assistant_run"] = Field("cancel_assistant_run", json_schema_extra={"ui:hidden": True})
    assistant_run_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeListThreadsConfig(_Paged):
    """List one page of conversation threads."""
    operation: Literal["list_threads"] = Field("list_threads", json_schema_extra={"ui:hidden": True})


class GriptapeCreateThreadConfig(_Input):
    """Create a named conversation thread."""
    operation: Literal["create_thread"] = Field("create_thread", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=200)
    alias: str | None = Field(None, min_length=1, max_length=200)


class GriptapeGetThreadConfig(_Input):
    """Get a conversation thread."""
    operation: Literal["get_thread"] = Field("get_thread", json_schema_extra={"ui:hidden": True})
    thread_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeDeleteThreadConfig(_Input):
    """Delete a thread; this cannot be undone."""
    operation: Literal["delete_thread"] = Field("delete_thread", json_schema_extra={"ui:hidden": True})
    thread_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeListMessagesConfig(_Paged):
    """List one page of messages in a thread."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    thread_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeCreateMessageConfig(_Input):
    """Store a conversation input and output pair in a thread."""
    operation: Literal["create_message"] = Field("create_message", json_schema_extra={"ui:hidden": True})
    thread_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")
    input: str = Field(..., description="Stored user input.")
    output: str = Field(..., description="Stored assistant response.")


class GriptapeListKnowledgeBasesConfig(_Paged):
    """List one page of knowledge bases."""
    operation: Literal["list_knowledge_bases"] = Field("list_knowledge_bases", json_schema_extra={"ui:hidden": True})


class GriptapeGetKnowledgeBaseConfig(_Input):
    """Get knowledge base configuration."""
    operation: Literal["get_knowledge_base"] = Field("get_knowledge_base", json_schema_extra={"ui:hidden": True})
    knowledge_base_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")


class GriptapeQueryKnowledgeBaseConfig(_Input):
    """Query a knowledge base; returns the provider query response."""
    operation: Literal["query_knowledge_base"] = Field("query_knowledge_base", json_schema_extra={"ui:hidden": True})
    knowledge_base_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")
    query: str = Field(..., min_length=1, description="Text to query or search for.")


class GriptapeSearchKnowledgeBaseConfig(_Input):
    """Search a knowledge base; returns the provider search response."""
    operation: Literal["search_knowledge_base"] = Field("search_knowledge_base", json_schema_extra={"ui:hidden": True})
    knowledge_base_id: str = Field(..., pattern=UUID_PATTERN, description="Griptape resource UUID (version 4).")
    query: str = Field(..., min_length=1, description="Text to query or search for.")


GriptapeOperation = Annotated[Union[
    GriptapeListStructuresConfig,
    GriptapeGetStructureConfig,
    GriptapeListStructureRunsConfig,
    GriptapeCreateStructureRunConfig,
    GriptapeGetStructureRunConfig,
    GriptapeCancelStructureRunConfig,
    GriptapeListStructureRunEventsConfig,
    GriptapeListAssistantsConfig,
    GriptapeGetAssistantConfig,
    GriptapeCreateAssistantRunConfig,
    GriptapeGetAssistantRunConfig,
    GriptapeCancelAssistantRunConfig,
    GriptapeListThreadsConfig,
    GriptapeCreateThreadConfig,
    GriptapeGetThreadConfig,
    GriptapeDeleteThreadConfig,
    GriptapeListMessagesConfig,
    GriptapeCreateMessageConfig,
    GriptapeListKnowledgeBasesConfig,
    GriptapeGetKnowledgeBaseConfig,
    GriptapeQueryKnowledgeBaseConfig,
    GriptapeSearchKnowledgeBaseConfig,
], Field(discriminator="operation")]


class GriptapeNodeConfig(NodeConfig[GriptapeOperation, GriptapeAPIKeyCredential]):
    pass


ROUTES = {
    "list_structures": ("GET", "/api/structures"),
    "get_structure": ("GET", "/api/structures/{structure_id}"),
    "list_structure_runs": ("GET", "/api/structures/{structure_id}/runs"),
    "create_structure_run": ("POST", "/api/structures/{structure_id}/runs"),
    "get_structure_run": ("GET", "/api/structure-runs/{structure_run_id}"),
    "cancel_structure_run": ("POST", "/api/structure-runs/{structure_run_id}/cancel"),
    "list_structure_run_events": ("GET", "/api/structure-runs/{structure_run_id}/events"),
    "list_assistants": ("GET", "/api/assistants"),
    "get_assistant": ("GET", "/api/assistants/{assistant_id}"),
    "create_assistant_run": ("POST", "/api/assistants/{assistant_id}/runs"),
    "get_assistant_run": ("GET", "/api/assistant-runs/{assistant_run_id}"),
    "cancel_assistant_run": ("POST", "/api/assistant-runs/{assistant_run_id}/cancel"),
    "list_threads": ("GET", "/api/threads"),
    "create_thread": ("POST", "/api/threads"),
    "get_thread": ("GET", "/api/threads/{thread_id}"),
    "delete_thread": ("DELETE", "/api/threads/{thread_id}"),
    "list_messages": ("GET", "/api/threads/{thread_id}/messages"),
    "create_message": ("POST", "/api/threads/{thread_id}/messages"),
    "list_knowledge_bases": ("GET", "/api/knowledge-bases"),
    "get_knowledge_base": ("GET", "/api/knowledge-bases/{knowledge_base_id}"),
    "query_knowledge_base": ("POST", "/api/knowledge-bases/{knowledge_base_id}/query"),
    "search_knowledge_base": ("POST", "/api/knowledge-bases/{knowledge_base_id}/search"),
}


# Keep raw provider envelopes (including pagination and async run IDs) under data.
# Evidence gets a parallel items list from the same single read.
LIST_KEYS = {
    "list_structures": "structures", "list_structure_runs": "structure_runs",
    "list_structure_run_events": "events", "list_assistants": "assistants",
    "list_threads": "threads", "list_messages": "messages",
    "list_knowledge_bases": "knowledge_bases",
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, key) for name, item in value.items()}
    return value


class GriptapeNode(WorkflowNode):
    integration_type = "automation-griptape"
    connection_evidence = ConnectionEvidence(operation="list_threads", noun="conversation threads", label_keys=("name", "alias", "thread_id"))

    @classmethod
    def get_config_model(cls):
        return GriptapeNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Griptape API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        if config.operation == "create_structure_run":
            values["args"] = json.loads(values["args"])
        if config.operation == "create_assistant_run":
            values["stream"] = False
        request = {"params": values} if method == "GET" else ({"json": values} if values else {})
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **request)
        except httpx.HTTPError:
            return {"status": "error", "error": "Griptape request did not complete; check the provider before retrying a write", "operation": config.operation}
        if not 200 <= response.status_code < 300:
            return {"status": "error", "error": response.text.replace(key, "[redacted]")[:2000] or "Griptape rejected the request",
                "http_status": response.status_code, "operation": config.operation}
        output = {"status": "success", "operation": config.operation, "http_status": response.status_code}
        if response.status_code == 204:
            return {**output, "acknowledged": True}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "error": "Griptape returned an invalid JSON response", "http_status": response.status_code}
        if not isinstance(data, dict) or data.get("errors") or data.get("error"):
            return {"status": "error", "error": _redact(json.dumps(data), key)[:2000], "http_status": response.status_code}
        output["data"] = _redact(data, key)
        if config.operation in LIST_KEYS:
            rows = data.get(LIST_KEYS[config.operation])
            if not isinstance(rows, list):
                return {"status": "error", "error": "Griptape omitted the requested resource list", "http_status": response.status_code}
            output["items"] = _redact(rows, key)
        return output
