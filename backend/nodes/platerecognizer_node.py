"""Plate Recognizer Cloud operations, pinned to the provider's OpenAPI 1.0.0.

Personal API token authentication; each action makes exactly one contract call.
Recognition accepts public image/video URLs. Lists return one page and retain
provider pagination metadata; downloads use BinaryOutput.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.platerecognizer.com"
TYPE = "platerecognizer_api_token"
DOCS = "https://api.platerecognizer.com/v1/api-reference/"
HIDDEN = {"ui:hidden": True}
Status = Literal["normal", "anomaly", "under_review", "offline", "config_issue", "no_data", "pending_retry"]


class PlaterecognizerApiTokenCredential(BaseModel):
    model_config = ConfigDict(title="Plate Recognizer API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.platerecognizer.com/accounts/tokens/",
            "x-credential-instructions": "Paste your personal API token from Plate Recognizer. Each product needs its own active subscription. Omit the Token prefix."})
    credential_type: Literal["platerecognizer_api_token"] = Field(TYPE, json_schema_extra=HIDDEN)
    api_token: str = Field(..., title="API Token", min_length=1, repr=False,
        description="Personal API token; sent as Authorization: Token to api.platerecognizer.com.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, key=True)
        if len(value) > 4096 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Image(_Config):
    upload_url: str = Field(..., title="Image URL", description="Public HTTPS image URL that Plate Recognizer can download.")
    camera_id: str | None = Field(None, max_length=255, title="Camera ID")
    timestamp: str | None = Field(None, description="UTC ISO 8601 capture time.")

    @field_validator("upload_url")
    @classmethod
    def public_url(cls, value):
        u = urlsplit(value)
        if u.scheme != "https" or not u.hostname or u.username or u.password or len(value) > 8192 or any(c.isspace() for c in value):
            raise ValueError("Supply a public HTTPS media URL without embedded credentials")
        return value

    @field_validator("timestamp")
    @classmethod
    def utc_time(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError("Capture time must include a UTC offset")
        return value


class RecognizePlates(_Image):
    """Read license plates from an image; optional paid vehicle attributes."""
    operation: Literal["recognize_plates"] = Field("recognize_plates", title="Recognize Plates", json_schema_extra=HIDDEN)
    regions: list[str] | None = Field(None, max_length=20, description="Country/state codes such as gb or us-ca.")
    mmc: bool | None = Field(None, description="Enable only with the paid make/model/color feature.")
    direction: bool | None = Field(None, description="Direction prediction also requires mmc=true.")
    engine_config_json: str | None = Field(None, title="Engine Configuration JSON",
        description="Documented engine configuration, for example {\"detection_mode\":\"vehicle\"}.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("engine_config_json")
    @classmethod
    def engine_json(cls, value):
        if value is not None and not isinstance(json.loads(value), dict):
            raise ValueError("Engine configuration must be a JSON object")
        return value


class GetStatistics(_Config):
    """Read account-specific Snapshot Cloud usage and quota."""
    operation: Literal["get_statistics"] = Field("get_statistics", title="Get Snapshot Statistics", json_schema_extra=HIDDEN)


class ExtractText(_Image):
    """Extract VIN, trailer ID, odometer, container, boat or seal identifiers."""
    operation: Literal["extract_text"] = Field("extract_text", title="Extract Text", json_schema_extra=HIDDEN)
    type: Literal["vin", "trailer_id", "odometer", "shipping_container", "boat_reg_number", "seal_ctpat"] = Field(..., title="Recognition Type")


class GetOcrStatistics(_Config):
    """Read account-specific OCR usage and quota."""
    operation: Literal["get_ocr_statistics"] = Field("get_ocr_statistics", title="Get OCR Statistics", json_schema_extra=HIDDEN)


class ListLicenses(_Config):
    """Read one page of licenses for an explicit product type."""
    operation: Literal["list_licenses"] = Field("list_licenses", title="List Product Licenses", json_schema_extra=HIDDEN)
    product_type: str = Field(..., min_length=1, max_length=128, description="Product type from your Plate Recognizer license.")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)
    expiration: str | None = None
    expiration__gte: str | None = None
    expiration__lte: str | None = None
    expiration__isnull: bool | None = None


class GetModels(_Config):
    """Read currently deployed recognition model versions."""
    operation: Literal["get_models"] = Field("get_models", title="Get Production Models", json_schema_extra=HIDDEN)


class ListVisionLicenses(_Config):
    """Read your VisionAlert licenses."""
    operation: Literal["list_vision_licenses"] = Field("list_vision_licenses", title="List VisionAlert Licenses", json_schema_extra=HIDDEN)


class _License(_Config):
    license_id: int = Field(..., ge=1, title="VisionAlert License ID")


class _Page(_License):
    cursor: str | None = Field(None, max_length=8192, description="Opaque cursor from the previous response's next URL. Copy only its cursor query value.")
    page_size: int = Field(50, ge=1, le=200)


class ListCameras(_Page):
    """Read one page of cameras on a VisionAlert license."""
    operation: Literal["list_cameras"] = Field("list_cameras", title="List Cameras", json_schema_extra=HIDDEN)
    status: Status | None = None


class _Logs(_Page):
    start: str | None = Field(None, description="Inclusive YYYY-MM-DD or ISO 8601 timestamp.")
    end: str | None = Field(None, description="Inclusive YYYY-MM-DD or ISO 8601 timestamp.")
    status: Status | None = None
    tag: str | None = Field(None, max_length=255)

    @field_validator("start", "end")
    @classmethod
    def date_filter(cls, value):
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ListCameraLogs(_Logs):
    """Read one page of logs for a selected camera."""
    operation: Literal["list_camera_logs"] = Field("list_camera_logs", title="List Camera Logs", json_schema_extra=HIDDEN)
    serial: str = Field(..., min_length=1, max_length=255, title="Camera Serial")


class ListLicenseLogs(_Logs):
    """Read one page of logs across the selected license."""
    operation: Literal["list_license_logs"] = Field("list_license_logs", title="List License Logs", json_schema_extra=HIDDEN)
    serial: str | None = Field(None, max_length=255, title="Camera Serial Filter")


class DeleteCamera(_License):
    """Delete a VisionAlert camera. This also removes its associated logs."""
    operation: Literal["delete_camera"] = Field("delete_camera", title="Delete Camera", json_schema_extra=HIDDEN)
    serial: str = Field(..., min_length=1, max_length=255, title="Camera Serial")


class GetCameraReference(_License):
    """Get the reference image URL for a selected camera."""
    operation: Literal["get_camera_reference"] = Field("get_camera_reference", title="Get Camera Reference", json_schema_extra=HIDDEN)
    serial: str = Field(..., min_length=1, max_length=255, title="Camera Serial")


class ListAlerts(_Page):
    """Read one page of anomaly alerts on a license."""
    operation: Literal["list_alerts"] = Field("list_alerts", title="List Anomaly Alerts", json_schema_extra=HIDDEN)
    start: str | None = None
    end: str | None = None
    license: str | None = Field(None, title="License Code Filter")
    sent: bool | None = None
    _dates = field_validator("start", "end")(_Logs.date_filter.__func__)


class UploadVideo(_Config):
    """Submit a public video for Stream Cloud processing; results arrive at configured webhooks.

    Requires a Stream Cloud license with video upload and a webhook enabled.
    Videos must be downloadable without encryption, at most 100 MB.
    """
    operation: Literal["upload_video"] = Field("upload_video", title="Submit Video", json_schema_extra=HIDDEN)
    upload_url: str = Field(..., title="Video URL")
    regions: list[str] | None = Field(None, max_length=20)
    mmc: bool | None = None
    camera_id: str | None = Field(None, max_length=255)
    _url = field_validator("upload_url")(_Image.public_url.__func__)


class ListStreamLicenses(_Config):
    """Read your Stream Cloud licenses, optionally filtering by host count."""
    operation: Literal["list_stream_licenses"] = Field("list_stream_licenses", title="List Stream Cloud Licenses", json_schema_extra=HIDDEN)
    hosts: int | None = Field(None, ge=0)


class DownloadStreamConfig(_Config):
    """Download a Stream configuration as a file."""
    operation: Literal["download_stream_config"] = Field("download_stream_config", title="Download Stream Config", json_schema_extra=HIDDEN)
    code: str = Field(..., min_length=1, max_length=128, title="Stream License Code")
    version: str | None = Field(None, max_length=128)


class ListRecentEvents(_Config):
    """Read recent recognition events from the provider's Zapier endpoint."""
    operation: Literal["list_recent_events"] = Field("list_recent_events", title="List Recent Recognitions", json_schema_extra=HIDDEN)


