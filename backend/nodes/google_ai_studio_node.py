"""Google AI Studio's Gemini v1beta API, using a person-supplied API key.

Each operation performs one provider request. Lists expose Google's page token;
imports return the long-running operation without claiming indexing is finished.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GoogleAIStudioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Google AI Studio API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://aistudio.google.com/apikey",
            "x-credential-instructions": "Create a Gemini API key in Google AI Studio, then paste it here. Use an authorization key or a standard key restricted to the Generative Language API. NoClick sends it only to generativelanguage.googleapis.com. Listing your project's files checks read access; model availability, billing and write permissions may differ.",
        })
    credential_type: Literal["google_ai_studio_api_key"] = Field("google_ai_studio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste an API key without a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("file_id", "cache_id", "store_id", "document_id", "operation_id", check_fields=False)
    @classmethod
    def resource_id(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value):
            raise ValueError("Use the resource ID, without its collection prefix or URL")
        return value


class Page(Input):
    page_size: int = Field(20, ge=1, le=100)
    page_token: str | None = Field(None, max_length=8192, description="nextPageToken from the previous response; keep the same operation and parent.")


class ModelInput(Input):
    @field_validator("model", check_fields=False)
    @classmethod
    def model_id(cls, value):
        return cls.resource_id(value)

    model: str = Field(..., description="Model ID, without models/. Discover available IDs with List models.")


class FileData(Input):
    fileUri: str = Field(..., min_length=1)
    mimeType: str | None = None


class SafetySetting(Input):
    category: str
    threshold: str


class Part(Input):
    text: str | None = None
    fileData: FileData | None = Field(None, description="Gemini fileUri and mimeType for previously uploaded media.")


class Content(Input):
    role: Literal["user", "model"] = "user"
    parts: list[Part] = Field(..., min_length=1)


class GenerateContent(ModelInput):
    operation: Literal["generate_content"] = "generate_content"
    contents: list[Content] = Field(..., min_length=1)
    system_instruction: Content | None = None
    generation_config: dict[str, Any] | None = Field(None, description="Gemini GenerationConfig, e.g. temperature, maxOutputTokens, responseMimeType, responseJsonSchema.")
    safety_settings: list[SafetySetting] | None = None
    tools: list[dict[str, Any]] | None = Field(None, description="Gemini Tool objects, e.g. googleSearch or fileSearch.")
    cached_content: str | None = Field(None, pattern=r"^cachedContents/[A-Za-z0-9_.-]+$")


class CountTokens(ModelInput):
    operation: Literal["count_tokens"] = "count_tokens"
    contents: list[Content] = Field(..., min_length=1)


class EmbedContent(ModelInput):
    operation: Literal["embed_content"] = "embed_content"
    content: Content
    task_type: Literal["RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT", "SEMANTIC_SIMILARITY", "CLASSIFICATION", "CLUSTERING", "QUESTION_ANSWERING", "FACT_VERIFICATION", "CODE_RETRIEVAL_QUERY"] | None = None
    title: str | None = None
    output_dimensionality: int | None = Field(None, ge=1)


class EmbeddingRequest(Input):
    model: str = Field(..., pattern=r"^models/[A-Za-z0-9_.-]+$")
    content: Content
    taskType: str | None = None
    outputDimensionality: int | None = Field(None, ge=1)


class BatchEmbedContents(ModelInput):
    operation: Literal["batch_embed_contents"] = "batch_embed_contents"
    requests: list[EmbeddingRequest] = Field(..., min_length=1, max_length=100)


class CreateCache(ModelInput):
    operation: Literal["create_cache"] = "create_cache"
    contents: list[Content] = Field(..., min_length=1)
    display_name: str | None = Field(None, max_length=128)
    ttl: str = Field("3600s", pattern=r"^[1-9][0-9]*(?:\.[0-9]{1,9})?s$")
    system_instruction: Content | None = None


class ListModels(Page):
    operation: Literal["list_models"] = "list_models"


class GetModel(ModelInput):
    operation: Literal["get_model"] = "get_model"


class ListFiles(Page):
    operation: Literal["list_files"] = "list_files"


class GetFile(Input):
    operation: Literal["get_file"] = "get_file"
    file_id: str = Field(..., description="ID without the collection prefix.")


class DeleteFile(Input):
    operation: Literal["delete_file"] = "delete_file"
    file_id: str = Field(..., description="ID without the collection prefix.")


class ListCaches(Page):
    operation: Literal["list_caches"] = "list_caches"


class GetCache(Input):
    operation: Literal["get_cache"] = "get_cache"
    cache_id: str = Field(..., description="ID without the collection prefix.")


class DeleteCache(Input):
    operation: Literal["delete_cache"] = "delete_cache"
    cache_id: str = Field(..., description="ID without the collection prefix.")


class CreateStore(Input):
    operation: Literal["create_store"] = "create_store"
    display_name: str = Field(..., min_length=1, max_length=512)


class ListStores(Page):
    operation: Literal["list_stores"] = "list_stores"


class GetStore(Input):
    operation: Literal["get_store"] = "get_store"
    store_id: str = Field(..., description="ID without the collection prefix.")


class DeleteStore(Input):
    operation: Literal["delete_store"] = "delete_store"
    store_id: str = Field(..., description="ID without the collection prefix.")
    force: bool = Field(False, description="Also delete contained chunks/documents, as documented by Google.")


class ListDocuments(Page):
    operation: Literal["list_documents"] = "list_documents"
    store_id: str = Field(..., description="ID without the collection prefix.")


class GetDocument(Input):
    operation: Literal["get_document"] = "get_document"
    store_id: str = Field(..., description="ID without the collection prefix.")
    document_id: str = Field(..., description="ID without the collection prefix.")


class DeleteDocument(Input):
    operation: Literal["delete_document"] = "delete_document"
    store_id: str = Field(..., description="ID without the collection prefix.")
    document_id: str = Field(..., description="ID without the collection prefix.")
    force: bool = Field(False, description="Also delete contained chunks/documents, as documented by Google.")


class ImportFile(Input):
    operation: Literal["import_file"] = "import_file"
    store_id: str = Field(..., description="ID without the collection prefix.")
    file_name: str = Field(..., pattern=r"^files/[A-Za-z0-9_.-]+$", description="Existing uploaded File resource name.")
    custom_metadata: list[dict[str, Any]] | None = None
    chunking_config: dict[str, Any] | None = None


class GetImportOperation(Input):
    operation: Literal["get_import_operation"] = "get_import_operation"
    store_id: str = Field(..., description="ID without the collection prefix.")
    operation_id: str = Field(..., description="ID without the collection prefix.")


GoogleAIStudioOperation = Annotated[Union[GenerateContent, CountTokens, EmbedContent, BatchEmbedContents, CreateCache, ListModels, GetModel, ListFiles, GetFile, DeleteFile, ListCaches, GetCache, DeleteCache, CreateStore, ListStores, GetStore, DeleteStore, ListDocuments, GetDocument, DeleteDocument, ImportFile, GetImportOperation], Field(discriminator="operation")]


class GoogleAIStudioConfig(NodeConfig[GoogleAIStudioOperation, GoogleAIStudioAPIKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    return value


class GoogleAIStudioNode(WorkflowNode):
    integration_type = "automation-google-ai-studio"
    connection_evidence = ConnectionEvidence(noun="files", operation="list_files", label_keys=("displayName", "name"))

    @classmethod
    def get_config_model(cls):
        return GoogleAIStudioConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Google AI Studio API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, params, body = self._request(op)
        try:
            async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"x-goog-api-key": key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except Exception:
            raise ValueError("Google AI Studio request could not be completed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("error", {}).get("message", "Request rejected")
            except Exception:
                message = "Request rejected"
            raise ValueError(_redact(f"Google AI Studio HTTP {response.status_code}: {message}", key))
        try:
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                raise ValueError()
            if "error" in data and op.operation not in {"get_import_operation", "import_file"}:
                raise ValueError()
        except Exception:
            raise ValueError("Google AI Studio returned an unexpected JSON response; inspect writes before retrying") from None
        result = _redact({"status": "error" if "error" in data else "success", "operation": op.operation, "data": data}, key)
        # A list remains a single page; the original nextPageToken is preserved.
        await self.emit(result)
        return result

    @staticmethod
    def _request(op):
        action = op.operation
        params, body = {}, None
        if isinstance(op, Page):
            params = {"pageSize": op.page_size}
            if op.page_token is not None:
                params["pageToken"] = op.page_token
        if action in {"generate_content", "count_tokens", "embed_content", "batch_embed_contents"}:
            method = "POST"
            suffix = {"generate_content": "generateContent", "count_tokens": "countTokens", "embed_content": "embedContent", "batch_embed_contents": "batchEmbedContents"}[action]
            path = "/models/" + quote(op.model, safe="") + ":" + suffix
            body = op.model_dump(exclude={"operation", "model"}, exclude_none=True)
            aliases = {"system_instruction": "systemInstruction", "generation_config": "generationConfig", "safety_settings": "safetySettings", "cached_content": "cachedContent", "task_type": "taskType", "output_dimensionality": "outputDimensionality"}
            body = {aliases.get(k, k): v for k, v in body.items()}
            if action in {"generate_content", "embed_content"}:
                body["model"] = "models/" + op.model
            if action == "batch_embed_contents" and any(r.model != "models/" + op.model for r in op.requests):
                raise ValueError("Each embedding request must use the selected model")
        elif action == "create_cache":
            method, path = "POST", "/cachedContents"
            body = {"model": "models/" + op.model, "contents": [c.model_dump(exclude_none=True) for c in op.contents], "ttl": op.ttl}
            if op.display_name is not None:
                body["displayName"] = op.display_name
            if op.system_instruction is not None:
                body["systemInstruction"] = op.system_instruction.model_dump(exclude_none=True)
        elif action == "create_store":
            method, path, body = "POST", "/fileSearchStores", {"displayName": op.display_name}
        elif action in {"list_models", "list_files", "list_caches", "list_stores"}:
            method, path = "GET", "/" + {"list_models": "models", "list_files": "files", "list_caches": "cachedContents", "list_stores": "fileSearchStores"}[action]
        else:
            method = "DELETE" if action.startswith("delete_") else "GET"
            if action == "get_model":
                path = "/models/" + quote(op.model, safe="")
            elif action.endswith("_file") and action != "import_file":
                path = "/files/" + quote(op.file_id, safe="")
            elif action.endswith("_cache"):
                path = "/cachedContents/" + quote(op.cache_id, safe="")
            else:
                path = "/fileSearchStores/" + quote(op.store_id, safe="")
                if action in {"list_documents", "get_document", "delete_document"}:
                    path += "/documents"
                    if action != "list_documents":
                        path += "/" + quote(op.document_id, safe="")
                elif action == "get_import_operation":
                    path += "/operations/" + quote(op.operation_id, safe="")
                elif action == "import_file":
                    method, path = "POST", path + ":importFile"
                    body = {"fileName": op.file_name}
                    if op.custom_metadata is not None:
                        body["customMetadata"] = op.custom_metadata
                    if op.chunking_config is not None:
                        body["chunkingConfig"] = op.chunking_config
            if action in {"delete_store", "delete_document"}:
                params["force"] = "true" if op.force else "false"
        return method, path, params, body
