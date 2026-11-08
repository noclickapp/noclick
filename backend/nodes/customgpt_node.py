"""CustomGPT.ai v1 operations against the published OpenAPI 1.0.0 contract.

Each operation makes one request. List results preserve the provider's pagination;
source imports and document reindexing acknowledge work, not indexing completion.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.customgpt.ai"


class CustomgptAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="CustomGPT.ai API Token",
        extra="ignore",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.customgpt.ai",
            "x-credential-instructions": "In CustomGPT.ai, open Developers, create an API key and paste the token here. NoClick sends it as a Bearer token to app.customgpt.ai. Connecting reads your current user profile; it does not test write permissions.",
        },
    )
    credential_type: Literal["customgpt_api_token"] = Field(
        "customgpt_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        title="API token",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without a Bearer header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Agent(_Input):
    project_id: int = Field(
        ..., ge=1, description="Agent ID (called projectId in the API)."
    )


class _Page(_Agent):
    page: int = Field(
        1, ge=1, description="Page number. Use next_page from the previous response."
    )


class _Document(_Agent):
    page_id: int = Field(..., ge=1, description="Document page ID.")


class _Conversation(_Agent):
    session_id: str = Field(
        ..., min_length=1, max_length=255, description="Conversation session ID."
    )

    @field_validator("session_id")
    @classmethod
    def session(cls, value):
        if (
            value in {".", ".."}
            or any(c in value for c in "/\\?#")
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Use a single conversation session ID")
        return value


def _url(value):
    if value is None:
        return value
    p = urlsplit(value)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        raise ValueError("Use a public HTTP or HTTPS source URL without credentials")
    return value


class GetCurrentUser(_Input):
    """Get current user."""

    operation: Literal["get_current_user"] = "get_current_user"


class ListAgents(_Input):
    """List agents."""

    operation: Literal["list_agents"] = "list_agents"
    page: int = Field(1, ge=1)
    name: Optional[str] = None
    order: Literal["asc", "desc"] = "desc"
    orderBy: Literal["id", "created_at"] = "id"


class CreateAgent(_Input):
    """Create agent."""

    operation: Literal["create_agent"] = "create_agent"
    project_name: str = Field(..., min_length=1, max_length=255)
    sitemap_path: Optional[str] = None
    _source = field_validator("sitemap_path")(_url)


class GetAgent(_Agent):
    """Get agent."""

    operation: Literal["get_agent"] = "get_agent"


class UpdateAgent(_Agent):
    """Update agent."""

    operation: Literal["update_agent"] = "update_agent"
    project_name: str = Field(..., min_length=1, max_length=255)


class DeleteAgent(_Agent):
    """Delete agent."""

    operation: Literal["delete_agent"] = "delete_agent"


class GetAgentStatistics(_Agent):
    """Get agent statistics."""

    operation: Literal["get_agent_statistics"] = "get_agent_statistics"


class ListDocuments(_Page):
    """List documents."""

    operation: Literal["list_documents"] = "list_documents"
    limit: int = Field(20, ge=1, le=100)
    search: Optional[str] = None
    crawl_status: Literal["all", "ok", "failed", "n/a", "queued", "limited"] = "all"
    index_status: Literal["all", "ok", "failed", "n/a", "queued", "limited"] = "all"


class DeleteDocument(_Document):
    """Delete document."""

    operation: Literal["delete_document"] = "delete_document"


class ReindexDocument(_Document):
    """Start document reindexing; acceptance does not prove indexing finished."""

    operation: Literal["reindex_document"] = "reindex_document"


class GetDocumentMetadata(_Document):
    """Get document metadata."""

    operation: Literal["get_document_metadata"] = "get_document_metadata"


class GetAgentSettings(_Agent):
    """Get agent settings."""

    operation: Literal["get_agent_settings"] = "get_agent_settings"


class ListConversations(_Page):
    """List conversations."""

    operation: Literal["list_conversations"] = "list_conversations"
    name: Optional[str] = None
    order: Literal["asc", "desc"] = "desc"
    userFilter: Literal["all", "anonymous", "team_member", "me"] = "all"


class CreateConversation(_Agent):
    """Create conversation."""

    operation: Literal["create_conversation"] = "create_conversation"
    name: str = Field(..., min_length=1, max_length=255)


class UpdateConversation(_Conversation):
    """Update conversation."""

    operation: Literal["update_conversation"] = "update_conversation"
    name: str = Field(..., min_length=1, max_length=255)


class DeleteConversation(_Conversation):
    """Delete conversation."""

    operation: Literal["delete_conversation"] = "delete_conversation"


class ListMessages(_Conversation):
    """List messages."""

    operation: Literal["list_messages"] = "list_messages"
    page: int = Field(1, ge=1)
    order: Literal["asc", "desc"] = "desc"
    includeInsights: StrictBool = False


class SendMessage(_Conversation):
    """Send message."""

    operation: Literal["send_message"] = "send_message"
    prompt: str = Field(..., min_length=1)
    lang: str = Field("en", max_length=10)
    custom_context: Optional[str] = None
    custom_persona: Optional[str] = None
    response_source: Literal["default", "own_content", "openai_content"] = "default"


class ListSources(_Agent):
    """List sources."""

    operation: Literal["list_sources"] = "list_sources"


class AddSource(_Agent):
    """Import a URL source; inspect source and page status for indexing progress."""

    operation: Literal["add_source"] = "add_source"
    sitemap_path: str = Field(
        ..., min_length=1, description="Public sitemap, website, YouTube or Vimeo URL."
    )
    _source = field_validator("sitemap_path")(_url)


class DeleteSource(_Agent):
    """Delete source."""

    operation: Literal["delete_source"] = "delete_source"
    source_id: int = Field(..., ge=1)


class GetCitation(_Agent):
    """Get citation."""

    operation: Literal["get_citation"] = "get_citation"
    citation_id: int = Field(..., ge=1)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class CreateChatCompletion(_Agent):
    """Create chat completion."""

    operation: Literal["create_chat_completion"] = "create_chat_completion"
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=100)
    model: Optional[str] = None
    lang: str = "en"


CustomgptOperation = Annotated[
    Union[
        GetCurrentUser,
        ListAgents,
        CreateAgent,
        GetAgent,
        UpdateAgent,
        DeleteAgent,
        GetAgentStatistics,
        ListDocuments,
        DeleteDocument,
        ReindexDocument,
        GetDocumentMetadata,
        GetAgentSettings,
        ListConversations,
        CreateConversation,
        UpdateConversation,
        DeleteConversation,
        ListMessages,
        SendMessage,
        ListSources,
        AddSource,
        DeleteSource,
        GetCitation,
        CreateChatCompletion,
    ],
    Field(discriminator="operation"),
]


class CustomgptNodeConfig(NodeConfig[CustomgptOperation, CustomgptAPITokenCredential]):
    pass


ROUTES = {
    "get_current_user": ("GET", "/api/v1/user", "json"),
    "list_agents": ("GET", "/api/v1/projects", "json"),
    "create_agent": ("POST", "/api/v1/projects", "multipart"),
    "get_agent": ("GET", "/api/v1/projects/{project_id}", "json"),
    "update_agent": ("POST", "/api/v1/projects/{project_id}", "multipart"),
    "delete_agent": ("DELETE", "/api/v1/projects/{project_id}", "json"),
    "get_agent_statistics": ("GET", "/api/v1/projects/{project_id}/stats", "json"),
    "list_documents": ("GET", "/api/v1/projects/{project_id}/pages", "json"),
    "delete_document": (
        "DELETE",
        "/api/v1/projects/{project_id}/pages/{page_id}",
        "json",
    ),
    "reindex_document": (
        "POST",
        "/api/v1/projects/{project_id}/pages/{page_id}/reindex",
        "json",
    ),
    "get_document_metadata": (
        "GET",
        "/api/v1/projects/{project_id}/pages/{page_id}/metadata",
        "json",
    ),
    "get_agent_settings": ("GET", "/api/v1/projects/{project_id}/settings", "json"),
    "list_conversations": (
        "GET",
        "/api/v1/projects/{project_id}/conversations",
        "json",
    ),
    "create_conversation": (
        "POST",
        "/api/v1/projects/{project_id}/conversations",
        "json",
    ),
    "update_conversation": (
        "PUT",
        "/api/v1/projects/{project_id}/conversations/{session_id}",
        "json",
    ),
    "delete_conversation": (
        "DELETE",
        "/api/v1/projects/{project_id}/conversations/{session_id}",
        "json",
    ),
    "list_messages": (
        "GET",
        "/api/v1/projects/{project_id}/conversations/{session_id}/messages",
        "json",
    ),
    "send_message": (
        "POST",
        "/api/v1/projects/{project_id}/conversations/{session_id}/messages",
        "multipart",
    ),
    "list_sources": ("GET", "/api/v1/projects/{project_id}/sources", "json"),
    "add_source": ("POST", "/api/v1/projects/{project_id}/sources", "multipart"),
    "delete_source": (
        "DELETE",
        "/api/v1/projects/{project_id}/sources/{source_id}",
        "json",
    ),
    "get_citation": (
        "GET",
        "/api/v1/projects/{project_id}/citations/{citation_id}",
        "json",
    ),
    "create_chat_completion": (
        "POST",
        "/api/v1/projects/{project_id}/chat/completions",
        "json",
    ),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class CustomgptNode(WorkflowNode):
    integration_type = "automation-customgpt"
    connection_evidence = ConnectionEvidence(
        noun="account", identity_operation="get_current_user"
    )

    @classmethod
    def get_config_model(cls):
        return CustomgptNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CustomGPT.ai API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path, encoding = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("project_id", "page_id", "session_id", "source_id", "citation_id"):
            if "{" + key + "}" in path:
                path = path.replace(
                    "{" + key + "}", quote(str(values.pop(key)), safe="")
                )
        params, request = {}, {}
        if op.operation == "send_message":
            params = {"stream": "false", "lang": values.pop("lang")}
        if op.operation == "create_chat_completion":
            values["stream"] = False
        if method == "GET":
            params = {
                k: str(v).lower() if isinstance(v, bool) else v
                for k, v in values.items()
            }
        elif values:
            if encoding == "multipart":
                request["files"] = {
                    k: (None, str(v).lower() if isinstance(v, bool) else str(v))
                    for k, v in values.items()
                }
            else:
                request["json"] = values
        try:
            async with guarded_async_client(
                timeout=120, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    BASE + path,
                    params=params,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/json",
                    },
                    **request,
                )
        except httpx.HTTPError:
            raise ValueError(
                "CustomGPT.ai request did not complete; inspect provider state before retrying a write"
            ) from None
        if response.status_code >= 400:
            try:
                error = response.json()
            except ValueError:
                error = response.text[:1000]
            result = {
                "status": "error",
                "http_status": response.status_code,
                "error": error,
            }
        elif not 200 <= response.status_code < 300:
            raise ValueError("CustomGPT.ai returned an unexpected HTTP status")
        elif response.status_code == 204:
            result = {"status": "success", "http_status": 204, "acknowledged": True}
        else:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("CustomGPT.ai returned an unexpected JSON envelope")
            if payload.get("status") == "error":
                result = {
                    "status": "error",
                    "http_status": response.status_code,
                    "error": payload,
                }
            else:
                result = {
                    "status": "success",
                    "http_status": response.status_code,
                    "data": payload.get("data", payload),
                }
                if op.operation == "get_current_user":
                    profile = payload.get("data")
                    if not isinstance(profile, dict) or not (
                        profile.get("name") or profile.get("email")
                    ):
                        raise ValueError(
                            "CustomGPT.ai returned an incomplete user profile"
                        )
                page = payload.get("data")
                if op.operation == "list_messages" and isinstance(page, dict):
                    page = page.get("messages")
                if (
                    isinstance(page, dict)
                    and isinstance(page.get("current_page"), int)
                    and isinstance(page.get("last_page"), int)
                ):
                    result["next_page"] = (
                        page["current_page"] + 1
                        if page["current_page"] < page["last_page"]
                        else None
                    )
                if op.operation in {"create_agent", "add_source", "reindex_document"}:
                    result["indexing_complete"] = False
                if method == "DELETE":
                    result["absence_verified"] = False
        result = _redact(result, token)
        await self.emit(result)
        return result
