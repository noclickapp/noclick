"""Relevance AI tools, agents and knowledge over the published latest contract.

Each operation maps to one endpoint. Lists return a single page; jobs are started
and polled explicitly. The provider officially supports agent/tool triggering;
its other published endpoints are exposed with that limitation in their copy.
Contract: https://api-f1db6c.stack.tryrelevance.com/latest/openapi_schema.json
Auth/regions: https://relevanceai.com/docs/sdk/authentication
Region hosts: https://unpkg.com/@relevanceai/sdk@3.1.0/esm/region.js
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, Json, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

REGIONS = {"au": "f1db6c", "us": "bcbe5a", "eu": "d7b62b"}
ResourceID = Annotated[str, Field(min_length=1, max_length=240, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")]
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class RelevanceAIAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Relevance AI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://relevanceai.com/docs/sdk/authentication",
            "x-credential-instructions": "In your Relevance AI project settings, copy the project ID and API key, and select the project's region. Paste the key alone; NoClick sends project:key in Authorization. Use a project key with permissions for the selected operations, not an embed key. The provider officially supports triggering agents and tools; other published API endpoints are currently unsupported.",
        })
    credential_type: Literal["relevance_ai_api_key"] = Field("relevance_ai_api_key", json_schema_extra={"ui:hidden": True})
    project_id: ResourceID = Field(..., title="Project ID", description="The project ID from your Relevance AI project settings.")
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})
    region: Literal["au", "us", "eu"] = Field("au", title="Region", description="Select the region of your project: Australia, United States or Europe.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if ":" in value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key alone, without a project prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, validate_default=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number. Return one page only; increase this for the next page.")
    page_size: int = Field(20, ge=1, le=100, description="Maximum results on this page.")
    query: str | None = Field(None, max_length=100, description="Optional search text.")


class ListTools(_Page):
    """List tools in this project (published endpoint; currently unsupported by provider)."""
    operation: Literal["list_tools"] = Field("list_tools", title="List Tools", json_schema_extra={"ui:hidden": True})


class GetTool(_Input):
    """Get a tool definition (published endpoint; currently unsupported by provider)."""
    operation: Literal["get_tool"] = Field("get_tool", title="Get Tool", json_schema_extra={"ui:hidden": True})
    studio_id: ResourceID = Field(..., title="Tool ID", description="studio_id of the tool.")
    tool_version: str | None = Field(None, description="active, draft, or a specific version ID.")


class _RunTool(_Input):
    studio_id: ResourceID = Field(..., title="Tool ID", description="studio_id of the tool.")
    params: Json[dict] = Field('{}', title="Tool Inputs JSON", description="JSON object keyed by the tool's input names.", json_schema_extra=JSON_EDITOR)
    tool_version: str | None = Field(None, description="active, draft, or a specific version ID.")


class RunTool(_RunTool):
    """Run a tool once. Preserve output, status and execution errors."""
    operation: Literal["run_tool"] = Field("run_tool", title="Run Tool", json_schema_extra={"ui:hidden": True})


class RunToolAsync(_RunTool):
    """Start a tool job; use its returned job_id with Get Tool Job."""
    operation: Literal["run_tool_async"] = Field("run_tool_async", title="Run Tool Asynchronously", json_schema_extra={"ui:hidden": True})


class GetToolJob(_Input):
    """Poll a tool job once; keep type and last_message_id for the next poll."""
    operation: Literal["get_tool_job"] = Field("get_tool_job", title="Get Tool Job", json_schema_extra={"ui:hidden": True})
    studio_id: ResourceID = Field(..., title="Tool ID")
    job_id: ResourceID = Field(..., title="Job ID")
    after_message_id: int | None = Field(None, ge=0, description="last_message_id returned by the previous poll.")


class ListAgents(_Page):
    """List project agents (published endpoint; currently unsupported by provider)."""
    operation: Literal["list_agents"] = Field("list_agents", title="List Agents", json_schema_extra={"ui:hidden": True})


class GetAgent(_Input):
    """Get an agent definition (published endpoint; currently unsupported by provider)."""
    operation: Literal["get_agent"] = Field("get_agent", title="Get Agent", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID = Field(..., title="Agent ID")
    version: str | None = Field(None, description="active, draft, or a specific version ID.")


class TriggerAgent(_Input):
    """Send a user message to start an agent or continue a conversation; returns job metadata, not the agent's final answer."""
    operation: Literal["trigger_agent"] = Field("trigger_agent", title="Trigger Agent", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID = Field(..., title="Agent ID")
    message: str = Field(..., min_length=1, title="Message")
    conversation_id: ResourceID | None = Field(None, description="Continue this conversation; omit to start a new one.")
    external_id: str | None = Field(None, description="Source-system conversation ID. By default an existing ID does not create a second conversation.")
    external_id_behaviour: Literal["nothing", "extend-conversation"] | None = None
    params: Json[dict] | None = Field(None, title="Agent Inputs JSON", json_schema_extra=JSON_EDITOR)


class ListConversations(_Page):
    """List agent conversations (published endpoint; currently unsupported by provider)."""
    operation: Literal["list_conversations"] = Field("list_conversations", title="List Conversations", json_schema_extra={"ui:hidden": True})


class ListKnowledgeSets(_Page):
    """List knowledge tables (published endpoint; currently unsupported by provider)."""
    operation: Literal["list_knowledge_sets"] = Field("list_knowledge_sets", title="List Knowledge Tables", json_schema_extra={"ui:hidden": True})
    include_metadata: bool = False
    include_counts: bool = True


class GetKnowledgeMetadata(_Input):
    """Get knowledge table metadata (published endpoint; currently unsupported by provider)."""
    operation: Literal["get_knowledge_metadata"] = Field("get_knowledge_metadata", title="Get Knowledge Table Metadata", json_schema_extra={"ui:hidden": True})
    knowledge_set: ResourceID = Field(..., title="Knowledge Table ID")


class ListKnowledge(_Page):
    """Read/search knowledge rows (published endpoint; currently unsupported by provider)."""
    operation: Literal["list_knowledge"] = Field("list_knowledge", title="List Knowledge Rows", json_schema_extra={"ui:hidden": True})
    knowledge_set: ResourceID = Field(..., title="Knowledge Table ID")
    document_id: ResourceID | None = Field(None, title="Document ID")


class TextKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"]
    value: str
    document_id: str | None = None


class DocumentKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["document"]
    value: dict
    document_id: str | None = None


class AddKnowledge(_Input):
    """Add text or JSON documents to a table (published endpoint; currently unsupported by provider)."""
    operation: Literal["add_knowledge"] = Field("add_knowledge", title="Add Knowledge", json_schema_extra={"ui:hidden": True})
    knowledge_set: ResourceID = Field(..., title="Knowledge Table ID")
    data: Json[Annotated[list[Annotated[Union[TextKnowledge, DocumentKnowledge], Field(discriminator="type")]], Field(min_length=1, max_length=100)]] = Field(
        ..., title="Documents JSON", description='Array of text or document records, e.g. [{"type":"text","value":"Company policy"}]. Optional document_id identifies a row.', json_schema_extra=JSON_EDITOR)
    chunk_and_vectorize_on_upload: bool | None = Field(None, description="Ask the provider to chunk and vectorize the uploaded records.")


class DeleteKnowledge(_Input):
    """Delete one knowledge row (published endpoint; currently unsupported by provider)."""
    operation: Literal["delete_knowledge"] = Field("delete_knowledge", title="Delete Knowledge Row", json_schema_extra={"ui:hidden": True})
    knowledge_set: ResourceID = Field(..., title="Knowledge Table ID")
    document_id: ResourceID = Field(..., title="Document ID", description="One explicit row ID; required to avoid deleting the whole table.")


RelevanceAIOperation = Annotated[Union[ListTools, GetTool, RunTool, RunToolAsync, GetToolJob,
    ListAgents, GetAgent, TriggerAgent, ListConversations, ListKnowledgeSets,
    GetKnowledgeMetadata, ListKnowledge, AddKnowledge, DeleteKnowledge], Field(discriminator="operation")]


class RelevanceAIConfig(NodeConfig[RelevanceAIOperation, RelevanceAIAPIKeyCredential]):
    pass


# One operation -> one published method/path. No custom routes or implicit reads.
OPERATIONS = {
    "list_tools": ("GET", "/studios/list", ()),
    "get_tool": ("GET", "/studios/{studio_id}/get", ("studio_id",)),
    "run_tool": ("POST", "/studios/{studio_id}/trigger", ("studio_id",)),
    "run_tool_async": ("POST", "/studios/{studio_id}/trigger_async", ("studio_id",)),
    "get_tool_job": ("GET", "/studios/{studio_id}/async_poll/{job_id}", ("studio_id", "job_id")),
    "list_agents": ("POST", "/agents/list", ()),
    "get_agent": ("GET", "/agents/{agent_id}/get", ("agent_id",)),
    "trigger_agent": ("POST", "/agents/trigger", ()),
    "list_conversations": ("GET", "/agents/conversations/list", ()),
    "list_knowledge_sets": ("POST", "/knowledge/sets/list", ()),
    "get_knowledge_metadata": ("GET", "/knowledge/sets/{knowledge_set}/get_metadata", ("knowledge_set",)),
    "list_knowledge": ("POST", "/knowledge/list", ()),
    "add_knowledge": ("POST", "/knowledge/add", ()),
    "delete_knowledge": ("POST", "/knowledge/delete", ()),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(key, "[redacted]"): _redact(v, key) for k, v in value.items()}
    return value


class RelevanceAINode(WorkflowNode):
    integration_type = "automation-relevance-ai"
    connection_evidence = ConnectionEvidence(operation="list_agents", noun="Relevance AI agents")

    @classmethod
    def get_config_model(cls):
        return RelevanceAIConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Relevance AI API key")
        op = self.config.config
        method, path, path_fields = OPERATIONS[op.operation]
        data = op.model_dump(mode="python", exclude_none=True, exclude={"operation", *path_fields})
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(getattr(op, field), safe=""))
        if op.operation == "trigger_agent":
            data["message"] = {"role": "user", "content": op.message}
        if method == "GET":
            data = {k: str(v).lower() if isinstance(v, bool) else v for k, v in data.items()}
        url = f"https://api-{REGIONS[credential.region]}.stack.tryrelevance.com/latest" + path
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url,
                headers={"Authorization": credential.project_id + ":" + credential.api_key, "Accept": "application/json"},
                **({"params": data} if method == "GET" else {"json": data}))
        if response.status_code >= 300:
            try:
                body = response.json()
                message = body.get("message") or body.get("error") or body.get("detail") or response.reason_phrase
                if isinstance(message, dict):
                    message = message.get("message") or message.get("code") or response.reason_phrase
            except (ValueError, AttributeError):
                message = response.reason_phrase
            return {"status": "error", "status_code": response.status_code,
                    "error": _redact(str(message), credential.api_key)[:2000]}
        if "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Relevance AI returned a non-JSON API response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Relevance AI returned an unexpected response shape")
        payload = _redact(payload, credential.api_key)
        if payload.get("error") or payload.get("status") in {"failed", "cancelled"} or payload.get("type") == "failed":
            return {"status": "error", "error": str(payload.get("error") or payload.get("errors") or "Relevance AI execution failed"), "data": payload}
        # An HTTP 200 alone must not make an empty/foreign envelope evidence
        # that a credential worked. Preserve all fields after checking the
        # documented wrapper, including unknown fields added by the provider.
        wrapper = {
            "list_tools": ("results", list), "list_agents": ("results", list),
            "list_conversations": ("results", list), "list_knowledge_sets": ("results", list),
            "list_knowledge": ("results", list), "add_knowledge": ("results", list),
            "get_tool": ("studio", dict), "get_agent": ("agent", dict),
            "get_knowledge_metadata": ("metadata", dict), "run_tool": ("output", dict),
            "get_tool_job": ("updates", list), "trigger_agent": ("job_info", dict),
            "run_tool_async": ("job_id", str),
        }.get(op.operation)
        if wrapper and not isinstance(payload.get(wrapper[0]), wrapper[1]):
            raise ValueError("Relevance AI returned an unexpected response shape")
        return {"status": "success", "data": payload}
