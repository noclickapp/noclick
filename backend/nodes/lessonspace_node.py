"""Lessonspace v2 organisation API: fixed, contract-pinned operations.

Organisation keys are pasted by the user. Lists return a single provider page;
recording/transcription links are returned without following them. Launch output
omits the unrestricted space API secret returned by Lessonspace.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, EmailStr, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://api.thelessonspace.com/v2"
CREDENTIAL_TYPE = "lessonspace_api_key"


class LessonspaceAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Lessonspace API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.thelessonspace.com/docs/overview/authentication",
            "x-credential-instructions": "Generate an API key in your Lessonspace organisation dashboard's developer settings. Paste only the key, without the Organisation prefix. NoClick checks it by reading your organisation's users."})
    credential_type: Literal["lessonspace_api_key"] = Field("lessonspace_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Organisation prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LessonspaceLaunchUser(_Input):
    name: str = Field("Guest", max_length=64)
    id: str | None = Field(None, min_length=1, max_length=64)
    email: EmailStr | None = Field(None, min_length=1, description="Email address of the participant")
    leader: StrictBool = False
    single_use: StrictBool = False
    record: StrictBool | None = None
    ghost: StrictBool | None = None
    read_only: StrictBool | None = None


class LessonspaceListSessionsConfig(_Input):
    """Fetch the sessions for an organisation."""
    operation: Literal["list_sessions"] = Field("list_sessions", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description='If a UUID, filters to sessions or spaces with a matching slug. Otherwise, filters to sessions or spaces with a partial, case-insensitive match on the name.')
    page: int | None = Field(None, ge=1, strict=True, description='A page number within the paginated result set.')
    include_single_user: StrictBool | None = Field(None, description='Include sessions with only one user.')
    duration_min: int | None = Field(None, strict=True, description='Minimum session duration, in seconds.')
    duration_max: int | None = Field(None, strict=True, description='Maximum session duration, in seconds.')
    start_time_after: str | None = Field(None, description='Filter to sessions that started after the specified ISO8601 timestamp.')
    start_time_before: str | None = Field(None, description='Filter to sessions that started before the specified ISO8601 timestamp.')
    end_time_after: str | None = Field(None, description='Filter to sessions that ended after the specified ISO8601 timestamp.')
    end_time_before: str | None = Field(None, description='Filter to sessions that ended before the specified ISO8601 timestamp.')
    date_after: str | None = Field(None, description='Filter to sessions created after the specified ISO8601 timestamp. Using both `date_before` and `date_after` is the same as using `start_time_after` and `end_time_before`.')
    date_before: str | None = Field(None, description='Filter sessions created before the specified ISO8601 timestamp. Using both `date_before` and `date_after` is the same as using `start_time_after` and `end_time_before`.')
    user: str | None = Field(None, description='Filter to sessions that the specified Lessonspace user IDs were present in. Accepts multiple values, delimited by `&`.')
    space: str | None = Field(None, description='Filter to sessions linked to the provided space UUID(s). Accepts multiple values, delimited by `&`.')
    launch_id: str | None = Field(None, description='Filter to sessions linked to the space that was identified with the given value when it was created via the Launch endpoint. Performs a full-string, case-sensitive match.')
    in_progress_only: StrictBool | None = Field(None, description='Filter to sessions that are in progress only.')
    tags: str | None = Field(None, description='JSON object of tags that must match for the session. Leave the tag value blank to check if only the tag key exists. Must be URL-encoded. Performs a full-string, case-insensitive match.')
    user_external_id: str | None = Field(None, description='Filters to sessions that include a user with a matching `user.id` value that was provided via the Launch endpoint. Performs a full-string, case-insensitive match.')
    user_name: str | None = Field(None, description='Filters to sessions that include a user with a matching `user.name` value that was provided via the Launch endpoint. Performs a partial, case-insensitive match.')

class LessonspaceGetSessionConfig(_Input):
    """Fetch a session with the given UUID."""
    operation: Literal["get_session"] = Field("get_session", json_schema_extra={"ui:hidden": True})
    session: UUID = Field(..., description='The UUID identifying this session')

class LessonspaceUpdateSessionConfig(_Input):
    """Update a session's name or recording access policy for the given UUID."""
    operation: Literal["update_session"] = Field("update_session", json_schema_extra={"ui:hidden": True})
    session: UUID = Field(..., description='The UUID identifying this session')
    name: str = Field(..., min_length=1, max_length=512)
    recording_access_policy: dict | None = Field(None, description="Recording policy object as accepted by the published v2 schema.")

