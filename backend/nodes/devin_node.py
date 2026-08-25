"""
Devin AI software engineer automation node.

Provides workflow integration with the Devin REST API (v1) for operations including:
- Sessions: create, list, get, send message, update tags, terminate
- Attachments: upload
- Knowledge: list, create, update, delete
- Playbooks: list, get, create
- Secrets: list, create, delete
- Account: get self (v3)

Devin sessions are asynchronous and long-running. The canonical flow is
create a session -> poll "Get session" until it reaches a terminal state ->
optionally send follow-up messages -> read the (structured) output. Devin has
no outbound webhook/callback system, so this node is poll-based with no trigger.

Authentication: API Key (Bearer token). A legacy Service User API Key (apk_)
works against the v1 paths used here without an org_id in the URL. A current
cog_ Service User key also works for the included v3 "Get self" call.
API Base URL: https://api.devin.ai
Documentation: https://docs.devin.ai/api-reference/overview
"""

import json
import logging
import time
import uuid as uuid_module
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.schedule_registration import CronScheduleTriggerMixin
from nodes.core.poll_trigger import bounded_seen_ids
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)

logger = logging.getLogger(__name__)

# Session statuses that mean the run has reached a terminal state worth firing on.
DEVIN_TERMINAL_STATUSES = {"finished", "blocked", "expired"}

# Bound the persisted seen-key set so it can't grow without limit.
_DEVIN_MAX_SEEN_KEYS = 10000

DEVIN_API_BASE = "https://api.devin.ai"


# ============================================================================
# Credential Schema
# ============================================================================


class DevinApiKeyCredential(BaseModel):
    """API Key (Service User key) credential for Devin."""

    credential_type: Literal["devin_api_key"] = Field(
        "devin_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Devin Service User API key (starts with apk_ for v1 or cog_ for v3) from Settings -> Service users / API keys",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.devin.ai/settings/api-keys"}
    )


DevinCredential = DevinApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class DevinCreateSessionConfig(BaseModel):
    """Start a new Devin session from a task prompt."""

    operation: Literal["create_session"] = Field(
        "create_session",
        json_schema_extra={
            "const": "create_session",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Create Session",
            "x-creates-resource": True,
            "x-resource-type": "devin_session",
            "x-resource-id-path": "data.session_id",
        },
        title="Create Session",
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The task / instructions for Devin to work on",
        json_schema_extra={"ui:widget": "textarea"},
    )
    title: Optional[str] = Field(
        None, title="Title", description="Optional human-readable title for the session"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tags to attach to the session"
    )
    snapshot_id: Optional[str] = Field(
        None, title="Snapshot ID", description="Machine snapshot to start the session from"
    )
    playbook_id: Optional[str] = Field(
        None, title="Playbook ID", description="Playbook to run for this session"
    )
    knowledge_ids: Optional[str] = Field(
        None, title="Knowledge IDs", description="Comma-separated knowledge note IDs to attach"
    )
    secret_ids: Optional[str] = Field(
        None, title="Secret IDs", description="Comma-separated org secret IDs to expose to the session"
    )
    max_acu_limit: Optional[str] = Field(
        None, title="Max ACU Limit", description="Cap on Agent Compute Units this session may consume"
    )
    output_schema: Optional[str] = Field(
        None,
        title="Structured Output Schema",
        description="JSON Schema (Draft 7) the session's structured output must conform to",
        json_schema_extra={"ui:widget": "textarea"},
    )
    idempotent: str = Field(
        "false",
        title="Idempotent",
        description="De-duplicate retried creation requests",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    unlisted: str = Field(
        "false",
        title="Unlisted",
        description="Hide this session from the org session list",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class DevinListSessionsConfig(BaseModel):
    """List Devin sessions for the organization."""

    operation: Literal["list_sessions"] = Field(
        "list_sessions",
        json_schema_extra={
            "const": "list_sessions",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "List Sessions",
        },
        title="List Sessions",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of sessions to return"
    )
    offset: Optional[str] = Field(
        None, title="Offset", description="Number of sessions to skip (pagination)"
    )


class DevinGetSessionConfig(BaseModel):
    """Retrieve a session's status, output, structured output, and metadata."""

    operation: Literal["get_session"] = Field(
        "get_session",
        json_schema_extra={
            "const": "get_session",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Get Session",
        },
        title="Get Session",
    )
    session_id: str = Field(
        ...,
        title="Session ID",
        description="The session (devin) ID to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "session_id",
                "placeholder": "Select a session...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste session ID",
            },
            "x-resource-type": "devin_session",
        },
    )


