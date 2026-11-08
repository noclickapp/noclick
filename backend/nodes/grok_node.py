"""Grok automation against xAI's published REST contract (OpenAPI 1.0.0).

API keys are sent only to api.x.ai. Each operation makes one request; callers
explicitly paginate lists and poll deferred image/video jobs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.x.ai"


class GrokAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Grok API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://console.x.ai/team/default/api-keys",
        "x-credential-instructions": "Create an API key in the xAI console and paste it here. Your xAI team pays for generation. NoClick verifies the user and team with GET /v1/me; individual model and write permissions may differ.",
    })
    credential_type: Literal["grok_api_key"] = Field("grok_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(char.isspace() for char in value):
            raise ValueError("Paste the API key without a Bearer header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not value or value in {".", ".."} or len(value) > 256 or any(
                not (c.isascii() and (c.isalnum() or c in "_.:-")) for c in value
            ):
                raise ValueError("Paste a single Grok resource ID, without a URL or path")
        return value


class GetMe(_Operation):
    """Read the authenticated user's ID, team and zero data retention status."""
    operation: Literal["get_me"] = "get_me"


class ListModels(_Operation):
    """List the models available to this key, including pricing metadata."""
    operation: Literal["list_models"] = "list_models"


class ListLanguageModels(_Operation):
    """List chat and image-understanding model modalities and aliases."""
    operation: Literal["list_language_models"] = "list_language_models"


class GetModel(_Operation):
    """Retrieve a model's information and pricing."""
    operation: Literal["get_model"] = "get_model"
    model_id: str = Field(..., min_length=1)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(..., min_length=1)


class CreateChatCompletion(_Operation):
    """Generate a non-streaming chat completion from text messages."""
    operation: Literal["create_chat_completion"] = "create_chat_completion"
    model: str = Field(..., min_length=1, description="Model ID returned by List Models.")
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=1000)
    max_completion_tokens: Optional[int] = Field(None, ge=1)
    temperature: Optional[float] = Field(None, ge=0, le=2)


class CreateResponse(_Operation):
    """Generate a stored text response, optionally continuing an existing response."""
    operation: Literal["create_response"] = "create_response"
    model: str = Field(..., min_length=1)
    input: str = Field(..., min_length=1, description="Text prompt.")
    instructions: Optional[str] = None
    previous_response_id: Optional[str] = None
    max_output_tokens: Optional[int] = Field(None, ge=1)
    store: bool = Field(True, description="Stored responses last 30 days. ZDR teams may need to disable storage.")

    @model_validator(mode="after")
    def instructions_or_previous(self):
        if self.instructions is not None and self.previous_response_id is not None:
            raise ValueError("Instructions cannot be combined with previous_response_id")
        return self


class GetResponse(_Operation):
    """Retrieve a response created with storage enabled."""
    operation: Literal["get_response"] = "get_response"
    response_id: str = Field(..., min_length=1)


class DeleteResponse(_Operation):
    """Permanently delete a stored response."""
    operation: Literal["delete_response"] = "delete_response"
    response_id: str = Field(..., min_length=1)


class ListResponseInputs(_Operation):
    """Read one page of a stored response's input items; use last_id as after."""
    operation: Literal["list_response_inputs"] = "list_response_inputs"
    response_id: str = Field(..., min_length=1)
    limit: int = Field(20, ge=1, le=100)
    order: Literal["asc", "desc"] = "asc"
    after: Optional[str] = None