class LessonspaceDeleteSessionRecordingsConfig(_Input):
    """Irreversible: Delete all recording data associated with a specific session, including AV, events and transcriptions.

This cannot be undone. If the space stores recordings in a customer-owned (custom) bucket, the request is rejected and nothing is deleted unless `force_delete_custom_buckets` is set. Basic session metadata such as name and participants is retained and stays visible in the sessions list. Related spaces are not affected by this deletion and can continue to be used for new sessions."""
    operation: Literal["delete_session_recordings"] = Field("delete_session_recordings", json_schema_extra={"ui:hidden": True})
    session: UUID = Field(..., description='The UUID identifying this session')
    force_delete_custom_buckets: StrictBool = Field(False, description="Also permanently delete recordings in a customer-owned bucket.")

class LessonspaceGetSessionPlaybackConfig(_Input):
    """Get Session Recording URL"""
    operation: Literal["get_session_playback"] = Field("get_session_playback", json_schema_extra={"ui:hidden": True})
    session: UUID = Field(..., description='The UUID identifying this session')

class LessonspaceGetSessionTranscriptConfig(_Input):
    """Fetch the transcription for a given session. The transcription must have been scheduled on the session beforehand."""
    operation: Literal["get_session_transcript"] = Field("get_session_transcript", json_schema_extra={"ui:hidden": True})
    session: UUID = Field(..., description='The UUID identifying this session')

class LessonspaceListSpacesConfig(_Input):
    """Get Organisation Space List"""
    operation: Literal["list_spaces"] = Field("list_spaces", json_schema_extra={"ui:hidden": True})
    session: str | None = Field(None, description='The ID(s) of sessions to filter by. Accepts multiple values.')
    date: str | None = Field(None, description='Deprecated. Use `date_before` and `date_after`.')
    tag_key: str | None = Field(None, description='A tag key to match on. Only works if `tag_value` is also set. Performs a full-string, case-insensitive match.')
    tag_value: str | None = Field(None, description='A tag value to match on. Only works if `tag_key` is also set. Performs a full-string, case-insensitive match.')
    user: int | None = Field(None, description='The Lessonspace IDs of user profiles that have attended sessions which occurred in this space. Accepts multiple values.')
    assigned_to: int | None = Field(None, strict=True, description='Filter to spaces which are assigned to these Lessonspace IDs.')
    search: str | None = Field(None, description='A search term.')
    page: int | None = Field(None, ge=1, strict=True, description='A page number within the paginated result set.')
    date_after: str | None = Field(None, description='Filter to spaces with sessions that ended after the specified ISO8601 timestamp.')
    date_before: str | None = Field(None, description='Filter to spaces with sessions that started before the specified ISO8601 timestamp.')

class LessonspaceDeleteSpaceRecordingsConfig(_Input):
    """Irreversible: Delete all recording data for every session that has happened inside a space, including AV, events and transcriptions. The space itself is not deleted and remains usable.

This cannot be undone. If the space stores recordings in a customer-owned (custom) bucket, the request is rejected and nothing is deleted unless `force_delete_custom_buckets` is set. Basic session metadata such as name and participants is retained and stays visible in the sessions list. Related spaces are not affected by this deletion and can continue to be used for new sessions."""
    operation: Literal["delete_space_recordings"] = Field("delete_space_recordings", json_schema_extra={"ui:hidden": True})
    space: UUID = Field(..., description='The UUID identifying this space')
    force_delete_custom_buckets: StrictBool = Field(False, description="Also permanently delete recordings in a customer-owned bucket.")

class LessonspaceListUsersConfig(_Input):
    """Get Organisation User List"""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    role: str | None = Field(None, description='Role(s) to filter by.')
    space: str | None = Field(None, description='The ID(s) of Spaces(s) to filter by. Will filter out users who have not attended any sessions which occurred in the spaces listed. Accepts multiple values.')
    session: str | None = Field(None, description='The ID(s) of session(s) to filter by. Will filter out users who have not attended any sessions listed. Accepts multiple values.')
    search: str | None = Field(None, description='A search term.')
    page: int | None = Field(None, ge=1, strict=True, description='A page number within the paginated result set.')

