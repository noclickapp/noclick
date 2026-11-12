"""ImageKit API v1: private-key media library, metadata and CDN operations.

Contract: https://github.com/imagekit-developer/openapi/blob/main/openapi.yml
Each operation maps to one API request. Lists return a single page; writes are
never retried automatically, and HTTP 207 is reported as partial success.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

ResourceID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class ImageKitAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Imagekit.io API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://imagekit.io/dashboard/developer/api-keys",
            "x-credential-instructions": "In the ImageKit dashboard, open Developer options → API keys. Paste a private API key with the read and write permissions your operations need. NoClick verifies access by listing your media library. Public keys do not authenticate server-side API calls.",
        })
    credential_type: Literal["imagekit_io_api_key"] = Field("imagekit_io_api_key", json_schema_extra={"ui:hidden": True})
    private_api_key: str = Field(..., min_length=1, max_length=4096, title="Private API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("private_api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Private API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value) or ":" in value:
            raise ValueError("Paste the private key without a header prefix, colon or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @field_validator("file", "url", check_fields=False)
    @classmethod
    def public_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or any(c.isspace() for c in value):
            raise ValueError("Use an absolute HTTP or HTTPS URL without credentials or a fragment")
        return value


class ImageKitListFilesConfig(_Input):
    """List and search a single page of assets."""
    operation: Literal["list_files"] = Field("list_files", json_schema_extra={"ui:hidden": True})
    type: Literal["file", "file-version", "folder", "all"] = "file"
    sort: Literal["ASC_NAME", "DESC_NAME", "ASC_CREATED", "DESC_CREATED", "ASC_UPDATED", "DESC_UPDATED", "ASC_SIZE", "DESC_SIZE"] = "ASC_CREATED"
    path: str | None = None
    search_query: str | None = None
    file_type: Literal["all", "image", "non-image"] = "all"
    limit: int = Field(100, ge=1, le=1000)
    skip: int = Field(0, ge=0)


class ImageKitUploadFileConfig(_Input):
    """Upload a publicly accessible URL; ImageKit fetches the source."""
    operation: Literal["upload_file"] = Field("upload_file", json_schema_extra={"ui:hidden": True})
    file: str = Field(..., description="Public HTTP or HTTPS source URL; fetched by ImageKit, not NoClick.")
    file_name: str = Field(..., min_length=1)
    folder: str = "/"
    use_unique_file_name: bool = Field(True, description="False replaces an existing file with the same name.")
    is_private_file: bool = False


class ImageKitGetFileConfig(_Input):
    """Read file details."""
    operation: Literal["get_file"] = Field("get_file", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID


class ImageKitUpdateFileConfig(_Input):
    """Update tags, description or existing custom metadata fields."""
    operation: Literal["update_file"] = Field("update_file", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID
    tags: list[str] | None = Field(None, description="Replaces tags; an empty list clears them.")
    description: str | None = None
    custom_metadata: dict[str, object] | None = Field(None, description="Existing metadata fields only; null values unset individual keys.")

    @model_validator(mode="after")
    def supplied(self):
        if self.tags is None and self.description is None and self.custom_metadata is None:
            raise ValueError("Supply tags, description or custom metadata to update")
        return self


class ImageKitDeleteFileConfig(_Input):
    """Permanently delete a file and all its versions."""
    operation: Literal["delete_file"] = Field("delete_file", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID


class ImageKitDeleteFilesConfig(_Input):
    """Permanently delete multiple files; inspect partial failures."""
    operation: Literal["delete_files"] = Field("delete_files", json_schema_extra={"ui:hidden": True})
    file_ids: list[ResourceID] = Field(..., min_length=1, max_length=100)


class ImageKitCopyFileConfig(_Input):
    """Copy a file to a destination folder."""
    operation: Literal["copy_file"] = Field("copy_file", json_schema_extra={"ui:hidden": True})
    source_file_path: str = Field(..., min_length=1)
    destination_path: str = Field(..., min_length=1)
    include_file_versions: bool = False


class ImageKitMoveFileConfig(_Input):
    """Move a file and all versions; existing destination files receive the versions."""
    operation: Literal["move_file"] = Field("move_file", json_schema_extra={"ui:hidden": True})
    source_file_path: str = Field(..., min_length=1)
    destination_path: str = Field(..., min_length=1)


class ImageKitRenameFileConfig(_Input):
    """Rename all versions; old URLs stop working outside CDN cache."""
    operation: Literal["rename_file"] = Field("rename_file", json_schema_extra={"ui:hidden": True})
    file_path: str = Field(..., min_length=1)
    new_file_name: str = Field(..., min_length=1)
    purge_cache: bool = False


class ImageKitListFileVersionsConfig(_Input):
    """List versions of a file."""
    operation: Literal["list_file_versions"] = Field("list_file_versions", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID


class ImageKitGetFileVersionConfig(_Input):
    """Read one file version."""
    operation: Literal["get_file_version"] = Field("get_file_version", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID
    version_id: ResourceID


class ImageKitDeleteFileVersionConfig(_Input):
    """Permanently delete one file version."""
    operation: Literal["delete_file_version"] = Field("delete_file_version", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID
    version_id: ResourceID


class ImageKitRestoreFileVersionConfig(_Input):
    """Restore a previous version as the current version."""
    operation: Literal["restore_file_version"] = Field("restore_file_version", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID
    version_id: ResourceID


class ImageKitAddTagsConfig(_Input):
    """Add tags to multiple files; inspect partial failures."""
    operation: Literal["add_tags"] = Field("add_tags", json_schema_extra={"ui:hidden": True})
    file_ids: list[ResourceID] = Field(..., min_length=1, max_length=100)
    tags: list[str] = Field(..., min_length=1)


class ImageKitRemoveTagsConfig(_Input):
    """Remove tags from multiple files; inspect partial failures."""
    operation: Literal["remove_tags"] = Field("remove_tags", json_schema_extra={"ui:hidden": True})
    file_ids: list[ResourceID] = Field(..., min_length=1, max_length=100)
    tags: list[str] = Field(..., min_length=1)


class ImageKitRemoveAiTagsConfig(_Input):
    """Remove AI tags from multiple files; inspect partial failures."""
    operation: Literal["remove_ai_tags"] = Field("remove_ai_tags", json_schema_extra={"ui:hidden": True})
    file_ids: list[ResourceID] = Field(..., min_length=1, max_length=100)
    ai_tags: list[str] = Field(..., min_length=1)


class ImageKitCreateFolderConfig(_Input):
    """Create a folder, including missing parent folders."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    folder_name: str = Field(..., min_length=1)
    parent_folder_path: str = Field(..., min_length=1)


