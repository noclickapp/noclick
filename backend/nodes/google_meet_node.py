"""
Google Meet automation node.

Provides workflow integration with the Google Meet REST API (v2) for
operations including:
- Spaces: create, get, update (full SpaceConfig — access, moderation +
  restrictions, and artifact auto-generation for recording/transcript/smart-notes),
  end active conference
- Conference Records: get, list
- Participants: get, list
- Participant Sessions: get, list
- Recordings: get, list
- Transcripts: get, list
- Transcript Entries: get, list
- Smart Notes (Gemini summaries): get, list

Authentication: OAuth 2.0 (Google) — user-delegated Bearer token. The Meet REST
API supports user authentication only; there is no API key path.
API Base URL: https://meet.googleapis.com/v2 (stable)
Documentation: https://developers.google.com/workspace/meet/api/guides/overview

Webhooks: Google Meet has no native webhook registration API. Real-time events
are delivered through the Google Workspace Events API + Cloud Pub/Sub, which
requires Pub/Sub infrastructure rather than a pasteable URL. Instead, this node
ships a POLL-BASED trigger (`on_new_conference_record`) that polls
conferenceRecords.list on a schedule and fires for newly-ended meetings,
deduplicating on the conference record resource name.
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
# Aliased: this module already binds GOOGLE_MEET_SCOPES to the requested-scope list.
from nodes.scopes.google_cloud import GOOGLE_MEET_SCOPES as MEET_SCOPE_REGISTRY

logger = logging.getLogger(__name__)

GOOGLE_MEET_API_BASE = "https://meet.googleapis.com/v2"

GOOGLE_MEET_SCOPES = [
    "https://www.googleapis.com/auth/meetings.space.created",
    "https://www.googleapis.com/auth/meetings.space.readonly",
    "https://www.googleapis.com/auth/meetings.space.settings",
]

# Shared searchable-enum extras for the space-settings fields (all live-verified
# against the Meet REST v2 SpaceConfig). "" maps to "leave unchanged/default".
_AUTO_GEN_EXTRA = {
    "enum": ["", "ON", "OFF"],
    "enumNames": ["Default", "On", "Off"],
    "x-enum-searchable": True,
}
_RESTRICTION_EXTRA = {
    "enum": ["", "HOSTS_ONLY", "NO_RESTRICTION"],
    "enumNames": ["Default", "Hosts only", "No restriction"],
    "x-enum-searchable": True,
}


# ============================================================================
# Credential Schema
# ============================================================================


class GoogleMeetOAuthCredential(BaseModel):
    """
    OAuth credential for Google Meet access.
    Tokens are obtained via the Google OAuth flow, not entered manually.
    """

    credential_type: Literal["google_meet_oauth"] = Field(
        "google_meet_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when the access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": GOOGLE_MEET_SCOPES,
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
        }
    )


GoogleMeetCredential = GoogleMeetOAuthCredential


# ============================================================================
# Operation Configs — Spaces
# ============================================================================


class GoogleMeetCreateSpaceConfig(BaseModel):
    """Create a new meeting space; returns the shareable meeting URI and code."""

    operation: Literal["create_space"] = Field(
        "create_space",
        json_schema_extra={
            "const": "create_space",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "Create Meeting Space",
        },
        title="Create Meeting Space",
    )
    access_type: Optional[str] = Field(
        None,
        title="Access Type",
        description="Who can join without knocking",
        json_schema_extra={
            "enum": ["", "OPEN", "TRUSTED", "RESTRICTED"],
            "enumNames": ["Default", "Open (anyone with the link)", "Trusted (same org)", "Restricted (invited only)"],
            "x-enum-searchable": True,
        },
    )
    entry_point_access: Optional[str] = Field(
        None,
        title="Entry Point Access",
        description="Which clients can be used to join",
        json_schema_extra={
            "enum": ["", "ALL", "CREATOR_APP_ONLY"],
            "enumNames": ["Default", "All clients", "Creator app only"],
            "x-enum-searchable": True,
        },
    )
    moderation: Optional[str] = Field(
        None,
        title="Moderation",
        description="Whether the host has moderation controls on",
        json_schema_extra={
            "enum": ["", "ON", "OFF"],
            "enumNames": ["Default", "On", "Off"],
            "x-enum-searchable": True,
        },
    )
    auto_recording: Optional[str] = Field(
        None,
        title="Auto Recording",
        description="Automatically record the meeting (host must be a Workspace user with recording enabled)",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )
    auto_transcription: Optional[str] = Field(
        None,
        title="Auto Transcription",
        description="Automatically generate a transcript of the meeting",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )
    auto_smart_notes: Optional[str] = Field(
        None,
        title="Auto Smart Notes",
        description="Automatically generate Gemini smart notes (meeting summary)",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )
    chat_restriction: Optional[str] = Field(
        None,
        title="Chat Restriction",
        description="Who can send chat messages (requires moderation On)",
        json_schema_extra=_RESTRICTION_EXTRA,
    )
    reaction_restriction: Optional[str] = Field(
        None,
        title="Reaction Restriction",
        description="Who can send reactions (requires moderation On)",
        json_schema_extra=_RESTRICTION_EXTRA,
    )
    present_restriction: Optional[str] = Field(
        None,
        title="Present Restriction",
        description="Who can present/share their screen (requires moderation On)",
        json_schema_extra=_RESTRICTION_EXTRA,
    )
    default_join_as_viewer: Optional[str] = Field(
        None,
        title="Default Join As Viewer",
        description="Whether attendees join as viewers by default (requires moderation On)",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )


class GoogleMeetGetSpaceConfig(BaseModel):
    """Get a meeting space by resource name (spaces/{space}) or meeting code."""

    operation: Literal["get_space"] = Field(
        "get_space",
        json_schema_extra={
            "const": "get_space",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "Get Meeting Space",
        },
        title="Get Meeting Space",
    )
    space_name: str = Field(
        ...,
        title="Space",
        description="Space resource name 'spaces/{space}', the {space} id, or the meeting code",
    )


class GoogleMeetUpdateSpaceConfig(BaseModel):
    """Update a meeting space's configuration (access type, moderation)."""

    operation: Literal["update_space"] = Field(
        "update_space",
        json_schema_extra={
            "const": "update_space",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "Update Meeting Space",
        },
        title="Update Meeting Space",
    )
    space_name: str = Field(
        ...,
        title="Space",
        description="Space resource name 'spaces/{space}' or the {space} id to update",
    )
    access_type: Optional[str] = Field(
        None,
        title="Access Type",
        description="Who can join without knocking",
        json_schema_extra={
            "enum": ["", "OPEN", "TRUSTED", "RESTRICTED"],
            "enumNames": ["Unchanged", "Open (anyone with the link)", "Trusted (same org)", "Restricted (invited only)"],
            "x-enum-searchable": True,
        },
    )
    entry_point_access: Optional[str] = Field(
        None,
        title="Entry Point Access",
        description="Which clients can be used to join",
        json_schema_extra={
            "enum": ["", "ALL", "CREATOR_APP_ONLY"],
            "enumNames": ["Unchanged", "All clients", "Creator app only"],
            "x-enum-searchable": True,
        },
    )
    moderation: Optional[str] = Field(
        None,
        title="Moderation",
        description="Whether the host has moderation controls on",
        json_schema_extra={
            "enum": ["", "ON", "OFF"],
            "enumNames": ["Unchanged", "On", "Off"],
            "x-enum-searchable": True,
        },
    )
    auto_recording: Optional[str] = Field(
        None,
        title="Auto Recording",
        description="Automatically record the meeting (host must be a Workspace user with recording enabled)",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )
    auto_transcription: Optional[str] = Field(
        None,
        title="Auto Transcription",
        description="Automatically generate a transcript of the meeting",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )
    auto_smart_notes: Optional[str] = Field(
        None,
        title="Auto Smart Notes",
        description="Automatically generate Gemini smart notes (meeting summary)",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )
    chat_restriction: Optional[str] = Field(
        None,
        title="Chat Restriction",
        description="Who can send chat messages (requires moderation On)",
        json_schema_extra=_RESTRICTION_EXTRA,
    )
    reaction_restriction: Optional[str] = Field(
        None,
        title="Reaction Restriction",
        description="Who can send reactions (requires moderation On)",
        json_schema_extra=_RESTRICTION_EXTRA,
    )
    present_restriction: Optional[str] = Field(
        None,
        title="Present Restriction",
        description="Who can present/share their screen (requires moderation On)",
        json_schema_extra=_RESTRICTION_EXTRA,
    )
    default_join_as_viewer: Optional[str] = Field(
        None,
        title="Default Join As Viewer",
        description="Whether attendees join as viewers by default (requires moderation On)",
        json_schema_extra=_AUTO_GEN_EXTRA,
    )