class LessonspaceDeleteUserConfig(_Input):
    """Irreversible: Delete User from Organisation"""
    operation: Literal["delete_user"] = Field("delete_user", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., ge=1, strict=True, description='The ID identifying this user')

class LessonspaceLaunchSpaceConfig(_Input):
    """Create Unified Space"""
    operation: Literal["launch_space"] = Field("launch_space", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=64, description="External space identifier. Reuse the same ID to join the same space.")
    name: str | None = Field(None, max_length=128)
    user: LessonspaceLaunchUser | None = None
    record_av: StrictBool | None = None
    record_content: StrictBool | None = None
    transcribe: StrictBool | None = None
    summarise: StrictBool | None = None
    features: dict[str, StrictBool] | None = None
    session_tags: dict[str, Annotated[str, Field(min_length=1)]] | None = None
    space_tags: dict[str, Annotated[str, Field(min_length=1)]] | None = None
    video_layout_mode: Literal["grid", "sidebar", "floating"] | None = None
    locale: Literal["en", "fr", "it", "pl"] | None = None

class LessonspaceListSpaceSessionsConfig(_Input):
    """Fetch the sessions for a specific space."""
    operation: Literal["list_space_sessions"] = Field("list_space_sessions", json_schema_extra={"ui:hidden": True})
    space: UUID = Field(..., description='The UUID identifying this space')
    search: str | None = Field(None, description='If a UUID, filters to sessions or spaces with a matching slug. Otherwise, filters to sessions or spaces with a partial, case-insensitive match on the name.')
    page: int | None = Field(None, ge=1, strict=True, description='A page number within the paginated result set.')
    include_single_user: StrictBool | None = Field(None, description='Include sessions with only one user.')
    duration_min: int | None = Field(None, strict=True, description='Minimum session duration, in seconds.')
    duration_max: int | None = Field(None, strict=True, description='Maximum session duration, in seconds.')
    start_time_after: str | None = Field(None, description='Filter to sessions that started after the specified ISO8601 timestamp.')
    start_time_before: str | None = Field(None, description='Filter to sessions that started before the specified ISO8601 timestamp.')
    end_time_after: str | None = Field(None, description='Filter to sessions that ended after the specified ISO8601 timestamp.')
    end_time_before: str | None = Field(None, description='Filter to sessions that ended before the specified ISO8601 timestamp.')
    date_after: str | None = Field(None, description='Filter to sessions created after the specified ISO8601 timestamp. Using both `date_before` and `date_after` is the same as using `start_time_after` and `end_time_before`.')
    date_before: str | None = Field(None, description='Filter sessions created before the specified ISO8601 timestamp. Using both `date_before` and `date_after` is the same as using `start_time_after` and `end_time_before`.')
    user: str | None = Field(None, description='Filter to sessions that the specified Lessonspace user IDs were present in. Accepts multiple values, delimited by `&`.')
    launch_id: str | None = Field(None, description='Filter to sessions linked to the space that was identified with the given value when it was created via the Launch endpoint. Performs a full-string, case-sensitive match.')
    in_progress_only: StrictBool | None = Field(None, description='Filter to sessions that are in progress only.')
    tags: str | None = Field(None, description='JSON object of tags that must match for the session. Leave the tag value blank to check if only the tag key exists. Must be URL-encoded. Performs a full-string, case-insensitive match.')
    user_external_id: str | None = Field(None, description='Filters to sessions that include a user with a matching `user.id` value that was provided via the Launch endpoint. Performs a full-string, case-insensitive match.')
    user_name: str | None = Field(None, description='Filters to sessions that include a user with a matching `user.name` value that was provided via the Launch endpoint. Performs a partial, case-insensitive match.')

