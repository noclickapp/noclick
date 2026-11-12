"""Leexi public API v1. One request per operation; list results are one page.

Contract: https://public-api.leexi.ai/v1/openapi.json (version 1.0).
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://public-api.leexi.ai/v1"

class LeexiCredential(BaseModel):
    model_config = ConfigDict(title="Leexi API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.leexi.ai/settings/integrations",
        "x-credential-instructions": "Paste your Leexi API key signature, without the Basic prefix. Enable read_teams for the connection check and the read/write permissions needed by your operations. NoClick sends Authorization: Basic followed by this signature."})
    credential_type: Literal["leexi_api_key"] = Field("leexi_api_key", json_schema_extra={"ui:hidden": True})
    api_key_signature: str = Field(..., title="API key signature", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key_signature")
    @classmethod
    def signature(cls, value):
        value = clean_secret(value, field_name="API key signature")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key signature, without Basic or whitespace")
        return value

class LeexiInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def path_value(cls, value, info):
        if info.field_name == "uuid" and (not value or len(value) > 256 or any(c in value for c in "/?#\\") or value in {".", ".."}):
            raise ValueError("Use a single Leexi resource UUID")
        return value

class LeexiCustomer(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    uuid: Optional[str] = None

class LeexiListCallsConfig(LeexiInput):
    """List calls. List all calls and meetings within the API key's access scope. Keys with whole-company access list every call; scoped keys list only the calls they can access."""
    operation: Literal['list_calls'] = Field('list_calls', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='')
    items: int = Field(10, ge=1, le=100, description='')
    order: Literal['created_at desc', 'created_at asc', 'performed_at desc', 'performed_at asc', 'updated_at desc', 'updated_at asc'] = Field('created_at desc', description='')
    date_filter: Literal['created_at', 'performed_at', 'updated_at'] = Field('created_at', description='')
    from_time: Optional[str] = Field(None, description='')
    to_time: Optional[str] = Field(None, description='')
    source: Optional[str] = Field(None, description='')
    conversation_type_uuid: Optional[str] = Field(None, description='')
    with_simple_transcript: StrictBool = Field(False, description='')

class LeexiCreateCallConfig(LeexiInput):
    """Create a call. Create a call or meeting asynchronously (creation time is typically a few minutes). You must first finish uploading the recording of the call using a presigned recording url retrieved with the [Request a presigned url](/reference/request-a-presigned-url) endpoint. Use the [LIST users](/reference/list-users) endpoint to find the user_uuid to use in this request."""
    operation: Literal['create_call'] = Field('create_call', json_schema_extra={"ui:hidden": True})
    custom_fields: Optional[dict[str, Union[str, float, StrictBool, None]]] = Field(None, description='Free-form key/value pairs stored on the call and returned as-is by the [LIST calls](/reference/list-calls) and [GET call](/reference/get-call) endpoints. Only for custom integrations agreed with Leexi: the keys and their meaning must be defined with the Leexi team beforehand, otherwise the values are stored but never used. Values must be scalars (string, number, boolean or null).')
    customers: Optional[list[LeexiCustomer]] = Field(None, description='The external participants (customers) of the call. An array of objects, each accepting any of `name`, `email`, `phone_number` and `uuid` (only one attribute is required per object). When `uuid` is set it links an existing customer and the other attributes are ignored; unknown uuids are skipped. The provided names are used to help identify the speakers in the transcript. Prefer this over the deprecated `emails` and `raw_phone_number` params. ⚠️ Cannot be combined with the deprecated `emails` or `raw_phone_number` params in the same request (returns a 400).')
    description: Optional[str] = Field(None, description='')
    direction: str = Field(..., description='inbound or outbound')
    external_id: str = Field(..., description='the id of the call in your system')
    locale: Optional[str] = Field(None, description='fr-FR en-US de-DE es-ES nl-NL ar-AE da-DK hi-IN id-ID it-IT ja-JP ko-KR nb-NO pl-PL pt-PT ru-RU sv-SE tr-TR uk-UA zh-CN fr-CA he-IL th-TH bg-BG cs-CZ el-GR et-EE fi-FI hr-HR hu-HU lt-LT lv-LV ro-RO vi-VN en-AU en-GB en-NZ en-IN ca-ES')
    participating_user_uuids: Optional[list[str]] = Field(None, description='uuids of fellow Leexi users participating in the call (in addition to the owner set via `user_uuid`). Use the [LIST users](/reference/list-users) endpoint to find them. ⚠️ Cannot be combined with the deprecated `emails` or `raw_phone_number` params in the same request (returns a 400).')
    performed_at: str = Field(..., description='iso8601 format')
    recording_s3_key: str = Field(..., description='the recording_s3_key returned by the [Request a presigned url](/reference/request-a-presigned-url) endpoint')
    tags: Optional[list[str]] = Field(None, description='an array of tag names')
    title: str = Field('Meeting XYZ', description='The title of the call or meeting')
    user_uuid: str = Field(..., description='The uuid of the user associated to the call, must have an active license.')

