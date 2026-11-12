"""V0 API v2: fixed, documented chat, message, deployment and webhook operations.

Contract: https://v0.app/api/v2/openapi/json (2.0.0).
Each action makes exactly one provider request; pagination remains explicit.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-v0"
BASE_URL = "https://api.v0.dev/v2"
Privacy = Literal["public", "private", "team", "team-edit", "unlisted"]
Event = Literal["chat.created", "chat.updated", "chat.deleted", "message.created", "message.updated", "message.deleted", "message.finished"]


class V0APIKeyCredential(BaseModel):
    model_config = ConfigDict(title="V0 API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://v0.app/settings/keys",
        "x-credential-instructions": "Create an API key in V0 Settings → API Keys, then paste the key here. NoClick sends it as a bearer token to api.v0.dev. Your account must have permission for the selected action."
    })
    credential_type: Literal["v0_api_key"] = Field("v0_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without whitespace or a Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def saved_config(cls, value):
        # The editor saves credential attachments beside operation fields.
        if isinstance(value, dict) and "credentialIds" in value:
            return {key: item for key, item in value.items() if key != "credentialIds"}
        return value

    @field_validator("chat_id", "message_id", "hook_id", check_fields=False)
    @classmethod
    def resource_id(cls, value):
        if not value or value in {".", ".."} or any(c in value for c in "/\\?#\r\n"):
            raise ValueError("Paste a V0 resource ID, without a URL or path")
        return value


class ChatInput(Input):
    chat_id: str = Field(..., min_length=1, title="Chat ID", description="ID returned by List Chats or Create Chat.")


class HookInput(Input):
    hook_id: str = Field(..., min_length=1, title="Webhook ID")


class ModelConfiguration(Input):
    modelId: str = Field("v0-pro", description="V0 model ID or a supported AI Gateway creator/model ID.")
    imageGenerations: bool = False


class CreateChat(Input):
    """Generate a new chat from a prompt (this can incur V0 usage charges)."""
    operation: Literal["create_chat"] = "create_chat"
    message: str = Field(..., min_length=1, title="Message")
    title: Optional[str] = None
    privacy: Privacy = "private"
    system_prompt: Optional[str] = None
    model_configuration: Optional[ModelConfiguration] = None
    metadata: Optional[dict[str, str]] = None


class ListChats(Input):
    """Read one page of chats accessible to your account; pass back the cursor."""
    operation: Literal["list_chats"] = "list_chats"
    limit: int = Field(20, ge=1, le=100)
    cursor: Optional[str] = None
    order_by: Literal["createdAt", "updatedAt"] = "createdAt"
    order_direction: Literal["asc", "desc"] = "desc"
    author_id: Optional[str] = None
    vercel_project_id: Optional[str] = None
    metadata: Optional[dict[str, str]] = None


class GetChat(ChatInput):
    """Read an existing chat."""
    operation: Literal["get_chat"] = "get_chat"


class UpdateChat(ChatInput):
    """Change a chat's title, visibility or metadata."""
    operation: Literal["update_chat"] = "update_chat"
    title: Optional[str] = None
    privacy: Optional[Privacy] = None
    metadata: Optional[dict[str, Optional[str]]] = Field(None, description="Key/value updates; null values delete keys. An explicitly supplied null clears all metadata.")


class DeleteChat(ChatInput):
    """Permanently delete a chat."""
    operation: Literal["delete_chat"] = "delete_chat"


class ListMessages(ChatInput):
    """Read one page of chat messages."""
    operation: Literal["list_messages"] = "list_messages"
    limit: int = Field(20, ge=1, le=100)
    cursor: Optional[str] = None


class SendMessage(ChatInput):
    """Send a prompt to a chat (this can incur V0 usage charges)."""
    operation: Literal["send_message"] = "send_message"
    message: str = Field(..., min_length=1)
    system_prompt: Optional[str] = None
    model_configuration: Optional[ModelConfiguration] = None


class GetMessage(ChatInput):
    """Read a single message within a chat."""
    operation: Literal["get_message"] = "get_message"
    message_id: str = Field(..., min_length=1)


class StopMessage(ChatInput):
    """Ask V0 to stop an in-flight assistant generation at its next safe point."""
    operation: Literal["stop_message"] = "stop_message"
    message_id: str = Field(..., min_length=1)


class GetPreview(ChatInput):
    """Read preview details; a null result means the preview is still starting."""
    operation: Literal["get_preview"] = "get_preview"


class GetFiles(ChatInput):
    """Read the source files of a chat."""
    operation: Literal["get_files"] = "get_files"


class FileEdit(Input):
    path: str = Field(..., min_length=1, description="Project-relative path, e.g. app/page.tsx.")
    content: Optional[str] = Field(..., description="New content, or null to delete the file.")
    encoding: Literal["utf8", "base64"] = "utf8"


class UpdateFiles(ChatInput):
    """Create, update or delete source files in one chat."""
    operation: Literal["update_files"] = "update_files"
    files: list[FileEdit] = Field(..., min_length=1, max_length=100)

    @field_validator("files")
    @classmethod
    def unique_paths(cls, value):
        if len({f.path for f in value}) != len(value):
            raise ValueError("Each file path must be unique")
        return value


class DuplicateChat(ChatInput):
    """Duplicate an existing chat with a chosen visibility."""
    operation: Literal["duplicate_chat"] = "duplicate_chat"
    privacy: Privacy = "private"
    title: Optional[str] = None
    metadata: Optional[dict[str, str]] = None


class DeployChat(ChatInput):
    """Start a Vercel deployment; the returned ID does not mean the build finished."""
    operation: Literal["deploy_chat"] = "deploy_chat"


