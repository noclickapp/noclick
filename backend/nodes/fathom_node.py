"""
Fathom meeting-notetaker automation node.

Provides workflow integration with the Fathom external REST API for operations including:
- Meetings: list (with rich filters + content includes), list by type / with summaries /
  with action items / with CRM matches / external-only presets
- Meeting Types: list
- Recordings: get summary, get transcript
- Teams: list teams, list team members
- Webhooks: create, delete (API-managed)
- Trigger: fire the workflow when a new meeting is processed (newMeeting webhook)

Authentication: API Key (header X-Api-Key), Bearer token, or OAuth 2.0
API Base URL: https://api.fathom.ai/external/v1
Documentation: https://developers.fathom.ai

Note: this is the Fathom AI meeting notetaker (fathom.video / api.fathom.ai), NOT
Fathom Analytics (api.usefathom.com) or Fathom Global flood data.
"""

import base64
import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.scheduling import FATHOM_SCOPES

logger = logging.getLogger(__name__)

FATHOM_API_BASE = "https://api.fathom.ai/external/v1"
FATHOM_DATETIME_WIDGET = {
    "ui:widget": "datetime",
    "ui:placeholder": "2026-01-01T00:00:00Z",
}
FATHOM_DATETIME_END_WIDGET = {
    "ui:widget": "datetime",
    "ui:placeholder": "2026-12-31T23:59:59Z",
}

# The single Fathom webhook event type ("New meeting content ready").
# triggered_for controls which recordings fire the webhook.
FATHOM_TRIGGERED_FOR = ["my_recordings"]


# ============================================================================
# Credential Schema
# ============================================================================


class FathomApiKeyCredential(BaseModel):
    """API Key credential for Fathom (sent as the X-Api-Key header)."""

    credential_type: Literal["fathom_api_key"] = Field(
        "fathom_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Fathom API key from Settings. Sent as the X-Api-Key header.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://fathom.video/settings"}
    )


class FathomBearerTokenCredential(BaseModel):
    """Manual bearer token credential for Fathom."""

    credential_type: Literal["fathom_bearer_token"] = Field(
        "fathom_bearer_token", json_schema_extra={"ui:hidden": True}
    )
    bearer_token: str = Field(
        ...,
        title="Bearer Token",
        description="A Fathom bearer token to send as Authorization: Bearer <token>.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developers.fathom.ai/sdks/authentication"
        }
    )


class FathomOAuthCredential(BaseModel):
    """OAuth credential for Fathom multi-user integrations."""

    credential_type: Literal["fathom_oauth"] = Field(
        "fathom_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth access token issued by Fathom."
    )
    refresh_token: Optional[str] = Field(
        None,
        title="Refresh Token",
        description="OAuth refresh token used to renew the access token.",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when the OAuth access token expires.",
    )
    scope: Optional[str] = Field(
        None, title="Scope", description="Granted OAuth scope string."
    )
    token_type: str = Field(
        "Bearer", title="Token Type", description="OAuth token type."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "fathom",
            "x-oauth-scopes": ["public_api"],
        }
    )


FathomCredential = Union[
    FathomOAuthCredential,
    FathomBearerTokenCredential,
    FathomApiKeyCredential,
]


# ============================================================================
# Operation Configs
# ============================================================================


