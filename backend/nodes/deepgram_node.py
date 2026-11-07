"""Deepgram speech, text intelligence, and project management integration.

API reference: https://developers.deepgram.com/reference/deepgram-api-overview
Authentication uses a project API key (``Authorization: Token``). Deepgram does
not expose a third-party OAuth authorization flow.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import (
    filter_options_by_search,
    require_credential_token,
)


API_BASE = "https://api.deepgram.com/v1"
AGENT_BASE = "https://agent.deepgram.com/v1"


def operation(name: str, category: str, label: str):
    return Field(
        name,
        title=label,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-category": category,
            "x-is-trigger": False,
            "x-display-name": label,
        },
    )


def project_field():
    return Field(
        ...,
        title="Project",
        description="Deepgram project ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "placeholder": "Select a project...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter a project ID",
            },
            "x-resource-type": "deepgram_project",
        },
    )


class DeepgramAPIKeyCredential(BaseModel):
    credential_type: Literal["deepgram_api_key"] = Field(
        "deepgram_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Project API key from the Deepgram Console",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Deepgram API Key",
        json_schema_extra={"x-credential-url": "https://console.deepgram.com/"}
    )


class DeepgramTranscribeURLConfig(BaseModel):
    operation: Literal["transcribe_url"] = operation(
        "transcribe_url", "Speech to Text", "Transcribe Audio URL"
    )
    audio_url: str = Field(
        ..., title="Audio URL", description="Publicly reachable audio or video URL"
    )
    model: str = Field(
        "nova-3", title="Model", description="Speech recognition model, such as nova-3"
    )
    language: Optional[str] = Field(
        None,
        title="Language",
        description="BCP-47 language code; leave empty for English",
    )
    detect_language: bool = Field(False, title="Detect Language")
    smart_format: bool = Field(True, title="Smart Format")
    punctuate: bool = Field(True, title="Punctuate")
    utterances: bool = Field(False, title="Utterances")
    diarize_model: Optional[str] = Field(
        None, title="Diarization Model", description="latest, v1 or v2"
    )
    summarize: bool = Field(False, title="Summarize")
    sentiment: bool = Field(False, title="Sentiment")
    topics: bool = Field(False, title="Topics")
    intents: bool = Field(False, title="Intents")
    detect_entities: bool = Field(False, title="Detect Entities")
    keyterms: Optional[str] = Field(
        None,
        title="Key Terms",
        description="Nova-3 key terms, one per line",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tag: Optional[str] = Field(None, title="Usage Tag")


class DeepgramTextToSpeechConfig(BaseModel):
    operation: Literal["text_to_speech"] = operation(
        "text_to_speech", "Text to Speech", "Generate Speech"
    )
    text: str = Field(..., title="Text", json_schema_extra={"ui:widget": "textarea"})
    model: str = Field(
        "aura-2-thalia-en",
        title="Voice Model",
        description="Aura voice model, such as aura-2-thalia-en",
    )
    encoding: Literal[
        "mp3", "linear16", "mulaw", "alaw", "opus", "flac", "aac"
    ] = Field("mp3", title="Encoding")
    sample_rate: Optional[int] = Field(
        None, title="Sample Rate", description="Supported rates depend on encoding"
    )
    speed: Optional[float] = Field(None, ge=0.7, le=1.5, title="Speed")
    tag: Optional[str] = Field(None, title="Usage Tag")


class DeepgramAnalyzeTextConfig(BaseModel):
    operation: Literal["analyze_text"] = operation(
        "analyze_text", "Text Intelligence", "Analyze Text"
    )
    text: str = Field(..., title="Text", json_schema_extra={"ui:widget": "textarea"})
    language: str = Field("en", title="Language")
    summarize: bool = Field(False, title="Summarize")
    sentiment: bool = Field(True, title="Sentiment")
    topics: bool = Field(False, title="Topics")
    intents: bool = Field(False, title="Intents")


class DeepgramListProjectsConfig(BaseModel):
    operation: Literal["list_projects"] = operation(
        "list_projects", "Projects", "List Projects"
    )


class DeepgramGetProjectConfig(BaseModel):
    operation: Literal["get_project"] = operation(
        "get_project", "Projects", "Get Project"
    )
    project_id: str = project_field()


class DeepgramUpdateProjectConfig(BaseModel):
    operation: Literal["update_project"] = operation(
        "update_project", "Projects", "Rename Project"
    )
    project_id: str = project_field()
    name: str = Field(..., title="New Name")


class DeepgramListProjectModelsConfig(BaseModel):
    operation: Literal["list_project_models"] = operation(
        "list_project_models", "Models", "List Project Models"
    )
    project_id: str = project_field()
    include_outdated: bool = Field(False, title="Include Outdated Versions")


class DeepgramGetProjectModelConfig(BaseModel):
    operation: Literal["get_project_model"] = operation(
        "get_project_model", "Models", "Get Project Model"
    )
    project_id: str = project_field()
    model_id: str = Field(..., title="Model ID", description="UUID of a project model")


class DeepgramListPublicModelsConfig(BaseModel):
    operation: Literal["list_public_models"] = operation(
        "list_public_models", "Models", "List Public Models"
    )
    include_outdated: bool = Field(False, title="Include Outdated Versions")


class DeepgramGetPublicModelConfig(BaseModel):
    operation: Literal["get_public_model"] = operation(
        "get_public_model", "Models", "Get Public Model"
    )
    model_id: str = Field(..., title="Model ID", description="UUID of a public model")


class DeepgramListThinkModelsConfig(BaseModel):
    operation: Literal["list_think_models"] = operation(
        "list_think_models", "Models", "List Voice Agent Think Models"
    )


class DeepgramGetUsageBreakdownConfig(BaseModel):
    operation: Literal["get_usage_breakdown"] = operation(
        "get_usage_breakdown", "Usage", "Get Usage Breakdown"
    )
    project_id: str = project_field()
    start: Optional[str] = Field(None, title="Start Date", description="YYYY-MM-DD")
    end: Optional[str] = Field(None, title="End Date", description="YYYY-MM-DD")
    endpoint: Optional[Literal["listen", "read", "speak", "agent"]] = Field(
        None, title="Endpoint"
    )
    tag: Optional[str] = Field(None, title="Usage Tag")


class DeepgramListRequestsConfig(BaseModel):
    operation: Literal["list_requests"] = operation(
        "list_requests", "Usage", "List Project Requests"
    )
    project_id: str = project_field()
    start: Optional[str] = Field(None, title="Start Date")
    end: Optional[str] = Field(None, title="End Date")
    limit: int = Field(10, ge=1, le=1000, title="Page Size")
    page: int = Field(0, ge=0, title="Page")
    status: Optional[Literal["succeeded", "failed"]] = Field(None, title="Status")


class DeepgramGetRequestConfig(BaseModel):
    operation: Literal["get_request"] = operation(
        "get_request", "Usage", "Get Project Request"
    )
    project_id: str = project_field()
    request_id: str = Field(..., title="Request ID")


class DeepgramListKeysConfig(BaseModel):
    operation: Literal["list_keys"] = operation(
        "list_keys", "Projects", "List Project API Keys"
    )
    project_id: str = project_field()
    status: Optional[Literal["active", "expired"]] = Field(None, title="Status")


DeepgramConfig = Annotated[
    Union[
        DeepgramTranscribeURLConfig,
        DeepgramTextToSpeechConfig,
        DeepgramAnalyzeTextConfig,
        DeepgramListProjectsConfig,
        DeepgramGetProjectConfig,
        DeepgramUpdateProjectConfig,
        DeepgramListProjectModelsConfig,
        DeepgramGetProjectModelConfig,
        DeepgramListPublicModelsConfig,
        DeepgramGetPublicModelConfig,
        DeepgramListThinkModelsConfig,
        DeepgramGetUsageBreakdownConfig,
        DeepgramListRequestsConfig,
        DeepgramGetRequestConfig,
        DeepgramListKeysConfig,
    ],
    Discriminator("operation"),
]


class DeepgramNodeConfig(NodeConfig[DeepgramConfig, DeepgramAPIKeyCredential]):
    pass


def _segment(value: str) -> str:
    """Treat IDs as a single URL path segment, including user-entered values."""
    return quote(value, safe="")


async def _request(
    api_key: str,
    method: str,
    path: str,
    *,
    params=None,
    body=None,
    binary=False,
    agent=False,
) -> Dict[str, Any]:
    started = time.monotonic()
    headers = {"Authorization": f"Token {api_key}"}
    base = AGENT_BASE if agent else API_BASE
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.request(
                method, f"{base}{path}", headers=headers, params=params, json=body
            )
        elapsed = round((time.monotonic() - started) * 1000, 1)
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]
            return {
                "status": "error",
                "status_code": response.status_code,
                "error": detail,
                "timing_ms": {"api_request": elapsed},
            }
        if binary:
            mime = response.headers.get("content-type", "audio/mpeg").split(";", 1)[0]
            ext = {
                "audio/mpeg": "mp3",
                "audio/wav": "wav",
                "audio/flac": "flac",
                "audio/ogg": "ogg",
                "audio/aac": "aac",
            }.get(mime, "bin")
            data = BinaryOutput(response.content, mime, f"deepgram-speech.{ext}")
        elif response.content:
            data = response.json()
        else:
            data = {"success": True}
        return {
            "status": "success",
            "data": data,
            "timing_ms": {"api_request": elapsed},
        }
    except httpx.HTTPError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 1)},
        }


class DeepgramNode(WorkflowNode):
    integration_type = "automation-deepgram"

    edit_examples = [
        "Transcribe a meeting recording and identify speakers",
        "Generate an audio reply from text",
        "Analyze a transcript for sentiment and topics",
        "Report Deepgram speech usage by project",
    ]
    connection_evidence = ConnectionEvidence(
        field="project_id", noun="projects", label_keys=("name",)
    )

    @classmethod
    def get_config_model(cls):
        return DeepgramNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name, credential_data, context=None, page_token=None, search=None
    ):
        if field_name != "project_id":
            return {"options": [], "next_page_token": None}
        api_key = require_credential_token(
            (credential_data or {}).get("api_key"),
            "Connect a Deepgram API key to load projects",
        )
        result = await _request(api_key, "GET", "/projects")
        if result["status"] != "success":
            raise ValueError(
                f"Deepgram could not list projects: {result.get('status_code', result.get('error'))}"
            )
        projects = result["data"].get("projects", [])
        options = [
            {"value": p["project_id"], "label": p.get("name") or p["project_id"]}
            for p in projects
            if p.get("project_id")
        ]
        return {
            "options": filter_options_by_search(options, search),
            "next_page_token": None,
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, DeepgramNodeConfig):
            raise ValueError("Deepgram configuration is required")
        credentials = self.config.credentials
        if not credentials or not credentials.api_key:
            raise ValueError("Connect a Deepgram API key in the Credentials tab")
        config = self.config.config
        action = config.operation
        path = ""
        method = "GET"
        params: Dict[str, Any] = {}
        body = None
        binary = False
        agent = False

        if action == "transcribe_url":
            method, path = "POST", "/listen"
            params = {
                k: getattr(config, k)
                for k in (
                    "model",
                    "language",
                    "detect_language",
                    "smart_format",
                    "punctuate",
                    "utterances",
                    "diarize_model",
                    "sentiment",
                    "topics",
                    "intents",
                    "detect_entities",
                    "tag",
                )
                if getattr(config, k) is not None
            }
            # Summarization is opt-in; absence disables it. The Listen API
            # recommends the explicit v2 version when enabled.
            if config.summarize:
                params["summarize"] = "v2"
            if config.keyterms:
                params["keyterm"] = [
                    term.strip()
                    for term in config.keyterms.splitlines()
                    if term.strip()
                ]
            body = {"url": config.audio_url}
        elif action == "text_to_speech":
            method, path, binary = "POST", "/speak", True
            params = {
                k: getattr(config, k)
                for k in ("model", "encoding", "sample_rate", "speed", "tag")
                if getattr(config, k) is not None
            }
            body = {"text": config.text}
        elif action == "analyze_text":
            method, path = "POST", "/read"
            params = {
                k: getattr(config, k)
                for k in ("language", "sentiment", "topics", "intents")
            }
            if config.summarize:
                params["summarize"] = True
            body = {"text": config.text}
        elif action == "list_projects":
            path = "/projects"
        elif action == "get_project":
            path = f"/projects/{_segment(config.project_id)}"
        elif action == "update_project":
            method, path, body = (
                "PATCH",
                f"/projects/{_segment(config.project_id)}",
                {"name": config.name},
            )
        elif action == "list_project_models":
            path = f"/projects/{_segment(config.project_id)}/models"
            params = {"include_outdated": config.include_outdated}
        elif action == "get_project_model":
            path = f"/projects/{_segment(config.project_id)}/models/{_segment(config.model_id)}"
        elif action == "list_public_models":
            path, params = "/models", {"include_outdated": config.include_outdated}
        elif action == "get_public_model":
            path = f"/models/{_segment(config.model_id)}"
        elif action == "list_think_models":
            path, agent = "/agent/settings/think/models", True
        elif action == "get_usage_breakdown":
            path = f"/projects/{_segment(config.project_id)}/usage/breakdown"
            params = {
                k: getattr(config, k)
                for k in ("start", "end", "endpoint", "tag")
                if getattr(config, k) is not None
            }
        elif action == "list_requests":
            path = f"/projects/{_segment(config.project_id)}/requests"
            params = {
                k: getattr(config, k)
                for k in ("start", "end", "limit", "page", "status")
                if getattr(config, k) is not None
            }
        elif action == "get_request":
            path = f"/projects/{_segment(config.project_id)}/requests/{_segment(config.request_id)}"
        elif action == "list_keys":
            path = f"/projects/{_segment(config.project_id)}/keys"
            params = {"status": config.status} if config.status else {}
        else:
            raise ValueError(f"Unsupported Deepgram operation: {action}")

        result = await _request(
            credentials.api_key,
            method,
            path,
            params=params or None,
            body=body,
            binary=binary,
            agent=agent,
        )
        result["action"] = action
        return result
