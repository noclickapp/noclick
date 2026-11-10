"""Image-Charts image rendering, pinned to the provider's Swagger 6.1.19.

Each action performs one GET: getChart or getChartjs280. Enterprise credentials
sign the exact encoded query (https://documentation.image-charts.com/enterprise/).
The provider has no account identity, list, or webhook registration endpoint.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Annotated, Literal, Union
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ImageChartsAPIKey(BaseModel):
    model_config = ConfigDict(title="Image-Charts API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://documentation.image-charts.com/enterprise/",
            "x-credential-instructions": "Paste your Enterprise account ID and secret key. NoClick signs requests on the server; the secret key is never sent. The connection check renders a small signed QR image to prove the provider accepts the credentials, without claiming an account identity.",
        })
    credential_type: Literal["image_charts_api_key"] = Field("image_charts_api_key", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(..., title="Account ID", min_length=1, max_length=256)
    secret_key: str = Field(..., title="Secret Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("account_id", "secret_key", mode="before")
    @classmethod
    def credential_value(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the credential value without whitespace or a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckConnection(_Input):
    """Render a small signed QR image to check credential acceptance."""
    operation: Literal["check_connection"] = "check_connection"


class _Size(_Input):
    width: int = Field(500, ge=1, le=999)
    height: int = Field(300, ge=1, le=999)


class _Chart(_Size):
    chd: str = Field(..., min_length=3, max_length=100000, title="Chart Data",
        pattern=r"^[at]:[0-9_.\-,|]+$",
        description="Text-encoded numeric series, for example t:10,20,30|15,25,35. Use pipes between series and commas between values. Up to 1,000 series and 10,080 points.")
    chl: str = Field("", max_length=10000, title="Labels", description="Pipe-separated labels; leave empty to use the provider's default labels.")
    chco: str | None = Field(None, max_length=10000, title="Colors", pattern=r"^([0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?,?\|?)+$", description="Hex colors separated by commas (series) or pipes (points).")
    chtt: str | None = Field(None, max_length=10000, title="Title")
    chdl: str | None = Field(None, max_length=10000, title="Legend", description="Pipe-separated series names.")


class RenderLine(_Chart):
    """Render evenly spaced line series."""
    operation: Literal["render_line"] = "render_line"


class RenderBar(_Chart):
    """Render grouped vertical bars."""
    operation: Literal["render_bar"] = "render_bar"


class RenderHorizontalBar(_Chart):
    """Render grouped horizontal bars."""
    operation: Literal["render_horizontal_bar"] = "render_horizontal_bar"


class RenderStackedBar(_Chart):
    """Render stacked vertical bars."""
    operation: Literal["render_stacked_bar"] = "render_stacked_bar"


class RenderHorizontalStackedBar(_Chart):
    """Render stacked horizontal bars."""
    operation: Literal["render_horizontal_stacked_bar"] = "render_horizontal_stacked_bar"


class RenderPie(_Chart):
    """Render a pie chart."""
    operation: Literal["render_pie"] = "render_pie"


class RenderDoughnut(_Chart):
    """Render a doughnut with an optional centre label."""
    operation: Literal["render_doughnut"] = "render_doughnut"
    chli: str | None = Field(None, max_length=3000, title="Inside Label")


class RenderSparkline(_Chart):
    """Render a compact line chart without axes."""
    operation: Literal["render_sparkline"] = "render_sparkline"


class RenderRadar(_Chart):
    """Render a radar chart."""
    operation: Literal["render_radar"] = "render_radar"


class RenderPolarArea(_Chart):
    """Render a polar area chart."""
    operation: Literal["render_polar_area"] = "render_polar_area"


class RenderQR(_Size):
    """Encode text or a URL into a QR image."""
    operation: Literal["render_qr"] = "render_qr"
    chl: str = Field(..., min_length=1, max_length=1500, title="Text or URL")
    chof: Literal[".png", ".svg"] = Field(".png", title="Output Format")
    chld: str = Field("L|4", pattern=r"^[LMQH](?:\|[0-9]+)?$", title="Error Correction and Margin")
    icqrb: str = Field("FFFFFF", pattern=r"^[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$", title="Background Color")
    icqrf: str = Field("000000", pattern=r"^[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$", title="Foreground Color")


class RenderChartJS(_Size):
    """Render a Chart.js 2.8.0 configuration as a PNG image."""
    operation: Literal["render_chartjs"] = "render_chartjs"
    c: str = Field(..., min_length=2, max_length=100000, title="Chart.js Configuration",
        description="JSON or JavaScript object text for Chart.js 2.8.0, with type and data.datasets. NoClick sends the text to Image-Charts without evaluating it.",
        json_schema_extra={"ui:widget": "code_editor"})
    backgroundColor: str | None = Field(None, max_length=100, title="Background Color")


Operation = Annotated[Union[CheckConnection, RenderLine, RenderBar,
    RenderHorizontalBar, RenderStackedBar, RenderHorizontalStackedBar, RenderPie,
    RenderDoughnut, RenderSparkline, RenderRadar, RenderPolarArea, RenderQR,
    RenderChartJS], Field(discriminator="operation")]


class ImageChartsConfig(NodeConfig[Operation, ImageChartsAPIKey]):
    pass


CHART_TYPES = {
    "render_line": "lc", "render_bar": "bvg", "render_horizontal_bar": "bhg",
    "render_stacked_bar": "bvs", "render_horizontal_stacked_bar": "bhs",
    "render_pie": "p", "render_doughnut": "pd", "render_sparkline": "ls",
    "render_radar": "r", "render_polar_area": "pa", "render_qr": "qr",
}


def signed_query(params: dict, credential: ImageChartsAPIKey) -> str:
    query = urlencode({**params, "icac": credential.account_id})
    signature = hmac.new(credential.secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    return query + "&ichm=" + signature


class ImageChartsNode(WorkflowNode):
    integration_type = "automation-image-charts"
    connection_evidence = ConnectionEvidence(operation="check_connection",
        noun="Image-Charts signed image rendering", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return ImageChartsConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Image-Charts account ID and secret key")
        op = self.config.config
        credential = self.config.credentials
        if op.operation == "check_connection":
            path, params = "/chart", {"cht": "qr", "chs": "150x150", "chl": "Hello world", "choe": "UTF-8"}
        else:
            params = op.model_dump(exclude={"operation", "width", "height"}, exclude_none=True)
            if op.operation == "render_chartjs":
                path = "/chart.js/2.8.0"
                params.update(width=op.width, height=op.height, encoding="url")
            else:
                path = "/chart"
                params.update(cht=CHART_TYPES[op.operation], chs=f"{op.width}x{op.height}")
                if op.operation == "render_qr":
                    params["choe"] = "UTF-8"
        query = signed_query(params, credential)
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request("GET", "https://image-charts.com" + path + "?" + query)
        if response.status_code != 200 or response.headers.get("x-ic-error-code"):
            # The documented error headers preserve provider rejection text;
            # never include the request URL, signature or secret in an error.
            message = ": ".join(filter(None, [response.headers.get("x-ic-error-code"), response.headers.get("x-ic-error-validation")]))
            message = message or f"Image-Charts HTTP {response.status_code}"
            for secret in (credential.secret_key, credential.account_id, query.split("&ichm=")[-1]):
                message = message.replace(secret, "[redacted]")
            raise ValueError(message[:2000])
        media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        media = {"application/png": "image/png", "application/gif": "image/gif"}.get(media, media)
        extension = {"image/png": "png", "image/gif": "gif", "image/svg+xml": "svg"}.get(media)
        if extension is None or not response.content or len(response.content) > 20_000_000:
            raise ValueError("Image-Charts returned an empty, oversized or unexpected image response")
        if op.operation == "check_connection":
            output = {"status": "success", "signed_render_accepted": True, "identity_verified": False}
        else:
            output = {"status": "success", "file": BinaryOutput(data=response.content, content_type=media,
                filename=f"image-charts-{op.operation}.{extension}")}
        await self.emit(output)
        return output