class GoogleMeetEndActiveConferenceConfig(BaseModel):
    """End the conference currently active in a space (removes all participants)."""

    operation: Literal["end_active_conference"] = Field(
        "end_active_conference",
        json_schema_extra={
            "const": "end_active_conference",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "End Active Conference",
        },
        title="End Active Conference",
    )
    space_name: str = Field(
        ...,
        title="Space",
        description="Space resource name 'spaces/{space}' or the {space} id whose active conference to end",
    )


# ============================================================================
# Operation Configs — Conference Records
# ============================================================================


class GoogleMeetGetConferenceRecordConfig(BaseModel):
    """Get a single past-meeting conference record."""

    operation: Literal["get_conference_record"] = Field(
        "get_conference_record",
        json_schema_extra={
            "const": "get_conference_record",
            "ui:hidden": True,
            "x-category": "Conference Records",
            "x-is-trigger": False,
            "x-display-name": "Get Conference Record",
        },
        title="Get Conference Record",
    )
    conference_record_name: str = Field(
        ...,
        title="Conference Record",
        description="Resource name 'conferenceRecords/{conference_record}' or the {conference_record} id",
    )


class GoogleMeetListConferenceRecordsConfig(BaseModel):
    """List past conference records; supports a filter and pagination."""

    operation: Literal["list_conference_records"] = Field(
        "list_conference_records",
        json_schema_extra={
            "const": "list_conference_records",
            "ui:hidden": True,
            "x-category": "Conference Records",
            "x-is-trigger": False,
            "x-display-name": "List Conference Records",
        },
        title="List Conference Records",
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description='EBNF filter, e.g. space.name="spaces/abc" or start_time>="2026-01-01T00:00:00Z"',
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Max records to return (default 25, max 100)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


# ============================================================================
# Operation Config — Trigger (poll-based)
# ============================================================================


class GoogleMeetOnNewConferenceRecordConfig(PollTriggerConfigBase):
    """Trigger: polls conferenceRecords.list on a schedule and fires for newly
    ended meetings. Google Meet has no push webhooks, so this baselines on the
    first poll and then emits each new conference record exactly once,
    deduplicating on the record's resource name."""

    operation: Literal["on_new_conference_record"] = Field(
        "on_new_conference_record",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Meeting",
        },
        title="On New Meeting",
    )
    space_name: Optional[str] = Field(
        None,
        title="Space",
        description="Only fire for meetings in this space ('spaces/{space}' or the {space} id). Leave blank to watch all accessible meetings.",
    )