class ImageKitDeleteFolderConfig(_Input):
    """Permanently delete a folder and every asset inside it."""
    operation: Literal["delete_folder"] = Field("delete_folder", json_schema_extra={"ui:hidden": True})
    folder_path: str = Field(..., min_length=1)


class ImageKitPurgeCacheConfig(_Input):
    """Request CDN cache invalidation; completion requires checking status."""
    operation: Literal["purge_cache"] = Field("purge_cache", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1)


class ImageKitGetPurgeStatusConfig(_Input):
    """Read cache invalidation status."""
    operation: Literal["get_purge_status"] = Field("get_purge_status", json_schema_extra={"ui:hidden": True})
    request_id: ResourceID


class ImageKitGetFileMetadataConfig(_Input):
    """Read embedded metadata from an uploaded file."""
    operation: Literal["get_file_metadata"] = Field("get_file_metadata", json_schema_extra={"ui:hidden": True})
    file_id: ResourceID


class ImageKitListCustomMetadataFieldsConfig(_Input):
    """List custom metadata field definitions."""
    operation: Literal["list_custom_metadata_fields"] = Field("list_custom_metadata_fields", json_schema_extra={"ui:hidden": True})


# ImageKit.io's own MCP server: agents get its tools through a person's ImageKit.io sign-in.
ImagekitIoMcpCredential = mcp_credential("imagekit_io", "https://imagekit.io/mcp/dam", app="ImageKit.io")
ImageKitCredential = Union[ImageKitAPIKeyCredential, ImagekitIoMcpCredential]


ImageKitOperation = Annotated[Union[
    ImageKitListFilesConfig,
    ImageKitUploadFileConfig,
    ImageKitGetFileConfig,
    ImageKitUpdateFileConfig,
    ImageKitDeleteFileConfig,
    ImageKitDeleteFilesConfig,
    ImageKitCopyFileConfig,
    ImageKitMoveFileConfig,
    ImageKitRenameFileConfig,
    ImageKitListFileVersionsConfig,
    ImageKitGetFileVersionConfig,
    ImageKitDeleteFileVersionConfig,
    ImageKitRestoreFileVersionConfig,
    ImageKitAddTagsConfig,
    ImageKitRemoveTagsConfig,
    ImageKitRemoveAiTagsConfig,
    ImageKitCreateFolderConfig,
    ImageKitDeleteFolderConfig,
    ImageKitPurgeCacheConfig,
    ImageKitGetPurgeStatusConfig,
    ImageKitGetFileMetadataConfig,
    ImageKitListCustomMetadataFieldsConfig
], Field(discriminator="operation")]


