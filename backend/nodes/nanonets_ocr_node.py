"""Nanonets API v2 OCR and image classification, using a pasted API key."""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.media_resolver import resolve_media_input
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.nanonets.com/api/v2"


class NanonetsOcrAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Nanonets OCR API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.nanonets.com/#/keys",
        "x-credential-instructions": "Copy your API key from Nanonets → API Keys. Paste the key alone. It grants full account access; NoClick sends it as the Basic username with an empty password. Connection verification reads your classification models without changing them.",
    })
    credential_type: Literal["nanonets_ocr_api_key"] = Field("nanonets_ocr_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value) or ":" in value:
            raise ValueError("Paste the API key alone, without Basic, whitespace or a colon")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Model(_Operation):
    model_id: str = Field(..., title="Model ID", min_length=1, max_length=200, description="Copy the model ID from Nanonets model settings.")

    @field_validator("model_id")
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a Nanonets model ID, without a URL or path")
        return value


class _Urls(_Model):
    urls: list[str] = Field(..., min_length=1, max_length=100, title="Image URLs", description="Public PNG, JPEG or PDF URLs. Each URL is sent as a repeated urls form field.")

    @field_validator("urls")
    @classmethod
    def public_urls(cls, values):
        for value in values:
            try:
                parsed = urlsplit(value)
                if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or len(value) > 8192 or any(c.isspace() for c in value):
                    raise ValueError()
            except ValueError:
                raise ValueError("Use complete public HTTP or HTTPS image URLs") from None
        return values


class _File(_Model):
    file_reference: str | None = Field(None, min_length=1, title="File Reference", description="A PNG, JPEG or PDF workflow file reference, public URL or data URI. Supply this or inline base64 bytes.")

    file_base64: str | None = Field(None, title="Inline File Base64", description="Alternatively, provide base64 file bytes instead of an upload or file reference.", json_schema_extra={"format": "byte"})
    mime_type: Literal["application/pdf", "image/png", "image/jpeg"] = Field("application/pdf", title="Inline File Type")
    filename: str = Field("document.pdf", max_length=255, title="Inline Filename")

    @model_validator(mode="after")
    def one_file(self):
        if bool(self.file_reference) == bool(self.file_base64):
            raise ValueError("Provide exactly one uploaded file/reference or inline base64 file")
        return self


class GetModel(_Model):
    """Read OCR model categories and training state."""
    operation: Literal["get_model"] = "get_model"


class UploadTrainingUrls(_Urls):
    """Add image URLs to an OCR model's training set."""
    operation: Literal["upload_training_urls"] = "upload_training_urls"


class UploadTrainingFile(_File):
    """Upload one OCR training image with matching filename metadata."""
    operation: Literal["upload_training_file"] = "upload_training_file"


class TrainModel(_Model):
    """Start OCR model training; completion is checked with Get Model."""
    operation: Literal["train_model"] = "train_model"


class ListPredictionFiles(_Model):
    """Read one documented day batch of moderated and unmoderated predictions."""
    operation: Literal["list_prediction_files"] = "list_prediction_files"
    start_day_interval: int = Field(..., title="Start Day Interval", description="Number of days of prediction history to request.")
    current_batch_day: int = Field(..., title="Current Batch Day", description="The batch day index, as required by the API. Adjust explicitly to read another batch.")


class GetPredictionFile(_Model):
    """Get extracted fields and tables for a prediction file ID."""
    operation: Literal["get_prediction_file"] = "get_prediction_file"
    file_id: str = Field(..., min_length=1, max_length=200, title="Prediction File ID")
    _id = field_validator("file_id")(_Model.identifier.__func__)


class PredictUrls(_Urls):
    """Extract text, fields and tables from public image URLs."""
    operation: Literal["predict_urls"] = "predict_urls"


class PredictUrlsAsync(_Urls):
    """Queue URL predictions and return file IDs for later retrieval."""
    operation: Literal["predict_urls_async"] = "predict_urls_async"


class PredictFile(_File):
    """Extract text, fields and tables from one uploaded file."""
    operation: Literal["predict_file"] = "predict_file"


class PredictFileAsync(_File):
    """Queue an uploaded file prediction; retrieve results by returned file ID."""
    operation: Literal["predict_file_async"] = "predict_file_async"


class ListClassificationModels(_Operation):
    """Read the connected account's classification models."""
    operation: Literal["list_classification_models"] = "list_classification_models"


class GetClassificationModel(_Model):
    """Read classification model details by ID."""
    operation: Literal["get_classification_model"] = "get_classification_model"


class UploadClassificationTrainingUrls(_Urls):
    """Add labelled URLs to a classification model's training set."""
    operation: Literal["upload_classification_training_urls"] = "upload_classification_training_urls"
    category: str = Field(..., min_length=1, max_length=500, title="Category")


class UploadClassificationTrainingFile(_File):
    """Add one labelled file to a classification model's training set."""
    operation: Literal["upload_classification_training_file"] = "upload_classification_training_file"
    category: str = Field(..., min_length=1, max_length=500, title="Category")


class TrainClassificationModel(_Model):
    """Start classification model training."""
    operation: Literal["train_classification_model"] = "train_classification_model"


class ClassifyUrls(_Urls):
    """Classify public image URLs with a trained classification model."""
    operation: Literal["classify_urls"] = "classify_urls"


class ClassifyFile(_File):
    """Classify one uploaded image with a trained classification model."""
    operation: Literal["classify_file"] = "classify_file"


NanonetsOcrOperation = Annotated[Union[
    GetModel, UploadTrainingUrls, UploadTrainingFile, TrainModel, ListPredictionFiles,
    GetPredictionFile, PredictUrls, PredictUrlsAsync, PredictFile, PredictFileAsync,
    ListClassificationModels, GetClassificationModel, UploadClassificationTrainingUrls,
    UploadClassificationTrainingFile, TrainClassificationModel, ClassifyUrls, ClassifyFile,
], Field(discriminator="operation")]


class NanonetsOcrConfig(NodeConfig[NanonetsOcrOperation, NanonetsOcrAPIKeyCredential]):
    pass


# Each entry names exactly one published API operation, including async slash routes.
ROUTES = {
    "get_model": ("GET", "/OCR/Model/{model_id}"),
    "upload_training_urls": ("POST", "/OCR/Model/{model_id}/UploadUrls"),
    "upload_training_file": ("POST", "/OCR/Model/{model_id}/UploadFile"),
    "train_model": ("POST", "/OCR/Model/{model_id}/Train"),
    "list_prediction_files": ("GET", "/Inferences/Model/{model_id}/ImageLevelInferences"),
    "get_prediction_file": ("GET", "/Inferences/Model/{model_id}/ImageLevelInferences/{file_id}"),
    "predict_urls": ("POST", "/OCR/Model/{model_id}/LabelUrls"),
    "predict_urls_async": ("POST", "/OCR/Model/{model_id}/LabelUrls/"),
    "predict_file": ("POST", "/OCR/Model/{model_id}/LabelFile"),
    "predict_file_async": ("POST", "/OCR/Model/{model_id}/LabelFile/"),
    "list_classification_models": ("GET", "/ImageCategorization/Models"),
    "get_classification_model": ("GET", "/ImageCategorization/Model"),
    "upload_classification_training_urls": ("POST", "/ImageCategorization/UploadUrls"),
    "upload_classification_training_file": ("POST", "/ImageCategorization/UploadFile"),
    "train_classification_model": ("POST", "/ImageCategorization/Train"),
    "classify_urls": ("POST", "/ImageCategorization/LabelUrls"),
    "classify_file": ("POST", "/ImageCategorization/LabelFile"),
}


class NanonetsOcrNode(WorkflowNode):
    integration_type = "automation-nanonets-ocr"
    connection_evidence = ConnectionEvidence(noun="classification models", operation="list_classification_models", label_keys=("name", "model_id", "id"))

    @classmethod
    def get_config_model(cls):
        return NanonetsOcrConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Nanonets OCR API key")
        method, route = ROUTES[config.operation]
        route = route.format(**{k: quote(v, safe="") for k, v in config.model_dump().items() if k in {"model_id", "file_id"}})
        params, data, files = {}, {}, None
        if isinstance(config, ListPredictionFiles):
            params = {"start_day_interval": config.start_day_interval, "current_batch_day": config.current_batch_day}
        if config.operation.endswith("_async"):
            params["async"] = "true"
        if isinstance(config, GetClassificationModel):
            params["id"] = config.model_id
        if isinstance(config, TrainClassificationModel):
            params["modelId"] = config.model_id
        if isinstance(config, (_Urls, _File)):
            if route.startswith("/ImageCategorization/"):
                data["modelId"] = config.model_id
            if hasattr(config, "category"):
                data["category"] = config.category
            if isinstance(config, _Urls):
                data["urls"] = config.urls
            else:
                media = await resolve_media_input(config.file_reference or config.file_base64, max_bytes=20 * 1024 * 1024, default_mime=config.mime_type, workflow_id=self.workflow_id, owner_id=self.user_id)
                filename = media.filename if config.file_reference else config.filename
                if media.mime_type not in {"image/png", "image/jpeg", "application/pdf"}:
                    raise ValueError("Nanonets accepts PNG, JPEG or PDF files")
                if not re.fullmatch(r"[^/\\\r\n\x00]{1,255}", filename):
                    raise ValueError("Use a simple filename without path separators")
                files = {"file": (filename, media.data, media.mime_type)}
                if isinstance(config, UploadTrainingFile):
                    data["data"] = json.dumps([{"filename": filename}])
        async with guarded_async_client(timeout=httpx.Timeout(120), follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + route, params=params,
                auth=httpx.BasicAuth(credential.api_key, ""), data=data or None, files=files)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for connection evidence, but never echo the key.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Nanonets HTTP {response.status_code}: {message}")
        if response.status_code == 202 and not response.content:
            return {"data": None, "http_status": 202, "operation": config.operation, "partial": True}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Nanonets returned a non-JSON response; inspect the request before retrying") from None
        if not isinstance(payload, dict):
            raise ValueError("Nanonets returned an unexpected response envelope")
        if payload.get("error") or payload.get("errors") or payload.get("status") in ("error", "failed"):
            message = json.dumps(payload)[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Nanonets rejected the request: {message}")
        output = {"data": payload, "http_status": response.status_code, "operation": config.operation}
        if response.status_code == 202:
            output["partial"] = True
        if isinstance(config, ListClassificationModels):
            if isinstance(payload.get("model_id"), str):
                output["items"] = [payload]
            elif isinstance(payload.get("models"), list):
                output["items"] = payload["models"]
        return output