class DevinSendMessageConfig(BaseModel):
    """Send a follow-up message to an active session (auto-resumes if suspended)."""

    operation: Literal["send_message"] = Field(
        "send_message",
        json_schema_extra={
            "const": "send_message",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Send Message",
        },
        title="Send Message",
    )
    session_id: str = Field(
        ...,
        title="Session ID",
        description="The session to send the message to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "session_id",
                "placeholder": "Select a session...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste session ID",
            },
            "x-resource-type": "devin_session",
        },
    )
    message: str = Field(
        ...,
        title="Message",
        description="The follow-up instruction / message",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DevinUpdateTagsConfig(BaseModel):
    """Replace the tags associated with a session (max 50)."""

    operation: Literal["update_tags"] = Field(
        "update_tags",
        json_schema_extra={
            "const": "update_tags",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Update Session Tags",
        },
        title="Update Session Tags",
    )
    session_id: str = Field(
        ...,
        title="Session ID",
        description="The session whose tags to replace",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "session_id",
                "placeholder": "Select a session...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste session ID",
            },
            "x-resource-type": "devin_session",
        },
    )
    tags: str = Field(
        ..., title="Tags", description="Comma-separated tags that replace the current set"
    )


class DevinTerminateSessionConfig(BaseModel):
    """Terminate an active session (cannot be resumed afterward)."""

    operation: Literal["terminate_session"] = Field(
        "terminate_session",
        json_schema_extra={
            "const": "terminate_session",
            "ui:hidden": True,
            "x-category": "Sessions",
            "x-is-trigger": False,
            "x-display-name": "Terminate Session",
        },
        title="Terminate Session",
    )
    session_id: str = Field(
        ...,
        title="Session ID",
        description="The session to terminate",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "session_id",
                "placeholder": "Select a session...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste session ID",
            },
            "x-resource-type": "devin_session",
        },
    )


