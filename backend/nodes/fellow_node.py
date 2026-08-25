"""
Fellow (fellow.ai) AI meeting assistant automation node.

Provides workflow integration with the Fellow Developer REST API (v1) for
operations including:
- Profile: get authenticated user / workspace info
- Recordings: list, retrieve, delete
- Notes: list, retrieve, delete
- Action Items: list, retrieve, mark complete, archive
- Webhooks: list, create, retrieve, update, delete
- Webhook Trigger: fire when an AI note is generated / shared, or an action
  item is assigned / completed

Authentication: API Key passed in the `X-API-KEY` header (per-user Developer
API key). Every request targets the workspace's own subdomain, so the
credential captures the workspace subdomain.

API Base URL: https://{subdomain}.fellow.app/api/v1
Documentation: https://developers.fellow.ai/reference/introduction

Notes:
- Fellow's list endpoints are POST (filters + cursor pagination go in the body),
  while single-resource reads are GET.
- `media_url` on recordings, DELETE /note and DELETE /recording require a
  privileged ("Super Admin") key (Enterprise plan only).
"""

import base64
import hashlib
import hmac
import json as _json
import logging
import time
from typing import ClassVar, Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from utils.ssrf import normalize_provider_subdomain

logger = logging.getLogger(__name__)

# Events the trigger subscribes to (all subscribable Fellow webhook events).
FELLOW_TRIGGER_EVENTS = [
    "ai_note.generated",
    "ai_note.shared_to_channel",
    "action_item.assigned",
    "action_item.completed",
]


# ============================================================================
# Credential Schema
# ============================================================================


class FellowAPIKeyCredential(BaseModel):
    """API Key credential for Fellow (fellow.ai)."""

    credential_type: Literal["fellow_api_key"] = Field(
        "fellow_api_key", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ...,
        title="Workspace Subdomain",
        description=(
            'Your Fellow workspace subdomain — the "acme" in '
            "https://acme.fellow.app. You can also paste the full URL; "
            "the subdomain is extracted automatically."
        ),
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description=(
            "Your Fellow Developer API key from User Settings → API & MCP Connections → + New API Key. "
            "Sent in the X-API-KEY header."
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://help.fellow.ai/en/articles/11817206-developer-api"
        }
    )


