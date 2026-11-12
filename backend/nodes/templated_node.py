"""Templated v1 operations backed by the provider's pinned Postman collection.

Each operation makes one request and lists return one provider page, including
pagination metadata. Render URLs are returned as metadata, never downloaded.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.templated.io"


class TemplatedAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Templated API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://templated.io/dashboard",
            "x-credential-instructions": "Copy your API key from the Templated dashboard and paste it here without the Bearer prefix. NoClick uses it to read your templates and perform the operations you select."})
    credential_type: Literal["templated_api_key"] = Field("templated_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Template(_Input):
    template_id: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Template ID")


class _Folder(_Input):
    folder_id: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Folder ID")


class _Page(_Input):
    page: int | None = Field(None, ge=1, description="One page per call. Use pagination.totalPages to decide whether to increment page.")
    limit: int | None = Field(None, ge=1, description="Number of results per page.")


class TemplatedCreateTemplateConfig(_Input):
    """Create a new template with specified dimensions and layers."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    width: int = Field(..., ge=1)
    height: int = Field(..., ge=1)
    layers: list[dict] = Field(default_factory=list)


class TemplatedGetTemplateConfig(_Template):
    """Retrieve a specific template by ID."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class TemplatedUpdateTemplateConfig(_Template):
    """Update an existing template; omitted layers remain unchanged."""
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    layers: list[dict] | None = Field(None, description="Omit to preserve existing layers. An empty list explicitly clears them.")


class TemplatedDeleteTemplateConfig(_Template):
    """Delete a template by ID."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})


class TemplatedListTemplatesConfig(_Page):
    """List all templates with optional filtering."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)
    width: int | None = Field(None, ge=1)
    height: int | None = Field(None, ge=1)
    tags: str | None = Field(None, max_length=1000)
    externalId: str | None = Field(None, max_length=1000)
    includeLayers: bool | None = Field(None)
    includePages: bool | None = Field(None)


class TemplatedCloneTemplateConfig(_Template):
    """Clone an existing template."""
    operation: Literal["clone_template"] = Field("clone_template", json_schema_extra={"ui:hidden": True})


class TemplatedListTemplateLayersConfig(_Template):
    """List all layers in a template."""
    operation: Literal["list_template_layers"] = Field("list_template_layers", json_schema_extra={"ui:hidden": True})
    includeLockedLayers: bool | None = Field(None)


class TemplatedListTemplateRendersConfig(_Template):
    """List all renders for a specific template."""
    operation: Literal["list_template_renders"] = Field("list_template_renders", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1)
    limit: int | None = Field(None, ge=1)
    externalId: str | None = Field(None, max_length=1000)


class TemplatedCreateRenderConfig(_Input):
    """Create a new render from a template."""
    operation: Literal["create_render"] = Field("create_render", json_schema_extra={"ui:hidden": True})
    template: str = Field(..., min_length=1, max_length=255)
    format: str = Field("png", description="Render format, for example png.")
    layers: dict = Field(default_factory=dict)


class TemplatedGetRenderConfig(_Input):
    """Retrieve a specific render by ID."""
    operation: Literal["get_render"] = Field("get_render", json_schema_extra={"ui:hidden": True})
    render_id: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Render ID")


class TemplatedCreateFolderConfig(_Input):
    """Create a new folder to organize templates."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)


class TemplatedListFoldersConfig(_Page):
    """List all folders with optional filtering."""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)


