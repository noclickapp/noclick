"""Frame.io V4 account, project, folder, file, comment and share automation.

Contract: https://api.frame.io/v4/openapi.json (v4.0).
Authentication: https://developer.frame.io/platform/docs/guides/authentication/overview
Lists expose one page and a provider cursor; writes send once without retries.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit, parse_qs, unquote
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.frame.io"
NODE_TYPE = "automation-frame-io-v4"
# Adobe cloud-storage IDs are valid too, including their colon/pipe syntax.
ID = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"^[^\s/?#\\]+$")]
UUID = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]


class FrameIoV4TokenCredential(BaseModel):
    model_config = ConfigDict(title="Frame.io V4 Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.frame.io/platform/docs/guides/authentication/overview",
            "x-credential-instructions": "Paste an existing Adobe IMS access token for Frame.io V4. Access tokens typically expire after one hour; replace the token when it expires. NoClick does not refresh it. For an eligible auto-migrated account using a legacy developer token, enable Legacy developer token to send the required x-frameio-legacy-token-auth header. Frame.io account roles determine read and write access. Connection verification reads the current user."
        })
    credential_type: Literal["frame_io_v4_token"] = Field("frame_io_v4_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=16384, title="Access token", json_schema_extra={"ui:widget": "password"})
    legacy_developer_token: Literal["false", "true"] = Field("false", title="Legacy developer token", json_schema_extra={"enumNames": ["No (Adobe IMS access token)", "Yes (eligible legacy developer token)"]})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste only the access token, without a Bearer header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segments(cls, value, info):
        if info.field_name.endswith("_id") and value in {".", ".."}:
            raise ValueError("Use a resource ID, not a path segment")
        return value

    @model_validator(mode="after")
    def update_fields(self):
        if self.operation.startswith("update_"):
            names = BODY_FIELDS[self.operation]
            if not any(getattr(self, name, None) is not None for name in names):
                raise ValueError("Supply at least one field to update")
        return self


class GetCurrentUserConfig(_Input):
    """Show user."""
    operation: Literal['get_current_user'] = Field('get_current_user', title='Show user', json_schema_extra={"ui:hidden": True})


class ListAccountsConfig(_Input):
    """List accounts. Returns one page; pass next_after to after for more."""
    operation: Literal['list_accounts'] = Field('list_accounts', title='List accounts', json_schema_extra={"ui:hidden": True})
    sort: Optional[Literal['display_name_asc', 'created_at_asc', 'display_name_desc', 'created_at_desc']] = Field(None, description='Sort by query parameter for accounts')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=100, description='Page size query param for requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')


class ListWorkspacesConfig(_Input):
    """List workspaces. Returns one page; pass next_after to after for more."""
    operation: Literal['list_workspaces'] = Field('list_workspaces', title='List workspaces', json_schema_extra={"ui:hidden": True})
    account_id: ID
    sort: Optional[Literal['name_asc', 'created_at_asc', 'name_desc', 'created_at_desc']] = Field(None, description='Sort query parameter for workspaces')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=100, description='Page size query param for requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')
    include: Optional[Literal['creator']] = Field(None, description='Include query parameter for workspaces')


class ListProjectsConfig(_Input):
    """List projects. Returns one page; pass next_after to after for more."""
    operation: Literal['list_projects'] = Field('list_projects', title='List projects', json_schema_extra={"ui:hidden": True})
    account_id: ID
    workspace_id: UUID
    sort: Optional[Literal['name_asc', 'created_at_asc', 'name_desc', 'created_at_desc']] = Field(None, description='Sort query parameter for projects')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=100, description='Page size query param for requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')
    include: Optional[Literal['owner']] = Field(None, description='Include query parameter for projects')


class GetProjectConfig(_Input):
    """Show project."""
    operation: Literal['get_project'] = Field('get_project', title='Show project', json_schema_extra={"ui:hidden": True})
    account_id: ID
    project_id: ID
    include: Optional[Literal['owner']] = Field(None, description='Include query parameter for projects')


class CreateProjectConfig(_Input):
    """Create project."""
    operation: Literal['create_project'] = Field('create_project', title='Create project', json_schema_extra={"ui:hidden": True})
    account_id: ID
    workspace_id: UUID
    name: str = Field(..., min_length=1, max_length=255, description='Project Name')
    restricted: Optional[StrictBool] = Field(None, description='Whether the project is restricted or not')


class UpdateProjectConfig(_Input):
    """Update project."""
    operation: Literal['update_project'] = Field('update_project', title='Update project', json_schema_extra={"ui:hidden": True})
    account_id: ID
    project_id: ID
    name: Optional[str] = Field(None, min_length=1, max_length=255, description='Project Name')
    restricted: Optional[StrictBool] = Field(None, description='Whether the project is restricted or not')
    status: Optional[Literal['active', 'inactive']] = Field(None, description='Project Status')


class DeleteProjectConfig(_Input):
    """Delete project."""
    operation: Literal['delete_project'] = Field('delete_project', title='Delete project', json_schema_extra={"ui:hidden": True})
    account_id: ID
    project_id: ID


class ListFolderChildrenConfig(_Input):
    """List folder children. Returns one page; pass next_after to after for more."""
    operation: Literal['list_folder_children'] = Field('list_folder_children', title='List folder children', json_schema_extra={"ui:hidden": True})
    account_id: ID
    folder_id: ID
    sort: Optional[Literal['name_asc', 'created_at_asc', 'updated_at_asc', 'name_desc', 'created_at_desc', 'updated_at_desc']] = Field(None, description='Sort by query parameter for folders')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=500, description='Page size query param for asset list requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')
    include: Optional[Literal['media_links.original', 'media_links.thumbnail', 'media_links.thumbnail_high_quality', 'media_links.video_h264_180', 'media_links.high_quality', 'media_links.efficient', 'media_links.scrub_sheet', 'media_links.hls_manifest', 'creator', 'project', 'metadata']] = Field(None, description='Supported include query parameter values for endpoints that return files with media links')


class ListFoldersConfig(_Input):
    """List folders. Returns one page; pass next_after to after for more."""
    operation: Literal['list_folders'] = Field('list_folders', title='List folders', json_schema_extra={"ui:hidden": True})
    account_id: ID
    folder_id: ID
    sort: Optional[Literal['name_asc', 'created_at_asc', 'updated_at_asc', 'name_desc', 'created_at_desc', 'updated_at_desc']] = Field(None, description='Sort by query parameter for folders')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=500, description='Page size query param for asset list requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')
    include: Optional[Literal['creator', 'project', 'metadata']] = Field(None, description='Include query parameter for assets')


class CreateFolderConfig(_Input):
    """Create folder."""
    operation: Literal['create_folder'] = Field('create_folder', title='Create folder', json_schema_extra={"ui:hidden": True})
    account_id: ID
    folder_id: ID
    name: str = Field(..., min_length=1, max_length=255, description='Folder name')


class GetFolderConfig(_Input):
    """Show folder."""
    operation: Literal['get_folder'] = Field('get_folder', title='Show folder', json_schema_extra={"ui:hidden": True})
    account_id: ID
    folder_id: ID
    include: Optional[Literal['creator', 'project', 'metadata']] = Field(None, description='Include query parameter for assets')


class UpdateFolderConfig(_Input):
    """Update folder."""
    operation: Literal['update_folder'] = Field('update_folder', title='Update folder', json_schema_extra={"ui:hidden": True})
    account_id: ID
    folder_id: ID
    name: Optional[str] = Field(None, min_length=1, max_length=255, description='Folder name')


class DeleteFolderConfig(_Input):
    """Delete folder."""
    operation: Literal['delete_folder'] = Field('delete_folder', title='Delete folder', json_schema_extra={"ui:hidden": True})
    account_id: ID
    folder_id: ID


class ListFilesConfig(_Input):
    """List files. Returns one page; pass next_after to after for more."""
    operation: Literal['list_files'] = Field('list_files', title='List files', json_schema_extra={"ui:hidden": True})
    account_id: ID
    folder_id: ID
    sort: Optional[Literal['name_asc', 'created_at_asc', 'updated_at_asc', 'file_size_asc', 'name_desc', 'created_at_desc', 'updated_at_desc', 'file_size_desc']] = Field(None, description='Sort by query parameter for files')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=500, description='Page size query param for asset list requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')
    include: Optional[Literal['media_links.original', 'media_links.thumbnail', 'media_links.thumbnail_high_quality', 'media_links.video_h264_180', 'media_links.high_quality', 'media_links.efficient', 'media_links.scrub_sheet', 'media_links.hls_manifest', 'creator', 'project', 'metadata']] = Field(None, description='Supported include query parameter values for endpoints that return files with media links')


class GetFileConfig(_Input):
    """Show file."""
    operation: Literal['get_file'] = Field('get_file', title='Show file', json_schema_extra={"ui:hidden": True})
    account_id: ID
    file_id: ID
    include: Optional[Literal['parent', 'media_links.original', 'media_links.thumbnail', 'media_links.thumbnail_high_quality', 'media_links.video_h264_180', 'media_links.high_quality', 'media_links.efficient', 'media_links.scrub_sheet', 'media_links.hls_manifest', 'creator', 'project', 'metadata']] = Field(None, description='Supported include query parameter values for showing a single file')


class UpdateFileConfig(_Input):
    """Update file."""
    operation: Literal['update_file'] = Field('update_file', title='Update file', json_schema_extra={"ui:hidden": True})
    account_id: ID
    file_id: ID
    name: Optional[str] = Field(None, min_length=1, max_length=255, description='File name')


class DeleteFileConfig(_Input):
    """Delete file."""
    operation: Literal['delete_file'] = Field('delete_file', title='Delete file', json_schema_extra={"ui:hidden": True})
    account_id: ID
    file_id: ID


class ListCommentsConfig(_Input):
    """List comments. Returns one page; pass next_after to after for more."""
    operation: Literal['list_comments'] = Field('list_comments', title='List comments', json_schema_extra={"ui:hidden": True})
    account_id: ID
    file_id: ID
    timestamp_as_timecode: Optional[StrictBool] = Field(None, description='Enables display of timestamp as timecode (HH:MM:SS:FF) when true')
    sort: Optional[Literal['owner_asc', 'owner_desc', 'completed_at_asc', 'completed_at_desc', 'created_at_asc', 'created_at_desc']] = Field(None, description='Sort query parameter for comments. Include query params for owner is required when sorting by owner.')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=100, description='Page size query param for requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')
    include: Optional[Literal['owner', 'replies']] = Field(None, description='Include query parameter for comments')


class GetCommentConfig(_Input):
    """Show comment."""
    operation: Literal['get_comment'] = Field('get_comment', title='Show comment', json_schema_extra={"ui:hidden": True})
    account_id: ID
    comment_id: UUID
    timestamp_as_timecode: Optional[StrictBool] = Field(None, description='Enables display of timestamp as timecode (HH:MM:SS:FF) when true')
    include: Optional[Literal['owner', 'replies']] = Field(None, description='Include query parameter for comments')


class CreateCommentConfig(_Input):
    """Create comment."""
    operation: Literal['create_comment'] = Field('create_comment', title='Create comment', json_schema_extra={"ui:hidden": True})
    account_id: ID
    file_id: ID
    timestamp_as_timecode: Optional[StrictBool] = Field(None, description='Enables display of timestamp as timecode (HH:MM:SS:FF) when true')
    completed: Optional[StrictBool] = Field(None, description='Comment completion status')
    text: str = Field(..., min_length=1, max_length=40000, description='Comment text (required)')
    timestamp: Optional[int] = Field(None, ge=0, description='Comment frame number for audio, stream or video media.')


class UpdateCommentConfig(_Input):
    """Update comment."""
    operation: Literal['update_comment'] = Field('update_comment', title='Update comment', json_schema_extra={"ui:hidden": True})
    account_id: ID
    comment_id: UUID
    timestamp_as_timecode: Optional[StrictBool] = Field(None, description='Enables display of timestamp as timecode (HH:MM:SS:FF) when true')
    completed: Optional[StrictBool] = Field(None, description='Comment completion status')
    text: Optional[str] = Field(None, min_length=1, max_length=40000, description='Comment text')
    timestamp: Optional[int] = Field(None, ge=0, description='Comment frame number for audio, stream or video media.')


class DeleteCommentConfig(_Input):
    """Delete comment."""
    operation: Literal['delete_comment'] = Field('delete_comment', title='Delete comment', json_schema_extra={"ui:hidden": True})
    account_id: ID
    comment_id: UUID


class ListSharesConfig(_Input):
    """List shares. Returns one page; pass next_after to after for more."""
    operation: Literal['list_shares'] = Field('list_shares', title='List shares', json_schema_extra={"ui:hidden": True})
    account_id: ID
    project_id: ID
    sort: Optional[Literal['name_asc', 'created_at_asc', 'name_desc', 'created_at_desc']] = Field(None, description='Sort query parameter for shares')
    after: Optional[str] = Field(None, min_length=1, max_length=8192, description='Opaque Cursor query param for requests returning paginated results.\n<br/>\nNOTE: this value is auto-generated and included as part of links from a previous response. It is not intended to be human readable.\n')
    page_size: int = Field(50, ge=1, le=100, description='Page size query param for requests')
    include_total_count: Optional[StrictBool] = Field(None, description='Page query param to include the count of all entities')


class GetShareConfig(_Input):
    """Show Share."""
    operation: Literal['get_share'] = Field('get_share', title='Show Share', json_schema_extra={"ui:hidden": True})
    account_id: ID
    share_id: UUID


FrameIoV4Config = Annotated[Union[GetCurrentUserConfig, ListAccountsConfig, ListWorkspacesConfig, ListProjectsConfig, GetProjectConfig, CreateProjectConfig, UpdateProjectConfig, DeleteProjectConfig, ListFolderChildrenConfig, ListFoldersConfig, CreateFolderConfig, GetFolderConfig, UpdateFolderConfig, DeleteFolderConfig, ListFilesConfig, GetFileConfig, UpdateFileConfig, DeleteFileConfig, ListCommentsConfig, GetCommentConfig, CreateCommentConfig, UpdateCommentConfig, DeleteCommentConfig, ListSharesConfig, GetShareConfig], Field(discriminator="operation")]


class FrameIoV4NodeConfig(NodeConfig[FrameIoV4Config, FrameIoV4TokenCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/v4/me'), 'list_accounts': ('GET', '/v4/accounts'), 'list_workspaces': ('GET', '/v4/accounts/{account_id}/workspaces'), 'list_projects': ('GET', '/v4/accounts/{account_id}/workspaces/{workspace_id}/projects'), 'get_project': ('GET', '/v4/accounts/{account_id}/projects/{project_id}'), 'create_project': ('POST', '/v4/accounts/{account_id}/workspaces/{workspace_id}/projects'), 'update_project': ('PATCH', '/v4/accounts/{account_id}/projects/{project_id}'), 'delete_project': ('DELETE', '/v4/accounts/{account_id}/projects/{project_id}'), 'list_folder_children': ('GET', '/v4/accounts/{account_id}/folders/{folder_id}/children'), 'list_folders': ('GET', '/v4/accounts/{account_id}/folders/{folder_id}/folders'), 'create_folder': ('POST', '/v4/accounts/{account_id}/folders/{folder_id}/folders'), 'get_folder': ('GET', '/v4/accounts/{account_id}/folders/{folder_id}'), 'update_folder': ('PATCH', '/v4/accounts/{account_id}/folders/{folder_id}'), 'delete_folder': ('DELETE', '/v4/accounts/{account_id}/folders/{folder_id}'), 'list_files': ('GET', '/v4/accounts/{account_id}/folders/{folder_id}/files'), 'get_file': ('GET', '/v4/accounts/{account_id}/files/{file_id}'), 'update_file': ('PATCH', '/v4/accounts/{account_id}/files/{file_id}'), 'delete_file': ('DELETE', '/v4/accounts/{account_id}/files/{file_id}'), 'list_comments': ('GET', '/v4/accounts/{account_id}/files/{file_id}/comments'), 'get_comment': ('GET', '/v4/accounts/{account_id}/comments/{comment_id}'), 'create_comment': ('POST', '/v4/accounts/{account_id}/files/{file_id}/comments'), 'update_comment': ('PATCH', '/v4/accounts/{account_id}/comments/{comment_id}'), 'delete_comment': ('DELETE', '/v4/accounts/{account_id}/comments/{comment_id}'), 'list_shares': ('GET', '/v4/accounts/{account_id}/projects/{project_id}/shares'), 'get_share': ('GET', '/v4/accounts/{account_id}/shares/{share_id}')}
BODY_FIELDS = {'create_project': ['name', 'restricted'], 'update_project': ['name', 'restricted', 'status'], 'create_folder': ['name'], 'update_folder': ['name'], 'update_file': ['name'], 'create_comment': ['completed', 'text', 'timestamp'], 'update_comment': ['completed', 'text', 'timestamp']}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class FrameIoV4Node(WorkflowNode):
    integration_type = "automation-frame-io-v4"
    connection_evidence = ConnectionEvidence(noun="user", identity_operation="get_current_user", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return FrameIoV4NodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Frame.io V4 access token")
        config = self.config.config
        credential = self.config.credentials
        token = credential.api_token
        method, route = ROUTES[config.operation]
        fields = config.model_dump(exclude={"operation"}, exclude_none=True)
        for name in tuple(fields):
            if "{" + name + "}" in route:
                route = route.replace("{" + name + "}", quote(fields.pop(name), safe=""))
        body_names = BODY_FIELDS.get(config.operation, ())
        data = {name: fields.pop(name) for name in body_names if name in fields}
        if config.operation == "list_comments" and fields.get("sort") in {"owner_asc", "owner_desc"}:
            if fields.get("include") not in {None, "owner"}:
                raise ValueError("Sorting comments by owner requires include=owner")
            fields["include"] = "owner"
        params = {name: str(value).lower() if isinstance(value, bool) else value for name, value in fields.items()}
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if credential.legacy_developer_token == "true":
            headers["x-frameio-legacy-token-auth"] = "true"
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, headers=headers, params=params,
                    **({"json": {"data": data}} if body_names else {}))
        except httpx.TransportError:
            raise ValueError("Frame.io request did not complete" + ("; the write outcome is unknown, inspect before retrying" if writing else "")) from None
        if response.status_code not in {200, 201, 204}:
            # Provider rejection text is required by the manual-connect seam.
            text = response.text.replace(token, "[redacted]")[:1000]
            raise ValueError(f"Frame.io HTTP {response.status_code}: {text}")
        if method == "DELETE":
            if response.status_code != 204:
                raise ValueError("Frame.io did not acknowledge deletion; inspect before retrying")
            output = {"status": "success", "http_status": 204, "deletion_acknowledged": True}
        else:
            if len(response.content) > 10_000_000 or "application/json" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("Expected bounded JSON from Frame.io" + ("; inspect the write before retrying" if writing else ""))
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Frame.io returned invalid JSON" + ("; inspect the write before retrying" if writing else "")) from None
            if not isinstance(body, dict) or "error" in body or "errors" in body or "data" not in body:
                raise ValueError("Frame.io returned an unexpected envelope" + ("; inspect the write before retrying" if writing else ""))
            output = {"status": "success", "http_status": response.status_code, "data": body["data"]}
            if config.operation.startswith("list_"):
                if not isinstance(body["data"], list) or any(not isinstance(item, dict) for item in body["data"]):
                    raise ValueError("Frame.io returned an invalid resource list")
                links = body.get("links")
                if not isinstance(links, dict) or "next" not in links:
                    raise ValueError("Frame.io pagination links are missing")
                following = links["next"]
                after = None
                if following is not None:
                    if not isinstance(following, str):
                        raise ValueError("Frame.io returned an invalid next-page link")
                    parsed = urlsplit(following)
                    # Never follow provider URLs. Reconstruct the fixed route with
                    # the cursor, retaining the original filters and page size.
                    trusted = parsed.scheme in {"", "https"} and parsed.netloc in {"", "api.frame.io"} and not parsed.fragment and unquote(parsed.path) == unquote(route)
                    query = parse_qs(parsed.query)
                    cursors = query.get("after", [])
                    if trusted and len(cursors) == 1 and cursors[0] and cursors[0] != getattr(config, "after", None):
                        after = cursors[0]
                output.update(items=body["data"], next_after=after, has_more=following is not None,
                    complete=following is None, continuation_available=after is not None, total_count=body.get("total_count"))
            elif not isinstance(body["data"], dict):
                raise ValueError("Frame.io returned an invalid resource" + ("; inspect the write before retrying" if writing else ""))
        output = _redact(output, token)
        await self.emit(output)
        return output