class DevinUploadAttachmentConfig(BaseModel):
    """Upload a file for Devin to work with; returns a reference URL for a prompt."""

    operation: Literal["upload_attachment"] = Field(
        "upload_attachment",
        json_schema_extra={
            "const": "upload_attachment",
            "ui:hidden": True,
            "x-category": "Attachments",
            "x-is-trigger": False,
            "x-display-name": "Upload Attachment",
        },
        title="Upload Attachment",
    )
    file_name: str = Field(
        ..., title="File Name", description="Name to give the uploaded file (e.g. spec.txt)"
    )
    content: str = Field(
        ...,
        title="Content",
        description="Text content of the file to upload",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DevinListKnowledgeConfig(BaseModel):
    """List all knowledge notes and folders for the organization."""

    operation: Literal["list_knowledge"] = Field(
        "list_knowledge",
        json_schema_extra={
            "const": "list_knowledge",
            "ui:hidden": True,
            "x-category": "Knowledge",
            "x-is-trigger": False,
            "x-display-name": "List Knowledge",
        },
        title="List Knowledge",
    )


class DevinCreateKnowledgeConfig(BaseModel):
    """Create a new knowledge entry."""

    operation: Literal["create_knowledge"] = Field(
        "create_knowledge",
        json_schema_extra={
            "const": "create_knowledge",
            "ui:hidden": True,
            "x-category": "Knowledge",
            "x-is-trigger": False,
            "x-display-name": "Create Knowledge",
        },
        title="Create Knowledge",
    )
    name: str = Field(..., title="Name", description="Name of the knowledge entry")
    body: str = Field(
        ...,
        title="Body",
        description="The knowledge content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    trigger_description: str = Field(
        ...,
        title="Trigger Description",
        description="When this knowledge should be surfaced to Devin",
    )
    parent_folder_id: Optional[str] = Field(
        None, title="Parent Folder ID", description="Folder to place the knowledge entry in"
    )


class DevinUpdateKnowledgeConfig(BaseModel):
    """Update an existing knowledge entry."""

    operation: Literal["update_knowledge"] = Field(
        "update_knowledge",
        json_schema_extra={
            "const": "update_knowledge",
            "ui:hidden": True,
            "x-category": "Knowledge",
            "x-is-trigger": False,
            "x-display-name": "Update Knowledge",
        },
        title="Update Knowledge",
    )
    note_id: str = Field(..., title="Note ID", description="The knowledge entry to update")
    name: Optional[str] = Field(None, title="Name", description="New name for the entry")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="New knowledge content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    # Required by the API — cannot be omitted or null.
    trigger_description: str = Field(
        ..., title="Trigger Description", description="When Devin should apply this knowledge note"
    )


class DevinDeleteKnowledgeConfig(BaseModel):
    """Delete a knowledge entry."""

    operation: Literal["delete_knowledge"] = Field(
        "delete_knowledge",
        json_schema_extra={
            "const": "delete_knowledge",
            "ui:hidden": True,
            "x-category": "Knowledge",
            "x-is-trigger": False,
            "x-display-name": "Delete Knowledge",
        },
        title="Delete Knowledge",
    )
    note_id: str = Field(..., title="Note ID", description="The knowledge entry to delete")


class DevinListPlaybooksConfig(BaseModel):
    """List all playbooks accessible to the organization."""

    operation: Literal["list_playbooks"] = Field(
        "list_playbooks",
        json_schema_extra={
            "const": "list_playbooks",
            "ui:hidden": True,
            "x-category": "Playbooks",
            "x-is-trigger": False,
            "x-display-name": "List Playbooks",
        },
        title="List Playbooks",
    )


class DevinGetPlaybookConfig(BaseModel):
    """Retrieve a specific playbook's details."""

    operation: Literal["get_playbook"] = Field(
        "get_playbook",
        json_schema_extra={
            "const": "get_playbook",
            "ui:hidden": True,
            "x-category": "Playbooks",
            "x-is-trigger": False,
            "x-display-name": "Get Playbook",
        },
        title="Get Playbook",
    )
    playbook_id: str = Field(
        ...,
        title="Playbook ID",
        description="The playbook to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "playbook_id",
                "placeholder": "Select a playbook...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste playbook ID",
            },
            "x-resource-type": "devin_playbook",
        },
    )


class DevinCreatePlaybookConfig(BaseModel):
    """Create a new team playbook."""

    operation: Literal["create_playbook"] = Field(
        "create_playbook",
        json_schema_extra={
            "const": "create_playbook",
            "ui:hidden": True,
            "x-category": "Playbooks",
            "x-is-trigger": False,
            "x-display-name": "Create Playbook",
            "x-creates-resource": True,
            "x-resource-type": "devin_playbook",
            "x-resource-id-path": "data.id",
        },
        title="Create Playbook",
    )
    title: str = Field(..., title="Title", description="Title of the playbook")
    body: str = Field(
        ...,
        title="Body",
        description="The playbook instructions",
        json_schema_extra={"ui:widget": "textarea"},
    )


class DevinListSecretsConfig(BaseModel):
    """List metadata for all org secrets (values are never returned)."""

    operation: Literal["list_secrets"] = Field(
        "list_secrets",
        json_schema_extra={
            "const": "list_secrets",
            "ui:hidden": True,
            "x-category": "Secrets",
            "x-is-trigger": False,
            "x-display-name": "List Secrets",
        },
        title="List Secrets",
    )


class DevinCreateSecretConfig(BaseModel):
    """Create a new org secret for use in sessions."""

    operation: Literal["create_secret"] = Field(
        "create_secret",
        json_schema_extra={
            "const": "create_secret",
            "ui:hidden": True,
            "x-category": "Secrets",
            "x-is-trigger": False,
            "x-display-name": "Create Secret",
        },
        title="Create Secret",
    )
    key: str = Field(..., title="Key", description="The secret key / name")
    value: str = Field(
        ...,
        title="Value",
        description="The secret value",
        json_schema_extra={"ui:widget": "password"},
    )
    secret_type: str = Field(
        "key-value",
        title="Type",
        description="Secret type",
        json_schema_extra={
            "enum": ["cookie", "key-value", "totp"],
            "enumNames": ["Cookie", "Key-Value", "TOTP"],
            "x-enum-searchable": True,
        },
    )
    note: str = Field(
        "",
        title="Note",
        description="Human-readable description of what this secret is for",
    )
    sensitive: str = Field(
        "true",
        title="Sensitive",
        description="Whether to mask this secret's value in logs and UI",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes (masked)", "No (visible)"],
            "x-enum-searchable": True,
        },
    )