class CreateEmbeddings(_Operation):
    """Embed one or more texts, returning numeric vectors."""
    operation: Literal["create_embeddings"] = "create_embeddings"
    model: str = Field(..., min_length=1)
    input: list[str] = Field(..., min_length=1, max_length=128)
    dimensions: Optional[int] = Field(None, ge=1)

    @field_validator("input")
    @classmethod
    def nonempty_texts(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("Each embedding input must contain text")
        return value


class GenerateImage(_Operation):
    """Generate images as URLs. Enable deferred to obtain a request ID to poll."""
    operation: Literal["generate_image"] = "generate_image"
    model: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    n: int = Field(1, ge=1, le=10)
    deferred: bool = False
    aspect_ratio: Optional[Literal["1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2", "9:19.5", "19.5:9", "9:20", "20:9", "1:2", "2:1", "21:9", "5:2", "auto"]] = None
    resolution: Optional[Literal["1k", "2k", "1.5k"]] = None


class GetImageResult(_Operation):
    """Poll one deferred image job; HTTP 202 means it is still pending."""
    operation: Literal["get_image_result"] = "get_image_result"
    request_id: str = Field(..., min_length=1)


class GenerateVideo(_Operation):
    """Start text-to-video generation; poll the returned request_id separately."""
    operation: Literal["generate_video"] = "generate_video"
    model: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    duration: int = Field(8, ge=1, le=15)
    aspect_ratio: Optional[Literal["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "5:2"]] = None
    resolution: Optional[Literal["480p", "720p", "1080p"]] = None


class GetVideoResult(_Operation):
    """Poll one video job; surface pending and failed jobs without retrying."""
    operation: Literal["get_video_result"] = "get_video_result"
    request_id: str = Field(..., min_length=1)


class TokenizeText(_Operation):
    """Count and inspect a model's tokens for text."""
    operation: Literal["tokenize_text"] = "tokenize_text"
    model: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class ListFiles(_Operation):
    """Read one team file page. A full page may have more; pass pagination_token."""
    operation: Literal["list_files"] = "list_files"
    limit: int = Field(20, ge=1, le=100)
    order: Literal["asc", "desc"] = "desc"
    sort_by: Literal["created_at", "filename", "size"] = "created_at"
    pagination_token: Optional[str] = None
    filter: Optional[str] = Field(None, description="Documented AIP-160 file filter expression.")


class GetFile(_Operation):
    """Retrieve metadata for one team file."""
    operation: Literal["get_file"] = "get_file"
    file_id: str = Field(..., min_length=1)


class DeleteFile(_Operation):
    """Permanently delete a team file and its attachment availability."""
    operation: Literal["delete_file"] = "delete_file"
    file_id: str = Field(..., min_length=1)


class CreateFilePublicURL(_Operation):
    """Publish an unauthenticated URL for a file; anyone with it can read it."""
    operation: Literal["create_file_public_url"] = "create_file_public_url"
    file_id: str = Field(..., min_length=1)
    expires_after: Optional[int] = Field(None, ge=3600, le=2592000, description="Lifetime in seconds. Omit to inherit file expiry or publish indefinitely.")


class RevokeFilePublicURL(_Operation):
    """Revoke the file's public URL while retaining its authenticated content."""
    operation: Literal["revoke_file_public_url"] = "revoke_file_public_url"
    file_id: str = Field(..., min_length=1)


Operation = Annotated[Union[
    GetMe, ListModels, ListLanguageModels, GetModel, CreateChatCompletion, CreateResponse, GetResponse,
    DeleteResponse, ListResponseInputs, CreateEmbeddings, GenerateImage,
    GetImageResult, GenerateVideo, GetVideoResult, TokenizeText, ListFiles,
    GetFile, DeleteFile, CreateFilePublicURL, RevokeFilePublicURL,
], Field(discriminator="operation")]


class GrokNodeConfig(NodeConfig[Operation, GrokAPIKeyCredential]):
    pass


# One operation -> exactly one provider operation (no arbitrary route or body).
ROUTES = {
    "get_me": ("GET", "/v1/me"),
    "list_models": ("GET", "/v1/models"),
    "list_language_models": ("GET", "/v1/language-models"),
    "get_model": ("GET", "/v1/models/{model_id}"),
    "create_chat_completion": ("POST", "/v1/chat/completions"),
    "create_response": ("POST", "/v1/responses"),
    "get_response": ("GET", "/v1/responses/{response_id}"),
    "delete_response": ("DELETE", "/v1/responses/{response_id}"),
    "list_response_inputs": ("GET", "/v1/responses/{response_id}/input_items"),
    "create_embeddings": ("POST", "/v1/embeddings"),
    "generate_image": ("POST", "/v1/images/generations"),
    "get_image_result": ("GET", "/v1/images/{request_id}"),
    "generate_video": ("POST", "/v1/videos/generations"),
    "get_video_result": ("GET", "/v1/videos/{request_id}"),
    "tokenize_text": ("POST", "/v1/tokenize-text"),
    "list_files": ("GET", "/v1/files"),
    "get_file": ("GET", "/v1/files/{file_id}"),
    "delete_file": ("DELETE", "/v1/files/{file_id}"),
    "create_file_public_url": ("POST", "/v1/files/{file_id}/public-url"),
    "revoke_file_public_url": ("POST", "/v1/files/{file_id}/public-url/revoke"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class GrokNode(WorkflowNode):
    integration_type = "automation-grok"
    connection_evidence = ConnectionEvidence(
        noun="xAI account", identity_operation="get_me", identity_keys=("team_id", "user_id"),
    )

    @classmethod
    def get_config_model(cls):
        return GrokNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Grok API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        fields = op.model_dump(exclude={"operation"}, exclude_none=True)
        for key in list(fields):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(fields.pop(key), safe=""))
        if op.operation == "create_chat_completion":
            fields["stream"] = False
        elif op.operation == "create_response":
            fields["stream"] = False
        elif op.operation == "create_embeddings":
            fields["encoding_format"] = "float"
        elif op.operation == "generate_image":
            fields["response_format"] = "url"
        kwargs = {"params": fields} if method == "GET" else {"json": fields} if method == "POST" and op.operation != "revoke_file_public_url" else {}
        try:
            async with guarded_async_client(timeout=180, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers={
                    "Authorization": "Bearer " + secret, "Accept": "application/json",
                }, **kwargs)
        except httpx.HTTPError:
            result = {"status": "error", "error": "Grok request did not complete", "write_outcome": "unknown" if method != "GET" else None}
        else:
            result = self._result(response, op)
        result = _redact(result, secret)
        await self.emit(result)
        return result

    @staticmethod
    def _result(response, op):
        code = response.status_code
        if code == 202 and op.operation in {"get_video_result", "get_image_result"}:
            return {"status": "pending", "http_status": code, "request_id": op.request_id}
        try:
            body = response.json()
        except ValueError:
            body = None
        if code < 200 or code >= 300:
            message = body.get("error", body.get("message")) if isinstance(body, dict) else None
            return {"status": "error", "http_status": code, "error": message or "Grok rejected the request", "write_outcome": "unknown" if code >= 500 and ROUTES[op.operation][0] != "GET" else None}
        if not isinstance(body, dict) or not body:
            raise ValueError("Grok returned an invalid JSON object")
        if body.get("error") or body.get("status") == "failed":
            return {"status": "error", "http_status": code, "error": body.get("error") or "Grok generation failed", "data": body}
        if op.operation == "get_me":
            if not all(isinstance(body.get(k), str) and body[k] for k in ("user_id", "team_id")) or type(body.get("team_blocked")) is not bool:
                raise ValueError("Grok identity response is missing its user or team")
        return {"status": "success", "http_status": code, "data": body}
