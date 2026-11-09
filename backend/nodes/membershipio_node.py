"""Membership.io API v2: audience management and content metadata.

The published contract uses the former Searchie hostname. Only its exact
Membership.io migration redirect is followed, with method and JSON preserved.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.searchie.io/api/v2"
MIGRATED_BASE = "https://app.membership.io/api/v2"



class MembershipioTokenCredential(BaseModel):
    model_config = ConfigDict(title="Membership.io Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.membership.io/getting-started-with-membership.io-authentication",
            "x-credential-instructions": "Paste an existing access token without Bearer. Follow Membership.io's authentication guide to generate one on app.membership.io; generating a new token revokes the previous one. NoClick does not collect your password or generate tokens."})
    credential_type: Literal["membershipio_token"] = Field("membershipio_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value



class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name in {"audience", "file"} and not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
            raise ValueError("Use a single resource ID or hash")
        return value



class AudienceAttribute(_Input):
    id: int = Field(..., ge=0)
    type: Literal["boolean", "date", "text", "number", "option", "multiple"]
    value: str



class GetProfile(_Input):
    """Get user profile."""
    operation: Literal["get_profile"] = Field("get_profile", title="Get Profile", json_schema_extra={"ui:hidden": True})


class AttachAudienceAchievements(_Input):
    """Attach achievements to an audience."""
    operation: Literal["attach_audience_achievements"] = Field("attach_audience_achievements", title="Attach Audience Achievements", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    achievements: list[int] = Field(..., description='Array of achievement IDs')


class ListAudienceAttributes(_Input):
    """Get attributes for a specific audience."""
    operation: Literal["list_audience_attributes"] = Field("list_audience_attributes", title="List Audience Attributes", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    limit: int | None = Field(None, ge=1, le=1000, description='Number of items per page (default: 30)')


class StoreAudienceAttributes(_Input):
    """Store audience attributes."""
    operation: Literal["store_audience_attributes"] = Field("store_audience_attributes", title="Store Audience Attributes", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    attributes: list[AudienceAttribute] = Field(..., description='Array of attributes to store or update')


class ListAudience(_Input):
    """Get a paginated list of audiences with optional filtering, sorting, and related resources."""
    operation: Literal["list_audience"] = Field("list_audience", title="List Audience", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=1000, description='Number of items per page')
    page: int | None = Field(None, ge=1, le=1000, description='Page number')
    sort: list[str] | None = Field(None, description='Sort the results by specific fields')
    include: list[str] | None = Field(None, description='Related resources to include (e.g., tags, hubs, achievements)')
    filter_id: int | None = Field(None, description='Filter by ID')
    filter_name: str | None = Field(None, description='Filter by name')
    filter_email: str | None = Field(None, description='Filter by email')
    filter_is_person: bool | None = Field(None, description='Filter by is_person')


class CreateAudience(_Input):
    """Create a new audience."""
    operation: Literal["create_audience"] = Field("create_audience", title="Create Audience", json_schema_extra={"ui:hidden": True})
    is_create_or_update: bool | None = Field(None, description='Update the matching audience if one exists instead of creating another.')
    tracking_id: str | None = Field(None, description='')
    email: str = Field(..., min_length=1, description='')
    name: str | None = Field(None, description='')
    phone: str | None = Field(None, description='')
    meta: list[str] | None = Field(None, description='')
    hubs: list[int] | None = Field(None, description='Hub IDs to grant access to.')
    notify: bool | None = Field(None, description='Request a notification email for the new audience. Delivery is controlled by Membership.io.')
    tags: list[str] | None = Field(None, description='Tags to attach to the audience.')
    remove_existing_tags: bool | None = Field(None, description='Replace existing tags with the supplied tags.')
    attributes: list[AudienceAttribute] | None = Field(None, description='Attribute values to store.')


class ListAudienceHubs(_Input):
    """Get hubs for an audience."""
    operation: Literal["list_audience_hubs"] = Field("list_audience_hubs", title="List Audience Hubs", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    includes: str | None = Field(None, description='Specify additional data to include (e.g., price)')


class AttachAudienceHubs(_Input):
    """Attach hubs to an audience."""
    operation: Literal["attach_audience_hubs"] = Field("attach_audience_hubs", title="Attach Audience Hubs", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    hubs: list[int] = Field(..., description='Array of hub IDs')


class DetachAudienceHubs(_Input):
    """Detach hubs from an audience."""
    operation: Literal["detach_audience_hubs"] = Field("detach_audience_hubs", title="Detach Audience Hubs", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    hubs: list[int] = Field(..., description='Array of hub IDs')


class ListAudienceTags(_Input):
    """Get all tags for audience."""
    operation: Literal["list_audience_tags"] = Field("list_audience_tags", title="List Audience Tags", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Search query for tags')
    limit: int | None = Field(None, ge=1, le=1000, description='Limit the number of results per page')
    sort: str | None = Field(None, description='Sort the results by specific fields (e.g., created_at,updated_at,name,audiences_count)')


class ListMemberTags(_Input):
    """Get tags associated with a specific audience."""
    operation: Literal["list_member_tags"] = Field("list_member_tags", title="List Member Tags", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='ID of the audience')


class AttachAudienceTags(_Input):
    """Attach tags to an audience."""
    operation: Literal["attach_audience_tags"] = Field("attach_audience_tags", title="Attach Audience Tags", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    tags: list[str] = Field(..., description='Array of tags')


class DetachAudienceTags(_Input):
    """Detach tags from an audience."""
    operation: Literal["detach_audience_tags"] = Field("detach_audience_tags", title="Detach Audience Tags", json_schema_extra={"ui:hidden": True})
    audience: str = Field(..., min_length=1, description='Hash ID of the audience')
    tags: list[str] = Field(..., description='Array of tags')


class ListAttributes(_Input):
    """Get a list of attributes."""
    operation: Literal["list_attributes"] = Field("list_attributes", title="List Attributes", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=1000, description='Number of items per page')
    filter_title: str | None = Field(None, description='Filter attributes by title')
    filter_type: str | None = Field(None, description='Filter attributes by type')
    sort: Literal['created_at', 'id', 'title', 'type', 'description'] | None = Field(None, description='Sort the results by a specific field (e.g., created_at, id, title)')
    order: Literal['asc', 'desc'] | None = Field(None, description='Sort order (asc or desc)')


class ListAchievements(_Input):
    """Get a list of achievements."""
    operation: Literal["list_achievements"] = Field("list_achievements", title="List Achievements", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=1000, description='Number of items per page')
    filter_id: int | None = Field(None, description='Filter achievements by ID')
    filter_title: str | None = Field(None, description='Filter achievements by title')
    filter_type: str | None = Field(None, description='Filter achievements by type')
    filter_criteria: str | None = Field(None, description='Filter achievements by criteria')
    sort: Literal['created_at', 'id', 'title', 'description', 'criteria'] | None = Field(None, description='Sort the results by a specific field (e.g., created_at, id, title)')
    order: Literal['asc', 'desc'] | None = Field(None, description='Sort order (asc or desc)')


class ListFiles(_Input):
    """List all files with optional filtering, sorting, and related resources."""
    operation: Literal["list_files"] = Field("list_files", title="List Files", json_schema_extra={"ui:hidden": True})
    append: str | None = Field(None, description='Additional attributes to append to each file (e.g., connection_type,permissions,player_settings,player_logo,custom_logo_url,document_preview_url,document_download_url)')
    include: str | None = Field(None, description='Related resources to include (e.g., tags, attachments)')
    sort: str | None = Field(None, description='Sort the results by specific fields (e.g., created_at,id,title,description)')
    ignore_language: bool | None = Field(None, description='Flag to ignore language')
    filter_id: int | None = Field(None, description='Filter by ID')
    filter_folder_id: int | None = Field(None, description='Filter by Folder ID')
    filter_status_upload: str | None = Field(None, description='Filter by Upload Status')
    filter_status_transcription: str | None = Field(None, description='Filter by Transcription Status')
    filter_status_transcode: str | None = Field(None, description='Filter by Transcode Status')
    page: int | None = Field(None, ge=1, le=1000, description='Page number')
    limit: int | None = Field(None, ge=1, le=1000, description='Number of items per page')


class ListFileTags(_Input):
    """Get all tags for files."""
    operation: Literal["list_file_tags"] = Field("list_file_tags", title="List File Tags", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Search query for tags')
    limit: int | None = Field(None, ge=1, le=1000, description='Limit the number of results per page')
    sort: str | None = Field(None, description='Sort the results by specific fields (e.g., created_at,updated_at,name,files_count)')


class ListSelectedFileTags(_Input):
    """Get tags associated with a specific file."""
    operation: Literal["list_selected_file_tags"] = Field("list_selected_file_tags", title="List Selected File Tags", json_schema_extra={"ui:hidden": True})
    file: str = Field(..., min_length=1, description='Hash of the file')


class UpdateFileTags(_Input):
    """Update tags for a specific file."""
    operation: Literal["update_file_tags"] = Field("update_file_tags", title="Update File Tags", json_schema_extra={"ui:hidden": True})
    file: str = Field(..., min_length=1, description='Hash of the file')
    tags: list[str] = Field(..., description='')


class ListFolders(_Input):
    """Get a list of folders."""
    operation: Literal["list_folders"] = Field("list_folders", title="List Folders", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=1000, description='Number of items per page')
    filter_id: str | None = Field(None, description='Filter folders by ID or folder hash')
    filter_title: str | None = Field(None, description='Filter folders by title')
    filter_connection_type: str | None = Field(None, description='Filter folders by connection type')
    filter_collection_name: str | None = Field(None, description='Filter folders by collection name')
    include: str | None = Field(None, description='Related resources to include (e.g., files, filesProcessedCount)')
    append: str | None = Field(None, description='Additional attributes to append to each file (e.g., connection_type,file_thumbnails)')
    sort: str | None = Field(None, description='Sort the results by specific fields (e.g., created_at,id,title,description, updated_at)')


class ListPlaylists(_Input):
    """Get a list of playlists."""
    operation: Literal["list_playlists"] = Field("list_playlists", title="List Playlists", json_schema_extra={"ui:hidden": True})
    filer_id: int | None = Field(None, description='Filter playlists by ID')
    filer_title: str | None = Field(None, description='Filter playlists by title')
    filer_hub_id: int | None = Field(None, description='Filter playlists by hub ID')
    include: str | None = Field(None, description='Related resources to include (e.g., sections, files, videoFilesCount, audioFilesCount, filesProcessedCount)')
    append: str | None = Field(None, description='Additional attributes to append to each playlist (e.g., permissions)')
    sort: str | None = Field(None, description='Sort the results by specific fields (e.g., created_at,id,title)')


class ListHubs(_Input):
    """Get a list of hubs."""
    operation: Literal["list_hubs"] = Field("list_hubs", title="List Hubs", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Search query for hub titles')
    perPage: int | None = Field(None, ge=1, le=1000, description='Number of items per page')
    include: str | None = Field(None, description='Related resources to include (e.g., audiencesCount, pagesCount)')
    append: str | None = Field(None, description='Additional attributes to append to each hub (e.g., custom_logo_url, custom_login_logo_url, social_image_url, favicon_url, dashboard, onboarding)')
    sort: str | None = Field(None, description='Sort the results by specific fields (e.g., created_at,id,title,updated_at)')


class ListWidgets(_Input):
    """Get a list of widgets."""
    operation: Literal["list_widgets"] = Field("list_widgets", title="List Widgets", json_schema_extra={"ui:hidden": True})
    filter_type: str | None = Field(None, description='Filter widgets by type')
    limit: int | None = Field(None, ge=1, le=1000, description='Number of items per page')
    sort: str | None = Field(None, description='Sort the results by specific fields (e.g., created_at,id,name, description)')


Operation = Annotated[Union[GetProfile, AttachAudienceAchievements, ListAudienceAttributes, StoreAudienceAttributes, ListAudience, CreateAudience, ListAudienceHubs, AttachAudienceHubs, DetachAudienceHubs, ListAudienceTags, ListMemberTags, AttachAudienceTags, DetachAudienceTags, ListAttributes, ListAchievements, ListFiles, ListFileTags, ListSelectedFileTags, UpdateFileTags, ListFolders, ListPlaylists, ListHubs, ListWidgets], Field(discriminator="operation")]



class MembershipioConfig(NodeConfig[Operation, MembershipioTokenCredential]):
    pass


ROUTES = {'get_profile': ('GET', '/me', {}, []),
 'attach_audience_achievements': ('POST',
                                  '/audience/{audience}/achievements/attach',
                                  {},
                                  ['achievements']),
 'list_audience_attributes': ('GET', '/audience/{audience}/attributes', {'limit': 'limit'}, []),
 'store_audience_attributes': ('POST', '/audience/{audience}/attributes', {}, ['attributes']),
 'list_audience': ('GET',
                   '/audience',
                   {'limit': 'limit',
                    'page': 'page',
                    'sort': 'sort',
                    'include': 'include',
                    'filter_id': 'filter[id]',
                    'filter_name': 'filter[name]',
                    'filter_email': 'filter[email]',
                    'filter_is_person': 'filter[is_person]'},
                   []),
 'create_audience': ('POST',
                     '/audience',
                     {},
                     ['is_create_or_update',
                      'tracking_id',
                      'email',
                      'name',
                      'phone',
                      'meta',
                      'hubs',
                      'notify',
                      'tags',
                      'remove_existing_tags',
                      'attributes']),
 'list_audience_hubs': ('GET', '/audience/{audience}/hubs', {'includes': 'includes'}, []),
 'attach_audience_hubs': ('POST', '/audience/{audience}/hubs/attach', {}, ['hubs']),
 'detach_audience_hubs': ('DELETE', '/audience/{audience}/hubs/detach', {}, ['hubs']),
 'list_audience_tags': ('GET',
                        '/audience/tags',
                        {'query': 'query', 'limit': 'limit', 'sort': 'sort'},
                        []),
 'list_member_tags': ('GET', '/audience/{audience}/tags', {}, []),
 'attach_audience_tags': ('POST', '/audience/{audience}/tags/attach', {}, ['tags']),
 'detach_audience_tags': ('POST', '/audience/{audience}/tags/detach', {}, ['tags']),
 'list_attributes': ('GET',
                     '/data/attributes',
                     {'limit': 'limit',
                      'filter_title': 'filter[title]',
                      'filter_type': 'filter[type]',
                      'sort': 'sort',
                      'order': 'order'},
                     []),
 'list_achievements': ('GET',
                       '/achievements',
                       {'limit': 'limit',
                        'filter_id': 'filter[id]',
                        'filter_title': 'filter[title]',
                        'filter_type': 'filter[type]',
                        'filter_criteria': 'filter[criteria]',
                        'sort': 'sort',
                        'order': 'order'},
                       []),
 'list_files': ('GET',
                '/files',
                {'append': 'append',
                 'include': 'include',
                 'sort': 'sort',
                 'ignore_language': 'ignore_language',
                 'filter_id': 'filter[id]',
                 'filter_folder_id': 'filter[folder_id]',
                 'filter_status_upload': 'filter[status_upload]',
                 'filter_status_transcription': 'filter[status_transcription]',
                 'filter_status_transcode': 'filter[status_transcode]',
                 'page': 'page',
                 'limit': 'limit'},
                []),
 'list_file_tags': ('GET', '/files/tags', {'query': 'query', 'limit': 'limit', 'sort': 'sort'}, []),
 'list_selected_file_tags': ('GET', '/files/{file}/tags', {}, []),
 'update_file_tags': ('PUT', '/files/{file}/tags', {}, ['tags']),
 'list_folders': ('GET',
                  '/folders',
                  {'limit': 'limit',
                   'filter_id': 'filter[id]',
                   'filter_title': 'filter[title]',
                   'filter_connection_type': 'filter[connection.type]',
                   'filter_collection_name': 'filter[collection_name]',
                   'include': 'include',
                   'append': 'append',
                   'sort': 'sort'},
                  []),
 'list_playlists': ('GET',
                    '/playlists',
                    {'filer_id': 'filer[id]',
                     'filer_title': 'filer[title]',
                     'filer_hub_id': 'filer[hub_id]',
                     'include': 'include',
                     'append': 'append',
                     'sort': 'sort'},
                    []),
 'list_hubs': ('GET',
               '/hubs',
               {'query': 'query',
                'perPage': 'perPage',
                'include': 'include',
                'append': 'append',
                'sort': 'sort'},
               []),
 'list_widgets': ('GET',
                  '/widgets',
                  {'filter_type': 'filter[type]', 'limit': 'limit', 'sort': 'sort'},
                  [])}



class MembershipioNode(WorkflowNode):
    integration_type = "automation-membershipio"
    connection_evidence = ConnectionEvidence(noun="audience members", operation="list_audience",
        identity_operation="get_profile", label_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return MembershipioConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Membership.io access token")
        config = self.config.config
        method, template, query, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template
        for key in ("audience", "file"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values[key], safe=""))
        params = {}
        for field, wire in query.items():
            if field in values:
                value = values[field]
                # OpenAPI's default array query style is form/explode (repeated keys).
                params[wire] = str(value).lower() if isinstance(value, bool) else value
        body = {field: values[field] for field in body_fields if field in values} if method != "GET" else None
        token = self.config.credentials.access_token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params,
                **({"json": body} if body is not None else {}))
            if response.status_code in {301, 302, 307, 308}:
                # Never forward credentials to a caller-supplied or arbitrary redirect.
                target = str(response.url).replace(BASE, MIGRATED_BASE, 1)
                allowed = {target, target.replace("app.membership.io/", "app.membership.io:443/", 1)}
                if response.headers.get("location") not in allowed:
                    raise ValueError("Membership.io returned an unexpected redirect")
                response = await client.request(method, target, headers=headers,
                    **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the shared connection-evidence seam.
            message = response.text[:2000].replace(token, "[redacted]")
            raise ValueError(f"Membership.io HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            data = None
        else:
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Membership.io returned an unexpected JSON response")
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                raise ValueError("Membership.io rejected the request: " + str(data).replace(token, "[redacted]")[:2000])
        # Keep provider resource/envelope and pagination fields intact; never follow response URLs.
        result = {"status": "success", "operation": config.operation, "data": data}
        await self.emit(result)
        return result
