"""Orshot workspace API: https://orshot.com/openapi.json (1.0.0).

Each operation makes one documented request. Lists return one page and preserve
provider pagination. Rendering requests URL output; NoClick does not download
or encode rendered files. API keys stay on the fixed Orshot API origin.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://api.orshot.com/v1"


class OrshotAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Orshot API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://orshot.com/workspace",
            "x-credential-instructions": "In your Orshot workspace, open API Keys and copy a workspace API key. Paste only the key. NoClick sends it as a Bearer token to api.orshot.com. Connecting reads your workspace; rendering uses Orshot credits and template folders require a paid plan.",
        },
    )
    credential_type: Literal["orshot_api_key"] = Field(
        "orshot_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your workspace API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without a Bearer prefix or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class RenderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal[
        "png", "webp", "jpg", "avif", "pdf", "mp4", "webm", "mov", "mkv", "gif"
    ] = "png"
    mode: Literal["sync", "async"] = "sync"
    scale: float | None = Field(None, gt=0)
    size: str | None = None
    quality: int | None = Field(None, ge=1, le=100)
    fileName: str | None = None


class RenderTemplate(_Operation):
    """Render from Studio Template. https://orshot.com/docs/api-reference/render-from-studio-template"""

    operation: Literal["render_template"] = Field(
        "render_template", json_schema_extra={"ui:hidden": True}
    )
    templateId: int = Field(..., gt=0, title="Template ID")
    modifications: dict = Field(
        default_factory=dict,
        description="Dynamic values keyed by template parameter ID.",
    )
    response: RenderResponse = Field(
        default_factory=RenderResponse,
        description="Output format and mode; content is always returned as URLs.",
    )
    pdfOptions: dict | None = None
    videoOptions: dict | None = None
    lang: str | None = None


class GetRenderJob(_Operation):
    """Get a Render Job. https://orshot.com/docs/api-reference/async-render-job-get"""

    operation: Literal["get_render_job"] = Field(
        "get_render_job", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., pattern=r"^[1-9][0-9]*$", title="Render job ID")


class ListRenderJobs(_Operation):
    """List Render Jobs. https://orshot.com/docs/api-reference/async-render-jobs-list"""

    operation: Literal["list_render_jobs"] = Field(
        "list_render_jobs", json_schema_extra={"ui:hidden": True}
    )
    status: Literal[
        "queued", "processing", "succeeded", "failed", "canceled"
    ] | None = None
    limit: int = Field(20, ge=1, le=100)
    cursor: int | None = Field(
        None, gt=0, description="pagination.next_cursor from the preceding response."
    )


class CancelRenderJob(_Operation):
    """Cancel a Render Job. https://orshot.com/docs/api-reference/async-render-job-cancel"""

    operation: Literal["cancel_render_job"] = Field(
        "cancel_render_job", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., pattern=r"^[1-9][0-9]*$", title="Queued render job ID")


class ListTemplates(_Operation):
    """Get All Studio Templates. https://orshot.com/docs/api-reference/studio-templates-list"""

    operation: Literal["list_templates"] = Field(
        "list_templates", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, ge=1)
    limit: int = Field(10, ge=1, le=40)
    search: str | None = None
    tags: str | None = Field(None, description="Comma-separated tags; all must match.")


class GetTemplate(_Operation):
    """Get Studio Template. https://orshot.com/docs/api-reference/studio-template-get"""

    operation: Literal["get_template"] = Field(
        "get_template", json_schema_extra={"ui:hidden": True}
    )
    templateId: str = Field(..., pattern=r"^[1-9][0-9]*$", title="Template ID")


class DeleteTemplate(_Operation):
    """Delete Studio Template. https://orshot.com/docs/api-reference/studio-template-delete"""

    operation: Literal["delete_template"] = Field(
        "delete_template", json_schema_extra={"ui:hidden": True}
    )
    templateId: int = Field(
        ...,
        gt=0,
        title="Template ID",
        description="Permanently delete this studio template.",
    )


class ListFolders(_Operation):
    """List Template Folders. https://orshot.com/docs/api-reference/template-folders-get"""

    operation: Literal["list_folders"] = Field(
        "list_folders", json_schema_extra={"ui:hidden": True}
    )


class CreateFolder(_Operation):
    """Create Template Folder. https://orshot.com/docs/api-reference/template-folders-post"""

    operation: Literal["create_folder"] = Field(
        "create_folder", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=50)


class RenameFolder(_Operation):
    """Rename Template Folder. https://orshot.com/docs/api-reference/template-folders-update"""

    operation: Literal["rename_folder"] = Field(
        "rename_folder", json_schema_extra={"ui:hidden": True}
    )
    folderId: int = Field(..., gt=0, title="Folder ID")
    name: str = Field(..., min_length=1, max_length=50)


class DeleteFolder(_Operation):
    """Delete Template Folder. https://orshot.com/docs/api-reference/template-folders-delete"""

    operation: Literal["delete_folder"] = Field(
        "delete_folder", json_schema_extra={"ui:hidden": True}
    )
    folderId: int = Field(..., gt=0, title="Folder ID")


