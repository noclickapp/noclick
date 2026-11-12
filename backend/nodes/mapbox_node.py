"""Mapbox token validation, geocoding and map style automation."""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MapboxAccessToken(BaseModel):
    model_config = ConfigDict(title="Mapbox Access Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://account.mapbox.com/access-tokens/",
        "x-credential-instructions": "Paste a Mapbox access token and your account username. Geocoding accepts public tokens. Reading styles needs styles:read; modifying styles or sprites needs a secret token with styles:write. Use an unrestricted server token; URL-restricted tokens may reject server requests."})
    credential_type: Literal["mapbox_access_token"] = Field("mapbox_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, json_schema_extra={"ui:widget": "password"})
    username: str = Field(..., title="Account username", pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("access_token")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="Access token")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckConnection(Input):
    operation: Literal["check_connection"] = "check_connection"


class ListStyles(Input):
    operation: Literal["list_styles"] = "list_styles"
    limit: int = Field(100, ge=1, le=100)
    start: str | None = Field(None, description="Cursor from the preceding page's next_start.")
    draft: bool | None = None


class StyleRef(Input):
    style_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class GetStyle(StyleRef):
    operation: Literal["get_style"] = "get_style"


class DeleteStyle(StyleRef):
    operation: Literal["delete_style"] = "delete_style"


class GetStyleDraft(StyleRef):
    operation: Literal["get_style_draft"] = "get_style_draft"


class DeleteStyleDraft(StyleRef):
    operation: Literal["delete_style_draft"] = "delete_style_draft"


class GetSprite(StyleRef):
    operation: Literal["get_sprite"] = "get_sprite"


class DeleteSpriteImage(StyleRef):
    operation: Literal["delete_sprite_image"] = "delete_sprite_image"
    icon_name: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class StyleInput(Input):
    name: str = Field(..., min_length=1)
    version: Literal[6, 7, 8] = 8
    sources: dict = Field(..., description="Mapbox Style Specification source objects; maximum 15 sources.")
    layers: list[dict] = Field(..., description="Ordered Mapbox Style Specification layers.")
    sprite: str | None = None
    glyphs: str | None = None
    metadata: dict | None = None

    @field_validator("sources")
    @classmethod
    def source_limit(cls, value):
        if len(value) > 15:
            raise ValueError("Mapbox supports at most 15 sources per style")
        return value


class CreateStyle(StyleInput):
    operation: Literal["create_style"] = "create_style"


class UpdateStyle(StyleInput, StyleRef):
    operation: Literal["update_style"] = "update_style"


class UpdateStyleDraft(StyleInput, StyleRef):
    operation: Literal["update_style_draft"] = "update_style_draft"


class ForwardGeocode(Input):
    operation: Literal["forward_geocode"] = "forward_geocode"
    q: str = Field(..., min_length=1, max_length=256, description="Address or place to find; at most 20 words, without semicolons.")
    limit: int = Field(5, ge=1, le=10)
    permanent: bool = Field(False, description="Enable only with a Mapbox plan permitting permanent storage.")
    country: str | None = None
    language: str | None = None

    @field_validator("q")
    @classmethod
    def query(cls, value):
        if ";" in value or len(value.split()) > 20:
            raise ValueError("Use at most 20 words and no semicolons")
        return value


class ReverseGeocode(Input):
    operation: Literal["reverse_geocode"] = "reverse_geocode"
    longitude: float = Field(..., ge=-180, le=180)
    latitude: float = Field(..., ge=-90, le=90)
    permanent: bool = False
    country: str | None = None
    language: str | None = None


# Mapbox's own MCP server: agents get its tools through a person's Mapbox sign-in.
MapboxMcpCredential = mcp_credential("mapbox", "https://mcp.mapbox.com/mcp", app="Mapbox")
MapboxCredential = Union[MapboxAccessToken, MapboxMcpCredential]


MapboxConfig = Annotated[Union[CheckConnection, ListStyles, GetStyle, CreateStyle, UpdateStyle,
    DeleteStyle, GetStyleDraft, UpdateStyleDraft, DeleteStyleDraft, GetSprite, DeleteSpriteImage,
    ForwardGeocode, ReverseGeocode], Field(discriminator="operation")]


class MapboxFullConfig(NodeConfig[MapboxConfig, MapboxCredential]):
    pass


class MapboxNode(WorkflowNode):
    integration_type = "automation-mapbox"
    credential_provider_labels = {"mapbox": "Mapbox Account"}
    connection_evidence = ConnectionEvidence(noun="Mapbox account", identity_operation="check_connection")

    @classmethod
    def get_config_model(cls):
        return MapboxFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Mapbox access token")
        config = self.config.config
        op = config.operation
        params = {"access_token": credential.access_token}
        body = None
        method = "GET"
        if op == "check_connection":
            path = "/tokens/v2"
        elif op in {"forward_geocode", "reverse_geocode"}:
            path = "/search/geocode/v6/" + ("forward" if op == "forward_geocode" else "reverse")
            params.update(config.model_dump(exclude={"operation"}, exclude_none=True))
        else:
            path = "/styles/v1/" + quote(credential.username, safe="")
            if isinstance(config, StyleRef):
                path += "/" + quote(config.style_id, safe="")
            if op.endswith("_draft"):
                path += "/draft"
            if op == "get_sprite":
                path += "/sprite"
            elif op == "delete_sprite_image":
                path += "/sprite/" + quote(config.icon_name, safe="")
            if op == "list_styles":
                params.update(config.model_dump(exclude={"operation"}, exclude_none=True))
            elif isinstance(config, StyleInput):
                method = "POST" if op == "create_style" else "PATCH"
                body = config.model_dump(exclude={"operation", "style_id"}, exclude_none=True)
            elif op.startswith("delete_"):
                method = "DELETE"
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.mapbox.com" + path,
                    params=params, **({"json": body} if body is not None else {}))
            expected = 201 if op == "create_style" else 204 if op in {"delete_style", "delete_style_draft"} else 200
            if response.status_code != expected:
                return {"status": "error", "http_status": response.status_code,
                    "error": "Mapbox rejected the request; check token scopes, account username and resource ID."}
            if expected == 204:
                return {"status": "success", "deleted": True}
            data = response.json()
            if op == "check_connection":
                if not isinstance(data, dict) or data.get("code") != "TokenValid":
                    return {"status": "error", "error": str(data.get("code", "Invalid token validation response")) if isinstance(data, dict) else "Invalid token validation response"}
                identity = data.get("token", {}).get("user")
                if not identity or identity != credential.username:
                    return {"status": "error", "error": "Token account does not match the supplied Mapbox username"}
                return {"status": "success", "name": identity, "id": identity}
            if not isinstance(data, list if op == "list_styles" else dict):
                raise ValueError("Unexpected Mapbox response shape")
            if op == "list_styles":
                from urllib.parse import urlsplit, parse_qs
                next_start = None
                link = response.links.get("next", {}).get("url")
                if link:
                    parts = urlsplit(link)
                    if parts.scheme != "https" or parts.netloc != "api.mapbox.com" or parts.path != path:
                        raise ValueError("Unexpected pagination target")
                    next_start = parse_qs(parts.query).get("start", [None])[0]
                    if not next_start or next_start == config.start:
                        raise ValueError("Invalid pagination cursor")
                return {"status": "success", "styles": data, "next_start": next_start, "has_more": next_start is not None}
            return {"status": "success", "data": data}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Mapbox request could not be confirmed"}