class FathomListMeetingsConfig(BaseModel):
    """List meetings/recordings with optional filters and inline content includes."""

    operation: Literal["list_meetings"] = Field(
        "list_meetings",
        json_schema_extra={
            "const": "list_meetings",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "List Meetings",
        },
        title="List Meetings",
    )
    created_after: Optional[str] = Field(
        None,
        title="Created After",
        description="ISO 8601 lower bound on meeting creation time",
        json_schema_extra=FATHOM_DATETIME_WIDGET,
    )
    created_before: Optional[str] = Field(
        None,
        title="Created Before",
        description="ISO 8601 upper bound on meeting creation time",
        json_schema_extra=FATHOM_DATETIME_END_WIDGET,
    )
    meeting_type: Optional[str] = Field(
        None,
        title="Meeting Type",
        description="Filter to a single configured meeting type",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "meeting_type",
                "placeholder": "Select a meeting type...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a meeting type",
            }
        },
    )
    recorded_by: Optional[str] = Field(
        None, title="Recorded By", description="Filter by recorder email(s), comma-separated"
    )
    teams: Optional[str] = Field(
        None, title="Teams", description="Filter by team name(s), comma-separated"
    )
    calendar_invitees_domains: Optional[str] = Field(
        None,
        title="Invitee Domains",
        description="Filter by calendar invitee domain(s), comma-separated",
    )
    calendar_invitees_domains_type: Optional[str] = Field(
        None,
        title="Invitee Domain Type",
        description="Scope the invitee-domain filter",
        json_schema_extra={
            "enum": ["", "all", "only_internal", "one_or_more_external"],
            "enumNames": ["Any", "All", "Only internal", "One or more external"],
            "x-enum-searchable": True,
        },
    )
    include_summary: str = Field(
        "false",
        title="Include Summary",
        description="Include the AI summary inline (heavy / rate-limited)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_transcript: str = Field(
        "false",
        title="Include Transcript",
        description="Include the full transcript inline (heavy / rate-limited)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_action_items: str = Field(
        "false",
        title="Include Action Items",
        description="Include extracted action items inline",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_crm_matches: str = Field(
        "false",
        title="Include CRM Matches",
        description="Include matched CRM contacts/companies/deals inline",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_highlights: str = Field(
        "false",
        title="Include Highlights",
        description="Include meeting highlights inline",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomListMeetingsWithSummariesConfig(BaseModel):
    """List meetings with AI summaries inline (preset of list_meetings)."""

    operation: Literal["list_meetings_with_summaries"] = Field(
        "list_meetings_with_summaries",
        json_schema_extra={
            "const": "list_meetings_with_summaries",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "List Meetings With Summaries",
        },
        title="List Meetings With Summaries",
    )
    created_after: Optional[str] = Field(
        None,
        title="Created After",
        description="ISO 8601 lower bound on meeting creation time",
        json_schema_extra=FATHOM_DATETIME_WIDGET,
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomListMeetingsWithActionItemsConfig(BaseModel):
    """List meetings with extracted action items inline (preset of list_meetings)."""

    operation: Literal["list_meetings_with_action_items"] = Field(
        "list_meetings_with_action_items",
        json_schema_extra={
            "const": "list_meetings_with_action_items",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "List Meetings With Action Items",
        },
        title="List Meetings With Action Items",
    )
    created_after: Optional[str] = Field(
        None,
        title="Created After",
        description="ISO 8601 lower bound on meeting creation time",
        json_schema_extra=FATHOM_DATETIME_WIDGET,
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomListMeetingsWithCrmMatchesConfig(BaseModel):
    """List meetings with matched CRM contacts/companies/deals inline (preset)."""

    operation: Literal["list_meetings_with_crm_matches"] = Field(
        "list_meetings_with_crm_matches",
        json_schema_extra={
            "const": "list_meetings_with_crm_matches",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "List Meetings With CRM Matches",
        },
        title="List Meetings With CRM Matches",
    )
    created_after: Optional[str] = Field(
        None,
        title="Created After",
        description="ISO 8601 lower bound on meeting creation time",
        json_schema_extra=FATHOM_DATETIME_WIDGET,
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomListMeetingsByTypeConfig(BaseModel):
    """List only meetings of a given configured type (preset of list_meetings)."""

    operation: Literal["list_meetings_by_type"] = Field(
        "list_meetings_by_type",
        json_schema_extra={
            "const": "list_meetings_by_type",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "List Meetings By Type",
        },
        title="List Meetings By Type",
    )
    meeting_type: str = Field(
        ...,
        title="Meeting Type",
        description="The configured meeting type to filter by",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "meeting_type",
                "placeholder": "Select a meeting type...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a meeting type",
            }
        },
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomListExternalMeetingsConfig(BaseModel):
    """List meetings that had at least one external attendee (preset of list_meetings)."""

    operation: Literal["list_external_meetings"] = Field(
        "list_external_meetings",
        json_schema_extra={
            "const": "list_external_meetings",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "List External Meetings",
        },
        title="List External Meetings",
    )
    created_after: Optional[str] = Field(
        None,
        title="Created After",
        description="ISO 8601 lower bound on meeting creation time",
        json_schema_extra=FATHOM_DATETIME_WIDGET,
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomListMeetingTypesConfig(BaseModel):
    """List the configured meeting types used to categorize meetings."""

    operation: Literal["list_meeting_types"] = Field(
        "list_meeting_types",
        json_schema_extra={
            "const": "list_meeting_types",
            "ui:hidden": True,
            "x-category": "Meetings",
            "x-is-trigger": False,
            "x-display-name": "List Meeting Types",
        },
        title="List Meeting Types",
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomGetSummaryConfig(BaseModel):
    """Get the AI-generated summary for a recording."""

    operation: Literal["get_summary"] = Field(
        "get_summary",
        json_schema_extra={
            "const": "get_summary",
            "ui:hidden": True,
            "x-category": "Recordings",
            "x-is-trigger": False,
            "x-display-name": "Get Recording Summary",
        },
        title="Get Recording Summary",
    )
    recording_id: str = Field(
        ..., title="Recording ID", description="The recording's integer id"
    )
    destination_url: Optional[str] = Field(
        None,
        title="Destination URL",
        description="Optional callback URL to receive the summary asynchronously",
    )


class FathomGetTranscriptConfig(BaseModel):
    """Get the full speaker-attributed transcript for a recording."""

    operation: Literal["get_transcript"] = Field(
        "get_transcript",
        json_schema_extra={
            "const": "get_transcript",
            "ui:hidden": True,
            "x-category": "Recordings",
            "x-is-trigger": False,
            "x-display-name": "Get Recording Transcript",
        },
        title="Get Recording Transcript",
    )
    recording_id: str = Field(
        ..., title="Recording ID", description="The recording's integer id"
    )
    destination_url: Optional[str] = Field(
        None,
        title="Destination URL",
        description="Optional callback URL to receive the transcript asynchronously",
    )


class FathomListTeamsConfig(BaseModel):
    """List teams in the Fathom account."""

    operation: Literal["list_teams"] = Field(
        "list_teams",
        json_schema_extra={
            "const": "list_teams",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "List Teams",
        },
        title="List Teams",
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomListTeamMembersConfig(BaseModel):
    """List team members, optionally filtered to a single team."""

    operation: Literal["list_team_members"] = Field(
        "list_team_members",
        json_schema_extra={
            "const": "list_team_members",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "List Team Members",
        },
        title="List Team Members",
    )
    team: Optional[str] = Field(
        None,
        title="Team",
        description="Filter to members of a specific team",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "team",
                "placeholder": "Select a team...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a team name",
            }
        },
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor (next_cursor from a prior page)"
    )


class FathomCreateWebhookConfig(BaseModel):
    """Register a Fathom webhook that posts new-meeting content to a URL."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    destination_url: str = Field(
        ..., title="Destination URL", description="Where Fathom should POST new-meeting events"
    )
    triggered_for: Optional[str] = Field(
        "my_recordings",
        title="Triggered For",
        description="Which recordings fire the webhook",
        json_schema_extra={
            "enum": [
                "my_recordings",
                "shared_external_recordings",
                "my_shared_with_team_recordings",
                "shared_team_recordings",
            ],
            "enumNames": [
                "My recordings",
                "Shared external recordings",
                "My recordings shared with team",
                "Shared team recordings",
            ],
            "x-enum-searchable": True,
        },
    )
    include_transcript: str = Field(
        "false",
        title="Include Transcript",
        description="Include the transcript in the payload",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_summary: str = Field(
        "true",
        title="Include Summary",
        description="Include the AI summary in the payload",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_action_items: str = Field(
        "false",
        title="Include Action Items",
        description="Include action items in the payload",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_crm_matches: str = Field(
        "false",
        title="Include CRM Matches",
        description="Include CRM matches in the payload",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FathomDeleteWebhookConfig(BaseModel):
    """Delete a previously registered Fathom webhook by id."""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={
            "const": "delete_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
        },
        title="Delete Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The id of the webhook to delete"
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class FathomNewMeetingTriggerConfig(BaseModel):
    """Fire the workflow when a new meeting is processed (Fathom newMeeting webhook)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_new_meeting"] = Field(
        "on_new_meeting",
        json_schema_extra={
            "const": "on_new_meeting",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Meeting",
        },
        title="On New Meeting",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Fathom posts new-meeting events here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


FathomConfig = Annotated[
    Union[
        FathomListMeetingsConfig,
        FathomListMeetingsWithSummariesConfig,
        FathomListMeetingsWithActionItemsConfig,
        FathomListMeetingsWithCrmMatchesConfig,
        FathomListMeetingsByTypeConfig,
        FathomListExternalMeetingsConfig,
        FathomListMeetingTypesConfig,
        FathomGetSummaryConfig,
        FathomGetTranscriptConfig,
        FathomListTeamsConfig,
        FathomListTeamMembersConfig,
        FathomCreateWebhookConfig,
        FathomDeleteWebhookConfig,
        FathomNewMeetingTriggerConfig,
    ],
    Discriminator("operation"),
]


class FathomNodeConfig(NodeConfig[FathomConfig, FathomCredential]):
    """Full configuration for the Fathom node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _flag(value: Optional[str]) -> Optional[bool]:
    """Map the "true"/"false" string enum to a real bool, only when truthy.

    Returns True for "true", None otherwise so the param is dropped from the
    query string (Fathom treats absence as false).
    """
    return True if value == "true" else None


async def _fathom_request(
    credential: Dict[str, Any],
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Fathom request and return a structured result."""
    url = f"{FATHOM_API_BASE}{endpoint}"
    headers = _fathom_headers_from_credential(credential)
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        message = err.get("message") or err.get("error") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if not message or message in {"{}", "[]"}:
                    message = f"Fathom API returned HTTP {response.status_code}"
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[FathomNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
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
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[FathomNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class FathomNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Fathom meeting-notetaker automation node."""

    edit_examples = [
        "List my recent meetings with AI summaries",
        "Get the transcript for a specific recording",
        "List meetings that had at least one external attendee",
        "List meetings with action items to create tasks from",
        "Trigger a workflow whenever a new meeting is processed",
    ]

    scope_registry = FATHOM_SCOPES
    connection_evidence = ConnectionEvidence(
        field="team",
        noun="teams",
    )
    @classmethod
    def get_config_model(cls):
        return FathomNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (meeting types, teams)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not _fathom_has_auth(credential_data):
            return {"options": [], "next_page_token": None}

        if field_name == "meeting_type":
            result = await _fathom_request(
                credential_data, "GET", "/meeting_types", action_name="list_meeting_types"
            )
            items = _extract_items(result)
            options = []
            for it in items:
                if isinstance(it, dict):
                    name = it.get("name") or it.get("title") or it.get("id")
                    if name is not None:
                        options.append({"label": str(name), "value": str(name)})
                elif it is not None:
                    options.append({"label": str(it), "value": str(it)})
            return {"options": options, "next_page_token": None}

        if field_name == "team":
            result = await _fathom_request(
                credential_data, "GET", "/teams", action_name="list_teams"
            )
            items = _extract_items(result)
            options = []
            for it in items:
                if isinstance(it, dict):
                    name = it.get("name") or it.get("title") or it.get("id")
                    if name is not None:
                        options.append({"label": str(name), "value": str(name)})
                elif it is not None:
                    options.append({"label": str(it), "value": str(it)})
            return {"options": options, "next_page_token": None}

        return {"options": [], "next_page_token": None}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        if not _fathom_has_auth(credential):
            raise ValueError("A Fathom credential is required to register the trigger")
        result = await _fathom_request(
            credential,
            "POST",
            "/webhooks",
            json_body={
                "destination_url": webhook_url,
                "triggered_for": FATHOM_TRIGGERED_FOR,
                "include_summary": True,
                "include_action_items": True,
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Fathom webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        signing_secret = data.get("secret") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id is not None else None,
            "signing_secret": signing_secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        if not external_id or not _fathom_has_auth(credential):
            return
        await _fathom_request(
            credential, "DELETE", f"/webhooks/{external_id}", action_name="unregister_webhook"
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify a Svix-style Fathom webhook signature.

        Signature base is `{webhook-id}.{webhook-timestamp}.{body}`, HMAC-SHA256
        over a base64-decoded secret (the `whsec_` prefix is stripped). The
        webhook-signature header may carry several space-separated `v1,<sig>`
        entries; any match accepts.
        """
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        msg_id = headers.get("webhook-id")
        timestamp = headers.get("webhook-timestamp")
        sig_header = headers.get("webhook-signature")
        if not (msg_id and timestamp and sig_header):
            return False

        secret_key = secret
        if secret_key.startswith("whsec_"):
            secret_key = secret_key[len("whsec_"):]
        try:
            key_bytes = base64.b64decode(secret_key)
        except Exception:
            key_bytes = secret_key.encode()

        signed_content = f"{msg_id}.{timestamp}.".encode() + body
        expected = base64.b64encode(
            hmac.new(key_bytes, signed_content, hashlib.sha256).digest()
        ).decode()

        for part in sig_header.split():
            _, _, candidate = part.partition(",")
            if candidate and hmac.compare_digest(expected, candidate):
                return True
        return False

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, FathomNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, FathomNewMeetingTriggerConfig):
            return {
                "status": "success",
                "action": "on_new_meeting",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add a Fathom credential.")
        credential = await self._get_runtime_credential(credentials)

        handlers = {
            "list_meetings": self._list_meetings,
            "list_meetings_with_summaries": self._list_meetings_with_summaries,
            "list_meetings_with_action_items": self._list_meetings_with_action_items,
            "list_meetings_with_crm_matches": self._list_meetings_with_crm_matches,
            "list_meetings_by_type": self._list_meetings_by_type,
            "list_external_meetings": self._list_external_meetings,
            "list_meeting_types": self._list_meeting_types,
            "get_summary": self._get_summary,
            "get_transcript": self._get_transcript,
            "list_teams": self._list_teams,
            "list_team_members": self._list_team_members,
            "create_webhook": self._create_webhook,
            "delete_webhook": self._delete_webhook,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, credential)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _list_meetings(
        self, c: FathomListMeetingsConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        unsupported_inline_content = []
        if _fathom_uses_bearer_auth(credential):
            if c.include_summary == "true":
                unsupported_inline_content.append("summary")
            if c.include_transcript == "true":
                unsupported_inline_content.append("transcript")
        if unsupported_inline_content:
            return self._unsupported_meetings_inline_content_result(
                "list_meetings", unsupported_inline_content
            )
        params = {
            "created_after": c.created_after,
            "created_before": c.created_before,
            "meeting_type": c.meeting_type,
            "recorded_by[]": _comma_list(c.recorded_by),
            "teams[]": _comma_list(c.teams),
            "calendar_invitees_domains[]": _comma_list(c.calendar_invitees_domains),
            "calendar_invitees_domains_type": c.calendar_invitees_domains_type or None,
            "include_summary": _flag(c.include_summary),
            "include_transcript": _flag(c.include_transcript),
            "include_action_items": _flag(c.include_action_items),
            "include_crm_matches": _flag(c.include_crm_matches),
            "include_highlights": _flag(c.include_highlights),
            "cursor": c.cursor,
        }
        return await _fathom_request(
            credential, "GET", "/meetings", params=params, action_name="list_meetings"
        )

    async def _list_meetings_with_summaries(
        self, c: FathomListMeetingsWithSummariesConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        if _fathom_uses_bearer_auth(credential):
            return self._unsupported_meetings_inline_content_result(
                "list_meetings_with_summaries", ["summary"]
            )
        params = {"include_summary": True, "created_after": c.created_after, "cursor": c.cursor}
        return await _fathom_request(
            credential, "GET", "/meetings", params=params, action_name="list_meetings_with_summaries"
        )

    async def _list_meetings_with_action_items(
        self, c: FathomListMeetingsWithActionItemsConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = {"include_action_items": True, "created_after": c.created_after, "cursor": c.cursor}
        return await _fathom_request(
            credential,
            "GET",
            "/meetings",
            params=params,
            action_name="list_meetings_with_action_items",
        )

    async def _list_meetings_with_crm_matches(
        self, c: FathomListMeetingsWithCrmMatchesConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = {"include_crm_matches": True, "created_after": c.created_after, "cursor": c.cursor}
        return await _fathom_request(
            credential,
            "GET",
            "/meetings",
            params=params,
            action_name="list_meetings_with_crm_matches",
        )

    async def _list_meetings_by_type(
        self, c: FathomListMeetingsByTypeConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = {"meeting_type": c.meeting_type, "cursor": c.cursor}
        return await _fathom_request(
            credential, "GET", "/meetings", params=params, action_name="list_meetings_by_type"
        )

    async def _list_external_meetings(
        self, c: FathomListExternalMeetingsConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = {
            "calendar_invitees_domains_type": "one_or_more_external",
            "created_after": c.created_after,
            "cursor": c.cursor,
        }
        return await _fathom_request(
            credential, "GET", "/meetings", params=params, action_name="list_external_meetings"
        )

    async def _list_meeting_types(
        self, c: FathomListMeetingTypesConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await _fathom_request(
            credential, "GET", "/meeting_types", params={"cursor": c.cursor},
            action_name="list_meeting_types",
        )

    async def _get_summary(
        self, c: FathomGetSummaryConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await _fathom_request(
            credential,
            "GET",
            f"/recordings/{c.recording_id}/summary",
            params={"destination_url": c.destination_url},
            action_name="get_summary",
        )

    async def _get_transcript(
        self, c: FathomGetTranscriptConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await _fathom_request(
            credential,
            "GET",
            f"/recordings/{c.recording_id}/transcript",
            params={"destination_url": c.destination_url},
            action_name="get_transcript",
        )

    async def _list_teams(
        self, c: FathomListTeamsConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await _fathom_request(
            credential, "GET", "/teams", params={"cursor": c.cursor}, action_name="list_teams"
        )

    async def _list_team_members(
        self, c: FathomListTeamMembersConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = {"team": c.team, "cursor": c.cursor}
        return await _fathom_request(
            credential, "GET", "/team_members", params=params, action_name="list_team_members"
        )

    async def _create_webhook(
        self, c: FathomCreateWebhookConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        body = {
            "destination_url": c.destination_url,
            "triggered_for": [c.triggered_for] if c.triggered_for else None,
            "include_transcript": _flag(c.include_transcript),
            "include_summary": _flag(c.include_summary),
            "include_action_items": _flag(c.include_action_items),
            "include_crm_matches": _flag(c.include_crm_matches),
        }
        return await _fathom_request(
            credential, "POST", "/webhooks", json_body=body, action_name="create_webhook"
        )

    async def _delete_webhook(
        self, c: FathomDeleteWebhookConfig, credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await _fathom_request(
            credential, "DELETE", f"/webhooks/{c.webhook_id}", action_name="delete_webhook"
        )

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh expiring Fathom OAuth credentials during non-execute loads."""
        credential_data = credential_data or {}
        if not _fathom_is_oauth_credential(credential_data):
            return credential_data

        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.fathom_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="fathom",
        )

    async def _get_runtime_credential(
        self, credentials: FathomCredential
    ) -> Dict[str, Any]:
        if not isinstance(credentials, FathomOAuthCredential):
            return credentials.model_dump()

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.fathom_oauth import refresh_access_token
        
        credential_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=credential_dict,
            refresh=refresh_access_token,
            provider="fathom",
            caller_path="execute",
        )
        credentials.access_token = credential_dict["access_token"]
        credentials.expires_at = credential_dict["expires_at"]
        credentials.refresh_token = credential_dict.get("refresh_token")
        credentials.scope = credential_dict.get("scope")
        credentials.token_type = credential_dict.get("token_type") or "Bearer"
        return credential_dict

    def _unsupported_meetings_inline_content_result(
        self, action: str, features: List[str]
    ) -> Dict[str, Any]:
        joined = " and ".join(features)
        return {
            "status": "error",
            "action": action,
            "error": (
                f"Fathom does not support inline {joined} on /meetings for bearer or "
                "OAuth credentials. Use Get Recording Summary or Get Recording Transcript instead."
            ),
            "status_code": 400,
        }


def _extract_items(result: Dict[str, Any]) -> List[Any]:
    """Pull a list of items out of a Fathom list response envelope."""
    if result.get("status") != "success":
        return []
    data = result.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "results", "meeting_types", "teams"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return []


def _fathom_has_auth(credential: Optional[Dict[str, Any]]) -> bool:
    credential = credential or {}
    return bool(
        credential.get("api_key")
        or credential.get("bearer_token")
        or credential.get("access_token")
    )


def _fathom_is_oauth_credential(credential: Optional[Dict[str, Any]]) -> bool:
    credential = credential or {}
    credential_type = credential.get("credential_type")
    return credential_type == "fathom_oauth" or bool(
        credential.get("access_token") and credential.get("refresh_token")
    )


def _fathom_uses_bearer_auth(credential: Optional[Dict[str, Any]]) -> bool:
    credential = credential or {}
    return bool(credential.get("bearer_token") or credential.get("access_token"))


def _fathom_headers_from_credential(credential: Optional[Dict[str, Any]]) -> Dict[str, str]:
    credential = credential or {}
    if credential.get("api_key"):
        return {
            "X-Api-Key": credential["api_key"],
            "Content-Type": "application/json",
        }

    bearer_token = credential.get("bearer_token") or credential.get("access_token")
    if bearer_token:
        return {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

    raise ValueError("A Fathom API key or bearer token is required")