class TemplatedUpdateFolderConfig(_Folder):
    """Update an existing folder."""
    operation: Literal["update_folder"] = Field("update_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)


class TemplatedDeleteFolderConfig(_Folder):
    """Delete a folder by ID."""
    operation: Literal["delete_folder"] = Field("delete_folder", json_schema_extra={"ui:hidden": True})


class TemplatedListFolderTemplatesConfig(_Folder):
    """List all templates in a specific folder."""
    operation: Literal["list_folder_templates"] = Field("list_folder_templates", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)
    page: int | None = Field(None, ge=1)
    limit: int | None = Field(None, ge=1)
    width: int | None = Field(None, ge=1)
    height: int | None = Field(None, ge=1)
    tags: str | None = Field(None, max_length=1000)
    includeLayers: bool | None = Field(None)


class TemplatedListFolderRendersConfig(_Folder):
    """List all renders in a specific folder."""
    operation: Literal["list_folder_renders"] = Field("list_folder_renders", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1)
    limit: int | None = Field(None, ge=1)


class TemplatedListUploadsConfig(_Page):
    """List all uploaded images."""
    operation: Literal["list_uploads"] = Field("list_uploads", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)
    tags: str | None = Field(None, max_length=1000)


class TemplatedDeleteUploadsConfig(_Input):
    """Delete multiple uploaded images by IDs."""
    operation: Literal["delete_uploads"] = Field("delete_uploads", json_schema_extra={"ui:hidden": True})
    ids: list[str] = Field(..., min_length=1, description="IDs or font names to delete.")


class TemplatedListFontsConfig(_Input):
    """List all available fonts."""
    operation: Literal["list_fonts"] = Field("list_fonts", json_schema_extra={"ui:hidden": True})


class TemplatedDeleteFontsConfig(_Input):
    """Delete multiple fonts."""
    operation: Literal["delete_fonts"] = Field("delete_fonts", json_schema_extra={"ui:hidden": True})
    fonts: list[str] = Field(..., min_length=1, description="IDs or font names to delete.")


# Templated's own MCP server: agents get its tools through a person's Templated sign-in.
TemplatedMcpCredential = mcp_credential("templated", "https://mcp.templated.io/mcp", app="Templated")
TemplatedCredential = Union[TemplatedAPIKeyCredential, TemplatedMcpCredential]


TemplatedConfig = Annotated[Union[
    TemplatedCreateTemplateConfig,
    TemplatedGetTemplateConfig,
    TemplatedUpdateTemplateConfig,
    TemplatedDeleteTemplateConfig,
    TemplatedListTemplatesConfig,
    TemplatedCloneTemplateConfig,
    TemplatedListTemplateLayersConfig,
    TemplatedListTemplateRendersConfig,
    TemplatedCreateRenderConfig,
    TemplatedGetRenderConfig,
    TemplatedCreateFolderConfig,
    TemplatedListFoldersConfig,
    TemplatedUpdateFolderConfig,
    TemplatedDeleteFolderConfig,
    TemplatedListFolderTemplatesConfig,
    TemplatedListFolderRendersConfig,
    TemplatedListUploadsConfig,
    TemplatedDeleteUploadsConfig,
    TemplatedListFontsConfig,
    TemplatedDeleteFontsConfig
], Field(discriminator="operation")]


class TemplatedFullConfig(NodeConfig[TemplatedConfig, TemplatedCredential]):
    pass


OPERATIONS = {'create_template': {'method': 'POST',
                     'path': '/v1/template',
                     'id_field': None,
                     'query': [],
                     'body': ['name', 'width', 'height', 'layers']},
 'get_template': {'method': 'GET',
                  'path': '/v1/template/{id}',
                  'id_field': 'template_id',
                  'query': [],
                  'body': None},
 'update_template': {'method': 'PUT',
                     'path': '/v1/template/{id}',
                     'id_field': 'template_id',
                     'query': [],
                     'body': ['name', 'layers']},
 'delete_template': {'method': 'DELETE',
                     'path': '/v1/template/{id}',
                     'id_field': 'template_id',
                     'query': [],
                     'body': None},
 'list_templates': {'method': 'GET',
                    'path': '/v1/templates',
                    'id_field': None,
                    'query': ['query',
                              'page',
                              'limit',
                              'width',
                              'height',
                              'tags',
                              'externalId',
                              'includeLayers',
                              'includePages'],
                    'body': None},
 'clone_template': {'method': 'POST',
                    'path': '/v1/template/{id}/clone',
                    'id_field': 'template_id',
                    'query': [],
                    'body': None},
 'list_template_layers': {'method': 'GET',
                          'path': '/v1/template/{id}/layers',
                          'id_field': 'template_id',
                          'query': ['includeLockedLayers'],
                          'body': None},
 'list_template_renders': {'method': 'GET',
                           'path': '/v1/template/{id}/renders',
                           'id_field': 'template_id',
                           'query': ['page', 'limit', 'externalId'],
                           'body': None},
 'create_render': {'method': 'POST',
                   'path': '/v1/render',
                   'id_field': None,
                   'query': [],
                   'body': ['template', 'format', 'layers']},
 'get_render': {'method': 'GET',
                'path': '/v1/render/{id}',
                'id_field': 'render_id',
                'query': [],
                'body': None},
 'create_folder': {'method': 'POST',
                   'path': '/v1/folder',
                   'id_field': None,
                   'query': [],
                   'body': ['name']},
 'list_folders': {'method': 'GET',
                  'path': '/v1/folders',
                  'id_field': None,
                  'query': ['query', 'page', 'limit'],
                  'body': None},
 'update_folder': {'method': 'PUT',
                   'path': '/v1/folder/{id}',
                   'id_field': 'folder_id',
                   'query': [],
                   'body': ['name']},
 'delete_folder': {'method': 'DELETE',
                   'path': '/v1/folder/{id}',
                   'id_field': 'folder_id',
                   'query': [],
                   'body': None},
 'list_folder_templates': {'method': 'GET',
                           'path': '/v1/folder/{id}/templates',
                           'id_field': 'folder_id',
                           'query': ['query',
                                     'page',
                                     'limit',
                                     'width',
                                     'height',
                                     'tags',
                                     'includeLayers'],
                           'body': None},
 'list_folder_renders': {'method': 'GET',
                         'path': '/v1/folder/{id}/renders',
                         'id_field': 'folder_id',
                         'query': ['page', 'limit'],
                         'body': None},
 'list_uploads': {'method': 'GET',
                  'path': '/v1/uploads',
                  'id_field': None,
                  'query': ['query', 'tags', 'page', 'limit'],
                  'body': None},
 'delete_uploads': {'method': 'DELETE',
                    'path': '/v1/uploads',
                    'id_field': None,
                    'query': [],
                    'body': ['ids']},
 'list_fonts': {'method': 'GET', 'path': '/v1/fonts', 'id_field': None, 'query': [], 'body': None},
 'delete_fonts': {'method': 'DELETE',
                  'path': '/v1/fonts',
                  'id_field': None,
                  'query': [],
                  'body': ['fonts']}}


class TemplatedNode(WorkflowNode):
    integration_type = "automation-templated"
    credential_provider_labels = {"templated": "Templated Account"}
    connection_evidence = ConnectionEvidence(noun="templates", operation="list_templates")

    @classmethod
    def get_config_model(cls):
        return TemplatedFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Templated API key")
        config = self.config.config
        route = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = route["path"]
        if route["id_field"]:
            path = path.replace("{id}", quote(values[route["id_field"]], safe=""))
        params = {k: str(values[k]).lower() if isinstance(values[k], bool) else values[k]
            for k in route["query"] if k in values}
        kwargs = {"params": params}
        if route["body"] is not None:
            kwargs["json"] = {k: values[k] for k in route["body"] if k in values}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(route["method"], BASE_URL + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key,
                    "Content-Type": "application/json", "Accept": "application/json"}, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            message = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"Templated HTTP {response.status_code}: {message}") from None
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("Expected a JSON object or array from Templated")
        if isinstance(body, dict) and (body.get("error") or body.get("errors")):
            raise ValueError(str(body).replace(self.config.credentials.api_key, "[redacted]"))
        return {"status": "success", "data": body}
