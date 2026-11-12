"""Circleback public API v1: one documented request per operation."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urljoin, urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://circleback.ai/api"


class CirclebackAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Circleback API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://circleback.ai/settings?tab=api-access",
            "x-credential-instructions": "In Circleback, open Settings → API keys and create a key. Paste the key without the Bearer prefix. NoClick verifies it by reading your account email.",
        })
    credential_type: Literal["circleback_api_key"] = Field("circleback_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste only the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CirclebackDeleteActionItemConfig(_Input):
    operation: Literal['delete_action_item'] = Field('delete_action_item', json_schema_extra={"ui:hidden": True})
    actionItemId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description='The unique identifier of the action item.')


class CirclebackUpdateActionItemConfig(_Input):
    operation: Literal['update_action_item'] = Field('update_action_item', json_schema_extra={"ui:hidden": True})
    actionItemId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description='The unique identifier of the action item.')
    title: str | None = Field(None, description='The title of the action item.')
    description: str | None = Field(None, description='The detailed description of the action item.')
    assigneeProfileId: Union[Annotated[int, Field(gt=0, strict=True)], None] = Field(None, description='The ID of the profile to assign the action item to, or null to remove the assignee.')
    status: Literal['PENDING', 'DONE'] | None = Field(None, description='The completion status of the action item.')


class CirclebackListActionItemsConfig(_Input):
    operation: Literal['list_action_items'] = Field('list_action_items', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor for the next page. Omit for the first page (RFC 8288).')
    assigneeType: Literal['Me', 'NotMe', 'Profile', 'MyWorkspace', 'OutsideMyWorkspace', 'Unassigned', 'Anyone'] | None = Field(None, description='The assignee scope to filter by. Defaults to Me.')
    assigneeProfileId: Annotated[int, Field(gt=0, strict=True)] | None = Field(None, description='Profile ID of the assignee to filter by.')
    assigneeTeamId: Annotated[int, Field(gt=0, strict=True)] | None = Field(None, description='Team ID of the assignee to filter by.')
    status: str | None = Field(None, description='Completion status to filter by. Defaults to incomplete action items.')
    attendeeProfileIds: list[str] | None = Field(None, description='Profile IDs of meeting attendees to filter by.')
    tagIds: list[str] | None = Field(None, description='Tag IDs to filter by.')


class CirclebackCreateActionItemConfig(_Input):
    operation: Literal['create_action_item'] = Field('create_action_item', json_schema_extra={"ui:hidden": True})
    title: Annotated[str, Field(min_length=1)] = Field(..., description='The title of the action item.')
    description: str | None = Field(None, description='The detailed description of the action item.')


class CirclebackListCalendarEventsConfig(_Input):
    operation: Literal['list_calendar_events'] = Field('list_calendar_events', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor for the next page. Omit for the first page (RFC 8288).')
    includeOfflineSingleAttendee: Annotated[bool, Field(strict=True)] | None = Field(None, description='Set to true to include calendar meetings that have no meeting link and only one attendee.')
    startTimeLookbackHours: float | None = Field(None, description='How many hours in the past to include calendar meetings from, based on their start time.')
    startTimeLookaheadHours: float | None = Field(None, description='How many hours in the future to include calendar meetings from, based on their start time.')
    sortDirection: Literal['ascending', 'descending'] | None = Field(None, description='The direction calendar meetings are sorted in by start time. Defaults to ascending.')


class CirclebackUpdateMeetingForCalendarEventConfig(_Input):
    operation: Literal['update_meeting_for_calendar_event'] = Field('update_meeting_for_calendar_event', json_schema_extra={"ui:hidden": True})
    calendarMeetingId: str = Field(..., description='The ID of the calendar meeting.')
    privateNotes: str | None = Field(None, description='Your private notes for the meeting in Markdown. Replaces your current private notes, so include any existing content you want to keep.')
    tagIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description="The IDs of the tags to set on the meeting. Replaces the meeting's current tags, so include the IDs of any tags you want to keep. Pass an empty array to remove all tags.")


class CirclebackListCompaniesConfig(_Input):
    operation: Literal['list_companies'] = Field('list_companies', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor for the next page. Omit for the first page (RFC 8288).')
    tagIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description='Filter companies to those with meetings that have these tag IDs.')


class CirclebackGetCompanyConfig(_Input):
    operation: Literal['get_company'] = Field('get_company', json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., description='The domain of the company to fetch.')


class CirclebackListFoldersConfig(_Input):
    operation: Literal['list_folders'] = Field('list_folders', json_schema_extra={"ui:hidden": True})


class CirclebackGetFolderConfig(_Input):
    operation: Literal['get_folder'] = Field('get_folder', json_schema_extra={"ui:hidden": True})
    folderId: Annotated[str, Field(min_length=1)] = Field(..., description='The unique identifier of the folder.')


class CirclebackDeleteMeetingConfig(_Input):
    operation: Literal['delete_meeting'] = Field('delete_meeting', json_schema_extra={"ui:hidden": True})
    meetingId: str = Field(..., description='The unique identifier of the meeting.')


class CirclebackGetMeetingConfig(_Input):
    operation: Literal['get_meeting'] = Field('get_meeting', json_schema_extra={"ui:hidden": True})
    meetingId: str = Field(..., description='The unique identifier of the meeting.')


class CirclebackUpdateMeetingConfig(_Input):
    operation: Literal['update_meeting'] = Field('update_meeting', json_schema_extra={"ui:hidden": True})
    meetingId: str = Field(..., description='The unique identifier of the meeting.')
    name: str | None = Field(None, description="The meeting's name. Replaces the current name.")
    notes: str | None = Field(None, description="The meeting's notes in Markdown. Replaces the current notes, so include any existing content you want to keep.")
    privateNotes: str | None = Field(None, description='Your private notes for the meeting in Markdown. Replaces your current private notes, so include any existing content you want to keep.')
    folderIds: list[Annotated[str, Field(min_length=1)]] | None = Field(None, description="The IDs of the folders to put the meeting in. Replaces the meeting's current folders, so start from its folderIds in ReadMeetings and include any you want to keep. Use ListFolders to find folder IDs. Folders that can't be added are listed in folderErrors; the rest still apply and nothing is removed.")
    tagIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description="The IDs of the tags to set on the meeting. Replaces the meeting's current tags, so include the IDs of any tags you want to keep. Pass an empty array to remove all tags.")


class CirclebackShareMeetingConfigTargetsItem0(_Input):
    access: Union[Literal['Editor', 'Viewer', 'LimitedViewer'], None] = Field(..., description='The access level to grant. Set to null to remove access.')
    email: EmailStr = Field(..., description='The email address to share the meeting with.')
    sendEmail: Annotated[bool, Field(strict=True)] | None = Field(None, description='Set to true to email the people the meeting is shared with.')


class CirclebackShareMeetingConfigTargetsItem1(_Input):
    profileId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description='The ID of the person to share the meeting with.')
    access: Union[Literal['Editor', 'Viewer', 'LimitedViewer'], None] = Field(..., description='The access level to grant. Set to null to remove access.')
    sendEmail: Annotated[bool, Field(strict=True)] | None = Field(None, description='Set to true to email the people the meeting is shared with.')


class CirclebackShareMeetingConfigTargetsItem2(_Input):
    access: Union[Literal['Editor', 'Viewer', 'LimitedViewer'], None] = Field(None, description='The access level to grant. Set to null to remove access.')
    sendEmail: Annotated[bool, Field(strict=True)] | None = Field(None, description='Set to true to email the people the meeting is shared with.')
    teamId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description='The unique identifier of the team to share the meeting with.')


class CirclebackShareMeetingConfigTargetsItem3(_Input):
    access: Union[Literal['Editor', 'Viewer', 'LimitedViewer'], None] = Field(None, description='The access level to grant. Set to null to remove access.')
    sendEmail: Annotated[bool, Field(strict=True)] | None = Field(None, description='Set to true to email the people the meeting is shared with.')
    workspaceId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description='The unique identifier of the workspace to share the meeting with.')


class CirclebackShareMeetingConfigTargetsItem4(_Input):
    linkAccess: Union[Literal['Editor', 'Viewer', 'LimitedViewer'], None] = Field(..., description='The access level for anyone with the meeting link. Set to null to turn off the link.')


class CirclebackShareMeetingConfig(_Input):
    operation: Literal['share_meeting'] = Field('share_meeting', json_schema_extra={"ui:hidden": True})
    meetingId: str = Field(..., description='The unique identifier of the meeting.')
    targets: Annotated[list[Union[CirclebackShareMeetingConfigTargetsItem0, CirclebackShareMeetingConfigTargetsItem1, CirclebackShareMeetingConfigTargetsItem2, CirclebackShareMeetingConfigTargetsItem3, CirclebackShareMeetingConfigTargetsItem4]], Field(min_length=1, max_length=50)] = Field(..., description='The people, teams, workspaces, or link to share with, up to 50. Targets that fail are listed in errors; the rest still apply.')


class CirclebackGetMeetingTranscriptConfig(_Input):
    operation: Literal['get_meeting_transcript'] = Field('get_meeting_transcript', json_schema_extra={"ui:hidden": True})
    meetingId: str = Field(..., description='The unique identifier of the meeting.')


class CirclebackListMeetingsConfig(_Input):
    operation: Literal['list_meetings'] = Field('list_meetings', json_schema_extra={"ui:hidden": True})
    ownership: Literal['All', 'Mine', 'Shared'] | None = Field(None, description='Whether to return only meetings the user owns or all meetings the user can access.')
    statuses: list[str] | None = Field(None, description='Meeting statuses to filter by.')
    folderId: str | None = Field(None, description='Folder ID to filter by. Set ownership to All to include meetings other people filed into the folder.')
    cursor: str | None = Field(None, description='Cursor for the next page. Omit for the first page (RFC 8288).')
    tagIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description='Tag IDs to filter by.')
    attendeeProfileIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description='Profile IDs of attendees to filter by.')


class CirclebackImportMeetingConfigTagsItem(_Input):
    name: str = Field(..., description='The display name of the tag.')
    description: Union[Annotated[str, Field(max_length=1000)], None] = Field(None, description='A description of the tag.')


class CirclebackImportMeetingConfigAttendeesItem(_Input):
    name: Annotated[str, Field(min_length=1)] | None = Field(None, description="The person's full name.")
    email: EmailStr = Field(..., description="The person's email address.")
    isCalendarEventOrganizer: Annotated[bool, Field(strict=True)] | None = Field(None, description='Whether the attendee organized the calendar event.')
    isCalendarInvitee: Annotated[bool, Field(strict=True)] | None = Field(None, description='Whether the attendee was invited on the calendar event.')


class CirclebackImportMeetingConfigTranscriptItemWordsItem(_Input):
    endTimestamp: Annotated[float, Field(ge=0)] | None = Field(None, description='The time the word ends at, in seconds from the beginning of the meeting.')
    startTimestamp: Annotated[float, Field(ge=0)] | None = Field(None, description='The time the word starts at, in seconds from the beginning of the meeting.')
    text: Annotated[str, Field(min_length=1)] = Field(..., description='The text of the word.')


class CirclebackImportMeetingConfigTranscriptItem(_Input):
    language: str | None = Field(None, description='The language code of the speech in the segment, if the language was detected.')
    speaker: Annotated[str, Field(min_length=1)] = Field(..., description='The name of the speaker in the segment.')
    text: Annotated[str, Field(min_length=1)] | None = Field(None, description='Words spoken.')
    timestamp: Annotated[float, Field(ge=0)] | None = Field(None, description='Timestamp in seconds that marks the beginning of the segment.')
    words: list[CirclebackImportMeetingConfigTranscriptItemWordsItem] | None = Field(None, description='The words spoken in the segment. Use this instead of text when word-level timestamps are available.')


class CirclebackImportMeetingConfigSharedWithItem(_Input):
    access: Literal['Editor', 'Viewer', 'LimitedViewer'] = Field(..., description='The access level to grant.')
    email: EmailStr = Field(..., description='The email address to share the meeting with.')


class CirclebackImportMeetingConfig(_Input):
    'A meeting to import.'
    operation: Literal['import_meeting'] = Field('import_meeting', json_schema_extra={"ui:hidden": True})
    name: Annotated[str, Field(min_length=1)] = Field(..., description='Meeting name.')
    createdAt: datetime | None = Field(None, description='Meeting creation date, formatted as an ISO 8601 timestamp. Defaults to now.')
    tags: list[CirclebackImportMeetingConfigTagsItem] | None = Field(None, description='Tags to add to the meeting.')
    attendees: list[CirclebackImportMeetingConfigAttendeesItem] | None = Field(None, description='Meeting attendees.')
    notes: Annotated[str, Field(min_length=1)] = Field(..., description='Meeting notes with Markdown formatting.')
    transcript: list[CirclebackImportMeetingConfigTranscriptItem] | None = Field(None, description='The segments of the transcript. Provide text and timestamp, or a words array with optional word-level timestamps.')
    sharedWith: list[CirclebackImportMeetingConfigSharedWithItem] | None = Field(None, description='People to share the meeting with.')


class CirclebackGetAccountConfig(_Input):
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"ui:hidden": True})


class CirclebackListPeopleConfig(_Input):
    operation: Literal['list_people'] = Field('list_people', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor for the next page. Omit for the first page (RFC 8288).')
    domains: list[str] | None = Field(None, description='Filter people to those associated with any of these company domains.')
    limit: Annotated[int, Field(gt=0, strict=True)] | None = Field(None, description='The maximum number of people to return.')
    tagIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description='Filter people to attendees of meetings with these tag IDs.')


class CirclebackGetPersonConfig(_Input):
    operation: Literal['get_person'] = Field('get_person', json_schema_extra={"ui:hidden": True})
    profileId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description="The unique identifier of the person's profile.")


class CirclebackSearchMeetingsConfig(_Input):
    operation: Literal['search_meetings'] = Field('search_meetings', json_schema_extra={"ui:hidden": True})
    searchTerm: str | None = Field(None, description='The text to search for across meeting names and content.')
    meetingIds: list[str] | None = Field(None, description='Restrict the search to the meetings with these IDs.')
    tagIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description='Restrict the search to meetings with these tag IDs.')
    cursor: str | None = Field(None, description='Cursor for the next page. Omit for the first page (RFC 8288).')
    attendeeProfileIds: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, description='Restrict the search to meetings attended by the people with these profile IDs.')


class CirclebackListTagsConfig(_Input):
    operation: Literal['list_tags'] = Field('list_tags', json_schema_extra={"ui:hidden": True})


class CirclebackCreateTagConfig(_Input):
    operation: Literal['create_tag'] = Field('create_tag', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='The display name of the tag.')
    description: Union[Annotated[str, Field(max_length=1000)], None] = Field(None, description='A description of the tag.')


class CirclebackDeleteTagConfig(_Input):
    operation: Literal['delete_tag'] = Field('delete_tag', json_schema_extra={"ui:hidden": True})
    tagId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description='The ID of the tag.')


class CirclebackUpdateTagConfig(_Input):
    operation: Literal['update_tag'] = Field('update_tag', json_schema_extra={"ui:hidden": True})
    tagId: Annotated[int, Field(gt=0, strict=True)] = Field(..., description='The ID of the tag.')
    name: str | None = Field(None, description='The display name of the tag.')
    description: Union[Annotated[str, Field(max_length=1000)], None] = Field(None, description='A description of the tag.')


# Circleback's own MCP server: agents get its tools through a person's Circleback sign-in.
CirclebackMcpCredential = mcp_credential("circleback", "https://circleback.ai/api/mcp", app="Circleback")
CirclebackCredential = Union[CirclebackAPIKeyCredential, CirclebackMcpCredential]


CirclebackConfig = Annotated[Union[CirclebackDeleteActionItemConfig, CirclebackUpdateActionItemConfig, CirclebackListActionItemsConfig, CirclebackCreateActionItemConfig, CirclebackListCalendarEventsConfig, CirclebackUpdateMeetingForCalendarEventConfig, CirclebackListCompaniesConfig, CirclebackGetCompanyConfig, CirclebackListFoldersConfig, CirclebackGetFolderConfig, CirclebackDeleteMeetingConfig, CirclebackGetMeetingConfig, CirclebackUpdateMeetingConfig, CirclebackShareMeetingConfig, CirclebackGetMeetingTranscriptConfig, CirclebackListMeetingsConfig, CirclebackImportMeetingConfig, CirclebackGetAccountConfig, CirclebackListPeopleConfig, CirclebackGetPersonConfig, CirclebackSearchMeetingsConfig, CirclebackListTagsConfig, CirclebackCreateTagConfig, CirclebackDeleteTagConfig, CirclebackUpdateTagConfig], Field(discriminator="operation")]


class CirclebackFullConfig(NodeConfig[CirclebackConfig, CirclebackCredential]):
    pass


ROUTES = {'delete_action_item': ('DELETE', '/action-item/{actionItemId}', ['actionItemId'], [], False),
 'update_action_item': ('PUT', '/action-item/{actionItemId}', ['actionItemId'], [], False),
 'list_action_items': ('GET',
                       '/action-items',
                       [],
                       ['cursor',
                        'assigneeType',
                        'assigneeProfileId',
                        'assigneeTeamId',
                        'status',
                        'attendeeProfileIds',
                        'tagIds'],
                       False),
 'create_action_item': ('POST', '/action-items', [], [], False),
 'list_calendar_events': ('GET',
                          '/calendar/events',
                          [],
                          ['cursor',
                           'includeOfflineSingleAttendee',
                           'startTimeLookbackHours',
                           'startTimeLookaheadHours',
                           'sortDirection'],
                          False),
 'update_meeting_for_calendar_event': ('PUT',
                                       '/calendar/events/{calendarMeetingId}/meeting',
                                       ['calendarMeetingId'],
                                       [],
                                       False),
 'list_companies': ('GET', '/companies', [], ['cursor', 'tagIds'], False),
 'get_company': ('GET', '/company/{domain}', ['domain'], [], False),
 'list_folders': ('GET', '/folder', [], [], False),
 'get_folder': ('GET', '/folder/{folderId}', ['folderId'], [], False),
 'delete_meeting': ('DELETE', '/meeting/{meetingId}', ['meetingId'], [], False),
 'get_meeting': ('GET', '/meeting/{meetingId}', ['meetingId'], [], False),
 'update_meeting': ('PUT', '/meeting/{meetingId}', ['meetingId'], [], False),
 'share_meeting': ('PUT', '/meeting/{meetingId}/share', ['meetingId'], [], True),
 'get_meeting_transcript': ('GET', '/meeting/{meetingId}/transcript', ['meetingId'], [], False),
 'list_meetings': ('GET',
                   '/meetings',
                   [],
                   ['ownership', 'statuses', 'folderId', 'cursor', 'tagIds', 'attendeeProfileIds'],
                   False),
 'import_meeting': ('POST', '/meetings', [], [], False),
 'get_account': ('GET', '/oauth/test', [], [], False),
 'list_people': ('GET', '/people', [], ['cursor', 'domains', 'limit', 'tagIds'], False),
 'get_person': ('GET', '/person/{profileId}', ['profileId'], [], False),
 'search_meetings': ('GET',
                     '/search',
                     [],
                     ['searchTerm', 'meetingIds', 'tagIds', 'cursor', 'attendeeProfileIds'],
                     False),
 'list_tags': ('GET', '/tag', [], [], False),
 'create_tag': ('POST', '/tag', [], [], False),
 'delete_tag': ('DELETE', '/tag/{tagId}', ['tagId'], [], False),
 'update_tag': ('PUT', '/tag/{tagId}', ['tagId'], [], False)}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class CirclebackNode(WorkflowNode):
    integration_type = "automation-circleback"
    credential_provider_labels = {"circleback": "Circleback Account"}
    connection_evidence = ConnectionEvidence(noun="Circleback account", identity_operation="get_account", label_keys=("email",))

    @classmethod
    def get_config_model(cls):
        return CirclebackFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Circleback API key")
        credential = self.config.credentials
        config = self.config.config
        method, path, path_fields, query_fields, array_body = ROUTES[config.operation]
        for name in path_fields:
            path = path.replace("{" + name + "}", quote(str(getattr(config, name)), safe=""))
        values = config.model_dump(exclude_unset=True, exclude={"operation", *path_fields}, mode="json")
        params = []
        for name in query_fields:
            value = values.get(name)
            if value is not None:
                for item in value if isinstance(value, list) else [value]:
                    params.append((name, str(item).lower() if isinstance(item, bool) else str(item)))
        body = None
        if method in {"POST", "PUT"}:
            body = values["targets"] if array_body else values
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
            if response.status_code != 200:
                message = "Circleback request failed (HTTP " + str(response.status_code) + ")"
                try:
                    error = response.json().get("error")
                    if isinstance(error, str):
                        message = error[:2000]
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "error": _redact(message, credential.api_key), "http_status": response.status_code}
            if len(response.content) > 10_000_000 or "json" not in response.headers.get("Content-Type", ""):
                raise ValueError("Expected bounded JSON from Circleback")
            data = response.json()
            if not isinstance(data, (dict, list)) or isinstance(data, dict) and data.get("error"):
                raise ValueError("Invalid Circleback response")
            expects_list = config.operation.startswith(("list_", "search_")) or config.operation == "get_meeting_transcript"
            if not isinstance(data, list if expects_list else dict):
                raise ValueError("Unexpected Circleback response shape")
            if config.operation == "get_account" and (not isinstance(data, dict) or not isinstance(data.get("email"), str)):
                raise ValueError("Circleback account email is missing")
            next_cursor = None
            link = response.links.get("next", {}).get("url")
            if link:
                target = urlsplit(urljoin(BASE + path, link))
                if target.scheme != "https" or target.netloc != "circleback.ai" or target.path != "/api" + path:
                    raise ValueError("Invalid Circleback pagination link")
                cursors = parse_qs(target.query).get("cursor", [])
                if len(cursors) != 1 or cursors[0] == getattr(config, "cursor", None):
                    raise ValueError("Invalid Circleback cursor")
                next_cursor = cursors[0]
            output = {"status": "success", "data": data, "http_status": 200}
            if query_fields:
                output.update(next_cursor=next_cursor, has_more=next_cursor is not None)
            return _redact(output, credential.api_key)
        except (httpx.HTTPError, ValueError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Circleback request could not be completed"
            return {"status": "error", "error": _redact(message, credential.api_key)}
