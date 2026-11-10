"""LibreTranslate's published translation, detection and service API.

Each operation makes one documented request; no account identity or event API exists.
"""
from __future__ import annotations

import base64
import binascii
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://libretranslate.com"
CREDENTIAL_TYPE = "libretranslate_api_key"


class LibreTranslateAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="LibreTranslate API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://portal.libretranslate.com/",
            "x-credential-instructions": "Paste your LibreTranslate API key from the LibreTranslate portal. Requests go to libretranslate.com. Connecting detects the language of a short sample to check API access; it does not identify your account."})
    credential_type: Literal["libretranslate_api_key"] = Field("libretranslate_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Translate(_Input):
    q: str = Field(..., min_length=1, title="Text to translate")
    source: str = Field("en", description="Source language code, or auto.")
    target: str = Field(..., min_length=1, title="Target language code")
    alternatives: int = Field(0, ge=0, description="Preferred number of alternative translations.")


class TranslateText(_Translate):
    """Translate plain text with a chosen source language."""
    operation: Literal["translate_text"] = Field("translate_text", json_schema_extra={"ui:hidden": True})


class TranslateHTML(_Translate):
    """Translate HTML while preserving markup."""
    operation: Literal["translate_html"] = Field("translate_html", json_schema_extra={"ui:hidden": True})


class TranslateAutoText(_Translate):
    """Detect the source language and translate plain text."""
    operation: Literal["translate_auto_text"] = Field("translate_auto_text", json_schema_extra={"ui:hidden": True})
    source: Literal["auto"] = Field("auto", json_schema_extra={"ui:hidden": True})


class TranslateAutoHTML(_Translate):
    """Detect the source language and translate HTML."""
    operation: Literal["translate_auto_html"] = Field("translate_auto_html", json_schema_extra={"ui:hidden": True})
    source: Literal["auto"] = Field("auto", json_schema_extra={"ui:hidden": True})


class TranslateBatchText(_Translate):
    """Translate a list of plain text strings in one request."""
    operation: Literal["translate_batch_text"] = Field("translate_batch_text", json_schema_extra={"ui:hidden": True})
    q: list[str] = Field(..., min_length=1, title="Texts to translate")


class TranslateBatchHTML(TranslateBatchText):
    """Translate a list of HTML fragments in one request."""
    operation: Literal["translate_batch_html"] = Field("translate_batch_html", json_schema_extra={"ui:hidden": True})


class TranslateAlternatives(_Translate):
    """Request preferred alternative translations for plain text."""
    operation: Literal["translate_alternatives"] = Field("translate_alternatives", json_schema_extra={"ui:hidden": True})
    alternatives: int = Field(3, ge=1)


class DetectLanguage(_Input):
    """Detect candidate languages and their confidence scores."""
    operation: Literal["detect_language"] = Field("detect_language", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, title="Text to detect")


class TranslateFile(_Input):
    """Upload an inline file and return the provider's translated-file URL."""
    operation: Literal["translate_file"] = Field("translate_file", json_schema_extra={"ui:hidden": True})
    file_base64: str = Field(..., min_length=1, max_length=14_000_000, title="File content (base64)",
        json_schema_extra={"contentEncoding": "base64"})
    file_name: str = Field("document.txt", max_length=255, pattern=r"^[^/\\\r\n]+$", description="Original file name with its extension, e.g. document.txt.")
    source: str = Field("auto")
    target: str = Field(..., min_length=1)

    @field_validator("file_base64")
    @classmethod
    def file_content(cls, value):
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Provide base64 encoded file content") from None
        if not raw or len(raw) > 10_000_000:
            raise ValueError("Upload a nonempty file up to 10 MB")
        return value


class SuggestTranslation(_Input):
    """Submit a translation correction when suggestions are enabled."""
    operation: Literal["suggest_translation"] = Field("suggest_translation", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, title="Original text")
    s: str = Field(..., min_length=1, title="Suggested translation")
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)


