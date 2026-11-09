"""Langbase v1 pipes, memory, text primitives and conversation threads.

Contract: https://api.langbase.com/openapi.json (1.0.0).
Account API keys: https://langbase.com/docs/api-reference#authentication.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.langbase.com"


class LangbaseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Langbase API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://langbase.com/docs/api-reference/api-keys",
        "x-credential-instructions": "Paste a Langbase user or organization API key with access to the pipes, memories and threads you need. Use an account key rather than a pipe-only key so NoClick can list your pipes to check the connection. LLM operations use the provider keys configured in Langbase.",
    })
    credential_type: Literal["langbase_api_key"] = Field("langbase_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


def operation(name, title):
    return Field(name, title=title, json_schema_extra={"ui:hidden": True, "x-display-name": title})


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("pipe_name", "owner_login", "memory_name", "document_name", check_fields=False)
    @classmethod
    def segment(cls, value):
        if not value or value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Supply a resource name")
        return value

    @field_validator("thread_id", "message_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        return str(UUID(value)) if value is not None else None


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "function", "tool"]
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None
    metadata: dict[str, Annotated[str, Field(max_length=2048)]] | None = None


class PipeMessage(BaseModel):
    role: Literal["system", "user", "assistant", "function"]
    content: str
    name: str | None = None


class ListPipes(Input):
    operation: Literal["list_pipes"] = operation("list_pipes", "List Pipes")


class PipeSettings(Input):
    description: str | None = None
    model: str | None = None
    status: Literal["private", "public"] | None = None
    messages: list[PipeMessage] | None = None
    variables: dict[str, Annotated[str, Field(min_length=1)]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    store: bool | None = None
    moderate: bool | None = None


class CreatePipe(PipeSettings):
    operation: Literal["create_pipe"] = operation("create_pipe", "Create Pipe")
    name: str = Field(..., min_length=1)
    upsert: bool = Field(False, description="Update an existing pipe with this name if it exists.")
    type: Literal["chat", "generate"] = "generate"
    status: Literal["private", "public"] = "private"


class UpdatePipe(PipeSettings):
    operation: Literal["update_pipe"] = operation("update_pipe", "Update Pipe")
    pipe_name: str = Field(..., min_length=1)


class GetPipe(Input):
    operation: Literal["get_pipe"] = operation("get_pipe", "Get Pipe")
    owner_login: str = Field(..., min_length=1)
    pipe_name: str = Field(..., min_length=1)


class RunPipe(Input):
    operation: Literal["run_pipe"] = operation("run_pipe", "Run Pipe")
    name: str = Field(..., min_length=1, description="Pipe name in the connected account.")
    messages: list[Message] = Field(..., min_length=1)
    variables: dict[str, str] | None = None
    thread_id: str | None = Field(None, description="Continue an existing conversation.", json_schema_extra={"format": "uuid"})

    @field_validator("thread_id")
    @classmethod
    def optional_id(cls, value):
        return str(UUID(value)) if value is not None else None


class ListMemories(Input):
    operation: Literal["list_memories"] = operation("list_memories", "List Memories")


class CreateMemory(Input):
    operation: Literal["create_memory"] = operation("create_memory", "Create Memory")
    name: str = Field(..., min_length=1)
    description: str | None = None
    embedding_model: Literal["openai:text-embedding-3-large", "cohere:embed-v4.0", "cohere:embed-multilingual-v3.0", "cohere:embed-multilingual-light-v3.0", "google:text-embedding-004"] = "openai:text-embedding-3-large"
    chunk_size: int = Field(10000, ge=1024, le=30000)
    chunk_overlap: int = Field(2048, ge=256)
    top_k: int = Field(3, ge=1, le=100)

    @model_validator(mode="after")
    def overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("Chunk overlap must be smaller than chunk size")
        return self


class MemoryReference(BaseModel):
    name: str = Field(..., min_length=1)
    filters: dict | None = None


class RetrieveMemory(Input):
    operation: Literal["retrieve_memory"] = operation("retrieve_memory", "Search Memory")
    memory: list[MemoryReference] = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(20, ge=1, le=100)


class MemoryInput(Input):
    memory_name: str = Field(..., min_length=1)


class DeleteMemory(MemoryInput):
    operation: Literal["delete_memory"] = operation("delete_memory", "Delete Memory")


class ListDocuments(MemoryInput):
    operation: Literal["list_documents"] = operation("list_documents", "List Memory Documents")


class DocumentInput(MemoryInput):
    document_name: str = Field(..., min_length=1)


class DeleteDocument(DocumentInput):
    operation: Literal["delete_document"] = operation("delete_document", "Delete Memory Document")


class RetryEmbeddings(DocumentInput):
    operation: Literal["retry_embeddings"] = operation("retry_embeddings", "Retry Document Embeddings")


class ChunkText(Input):
    operation: Literal["chunk_text"] = operation("chunk_text", "Chunk Text")
    content: str = Field(..., min_length=1)
    chunk_max_length: int = Field(1024, ge=1024, le=30000)
    chunk_overlap: int = Field(256, ge=256)

    @model_validator(mode="after")
    def overlap(self):
        if self.chunk_overlap >= self.chunk_max_length:
            raise ValueError("Chunk overlap must be smaller than maximum length")
        return self


class EmbedText(Input):
    operation: Literal["embed_text"] = operation("embed_text", "Embed Text")
    chunks: list[Annotated[str, Field(max_length=8192)]] = Field(..., min_length=1, max_length=100)
    embedding_model: str = "openai:text-embedding-3-large"


class CreateThread(Input):
    operation: Literal["create_thread"] = operation("create_thread", "Create Thread")
    metadata: dict[str, Annotated[str, Field(max_length=2048)]] = Field(default_factory=dict)


class ThreadInput(Input):
    thread_id: str = Field(..., description="Thread UUID", json_schema_extra={"format": "uuid"})


class GetThread(ThreadInput):
    operation: Literal["get_thread"] = operation("get_thread", "Get Thread")


class UpdateThread(ThreadInput):
    operation: Literal["update_thread"] = operation("update_thread", "Update Thread")
    metadata: dict[str, Annotated[str, Field(max_length=2048)]] = Field(default_factory=dict)


class DeleteThread(ThreadInput):
    operation: Literal["delete_thread"] = operation("delete_thread", "Delete Thread")


class CreateMessages(ThreadInput):
    operation: Literal["create_messages"] = operation("create_messages", "Add Thread Messages")
    messages: list[Message] = Field(..., min_length=1)


class ListMessages(ThreadInput):
    operation: Literal["list_messages"] = operation("list_messages", "List Thread Messages")


class MessageInput(ThreadInput):
    message_id: str = Field(..., description="Message UUID", json_schema_extra={"format": "uuid"})


class UpdateMessage(MessageInput):
    operation: Literal["update_message"] = operation("update_message", "Update Thread Message")
    content: str | None = None
    metadata: dict[str, Annotated[str, Field(max_length=2048)]] | None = None


class DeleteMessage(MessageInput):
    operation: Literal["delete_message"] = operation("delete_message", "Delete Thread Message")


LangbaseOperations = Annotated[Union[
    ListPipes, CreatePipe, UpdatePipe, GetPipe, RunPipe,
    ListMemories, CreateMemory, RetrieveMemory, DeleteMemory, ListDocuments, DeleteDocument, RetryEmbeddings,
    ChunkText, EmbedText, CreateThread, GetThread, UpdateThread, DeleteThread,
    CreateMessages, ListMessages, UpdateMessage, DeleteMessage,
], Field(discriminator="operation")]


class LangbaseConfig(NodeConfig[LangbaseOperations, LangbaseAPIKeyCredential]):
    pass


# Each operation issues exactly one request to its pinned v1 operation.
ROUTES = {
    "list_pipes": ("GET", "/v1/pipes"),
    "create_pipe": ("POST", "/v1/pipes"),
    "update_pipe": ("POST", "/v1/pipes/{pipe_name}"),
    "get_pipe": ("GET", "/v1/pipes/{owner_login}/{pipe_name}"),
    "run_pipe": ("POST", "/v1/pipes/run"),
    "list_memories": ("GET", "/v1/memory"),
    "create_memory": ("POST", "/v1/memory"),
    "retrieve_memory": ("POST", "/v1/memory/retrieve"),
    "delete_memory": ("DELETE", "/v1/memory/{memory_name}"),
    "list_documents": ("GET", "/v1/memory/{memory_name}/documents"),
    "delete_document": ("DELETE", "/v1/memory/{memory_name}/documents/{document_name}"),
    "retry_embeddings": ("GET", "/v1/memory/{memory_name}/documents/{document_name}/embeddings/retry"),
    "chunk_text": ("POST", "/v1/chunker"),
    "embed_text": ("POST", "/v1/embed"),
    "create_thread": ("POST", "/v1/threads"),
    "get_thread": ("GET", "/v1/threads/{thread_id}"),
    "update_thread": ("POST", "/v1/threads/{thread_id}"),
    "delete_thread": ("DELETE", "/v1/threads/{thread_id}"),
    "create_messages": ("POST", "/v1/threads/{thread_id}/messages"),
    "list_messages": ("GET", "/v1/threads/{thread_id}/messages"),
    "update_message": ("POST", "/v1/threads/{thread_id}/messages/{message_id}"),
    "delete_message": ("DELETE", "/v1/threads/{thread_id}/messages/{message_id}"),
}
WIRE_NAMES = {"top_k": "topK", "chunk_max_length": "chunkMaxLength", "chunk_overlap": "chunkOverlap", "embedding_model": "embeddingModel", "thread_id": "threadId"}


class LangbaseNode(WorkflowNode):
    integration_type = "automation-langbase"
    connection_evidence = ConnectionEvidence(operation="list_pipes", noun="pipes")

    @classmethod
    def get_config_model(cls):
        return LangbaseConfig

    async def execute(self, inputs):
        cfg = self.config.config
        creds = self.config.credentials
        if not isinstance(creds, LangbaseAPIKeyCredential):
            raise ValueError("Connect a Langbase API key")
        method, path = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude={"operation"}, exclude_none=True)
        for key in tuple(values):
            placeholder = "{" + key + "}"
            if placeholder in path:
                path = path.replace(placeholder, quote(str(values.pop(key)), safe=""))
        body = None
        if method == "POST":
            body = values
            if cfg.operation in {"chunk_text", "embed_text", "retrieve_memory", "run_pipe"}:
                body = {WIRE_NAMES.get(k, k): v for k, v in body.items()}
            if cfg.operation == "run_pipe":
                body["stream"] = False
            if cfg.operation == "create_messages":
                body = body["messages"]
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + creds.api_key, "Accept": "application/json", "Content-Type": "application/json"},
                **({"json": body} if body is not None else {}))
        if not response.is_success:
            # Preserve provider rejection words for the shared connection verdict,
            # but never let a provider echo the pasted key back into an error.
            detail = response.text[:2000].replace(creds.api_key, "[redacted]")
            raise ValueError(f"Langbase HTTP {response.status_code}: {detail}")
        value = response.json()
        if isinstance(value, dict) and (value.get("success") is False or value.get("error") or value.get("errors")):
            detail = str(value.get("error") or value.get("errors") or "Request unsuccessful")
            raise ValueError("Langbase: " + detail[:2000].replace(creds.api_key, "[redacted]"))
        if not isinstance(value, (dict, list)):
            raise ValueError("Langbase returned an unexpected JSON response")
        if cfg.operation == "list_pipes" and (not isinstance(value, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in value)):
            raise ValueError("Langbase returned an unexpected pipe list")
        # Pipe create/get responses include a pipe API key. Do not emit those keys.
        def public(item):
            if isinstance(item, dict):
                return {k: public(v) for k, v in item.items() if k not in {"api_key", "apiKey"}}
            if isinstance(item, list):
                return [public(v) for v in item]
            return item
        return {"data": public(value), "thread_id": response.headers.get("lb-thread-id")}
