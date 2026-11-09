"""QuickChart rendering and validation, pinned to the published OpenAPI 1.0.0.

Images and ZIP files use the shared binary output resolver. Authentication
uses a Bearer key, except saved charts which must retain the key in their body.
https://quickchart.io/documentation/authentication/
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class QuickChartAPIKey(BaseModel):
    model_config = ConfigDict(title="QuickChart API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://quickchart.io/documentation/authentication/",
            "x-credential-instructions": "Paste your QuickChart API key. The connection check renders a small QR code and checks QuickChart's verified-key response header. QuickChart has no account identity endpoint.",
        })
    credential_type: Literal["quickchart_api_key"] = Field("quickchart_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckConnection(_Input):
    """Check key recognition using a non-persistent QR render."""
    operation: Literal["check_connection"] = "check_connection"


class _Chart(_Input):
    chart: dict | str = Field(..., description="Chart.js configuration object or JavaScript object string.")
    width: int = Field(500, ge=1, le=3000)
    height: int = Field(300, ge=1, le=3000)
    devicePixelRatio: float = Field(2, gt=0, le=2, title="Device Pixel Ratio")
    backgroundColor: str = Field("transparent", title="Background Color")
    version: Literal["2", "3", "4"] = "2"
    format: Literal["png", "jpg", "jpeg", "webp", "svg", "pdf", "base64"] = "png"


class RenderChart(_Chart):
    """Render a Chart.js chart as an image or PDF."""
    operation: Literal["render_chart"] = "render_chart"


class CreateChartURL(_Chart):
    """Save a chart and return a reusable short URL; the saved chart retains the API key."""
    operation: Literal["create_chart_url"] = "create_chart_url"


class ValidateChart(_Chart):
    """Validate a chart and return structured errors and warnings."""
    operation: Literal["validate_chart"] = "validate_chart"


class RenderWordCloud(_Input):
    """Render a word cloud from text or a weighted word list."""
    operation: Literal["render_word_cloud"] = "render_word_cloud"
    text: str = Field(..., min_length=1)
    format: Literal["png", "svg"] = "png"
    width: int = Field(600, ge=1)
    height: int = Field(600, ge=1)
    backgroundColor: str = "transparent"
    fontFamily: str = "serif"
    fontScale: float = 25
    scale: Literal["linear", "sqrt", "log"] = "linear"
    rotation: float = 20
    maxNumWords: int = Field(200, ge=1)
    minWordLength: int = Field(1, ge=1)
    colors: list[str] | None = None
    removeStopwords: bool = False
    cleanWords: bool = True
    language: str = "en"
    useWordList: bool = False


class RenderTable(_Input):
    """Render table columns and rows to PNG."""
    operation: Literal["render_table"] = "render_table"
    data: dict | str = Field(..., description="Table definition with columns and dataSource, optionally title.")
    options: dict | str | None = Field(None, description="Table rendering options.")


class WatermarkImage(_Input):
    """Overlay a watermark on a publicly accessible image."""
    operation: Literal["watermark_image"] = "watermark_image"
    mainImageUrl: str = Field(..., min_length=1, title="Main Image URL", json_schema_extra={"format": "uri"})
    markImageUrl: str = Field(..., min_length=1, title="Watermark Image URL", json_schema_extra={"format": "uri"})
    opacity: float = Field(1, ge=0, le=1)
    position: Literal["topLeft", "topMiddle", "topRight", "middleLeft", "center", "middleRight", "bottomLeft", "bottomMiddle", "bottomRight"] = "bottomRight"
    margin: float | None = None
    markRatio: float | None = None
    imageWidth: int | None = None
    imageHeight: int | None = None
    markWidth: int | None = None
    markHeight: int | None = None


class RenderDiagram(_Input):
    """Render a Graphviz DOT diagram."""
    operation: Literal["render_diagram"] = "render_diagram"
    graph: str = Field(..., min_length=1, description="Graphviz DOT source, for example graph{a--b}.")
    format: Literal["png", "svg"] = "png"
    engine: Literal["dot", "neato", "fdp", "sfdp", "twopi", "circo", "osage", "patchwork"] = "dot"
    width: int | None = None
    height: int | None = None


class _QR(_Input):
    text: str = Field(..., min_length=1, description="Text or URL to encode.")
    format: Literal["png", "svg", "jpg", "jpeg", "base64"] = "png"
    size: int = Field(150, ge=1, le=3000)
    margin: int = 4
    ecLevel: Literal["L", "M", "Q", "H"] | None = None
    dark: str | None = None
    light: str | None = None
    dotStyle: Literal["square", "dot", "dots", "round", "circle", "rounded"] | None = None
    centerImageUrl: str | None = None
    centerImageSizeRatio: float | None = Field(None, ge=0, le=1)
    caption: str | None = None
    captionFontFamily: str | None = None
    captionFontSize: int | None = None
    captionFontColor: str | None = None


class RenderQR(_QR):
    """Render a customized QR code."""
    operation: Literal["render_qr"] = "render_qr"


class ValidateQR(_QR):
    """Validate a QR request and return structured errors and warnings."""
    operation: Literal["validate_qr"] = "validate_qr"


class BuildQRURL(_QR):
    """Build one public QR image URL without rendering it."""
    operation: Literal["build_qr_url"] = "build_qr_url"


class BuildQRURLs(_Input):
    """Build QR image URLs in input order without rendering them."""
    operation: Literal["build_qr_urls"] = "build_qr_urls"
    qrCodes: list[_QR] = Field(..., min_length=1, max_length=1000, title="QR Codes")


class _BatchQR(_QR):
    format: Literal["png", "svg", "jpg", "jpeg"] = "png"
    filename: str | None = None


class BatchQR(_Input):
    """Render up to 1000 QR codes into a ZIP archive."""
    operation: Literal["batch_qr"] = "batch_qr"
    qrCodes: list[_BatchQR] = Field(..., min_length=1, max_length=1000, title="QR Codes")


class RenderBarcode(_Input):
    """Render a barcode such as code128, ean13 or datamatrix."""
    operation: Literal["render_barcode"] = "render_barcode"
    type: str = Field(..., min_length=1, title="Barcode Type")
    text: str = Field(..., min_length=1)
    format: Literal["png", "svg"] = "png"
    width: int | None = None
    height: int | None = None
    scale: int = 1
    includeText: bool = False
    useMillimeters: bool = False
    rotate: Literal["N", "R", "L", "I"] = "N"


class ReadQR(_Input):
    """Decode a QR code from a public image URL."""
    operation: Literal["read_qr"] = "read_qr"
    url: str = Field(..., min_length=1, title="QR Image URL", json_schema_extra={"format": "uri"})


class GenerateChartConfig(_Input):
    """Generate a Chart.js configuration and saved URLs from a description."""
    operation: Literal["generate_chart_config"] = "generate_chart_config"
    description: str = Field(..., min_length=1, max_length=512)
    width: int = Field(500, ge=1)
    height: int = Field(300, ge=1)
    backgroundColor: str = "transparent"


Operation = Annotated[Union[CheckConnection, RenderChart, CreateChartURL,
    ValidateChart, RenderWordCloud, RenderTable, WatermarkImage, RenderDiagram,
    RenderQR, ValidateQR, BuildQRURL, BuildQRURLs, BatchQR, RenderBarcode,
    ReadQR, GenerateChartConfig], Field(discriminator="operation")]


class QuickChartConfig(NodeConfig[Operation, QuickChartAPIKey]):
    pass


# Each operation makes exactly one request to a published contract operation.
ROUTES = {
    "check_connection": ("GET", "/qr"),
    "render_chart": ("POST", "/chart"),
    "create_chart_url": ("POST", "/chart/create"),
    "validate_chart": ("POST", "/api/validate-chart"),
    "render_word_cloud": ("POST", "/wordcloud"),
    "render_table": ("POST", "/v1/table"),
    "watermark_image": ("POST", "/watermark"),
    "render_diagram": ("POST", "/graphviz"),
    "render_qr": ("POST", "/qr"),
    "validate_qr": ("POST", "/api/validate-qr"),
    "build_qr_url": ("POST", "/qr-url"),
    "build_qr_urls": ("POST", "/qr-urls"),
    "batch_qr": ("POST", "/qr/batch"),
    "render_barcode": ("POST", "/barcode"),
    "read_qr": ("GET", "/qr-read"),
    "generate_chart_config": ("POST", "/natural/config"),
}
JSON_OPERATIONS = frozenset({"create_chart_url", "validate_chart", "validate_qr",
    "build_qr_url", "build_qr_urls", "read_qr", "generate_chart_config"})


class QuickChartNode(WorkflowNode):
    integration_type = "automation-quickchart"
    connection_evidence = ConnectionEvidence(operation="check_connection",
        noun="QuickChart API key recognition", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return QuickChartConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a QuickChart API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        if op.operation == "check_connection":
            body = {"text": "Hello world", "size": 150}
        if op.operation == "create_chart_url":
            body["key"] = key  # Required for the saved chart to retain paid authentication.
        headers = {"Authorization": "Bearer " + key}
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://quickchart.io" + path,
                headers=headers, **({"params": body} if method == "GET" else {"json": body}))
        media = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not 200 <= response.status_code < 300:
            message = response.headers.get("x-quickchart-error")
            if not message and media == "application/json":
                payload = response.json()
                message = payload.get("error") if isinstance(payload, dict) else None
            if not message and media.startswith("text/"):
                message = response.text
            # Do not expose the body of a rendered error image or a request URL.
            message = str(message or f"QuickChart HTTP {response.status_code}").replace(key, "[redacted]")[:1000]
            raise ValueError(message)
        verified = response.headers.get("x-quickchart-verified-key") == "1"
        if op.operation == "check_connection":
            if not verified:
                raise ValueError("QuickChart did not return X-quickchart-verified-key: 1; API key recognition is unverified")
            output = {"status": "success", "key_verified": True, "identity_verified": False}
        elif op.operation in JSON_OPERATIONS:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("QuickChart returned an unexpected JSON response")
            if payload.get("error") or (payload.get("success") is False and op.operation not in {"validate_chart", "validate_qr"}):
                raise ValueError(str(payload.get("error") or payload.get("errors") or "QuickChart reported failure").replace(key, "[redacted]"))
            output = {"status": "success", "data": payload}
        else:
            if media not in {"image/png", "image/jpeg", "image/svg+xml", "image/webp", "application/pdf", "application/zip", "text/plain"}:
                raise ValueError("QuickChart returned an unexpected media type")
            data = response.content
            if media == "text/plain":
                try:
                    data = base64.b64decode(data, validate=True)
                except ValueError:
                    raise ValueError("QuickChart returned invalid base64 image data") from None
                media = "image/png"
            extension = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg",
                "image/webp": "webp", "application/pdf": "pdf", "application/zip": "zip"}[media]
            output = {"status": "success", "file": BinaryOutput(data=data, content_type=media,
                filename=f"quickchart-{op.operation}.{extension}")}
        await self.emit(output)
        return output
