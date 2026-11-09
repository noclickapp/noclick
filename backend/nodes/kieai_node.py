"""Kie.ai API-key operations against its published v1 contract."""
from __future__ import annotations

import json
import math
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.kie.ai"


class KieaiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Kieai API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://kie.ai/api-key",
            "x-credential-instructions": "Paste your Kie.ai API key. NoClick checks your account credit balance to verify that the key is accepted. Chat and transcription requests consume your Kie.ai credits.",
        })
    credential_type: Literal["kieai_api_key"] = Field("kieai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetCredits(Operation):
    """Read the account's remaining credits."""
    operation: Literal["get_account_credits"] = "get_account_credits"


class GetTask(Operation):
    """Read one task's current state and any completed result; no polling."""
    operation: Literal["get_task"] = "get_task"
    task_id: str = Field(..., min_length=1, max_length=256)


class TranscribeAudio(Operation):
    """Queue Nemotron transcription or translation and return its task ID."""
    operation: Literal["transcribe_audio"] = "transcribe_audio"
    audio_url: str = Field(..., json_schema_extra={"format": "uri"})
    timestamps: bool = False
    target_language: Literal["en", "zh", "ja", "ko", "fr", "de", "es", "pt", "it", "ru", "nl", "pl", "cs", "sk", "hi", "bg", "hr", "da", "et", "fi", "hu", "lv", "lt", "ro", "sl", "sv", "th", "uk", "ar", "el", "he", "mt"] | None = None
    callback_url: str | None = Field(None, json_schema_extra={"format": "uri"})

    @model_validator(mode="after")
    def translation(self):
        if self.timestamps and self.target_language:
            raise ValueError("Timestamps cannot be combined with translation")
        return self


class CreateVoice(Operation):
    """Register an Omni voice configuration; this does not generate audio."""
    operation: Literal["create_voice"] = "create_voice"
    audio_id: str = Field(..., min_length=1, description="Preset voice ID, for example achernar.")
    name: str = Field(..., min_length=1, max_length=210)
    voice_description: str | None = Field(None, max_length=20000)
    example_dialogue: str | None = Field(None, max_length=120)


class CreateCharacter(Operation):
    """Create an Omni character from one or two reference images."""
    operation: Literal["create_character"] = "create_character"
    descriptions: str = Field(..., min_length=1)
    image_urls: list[str] = Field(..., min_length=1, max_length=2)
    audio_ids: list[str] | None = None
    character_name: str | None = None


class GetDownloadURL(Operation):
    """Get a generated file's download URL, valid for 20 minutes."""
    operation: Literal["get_download_url"] = "get_download_url"
    url: str = Field(..., json_schema_extra={"format": "uri"})


class Prompt(Operation):
    prompt: str = Field(..., min_length=1, description="Text to send as one user message.")


class GPT52Chat(Prompt):
    """Generate a synchronous answer using gpt 5 2."""
    operation: Literal["chat_gpt_5_2"] = "chat_gpt_5_2"


class Gemini38Chat(Prompt):
    """Generate a synchronous answer using gemini 3 8 flash."""
    operation: Literal["chat_gemini_3_8_flash"] = "chat_gemini_3_8_flash"


class Gemini3Chat(Prompt):
    """Generate a synchronous answer using gemini 3 pro."""
    operation: Literal["chat_gemini_3_pro"] = "chat_gemini_3_pro"


class Gemini31Chat(Prompt):
    """Generate a synchronous answer using gemini 3 1 pro."""
    operation: Literal["chat_gemini_3_1_pro"] = "chat_gemini_3_1_pro"


class GeminiArgonChat(Prompt):
    """Generate a synchronous answer using gemini 4 argon."""
    operation: Literal["chat_gemini_4_argon"] = "chat_gemini_4_argon"


class Gemini36Chat(Prompt):
    """Generate a synchronous answer using gemini 3 6 flash."""
    operation: Literal["chat_gemini_3_6_flash"] = "chat_gemini_3_6_flash"


class ClaudeChat(Prompt):
    """Generate a synchronous Claude Sonnet 4.6 answer."""
    operation: Literal["chat_claude_sonnet_4_6"] = "chat_claude_sonnet_4_6"
    max_tokens: int = Field(4096, ge=1)


class KimiResponse(Prompt):
    """Generate a synchronous Kimi K3 Responses API answer."""
    operation: Literal["create_kimi_response"] = "create_kimi_response"
    model: Literal["kimi-k3"] = "kimi-k3"


KieaiOperation = Annotated[Union[GetCredits, GetTask, TranscribeAudio, CreateVoice, CreateCharacter, GetDownloadURL, GPT52Chat, Gemini38Chat, Gemini3Chat, Gemini31Chat, GeminiArgonChat, Gemini36Chat, ClaudeChat, KimiResponse], Field(discriminator="operation")]


class KieaiConfig(NodeConfig[KieaiOperation, KieaiAPIKeyCredential]):
    pass


CHAT_PATHS = {'chat_gpt_5_2': '/gpt-5-2/v1/chat/completions', 'chat_gemini_3_8_flash': '/gemini-3-8-flash-openai/v1/chat/completions', 'chat_gemini_3_pro': '/gemini-3-pro/v1/chat/completions', 'chat_gemini_3_1_pro': '/gemini-3.1-pro/v1/chat/completions', 'chat_gemini_4_argon': '/gemini-4-argon-openai/v1/chat/completions', 'chat_gemini_3_6_flash': '/gemini-3-6-flash-openai/v1/chat/completions'}


def _public_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public HTTP or HTTPS URL without credentials")
    return value


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class KieaiNode(WorkflowNode):
    integration_type = "automation-kieai"
    connection_evidence = ConnectionEvidence(
        operation="get_account_credits", noun="Kie.ai account credit balance", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return KieaiConfig

    @staticmethod
    def _request_parts(op):
        action = op.operation
        if isinstance(op, GetCredits):
            return "GET", "/api/v1/chat/credit", None, None
        if isinstance(op, GetTask):
            return "GET", "/api/v1/jobs/recordInfo", {"taskId": op.task_id}, None
        if isinstance(op, TranscribeAudio):
            body = {"model": "nvidia/nemotron-3-5-transcribe", "input": {
                "audio_url": _public_url(op.audio_url), "timestamps": op.timestamps}}
            if op.target_language is not None:
                body["input"]["target_language"] = op.target_language
            if op.callback_url is not None:
                body["callBackUrl"] = _public_url(op.callback_url)
            return "POST", "/api/v1/jobs/createTask", None, body
        if isinstance(op, CreateVoice):
            return "POST", "/api/v1/omni/audio/create", None, op.model_dump(exclude={"operation"}, exclude_none=True)
        if isinstance(op, CreateCharacter):
            for url in op.image_urls:
                _public_url(url)
            return "POST", "/api/v1/omni/character/create", None, op.model_dump(exclude={"operation"}, exclude_none=True)
        if isinstance(op, GetDownloadURL):
            return "POST", "/api/v1/common/download-url", None, {"url": _public_url(op.url)}
        if action in CHAT_PATHS:
            body = {"messages": [{"role": "user", "content": [{"type": "text", "text": op.prompt}]}]}
            if not isinstance(op, GPT52Chat):
                body["stream"] = False
            return "POST", CHAT_PATHS[action], None, body
        if isinstance(op, ClaudeChat):
            return "POST", "/claude/v1/messages", None, {
                "model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": op.prompt}],
                "stream": False, "max_tokens": op.max_tokens}
        if isinstance(op, KimiResponse):
            return "POST", "/openai/v1/responses", None, {"model": op.model, "input": op.prompt, "stream": False}
        raise ValueError("Unknown Kie.ai operation")

    @staticmethod
    def _result(op, payload):
        if not isinstance(payload, dict):
            raise ValueError("Kie.ai returned an unexpected JSON response")
        if payload.get("error") or payload.get("success") is False:
            raise ValueError(str(payload.get("msg") or payload.get("error")))
        if "code" in payload and payload["code"] != 200:
            raise ValueError(str(payload.get("msg") or "Kie.ai rejected the request"))
        if isinstance(op, Prompt):
            if op.operation in CHAT_PATHS and not isinstance(payload.get("choices"), list):
                raise ValueError("Kie.ai chat response is missing choices")
            if isinstance(op, ClaudeChat) and not isinstance(payload.get("content"), list):
                raise ValueError("Kie.ai Claude response is missing content")
            if isinstance(op, KimiResponse) and not isinstance(payload.get("output"), list):
                raise ValueError("Kie.ai Kimi response is missing output")
            return {"status": "success", "data": payload}
        if payload.get("code") != 200 or "data" not in payload:
            raise ValueError("Kie.ai response is missing its success envelope")
        data = payload["data"]
        if isinstance(op, GetCredits):
            if isinstance(data, bool) or not isinstance(data, (int, float)) or not math.isfinite(data):
                raise ValueError("Kie.ai account credit balance is invalid")
            return {"status": "success", "credits": data}
        if isinstance(op, GetDownloadURL):
            if not isinstance(data, str):
                raise ValueError("Kie.ai response is missing the download URL")
            return {"status": "success", "download_url": _public_url(data)}
        if not isinstance(data, dict):
            raise ValueError("Kie.ai response data must be an object")
        key = "taskId" if isinstance(op, (GetTask, TranscribeAudio)) else "audioId" if isinstance(op, CreateVoice) else "characterId"
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError("Kie.ai response is missing " + key)
        result = {"status": "success", "data": data}
        if isinstance(op, TranscribeAudio):
            result["task_id"] = data["taskId"]
            result["completed"] = False
        if isinstance(op, GetTask):
            state = data.get("state")
            if state not in {"waiting", "queuing", "generating", "success", "fail"}:
                raise ValueError("Kie.ai returned an unknown task state")
            result["completed"] = state in {"success", "fail"}
            if state == "fail":
                result.update(status="error", message=data.get("failMsg") or "Kie.ai task failed")
            if state == "success" and data.get("resultJson"):
                result["result"] = json.loads(data["resultJson"])
        return result

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Kie.ai API key")
        credential = self.config.credentials
        op = self.config.config
        method, path, params, body = self._request_parts(op)
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
            if response.status_code < 200 or response.status_code >= 300:
                try:
                    payload = response.json()
                    message = payload.get("msg") or payload.get("error") or "Kie.ai rejected the request"
                except (ValueError, AttributeError):
                    message = "Kie.ai rejected the request"
                return _redact({"status": "error", "http_status": response.status_code, "message": str(message)}, credential.api_key)
            result = self._result(op, response.json())
        except httpx.RequestError:
            return {"status": "error", "message": "Kie.ai request could not be completed; inspect the provider before retrying a write"}
        except (ValueError, TypeError) as exc:
            return _redact({"status": "error", "message": str(exc)}, credential.api_key)
        return _redact(result, credential.api_key)
