"""Abyssale creative automation, pinned to the published v2026-10-29 API.

Each operation issues one provider request. Generation spends workspace credits;
async operations return a request ID for explicit polling, never retry a write.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.abyssale.com"
DesignType = Literal["static", "animated", "printer", "printer_multipage"]
Identifier = Annotated[str, Field(min_length=1, max_length=36)]


class AbyssaleApiKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Abyssale API Key",
        json_schema_extra={"x-credential-url": "https://developers.abyssale.com/rest-api/authentication#how-to-get-an-api-key",
            "x-credential-instructions": "In Abyssale, open Workspace settings → API key and copy an existing API key. An Admin can create one there. Paste the key alone. NoClick sends it in x-api-key to api.abyssale.com. Generation uses your workspace credits; a webhook signing secret is a different credential."})
    credential_type: Literal["abyssale_api_key"] = Field("abyssale_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if "{{" in value or "}}" in value or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if value is not None and info.field_name.endswith("_id"):
            try:
                return str(UUID(value))
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Use the resource UUID from Abyssale") from None
        return value


class Page(Input):
    page: int = Field(1, ge=1, le=1000000, description="1-based page. Use next_page from the previous result.")
    per_page: int = Field(25, ge=1, le=100)


class ListDesigns(Page):
    """Search designs by name and project, returning one explicit page."""
    operation: Literal["list_designs"] = "list_designs"
    project_id: Identifier | None = None
    name: str | None = Field(None, max_length=1000)
    query: str | None = Field(None, max_length=500, description="At most eight search words.")
    type: list[DesignType] | None = Field(None, max_length=10)
    orientation: Literal["portrait", "landscape", "square"] | None = None
    sort: Literal["name", "updated", "created"] = "name"
    order: Literal["asc", "desc"] | None = None


class DesignInput(Input):
    design_id: Identifier


class GetDesign(DesignInput):
    """Read a design, its formats and customizable layers."""
    operation: Literal["get_design"] = "get_design"
    i: Literal["advanced"] | None = Field(None, description="Include the full layer/property set, including groups.")


class DeleteDesign(DesignInput):
    """Permanently delete a design. This cannot be undone."""
    operation: Literal["delete_design"] = "delete_design"


class RenameDesign(DesignInput):
    """Rename a design."""
    operation: Literal["rename_design"] = "rename_design"
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Design name must contain text")
        return value.strip()


class MoveDesign(DesignInput):
    """Move a design into an existing workspace project."""
    operation: Literal["move_design"] = "move_design"
    project_id: Identifier


class GetDesignFormat(DesignInput):
    """Read one format by stable UID or format name."""
    operation: Literal["get_design_format"] = "get_design_format"
    format_specifier: str = Field(..., min_length=1, max_length=255)


class CreateDynamicImageUrl(DesignInput):
    """Create a dynamic image URL for a static design."""
    operation: Literal["create_dynamic_image_url"] = "create_dynamic_image_url"
    enable_rate_limit: StrictBool = False
    enable_production_mode: StrictBool = False


class GenerateImage(DesignInput):
    """Generate one image synchronously, spending workspace generation credits."""
    operation: Literal["generate_image"] = "generate_image"
    template_format_name: str | None = Field(None, max_length=255)
    elements: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Layer names mapped to property objects, e.g. {\"title\": {\"payload\": \"Summer sale\"}}. Properties depend on the design's layer types; use Get Design first.")
    image_file_type: Literal["png", "jpeg", "webp", "avif", "pdf", "auto"] | None = None
    original_visual_id: Identifier | None = None
    file_compression_level: int | None = Field(None, ge=1, le=100)


class GenerateMedia(DesignInput):
    """Queue multi-format media; poll Get Generation Request for completion."""
    operation: Literal["generate_media"] = "generate_media"
    template_format_names: list[str] | None = Field(None, max_length=100, description="Omit or use [] to generate all design formats.")
    elements: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Layer names mapped to property objects, as returned by Get Design.")
    image_file_type: Literal["png", "jpeg", "webp", "avif", "gif", "pdf", "html5", "mp4", "auto"] | None = None
    file_compression_level: int | None = Field(None, ge=1, le=100)
    callback_url: str | None = Field(None, max_length=2048)


class GetFile(Input):
    """Read generated asset metadata and file URLs without downloading bytes."""
    operation: Literal["get_file"] = "get_file"
    banner_id: Identifier


class GetGenerationRequest(Input):
    """Poll a generation request once. A 202 means generation is still running."""
    operation: Literal["get_generation_request"] = "get_generation_request"
    generation_request_id: Identifier


class ListFonts(Page):
    """Search fonts by name, type and category."""
    operation: Literal["list_fonts"] = "list_fonts"
    name: str | None = Field(None, max_length=1000)
    type: Literal["google", "custom"] | None = None
    category: Literal["serif", "sans-serif", "display", "handwriting", "monospace"] | None = None
    weight: Literal[100, 200, 300, 400, 500, 600, 700, 800, 900] | None = None
    style: Literal["normal", "italic"] | None = None


class GetCredits(Input):
    """Read remaining workspace generation and AI credits."""
    operation: Literal["get_credits"] = "get_credits"


class ListProjects(Page):
    """Read workspace projects; also proves the connected account can read them."""
    operation: Literal["list_projects"] = "list_projects"
    name: str | None = Field(None, max_length=1000)


class CreateProject(Input):
    """Create a workspace project with a unique name."""
    operation: Literal["create_project"] = "create_project"
    name: str = Field(..., min_length=2, max_length=100)


class ListWorkspaceTemplates(Input):
    """Read the workspace's shared templates, optionally filtered by category."""
    operation: Literal["list_workspace_templates"] = "list_workspace_templates"
    category_id: Identifier | None = None
    type: DesignType | None = None