class ImageKitFullConfig(NodeConfig[ImageKitOperation, ImageKitCredential]):
    pass


ROUTES = {'list_files': {'method': 'GET',
                'path': '/v1/files',
                'path_fields': [],
                'query': ['type', 'sort', 'path', 'search_query', 'file_type', 'limit', 'skip'],
                'body': [],
                'wire': {'search_query': 'searchQuery', 'file_type': 'fileType'},
                'statuses': [200],
                'shape': 'list'},
 'upload_file': {'method': 'POST',
                 'path': '/api/v1/files/upload',
                 'path_fields': [],
                 'query': [],
                 'body': ['file', 'file_name', 'folder', 'use_unique_file_name', 'is_private_file'],
                 'wire': {'file_name': 'fileName',
                          'use_unique_file_name': 'useUniqueFileName',
                          'is_private_file': 'isPrivateFile'},
                 'statuses': [200],
                 'shape': 'object'},
 'get_file': {'method': 'GET',
              'path': '/v1/files/{file_id}/details',
              'path_fields': ['file_id'],
              'query': [],
              'body': [],
              'wire': {},
              'statuses': [200],
              'shape': 'object'},
 'update_file': {'method': 'PATCH',
                 'path': '/v1/files/{file_id}/details',
                 'path_fields': ['file_id'],
                 'query': [],
                 'body': ['tags', 'description', 'custom_metadata'],
                 'wire': {'custom_metadata': 'customMetadata'},
                 'statuses': [200],
                 'shape': 'object'},
 'delete_file': {'method': 'DELETE',
                 'path': '/v1/files/{file_id}',
                 'path_fields': ['file_id'],
                 'query': [],
                 'body': [],
                 'wire': {},
                 'statuses': [204],
                 'shape': 'empty'},
 'delete_files': {'method': 'POST',
                  'path': '/v1/files/batch/deleteByFileIds',
                  'path_fields': [],
                  'query': [],
                  'body': ['file_ids'],
                  'wire': {'file_ids': 'fileIds'},
                  'statuses': [200, 207],
                  'shape': 'object'},
 'copy_file': {'method': 'POST',
               'path': '/v1/files/copy',
               'path_fields': [],
               'query': [],
               'body': ['source_file_path', 'destination_path', 'include_file_versions'],
               'wire': {'source_file_path': 'sourceFilePath',
                        'destination_path': 'destinationPath',
                        'include_file_versions': 'includeFileVersions'},
               'statuses': [204],
               'shape': 'empty'},
 'move_file': {'method': 'POST',
               'path': '/v1/files/move',
               'path_fields': [],
               'query': [],
               'body': ['source_file_path', 'destination_path'],
               'wire': {'source_file_path': 'sourceFilePath', 'destination_path': 'destinationPath'},
               'statuses': [204],
               'shape': 'empty'},
 'rename_file': {'method': 'PUT',
                 'path': '/v1/files/rename',
                 'path_fields': [],
                 'query': [],
                 'body': ['file_path', 'new_file_name', 'purge_cache'],
                 'wire': {'file_path': 'filePath', 'new_file_name': 'newFileName', 'purge_cache': 'purgeCache'},
                 'statuses': [200, 207],
                 'shape': 'object'},
 'list_file_versions': {'method': 'GET',
                        'path': '/v1/files/{file_id}/versions',
                        'path_fields': ['file_id'],
                        'query': [],
                        'body': [],
                        'wire': {},
                        'statuses': [200],
                        'shape': 'list'},
 'get_file_version': {'method': 'GET',
                      'path': '/v1/files/{file_id}/versions/{version_id}',
                      'path_fields': ['file_id', 'version_id'],
                      'query': [],
                      'body': [],
                      'wire': {},
                      'statuses': [200],
                      'shape': 'object'},
 'delete_file_version': {'method': 'DELETE',
                         'path': '/v1/files/{file_id}/versions/{version_id}',
                         'path_fields': ['file_id', 'version_id'],
                         'query': [],
                         'body': [],
                         'wire': {},
                         'statuses': [204],
                         'shape': 'empty'},
 'restore_file_version': {'method': 'PUT',
                          'path': '/v1/files/{file_id}/versions/{version_id}/restore',
                          'path_fields': ['file_id', 'version_id'],
                          'query': [],
                          'body': [],
                          'wire': {},
                          'statuses': [200],
                          'shape': 'object'},
 'add_tags': {'method': 'POST',
              'path': '/v1/files/addTags',
              'path_fields': [],
              'query': [],
              'body': ['file_ids', 'tags'],
              'wire': {'file_ids': 'fileIds'},
              'statuses': [200, 207],
              'shape': 'object'},
 'remove_tags': {'method': 'POST',
                 'path': '/v1/files/removeTags',
                 'path_fields': [],
                 'query': [],
                 'body': ['file_ids', 'tags'],
                 'wire': {'file_ids': 'fileIds'},
                 'statuses': [200, 207],
                 'shape': 'object'},
 'remove_ai_tags': {'method': 'POST',
                    'path': '/v1/files/removeAITags',
                    'path_fields': [],
                    'query': [],
                    'body': ['file_ids', 'ai_tags'],
                    'wire': {'file_ids': 'fileIds', 'ai_tags': 'AITags'},
                    'statuses': [200, 207],
                    'shape': 'object'},
 'create_folder': {'method': 'POST',
                   'path': '/v1/folder',
                   'path_fields': [],
                   'query': [],
                   'body': ['folder_name', 'parent_folder_path'],
                   'wire': {'folder_name': 'folderName', 'parent_folder_path': 'parentFolderPath'},
                   'statuses': [201],
                   'shape': 'object'},
 'delete_folder': {'method': 'DELETE',
                   'path': '/v1/folder',
                   'path_fields': [],
                   'query': [],
                   'body': ['folder_path'],
                   'wire': {'folder_path': 'folderPath'},
                   'statuses': [204],
                   'shape': 'empty'},
 'purge_cache': {'method': 'POST',
                 'path': '/v1/files/purge',
                 'path_fields': [],
                 'query': [],
                 'body': ['url'],
                 'wire': {},
                 'statuses': [201],
                 'shape': 'object'},
 'get_purge_status': {'method': 'GET',
                      'path': '/v1/files/purge/{request_id}',
                      'path_fields': ['request_id'],
                      'query': [],
                      'body': [],
                      'wire': {},
                      'statuses': [200],
                      'shape': 'object'},
 'get_file_metadata': {'method': 'GET',
                       'path': '/v1/files/{file_id}/metadata',
                       'path_fields': ['file_id'],
                       'query': [],
                       'body': [],
                       'wire': {},
                       'statuses': [200],
                       'shape': 'object'},
 'list_custom_metadata_fields': {'method': 'GET',
                                 'path': '/v1/customMetadataFields',
                                 'path_fields': [],
                                 'query': [],
                                 'body': [],
                                 'wire': {},
                                 'statuses': [200],
                                 'shape': 'list'}}