class GetUsageSummary(Input):
    """Read usage totals, optionally filtered by time range and user."""
    operation: Literal["get_usage_summary"] = "get_usage_summary"
    start: Optional[str] = Field(None, description="Inclusive UTC ISO 8601 timestamp.")
    end: Optional[str] = Field(None, description="Exclusive UTC ISO 8601 timestamp.")
    user_id: Optional[str] = None


class ListWebhooks(Input):
    """List your configured webhook IDs and names."""
    operation: Literal["list_webhooks"] = "list_webhooks"


class CreateWebhook(Input):
    """Register a webhook for V0 chat and message lifecycle events."""
    operation: Literal["create_webhook"] = "create_webhook"
    name: str
    events: list[Event]
    url: str = Field(..., description="Target URL that receives webhook payloads.")
    chat_id: Optional[str] = Field(None, description="Optional chat scope. Null subscribes without a chat restriction.")


class GetWebhook(HookInput):
    """Read a webhook configuration."""
    operation: Literal["get_webhook"] = "get_webhook"


class UpdateWebhook(HookInput):
    """Change a webhook's name, subscribed events or target URL."""
    operation: Literal["update_webhook"] = "update_webhook"
    name: Optional[str] = None
    events: Optional[list[Event]] = None
    url: Optional[str] = None


class DeleteWebhook(HookInput):
    """Delete a webhook subscription."""
    operation: Literal["delete_webhook"] = "delete_webhook"


# v0's own MCP server: agents get its tools through a person's v0 sign-in.
V0McpCredential = mcp_credential("v0", "https://v0.app/api/mcp", app="v0")
V0Credential = Union[V0APIKeyCredential, V0McpCredential]


Operation = Annotated[Union[CreateChat, ListChats, GetChat, UpdateChat, DeleteChat,
    ListMessages, SendMessage, GetMessage, StopMessage, GetPreview, GetFiles,
    UpdateFiles, DuplicateChat, DeployChat, GetUsageSummary, ListWebhooks,
    CreateWebhook, GetWebhook, UpdateWebhook, DeleteWebhook], Field(discriminator="operation")]


class V0Config(NodeConfig[Operation, V0Credential]):
    pass


# One and only one published operation per action; never accept arbitrary paths.
ROUTES = {
    "create_chat": ("POST", "/chats"),
    "list_chats": ("GET", "/chats"),
    "get_chat": ("GET", "/chats/{chat_id}"),
    "update_chat": ("PATCH", "/chats/{chat_id}"),
    "delete_chat": ("DELETE", "/chats/{chat_id}"),
    "list_messages": ("GET", "/chats/{chat_id}/messages"),
    "send_message": ("POST", "/chats/{chat_id}/messages"),
    "get_message": ("GET", "/chats/{chat_id}/messages/{message_id}"),
    "stop_message": ("POST", "/chats/{chat_id}/messages/{message_id}/stop"),
    "get_preview": ("GET", "/chats/{chat_id}/preview"),
    "get_files": ("GET", "/chats/{chat_id}/files"),
    "update_files": ("PATCH", "/chats/{chat_id}/files"),
    "duplicate_chat": ("POST", "/chats/{chat_id}/duplicate"),
    "deploy_chat": ("POST", "/chats/{chat_id}/deploy"),
    "get_usage_summary": ("GET", "/usage/summary"),
    "list_webhooks": ("GET", "/hooks"),
    "create_webhook": ("POST", "/hooks"),
    "get_webhook": ("GET", "/hooks/{hook_id}"),
    "update_webhook": ("PATCH", "/hooks/{hook_id}"),
    "delete_webhook": ("DELETE", "/hooks/{hook_id}"),
}
WIRE_NAMES = {"system_prompt": "systemPrompt", "model_configuration": "modelConfiguration",
    "order_by": "orderBy", "order_direction": "orderDirection", "author_id": "authorId",
    "vercel_project_id": "vercelProjectId", "chat_id": "chatId", "user_id": "userId"}
BODY_OPERATIONS = {"create_chat", "update_chat", "send_message", "update_files", "duplicate_chat", "create_webhook", "update_webhook"}


class V0Node(WorkflowNode):
    integration_type = "automation-v0"
    credential_provider_labels = {"v0": "v0 Account"}
    connection_evidence = ConnectionEvidence(operation="list_chats", noun="V0 chats")

    @classmethod
    def get_config_model(cls):
        return V0Config

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a V0 API Key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("chat_id", "message_id", "hook_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        values = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        if isinstance(config, UpdateFiles):
            values["files"] = [file.model_dump() for file in config.files]
        if isinstance(config, CreateWebhook):
            values["chatId"] = config.chat_id  # required nullable property in v2
        if isinstance(config, UpdateChat) and "metadata" in config.model_fields_set and config.metadata is None:
            values["metadata"] = None
        params = values if method == "GET" else None
        if isinstance(config, ListChats) and "metadata" in values:
            metadata = params.pop("metadata")
            params.update({f"metadata[{key}]": value for key, value in metadata.items()})
        kwargs = {"params": params} if params is not None else {}
        if config.operation in BODY_OPERATIONS:
            kwargs["json"] = values
        token = self.config.credentials.api_key
        async with guarded_async_client(timeout=180, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for manual connect; never echo a key.
            message = response.text[:2000].replace(token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": f"V0 HTTP {response.status_code}: {message}"}
        if len(response.content) > 20_000_000:
            raise ValueError("V0 response exceeds 20 MB")
        if response.status_code == 204:
            return {"status": "success", "data": None}
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Expected a JSON response from V0")
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            raise ValueError("V0 returned an error envelope")
        result = {"status": "success", "data": body}
        if isinstance(config, ListChats):
            if not isinstance(body, dict) or not isinstance(body.get("chats"), list):
                raise ValueError("Expected a V0 chats page")
            result["items"] = body["chats"]
        return result
