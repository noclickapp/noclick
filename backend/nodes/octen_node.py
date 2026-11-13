"""Octen search, extraction, embeddings and non-streaming AI APIs.

Contract: https://docs.octen.ai/api-reference/openapi.json, version 1.0.0.
Each operation makes exactly one request; async agent tasks are retrieved explicitly.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.octen.ai"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class OctenAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Octen API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://octen.ai/platform",
            "x-credential-instructions": "Create an API key in your Octen platform account and paste it here. A payment method and sufficient balance are required for search and generation. Connecting runs a small web search, which may incur usage. This proves key acceptance, not account identity.",
        },
    )
    credential_type: Literal["octen_api_key"] = Field("octen_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Query(_Operation):
    query: str = Field(..., min_length=1, max_length=500, title="Search Query")


class PulseSearch(_Query):
    """Quickly find likely URLs, optionally including highlights and page content."""
    operation: Literal["pulse_search"] = Field("pulse_search", json_schema_extra={"ui:hidden": True, "x-display-name": "Pulse Search"})
    mode: Literal["lite", "standard"] = "lite"
    count: int = Field(5, ge=1, le=10)
    highlight: Optional[Json[dict[str, Any]]] = Field(None, description="JSON highlight options: enable, max_tokens (100–20000).", json_schema_extra=JSON_EDITOR)
    full_content: Optional[Json[dict[str, Any]]] = Field(None, description="JSON full-content options: enable, max_tokens.", json_schema_extra=JSON_EDITOR)
    safesearch: Literal["off", "strict"] = "strict"
    include_images: bool = False


class _SearchFilters(_Query):
    count: int = Field(5, ge=1, le=100)
    include_domains: Optional[Json[list[str]]] = Field(None, json_schema_extra=JSON_EDITOR)
    exclude_domains: Optional[Json[list[str]]] = Field(None, json_schema_extra=JSON_EDITOR)
    time_basis: Optional[Literal["auto", "published", "crawled"]] = None
    time_range: Optional[Literal["day", "week", "month", "year", "d", "w", "m", "y"]] = None
    start_time: Optional[str] = Field(None, description="ISO 8601 date-time, including timezone.", json_schema_extra={"format": "date-time"})
    end_time: Optional[str] = Field(None, description="ISO 8601 date-time, including timezone.", json_schema_extra={"format": "date-time"})
    language: Optional[Json[list[str]]] = Field(None, description="JSON array of ISO 639-1 language codes.", json_schema_extra=JSON_EDITOR)
    highlight: Optional[Json[dict[str, Any]]] = Field(None, description="JSON options: enable, max_tokens.", json_schema_extra=JSON_EDITOR)
    full_content: Optional[Json[dict[str, Any]]] = Field(None, description="JSON options: enable, max_tokens.", json_schema_extra=JSON_EDITOR)


class WebSearch(_SearchFilters):
    """Search ranked web pages with domain, date, language and content filters."""
    operation: Literal["search_web"] = Field("search_web", json_schema_extra={"ui:hidden": True, "x-display-name": "Web Search"})
    include_text: Optional[Json[list[str]]] = Field(None, json_schema_extra=JSON_EDITOR)
    exclude_text: Optional[Json[list[str]]] = Field(None, json_schema_extra=JSON_EDITOR)
    format: Literal["markdown", "text"] = "text"
    safesearch: Literal["off", "strict"] = "strict"
    include_images: bool = False


class NewsSearch(_SearchFilters):
    """Search news articles and optionally group related stories into subjects."""
    operation: Literal["news_search"] = Field("news_search", json_schema_extra={"ui:hidden": True, "x-display-name": "News Search"})
    subjects: Optional[Json[dict[str, Any]]] = Field(None, description="JSON options: enable, count (1–5), max_sub_news (1–20).", json_schema_extra=JSON_EDITOR)


class BusinessSearch(_SearchFilters):
    """Search companies, people, business news and entity cards."""
    operation: Literal["business_search"] = Field("business_search", json_schema_extra={"ui:hidden": True, "x-display-name": "Business Search"})
    entities: Optional[Json[dict[str, Any]]] = Field(None, description="JSON entity-card options: enable, count, max_activities, max_news.", json_schema_extra=JSON_EDITOR)


class PlaceSearch(_Query):
    """Find local businesses and places near a location."""
    operation: Literal["place_search"] = Field("place_search", json_schema_extra={"ui:hidden": True, "x-display-name": "Place Search"})
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius: Optional[int] = Field(None, ge=1, le=50000, description="Search radius in metres.")
    places: Optional[Json[dict[str, Any]]] = Field(None, description="JSON place-card options, for example {\"count\":5}.", json_schema_extra=JSON_EDITOR)
    web_search: Optional[Json[dict[str, Any]]] = Field(None, description="JSON web result options.", json_schema_extra=JSON_EDITOR)
    user_location: Optional[Json[dict[str, Any]]] = Field(None, description="JSON location context from the Place Search API.", json_schema_extra=JSON_EDITOR)


class ImageSearch(_Operation):
    """Search images using one text or image input."""
    operation: Literal["image_search"] = Field("image_search", json_schema_extra={"ui:hidden": True, "x-display-name": "Image Search"})
    inputs: Json[list[dict[str, Any]]] = Field(..., description='JSON array with one input, e.g. [{"type":"text","data":"mountains"}] or [{"type":"image","url":"https://example.com/image.jpg"}].', json_schema_extra=JSON_EDITOR)
    count: int = Field(5, ge=1, le=10)
    include_domains: Optional[Json[list[str]]] = Field(None, json_schema_extra=JSON_EDITOR)
    exclude_domains: Optional[Json[list[str]]] = Field(None, json_schema_extra=JSON_EDITOR)
    safesearch: Literal["off", "strict"] = "strict"

    @field_validator("inputs")
    @classmethod
    def one_input(cls, value):
        if len(value) != 1:
            raise ValueError("Supply exactly one image or text input")
        return value


class VideoSearch(_Operation):
    """Find videos matching one text input."""
    operation: Literal["video_search"] = Field("video_search", json_schema_extra={"ui:hidden": True, "x-display-name": "Video Search"})
    inputs: Json[list[dict[str, Any]]] = Field(..., description='JSON array with one text query, e.g. [{"type":"text","data":"sourdough bread"}].', json_schema_extra=JSON_EDITOR)
    count: int = Field(5, ge=1, le=10)
    time_range: Optional[Literal["day", "week", "month", "year", "d", "w", "m", "y"]] = None
    start_time: Optional[str] = Field(None, json_schema_extra={"format": "date-time"})
    end_time: Optional[str] = Field(None, json_schema_extra={"format": "date-time"})
    safesearch: Literal["off", "strict"] = "strict"

    @field_validator("inputs")
    @classmethod
    def one_text(cls, value):
        if len(value) != 1 or value[0].get("type") != "text" or not isinstance(value[0].get("data"), str):
            raise ValueError("Supply one text input with type and data")
        return value


class Extract(_Operation):
    """Extract clean text or Markdown from up to 20 URLs."""
    operation: Literal["extract"] = Field("extract", json_schema_extra={"ui:hidden": True, "x-display-name": "Extract Content"})
    urls: Json[list[str]] = Field(..., description="JSON array of 1–20 page URLs.", json_schema_extra=JSON_EDITOR)
    mode: Literal["standard", "advanced", "auto"] = "standard"
    query: Optional[str] = Field(None, max_length=500)
    format: Literal["markdown", "text"] = "markdown"
    timeout: int = Field(30, ge=1, le=60)
    max_age_seconds: Optional[int] = Field(None, ge=300, le=31536000)
    include_images: bool = False
    include_videos: bool = False
    include_audio: bool = False
    include_links: Optional[Json[dict[str, Any]]] = Field(None, description="JSON options: scope, max_links.", json_schema_extra=JSON_EDITOR)

    @field_validator("urls")
    @classmethod
    def url_count(cls, value):
        if not 1 <= len(value) <= 20 or any(len(url) > 2048 for url in value):
            raise ValueError("Supply 1–20 URLs, each at most 2048 characters")
        return value


class CreateEmbeddings(_Operation):
    """Convert a batch of texts into embedding vectors."""
    operation: Literal["create_embeddings"] = Field("create_embeddings", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Text Embeddings"})
    input: Json[list[str]] = Field(..., description="JSON array of up to 1000 texts, each at most 10000 characters.", json_schema_extra=JSON_EDITOR)
    model: Literal["octen-embedding-0.6b", "octen-embedding-4b", "octen-embedding-8b"] = "octen-embedding-4b"
    dimension: Optional[int] = Field(None, ge=1)
    input_type: Optional[Literal["query", "document"]] = None

    @model_validator(mode="after")
    def bounds(self):
        if not 1 <= len(self.input) <= 1000 or any(len(text) > 10000 for text in self.input):
            raise ValueError("Supply 1–1000 texts of at most 10000 characters")
        maximum = {"octen-embedding-0.6b": 1024, "octen-embedding-4b": 2560, "octen-embedding-8b": 4096}[self.model]
        if self.dimension is not None and self.dimension > maximum:
            raise ValueError("Dimension exceeds this embedding model's maximum")
        return self


class CreateVLEmbeddings(_Operation):
    """Convert text, images or video into multimodal embedding vectors."""
    operation: Literal["create_vl_embeddings"] = Field("create_vl_embeddings", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Multimodal Embeddings"})
    model: Literal["octen-vl-embedding", "octen-vl-embedding-large"] = "octen-vl-embedding"
    input: Json[dict[str, Any]] = Field(..., description='JSON input object, e.g. {"contents":[{"text":"A red tent"}]}.', json_schema_extra=JSON_EDITOR)
    dimension: Optional[int] = Field(None, ge=1)
    enable_fusion: Optional[bool] = Field(None, description="Fuse all content elements into one vector.")
    fps: Optional[float] = Field(None, ge=0, le=1, description="Video frames sampled per second.")
    instruct: Optional[str] = Field(None, description="Custom embedding task instructions.")

    @model_validator(mode="after")
    def bounds(self):
        contents = self.input.get("contents")
        if not isinstance(contents, list) or not 1 <= len(contents) <= 20:
            raise ValueError("Supply an input object with 1–20 contents")
        for item in contents:
            if not isinstance(item, dict) or len(set(item) & {"text", "image", "video"}) != 1:
                raise ValueError("Each content element must supply exactly one of text, image or video")
        maximum = 2048 if self.model == "octen-vl-embedding" else 4096
        if self.dimension is not None and self.dimension > maximum:
            raise ValueError("Dimension exceeds this multimodal model's maximum")
        return self


class _Conversation(_Operation):
    messages: Json[list[dict[str, Any]]] = Field(..., description='JSON conversation, e.g. [{"role":"user","content":"Explain vector search"}].', json_schema_extra=JSON_EDITOR)

    @field_validator("messages")
    @classmethod
    def nonempty(cls, value):
        if not value:
            raise ValueError("Supply at least one conversation message")
        return value


class ChatCompletion(_Conversation):
    """Generate a non-streaming chat completion, optionally with tools."""
    operation: Literal["chat_completion"] = Field("chat_completion", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Chat Completion"})
    model: str = Field("anthropic/claude-sonnet-4.6")
    max_tokens: Optional[int] = Field(None, ge=1)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    tools: Optional[Json[list[dict[str, Any]]]] = Field(None, json_schema_extra=JSON_EDITOR)
    tool_choice: Optional[Json[Any]] = Field(None, json_schema_extra=JSON_EDITOR)
    response_format: Optional[Json[dict[str, Any]]] = Field(None, json_schema_extra=JSON_EDITOR)


class Answer(_Conversation):
    """Decompose a question, search the web and synthesize a cited answer."""
    operation: Literal["answer"] = Field("answer", json_schema_extra={"ui:hidden": True, "x-display-name": "Generate Answer"})
    model: str = Field("anthropic/claude-sonnet-4.6")
    mode: Literal["queries_only", "queries_and_search", "full"] = "full"
    max_queries: int = Field(5, ge=1, le=30)
    web_search_options: Optional[Json[dict[str, Any]]] = Field(None, json_schema_extra=JSON_EDITOR)


class BroadSearch(_Query):
    """Decompose a query and return web results grouped by sub-query."""
    operation: Literal["broad_search"] = Field("broad_search", json_schema_extra={"ui:hidden": True, "x-display-name": "Broad Search"})
    max_queries: int = Field(5, ge=1, le=30)
    search_options: Optional[Json[dict[str, Any]]] = Field(None, json_schema_extra=JSON_EDITOR)


class CreateSearchAgent(_Conversation):
    """Submit an asynchronous Search Agent task; retrieve its result separately."""
    operation: Literal["create_search_agent"] = Field("create_search_agent", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Search Agent Task"})
    tier: Literal["auto", "low", "medium", "high"] = "auto"
    previous_task_id: Optional[str] = None
    response_format: Optional[Json[dict[str, Any]]] = Field(None, json_schema_extra=JSON_EDITOR)


class GetSearchAgent(_Operation):
    """Retrieve a Search Agent task's status, answer, citations and usage."""
    operation: Literal["get_search_agent"] = Field("get_search_agent", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Search Agent Result"})
    task_id: str = Field(..., min_length=1, max_length=256, description="Task ID returned by Create Search Agent Task.")

    @field_validator("task_id")
    @classmethod
    def segment(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(c.isspace() for c in value):
            raise ValueError("Paste one Search Agent task ID")
        return value


# Octen's own MCP server: agents get its tools through a person's Octen sign-in.
OctenMcpCredential = mcp_credential("octen", "https://mcp.octen.ai/mcp", app="Octen")
OctenCredential = Union[OctenAPIKeyCredential, OctenMcpCredential]


OctenOperation = Annotated[Union[
    PulseSearch, WebSearch, NewsSearch, BusinessSearch, PlaceSearch, ImageSearch,
    VideoSearch, Extract, CreateEmbeddings, CreateVLEmbeddings, ChatCompletion,
    Answer, BroadSearch, CreateSearchAgent, GetSearchAgent,
], Field(discriminator="operation")]


class OctenNodeConfig(NodeConfig[OctenOperation, OctenCredential]):
    pass


ROUTES = {
    "pulse_search": "/pulse-search", "search_web": "/search",
    "news_search": "/news-search", "business_search": "/business-search",
    "place_search": "/place-search", "image_search": "/image-search",
    "video_search": "/video-search", "extract": "/extract",
    "create_embeddings": "/embedding", "create_vl_embeddings": "/vl-embedding",
    "chat_completion": "/v1/chat/completions", "answer": "/answer",
    "broad_search": "/broad-search", "create_search_agent": "/v1/agent",
}


class OctenNode(WorkflowNode):
    integration_type = "automation-octen"
    credential_provider_labels = {"octen": "Octen Account"}
    connection_evidence = ConnectionEvidence(
        noun="web search results", operation="search_web",
        operation_arguments={"query": "Octen", "count": 1}, proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return OctenNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Octen API key")
        op = self.config.config
        key = self.config.credentials.api_key
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        method = "POST"
        if isinstance(op, GetSearchAgent):
            method, route, body = "GET", "/v1/agent/" + quote(op.task_id, safe=""), None
        else:
            route = ROUTES[op.operation]
            if isinstance(op, (ChatCompletion, Answer, CreateSearchAgent)):
                body["stream"] = False
        async with guarded_async_client(timeout=180.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + route,
                headers={"x-api-key": key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"Octen returned a non-JSON response (HTTP {response.status_code})") from None
        if not isinstance(data, dict):
            raise ValueError("Octen returned an unexpected JSON response")
        if response.is_error or response.is_redirect or data.get("error") or data.get("code", 0) not in (0, None):
            message = data.get("msg") or data.get("message") or data.get("error") or f"HTTP {response.status_code}"
            raise ValueError("Octen: " + str(message).replace(key, "[redacted]"))
        if not any(data.get(field) for field in ("request_id", "id", "task_id")):
            raise ValueError("Octen response is missing its request or task identifier")
        result = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(result)
        return result