# ============================================================================
# Operation Configs — Participants
# ============================================================================


class GoogleMeetGetParticipantConfig(BaseModel):
    """Get a single participant of a conference record."""

    operation: Literal["get_participant"] = Field(
        "get_participant",
        json_schema_extra={
            "const": "get_participant",
            "ui:hidden": True,
            "x-category": "Participants",
            "x-is-trigger": False,
            "x-display-name": "Get Participant",
        },
        title="Get Participant",
    )
    participant_name: str = Field(
        ...,
        title="Participant",
        description="Full resource name 'conferenceRecords/{record}/participants/{participant}'",
    )


class GoogleMeetListParticipantsConfig(BaseModel):
    """List all participants for a conference record."""

    operation: Literal["list_participants"] = Field(
        "list_participants",
        json_schema_extra={
            "const": "list_participants",
            "ui:hidden": True,
            "x-category": "Participants",
            "x-is-trigger": False,
            "x-display-name": "List Participants",
        },
        title="List Participants",
    )
    conference_record_name: str = Field(
        ...,
        title="Conference Record",
        description="Resource name 'conferenceRecords/{conference_record}' or the {conference_record} id",
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description='EBNF filter, e.g. earliest_start_time or latest_end_time conditions',
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Max participants to return (default 100, max 250)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


class GoogleMeetGetParticipantSessionConfig(BaseModel):
    """Get one join/leave session for a participant."""

    operation: Literal["get_participant_session"] = Field(
        "get_participant_session",
        json_schema_extra={
            "const": "get_participant_session",
            "ui:hidden": True,
            "x-category": "Participant Sessions",
            "x-is-trigger": False,
            "x-display-name": "Get Participant Session",
        },
        title="Get Participant Session",
    )
    participant_session_name: str = Field(
        ...,
        title="Participant Session",
        description="Full resource name 'conferenceRecords/{record}/participants/{participant}/participantSessions/{session}'",
    )


class GoogleMeetListParticipantSessionsConfig(BaseModel):
    """List a participant's device-level join/leave sessions."""

    operation: Literal["list_participant_sessions"] = Field(
        "list_participant_sessions",
        json_schema_extra={
            "const": "list_participant_sessions",
            "ui:hidden": True,
            "x-category": "Participant Sessions",
            "x-is-trigger": False,
            "x-display-name": "List Participant Sessions",
        },
        title="List Participant Sessions",
    )
    participant_name: str = Field(
        ...,
        title="Participant",
        description="Parent resource name 'conferenceRecords/{record}/participants/{participant}'",
    )
    filter: Optional[str] = Field(
        None, title="Filter", description="EBNF filter on session start/end time"
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Max sessions to return (default 100, max 250)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


# ============================================================================
# Operation Configs — Recordings
# ============================================================================


class GoogleMeetGetRecordingConfig(BaseModel):
    """Get a recording's metadata and Drive file reference."""

    operation: Literal["get_recording"] = Field(
        "get_recording",
        json_schema_extra={
            "const": "get_recording",
            "ui:hidden": True,
            "x-category": "Recordings",
            "x-is-trigger": False,
            "x-display-name": "Get Recording",
        },
        title="Get Recording",
    )
    recording_name: str = Field(
        ...,
        title="Recording",
        description="Full resource name 'conferenceRecords/{record}/recordings/{recording}'",
    )


class GoogleMeetListRecordingsConfig(BaseModel):
    """List recordings produced by a conference record."""

    operation: Literal["list_recordings"] = Field(
        "list_recordings",
        json_schema_extra={
            "const": "list_recordings",
            "ui:hidden": True,
            "x-category": "Recordings",
            "x-is-trigger": False,
            "x-display-name": "List Recordings",
        },
        title="List Recordings",
    )
    conference_record_name: str = Field(
        ...,
        title="Conference Record",
        description="Resource name 'conferenceRecords/{conference_record}' or the {conference_record} id",
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Max recordings to return (default 10, max 100)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


# ============================================================================
# Operation Configs — Transcripts
# ============================================================================


class GoogleMeetGetTranscriptConfig(BaseModel):
    """Get a transcript's metadata and Google Docs reference."""

    operation: Literal["get_transcript"] = Field(
        "get_transcript",
        json_schema_extra={
            "const": "get_transcript",
            "ui:hidden": True,
            "x-category": "Transcripts",
            "x-is-trigger": False,
            "x-display-name": "Get Transcript",
        },
        title="Get Transcript",
    )
    transcript_name: str = Field(
        ...,
        title="Transcript",
        description="Full resource name 'conferenceRecords/{record}/transcripts/{transcript}'",
    )


class GoogleMeetListTranscriptsConfig(BaseModel):
    """List transcripts for a conference record."""

    operation: Literal["list_transcripts"] = Field(
        "list_transcripts",
        json_schema_extra={
            "const": "list_transcripts",
            "ui:hidden": True,
            "x-category": "Transcripts",
            "x-is-trigger": False,
            "x-display-name": "List Transcripts",
        },
        title="List Transcripts",
    )
    conference_record_name: str = Field(
        ...,
        title="Conference Record",
        description="Resource name 'conferenceRecords/{conference_record}' or the {conference_record} id",
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Max transcripts to return (default 10, max 100)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


class GoogleMeetGetTranscriptEntryConfig(BaseModel):
    """Get a single spoken transcript entry (speaker, text, timing)."""

    operation: Literal["get_transcript_entry"] = Field(
        "get_transcript_entry",
        json_schema_extra={
            "const": "get_transcript_entry",
            "ui:hidden": True,
            "x-category": "Transcripts",
            "x-is-trigger": False,
            "x-display-name": "Get Transcript Entry",
        },
        title="Get Transcript Entry",
    )
    entry_name: str = Field(
        ...,
        title="Transcript Entry",
        description="Full resource name 'conferenceRecords/{record}/transcripts/{transcript}/entries/{entry}'",
    )


class GoogleMeetListTranscriptEntriesConfig(BaseModel):
    """List the structured transcript entries for a transcript."""

    operation: Literal["list_transcript_entries"] = Field(
        "list_transcript_entries",
        json_schema_extra={
            "const": "list_transcript_entries",
            "ui:hidden": True,
            "x-category": "Transcripts",
            "x-is-trigger": False,
            "x-display-name": "List Transcript Entries",
        },
        title="List Transcript Entries",
    )
    transcript_name: str = Field(
        ...,
        title="Transcript",
        description="Parent resource name 'conferenceRecords/{record}/transcripts/{transcript}'",
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Max entries to return (default 100, max 1000)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


# ============================================================================
# Operation Configs — Smart Notes (Gemini meeting summaries)
# ============================================================================


class GoogleMeetGetSmartNotesConfig(BaseModel):
    """Get a smart-notes (Gemini summary) artifact's metadata and Docs reference."""

    operation: Literal["get_smart_notes"] = Field(
        "get_smart_notes",
        json_schema_extra={
            "const": "get_smart_notes",
            "ui:hidden": True,
            "x-category": "Smart Notes",
            "x-is-trigger": False,
            "x-display-name": "Get Smart Notes",
        },
        title="Get Smart Notes",
    )
    smart_notes_name: str = Field(
        ...,
        title="Smart Notes",
        description="Full resource name 'conferenceRecords/{record}/smartNotes/{smart_notes}'",
    )


class GoogleMeetListSmartNotesConfig(BaseModel):
    """List the smart-notes (Gemini summary) artifacts for a conference record."""

    operation: Literal["list_smart_notes"] = Field(
        "list_smart_notes",
        json_schema_extra={
            "const": "list_smart_notes",
            "ui:hidden": True,
            "x-category": "Smart Notes",
            "x-is-trigger": False,
            "x-display-name": "List Smart Notes",
        },
        title="List Smart Notes",
    )
    conference_record_name: str = Field(
        ...,
        title="Conference Record",
        description="Resource name 'conferenceRecords/{conference_record}' or the {conference_record} id",
    )
    page_size: Optional[str] = Field(
        None, title="Page Size", description="Max smart notes to return (default 10, max 100)"
    )
    page_token: Optional[str] = Field(
        None, title="Page Token", description="Token from a previous response for the next page"
    )


# ============================================================================
# Discriminated Union
# ============================================================================


GoogleMeetConfig = Annotated[
    Union[
        GoogleMeetOnNewConferenceRecordConfig,
        GoogleMeetCreateSpaceConfig,
        GoogleMeetGetSpaceConfig,
        GoogleMeetUpdateSpaceConfig,
        GoogleMeetEndActiveConferenceConfig,
        GoogleMeetGetConferenceRecordConfig,
        GoogleMeetListConferenceRecordsConfig,
        GoogleMeetGetParticipantConfig,
        GoogleMeetListParticipantsConfig,
        GoogleMeetGetParticipantSessionConfig,
        GoogleMeetListParticipantSessionsConfig,
        GoogleMeetGetRecordingConfig,
        GoogleMeetListRecordingsConfig,
        GoogleMeetGetTranscriptConfig,
        GoogleMeetListTranscriptsConfig,
        GoogleMeetGetTranscriptEntryConfig,
        GoogleMeetListTranscriptEntriesConfig,
        GoogleMeetGetSmartNotesConfig,
        GoogleMeetListSmartNotesConfig,
    ],
    Discriminator("operation"),
]


class GoogleMeetNodeConfig(NodeConfig[GoogleMeetConfig, GoogleMeetCredential]):
    """Full configuration for the Google Meet node including credentials."""

    pass


# ============================================================================
# Resource-name normalization helpers
# ============================================================================


def _normalize_resource(value: str, prefix: str) -> str:
    """Accept either a bare id or a full 'prefix/id' resource name and return
    the full resource name. Multi-segment resource names (containing '/') are
    returned unchanged."""
    value = (value or "").strip()
    if "/" in value:
        return value
    return f"{prefix}/{value}"


def _build_space_config(c: Any) -> tuple[Dict[str, Any], List[str]]:
    """Build the nested SpaceConfig body + field-mask paths from a create/update
    config. Shared by create_space and update_space so both cover the full
    SpaceConfig surface. Only fields the user set (truthy) are emitted; the
    update mask lists exactly those paths (create ignores the mask). Field names
    are live-verified against the Meet REST v2 SpaceConfig."""
    config: Dict[str, Any] = {}
    paths: List[str] = []

    def _set(attr: str, key: str, path: str) -> None:
        val = getattr(c, attr, None)
        if val:
            config[key] = val
            paths.append(path)

    _set("access_type", "accessType", "config.accessType")
    _set("entry_point_access", "entryPointAccess", "config.entryPointAccess")
    _set("moderation", "moderation", "config.moderation")

    restrictions: Dict[str, Any] = {}
    if getattr(c, "chat_restriction", None):
        restrictions["chatRestriction"] = c.chat_restriction
    if getattr(c, "reaction_restriction", None):
        restrictions["reactionRestriction"] = c.reaction_restriction
    if getattr(c, "present_restriction", None):
        restrictions["presentRestriction"] = c.present_restriction
    if getattr(c, "default_join_as_viewer", None):
        restrictions["defaultJoinAsViewerType"] = c.default_join_as_viewer
    if restrictions:
        config["moderationRestrictions"] = restrictions
        paths.append("config.moderationRestrictions")

    artifact: Dict[str, Any] = {}
    if getattr(c, "auto_recording", None):
        artifact["recordingConfig"] = {"autoRecordingGeneration": c.auto_recording}
    if getattr(c, "auto_transcription", None):
        artifact["transcriptionConfig"] = {"autoTranscriptionGeneration": c.auto_transcription}
    if getattr(c, "auto_smart_notes", None):
        artifact["smartNotesConfig"] = {"autoSmartNotesGeneration": c.auto_smart_notes}
    if artifact:
        config["artifactConfig"] = artifact
        paths.append("config.artifactConfig")

    return config, paths


# ============================================================================
# Node Implementation
# ============================================================================


class GoogleMeetNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Google Meet automation node (OAuth, Meet REST API v2)."""

    edit_examples = [
        "Create a new Google Meet space and return the join link",
        "List the conference records for a meeting space",
        "List the participants of the last conference",
        "Get the transcript entries for a finished meeting",
        "End the active conference in a meeting space",
        "When a meeting ends, summarize the transcript and post it to Slack",
    ]

    scope_registry = MEET_SCOPE_REGISTRY
    connection_evidence = ConnectionEvidence(
        operation="list_conference_records",
        noun="recent meetings",
    )

    @classmethod
    def get_config_model(cls):
        return GoogleMeetNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns / triggers)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="google",
        )

    # ------------------------------------------------------------------
    # OAuth token refresh
    # ------------------------------------------------------------------
    async def _ensure_fresh_token(self, credentials: GoogleMeetOAuthCredential) -> str:
        """Return a valid Google access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ------------------------------------------------------------------
    # HTTP request helper
    # ------------------------------------------------------------------
    async def _make_request(
        self,
        method: str,
        url: str,
        access_token: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        if json_body is not None:
            json_body = {k: v for k, v in json_body.items() if v is not None}
        if params:
            params = {k: v for k, v in params.items() if v not in (None, "")}

        start_time = time.time()
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )
                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    try:
                        err = response.json()
                        error_obj = err.get("error", err)
                        message = (
                            error_obj.get("message")
                            if isinstance(error_obj, dict)
                            else str(error_obj)
                        )
                    except Exception:
                        message = response.text
                    if isinstance(message, str):
                        message = message.encode("ascii", errors="replace").decode("ascii")
                    logger.error(f"[GoogleMeetNode] API error ({action_name}): {message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                if response.status_code == 204 or not response.content:
                    data: Any = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
                }
            except Exception as e:
                error_msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[GoogleMeetNode] Request failed ({action_name}): {error_msg}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": error_msg,
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
                }

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, GoogleMeetNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your Google account to use Google Meet."
            )

        access_token = await self._ensure_fresh_token(credentials)
        op = config.config

        handlers = {
            "on_new_conference_record": self._trigger_on_new_conference_record,
            "create_space": self._create_space,
            "get_space": self._get_space,
            "update_space": self._update_space,
            "end_active_conference": self._end_active_conference,
            "get_conference_record": self._get_conference_record,
            "list_conference_records": self._list_conference_records,
            "get_participant": self._get_participant,
            "list_participants": self._list_participants,
            "get_participant_session": self._get_participant_session,
            "list_participant_sessions": self._list_participant_sessions,
            "get_recording": self._get_recording,
            "list_recordings": self._list_recordings,
            "get_transcript": self._get_transcript,
            "list_transcripts": self._list_transcripts,
            "get_transcript_entry": self._get_transcript_entry,
            "list_transcript_entries": self._list_transcript_entries,
            "get_smart_notes": self._get_smart_notes,
            "list_smart_notes": self._list_smart_notes,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, access_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Trigger — poll conferenceRecords.list for newly-ended meetings
    # ------------------------------------------------------------------
    async def _trigger_on_new_conference_record(
        self, c: GoogleMeetOnNewConferenceRecordConfig, token: str
    ) -> Dict[str, Any]:
        """Poll past conference records and emit only newly-ended meetings.

        Google Meet has no push webhooks; the cron POST is a wake-up signal.
        We list conference records (optionally scoped to a space), then dedupe
        on the record resource name via ``_filter_unseen`` so each ended meeting
        fires the trigger exactly once. The first poll baselines (emits nothing).
        """
        params: Dict[str, Any] = {"pageSize": "100"}
        if c.space_name:
            space = _normalize_resource(c.space_name, "spaces")
            params["filter"] = f'space.name="{space}"'

        result = await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/conferenceRecords", token,
            params=params, action_name="on_new_conference_record",
        )
        if result.get("status") == "error":
            return result

        records = result.get("data", {}).get("conferenceRecords", [])
        # Only consider meetings that have actually ended (endTime present).
        ended = [r for r in records if r.get("endTime")]
        new_records = await self._filter_unseen(ended, lambda r: r.get("name"))

        return {
            "status": "success",
            "operation": "on_new_conference_record",
            "conference_records": new_records,
            "new_count": len(new_records),
            "space_name": c.space_name,
        }

    # ------------------------------------------------------------------
    # Spaces
    # ------------------------------------------------------------------
    async def _create_space(
        self, c: GoogleMeetCreateSpaceConfig, token: str
    ) -> Dict[str, Any]:
        space_config, _ = _build_space_config(c)
        body = {"config": space_config} if space_config else {}
        return await self._make_request(
            "POST", f"{GOOGLE_MEET_API_BASE}/spaces", token, json_body=body,
            action_name="create_space",
        )

    async def _get_space(self, c: GoogleMeetGetSpaceConfig, token: str) -> Dict[str, Any]:
        name = _normalize_resource(c.space_name, "spaces")
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{name}", token, action_name="get_space"
        )

    async def _update_space(
        self, c: GoogleMeetUpdateSpaceConfig, token: str
    ) -> Dict[str, Any]:
        name = _normalize_resource(c.space_name, "spaces")
        space_config, update_paths = _build_space_config(c)
        body = {"config": space_config}
        params = {"updateMask": ",".join(update_paths)} if update_paths else None
        return await self._make_request(
            "PATCH", f"{GOOGLE_MEET_API_BASE}/{name}", token, params=params,
            json_body=body, action_name="update_space",
        )

    async def _end_active_conference(
        self, c: GoogleMeetEndActiveConferenceConfig, token: str
    ) -> Dict[str, Any]:
        name = _normalize_resource(c.space_name, "spaces")
        return await self._make_request(
            "POST", f"{GOOGLE_MEET_API_BASE}/{name}:endActiveConference", token,
            json_body={}, action_name="end_active_conference",
        )

    # ------------------------------------------------------------------
    # Conference Records
    # ------------------------------------------------------------------
    async def _get_conference_record(
        self, c: GoogleMeetGetConferenceRecordConfig, token: str
    ) -> Dict[str, Any]:
        name = _normalize_resource(c.conference_record_name, "conferenceRecords")
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{name}", token,
            action_name="get_conference_record",
        )

    async def _list_conference_records(
        self, c: GoogleMeetListConferenceRecordsConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "filter": c.filter,
            "pageSize": c.page_size,
            "pageToken": c.page_token,
        }
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/conferenceRecords", token, params=params,
            action_name="list_conference_records",
        )

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    async def _get_participant(
        self, c: GoogleMeetGetParticipantConfig, token: str
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{c.participant_name.strip()}", token,
            action_name="get_participant",
        )

    async def _list_participants(
        self, c: GoogleMeetListParticipantsConfig, token: str
    ) -> Dict[str, Any]:
        parent = _normalize_resource(c.conference_record_name, "conferenceRecords")
        params = {"filter": c.filter, "pageSize": c.page_size, "pageToken": c.page_token}
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{parent}/participants", token, params=params,
            action_name="list_participants",
        )

    async def _get_participant_session(
        self, c: GoogleMeetGetParticipantSessionConfig, token: str
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{c.participant_session_name.strip()}", token,
            action_name="get_participant_session",
        )

    async def _list_participant_sessions(
        self, c: GoogleMeetListParticipantSessionsConfig, token: str
    ) -> Dict[str, Any]:
        parent = c.participant_name.strip()
        params = {"filter": c.filter, "pageSize": c.page_size, "pageToken": c.page_token}
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{parent}/participantSessions", token,
            params=params, action_name="list_participant_sessions",
        )

    # ------------------------------------------------------------------
    # Recordings
    # ------------------------------------------------------------------
    async def _get_recording(
        self, c: GoogleMeetGetRecordingConfig, token: str
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{c.recording_name.strip()}", token,
            action_name="get_recording",
        )

    async def _list_recordings(
        self, c: GoogleMeetListRecordingsConfig, token: str
    ) -> Dict[str, Any]:
        parent = _normalize_resource(c.conference_record_name, "conferenceRecords")
        params = {"pageSize": c.page_size, "pageToken": c.page_token}
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{parent}/recordings", token, params=params,
            action_name="list_recordings",
        )

    # ------------------------------------------------------------------
    # Transcripts
    # ------------------------------------------------------------------
    async def _get_transcript(
        self, c: GoogleMeetGetTranscriptConfig, token: str
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{c.transcript_name.strip()}", token,
            action_name="get_transcript",
        )

    async def _list_transcripts(
        self, c: GoogleMeetListTranscriptsConfig, token: str
    ) -> Dict[str, Any]:
        parent = _normalize_resource(c.conference_record_name, "conferenceRecords")
        params = {"pageSize": c.page_size, "pageToken": c.page_token}
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{parent}/transcripts", token, params=params,
            action_name="list_transcripts",
        )

    async def _get_transcript_entry(
        self, c: GoogleMeetGetTranscriptEntryConfig, token: str
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{c.entry_name.strip()}", token,
            action_name="get_transcript_entry",
        )

    async def _list_transcript_entries(
        self, c: GoogleMeetListTranscriptEntriesConfig, token: str
    ) -> Dict[str, Any]:
        parent = c.transcript_name.strip()
        params = {"pageSize": c.page_size, "pageToken": c.page_token}
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{parent}/entries", token, params=params,
            action_name="list_transcript_entries",
        )

    # ------------------------------------------------------------------
    # Smart Notes
    # ------------------------------------------------------------------
    async def _get_smart_notes(
        self, c: GoogleMeetGetSmartNotesConfig, token: str
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{c.smart_notes_name.strip()}", token,
            action_name="get_smart_notes",
        )

    async def _list_smart_notes(
        self, c: GoogleMeetListSmartNotesConfig, token: str
    ) -> Dict[str, Any]:
        parent = _normalize_resource(c.conference_record_name, "conferenceRecords")
        params = {"pageSize": c.page_size, "pageToken": c.page_token}
        return await self._make_request(
            "GET", f"{GOOGLE_MEET_API_BASE}/{parent}/smartNotes", token, params=params,
            action_name="list_smart_notes",
        )
