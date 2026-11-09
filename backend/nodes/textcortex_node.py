"""TextCortex v1 API-key operations (published contract 1.2026.11.06).

Each action makes one request. Pagination is explicit; paid operations and writes
are never retried automatically. Images return provider URLs.
https://api.textcortex.com/v1/openapi.json
"""
from __future__ import annotations
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.textcortex.com/v1"

class TextcortexAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="TextCortex API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.textcortex.com/user/settings/api",
            "x-credential-instructions": "Create an API key in your TextCortex account's API settings, then paste the key here. NoClick sends it as a Bearer token to api.textcortex.com. Connecting reads your owned file list; generation and search can consume credits."})
    credential_type: Literal["textcortex_api_key"] = Field("textcortex_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_path_id(cls, value, info):
        if info.field_name in {"file_id", "kb_id", "model_id"}:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value):
                raise ValueError("Use a single TextCortex resource ID")
        return value

def action(name, label, category):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-category": category})

class _Page(_Input):
    page: int = Field(0, ge=0, description="Zero-based page. Use next_page from the previous result; one page per execution.")
    limit: int = Field(20, ge=1, le=100)

class ListFiles(_Page):
    operation: Literal["list_files"] = action("list_files", "List Owned Files", "Files")
    q: Optional[str] = Field(None, min_length=1, max_length=256)

class GetFile(_Input):
    operation: Literal["get_file"] = action("get_file", "Get File Metadata", "Files")
    file_id: str = Field(..., min_length=1, max_length=256)

class DeleteFile(GetFile):
    operation: Literal["delete_file"] = action("delete_file", "Delete Owned File", "Files")

class ListKnowledgeBases(_Page):
    operation: Literal["list_knowledge_bases"] = action("list_knowledge_bases", "List Knowledge Bases", "Knowledge")

class SearchKnowledgeBaseFiles(_Page):
    operation: Literal["search_knowledge_base_files"] = action("search_knowledge_base_files", "Search Knowledge Base Files", "Knowledge")
    q: str = Field(..., min_length=1, max_length=512)
    limit: int = Field(20, ge=1, le=25)

class ListKnowledgeBaseFiles(_Page):
    operation: Literal["list_knowledge_base_files"] = action("list_knowledge_base_files", "List Knowledge Base Insertions", "Knowledge")
    kb_id: str = Field(..., min_length=1, max_length=256)

class InsertKnowledgeBaseFile(_Input):
    operation: Literal["insert_knowledge_base_file"] = action("insert_knowledge_base_file", "Add File to Knowledge Base", "Knowledge")
    kb_id: str = Field(..., min_length=1, max_length=256)
    file_id: str = Field(..., min_length=1, max_length=64, description="An existing uploaded file ID, not a URL. Acknowledgement does not mean indexing has finished.")

class QueryKnowledgeBase(_Input):
    operation: Literal["query_knowledge_base"] = action("query_knowledge_base", "Query Knowledge Base", "Knowledge")
    kb_id: str = Field(..., min_length=1, max_length=256)
    query: str = Field(..., min_length=1, max_length=8000)
    top_k: int = Field(10, ge=1, le=20)
    verbatim: bool = Field(False, description="Use plain-text lexical query parsing.")

class GetBalance(_Input):
    operation: Literal["get_balance"] = action("get_balance", "Get Credit Balance", "Account")

class GetCapabilities(_Input):
    operation: Literal["get_capabilities"] = action("get_capabilities", "Get API Capabilities", "Account")

class ListModels(_Input):
    operation: Literal["list_models"] = action("list_models", "List Chat Models", "Models")

class GetModel(_Input):
    operation: Literal["get_model"] = action("get_model", "Get Model", "Models")
    model_id: str = Field(..., min_length=1, max_length=256)

class CreateChatCompletion(_Input):
    operation: Literal["create_chat_completion"] = action("create_chat_completion", "Create Chat Completion", "Generation")
    model: str = Field(..., min_length=1, description="An available ID from List Chat Models.")
    prompt: str = Field(..., min_length=1, description="User message. Generation may consume credits.")
    system_prompt: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    reasoning_effort: Optional[Literal["none", "low", "medium", "high"]] = None

class CreateResponse(_Input):
    operation: Literal["create_response"] = action("create_response", "Create Text Response", "Generation")
    model: str = Field(..., min_length=1, description="An available ID from List Chat Models. Uses the model's default reasoning.")
    input: str = Field(..., min_length=1, description="Text input. Generation may consume credits.")
    instructions: Optional[str] = None
    max_output_tokens: Optional[int] = Field(None, ge=1)
    temperature: Optional[float] = Field(None, ge=0, le=2)

