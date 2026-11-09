"""TomTom Maps v1 display contract: ten read-only operations.

Copyrights v1 is withdrawn per TomTom's documentation; retained only to expose
this pinned legacy contract. Use tiles for connection reachability.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from xml.etree import ElementTree
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class TomTomAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Tomtom API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.tomtom.com/user/me/apps",
        "x-credential-instructions": "Paste your TomTom application API key with Map Display access. NoClick reads a map tile to check key reachability; it cannot establish account identity. Map requests may consume your TomTom allowance.",
    })
    credential_type: Literal["tomtom_api_key"] = Field("tomtom_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetWorldCopyrights(_Input):
    """Read legacy whole-world copyrights (withdrawn by TomTom)."""
    operation: Literal["get_world_copyrights"] = "get_world_copyrights"


class GetCopyrightCaption(_Input):
    """Read the legacy copyright caption (withdrawn by TomTom)."""
    operation: Literal["get_copyright_caption"] = "get_copyright_caption"


class GetAreaCopyrights(_Input):
    """Read legacy bounding-box copyrights (withdrawn by TomTom)."""
    operation: Literal["get_area_copyrights"] = "get_area_copyrights"
    minLon: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    minLat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    maxLon: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    maxLat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)

    @model_validator(mode="after")
    def bounds(self):
        if self.minLon >= self.maxLon or self.minLat >= self.maxLat:
            raise ValueError("Minimum coordinates must precede maximum coordinates")
        return self


class _Tile(_Input):
    zoom: int = Field(0, ge=0, le=22)
    X: int = Field(0, ge=0)
    Y: int = Field(0, ge=0)

    @model_validator(mode="after")
    def grid(self):
        if self.X >= 2 ** self.zoom or self.Y >= 2 ** self.zoom:
            raise ValueError("Tile coordinates must be below 2 to the power of zoom")
        return self


class GetTileCopyrights(_Tile):
    """Read legacy tile copyrights (withdrawn by TomTom)."""
    operation: Literal["get_tile_copyrights"] = "get_tile_copyrights"
    zoom: int = Field(0, ge=0, le=18)


class GetStaticImage(_Input):
    """Render a static map centered on longitude,latitude."""
    operation: Literal["get_static_image"] = "get_static_image"
    center: str = Field(..., description="Longitude,latitude, for example 4.899886,52.379031", pattern=r"^-?\d+(?:\.\d+)?, *-?\d+(?:\.\d+)?$")
    zoom: int = Field(12, ge=0, le=22)
    width: int = Field(512, ge=1, le=8192)
    height: int = Field(512, ge=1, le=8192)
    layer: Literal["basic", "hybrid", "labels"] = "basic"
    style: Literal["main", "night"] = "main"
    format: Literal["png", "jpg", "jpeg"] = "png"
    view: Literal["Unified", "IN"] | None = None

    @field_validator("center")
    @classmethod
    def coordinates(cls, value):
        lon, lat = map(float, value.split(","))
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Center must be longitude,latitude in degrees")
        return value


class GetVectorTile(_Tile):
    """Download a protobuf vector map tile."""
    operation: Literal["get_vector_tile"] = "get_vector_tile"
    layer: Literal["basic", "hybrid", "labels"] = "basic"
    language: str | None = Field(None, max_length=32)
    view: Literal["Unified", "IL", "IN"] | None = None


class GetRasterTile(_Tile):
    """Download a PNG or JPEG raster map tile."""
    operation: Literal["get_raster_tile"] = "get_raster_tile"
    layer: Literal["basic", "hybrid", "labels"] = "basic"
    style: Literal["main", "night"] = "main"
    format: Literal["png", "jpg"] = "png"
    tileSize: Literal[256, 512] = 256
    view: Literal["Unified", "IN"] | None = None

    @model_validator(mode="after")
    def combination(self):
        if self.layer != "basic" and self.format != "png":
            raise ValueError("Hybrid and labels tiles require PNG")
        if self.tileSize == 512 and (self.style != "main" or self.layer == "hybrid"):
            raise ValueError("512-pixel tiles require main style and basic or labels layer")
        return self


class GetWMSMap(_Input):
    """Render a WMS 1.1.1 map for a bounding box."""
    operation: Literal["get_wms_map"] = "get_wms_map"
    srs: Literal["EPSG:3857", "EPSG:4326"] = "EPSG:4326"
    bbox: str = Field(..., pattern=r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$", description="minX,minY,maxX,maxY in the chosen SRS")
    width: int = Field(512, ge=1, le=2048)
    height: int = Field(512, ge=1, le=2048)
    format: Literal["image/png", "image/jpeg"] = "image/png"

    @model_validator(mode="after")
    def bounds(self):
        x1,y1,x2,y2 = map(float, self.bbox.split(","))
        if x1 >= x2 or y1 >= y2:
            raise ValueError("Minimum coordinates must precede maximum coordinates")
        if self.srs == "EPSG:4326" and not (-180 <= x1 < x2 <= 180 and -90 <= y1 < y2 <= 90):
            raise ValueError("EPSG:4326 requires longitude and latitude in degrees")
        return self


class GetWMSCapabilities(_Input):
    """Read WMS service capabilities as XML."""
    operation: Literal["get_wms_capabilities"] = "get_wms_capabilities"


class GetWMTSCapabilities(_Input):
    """Read WMTS 1.0.0 service capabilities as XML."""
    operation: Literal["get_wmts_capabilities"] = "get_wmts_capabilities"


TomTomOperation = Annotated[Union[GetWorldCopyrights, GetCopyrightCaption,
    GetAreaCopyrights, GetTileCopyrights, GetStaticImage, GetVectorTile,
    GetRasterTile, GetWMSMap, GetWMSCapabilities, GetWMTSCapabilities], Field(discriminator="operation")]


class TomTomConfig(NodeConfig[TomTomOperation, TomTomAPIKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]").replace(quote(key, safe=""), "[redacted]")
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k,v in value.items()}
    return value


class TomTomNode(WorkflowNode):
    integration_type = "automation-tomtom"
    connection_evidence = ConnectionEvidence(operation="get_raster_tile", noun="TomTom map access", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return TomTomConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a TomTom API key")
        op = self.config.config
        key = self.config.credentials.api_key
        action = op.operation
        params = {"key": key}
        binary = False
        extension = "json"
        if action == "get_world_copyrights":
            path = "/map/1/copyrights.json"
        elif action == "get_copyright_caption":
            path = "/map/1/copyrights/caption.json"
        elif action == "get_area_copyrights":
            path = f"/map/1/copyrights/{op.minLon}/{op.minLat}/{op.maxLon}/{op.maxLat}.json"
        elif action == "get_tile_copyrights":
            path = f"/map/1/copyrights/{op.zoom}/{op.X}/{op.Y}.json"
        elif action == "get_static_image":
            path = "/map/1/staticimage"
            params.update(op.model_dump(exclude={"operation"}, exclude_none=True))
            binary, extension = True, op.format
        elif action in {"get_vector_tile", "get_raster_tile"}:
            vector = action == "get_vector_tile"
            extension = "pbf" if vector else op.format
            style = "main" if vector else op.style
            path = f"/map/1/tile/{op.layer}/{style}/{op.zoom}/{op.X}/{op.Y}.{extension}"
            for field in (("language", "view") if vector else ("tileSize", "view")):
                if getattr(op, field) is not None:
                    params[field] = getattr(op, field)
            binary = True
        elif action == "get_wms_map":
            path = "/map/1/wms/"
            params.update(op.model_dump(exclude={"operation"}))
            params.update(request="GetMap", service="WMS", version="1.1.1", layers="basic", styles="")
            binary, extension = True, "png" if op.format == "image/png" else "jpg"
        elif action == "get_wms_capabilities":
            # The published Maps 1.0.0 spec mistakenly appends a second slash.
            path = "/map/1/wms/"
            params.update(request="GetCapabilities", service="WMS", version="1.1.1")
            extension = "xml"
        else:
            # Official WMTS docs require the literal apiKey= prefix in this segment.
            path = f"/map/1/wmts/apiKey={quote(key, safe='')}/1.0.0/WMTSCapabilities.xml"
            params = {}
            extension = "xml"
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.request("GET", "https://api.tomtom.com" + path, params=params)
        except httpx.HTTPError:
            raise ValueError("TomTom request could not be completed") from None
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code, "message": _redact(response.text, key)[:2000]}
        if not response.content:
            raise ValueError("TomTom returned an empty response")
        media = response.headers.get("content-type", "").split(";",1)[0].lower()
        if binary:
            if media in {"application/json", "text/html", "text/xml", "application/xml"} or response.content.lstrip().startswith((b"{", b"<")):
                raise ValueError("TomTom returned an error document instead of map data")
            mime = "application/x-protobuf" if extension == "pbf" else "image/png" if extension == "png" else "image/jpeg"
            result = {"file": BinaryOutput(data=response.content, content_type=mime, filename=f"tomtom-{action}.{extension}")}
        elif extension == "xml":
            text = response.text
            if "ServiceException" in text or "ExceptionReport" in text or "<html" in text.lower():
                raise ValueError("TomTom returned an exception document")
            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError:
                raise ValueError("TomTom returned invalid capabilities XML") from None
            expected = "WMT_MS_Capabilities" if action == "get_wms_capabilities" else "Capabilities"
            if root.tag.rsplit("}", 1)[-1] != expected:
                raise ValueError("TomTom returned an unexpected capabilities document")
            result = {"xml": _redact(text, key)}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("TomTom returned invalid JSON") from None
            if not isinstance(data, dict) or "error" in data or "errorText" in data:
                raise ValueError("TomTom returned an unexpected copyright response")
            result = {"data": _redact(data, key)}
        output = {"status": "success", "operation": action, **result}
        await self.emit(output)
        return output
