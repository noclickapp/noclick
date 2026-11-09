"""JigsawStack v1 AI utilities and project prompt management.

Wire contract: https://jigsawstack.com/openapi.json (1.0.0).
Prompt creation/list fields also follow the provider's prompt-engine docs.
Each operation makes one fixed API call; processing may consume provider credits.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.jigsawstack.com/v1"
Language = Literal['af', 'am', 'ar', 'as', 'az', 'ba', 'be', 'bg', 'bn', 'bo', 'br', 'bs', 'ca', 'ch', 'co', 'cs', 'cy', 'da', 'de', 'dv', 'dz', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'ff', 'fi', 'fj', 'fo', 'fr', 'fy', 'ga', 'gd', 'gl', 'gn', 'gu', 'gv', 'ha', 'he', 'hi', 'hr', 'ht', 'hu', 'hy', 'id', 'ig', 'is', 'it', 'iu', 'ja', 'jv', 'ka', 'kg', 'ki', 'kj', 'kk', 'kl', 'km', 'kn', 'ko', 'kr', 'ks', 'ku', 'kv', 'kw', 'ky', 'la', 'lb', 'lg', 'li', 'ln', 'lo', 'lt', 'lu', 'lv', 'mg', 'mh', 'mi', 'mk', 'ml', 'mn', 'mo', 'mr', 'ms', 'mt', 'my', 'na', 'nb', 'nd', 'ne', 'ng', 'nl', 'nn', 'no', 'nr', 'nv', 'ny', 'oc', 'oj', 'om', 'or', 'os', 'pa', 'pi', 'pl', 'ps', 'pt', 'qu', 'rm', 'rn', 'ro', 'ru', 'rw', 'sa', 'sc', 'sd', 'se', 'sg', 'sh', 'si', 'sk', 'sl', 'sm', 'sn', 'so', 'sq', 'sr', 'ss', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'ti', 'tk', 'tl', 'tn', 'to', 'tr', 'ts', 'tt', 'tw', 'ty', 'ug', 'uk', 'ur', 'uz', 've', 'vi', 'vo', 'wo', 'xh', 'yi', 'yo', 'zh', 'zh-TW', 'zu']


class JigsawstackAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Jigsawstack API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://jigsawstack.com/dashboard",
            "x-credential-instructions": "Paste your project's secret API key from the JigsawStack dashboard. NoClick sends it in x-api-key to api.jigsawstack.com. Listing saved prompts checks project access; AI operations consume your JigsawStack credits.",
        })
    credential_type: Literal["jigsawstack_api_key"] = Field("jigsawstack_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class Sentiment(Input):
    """Analyze the sentiment of text."""
    operation: Literal["analyze_sentiment"] = "analyze_sentiment"
    text: str = Field(..., min_length=1, max_length=2000)


class TextToSQL(Input):
    """Generate SQL from a prompt; does not execute the SQL."""
    operation: Literal["generate_sql"] = "generate_sql"
    prompt: str = Field(..., min_length=10)
    sql_schema: Optional[str] = None
    database: Optional[Literal["postgresql", "mysql", "sqlite"]] = None


class Profanity(Input):
    """Detect profanity and return censored text."""
    operation: Literal["check_profanity"] = "check_profanity"
    text: str = Field(..., min_length=1)
    censor_replacement: str = "*"


class Spam(Input):
    """Check text for spam."""
    operation: Literal["check_spam"] = "check_spam"
    text: str = Field(..., min_length=5, max_length=5000)


class Spelling(Input):
    """Check text spelling in a language."""
    operation: Literal["check_spelling"] = "check_spelling"
    text: str = Field(..., min_length=1)
    language_code: str = "en"


class Translate(Input):
    """Translate text into a supported target language."""
    operation: Literal["translate_text"] = "translate_text"
    text: str = Field(..., min_length=1, max_length=5000)
    target_language: Language
    current_language: Optional[Language] = None


class Embedding(Input):
    """Generate a text embedding with the v1 embedding endpoint."""
    operation: Literal["create_embedding"] = "create_embedding"
    text: str = Field(..., min_length=1)
    type: Literal["text", "text-other"] = "text"
    dimensions: int = Field(4096, ge=32, le=4096)
    query: bool = False
    token_overflow_mode: Literal["truncate", "error"] = "error"


class Scrape(Input):
    """Extract requested elements from a web page."""
    operation: Literal["scrape_page"] = "scrape_page"
    url: str = Field(..., min_length=1)
    element_prompts: list[str] = Field(..., min_length=1, max_length=5)
    root_element_selector: str = "main"
    scroll: bool = False


class OCR(Input):
    """Extract text or structured fields from an image or document URL."""
    operation: Literal["extract_document"] = "extract_document"
    url: str = Field(..., min_length=1)
    prompt: Optional[str] = Field(None, min_length=1)
    fine_grained: bool = False
    return_bounds: bool = True


class DetectObjects(Input):
    """Detect objects in an image; annotated images are returned as URLs."""
    operation: Literal["detect_objects"] = "detect_objects"
    url: str = Field(..., min_length=1)
    prompts: Optional[list[Annotated[str, Field(min_length=1, max_length=150)]]] = None
    features: list[Literal["object_detection", "object", "gui"]] = Field(default_factory=lambda: ["object_detection"], min_length=1)
    annotated_image: bool = False


class Transcribe(Input):
    """Synchronously transcribe an audio/video URL without streaming or a webhook."""
    operation: Literal["transcribe_audio"] = "transcribe_audio"
    url: str = Field(..., min_length=1)
    by_speaker: bool = False
    word_timestamps: bool = False
    translate: bool = False


class Search(Input):
    """Search the web; returns a single bounded provider result set."""
    operation: Literal["search_web"] = "search_web"
    query: str = Field(..., min_length=1, max_length=400)
    max_results: int = Field(10, ge=1, le=100)
    safe_search: Literal["strict", "moderate", "off"] = "moderate"
    spell_check: bool = True
    ai_overview: bool = True
    auto_scrape: bool = False


class Suggest(Input):
    """Get web-search suggestions for a query."""
    operation: Literal["suggest_search"] = "suggest_search"
    query: str = Field(..., min_length=1, max_length=100)


class ListPrompts(Input):
    """Read one page of prompts saved in the connected project."""
    operation: Literal["list_prompts"] = "list_prompts"
    limit: int = Field(30, ge=1, le=100)
    page: int = Field(1, ge=1)


class PromptInput(Input):
    key: str = Field(..., min_length=1)
    optional: bool = False
    initial_value: Optional[str] = None


class CreatePrompt(Input):
    """Save a reusable prompt in the connected project."""
    operation: Literal["create_prompt"] = "create_prompt"
    prompt: str = Field(..., min_length=1, max_length=500000)
    name: Optional[str] = Field(None, max_length=300)
    inputs: Optional[list[PromptInput]] = None
    return_prompt: Optional[str] = None
    optimize_prompt: bool = True
    use_internet: bool = False


class RunPrompt(Input):
    """Run one saved prompt with non-streaming string inputs."""
    operation: Literal["run_prompt"] = "run_prompt"
    id: UUID
    input_values: Optional[dict[str, Annotated[str, Field(min_length=1, max_length=500)]]] = None


class DeletePrompt(Input):
    """Delete the explicitly selected saved prompt."""
    operation: Literal["delete_prompt"] = "delete_prompt"
    id: UUID


JigsawstackConfig = Annotated[Union[Sentiment, TextToSQL, Profanity, Spam, Spelling,
    Translate, Embedding, Scrape, OCR, DetectObjects, Transcribe, Search, Suggest,
    ListPrompts, CreatePrompt, RunPrompt, DeletePrompt], Field(discriminator="operation")]


class JigsawstackFullConfig(NodeConfig[JigsawstackConfig, JigsawstackAPIKeyCredential]):
    pass


ROUTES = {
    "analyze_sentiment": ("POST", "/ai/sentiment"),
    "generate_sql": ("POST", "/ai/sql"),
    "check_profanity": ("POST", "/validate/profanity"),
    "check_spam": ("POST", "/validate/spam_check"),
    "check_spelling": ("POST", "/validate/spell_check"),
    "translate_text": ("POST", "/ai/translate"),
    "create_embedding": ("POST", "/embedding"),
    "scrape_page": ("POST", "/ai/scrape"),
    "extract_document": ("POST", "/vocr"),
    "detect_objects": ("POST", "/object_detection"),
    "transcribe_audio": ("POST", "/ai/transcribe"),
    "search_web": ("POST", "/web/search"),
    "suggest_search": ("GET", "/web/search/suggest"),
    "list_prompts": ("GET", "/prompt_engine"),
    "create_prompt": ("POST", "/prompt_engine"),
    "run_prompt": ("POST", "/prompt_engine/{id}"),
    "delete_prompt": ("DELETE", "/prompt_engine/{id}"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class JigsawstackNode(WorkflowNode):
    integration_type = "automation-jigsawstack"
    connection_evidence = ConnectionEvidence(noun="saved prompts", operation="list_prompts", label_keys=("prompt", "id"))

    @classmethod
    def get_config_model(cls):
        return JigsawstackFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a JigsawStack API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        body = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if "{id}" in path:
            path = path.replace("{id}", quote(str(op.id), safe=""))
            if method == "DELETE":
                body = {}
        if isinstance(op, RunPrompt):
            body["stream"] = False
        if isinstance(op, Transcribe):
            body["stream"] = False
        if isinstance(op, DetectObjects):
            body["return_type"] = "url"
        try:
            async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"x-api-key": key, "Accept": "application/json"},
                    **({"params": body} if method == "GET" else {"json": body} if method == "POST" else {}))
        except httpx.HTTPError:
            raise ValueError("JigsawStack request did not complete; inspect the provider before retrying a write") from None
        if len(response.content) > 20_000_000:
            raise ValueError("JigsawStack response exceeds the output limit")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("JigsawStack returned an unexpected non-JSON response") from None
        payload = _redact(payload, key)
        if not response.is_success or not isinstance(payload, dict) or payload.get("success") is not True:
            output = {"status": "error", "success": False, "http_status": response.status_code,
                "error": payload.get("error", "JigsawStack did not confirm success") if isinstance(payload, dict) else "Unexpected JigsawStack response"}
        else:
            output = {"status": "success", "success": True, "http_status": response.status_code, "data": payload}
            if isinstance(op, ListPrompts):
                rows = payload.get("prompt_engines")
                if not isinstance(rows, list):
                    raise ValueError("JigsawStack prompt list is missing")
                output.update(items=rows, page=payload.get("page"), limit=payload.get("limit"), has_more=payload.get("has_more"))
        await self.emit(output)
        return output
