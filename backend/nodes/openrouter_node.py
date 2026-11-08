"""OpenRouter API v1: one documented request per workflow operation.

Contract: https://openrouter.ai/openapi.json, version 1.0.0.
List operations return a single page; use offset to request another page.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://openrouter.ai/api/v1"
Segment = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")]

class OpenRouterAPIKey(BaseModel):
    model_config = ConfigDict(title="OpenRouter API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://openrouter.ai/settings/keys",
        "x-credential-instructions": "Paste an OpenRouter API key. Chat and embeddings require credit. Listing, creating, updating and deleting API keys and reading credits or activity require a management key with the corresponding permissions. The connection check reads the current key label and limits; it does not prove access to every operation."})
    credential_type: Literal["openrouter_api_key"] = Field("openrouter_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without an Authorization header")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class ChatMessage(Input):
    role: Literal["system", "user", "assistant"]
    content: str

class GetCurrentKey(Input):
    """Get current key."""
    operation: Literal["get_current_key"] = Field("get_current_key", json_schema_extra={"ui:hidden": True})

class GetCredits(Input):
    """Get credits."""
    operation: Literal["get_credits"] = Field("get_credits", json_schema_extra={"ui:hidden": True})

class ListModels(Input):
    """List models."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0)
    page_size: int = Field(100, ge=1, le=1000)
    category: Literal["programming", "roleplay", "marketing", "marketing/seo", "technology", "science", "translation", "legal", "finance", "health", "trivia", "academia"] | None = None

class ListUserModels(Input):
    """List user models."""
    operation: Literal["list_user_models"] = Field("list_user_models", json_schema_extra={"ui:hidden": True})

class ListEmbeddingModels(Input):
    """List embedding models."""
    operation: Literal["list_embedding_models"] = Field("list_embedding_models", json_schema_extra={"ui:hidden": True})

class ListProviders(Input):
    """List providers."""
    operation: Literal["list_providers"] = Field("list_providers", json_schema_extra={"ui:hidden": True})

class ListModelEndpoints(Input):
    """List model endpoints."""
    operation: Literal["list_model_endpoints"] = Field("list_model_endpoints", json_schema_extra={"ui:hidden": True})
    author: Segment
    slug: Segment

class GetGeneration(Input):
    """Get generation."""
    operation: Literal["get_generation"] = Field("get_generation", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^gen-[0-9A-Za-z-]+$", max_length=128)

class GetActivity(Input):
    """Get activity."""
    operation: Literal["get_activity"] = Field("get_activity", json_schema_extra={"ui:hidden": True})
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

class ListKeys(Input):
    """List keys."""
    operation: Literal["list_keys"] = Field("list_keys", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0)
    include_disabled: bool = False
    include_expired: bool = False

class GetKey(Input):
    """Get key."""
    operation: Literal["get_key"] = Field("get_key", json_schema_extra={"ui:hidden": True})
    hash: Segment

class CreateKey(Input):
    """Create key."""
    operation: Literal["create_key"] = Field("create_key", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=256)
    limit: float | None = Field(None, ge=0, lt=1000000)
    limit_reset: Literal["daily", "weekly", "monthly"] | None = None
    include_byok_in_limit: bool | None = None

class UpdateKey(Input):
    """Update key."""
    operation: Literal["update_key"] = Field("update_key", json_schema_extra={"ui:hidden": True})
    hash: Segment
    name: str | None = Field(None, min_length=1, max_length=256)
    limit: float | None = Field(None, ge=0, lt=1000000)
    limit_reset: Literal["daily", "weekly", "monthly"] | None = None
    disabled: bool | None = None
    include_byok_in_limit: bool | None = None

class DeleteKey(Input):
    """Delete key."""
    operation: Literal["delete_key"] = Field("delete_key", json_schema_extra={"ui:hidden": True})
    hash: Segment

class CreateChatCompletion(Input):
    """Create chat completion."""
    operation: Literal["create_chat_completion"] = Field("create_chat_completion", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1)
    messages: list[ChatMessage] = Field(..., min_length=1)
    temperature: float | None = Field(None, ge=0, le=2)
    max_completion_tokens: int | None = Field(None, ge=1)

class CreateEmbeddings(Input):
    """Create embeddings."""
    operation: Literal["create_embeddings"] = Field("create_embeddings", json_schema_extra={"ui:hidden": True})
    model: str = Field(..., min_length=1)
    input: str | list[str]
    dimensions: int | None = Field(None, ge=1)

OpenRouterOperation = Annotated[Union[GetCurrentKey, GetCredits, ListModels, ListUserModels, ListEmbeddingModels, ListProviders, ListModelEndpoints, GetGeneration, GetActivity, ListKeys, GetKey, CreateKey, UpdateKey, DeleteKey, CreateChatCompletion, CreateEmbeddings], Field(discriminator="operation")]

class OpenRouterConfig(NodeConfig[OpenRouterOperation, OpenRouterAPIKey]):
    pass

ROUTES = {'get_current_key': ('GET', '/key'), 'get_credits': ('GET', '/credits'), 'list_models': ('GET', '/models'), 'list_user_models': ('GET', '/models/user'), 'list_embedding_models': ('GET', '/embeddings/models'), 'list_providers': ('GET', '/providers'), 'list_model_endpoints': ('GET', '/models/{author}/{slug}/endpoints'), 'get_generation': ('GET', '/generation'), 'get_activity': ('GET', '/activity'), 'list_keys': ('GET', '/keys'), 'get_key': ('GET', '/keys/{hash}'), 'create_key': ('POST', '/keys'), 'update_key': ('PATCH', '/keys/{hash}'), 'delete_key': ('DELETE', '/keys/{hash}'), 'create_chat_completion': ('POST', '/chat/completions'), 'create_embeddings': ('POST', '/embeddings')}

class OpenRouterNode(WorkflowNode):
    integration_type = "automation-openrouter"
    connection_evidence = ConnectionEvidence(noun="API key", identity_operation="get_current_key", identity_keys=("label",))

    @classmethod
    def get_config_model(cls):
        return OpenRouterConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an OpenRouter API key")
        config = self.config.config
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_unset=method != "GET", exclude_none=method == "GET")
        for name in ("author", "slug", "hash"):
            if "{" + name + "}" in route:
                route = route.replace("{" + name + "}", quote(values.pop(name), safe=""))
        if config.operation == "list_models":
            values["limit"] = values.pop("page_size")
        # Explicit null removes key limits/reset periods; absent fields stay absent.
        if config.operation == "create_chat_completion":
            values["stream"] = False
        if config.operation == "create_embeddings":
            values["encoding_format"] = "float"
        kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PATCH"} else {}
        token = self.config.credentials.api_key
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.request(method, BASE + route, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
            if not response.is_success:
                try:
                    error = response.json().get("error", {})
                    message = error.get("message") if isinstance(error, dict) else str(error)
                except (ValueError, AttributeError):
                    message = None
                return {"status": "error", "http_status": response.status_code, "error": (message or "OpenRouter rejected the request").replace(token, "[redacted]")}
            body = response.json()
            if not isinstance(body, dict) or "error" in body:
                raise ValueError("OpenRouter returned an invalid response")
            return {"status": "success", **body}
        except httpx.HTTPError:
            raise ValueError("OpenRouter request could not be completed; inspect usage before retrying a write") from None
