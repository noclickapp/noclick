"""OpenAI API actions for ChatGPT automation using a person's project API key.

Each action makes one request to a fixed v1 route. List actions return one
provider page, including its cursors, so callers can explicitly continue.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.openai.com/v1"


class ChatGPTAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpenAI API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://platform.openai.com/api-keys",
            "x-credential-instructions": "Paste an OpenAI project API key with permission for the operations you use. API usage is billed separately from a ChatGPT subscription. NoClick checks access by listing available models; this proves key reachability, not account identity.",
        })
    credential_type: Literal["chatgpt_api_key"] = Field("chatgpt_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name in {"response_id", "completion_id", "file_id", "input_file_id", "batch_id", "vector_store_id", "after", "before"} and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", value):
                raise ValueError("Use a single OpenAI resource ID")
        return value


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="Maximum items in this page; continue with the returned last_id as after.")
    after: Optional[str] = Field(None, description="Cursor ID from the preceding page.")


class _OrderedPage(_Page):
    order: Literal["asc", "desc"] = "desc"


class ChatGPTMessage(_Input):
    role: Literal["developer", "system", "user", "assistant"]
    content: str = Field(..., min_length=1, description="Text message content.")


class ChatGPTCreateResponse(_Input):
    """Generate text or structured content with the Responses API."""
    operation: Literal["create_response"] = "create_response"
    model: str = Field(..., min_length=1, description="OpenAI model ID, for example gpt-4.1.")
    input: str = Field(..., min_length=1, description="Text prompt to send to the model.")
    instructions: Optional[str] = None
    max_output_tokens: Optional[int] = Field(None, ge=16)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    previous_response_id: Optional[str] = None
    store: bool = True
    background: bool = False


class ChatGPTCreateChatCompletion(_Input):
    """Generate a chat completion from text messages; optionally store it for later reads."""
    operation: Literal["create_chat_completion"] = "create_chat_completion"
    model: str = Field(..., min_length=1)
    messages: list[ChatGPTMessage] = Field(..., min_length=1)
    max_completion_tokens: Optional[int] = Field(None, ge=1)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    store: bool = False


class ChatGPTCreateEmbedding(_Input):
    """Create numeric embedding vectors for text."""
    operation: Literal["create_embedding"] = "create_embedding"
    model: str = Field(..., min_length=1, description="Embedding model, for example text-embedding-3-small.")
    input: Union[str, list[str]] = Field(..., description="Text or a batch of texts to embed.")
    dimensions: Optional[int] = Field(None, ge=1)


class ChatGPTCreateModeration(_Input):
    """Classify text against OpenAI safety categories."""
    operation: Literal["create_moderation"] = "create_moderation"
    input: Union[str, list[str]]
    model: str = "omni-moderation-latest"


class ChatGPTCreateBatch(_Input):
    """Start asynchronous processing of an existing uploaded batch input file."""
    operation: Literal["create_batch"] = "create_batch"
    input_file_id: str
    endpoint: Literal["/v1/responses", "/v1/chat/completions", "/v1/embeddings", "/v1/completions", "/v1/moderations", "/v1/images/generations", "/v1/images/edits", "/v1/videos"]
    completion_window: Literal["24h"] = "24h"
    metadata: Optional[dict[str, str]] = None


class ChatGPTCreateVectorStore(_Input):
    """Create a vector store, optionally from existing uploaded file IDs."""
    operation: Literal["create_vector_store"] = "create_vector_store"
    name: str = Field(..., min_length=1)
    file_ids: Optional[list[str]] = None
    metadata: Optional[dict[str, str]] = None


class ChatGPTGetResponse(_Input):
    """Get response using the corresponding OpenAI endpoint."""
    operation: Literal["get_response"] = "get_response"
    response_id: str


class ChatGPTDeleteResponse(_Input):
    """Delete response using the corresponding OpenAI endpoint."""
    operation: Literal["delete_response"] = "delete_response"
    response_id: str


class ChatGPTCancelResponse(_Input):
    """Cancel response using the corresponding OpenAI endpoint."""
    operation: Literal["cancel_response"] = "cancel_response"
    response_id: str


class ChatGPTListResponseInputItems(_Page):
    """List response input items using the corresponding OpenAI endpoint."""
    operation: Literal["list_response_input_items"] = "list_response_input_items"
    response_id: str
    order: Literal["asc", "desc"] = "desc"
    before: Optional[str] = None


class ChatGPTSearchVectorStore(_Input):
    """Search a vector store for relevant text chunks."""
    operation: Literal["search_vector_store"] = "search_vector_store"
    vector_store_id: str
    query: Union[str, list[str]]
    max_num_results: Optional[int] = Field(None, ge=1, le=50)
    rewrite_query: Optional[bool] = None


class ChatGPTGetChatCompletion(_Input):
    """Get chat completion using the corresponding OpenAI endpoint."""
    operation: Literal["get_chat_completion"] = "get_chat_completion"
    completion_id: str


class ChatGPTDeleteChatCompletion(_Input):
    """Delete chat completion using the corresponding OpenAI endpoint."""
    operation: Literal["delete_chat_completion"] = "delete_chat_completion"
    completion_id: str


class ChatGPTListChatMessages(_OrderedPage):
    """List chat messages using the corresponding OpenAI endpoint."""
    operation: Literal["list_chat_messages"] = "list_chat_messages"
    completion_id: str


class ChatGPTListModels(_Input):
    """List models using the corresponding OpenAI endpoint."""
    operation: Literal["list_models"] = "list_models"


class ChatGPTGetModel(_Input):
    """Get model using the corresponding OpenAI endpoint."""
    operation: Literal["get_model"] = "get_model"
    model: str = Field(..., min_length=1)


class ChatGPTListFiles(_Input):
    """List files using the corresponding OpenAI endpoint."""
    operation: Literal["list_files"] = "list_files"
    purpose: Optional[Literal["assistants", "batch", "fine-tune", "vision", "user_data", "evals"]] = None
    limit: int = Field(100, ge=1, le=10000)
    after: Optional[str] = None
    order: Literal["asc", "desc"] = "desc"


class ChatGPTGetFile(_Input):
    """Get file using the corresponding OpenAI endpoint."""
    operation: Literal["get_file"] = "get_file"
    file_id: str


class ChatGPTDeleteFile(_Input):
    """Delete file using the corresponding OpenAI endpoint."""
    operation: Literal["delete_file"] = "delete_file"
    file_id: str


class ChatGPTListBatches(_Page):
    """List batches using the corresponding OpenAI endpoint."""
    operation: Literal["list_batches"] = "list_batches"


class ChatGPTGetBatch(_Input):
    """Get batch using the corresponding OpenAI endpoint."""
    operation: Literal["get_batch"] = "get_batch"
    batch_id: str


class ChatGPTCancelBatch(_Input):
    """Cancel batch using the corresponding OpenAI endpoint."""
    operation: Literal["cancel_batch"] = "cancel_batch"
    batch_id: str


class ChatGPTListVectorStores(_OrderedPage):
    """List vector stores using the corresponding OpenAI endpoint."""
    operation: Literal["list_vector_stores"] = "list_vector_stores"
    before: Optional[str] = None


class ChatGPTGetVectorStore(_Input):
    """Get vector store using the corresponding OpenAI endpoint."""
    operation: Literal["get_vector_store"] = "get_vector_store"
    vector_store_id: str


class ChatGPTDeleteVectorStore(_Input):
    """Delete vector store using the corresponding OpenAI endpoint."""
    operation: Literal["delete_vector_store"] = "delete_vector_store"
    vector_store_id: str


ChatGPTOperation = Annotated[Union[
    ChatGPTCreateResponse,
    ChatGPTGetResponse,
    ChatGPTDeleteResponse,
    ChatGPTCancelResponse,
    ChatGPTListResponseInputItems,
    ChatGPTCreateChatCompletion,
    ChatGPTSearchVectorStore,
    ChatGPTGetChatCompletion,
    ChatGPTDeleteChatCompletion,
    ChatGPTListChatMessages,
    ChatGPTCreateEmbedding,
    ChatGPTCreateModeration,
    ChatGPTListModels,
    ChatGPTGetModel,
    ChatGPTListFiles,
    ChatGPTGetFile,
    ChatGPTDeleteFile,
    ChatGPTCreateBatch,
    ChatGPTListBatches,
    ChatGPTGetBatch,
    ChatGPTCancelBatch,
    ChatGPTCreateVectorStore,
    ChatGPTListVectorStores,
    ChatGPTGetVectorStore,
    ChatGPTDeleteVectorStore
], Field(discriminator="operation")]


class ChatGPTConfig(NodeConfig[ChatGPTOperation, ChatGPTAPIKeyCredential]):
    pass


ROUTES = {
    'create_response': ('POST', '/responses', True),
    'get_response': ('GET', '/responses/{response_id}', False),
    'delete_response': ('DELETE', '/responses/{response_id}', False),
    'cancel_response': ('POST', '/responses/{response_id}/cancel', False),
    'list_response_input_items': ('GET', '/responses/{response_id}/input_items', False),
    'create_chat_completion': ('POST', '/chat/completions', True),
    'get_chat_completion': ('GET', '/chat/completions/{completion_id}', False),
    'delete_chat_completion': ('DELETE', '/chat/completions/{completion_id}', False),
    'list_chat_messages': ('GET', '/chat/completions/{completion_id}/messages', False),
    'create_embedding': ('POST', '/embeddings', True),
    'create_moderation': ('POST', '/moderations', True),
    'list_models': ('GET', '/models', False),
    'get_model': ('GET', '/models/{model}', False),
    'list_files': ('GET', '/files', False),
    'get_file': ('GET', '/files/{file_id}', False),
    'delete_file': ('DELETE', '/files/{file_id}', False),
    'create_batch': ('POST', '/batches', True),
    'list_batches': ('GET', '/batches', False),
    'get_batch': ('GET', '/batches/{batch_id}', False),
    'cancel_batch': ('POST', '/batches/{batch_id}/cancel', False),
    'create_vector_store': ('POST', '/vector_stores', True),
    'list_vector_stores': ('GET', '/vector_stores', False),
    'get_vector_store': ('GET', '/vector_stores/{vector_store_id}', False),
    'delete_vector_store': ('DELETE', '/vector_stores/{vector_store_id}', False),
    'search_vector_store': ('POST', '/vector_stores/{vector_store_id}/search', True),
}


class ChatGPTNode(WorkflowNode):
    integration_type = "automation-chatgpt"
    connection_evidence = ConnectionEvidence(operation="list_models", noun="available OpenAI models", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return ChatGPTConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an OpenAI API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route, has_body = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        # Encode each path value as one segment; inputs cannot change the host or route.
        for field in re.findall(r"\{([^}]+)\}", route):
            value = values.pop(field)
            if value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError("Use a single OpenAI resource ID")
            route = route.replace("{" + field + "}", quote(value, safe=""))
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        if route.startswith("/vector_stores"):
            headers["OpenAI-Beta"] = "assistants=v2"
        kwargs = {}
        if has_body:
            if config.operation in {"create_response", "create_chat_completion"}:
                values["stream"] = False
            if config.operation == "create_embedding":
                values["encoding_format"] = "float"
            kwargs["json"] = values
        elif method == "GET":
            kwargs["params"] = values
        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=120.0) as client:
            response = await client.request(method, BASE + route, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            message = "OpenAI request failed"
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "http_status": response.status_code, "error": message.replace(key, "[redacted]")}
        result = response.json()
        if not isinstance(result, dict) or "error" in result and result["error"] is not None:
            raise ValueError("OpenAI returned an unexpected response or error envelope")
        if config.operation == "list_models" and (
            result.get("object") != "list" or not isinstance(result.get("data"), list)
            or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in result["data"])
        ):
            raise ValueError("OpenAI returned an unexpected model list")
        # Preserve provider IDs, output items, usage and pagination without assuming
        # the first output item is a text message. Never re-encode response bytes.
        await self.emit(result)
        return result