class ListWorkspaceTemplateCategories(Input):
    """Read categories for the workspace template library."""
    operation: Literal["list_workspace_template_categories"] = "list_workspace_template_categories"


class DuplicateWorkspaceTemplate(Input):
    """Queue duplication of a workspace template into an existing project."""
    operation: Literal["duplicate_workspace_template"] = "duplicate_workspace_template"
    company_template_id: Identifier
    project_id: Identifier
    name: str | None = Field(None, min_length=2, max_length=100)


class GetDuplicationRequest(Input):
    """Poll template duplication once; statuses expire after seven days."""
    operation: Literal["get_duplication_request"] = "get_duplication_request"
    duplicate_request_id: Identifier


class ExportBanners(Input):
    """Queue a ZIP export; callback_url receives the asynchronous result."""
    operation: Literal["export_banners"] = "export_banners"
    ids: list[str] = Field(..., min_length=1, max_length=1000)
    callback_url: str | None = Field(None, max_length=2048)

    @field_validator("ids")
    @classmethod
    def uuids(cls, value):
        return [str(UUID(item)) for item in value]


Operation = Annotated[Union[ListDesigns, GetDesign, DeleteDesign, RenameDesign, MoveDesign,
    GetDesignFormat, CreateDynamicImageUrl, GenerateImage, GenerateMedia, GetFile,
    GetGenerationRequest, ListFonts, GetCredits, ListProjects, CreateProject,
    ListWorkspaceTemplates, ListWorkspaceTemplateCategories, DuplicateWorkspaceTemplate,
    GetDuplicationRequest, ExportBanners], Field(discriminator="operation")]


class AbyssaleConfig(NodeConfig[Operation, AbyssaleApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Each entry maps exactly one operation to one published method/path.
ROUTES = {
    "list_designs": ("GET", "/designs"),
    "get_design": ("GET", "/designs/{design_id}"),
    "delete_design": ("DELETE", "/designs/{design_id}"),
    "rename_design": ("PUT", "/designs/{design_id}/name"),
    "move_design": ("PUT", "/designs/{design_id}/project"),
    "get_design_format": ("GET", "/designs/{design_id}/formats/{format_specifier}"),
    "create_dynamic_image_url": ("POST", "/designs/{design_id}/dynamic-image-url"),
    "generate_image": ("POST", "/banner-builder/{design_id}/generate"),
    "generate_media": ("POST", "/async/banner-builder/{design_id}/generate"),
    "get_file": ("GET", "/banners/{banner_id}"),
    "get_generation_request": ("GET", "/generation-request/{generation_request_id}"),
    "list_fonts": ("GET", "/fonts"), "get_credits": ("GET", "/credits"),
    "list_projects": ("GET", "/projects"), "create_project": ("POST", "/projects"),
    "list_workspace_templates": ("GET", "/workspace-templates"),
    "list_workspace_template_categories": ("GET", "/workspace-template-categories"),
    "duplicate_workspace_template": ("POST", "/workspace-templates/{company_template_id}/use"),
    "get_duplication_request": ("GET", "/design-duplication-requests/{duplicate_request_id}"),
    "export_banners": ("POST", "/async/banners/export"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, key) for name, item in value.items()}
    return value


class AbyssaleNode(WorkflowNode):
    integration_type = "automation-abyssale"
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return AbyssaleConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Abyssale API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, mode="json", exclude={"operation"})
        for name in list(values):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(str(values.pop(name)), safe=""))
        params = values if method == "GET" else {}
        for name, value in params.items():
            if isinstance(value, list):
                params[name] = ",".join(value)
        body = values if method in {"POST", "PUT"} else None
        try:
            async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            return {"status": "error", "error": "Abyssale request did not complete; inspect writes before retrying", "write_outcome": "unknown" if method != "GET" else None}
        if not 200 <= response.status_code < 300:
            message = "Abyssale rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000]
            except (ValueError, UnicodeError):
                pass
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, key)}
        allowed = {200, 201} if op.operation == "create_dynamic_image_url" else {200, 202} if op.operation == "get_generation_request" else {200}
        if response.status_code not in allowed:
            raise ValueError("Unexpected Abyssale success status; inspect writes before retrying")
        if len(response.content) > 10_000_000:
            raise ValueError("Abyssale response exceeds the JSON size limit")
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            raise ValueError("Expected JSON from Abyssale") from None
        listing = op.operation.startswith("list_")
        if not isinstance(data, list if listing else dict):
            raise ValueError("Unexpected Abyssale response shape")
        if isinstance(data, dict) and ("error" in data or ("message" in data and "id" in data)):
            raise ValueError("Abyssale returned an error envelope")
        result = {"status": "success", "http_status": response.status_code,
            "items" if listing else "data": _redact(data, key)}
        if op.operation == "delete_design":
            result["deletion_acknowledged"] = True
        if isinstance(op, Page):
            total = response.headers.get("X-Total-Count")
            if total is not None:
                try:
                    total = int(total)
                except ValueError:
                    raise ValueError("Invalid Abyssale pagination total") from None
                if total < 0:
                    raise ValueError("Invalid Abyssale pagination total")
            has_more = op.page * op.per_page < total if total is not None else len(data) == op.per_page
            result.update(page=op.page, per_page=op.per_page, total=total,
                has_more=has_more, next_page=op.page + 1 if has_more else None)
        return result