Operation = Annotated[Union[RecognizePlates, GetStatistics, ExtractText, GetOcrStatistics,
    ListLicenses, GetModels, ListVisionLicenses, ListCameras, ListCameraLogs,
    ListLicenseLogs, DeleteCamera, GetCameraReference, ListAlerts, UploadVideo,
    ListStreamLicenses, DownloadStreamConfig, ListRecentEvents], Field(discriminator="operation")]


class PlaterecognizerNodeConfig(NodeConfig[Operation, PlaterecognizerApiTokenCredential]):
    pass


# Each tuple names exactly one operation in the pinned provider contract.
ROUTES = {
    "recognize_plates": ("POST", "/v1/plate-reader/"),
    "get_statistics": ("GET", "/v1/statistics/"),
    "extract_text": ("POST", "/v1/ocr/reader/"),
    "get_ocr_statistics": ("GET", "/v1/ocr/statistics/"),
    "list_licenses": ("GET", "/v1/licenses/{product_type}/"),
    "get_models": ("GET", "/v1/models/"),
    "list_vision_licenses": ("GET", "/v1/vision-alert/licenses/"),
    "list_cameras": ("GET", "/v1/vision-alert/{license_id}/cameras/"),
    "list_camera_logs": ("GET", "/v1/vision-alert/{license_id}/cameras/{serial}/logs/"),
    "list_license_logs": ("GET", "/v1/vision-alert/{license_id}/logs/"),
    "delete_camera": ("DELETE", "/v1/vision-alert/{license_id}/cameras/{serial}/"),
    "get_camera_reference": ("GET", "/v1/vision-alert/{license_id}/cameras/{serial}/reference/"),
    "list_alerts": ("GET", "/v1/vision-alert/{license_id}/alerts/"),
    "upload_video": ("POST", "/v1/stream/video-upload/"),
    "list_stream_licenses": ("GET", "/v1/stream/cloud-licenses/"),
    "download_stream_config": ("GET", "/v1/stream/download-config/{code}/"),
    "list_recent_events": ("GET", "/v1/zapier/"),
}