class MoveTemplateToFolder(_Operation):
    """Move Template to Folder. https://orshot.com/docs/api-reference/template-folder-assign"""

    operation: Literal["move_template_to_folder"] = Field(
        "move_template_to_folder", json_schema_extra={"ui:hidden": True}
    )
    templateId: int = Field(..., gt=0, title="Template ID")
    folder_id: int = Field(..., gt=0, title="Destination folder ID")


class ListImages(_Operation):
    """Get Brand Images. https://orshot.com/docs/api-reference/brand-assets-get"""

    operation: Literal["list_images"] = Field(
        "list_images", json_schema_extra={"ui:hidden": True}
    )
    tag: str | None = Field(None, description="Comma-separated tags; all must match.")


class UploadImage(_Operation):
    """Upload Brand Image. https://orshot.com/docs/api-reference/brand-assets-post"""

    operation: Literal["upload_image"] = Field(
        "upload_image", json_schema_extra={"ui:hidden": True}
    )
    file: str = Field(
        ...,
        min_length=1,
        description="Public image URL or a data URI accepted by Orshot.",
    )
    fileName: str | None = None
    fileType: str | None = None
    tags: list[str] | None = None
    meta: dict | None = None


class UpdateImageTags(_Operation):
    """Update Image Tags. https://orshot.com/docs/api-reference/brand-assets-update"""

    operation: Literal["update_image_tags"] = Field(
        "update_image_tags", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., gt=0, title="Image ID")
    tags: list[str] = Field(
        ..., description="Replace all tags; an empty list clears them."
    )


class DeleteImage(_Operation):
    """Delete Brand Image. https://orshot.com/docs/api-reference/brand-assets-delete"""

    operation: Literal["delete_image"] = Field(
        "delete_image", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., gt=0, title="Image ID")


class ListColors(_Operation):
    """Get Colors. https://orshot.com/docs/api-reference/brand-colors-get"""

    operation: Literal["list_colors"] = Field(
        "list_colors", json_schema_extra={"ui:hidden": True}
    )
    tag: str | None = Field(None, description="Comma-separated tags; all must match.")


class AddColor(_Operation):
    """Add Color. https://orshot.com/docs/api-reference/brand-colors-post"""

    operation: Literal["add_color"] = Field(
        "add_color", json_schema_extra={"ui:hidden": True}
    )
    value: str = Field(
        ..., min_length=1, description="CSS color or gradient, for example #FF5733."
    )
    type: Literal["hex", "rgb", "hsl", "gradient"] = "hex"
    tags: list[str] | None = None


class DeleteColor(_Operation):
    """Delete Color. https://orshot.com/docs/api-reference/brand-colors-delete"""

    operation: Literal["delete_color"] = Field(
        "delete_color", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., gt=0, title="Color ID")


class GetWorkspace(_Operation):
    """Get Workspace. https://orshot.com/docs/api-reference/workspace-get"""

    operation: Literal["get_workspace"] = Field(
        "get_workspace", json_schema_extra={"ui:hidden": True}
    )


