"""Docupilot V2 APIs, pinned to the provider's published 3.0 contract.

One operation makes one request. List reads return a single page and never
follow provider-supplied URLs. Generation can run configured deliveries.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import re
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api-us1.docupilot.app"
AUTH_DOCS = "https://help.docupilot.app/developers/api-overview"


class DocupilotAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Docupilot API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOCS,
            "x-credential-instructions": "In Docupilot Settings > API Settings, create a key and secret and base64 encode key:secret as described in the API guide. Paste that encoded token without an authorization prefix. The published V2 schema specifies Authorization: Basic. Copy the workspace ID from Settings > Workspace details. Requests go to the US API server."})
    credential_type: Literal["docupilot_api_token"] = Field("docupilot_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Encoded API token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})
    workspace_id: str = Field(..., title="Workspace ID", min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Encoded API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the encoded token without a prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="One page per call. Increment when the response's next field is non-null.")
    ordering: str | None = Field(None, max_length=255)


class _Template(_Input):
    template_id: int = Field(..., ge=1, title="Template ID")


class _Block(_Input):
    content_block_id: int = Field(..., ge=1, title="Content block ID")


class _Folder(_Input):
    folder_id: int = Field(..., ge=1, title="Folder ID")


class GetCurrentOrganizationConfig(_Input):
    """Get current organization."""
    operation: Literal["get_current_organization"] = Field("get_current_organization", json_schema_extra={"ui:hidden": True})


class GetMeConfig(_Input):
    """Get me."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class ListContentBlocksConfig(_Page):
    """List content blocks."""
    operation: Literal["list_content_blocks"] = Field("list_content_blocks", json_schema_extra={"ui:hidden": True})
    search: str | None = None


class GetContentBlockConfig(_Block):
    """Get content block."""
    operation: Literal["get_content_block"] = Field("get_content_block", json_schema_extra={"ui:hidden": True})


class DeleteContentBlockConfig(_Block):
    """Delete content block."""
    operation: Literal["delete_content_block"] = Field("delete_content_block", json_schema_extra={"ui:hidden": True})


class CopyContentBlockConfig(_Block):
    """Copy content block."""
    operation: Literal["copy_content_block"] = Field("copy_content_block", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    key: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=255)


class ListFoldersConfig(_Input):
    """List folders."""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})
    ordering: str | None = None
    permission: Literal["manage", "read", "write"] | None = None