class ListLanguages(_Input):
    """List supported source languages and translation targets."""
    operation: Literal["list_languages"] = Field("list_languages", json_schema_extra={"ui:hidden": True})


class GetFrontendSettings(_Input):
    """Read server limits, file formats and enabled capabilities."""
    operation: Literal["get_frontend_settings"] = Field("get_frontend_settings", json_schema_extra={"ui:hidden": True})


class GetHealth(_Input):
    """Read the translation server's health status."""
    operation: Literal["get_health"] = Field("get_health", json_schema_extra={"ui:hidden": True})


class CheckConnection(_Input):
    """Check key access with a read-only language detection sample."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


LibreTranslateOperation = Annotated[Union[TranslateText, TranslateHTML, TranslateAutoText,
    TranslateAutoHTML, TranslateBatchText, TranslateBatchHTML, TranslateAlternatives,
    DetectLanguage, TranslateFile, SuggestTranslation, ListLanguages, GetFrontendSettings,
    GetHealth, CheckConnection], Field(discriminator="operation")]


class LibreTranslateConfig(NodeConfig[LibreTranslateOperation, LibreTranslateAPIKeyCredential]):
    model_config = ConfigDict(title="LibreTranslate Node Configuration", hide_input_in_errors=True)


class LibreTranslateNode(WorkflowNode):
    integration_type = "automation-libretranslate"
    connection_evidence = ConnectionEvidence(noun="language detection", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return LibreTranslateConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your LibreTranslate API key")
        op = self.config.config
        key = self.config.credentials.api_key
        action = op.operation
        method, path, kwargs = "POST", "/translate", {}
        if isinstance(op, _Translate):
            body = op.model_dump(exclude={"operation"})
            body.update(format="html" if action.endswith("html") else "text", api_key=key)
            # JSON preserves q arrays, as declared in the official API reference.
            kwargs["json"] = body
        elif action in {"detect_language", "check_connection"}:
            path = "/detect"
            kwargs["data"] = {"q": op.q if action == "detect_language" else "What language is this?", "api_key": key}
        elif action == "translate_file":
            path = "/translate_file"
            kwargs["data"] = {"source": op.source, "target": op.target, "api_key": key}
            kwargs["files"] = {"file": (op.file_name, base64.b64decode(op.file_base64), "application/octet-stream")}
        elif action == "suggest_translation":
            path = "/suggest"
            kwargs["data"] = op.model_dump(exclude={"operation"})
        else:
            method = "GET"
            path = {"list_languages": "/languages", "get_frontend_settings": "/frontend/settings", "get_health": "/health"}[action]
        try:
            async with guarded_async_client(timeout=120.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, **kwargs)
        except Exception:
            raise ValueError("LibreTranslate request could not be completed; inspect before retrying a suggestion") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("LibreTranslate returned a non-JSON response") from None
        if response.status_code >= 300 or isinstance(payload, dict) and payload.get("error"):
            message = payload.get("error") if isinstance(payload, dict) else None
            message = str(message or "LibreTranslate request failed").replace(key, "[redacted]")
            output = {"status": "error", "error": message, "http_status": response.status_code}
        else:
            self._validate_response(action, payload)
            # Keep response fields intact, including batch results, alternatives and detection confidence.
            output = {"status": "success", "data": payload, "http_status": response.status_code,
                "identity_verified": False}
        await self.emit(output)
        return output

    @staticmethod
    def _validate_response(action, payload):
        valid = isinstance(payload, dict)
        if action in {"detect_language", "check_connection"}:
            valid = isinstance(payload, list) and all(isinstance(row, dict) for row in payload)
        elif action == "list_languages":
            valid = isinstance(payload, list) and all(isinstance(row, dict) for row in payload)
        elif action.startswith("translate_") and action != "translate_file":
            valid = valid and isinstance(payload.get("translatedText"), (str, list))
        if not valid:
            raise ValueError("LibreTranslate returned an unexpected response shape")
