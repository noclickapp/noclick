"""AI/ML API operations from the provider's published 1.0.0 OpenAPI contract.

Connection identity: https://docs.aimlapi.com/api-references/service-endpoints/account-balance
Authentication: https://docs.aimlapi.com/quickstart/simple-model
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.aimlapi.com"


class AiMlApiCredential(BaseModel):
    model_config = ConfigDict(title="AI/ML API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://aimlapi.com/app/keys",
            "x-credential-instructions": "Create or copy a regular API key from your AI/ML API dashboard. Paste the key without the Bearer prefix. NoClick reads your billing account to verify the connection. Generations use your provider balance."})
    credential_type: Literal["ai_ml_api_key"] = Field("ai_ml_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste only the API key, without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(_Input):
    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(..., min_length=1)


class CreateResponse(_Input):
    """Generate a text response using the Responses API."""
    operation: Literal["create_response"] = "create_response"
    model: Literal["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"] = "gpt-4o-mini"
    input: str = Field(..., min_length=1, title="Input text")
    instructions: str | None = None
    max_output_tokens: int | None = Field(None, ge=16)


class CreateChatCompletion(_Input):
    """Generate a chat completion from conversation messages."""
    operation: Literal["create_chat_completion"] = "create_chat_completion"
    model: Literal["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"] = "gpt-4o-mini"
    messages: list[Message] = Field(..., min_length=1)
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1)


class CreateEmbeddings(_Input):
    """Embed text for semantic search and retrieval."""
    operation: Literal["create_embeddings"] = "create_embeddings"
    model: Literal["text-embedding-3-small", "text-embedding-3-large"] = "text-embedding-3-small"
    input: str | list[str] = Field(..., min_length=1, title="Text to embed")
    dimensions: int | None = Field(None, ge=1)


class GenerateImage(_Input):
    """Generate an image; provider base64 media is returned as a file."""
    operation: Literal["generate_image"] = "generate_image"
    model: Literal["gpt-image-1-mini", "gpt-image-1.5"] = "gpt-image-1-mini"
    prompt: str = Field(..., min_length=1, max_length=32000)
    size: Literal["auto", "1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    quality: Literal["low", "medium", "high"] = "medium"
    output_format: Literal["png", "jpeg", "webp"] = "png"
    response_format: Literal["url", "b64_json"] = "url"


class CreateTranscription(_Input):
    """Start transcription of an audio URL; use the returned generation ID to poll."""
    operation: Literal["create_transcription"] = "create_transcription"
    model: Literal["gpt-4o-transcribe", "gpt-4o-mini-transcribe"] = "gpt-4o-mini-transcribe"
    url: str = Field(..., title="Audio URL", min_length=1)
    language: str | None = None
    prompt: str | None = None


class GetTranscription(_Input):
    """Read a transcription job using the returned generation ID."""
    operation: Literal["get_transcription"] = "get_transcription"
    generation_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", title="Generation ID")


class CreateMessage(_Input):
    """Generate an Anthropic-compatible message."""
    operation: Literal["create_message"] = "create_message"
    model: Literal["claude-opus-4-1-20250805", "anthropic/claude-opus-4-1-20250805"] = "claude-opus-4-1-20250805"
    messages: list[Message] = Field(..., min_length=1, description="Use user and assistant roles; put system instructions in the System field.")
    system: str | None = None
    max_tokens: int = Field(1024, ge=1)

    @field_validator("messages")
    @classmethod
    def no_system_message(cls, messages):
        if any(m.role == "system" for m in messages):
            raise ValueError("Use the System field for system instructions")
        return messages


class GenerateVideo(_Input):
    """Start a Seedance video generation; poll with Get video."""
    operation: Literal["generate_video"] = "generate_video"
    model: Literal["bytedance/seedance-1-0-pro", "bytedance/seedance-1-0-pro-fast"] = "bytedance/seedance-1-0-pro"
    prompt: str = Field(..., min_length=1)
    image_url: str | None = None
    resolution: Literal["480p", "720p", "1080p"] = "1080p"
    duration: Literal[5, 10] = 5


class GetVideo(_Input):
    """Read one video generation's status and output URL."""
    operation: Literal["get_video"] = "get_video"
    generation_id: str = Field(..., title="Generation ID", min_length=1)