class DevinDeleteSecretConfig(BaseModel):
    """Permanently delete a secret by ID."""

    operation: Literal["delete_secret"] = Field(
        "delete_secret",
        json_schema_extra={
            "const": "delete_secret",
            "ui:hidden": True,
            "x-category": "Secrets",
            "x-is-trigger": False,
            "x-display-name": "Delete Secret",
        },
        title="Delete Secret",
    )
    secret_id: str = Field(..., title="Secret ID", description="The secret to delete")


class DevinGetSelfConfig(BaseModel):
    """Return information about the authenticated API key / principal (v3)."""

    operation: Literal["get_self"] = Field(
        "get_self",
        json_schema_extra={
            "const": "get_self",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Self",
        },
        title="Get Self",
    )


# ============================================================================
# Trigger Config (poll-based)
# ============================================================================


class DevinOnSessionFinishedConfig(BaseModel):
    """Poll-based trigger that fires when a Devin session newly reaches a
    terminal status (finished / blocked / expired / stopped).

    Devin has no outbound webhooks, so this provisions a webhook + cron schedule
    (the wake-up signal) and polls GET /v1/sessions on each tick, emitting only
    sessions whose (session_id, status) pair has not been seen before."""

    operation: Literal["on_session_finished"] = Field(
        "on_session_finished",
        json_schema_extra={
            "const": "on_session_finished",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Session Finished",
        },
        title="On Session Finished",
    )
    tags: Optional[str] = Field(
        None,
        title="Filter by Tags",
        description="Only fire for sessions carrying ALL of these comma-separated tags (optional)",
        json_schema_extra={"placeholder": "ci,release (optional)"},
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to poll Devin for finished sessions",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    max_results: int = Field(
        50,
        title="Max Sessions",
        description="Maximum number of sessions to scan per check (1-100)",
        ge=1,
        le=100,
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden internal fields for webhook/schedule management
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:hidden": True,
            "ui:loadValue": True,
            "ui:copyable": True,
        },
    )
    schedule_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    # Cursor: comma-joined "session_id:status" pairs already emitted, for dedupe.
    last_seen_ids: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    is_active: Optional[bool] = Field(
        default=True,
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


DevinConfig = Annotated[
    Union[
        DevinCreateSessionConfig,
        DevinListSessionsConfig,
        DevinGetSessionConfig,
        DevinSendMessageConfig,
        DevinUpdateTagsConfig,
        DevinTerminateSessionConfig,
        DevinUploadAttachmentConfig,
        DevinListKnowledgeConfig,
        DevinCreateKnowledgeConfig,
        DevinUpdateKnowledgeConfig,
        DevinDeleteKnowledgeConfig,
        DevinListPlaybooksConfig,
        DevinGetPlaybookConfig,
        DevinCreatePlaybookConfig,
        DevinListSecretsConfig,
        DevinCreateSecretConfig,
        DevinDeleteSecretConfig,
        DevinGetSelfConfig,
        DevinOnSessionFinishedConfig,
    ],
    Discriminator("operation"),
]


class DevinNodeConfig(NodeConfig[DevinConfig, DevinCredential]):
    """Full configuration for the Devin node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


async def _devin_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Devin request and return a structured result."""
    url = f"{DEVIN_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
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
                        message = err.get("error") or err.get("message") or err.get("detail") or str(err)
                        if isinstance(message, dict):
                            message = message.get("message") or str(message)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[DevinNode] API error ({action_name}): {message}")
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
            logger.error(f"[DevinNode] Request failed ({action_name}): {msg}")
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


class DevinNode(CronScheduleTriggerMixin, WorkflowNode):
    """Devin AI software engineer automation node."""

    schedule_trigger_operations = ("on_session_finished",)
    schedule_source = "devin_trigger"

    edit_examples = [
        "Create a Devin session to fix a failing test in the repo",
        "Poll a Devin session until it finishes and read its output",
        "Send a follow-up instruction to an active Devin session",
        "Create a knowledge note Devin should use for the project",
        "List all Devin sessions for the organization",
    ]

    @classmethod
    def get_config_model(cls):
        return DevinNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The Devin trigger is poll-based: the webhook fire is just a wake-up
        signal, not session data. Return None so execute() runs and polls the
        Devin API for newly-finished sessions."""
        if config.get("operation") == "on_session_finished":
            return None
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """A scheduled poll that found no newly-finished sessions → skip
        downstream. Dedup is the node-state seen-set, so emptiness is read off
        ``new_count``. See ``WorkflowNode`` for the seam."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_session_finished"
            and not output.get("new_count")
        )

    def trigger_emitted_event(self, output):
        """Fresh finished sessions emitted → executor stamps _pollFired so a
        wired agent receives them on any run source."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_session_finished"
            and bool(output.get("new_count"))
        )

    # load_field_value (webhook + schedule registration) is inherited from
    # CronScheduleTriggerMixin — it converges through reconcile_node.

    # ------------------------------------------------------------------
    # Dynamic options (sessions / playbooks)
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
        if field_name not in ("session_id", "playbook_id"):
            return {"options": []}
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return {"options": []}

        if field_name == "session_id":
            result = await _devin_request(
                api_key, "GET", "/v1/sessions", params={"limit": "100"}, action_name="list_sessions"
            )
            data = result.get("data") if result.get("status") == "success" else None
            sessions = _extract_list(data, ("sessions", "items"))
            options = []
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                sid = s.get("session_id") or s.get("devin_id") or s.get("id")
                title = s.get("title") or s.get("name") or s.get("status") or sid
                if sid is not None:
                    options.append({"label": str(title), "value": str(sid)})
            return {"options": options}

        result = await _devin_request(
            api_key, "GET", "/v1/playbooks", action_name="list_playbooks"
        )
        data = result.get("data") if result.get("status") == "success" else None
        playbooks = _extract_list(data, ("playbooks", "items"))
        options = []
        for p in playbooks:
            if not isinstance(p, dict):
                continue
            pid = p.get("playbook_id") or p.get("id")
            title = p.get("title") or p.get("name") or pid
            if pid is not None:
                options.append({"label": str(title), "value": str(pid)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, DevinNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Devin API key.")
        api_key = credentials.api_key

        handlers = {
            "create_session": self._create_session,
            "list_sessions": self._list_sessions,
            "get_session": self._get_session,
            "send_message": self._send_message,
            "update_tags": self._update_tags,
            "terminate_session": self._terminate_session,
            "upload_attachment": self._upload_attachment,
            "list_knowledge": self._list_knowledge,
            "create_knowledge": self._create_knowledge,
            "update_knowledge": self._update_knowledge,
            "delete_knowledge": self._delete_knowledge,
            "list_playbooks": self._list_playbooks,
            "get_playbook": self._get_playbook,
            "create_playbook": self._create_playbook,
            "list_secrets": self._list_secrets,
            "create_secret": self._create_secret,
            "delete_secret": self._delete_secret,
            "get_self": self._get_self,
            "on_session_finished": self._poll_finished_sessions,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Session handlers
    # ------------------------------------------------------------------
    async def _create_session(self, c: DevinCreateSessionConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "prompt": c.prompt,
            "title": c.title,
            "tags": _comma_list(c.tags),
            "snapshot_id": c.snapshot_id,
            "playbook_id": c.playbook_id,
            "knowledge_ids": _comma_list(c.knowledge_ids),
            "secret_ids": _comma_list(c.secret_ids),
            "max_acu_limit": int(c.max_acu_limit) if c.max_acu_limit and str(c.max_acu_limit).isdigit() else None,
            "idempotent": c.idempotent == "true",
            "unlisted": c.unlisted == "true",
        }
        if c.output_schema:
            try:
                body["structured_output_schema"] = json.loads(c.output_schema)
            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "action": "create_session",
                    "error": "Structured Output Schema is not valid JSON",
                    "status_code": 400,
                }
        return await _devin_request(
            api_key, "POST", "/v1/sessions", json_body=body, action_name="create_session"
        )

    async def _list_sessions(self, c: DevinListSessionsConfig, api_key: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "offset": c.offset}
        return await _devin_request(
            api_key, "GET", "/v1/sessions", params=params, action_name="list_sessions"
        )

    async def _get_session(self, c: DevinGetSessionConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "GET", f"/v1/sessions/{c.session_id}", action_name="get_session"
        )

    async def _send_message(self, c: DevinSendMessageConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key,
            "POST",
            f"/v1/sessions/{c.session_id}/message",
            json_body={"message": c.message},
            action_name="send_message",
        )

    async def _update_tags(self, c: DevinUpdateTagsConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key,
            "PUT",
            f"/v1/sessions/{c.session_id}/tags",
            json_body={"tags": _comma_list(c.tags) or []},
            action_name="update_tags",
        )

    async def _terminate_session(self, c: DevinTerminateSessionConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "DELETE", f"/v1/sessions/{c.session_id}", action_name="terminate_session"
        )

    async def _upload_attachment(self, c: DevinUploadAttachmentConfig, api_key: str) -> Dict[str, Any]:
        """Upload a file (multipart) and return the reference URL to use in a prompt."""
        url = f"{DEVIN_API_BASE}/v1/attachments"
        headers = {"Authorization": f"Bearer {api_key}"}
        start = time.time()
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    "POST",
                    url,
                    headers=headers,
                    files={"file": (c.file_name, c.content.encode("utf-8"))},
                )
                api_ms = round((time.time() - start) * 1000, 2)
                if response.status_code >= 400:
                    try:
                        err = response.json()
                        message = (err.get("error") or err.get("message") or str(err)) if isinstance(err, dict) else str(err)
                    except Exception:
                        message = response.text
                    return {
                        "status": "error",
                        "action": "upload_attachment",
                        "error": message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
                try:
                    raw = response.json()
                    # Devin returns the URL as a plain JSON string; normalize to dict.
                    data = raw if isinstance(raw, dict) else {"url": raw}
                except Exception:
                    data = {"url": response.text}
                return {
                    "status": "success",
                    "action": "upload_attachment",
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            except Exception as e:
                msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[DevinNode] Attachment upload failed: {msg}")
                return {
                    "status": "error",
                    "action": "upload_attachment",
                    "error": msg,
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
                }

    # ------------------------------------------------------------------
    # Knowledge handlers
    # ------------------------------------------------------------------
    async def _list_knowledge(self, c: DevinListKnowledgeConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "GET", "/v1/knowledge", action_name="list_knowledge"
        )

    async def _create_knowledge(self, c: DevinCreateKnowledgeConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "body": c.body,
            "trigger_description": c.trigger_description,
            "parent_folder_id": c.parent_folder_id,
        }
        return await _devin_request(
            api_key, "POST", "/v1/knowledge", json_body=body, action_name="create_knowledge"
        )

    async def _update_knowledge(self, c: DevinUpdateKnowledgeConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "body": c.body,
            "trigger_description": c.trigger_description,
        }
        return await _devin_request(
            api_key, "PUT", f"/v1/knowledge/{c.note_id}", json_body=body, action_name="update_knowledge"
        )

    async def _delete_knowledge(self, c: DevinDeleteKnowledgeConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "DELETE", f"/v1/knowledge/{c.note_id}", action_name="delete_knowledge"
        )

    # ------------------------------------------------------------------
    # Playbook handlers
    # ------------------------------------------------------------------
    async def _list_playbooks(self, c: DevinListPlaybooksConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "GET", "/v1/playbooks", action_name="list_playbooks"
        )

    async def _get_playbook(self, c: DevinGetPlaybookConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "GET", f"/v1/playbooks/{c.playbook_id}", action_name="get_playbook"
        )

    async def _create_playbook(self, c: DevinCreatePlaybookConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key,
            "POST",
            "/v1/playbooks",
            json_body={"title": c.title, "body": c.body},
            action_name="create_playbook",
        )

    # ------------------------------------------------------------------
    # Secret handlers
    # ------------------------------------------------------------------
    async def _list_secrets(self, c: DevinListSecretsConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "GET", "/v1/secrets", action_name="list_secrets"
        )

    async def _create_secret(self, c: DevinCreateSecretConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key,
            "POST",
            "/v1/secrets",
            json_body={"key": c.key, "value": c.value, "type": c.secret_type, "sensitive": c.sensitive == "true", "note": c.note},
            action_name="create_secret",
        )

    async def _delete_secret(self, c: DevinDeleteSecretConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "DELETE", f"/v1/secrets/{c.secret_id}", action_name="delete_secret"
        )

    # ------------------------------------------------------------------
    # Account handler
    # ------------------------------------------------------------------
    async def _get_self(self, c: DevinGetSelfConfig, api_key: str) -> Dict[str, Any]:
        return await _devin_request(
            api_key, "GET", "/v3/self", action_name="get_self"
        )

    # ------------------------------------------------------------------
    # Trigger handler (poll-based)
    # ------------------------------------------------------------------
    async def _poll_finished_sessions(
        self, c: DevinOnSessionFinishedConfig, api_key: str
    ) -> Dict[str, Any]:
        """Poll GET /v1/sessions and emit sessions that newly reached a terminal
        status. Dedup cursor is the set of "session_id:status" pairs already seen
        (stored in c.last_seen_ids), so re-running on the same finished session
        does not re-fire."""
        result = await _devin_request(
            api_key,
            "GET",
            "/v1/sessions",
            params={"limit": str(c.max_results)},
            action_name="on_session_finished",
        )
        if result.get("status") != "success":
            # Surface the API error directly; nothing fired.
            return result

        sessions = _extract_list(result.get("data"), ("sessions", "items"))
        wanted_tags = set(_comma_list(c.tags) or [])

        # Terminal-session keys visible in this poll ("session_id:status").
        # Computed BEFORE the state read so the mutator stays pure (re-runnable
        # on CAS retry). Order preserved, deduped.
        by_key: Dict[str, Dict[str, Any]] = {}
        for s in sessions:
            if not isinstance(s, dict):
                continue
            sid = s.get("session_id") or s.get("devin_id") or s.get("id")
            status = str(s.get("status") or s.get("status_enum") or "").lower()
            if sid is None or status not in DEVIN_TERMINAL_STATUSES:
                continue
            if wanted_tags:
                s_tags = set(s.get("tags") or [])
                if not wanted_tags.issubset(s_tags):
                    continue
            by_key.setdefault(f"{sid}:{status}", s)
        current_keys = list(by_key.keys())

        def mutator(state):
            # The dedup set lives in NODE STATE — config isn't persisted across
            # poll runs, so a config-held set stayed empty and the trigger
            # re-fired every finished session on every tick. The first poll
            # baselines: it records the currently-finished sessions and emits
            # nothing, so enabling the trigger doesn't fire the whole backlog.
            seen_keys = state.get("seen_session_keys", [])
            is_first_poll = "seen_session_keys" not in state
            seen = set(seen_keys)
            if is_first_poll:
                baseline = bounded_seen_ids([], current_keys, _DEVIN_MAX_SEEN_KEYS)
                return {"seen_session_keys": baseline}, ([], baseline)
            fresh = [by_key[k] for k in current_keys if k not in seen]
            if not fresh:
                return None, ([], seen_keys)
            all_seen = bounded_seen_ids(seen_keys, current_keys, _DEVIN_MAX_SEEN_KEYS)
            return {"seen_session_keys": all_seen}, (fresh, all_seen)

        # seen_snapshot backs the (back-compat) last_seen_ids output field.
        new_items, seen_snapshot = await self._update_node_state(
            mutator, skip_result=([], [])
        )

        return {
            "status": "success",
            "operation": "on_session_finished",
            "action": "on_session_finished",
            "new_count": len(new_items),
            "items": new_items,
            "last_seen_ids": ",".join(seen_snapshot),
            "timestamp": time.time(),
        }


def _extract_list(data: Any, keys: tuple) -> List[Any]:
    """Devin list endpoints may return a bare list or wrap it under a known key."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return data[k]
    return []