class CreateFolderConfig(_Input):
    """Create folder."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=50)


class UpdateFolderConfig(_Folder):
    """Update folder."""
    operation: Literal["update_folder"] = Field("update_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=50)


class DeleteFolderConfig(_Folder):
    """Delete folder."""
    operation: Literal["delete_folder"] = Field("delete_folder", json_schema_extra={"ui:hidden": True})


class GetCreatedDocumentsHistoryConfig(_Page):
    """Get created documents history."""
    operation: Literal["get_created_documents_history"] = Field("get_created_documents_history", json_schema_extra={"ui:hidden": True})


class ListTemplatesConfig(_Page):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    folder: int | None = Field(None, ge=1)
    status: Literal["active", "test"] | None = None
    output_type: Literal["docx", "html", "jpeg", "pdf", "png", "pptx", "xlsx"] | None = None
    type: Literal["docx", "dpt_html", "dpt_pdf", "fillable_pdf", "g_document", "g_presentation", "g_spreadsheet", "html", "pptx", "xlsx"] | None = None


class GetTemplateConfig(_Template):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class TrashTemplateConfig(_Template):
    """Trash template."""
    operation: Literal["trash_template"] = Field("trash_template", json_schema_extra={"ui:hidden": True})


class CopyTemplateConfig(_Template):
    """Copy template."""
    operation: Literal["copy_template"] = Field("copy_template", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=255)
    folder: int | None = Field(None, ge=1, description="Destination folder; null copies to the workspace root.")


class GenerateDocumentConfig(_Template):
    """Generate document."""
    operation: Literal["generate_document"] = Field("generate_document", json_schema_extra={"ui:hidden": True})
    data: dict = Field(default_factory=dict, description="Template merge data. This may trigger the template's configured deliveries.")
    output_type: Literal["docx", "html", "pdf", "png", "pptx", "xlsx"] | None = None
    version: str | None = Field(None, description="Numeric version ID, latest, or live.")
    includeUrl: bool | None = None


class PublishLatestTemplateVersionConfig(_Template):
    """Publish latest template version."""
    operation: Literal["publish_latest_template_version"] = Field("publish_latest_template_version", json_schema_extra={"ui:hidden": True})


class RestoreTemplateFromTrashConfig(_Template):
    """Restore template from trash."""
    operation: Literal["restore_template_from_trash"] = Field("restore_template_from_trash", json_schema_extra={"ui:hidden": True})


class GetTemplateSchemaConfig(_Template):
    """Get template schema."""
    operation: Literal["get_template_schema"] = Field("get_template_schema", json_schema_extra={"ui:hidden": True})
    version_id: str | None = None


class TestDocumentGenerationConfig(_Template):
    """Test document generation."""
    operation: Literal["test_document_generation"] = Field("test_document_generation", json_schema_extra={"ui:hidden": True})
    data: dict = Field(default_factory=dict, description="Test merge data.")
    output_type: Literal["docx", "html", "pdf", "png", "pptx", "xlsx"] | None = None
    version_id: str | None = None
    use_data: bool | None = None


class GetTestDataConfig(_Template):
    """Get test data."""
    operation: Literal["get_test_data"] = Field("get_test_data", json_schema_extra={"ui:hidden": True})


class ListTemplateDeliveriesConfig(_Template):
    """List template deliveries."""
    operation: Literal["list_template_deliveries"] = Field("list_template_deliveries", json_schema_extra={"ui:hidden": True})
    ordering: str | None = None


class ListTemplateVersionsConfig(_Template, _Page):
    """List template versions."""
    operation: Literal["list_template_versions"] = Field("list_template_versions", json_schema_extra={"ui:hidden": True})
    search: str | None = None


DocupilotOperation = Annotated[Union[
    GetCurrentOrganizationConfig,
    GetMeConfig,
    ListContentBlocksConfig,
    GetContentBlockConfig,
    DeleteContentBlockConfig,
    CopyContentBlockConfig,
    ListFoldersConfig,
    CreateFolderConfig,
    UpdateFolderConfig,
    DeleteFolderConfig,
    GetCreatedDocumentsHistoryConfig,
    ListTemplatesConfig,
    GetTemplateConfig,
    TrashTemplateConfig,
    CopyTemplateConfig,
    GenerateDocumentConfig,
    PublishLatestTemplateVersionConfig,
    RestoreTemplateFromTrashConfig,
    GetTemplateSchemaConfig,
    TestDocumentGenerationConfig,
    GetTestDataConfig,
    ListTemplateDeliveriesConfig,
    ListTemplateVersionsConfig
], Field(discriminator="operation")]


class DocupilotNodeConfig(NodeConfig[DocupilotOperation, DocupilotAPITokenCredential]):
    pass


ROUTES = {'get_current_organization': {'method': 'GET',
                              'path': '/dashboard/accounts/v2/organization/current/',
                              'id_field': None,
                              'workspace': False,
                              'query': [],
                              'success': [200]},
 'get_me': {'method': 'GET',
            'path': '/dashboard/accounts/v2/users/me/',
            'id_field': None,
            'workspace': False,
            'query': [],
            'success': [200]},
 'list_content_blocks': {'method': 'GET',
                         'path': '/dashboard/api/v2/content_blocks/',
                         'id_field': None,
                         'workspace': True,
                         'query': ['ordering', 'page', 'search'],
                         'success': [200]},
 'get_content_block': {'method': 'GET',
                       'path': '/dashboard/api/v2/content_blocks/{id}/',
                       'id_field': 'content_block_id',
                       'workspace': True,
                       'query': [],
                       'success': [200]},
 'delete_content_block': {'method': 'DELETE',
                          'path': '/dashboard/api/v2/content_blocks/{id}/',
                          'id_field': 'content_block_id',
                          'workspace': True,
                          'query': [],
                          'success': [204]},
 'copy_content_block': {'method': 'POST',
                        'path': '/dashboard/api/v2/content_blocks/{id}/copy/',
                        'id_field': 'content_block_id',
                        'workspace': True,
                        'query': [],
                        'success': [201]},
 'list_folders': {'method': 'GET',
                  'path': '/dashboard/api/v2/folders/',
                  'id_field': None,
                  'workspace': True,
                  'query': ['ordering', 'permission'],
                  'success': [200]},
 'create_folder': {'method': 'POST',
                   'path': '/dashboard/api/v2/folders/',
                   'id_field': None,
                   'workspace': True,
                   'query': [],
                   'success': [201]},
 'update_folder': {'method': 'PUT',
                   'path': '/dashboard/api/v2/folders/{id}/',
                   'id_field': 'folder_id',
                   'workspace': True,
                   'query': [],
                   'success': [200]},
 'delete_folder': {'method': 'DELETE',
                   'path': '/dashboard/api/v2/folders/{id}/',
                   'id_field': 'folder_id',
                   'workspace': True,
                   'query': [],
                   'success': [204]},
 'get_created_documents_history': {'method': 'GET',
                                   'path': '/dashboard/api/v2/history/',
                                   'id_field': None,
                                   'workspace': True,
                                   'query': ['ordering', 'page'],
                                   'success': [200]},
 'list_templates': {'method': 'GET',
                    'path': '/dashboard/api/v2/templates/',
                    'id_field': None,
                    'workspace': True,
                    'query': ['delivery_type',
                              'folder',
                              'ordering',
                              'output_type',
                              'page',
                              'search',
                              'status',
                              'type'],
                    'success': [200]},
 'get_template': {'method': 'GET',
                  'path': '/dashboard/api/v2/templates/{id}/',
                  'id_field': 'template_id',
                  'workspace': True,
                  'query': [],
                  'success': [200]},
 'trash_template': {'method': 'DELETE',
                    'path': '/dashboard/api/v2/templates/{id}/',
                    'id_field': 'template_id',
                    'workspace': True,
                    'query': [],
                    'success': [204]},
 'copy_template': {'method': 'POST',
                   'path': '/dashboard/api/v2/templates/{id}/copy/',
                   'id_field': 'template_id',
                   'workspace': True,
                   'query': [],
                   'success': [201]},
 'generate_document': {'method': 'POST',
                       'path': '/dashboard/api/v2/templates/{id}/generate/',
                       'id_field': 'template_id',
                       'workspace': True,
                       'query': ['download', 'includeUrl', 'output_type', 'version'],
                       'success': [201]},
 'publish_latest_template_version': {'method': 'POST',
                                     'path': '/dashboard/api/v2/templates/{id}/publish/',
                                     'id_field': 'template_id',
                                     'workspace': True,
                                     'query': [],
                                     'success': [200]},
 'restore_template_from_trash': {'method': 'PUT',
                                 'path': '/dashboard/api/v2/templates/{id}/restore/',
                                 'id_field': 'template_id',
                                 'workspace': True,
                                 'query': [],
                                 'success': [200]},
 'get_template_schema': {'method': 'GET',
                         'path': '/dashboard/api/v2/templates/{id}/schema/',
                         'id_field': 'template_id',
                         'workspace': True,
                         'query': ['version_id'],
                         'success': [200]},
 'test_document_generation': {'method': 'POST',
                              'path': '/dashboard/api/v2/templates/{id}/test/',
                              'id_field': 'template_id',
                              'workspace': True,
                              'query': ['output_type', 'use_data', 'version_id'],
                              'success': [201]},
 'get_test_data': {'method': 'GET',
                   'path': '/dashboard/api/v2/templates/{id}/test_data/',
                   'id_field': 'template_id',
                   'workspace': True,
                   'query': [],
                   'success': [200]},
 'list_template_deliveries': {'method': 'GET',
                              'path': '/dashboard/api/v2/templates/{template_id}/deliveries/',
                              'id_field': 'template_id',
                              'workspace': True,
                              'query': ['ordering'],
                              'success': [200]},
 'list_template_versions': {'method': 'GET',
                            'path': '/dashboard/api/v2/templates/{template_id}/versions/',
                            'id_field': 'template_id',
                            'workspace': True,
                            'query': ['ordering', 'page', 'search'],
                            'success': [200]}}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


class DocupilotNode(WorkflowNode):
    integration_type = "automation-docupilot"
    connection_evidence = ConnectionEvidence(noun="Docupilot account", identity_operation="get_me",
        identity_keys=("email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return DocupilotNodeConfig

    @staticmethod
    def _guard_credential(config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type", "docupilot_api_token") != "docupilot_api_token":
            raise ValueError("Attach a Docupilot API token credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._guard_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._guard_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Docupilot API token")
        cfg = self.config.config
        cred = self.config.credentials
        route = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude_none=True)
        path = route["path"]
        if route["id_field"]:
            identifier = str(values[route["id_field"]])
            path = re.sub(r"\{[^}]+\}", identifier, path)
        headers = {"Authorization": "Basic " + cred.api_token, "Accept": "application/json"}
        if route["workspace"]:
            headers["X-Workspace"] = cred.workspace_id
        params = {k: ("true" if values[k] is True else "false" if values[k] is False else values[k])
                  for k in route["query"] if k in values}
        body = None
        if cfg.operation in {"generate_document", "test_document_generation"}:
            body = cfg.data
            if cfg.operation == "generate_document":
                # Keep the documented JSON response; never request a binary download.
                params["download"] = "false"
        elif cfg.operation in {"create_folder", "update_folder"}:
            body = {"name": cfg.name}
        elif cfg.operation == "copy_template":
            body = {"title": cfg.title, "folder": cfg.folder}
        elif cfg.operation == "copy_content_block":
            body = {"name": cfg.name, "key": cfg.key}
            if cfg.description is not None:
                body["description"] = cfg.description
        kwargs = {"params": params, "headers": headers}
        if body is not None:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], BASE_URL + path, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Docupilot request could not be confirmed; a write may already have completed") from None
        if response.status_code not in route["success"]:
            message = _redact(response.text[:2000], cred.api_token)
            raise ValueError(f"Docupilot HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Docupilot returned a non-JSON response") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("Docupilot returned an unexpected response shape")
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                raise ValueError("Docupilot: " + str(_redact(data, cred.api_token))[:2000])
        output = {"status": "success", "operation": cfg.operation, "data": _redact(data, cred.api_token)}
        if isinstance(data, dict) and "results" in data and "next" in data:
            output["next_page"] = cfg.page + 1 if data["next"] else None
        return output