class GenerateAudio(_Input):
    """Start an Eleven Music generation; poll with Get audio."""
    operation: Literal["generate_audio"] = "generate_audio"
    model: Literal["elevenlabs/eleven_music"] = "elevenlabs/eleven_music"
    prompt: str = Field(..., min_length=1, max_length=2000)
    music_length_ms: int = Field(10000, ge=10000, le=300000)


class GetAudio(_Input):
    """Read one music generation's status and output URL."""
    operation: Literal["get_audio"] = "get_audio"
    generation_id: str = Field(..., title="Generation ID", min_length=1)


class ExtractDocument(_Input):
    """Extract text from a document using Google Document AI OCR."""
    operation: Literal["extract_document"] = "extract_document"
    model: Literal["gc-document-ai", "google/gc-document-ai"] = "gc-document-ai"
    document: str = Field(..., min_length=1, title="Document URL")
    mimeType: Literal["application/pdf", "image/gif", "image/tiff", "image/jpeg", "image/png", "image/bmp", "image/webp", "text/html"] | None = None


AiMlApiConfig = Annotated[Union[CreateResponse, CreateChatCompletion, CreateEmbeddings,
    GenerateImage, CreateTranscription, GetTranscription, CreateMessage, GenerateVideo, GetVideo,
    GenerateAudio, GetAudio, ExtractDocument], Field(discriminator="operation")]


class AiMlApiFullConfig(NodeConfig[AiMlApiConfig, AiMlApiCredential]):
    pass


ROUTES = {
    "create_response": ("POST", "/v1/responses"),
    "create_chat_completion": ("POST", "/v1/chat/completions"),
    "create_embeddings": ("POST", "/v1/embeddings"),
    "generate_image": ("POST", "/v1/images/generations"),
    "create_transcription": ("POST", "/v1/stt/create"),
    "create_message": ("POST", "/v1/messages"),
    "get_transcription": ("GET", "/v1/stt/{generation_id}"),
    "generate_video": ("POST", "/v2/video/generations"),
    "get_video": ("GET", "/v2/video/generations"),
    "generate_audio": ("POST", "/v2/generate/audio"),
    "get_audio": ("GET", "/v2/generate/audio"),
    "extract_document": ("POST", "/v1/ocr"),
}


async def _request(credential, method, path, data=None):
    async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
        response = await client.request(method, BASE_URL + path,
            headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
            **({"params": data} if method == "GET" else {"json": data}))
    if not 200 <= response.status_code < 300:
        # Keep the provider's rejection wording for the shared connect verdict.
        text = response.text.replace(credential.api_key, "[redacted]")[:2000]
        raise ValueError(f"AI/ML API HTTP {response.status_code}: {text}")
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("AI/ML API returned an unexpected response")
    if result.get("error"):
        raise ValueError("AI/ML API error: " + str(result["error"]).replace(credential.api_key, "[redacted]")[:2000])
    return result


class AiMlApiNode(WorkflowNode):
    integration_type = "automation-ai-ml-api"
    connection_evidence = ConnectionEvidence(field="account", noun="AI/ML API account")

    @classmethod
    def get_config_model(cls):
        return AiMlApiFullConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, **kwargs):
        if field_name != "account":
            return []
        credential = AiMlApiCredential.model_validate(credential_data)
        result = await _request(credential, "GET", "/v2/billing/detail")
        if not isinstance(result.get("email"), str) or not result["email"] or not isinstance(result.get("user_id"), (int, str)):
            raise ValueError("AI/ML API did not identify the billing account")
        return [{"value": str(result["user_id"]), "label": result["email"]}]

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an AI/ML API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        data = config.model_dump(exclude={"operation"}, exclude_none=True)
        if config.operation == "get_transcription":
            path = path.replace("{generation_id}", quote(data.pop("generation_id"), safe=""))
        result = await _request(self.config.credentials, method, path, data)
        if config.operation == "generate_image":
            for index, image in enumerate(result.get("data") or []):
                if image.get("b64_json"):
                    encoded = image.pop("b64_json")
                    image["file"] = BinaryOutput(base64.b64decode(encoded, validate=True),
                        content_type="image/" + config.output_format,
                        filename=f"image-{index}.{config.output_format}")
        return {"status": "success", "data": result}