class GenerateImage(_Input):
    operation: Literal["generate_image"] = action("generate_image", "Generate Image", "Generation")
    prompt: str = Field(..., min_length=1, max_length=8000, description="Image description. Generation may consume credits. Returns a provider image URL.")
    model: Optional[str] = Field(None, min_length=1, max_length=128, description="Image model from the provider's image guide, or omit for its deployment default. List Chat Models does not list image models.")
    size: Optional[str] = Field(None, min_length=1, max_length=32, description="A model-supported pixel size, e.g. 1024x1024.")

class SearchWeb(_Input):
    operation: Literal["search_web"] = action("search_web", "Search the Web", "Search")
    query: str = Field(..., min_length=1, max_length=1000, description="Search text. Search may consume credits.")
    website: Optional[str] = Field(None, min_length=1, max_length=512)
    limit: int = Field(5, ge=1, le=10)

TextcortexOperation = Annotated[Union[
    ListFiles, GetFile, DeleteFile, ListKnowledgeBases, SearchKnowledgeBaseFiles,
    ListKnowledgeBaseFiles, InsertKnowledgeBaseFile, QueryKnowledgeBase, GetBalance,
    GetCapabilities, ListModels, GetModel, CreateChatCompletion, CreateResponse,
    GenerateImage, SearchWeb,
], Field(discriminator="operation")]

class TextcortexNodeConfig(NodeConfig[TextcortexOperation, TextcortexAPIKeyCredential]):
    model_config = ConfigDict(title="TextCortex Node Configuration")

# Exactly one provider operation per action. Config cannot supply a host,
# route, HTTP method or arbitrary request headers.
ROUTES = {
    "list_files": ("GET", "/api-platform/files"),
    "get_file": ("GET", "/api-platform/files/{file_id}"),
    "delete_file": ("DELETE", "/api-platform/files/{file_id}"),
    "list_knowledge_bases": ("GET", "/api-platform/knowledge-bases"),
    "search_knowledge_base_files": ("GET", "/api-platform/knowledge-bases/files/search"),
    "list_knowledge_base_files": ("GET", "/api-platform/knowledge-bases/{kb_id}/files"),
    "insert_knowledge_base_file": ("POST", "/api-platform/knowledge-bases/{kb_id}/files"),
    "query_knowledge_base": ("POST", "/api-platform/knowledge-bases/{kb_id}/query"),
    "get_balance": ("GET", "/balance"),
    "get_capabilities": ("GET", "/capabilities"),
    "list_models": ("GET", "/models"),
    "get_model": ("GET", "/models/{model_id}"),
    "create_chat_completion": ("POST", "/chat/completions"),
    "create_response": ("POST", "/responses"),
    "generate_image": ("POST", "/images/generations"),
    "search_web": ("POST", "/web/search"),
}

def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value

def _error_message(payload, status):
    if isinstance(payload, dict):
        error = payload.get("error")
        for value in (error.get("message") if isinstance(error, dict) else error,
                      payload.get("detail"), payload.get("message")):
            if isinstance(value, str) and value:
                return value[:1000]
    return f"TextCortex request failed (HTTP {status})"

class TextcortexNode(WorkflowNode):
    integration_type = "automation-textcortex"
    connection_evidence = ConnectionEvidence(noun="owned files", operation="list_files", label_keys=("name", "original_filename", "id"))

    @classmethod
    def get_config_model(cls):
        return TextcortexNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a TextCortex API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        for name in ("file_id", "kb_id", "model_id"):
            marker = "{" + name + "}"
            if marker in route:
                route = route.replace(marker, quote(values.pop(name), safe=""))
        if isinstance(op, CreateChatCompletion):
            values.pop("prompt")
            values.pop("system_prompt", None)
            values["messages"] = ([{"role": "system", "content": op.system_prompt}] if op.system_prompt else []) + [{"role": "user", "content": op.prompt}]
            values["stream"] = False
        elif isinstance(op, CreateResponse):
            values.update(stream=False, store=False)
        elif isinstance(op, GenerateImage):
            values.update(n=1, response_format="url")
        try:
            async with guarded_async_client(timeout=120.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"json": values} if method == "POST" else {}))
        except httpx.RequestError:
            raise ValueError("TextCortex request did not complete; inspect state before repeating paid requests or writes") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"TextCortex returned a non-JSON response (HTTP {response.status_code})") from None
        if not 200 <= response.status_code < 300:
            result = {"status": "error", "success": False, "status_code": response.status_code,
                      "error": _error_message(payload, response.status_code)}
        else:
            if not isinstance(payload, dict) or payload.get("error") or payload.get("status") in {"error", "fail"}:
                raise ValueError("TextCortex returned an unexpected response")
            result = {"status": "success", "success": True, "data": payload}
            if isinstance(op, _Page):
                pagination = payload.get("pagination")
                if not isinstance(pagination, dict) or type(pagination.get("has_more")) is not bool:
                    raise ValueError("TextCortex pagination is missing or invalid")
                result["next_page"] = op.page + 1 if pagination["has_more"] else None
                result["has_more"] = pagination["has_more"]
        result = _redact(result, key)
        await self.emit(result)
        return result