class PlaterecognizerNode(WorkflowNode):
    integration_type = "automation-platerecognizer"
    credential_provider_labels = {"platerecognizer": "Plate Recognizer"}
    connection_evidence = ConnectionEvidence(operation="list_vision_licenses", noun="VisionAlert licenses", label_keys=("code", "id"))
    edit_examples = ["Recognize license plates in this image", "Extract a VIN", "List camera alerts", "Submit a video for recognition"]

    @classmethod
    def get_config_model(cls):
        return PlaterecognizerNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Plate Recognizer API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            marker = "{" + key + "}"
            if marker in path:
                value = str(values.pop(key))
                if value in {".", ".."} or any(c in value for c in "/\\\r\n"):
                    raise ValueError("Use a single resource identifier")
                path = path.replace(marker, quote(value, safe=""))
        binary = op.operation == "download_stream_config"
        headers = {"Authorization": "Token " + token, "Accept": "text/plain" if binary else "application/json"}
        kwargs = {}
        if method == "POST":
            if "engine_config_json" in values:
                values["config"] = json.loads(values.pop("engine_config_json"))
            kwargs["json"] = values
        elif method == "GET":
            kwargs["params"] = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        # Never retry writes automatically or follow a redirect with the token.
        async with guarded_async_client(timeout=90, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers=headers, **kwargs)
        expected = 201 if method == "POST" else 204 if method == "DELETE" else 200
        if response.status_code != expected:
            try:
                detail = response.json()
                detail = detail.get("detail", detail.get("message", "Plate Recognizer rejected the request")) if isinstance(detail, dict) else "Plate Recognizer rejected the request"
            except ValueError:
                detail = "Plate Recognizer returned an unexpected response"
            return {"status": "error", "http_status": response.status_code,
                "error": str(detail)[:2000].replace(token, "[redacted]"),
                "write_outcome_unknown": method != "GET" and response.status_code >= 500}
        if method == "DELETE":
            return {"status": "success", "http_status": 204, "deletion_acknowledged": True,
                "license_id": op.license_id, "serial": op.serial}
        if len(response.content) > 20_000_000:
            raise ValueError("Plate Recognizer response exceeds 20 MB")
        if binary:
            return {"status": "success", "file": BinaryOutput(response.content, "text/plain", "stream-config.ini")}
        mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if mime != "application/json":
            raise ValueError("Expected JSON from Plate Recognizer")
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Expected a Plate Recognizer object or list")
        # Keep the documented envelopes and recognition variants intact.
        return {"status": "success", "http_status": response.status_code, "data": payload,
            **({"processing_submitted": True} if op.operation == "upload_video" else {})}