class ImageKitNode(WorkflowNode):
    integration_type = "automation-imagekit-io"
    credential_provider_labels = {"imagekit_io": "ImageKit.io Account"}
    connection_evidence = ConnectionEvidence(noun="media assets", operation="list_files")

    @classmethod
    def get_config_model(cls):
        return ImageKitFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an ImageKit private API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for field in route["path_fields"]:
            path = path.replace("{" + field + "}", quote(values[field], safe=""))
        key = self.config.credentials.private_api_key
        encoded = base64.b64encode((key + ":").encode()).decode()
        headers = {"Authorization": "Basic " + encoded, "Accept": "application/json"}
        kwargs = {"headers": headers}
        if route["query"]:
            kwargs["params"] = {route["wire"].get(f, f): values[f] for f in route["query"] if f in values}
        if route["body"]:
            body = {route["wire"].get(f, f): values[f] for f in route["body"] if f in values}
            if config.operation == "upload_file":
                kwargs["files"] = {f: (None, str(v).lower() if isinstance(v, bool) else str(v)) for f, v in body.items()}
            else:
                kwargs["json"] = body
        origin = "https://upload.imagekit.io" if config.operation == "upload_file" else "https://api.imagekit.io"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], origin + path, **kwargs)
        except httpx.HTTPError:
            return {"status": "error", "error": "ImageKit request could not be confirmed; inspect the asset before retrying a write"}
        def redact(value):
            if isinstance(value, str):
                return value.replace(key, "[redacted]").replace(encoded, "[redacted]")
            if isinstance(value, dict):
                return {redact(k): redact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value
        if response.status_code not in route["statuses"]:
            return {"status": "error", "http_status": response.status_code,
                "error": redact(response.text)[:4000] or "ImageKit rejected the request"}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "data": None}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "ImageKit returned invalid JSON"}
        if not isinstance(data, list if route["shape"] == "list" else dict):
            return {"status": "error", "http_status": response.status_code, "error": "ImageKit returned an unexpected response shape"}
        result = {"status": "partial" if response.status_code == 207 else "success", "http_status": response.status_code, "data": redact(data)}
        if config.operation == "list_files":
            result["pagination"] = {"limit": config.limit, "skip": config.skip,
                "next_skip": config.skip + len(data) if len(data) == config.limit else None}
        return result