LessonspaceConfig = Annotated[Union[
    LessonspaceListSessionsConfig,
    LessonspaceGetSessionConfig,
    LessonspaceUpdateSessionConfig,
    LessonspaceDeleteSessionRecordingsConfig,
    LessonspaceGetSessionPlaybackConfig,
    LessonspaceGetSessionTranscriptConfig,
    LessonspaceListSpacesConfig,
    LessonspaceDeleteSpaceRecordingsConfig,
    LessonspaceListUsersConfig,
    LessonspaceDeleteUserConfig,
    LessonspaceLaunchSpaceConfig,
    LessonspaceListSpaceSessionsConfig
], Field(discriminator="operation")]


class LessonspaceFullConfig(NodeConfig[LessonspaceConfig, LessonspaceAPIKeyCredential]):
    pass


ROUTES = {
    "list_sessions": ("GET", "/organisations/sessions/"),
    "get_session": ("GET", "/organisations/sessions/{session}/"),
    "update_session": ("PATCH", "/organisations/sessions/{session}/"),
    "delete_session_recordings": ("POST", "/organisations/sessions/{session}/delete-recordings/"),
    "get_session_playback": ("GET", "/organisations/sessions/{session}/playback/"),
    "get_session_transcript": ("GET", "/organisations/sessions/{session}/transcript/"),
    "list_spaces": ("GET", "/organisations/spaces/"),
    "delete_space_recordings": ("POST", "/organisations/spaces/{space}/delete-recordings/"),
    "list_users": ("GET", "/organisations/users/"),
    "delete_user": ("DELETE", "/organisations/users/{user}/"),
    "launch_space": ("POST", "/spaces/launch/"),
    "list_space_sessions": ("GET", "/spaces/{space}/sessions/"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, key) for name, item in value.items() if name.lower() not in {"secret", "api_key", "authorization"}}
    return value


class LessonspaceNode(WorkflowNode):
    integration_type = "automation-lessonspace"
    connection_evidence = ConnectionEvidence(noun="Lessonspace organisation users", operation="list_users")

    @classmethod
    def get_config_model(cls):
        return LessonspaceFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Lessonspace API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude_unset=True)
        values.pop("operation", None)
        if config.operation == "launch_space":
            for name in ("name", "record_av", "record_content", "transcribe", "summarise", "video_layout_mode", "locale"):
                if name in config.model_fields_set and getattr(config, name) is None:
                    values[name] = None
        for name in ("session", "space", "user"):
            if "{" + name + "}" in route:
                value = values.pop("user_id" if name == "user" else name)
                route = route.replace("{" + name + "}", quote(str(value), safe=""))
                if config.operation == "delete_" + name + "_recordings":
                    values[name] = value  # Required body confirmation must match URL.
        kwargs = {"params": {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}} if method == "GET" else {"json": values} if method in {"POST", "PATCH"} else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Organisation " + key, "Accept": "application/json"}, **kwargs)
            status = response.status_code
            expected = {200, 201} if config.operation == "launch_space" else {204} if config.operation == "delete_user" else {200, 202, 204} if config.operation == "get_session_playback" else {200}
            if status not in expected:
                message = "Lessonspace request failed"
                try:
                    body = response.json()
                    if isinstance(body, dict):
                        message = body.get("detail") or body.get("error") or body.get("non_field_errors") or message
                except ValueError:
                    pass
                return {"status": "error", "http_status": status, "message": _redact(str(message), key)[:2000]}
            if status == 204:
                return {"status": "success", "http_status": status, "data": None,
                    **({"recording_state": "disabled"} if config.operation == "get_session_playback" else {"deleted": True})}
            if len(response.content) > 10_000_000:
                raise ValueError("Lessonspace response exceeds the JSON size limit")
            body = response.json()
            if not isinstance(body, dict) or any(k in body for k in ("error", "non_field_errors", "detail")):
                raise ValueError("Lessonspace returned an unexpected response")
            if config.operation.startswith("list_") and (not isinstance(body.get("results"), list) or not isinstance(body.get("count"), int)):
                raise ValueError("Lessonspace returned an unexpected page")
            return {"status": "success", "http_status": status, "data": _redact(body, key),
                **({"recording_state": "pending" if status == 202 else "available"} if config.operation == "get_session_playback" else {})}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "message": "Lessonspace request could not be confirmed"}
        except (ValueError, TypeError):
            return {"status": "error", "message": "Lessonspace response could not be parsed"}