class LeexiGetCallConfig(LeexiInput):
    """Get call. Getting a single call or meeting. This returns the same attributes as the [LIST calls](/reference/list-calls) endpoint with additionally the call topics and the call transcript. The simple_transcript has paragraph-level timestamps, while the transcript also has word-level timestamps. The call must be within the API key's access scope, otherwise the endpoint responds with 404."""
    operation: Literal['get_call'] = Field('get_call', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiRequestPresignedUrlConfig(LeexiInput):
    """Request a presigned url. Request a presigned URL to upload a call recording, before creating the call. To upload the file you must send a PUT request to the returned url, with the headers provided by the endpoint (single-part upload). This uploaded file automatically expires after 3 days unless used to create a call."""
    operation: Literal['request_presigned_url'] = Field('request_presigned_url', json_schema_extra={"ui:hidden": True})
    extension: str = Field(..., description='VIDEO: .mp4 .mkv .avi .webm .mov .wmv .mpg .mpeg .m4v AUDIO: .mp3 .wav .aac .flac .ogg .m4a .wma .opus .aiff .alac .amr .ape .dts .ac3 .mid .mp2 .mpc .ra .tta .vox')

class LeexiListCallNotesConfig(LeexiInput):
    """List call notes. List call notes for a given call. `call_uuid` is required. You can optionally filter by `prompt_uuid`. Only call notes generated from prompts in the `summary` or `text` categories are returned. The call must be within the API key's access scope, otherwise no notes are returned."""
    operation: Literal['list_call_notes'] = Field('list_call_notes', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='')
    items: int = Field(10, ge=1, le=100, description='')
    call_uuid: str = Field(..., description='')
    prompt_uuid: Optional[str] = Field(None, description='')

class LeexiDeleteCallNoteConfig(LeexiInput):
    """Delete a call note. Delete a call note"""
    operation: Literal['delete_call_note'] = Field('delete_call_note', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiGetCallNoteConfig(LeexiInput):
    """Get a call note. Retrieve a single call note"""
    operation: Literal['get_call_note'] = Field('get_call_note', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiUpdateCallNoteConfig(LeexiInput):
    """Update a call note. Update a note for a given call"""
    operation: Literal['update_call_note'] = Field('update_call_note', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')
    locale: str = Field(..., description='The locale of the translation to update, for example `en-US`.')
    text: str = Field(..., description='The new translated text.')

class LeexiListMeetingEventsConfig(LeexiInput):
    """list meeting events. """
    operation: Literal['list_meeting_events'] = Field('list_meeting_events', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='')
    items: int = Field(10, ge=1, le=100, description='')
    order: Literal['created_at desc', 'created_at asc', 'start_time desc', 'start_time asc', 'end_time desc', 'end_time asc'] = Field('start_time desc', description='')
    origin: Optional[Literal['calendar', 'manual', 'api']] = Field(None, description='')
    date_filter: Literal['start_time', 'end_time'] = Field('start_time', description='')
    from_time: Optional[str] = Field(None, description='')
    to_time: Optional[str] = Field(None, description='')

class LeexiDeleteMeetingEventConfig(LeexiInput):
    """Delete a meeting event. """
    operation: Literal['delete_meeting_event'] = Field('delete_meeting_event', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiGetMeetingEventConfig(LeexiInput):
    """Get a meeting event. """
    operation: Literal['get_meeting_event'] = Field('get_meeting_event', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiLaunchMeetingAssistantConfig(LeexiInput):
    """Launch a meeting assistant. """
    operation: Literal['launch_meeting_assistant'] = Field('launch_meeting_assistant', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')
    stop_task: StrictBool = Field(False, description='Stop the ongoing bot')

class LeexiListTeamsConfig(LeexiInput):
    """List teams. List all teams in your workspace"""
    operation: Literal['list_teams'] = Field('list_teams', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='')
    items: int = Field(10, ge=1, le=100, description='')

class LeexiCreateTeamConfig(LeexiInput):
    """Create a team. Create a team in your workspace. The team inherits your company settings and gets the default email templates."""
    operation: Literal['create_team'] = Field('create_team', json_schema_extra={"ui:hidden": True})
    active: Optional[StrictBool] = Field(None, description='Defaults to `true` on creation. A team can only be deactivated once it has no active users.')
    name: str = Field(..., description='The team name. It must be unique within your workspace.')

class LeexiDeleteTeamConfig(LeexiInput):
    """Delete a team. Delete a team. Only a team with no users and no calls can be deleted; deactivate it instead with a `PATCH` setting `active` to `false`."""
    operation: Literal['delete_team'] = Field('delete_team', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiGetTeamConfig(LeexiInput):
    """Get a team. Retrieve a single team of your workspace."""
    operation: Literal['get_team'] = Field('get_team', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiUpdateTeamConfig(LeexiInput):
    """Update a team. Update a team. Only the attributes present in the body are updated."""
    operation: Literal['update_team'] = Field('update_team', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')
    active: Optional[StrictBool] = Field(None, description='Defaults to `true` on creation. A team can only be deactivated once it has no active users.')
    name: Optional[str] = Field(None, description='The team name. It must be unique within your workspace.')

class LeexiListUsersConfig(LeexiInput):
    """List Users. List all users in your workspace"""
    operation: Literal['list_users'] = Field('list_users', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description='')
    items: int = Field(10, ge=1, le=100, description='')

class LeexiCreateUserConfig(LeexiInput):
    """Create a user. Create a user in your workspace. The user receives a welcome email with a link to set their password, unless `send_welcome_email` is `false`."""
    operation: Literal['create_user'] = Field('create_user', json_schema_extra={"ui:hidden": True})
    active: Optional[StrictBool] = Field(None, description='Defaults to `true` on creation. Set to `false` to deactivate the user.')
    email: str = Field(..., description="The user's email address. It must be deliverable and not already used in any Leexi company.")
    license: Optional[str] = Field(None, description="Either `free` or your company's own license category. Any other value is ignored.")
    name: str = Field(..., description="The user's full name.")
    roles: Optional[list[str]] = Field(None, description='Role names. Defaults to `["member"]` on creation. Privileged roles (`super_admin`, `system_admin`, `billing_manager`) cannot be assigned through the API; grant them from Leexi > Settings > Users.')
    send_welcome_email: Optional[StrictBool] = Field(None, description='Defaults to `true`. Set to `false` to create the user without sending them the welcome email.')
    team_uuid: str = Field(..., description='The uuid of the team the user belongs to.')

class LeexiDeactivateUserConfig(LeexiInput):
    """Deactivate a user. Deactivate a user. Users are never permanently deleted: their calls and history are kept, their sessions are revoked and they stop consuming a license. Reactivate them with a `PATCH` setting `active` to `true`."""
    operation: Literal['deactivate_user'] = Field('deactivate_user', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiGetUserConfig(LeexiInput):
    """Get a user. Retrieve a single user of your workspace."""
    operation: Literal['get_user'] = Field('get_user', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')

class LeexiUpdateUserConfig(LeexiInput):
    """Update a user. Update a user. Only the attributes present in the body are updated."""
    operation: Literal['update_user'] = Field('update_user', json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='')
    active: Optional[StrictBool] = Field(None, description='Defaults to `true` on creation. Set to `false` to deactivate the user.')
    email: Optional[str] = Field(None, description="The user's email address. It must be deliverable and not already used in any Leexi company.")
    license: Optional[str] = Field(None, description="Either `free` or your company's own license category. Any other value is ignored.")
    name: Optional[str] = Field(None, description="The user's full name.")
    roles: Optional[list[str]] = Field(None, description='Role names. Defaults to `["member"]` on creation. Privileged roles (`super_admin`, `system_admin`, `billing_manager`) cannot be assigned through the API; grant them from Leexi > Settings > Users.')
    team_uuid: Optional[str] = Field(None, description='The uuid of the team the user belongs to.')

# Leexi's own MCP server: agents get its tools through a person's Leexi sign-in.
LeexiMcpCredential = mcp_credential("leexi", "https://api.leexi.ai/mcp", app="Leexi")


LeexiOperation = Annotated[Union[LeexiListCallsConfig, LeexiCreateCallConfig, LeexiGetCallConfig, LeexiRequestPresignedUrlConfig, LeexiListCallNotesConfig, LeexiDeleteCallNoteConfig, LeexiGetCallNoteConfig, LeexiUpdateCallNoteConfig, LeexiListMeetingEventsConfig, LeexiDeleteMeetingEventConfig, LeexiGetMeetingEventConfig, LeexiLaunchMeetingAssistantConfig, LeexiListTeamsConfig, LeexiCreateTeamConfig, LeexiDeleteTeamConfig, LeexiGetTeamConfig, LeexiUpdateTeamConfig, LeexiListUsersConfig, LeexiCreateUserConfig, LeexiDeactivateUserConfig, LeexiGetUserConfig, LeexiUpdateUserConfig], Field(discriminator="operation")]

class LeexiFullConfig(NodeConfig[LeexiOperation, Union[LeexiCredential, LeexiMcpCredential]]):
    pass

ROUTES = {'list_calls': ('GET',
                '/calls',
                [('page', 'page', 'query'),
                 ('items', 'items', 'query'),
                 ('order', 'order', 'query'),
                 ('date_filter', 'date_filter', 'query'),
                 ('from_time', 'from', 'query'),
                 ('to_time', 'to', 'query'),
                 ('source', 'source', 'query'),
                 ('conversation_type_uuid', 'conversation_type_uuid', 'query'),
                 ('with_simple_transcript', 'with_simple_transcript', 'query')]),
 'create_call': ('POST',
                 '/calls',
                 [('custom_fields', 'custom_fields', 'body'),
                  ('customers', 'customers', 'body'),
                  ('description', 'description', 'body'),
                  ('direction', 'direction', 'body'),
                  ('external_id', 'external_id', 'body'),
                  ('locale', 'locale', 'body'),
                  ('participating_user_uuids', 'participating_user_uuids', 'body'),
                  ('performed_at', 'performed_at', 'body'),
                  ('recording_s3_key', 'recording_s3_key', 'body'),
                  ('tags', 'tags', 'body'),
                  ('title', 'title', 'body'),
                  ('user_uuid', 'user_uuid', 'body')]),
 'get_call': ('GET', '/calls/{uuid}', [('uuid', 'uuid', 'path')]),
 'request_presigned_url': ('POST', '/calls/presign_recording_url', [('extension', 'extension', 'body')]),
 'list_call_notes': ('GET',
                     '/call_notes',
                     [('page', 'page', 'query'),
                      ('items', 'items', 'query'),
                      ('call_uuid', 'call_uuid', 'query'),
                      ('prompt_uuid', 'prompt_uuid', 'query')]),
 'delete_call_note': ('DELETE', '/call_notes/{uuid}', [('uuid', 'uuid', 'path')]),
 'get_call_note': ('GET', '/call_notes/{uuid}', [('uuid', 'uuid', 'path')]),
 'update_call_note': ('PATCH',
                      '/call_notes/{uuid}',
                      [('uuid', 'uuid', 'path'), ('locale', 'locale', 'body'), ('text', 'text', 'body')]),
 'list_meeting_events': ('GET',
                         '/meeting_events',
                         [('page', 'page', 'query'),
                          ('items', 'items', 'query'),
                          ('order', 'order', 'query'),
                          ('origin', 'origin', 'query'),
                          ('date_filter', 'date_filter', 'query'),
                          ('from_time', 'from', 'query'),
                          ('to_time', 'to', 'query')]),
 'delete_meeting_event': ('DELETE', '/meeting_events/{uuid}', [('uuid', 'uuid', 'path')]),
 'get_meeting_event': ('GET', '/meeting_events/{uuid}', [('uuid', 'uuid', 'path')]),
 'launch_meeting_assistant': ('POST',
                              '/meeting_events/{uuid}/launch_bot',
                              [('uuid', 'uuid', 'path'), ('stop_task', 'stop_task', 'body')]),
 'list_teams': ('GET', '/teams', [('page', 'page', 'query'), ('items', 'items', 'query')]),
 'create_team': ('POST', '/teams', [('active', 'active', 'body'), ('name', 'name', 'body')]),
 'delete_team': ('DELETE', '/teams/{uuid}', [('uuid', 'uuid', 'path')]),
 'get_team': ('GET', '/teams/{uuid}', [('uuid', 'uuid', 'path')]),
 'update_team': ('PATCH',
                 '/teams/{uuid}',
                 [('uuid', 'uuid', 'path'), ('active', 'active', 'body'), ('name', 'name', 'body')]),
 'list_users': ('GET', '/users', [('page', 'page', 'query'), ('items', 'items', 'query')]),
 'create_user': ('POST',
                 '/users',
                 [('active', 'active', 'body'),
                  ('email', 'email', 'body'),
                  ('license', 'license', 'body'),
                  ('name', 'name', 'body'),
                  ('roles', 'roles', 'body'),
                  ('send_welcome_email', 'send_welcome_email', 'body'),
                  ('team_uuid', 'team_uuid', 'body')]),
 'deactivate_user': ('DELETE', '/users/{uuid}', [('uuid', 'uuid', 'path')]),
 'get_user': ('GET', '/users/{uuid}', [('uuid', 'uuid', 'path')]),
 'update_user': ('PATCH',
                 '/users/{uuid}',
                 [('uuid', 'uuid', 'path'),
                  ('active', 'active', 'body'),
                  ('email', 'email', 'body'),
                  ('license', 'license', 'body'),
                  ('name', 'name', 'body'),
                  ('roles', 'roles', 'body'),
                  ('team_uuid', 'team_uuid', 'body')])}

class LeexiNode(WorkflowNode):
    integration_type = "automation-leexi"
    credential_provider_labels = {"leexi": "Leexi Account"}
    connection_evidence = ConnectionEvidence(noun="teams", operation="list_teams", label_keys=("name", "uuid"))

    @classmethod
    def get_config_model(cls):
        return LeexiFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Leexi API key")
        op = self.config.config
        method, path, fields = ROUTES[op.operation]
        params, body = {}, {}
        for field, wire, location in fields:
            value = getattr(op, field)
            if value is None:
                continue
            if location == "path":
                path = path.replace("{" + wire + "}", quote(value, safe=""))
            elif location == "query":
                params[wire] = str(value).lower() if isinstance(value, bool) else value
            else:
                body[wire] = [x.model_dump(exclude_none=True) if isinstance(x, BaseModel) else x for x in value] if isinstance(value, list) else value
        secret = self.config.credentials.api_key_signature
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    json=body if method in {"POST", "PATCH"} else None,
                    headers={"Authorization": "Basic " + secret, "Accept": "application/json"})
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise ValueError("Leexi request could not be confirmed") from None
        if not isinstance(payload, dict):
            raise ValueError("Expected a Leexi JSON response object")
        if response.status_code >= 300 or payload.get("success") is False:
            result = {"status": "error", "http_status": response.status_code,
                      "message": str(payload.get("message", "Leexi rejected the request")).replace(secret, "[redacted]")}
        else:
            # Preserve provider data, pagination and asynchronous acknowledgement.
            # A create-call acknowledgement does not mean processing has finished.
            result = {**payload, "status": "success", "http_status": response.status_code}
        await self.emit(result)
        return result