FellowCredential = FellowAPIKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class FellowGetMeConfig(BaseModel):
    """Retrieve the authenticated user and workspace info (validates the key)."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get My Profile",
        },
        title="Get My Profile",
    )


class FellowListRecordingsConfig(BaseModel):
    """List meeting recordings with optional filters and cursor pagination."""

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
    event_guid: Optional[str] = Field(
        None, title="Event GUID", description="Filter to recordings for this calendar event"
    )
    channel_id: Optional[str] = Field(
        None, title="Channel ID", description="Filter to recordings in this channel"
    )
    title: Optional[str] = Field(
        None, title="Title", description="Filter by recording title (substring match)"
    )
    include_transcript: str = Field(
        "false",
        title="Include Transcript",
        description="Include transcript segments in each recording",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_ai_notes: str = Field(
        "false",
        title="Include AI Notes",
        description="Include AI-generated notes in each recording",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor from a previous response (leave blank for first page)"
    )
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Results per page (1-50, default 20)"
    )


class FellowGetRecordingConfig(BaseModel):
    """Retrieve one recording, including transcript segments."""

    operation: Literal["get_recording"] = Field(
        "get_recording",
        json_schema_extra={
            "const": "get_recording",
            "ui:hidden": True,
            "x-category": "Recordings",
            "x-is-trigger": False,
            "x-display-name": "Retrieve Recording",
        },
        title="Retrieve Recording",
    )
    recording_id: str = Field(
        ..., title="Recording ID", description="The ID of the recording to retrieve"
    )


class FellowDeleteRecordingConfig(BaseModel):
    """Permanently delete a recording. Requires a Super Admin (privileged) key."""

    operation: Literal["delete_recording"] = Field(
        "delete_recording",
        json_schema_extra={
            "const": "delete_recording",
            "ui:hidden": True,
            "x-category": "Recordings",
            "x-is-trigger": False,
            "x-display-name": "Delete Recording",
        },
        title="Delete Recording",
    )
    recording_id: str = Field(
        ..., title="Recording ID", description="The ID of the recording to delete (Super Admin key required)"
    )


class FellowListNotesConfig(BaseModel):
    """List meeting notes with optional filters and cursor pagination."""

    operation: Literal["list_notes"] = Field(
        "list_notes",
        json_schema_extra={
            "const": "list_notes",
            "ui:hidden": True,
            "x-category": "Notes",
            "x-is-trigger": False,
            "x-display-name": "List Notes",
        },
        title="List Notes",
    )
    event_guid: Optional[str] = Field(
        None, title="Event GUID", description="Filter to notes for this calendar event"
    )
    channel_id: Optional[str] = Field(
        None, title="Channel ID", description="Filter to notes in this channel"
    )
    title: Optional[str] = Field(
        None, title="Title", description="Filter by note title (substring match)"
    )
    include_attendees: str = Field(
        "false",
        title="Include Attendees",
        description="Include event attendees in each note",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    include_content_markdown: str = Field(
        "false",
        title="Include Content (Markdown)",
        description="Include the note content as markdown",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor from a previous response (leave blank for first page)"
    )
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Results per page (1-50, default 20)"
    )


class FellowGetNoteConfig(BaseModel):
    """Retrieve a single note by ID (structured / AI note content)."""

    operation: Literal["get_note"] = Field(
        "get_note",
        json_schema_extra={
            "const": "get_note",
            "ui:hidden": True,
            "x-category": "Notes",
            "x-is-trigger": False,
            "x-display-name": "Retrieve Note",
        },
        title="Retrieve Note",
    )
    note_id: str = Field(..., title="Note ID", description="The ID of the note to retrieve")


class FellowDeleteNoteConfig(BaseModel):
    """Permanently delete a note. Requires a Super Admin (privileged) key."""

    operation: Literal["delete_note"] = Field(
        "delete_note",
        json_schema_extra={
            "const": "delete_note",
            "ui:hidden": True,
            "x-category": "Notes",
            "x-is-trigger": False,
            "x-display-name": "Delete Note",
        },
        title="Delete Note",
    )
    note_id: str = Field(
        ..., title="Note ID", description="The ID of the note to delete (Super Admin key required)"
    )


class FellowListActionItemsConfig(BaseModel):
    """List action items with optional scope filter and cursor pagination."""

    operation: Literal["list_action_items"] = Field(
        "list_action_items",
        json_schema_extra={
            "const": "list_action_items",
            "ui:hidden": True,
            "x-category": "Action Items",
            "x-is-trigger": False,
            "x-display-name": "List Action Items",
        },
        title="List Action Items",
    )
    scope: Optional[str] = Field(
        None,
        title="Scope",
        description="Which action items to return",
        json_schema_extra={
            "enum": ["", "assigned_to_me", "assigned_to_others"],
            "enumNames": ["All accessible", "Assigned to me", "Assigned to others"],
            "x-enum-searchable": True,
        },
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor from a previous response (leave blank for first page)"
    )
    page_size: Optional[str] = Field(
        "20", title="Page Size", description="Results per page (1-50, default 20)"
    )


class FellowGetActionItemConfig(BaseModel):
    """Retrieve a single action item by ID."""

    operation: Literal["get_action_item"] = Field(
        "get_action_item",
        json_schema_extra={
            "const": "get_action_item",
            "ui:hidden": True,
            "x-category": "Action Items",
            "x-is-trigger": False,
            "x-display-name": "Retrieve Action Item",
        },
        title="Retrieve Action Item",
    )
    action_item_id: str = Field(
        ..., title="Action Item ID", description="The ID of the action item to retrieve"
    )


class FellowCompleteActionItemConfig(BaseModel):
    """Toggle an action item's completion state."""

    operation: Literal["complete_action_item"] = Field(
        "complete_action_item",
        json_schema_extra={
            "const": "complete_action_item",
            "ui:hidden": True,
            "x-category": "Action Items",
            "x-is-trigger": False,
            "x-display-name": "Mark Action Item Complete",
        },
        title="Mark Action Item Complete",
    )
    action_item_id: str = Field(
        ..., title="Action Item ID", description="The ID of the action item to update"
    )
    completed: str = Field(
        "true",
        title="Completed",
        description="Mark the action item complete (Yes) or incomplete (No)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class FellowArchiveActionItemConfig(BaseModel):
    """Archive an action item by marking it 'won't do'."""

    operation: Literal["archive_action_item"] = Field(
        "archive_action_item",
        json_schema_extra={
            "const": "archive_action_item",
            "ui:hidden": True,
            "x-category": "Action Items",
            "x-is-trigger": False,
            "x-display-name": "Archive Action Item",
        },
        title="Archive Action Item",
    )
    action_item_id: str = Field(
        ..., title="Action Item ID", description="The ID of the action item to archive"
    )


class FellowListWebhooksConfig(BaseModel):
    """List webhook subscriptions."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "const": "list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )


class FellowCreateWebhookConfig(BaseModel):
    """Create a webhook subscription that receives HTTP POST on subscribed events."""

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
    url: str = Field(..., title="Subscriber URL", description="HTTPS URL that receives event POSTs")
    events: str = Field(
        ...,
        title="Events",
        description=(
            "Comma-separated events to subscribe to: ai_note.generated, "
            "ai_note.shared_to_channel, action_item.assigned, action_item.completed"
        ),
    )


class FellowGetWebhookConfig(BaseModel):
    """Retrieve a single webhook subscription by ID."""

    operation: Literal["get_webhook"] = Field(
        "get_webhook",
        json_schema_extra={
            "const": "get_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Retrieve Webhook",
        },
        title="Retrieve Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook subscription to retrieve"
    )


class FellowUpdateWebhookConfig(BaseModel):
    """Partial update of a webhook subscription (only provided fields change)."""

    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={
            "const": "update_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Update Webhook",
        },
        title="Update Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook subscription to update"
    )
    url: Optional[str] = Field(
        None, title="Subscriber URL", description="New HTTPS URL that receives event POSTs"
    )
    events: Optional[str] = Field(
        None, title="Events", description="New comma-separated list of subscribed events"
    )


class FellowDeleteWebhookConfig(BaseModel):
    """Delete a webhook subscription by ID."""

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
        ..., title="Webhook ID", description="The ID of the webhook subscription to delete"
    )


# ============================================================================
# Webhook Trigger Configs
# ============================================================================


def _fellow_trigger_field(value: str, display: str, keywords: Optional[list] = None) -> Any:
    """Build the `operation` field for a Fellow trigger config."""
    extra: Dict[str, Any] = {
        "const": value,
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(default=value, json_schema_extra=extra, title=display)


class _FellowTriggerBase(BaseModel):
    """Shared hidden plumbing fields for all Fellow webhook trigger operations."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Fellow posts events here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class FellowOnAINoteGeneratedConfig(_FellowTriggerBase):
    """Fire when Fellow generates an AI note for a meeting."""

    operation: Literal["on_ai_note_generated"] = _fellow_trigger_field(
        "on_ai_note_generated",
        "On AI Note Generated",
        ["ai note", "meeting notes", "summary generated", "note created"],
    )


class FellowOnAINoteSharedConfig(_FellowTriggerBase):
    """Fire when a Fellow AI note is shared to a channel (e.g. Slack, Teams)."""

    operation: Literal["on_ai_note_shared"] = _fellow_trigger_field(
        "on_ai_note_shared",
        "On AI Note Shared",
        ["note shared", "share to channel", "slack share", "teams share"],
    )


class FellowOnActionItemAssignedConfig(_FellowTriggerBase):
    """Fire when a Fellow action item is assigned to someone."""

    operation: Literal["on_action_item_assigned"] = _fellow_trigger_field(
        "on_action_item_assigned",
        "On Action Item Assigned",
        ["action item assigned", "task assigned", "todo assigned"],
    )


class FellowOnActionItemCompletedConfig(_FellowTriggerBase):
    """Fire when a Fellow action item is marked complete."""

    operation: Literal["on_action_item_completed"] = _fellow_trigger_field(
        "on_action_item_completed",
        "On Action Item Completed",
        ["action item completed", "task done", "todo completed", "action item resolved"],
    )


class FellowEventTriggerConfig(_FellowTriggerBase):
    """Fire on any Fellow AI-note or action-item event (catch-all, backward-compat)."""

    operation: Literal["on_fellow_event"] = _fellow_trigger_field(
        "on_fellow_event",
        "On Fellow Event (Any)",
        ["any fellow event", "all events"],
    )


# ============================================================================
# Discriminated Union
# ============================================================================


FellowConfig = Annotated[
    Union[
        FellowGetMeConfig,
        FellowListRecordingsConfig,
        FellowGetRecordingConfig,
        FellowDeleteRecordingConfig,
        FellowListNotesConfig,
        FellowGetNoteConfig,
        FellowDeleteNoteConfig,
        FellowListActionItemsConfig,
        FellowGetActionItemConfig,
        FellowCompleteActionItemConfig,
        FellowArchiveActionItemConfig,
        FellowListWebhooksConfig,
        FellowCreateWebhookConfig,
        FellowGetWebhookConfig,
        FellowUpdateWebhookConfig,
        FellowDeleteWebhookConfig,
        # Decomposed triggers (specific events)
        FellowOnAINoteGeneratedConfig,
        FellowOnAINoteSharedConfig,
        FellowOnActionItemAssignedConfig,
        FellowOnActionItemCompletedConfig,
        # Catch-all trigger (backward compat)
        FellowEventTriggerConfig,
    ],
    Discriminator("operation"),
]


class FellowNodeConfig(NodeConfig[FellowConfig, FellowCredential]):
    """Full configuration for the Fellow node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================



def _comma_list(value: Optional[str]) -> Optional[list]:
    """Convert a user-entered comma-separated string to a list, or None if empty."""
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _pagination(cursor: Optional[str], page_size: Optional[str]) -> Dict[str, Any]:
    """Build Fellow's pagination object for list (POST) endpoints."""
    size = 20
    if page_size:
        try:
            size = max(1, min(50, int(page_size)))
        except ValueError:
            size = 20
    return {"cursor": cursor or None, "page_size": size}


def _normalize_subdomain(subdomain: str) -> str:
    """Extract just the subdomain slug from whatever the user pasted.

    Handles:
      - "acme"                              → "acme"
      - "https://acme.fellow.app"           → "acme"
      - "https://acme.fellow.app/"          → "acme"
      - "https://acme.fellow.app/anything"  → "acme"
    """
    return normalize_provider_subdomain(
        subdomain, "fellow.app", field_name="Fellow workspace subdomain"
    )


def _base_url(subdomain: str) -> str:
    return f"https://{_normalize_subdomain(subdomain)}.fellow.app/api/v1"


async def _fellow_request(
    subdomain: str,
    api_key: str,
    method: str,
    endpoint: str,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Fellow v1 request and return a structured result."""
    url = f"{_base_url(subdomain)}{endpoint}"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        message = err.get("message") or err.get("error") or err.get("detail") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[FellowNode] API error ({action_name}): {message}")
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
            logger.error(f"[FellowNode] Request failed ({action_name}): {msg}")
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


_FELLOW_TRIGGER_TYPES = (
    FellowOnAINoteGeneratedConfig,
    FellowOnAINoteSharedConfig,
    FellowOnActionItemAssignedConfig,
    FellowOnActionItemCompletedConfig,
    FellowEventTriggerConfig,
)


class FellowNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Fellow (fellow.ai) AI meeting assistant automation node."""

    edit_examples = [
        "List the latest meeting recordings with transcripts",
        "Retrieve the AI notes for a meeting",
        "List my open action items",
        "Mark an action item complete",
        "Trigger a workflow when a new AI note is generated",
        "Trigger a workflow when an action item is assigned to me",
    ]

    # Maps each trigger operation to the Fellow event type(s) it subscribes to.
    _trigger_event_map: ClassVar[Dict[str, list]] = {
        "on_ai_note_generated":    ["ai_note.generated"],
        "on_ai_note_shared":       ["ai_note.shared_to_channel"],
        "on_action_item_assigned": ["action_item.assigned"],
        "on_action_item_completed":["action_item.completed"],
        "on_fellow_event":         FELLOW_TRIGGER_EVENTS,  # catch-all
    }

    @classmethod
    def get_config_model(cls):
        return FellowNodeConfig

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        subdomain = credential.get("subdomain")
        api_key = credential.get("api_key")
        if not subdomain or not api_key:
            raise ValueError("A Fellow workspace subdomain and API key are required to register the trigger")
        operation = (config or {}).get("operation", "on_fellow_event")
        event_types = cls._trigger_event_map.get(operation) or FELLOW_TRIGGER_EVENTS
        result = await _fellow_request(
            subdomain,
            api_key,
            "POST",
            "/webhook",
            json_body={
                "url": webhook_url,
                # Fellow (via Svix) uses "enabled_events", not "events"
                "enabled_events": event_types,
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Fellow webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        external_id = data.get("id")
        # Fellow returns the signing secret (whsec_...) once in the create response
        signing_secret = data.get("secret")
        if not external_id or not signing_secret:
            raise ValueError(
                f"Fellow webhook registration returned incomplete data "
                f"(id={external_id!r}, secret_present={bool(signing_secret)})"
            )
        return {
            "external_webhook_id": str(external_id),
            "signing_secret": signing_secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        subdomain = (credential or {}).get("subdomain")
        api_key = (credential or {}).get("api_key")
        if not external_id or not subdomain or not api_key:
            return
        await _fellow_request(
            subdomain,
            api_key,
            "DELETE",
            f"/webhook/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def handle_webhook_handshake(
        cls, body: bytes, headers: Dict[str, str],
        config: Optional[Dict[str, Any]] = None,
    ):
        """Respond to Fellow's (Svix) URL verification challenge."""
        try:
            payload = _json.loads(body)
        except Exception:
            return None
        if isinstance(payload, dict) and payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        return None

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)

        # Fellow uses Svix. Headers: svix-id, svix-timestamp, svix-signature.
        svix_id = headers.get("svix-id")
        svix_timestamp = headers.get("svix-timestamp")
        svix_signature = headers.get("svix-signature")
        if not svix_id or not svix_timestamp or not svix_signature:
            return False

        # Reject replayed events older than 5 minutes (matches Svix SDK default).
        try:
            if abs(time.time() - int(svix_timestamp)) > 300:
                return False
        except (ValueError, TypeError):
            return False

        # whsec_ is base64-encoded; strip the "whsec_" prefix before decoding.
        try:
            secret_bytes = base64.b64decode(secret.replace("whsec_", ""))
        except Exception:
            return False

        # Svix signed content = "{svix-id}.{svix-timestamp}.{raw body}"
        signed_content = f"{svix_id}.{svix_timestamp}.".encode() + body
        expected = base64.b64encode(
            hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
        ).decode()

        # svix-signature may be a space-separated list of "v1,<base64>" signatures.
        for sig_part in svix_signature.split():
            if sig_part.startswith("v1,") and hmac.compare_digest(expected, sig_part[3:]):
                return True
        return False

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, FellowNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, _FELLOW_TRIGGER_TYPES):
            return {
                "status": "success",
                "action": op.operation,
                "event_types": self._trigger_event_map.get(op.operation, []),
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Fellow API key and workspace subdomain.")
        subdomain = credentials.subdomain
        api_key = credentials.api_key

        handlers = {
            "get_me": self._get_me,
            "list_recordings": self._list_recordings,
            "get_recording": self._get_recording,
            "delete_recording": self._delete_recording,
            "list_notes": self._list_notes,
            "get_note": self._get_note,
            "delete_note": self._delete_note,
            "list_action_items": self._list_action_items,
            "get_action_item": self._get_action_item,
            "complete_action_item": self._complete_action_item,
            "archive_action_item": self._archive_action_item,
            "list_webhooks": self._list_webhooks,
            "create_webhook": self._create_webhook,
            "get_webhook": self._get_webhook,
            "update_webhook": self._update_webhook,
            "delete_webhook": self._delete_webhook,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, subdomain, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _get_me(self, c: FellowGetMeConfig, subdomain: str, api_key: str) -> Dict[str, Any]:
        return await _fellow_request(subdomain, api_key, "GET", "/me", action_name="get_me")

    async def _list_recordings(
        self, c: FellowListRecordingsConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        # Fellow's include field is a dict of booleans, not a list.
        include: Dict[str, bool] = {}
        if c.include_transcript == "true":
            include["transcript"] = True
        if c.include_ai_notes == "true":
            include["ai_notes"] = True
        body: Dict[str, Any] = {
            "event_guid": c.event_guid,
            "channel_id": c.channel_id,
            "title": c.title,
            "include": include or None,
            "pagination": _pagination(c.cursor, c.page_size),
        }
        return await _fellow_request(
            subdomain, api_key, "POST", "/recordings", json_body=body, action_name="list_recordings"
        )

    async def _get_recording(
        self, c: FellowGetRecordingConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "GET", f"/recording/{c.recording_id}", action_name="get_recording"
        )

    async def _delete_recording(
        self, c: FellowDeleteRecordingConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "DELETE", f"/recording/{c.recording_id}", action_name="delete_recording"
        )

    async def _list_notes(
        self, c: FellowListNotesConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        # Fellow's include field is a dict of booleans, not a list.
        include: Dict[str, bool] = {}
        if c.include_attendees == "true":
            include["event_attendees"] = True
        if c.include_content_markdown == "true":
            include["content_markdown"] = True
        body: Dict[str, Any] = {
            "event_guid": c.event_guid,
            "channel_id": c.channel_id,
            "title": c.title,
            "include": include or None,
            "pagination": _pagination(c.cursor, c.page_size),
        }
        return await _fellow_request(
            subdomain, api_key, "POST", "/notes", json_body=body, action_name="list_notes"
        )

    async def _get_note(self, c: FellowGetNoteConfig, subdomain: str, api_key: str) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "GET", f"/note/{c.note_id}", action_name="get_note"
        )

    async def _delete_note(
        self, c: FellowDeleteNoteConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "DELETE", f"/note/{c.note_id}", action_name="delete_note"
        )

    async def _list_action_items(
        self, c: FellowListActionItemsConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "scope": c.scope or None,
            "pagination": _pagination(c.cursor, c.page_size),
        }
        return await _fellow_request(
            subdomain, api_key, "POST", "/action_items", json_body=body, action_name="list_action_items"
        )

    async def _get_action_item(
        self, c: FellowGetActionItemConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "GET", f"/action_item/{c.action_item_id}", action_name="get_action_item"
        )

    async def _complete_action_item(
        self, c: FellowCompleteActionItemConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain,
            api_key,
            "POST",
            f"/action_item/{c.action_item_id}/complete",
            json_body={"completed": c.completed == "true"},
            action_name="complete_action_item",
        )

    async def _archive_action_item(
        self, c: FellowArchiveActionItemConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain,
            api_key,
            "POST",
            f"/action_item/{c.action_item_id}/archive",
            action_name="archive_action_item",
        )

    async def _list_webhooks(
        self, c: FellowListWebhooksConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "GET", "/webhooks", action_name="list_webhooks"
        )

    async def _create_webhook(
        self, c: FellowCreateWebhookConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain,
            api_key,
            "POST",
            "/webhook",
            json_body={"url": c.url, "enabled_events": _comma_list(c.events)},
            action_name="create_webhook",
        )

    async def _get_webhook(
        self, c: FellowGetWebhookConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "GET", f"/webhook/{c.webhook_id}", action_name="get_webhook"
        )

    async def _update_webhook(
        self, c: FellowUpdateWebhookConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "url": c.url,
            "enabled_events": _comma_list(c.events),
        }
        return await _fellow_request(
            subdomain, api_key, "PATCH", f"/webhook/{c.webhook_id}", json_body=body, action_name="update_webhook"
        )

    async def _delete_webhook(
        self, c: FellowDeleteWebhookConfig, subdomain: str, api_key: str
    ) -> Dict[str, Any]:
        return await _fellow_request(
            subdomain, api_key, "DELETE", f"/webhook/{c.webhook_id}", action_name="delete_webhook"
        )