class ListWorkspaceLogs(_Operation):
    """List Workspace Logs. https://orshot.com/docs/api-reference/workspace-logs"""

    operation: Literal["list_workspace_logs"] = Field(
        "list_workspace_logs", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(50, ge=1, le=50)
    cursor: int | None = Field(
        None, gt=0, description="next_cursor from the preceding response."
    )
    status: str | None = None
    source: str | None = None
    source_client: str | None = None
    template_id: str | None = None
    format: str | None = None
    from_time: str | None = Field(
        None, description="ISO timestamp, inclusive lower bound."
    )
    to_time: str | None = Field(
        None, description="ISO timestamp, inclusive upper bound."
    )


OrshotOperation = Annotated[
    Union[
        RenderTemplate,
        GetRenderJob,
        ListRenderJobs,
        CancelRenderJob,
        ListTemplates,
        GetTemplate,
        DeleteTemplate,
        ListFolders,
        CreateFolder,
        RenameFolder,
        DeleteFolder,
        MoveTemplateToFolder,
        ListImages,
        UploadImage,
        UpdateImageTags,
        DeleteImage,
        ListColors,
        AddColor,
        DeleteColor,
        GetWorkspace,
        ListWorkspaceLogs,
    ],
    Field(discriminator="operation"),
]


class OrshotConfig(NodeConfig[OrshotOperation, OrshotAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "render_template": (
        "POST",
        "/studio/render",
        [],
        [],
        [
            "templateId",
            "modifications",
            "response",
            "pdfOptions",
            "videoOptions",
            "lang",
        ],
        True,
    ),
    "get_render_job": ("GET", "/studio/render-jobs/{id}", ["id"], [], [], False),
    "list_render_jobs": (
        "GET",
        "/studio/render-jobs",
        [],
        ["status", "limit", "cursor"],
        [],
        False,
    ),
    "cancel_render_job": (
        "POST",
        "/studio/render-jobs/{id}/cancel",
        ["id"],
        [],
        [],
        True,
    ),
    "list_templates": (
        "GET",
        "/studio/templates/all",
        [],
        ["page", "limit", "search", "tags"],
        [],
        False,
    ),
    "get_template": (
        "GET",
        "/studio/templates/{templateId}",
        ["templateId"],
        [],
        [],
        False,
    ),
    "delete_template": (
        "DELETE",
        "/studio/templates/{templateId}/delete",
        ["templateId"],
        [],
        [],
        False,
    ),
    "list_folders": ("GET", "/studio/folders", [], [], [], False),
    "create_folder": ("POST", "/studio/folders", [], [], ["name"], True),
    "rename_folder": (
        "PATCH",
        "/studio/folders/{folderId}",
        ["folderId"],
        [],
        ["name"],
        True,
    ),
    "delete_folder": (
        "DELETE",
        "/studio/folders/{folderId}",
        ["folderId"],
        [],
        [],
        False,
    ),
    "move_template_to_folder": (
        "PATCH",
        "/studio/templates/{templateId}/folder",
        ["templateId"],
        [],
        ["folder_id"],
        True,
    ),
    "list_images": ("GET", "/brand-assets/images/get", [], ["tag"], [], False),
    "upload_image": (
        "POST",
        "/brand-assets/images/add",
        [],
        [],
        ["file", "fileName", "fileType", "tags", "meta"],
        True,
    ),
    "update_image_tags": (
        "PATCH",
        "/brand-assets/images/update/{id}",
        ["id"],
        [],
        ["tags"],
        True,
    ),
    "delete_image": (
        "DELETE",
        "/brand-assets/images/delete/{id}",
        ["id"],
        [],
        [],
        False,
    ),
    "list_colors": ("GET", "/brand-assets/colors/get", [], ["tag"], [], False),
    "add_color": (
        "POST",
        "/brand-assets/colors/add",
        [],
        [],
        ["value", "type", "tags"],
        True,
    ),
    "delete_color": (
        "DELETE",
        "/brand-assets/colors/delete/{id}",
        ["id"],
        [],
        [],
        False,
    ),
    "get_workspace": ("GET", "/workspace", [], [], [], False),
    "list_workspace_logs": (
        "GET",
        "/workspace/logs",
        [],
        [
            "limit",
            "cursor",
            "status",
            "source",
            "source_client",
            "template_id",
            "format",
            "from",
            "to",
        ],
        [],
        False,
    ),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {
            str(k).replace(secret, "[redacted]"): _redact(v, secret)
            for k, v in value.items()
            if str(k).lower()
            not in {"api_key", "authorization", "access_token", "refresh_token"}
        }
    return value


class OrshotNode(WorkflowNode):
    integration_type = "automation-orshot"
    connection_evidence = ConnectionEvidence(
        noun="templates",
        operation="list_templates",
        identity_operation="get_workspace",
        identity_keys=("title", "slug", "url"),
    )

    @classmethod
    def get_config_model(cls):
        return OrshotConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Orshot workspace API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path, path_fields, query_fields, body_fields, has_body = ROUTES[
            op.operation
        ]
        values = op.model_dump(exclude_none=True)
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        aliases = {"from": "from_time", "to": "to_time"}
        params = {
            k: values[aliases.get(k, k)]
            for k in query_fields
            if aliases.get(k, k) in values
        }
        body = {k: values[k] for k in body_fields if k in values} if has_body else None
        if op.operation == "render_template":
            body["response"] = {
                **op.response.model_dump(exclude_none=True),
                "type": "url",
            }
        try:
            async with httpx.AsyncClient(
                timeout=120.0, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE + path,
                    params=params,
                    headers={
                        "Authorization": "Bearer " + secret,
                        "Accept": "application/json",
                    },
                    **({"json": body} if has_body else {}),
                )
        except httpx.TransportError:
            raise ValueError(
                "Orshot request did not complete; inspect writes before retrying"
            ) from None
        if not 200 <= response.status_code < 300:
            try:
                payload = response.json()
                message = (
                    payload.get("error", "Orshot rejected the request")
                    if isinstance(payload, dict)
                    else "Orshot rejected the request"
                )
            except ValueError:
                message = "Orshot returned an unexpected non-JSON response"
            raise ValueError(
                f"Orshot HTTP {response.status_code}: {_redact(str(message), secret)}"
            ) from None
        if response.status_code == 204:
            payload = None
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError(
                    "Orshot returned an unexpected non-JSON response"
                ) from None
            if not isinstance(payload, dict):
                raise ValueError("Orshot returned an unexpected response shape")
            if payload.get("error") and op.operation != "get_render_job":
                raise ValueError(_redact(str(payload["error"]), secret)) from None
        # Workspace identity has one data envelope; expose the account fields
        # at the standard output path used by connection evidence.
        data = (
            payload.get("data", payload)
            if op.operation == "get_workspace" and isinstance(payload, dict)
            else payload
        )
        result = {
            "status": "success",
            "data": _redact(data, secret),
            "http_status": response.status_code,
        }
        await self.emit(result)
        return result
