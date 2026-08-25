"""
Attio CRM automation node.

Provides workflow integration with Attio (v2 REST API) for operations including:
- Records: list/query, get, create, update, upsert, delete, full-text search
- Schema: list objects, list attributes, list lists
- List entries: query, create, update, delete
- Notes: list, create, delete
- Tasks: list, create, update, delete
- Comments: create
- Workspace: list members, identify self (token introspection)
- Webhooks: create, list, delete (used by the trigger registration)
- Webhook Trigger: fire when a record / list-entry / note / task event arrives

Authentication: API Key (single-workspace access token, Bearer)
API Base URL: https://api.attio.com (all endpoints under /v2)
Documentation: https://docs.attio.com/rest-api/overview
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, model_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.crm_records import ATTIO_SCOPES

logger = logging.getLogger(__name__)

ATTIO_API_BASE = "https://api.attio.com"

# Event types the webhook trigger can subscribe to (Attio V2 names), paired with
# human labels for the config dropdown. Order matters: it drives the enum order.
ATTIO_TRIGGER_EVENT_LABELS: List[tuple[str, str]] = [
    ("record.created", "Record created"),
    ("record.updated", "Record updated"),
    ("record.deleted", "Record deleted"),
    ("record.merged", "Record merged"),
    ("list-entry.created", "List entry created"),
    ("list-entry.updated", "List entry updated"),
    ("list-entry.deleted", "List entry deleted"),
    ("note.created", "Note created"),
    ("note.updated", "Note updated"),
    ("note.deleted", "Note deleted"),
    ("note-content.updated", "Note content updated"),
    ("task.created", "Task created"),
    ("task.updated", "Task updated"),
    ("task.deleted", "Task deleted"),
    ("comment.created", "Comment created"),
    ("comment.deleted", "Comment deleted"),
    ("comment.resolved", "Comment resolved"),
    ("comment.unresolved", "Comment unresolved"),
    ("list.created", "List created"),
    ("list.updated", "List updated"),
    ("list.deleted", "List deleted"),
    ("object-attribute.created", "Object attribute created"),
    ("object-attribute.updated", "Object attribute updated"),
    ("list-attribute.created", "List attribute created"),
    ("list-attribute.updated", "List attribute updated"),
    ("call-recording.created", "Call recording created"),
    ("workspace-member.created", "Workspace member created"),
]

# All subscribable event type names (the "*" / All events selection subscribes
# to every one of these).
ATTIO_TRIGGER_EVENTS = [name for name, _label in ATTIO_TRIGGER_EVENT_LABELS]

_ATTIO_EVENT_LABEL = {name: label for name, label in ATTIO_TRIGGER_EVENT_LABELS}

# Enum + labels for the event_types config field: a leading "All events" option
# plus every individual event type.
_ATTIO_EVENT_ENUM = ["*"] + ATTIO_TRIGGER_EVENTS
_ATTIO_EVENT_ENUM_NAMES = ["All events"] + [
    label for _name, label in ATTIO_TRIGGER_EVENT_LABELS
]

# The single trigger is decomposed into per-resource-category triggers so each
# shows up as a focused, discoverable operation ("On Record Event", "On Note
# Event", ...). Each still exposes an event_types selector scoped to its own
# category. ``on_attio_event`` remains a catch-all over every event (and is the
# only path to the less-common schema/admin events).
ATTIO_TRIGGER_CATEGORY_EVENTS: Dict[str, List[str]] = {
    "on_record_event": ["record.created", "record.updated", "record.deleted", "record.merged"],
    "on_list_entry_event": ["list-entry.created", "list-entry.updated", "list-entry.deleted"],
    "on_note_event": ["note.created", "note.updated", "note.deleted", "note-content.updated"],
    "on_task_event": ["task.created", "task.updated", "task.deleted"],
    "on_comment_event": ["comment.created", "comment.deleted", "comment.resolved", "comment.unresolved"],
    "on_attio_event": ATTIO_TRIGGER_EVENTS,
}

# All operation strings that identify a webhook trigger.
ATTIO_TRIGGER_OPERATIONS = tuple(ATTIO_TRIGGER_CATEGORY_EVENTS.keys())


def _event_enum_for(events: List[str]) -> tuple[List[str], List[str]]:
    """Build (enum, enumNames) for a category's event_types field, with a
    leading 'All events in this category' (\"*\") option."""
    return ["*"] + events, ["All events in this category"] + [
        _ATTIO_EVENT_LABEL.get(e, e) for e in events
    ]


def _selected_attio_events(config: Dict[str, Any]) -> List[str]:
    """Resolve the configured event_types into a concrete list of event names,
    scoped to the trigger operation's category.

    Accepts a comma-separated string or list. Empty / "*" / unknown values fall
    back to every event type allowed for that operation's category.
    """
    operation = (config or {}).get("operation", "on_attio_event")
    allowed = ATTIO_TRIGGER_CATEGORY_EVENTS.get(operation, ATTIO_TRIGGER_EVENTS)
    raw = (config or {}).get("event_types")
    if isinstance(raw, str):
        chosen = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        chosen = [str(part).strip() for part in raw if str(part).strip()]
    else:
        chosen = []
    if not chosen or "*" in chosen:
        return list(allowed)
    valid = [e for e in chosen if e in allowed]
    return valid or list(allowed)


def _delivered_event_types(payload: Dict[str, Any]) -> List[str]:
    """Extract event_type(s) from a delivered webhook payload.

    Attio batches events into ``{"webhook_id": ..., "events": [{event_type, id,
    actor}, ...]}`` (verified against live deliveries). A bare single-event shape
    is also tolerated defensively.
    """
    events = (payload or {}).get("events")
    if isinstance(events, list):
        delivered = [e.get("event_type") for e in events if isinstance(e, dict)]
    else:
        delivered = [(payload or {}).get("event_type")]
    return [e for e in delivered if e]


# ============================================================================
# Credential Schema
# ============================================================================


class AttioOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Attio.

    Tokens are obtained via the OAuth flow, not entered manually. Attio tokens are
    long-lived (non-expiring in the classic authorization-code flow).

    Register an OAuth app at: https://app.attio.com/_workos/settings/developers
    """

    credential_type: Literal["attio_oauth"] = Field(
        "attio_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="Workspace Name")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "attio",
        "x-oauth-scopes": [
            "user_management:read",
            "record_permission:read-write",
            "object_configuration:read-write",
            "list_entry:read-write",
            "list_configuration:read-write",
            "comment:read-write",
            "note:read-write",
            "task:read-write",
            "meeting:read",
            "call_recording:read",
            # Required for the trigger node's webhook registration.
            "webhook:read-write",
            "file:read",
        ],
    })


class AttioAPIKeyCredential(BaseModel):
    """API Key (single-workspace access token) credential for Attio."""

    credential_type: Literal["attio_api_key"] = Field(
        "attio_api_key", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Attio access token from Workspace settings -> Developers -> Access tokens. Passed as a Bearer token.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.attio.com/_workos/settings/developers"}
    )


# Union — OAuth shown first in UI (best UX), API key as the alternative.
AttioCredential = Union[AttioOAuthCredential, AttioAPIKeyCredential]


# ============================================================================
# Record Operation Configs
# ============================================================================


def _parse_json(value: Optional[str]) -> Optional[Any]:
    """Parse an optional JSON string field. Raises ValueError on bad JSON."""
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")


def _op_meta(op: str, category: str, display: str) -> Dict[str, Any]:
    return {
        "const": op, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": display,
    }


class AttioListRecordsConfig(BaseModel):
    """List/query records of an object with filtering, sorting, and pagination."""

    operation: Literal["list_records"] = Field(
        "list_records",
        json_schema_extra={
            "const": "list_records",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "List Records",
        },
        title="List Records",
    )
    object: str = Field(
        ...,
        title="Object",
        description="Object slug or ID (e.g. people, companies, deals, or a custom object)",
        json_schema_extra={
            "x-resource-type": "attio_object",
            "x-dynamic-options": {
                "field_name": "object",
                "placeholder": "Select an object...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an object slug",
            }
        },
    )
    filter_json: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description='Attio filter object as JSON, e.g. {"name": {"$contains": "Acme"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    sorts_json: Optional[str] = Field(
        None,
        title="Sorts (JSON)",
        description='Array of sort objects as JSON, e.g. [{"attribute": "name", "direction": "asc"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of records to return (1-1000)"
    )
    offset: Optional[str] = Field(
        "0", title="Offset", description="Number of records to skip for pagination"
    )


class AttioGetRecordConfig(BaseModel):
    """Fetch a single record by ID."""

    operation: Literal["get_record"] = Field(
        "get_record",
        json_schema_extra={
            "const": "get_record",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Get Record",
        },
        title="Get Record",
    )
    object: str = Field(
        ...,
        title="Object",
        description="Object slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_object",
            "x-dynamic-options": {
                "field_name": "object",
                "placeholder": "Select an object...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an object slug",
            }
        },
    )
    record_id: str = Field(..., title="Record ID", description="The record_id (UUID) to fetch")


class AttioCreateRecordConfig(BaseModel):
    """Create a record on any object."""

    operation: Literal["create_record"] = Field(
        "create_record",
        json_schema_extra={
            "const": "create_record",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Create Record",
        },
        title="Create Record",
    )
    object: str = Field(
        ...,
        title="Object",
        description="Object slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_object",
            "x-dynamic-options": {
                "field_name": "object",
                "placeholder": "Select an object...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an object slug",
            }
        },
    )
    values_json: str = Field(
        ...,
        title="Attribute Values (JSON)",
        description='Map of attribute slug -> value as JSON, e.g. {"name": "Acme", "domains": ["acme.com"]}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioUpdateRecordConfig(BaseModel):
    """Update a record (PATCH appends to multiselect attributes)."""

    operation: Literal["update_record"] = Field(
        "update_record",
        json_schema_extra={
            "const": "update_record",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Update Record",
        },
        title="Update Record",
    )
    object: str = Field(
        ...,
        title="Object",
        description="Object slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_object",
            "x-dynamic-options": {
                "field_name": "object",
                "placeholder": "Select an object...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an object slug",
            }
        },
    )
    record_id: str = Field(..., title="Record ID", description="The record_id (UUID) to update")
    values_json: str = Field(
        ...,
        title="Attribute Values (JSON)",
        description='Map of attribute slug -> value as JSON. PATCH appends to multiselect attributes.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioUpsertRecordConfig(BaseModel):
    """Create-or-update a record by a matching attribute (dedupe)."""

    operation: Literal["upsert_record"] = Field(
        "upsert_record",
        json_schema_extra={
            "const": "upsert_record",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Upsert Record",
        },
        title="Upsert Record",
    )
    object: str = Field(
        ...,
        title="Object",
        description="Object slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_object",
            "x-dynamic-options": {
                "field_name": "object",
                "placeholder": "Select an object...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an object slug",
            }
        },
    )
    matching_attribute: str = Field(
        ...,
        title="Matching Attribute",
        description="Slug of a unique attribute used to match an existing record (e.g. email_addresses, domains)",
    )
    values_json: str = Field(
        ...,
        title="Attribute Values (JSON)",
        description='Map of attribute slug -> value as JSON.',
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioDeleteRecordConfig(BaseModel):
    """Delete a record by ID."""

    operation: Literal["delete_record"] = Field(
        "delete_record",
        json_schema_extra={
            "const": "delete_record",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Delete Record",
        },
        title="Delete Record",
    )
    object: str = Field(
        ...,
        title="Object",
        description="Object slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_object",
            "x-dynamic-options": {
                "field_name": "object",
                "placeholder": "Select an object...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an object slug",
            }
        },
    )
    record_id: str = Field(..., title="Record ID", description="The record_id (UUID) to delete")


class AttioSearchRecordsConfig(BaseModel):
    """Search records of an object by matching text against an attribute.

    Attio has no global full-text endpoint; search is a filtered query against a
    single object's records/query endpoint using a ``$contains`` match.
    """

    operation: Literal["search_records"] = Field(
        "search_records",
        json_schema_extra={
            "const": "search_records",
            "ui:hidden": True,
            "x-category": "Records",
            "x-is-trigger": False,
            "x-display-name": "Search Records",
            "x-keywords": "find lookup full text search records by name",
        },
        title="Search Records",
    )
    object: str = Field(
        ...,
        title="Object",
        description="Object slug or ID to search within (e.g. people, companies)",
        json_schema_extra={
            "x-resource-type": "attio_object",
            "x-dynamic-options": {
                "field_name": "object",
                "placeholder": "Select an object...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste an object slug",
            }
        },
    )
    query: str = Field(..., title="Query", description="Text to match against the search attribute")
    attribute: Optional[str] = Field(
        "name",
        title="Search Attribute",
        description="Attribute slug to match the query against (default: name)",
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of results to return"
    )


# ============================================================================
# Schema Operation Configs
# ============================================================================


class AttioListObjectsConfig(BaseModel):
    """List all objects (standard + custom) in the workspace."""

    operation: Literal["list_objects"] = Field(
        "list_objects",
        json_schema_extra={
            "const": "list_objects",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "List Objects",
        },
        title="List Objects",
    )


class AttioListAttributesConfig(BaseModel):
    """List attributes defined on an object or list."""

    operation: Literal["list_attributes"] = Field(
        "list_attributes",
        json_schema_extra={
            "const": "list_attributes",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "List Attributes",
        },
        title="List Attributes",
    )
    target: str = Field(
        "objects",
        title="Target",
        description="Whether the identifier refers to an object or a list",
        json_schema_extra={
            "enum": ["objects", "lists"],
            "enumNames": ["Object", "List"],
            "x-enum-searchable": True,
        },
    )
    identifier: str = Field(
        ...,
        title="Identifier",
        description="Object/list slug or ID to list attributes for (e.g. people, companies)",
    )


class AttioListListsConfig(BaseModel):
    """List all lists in the workspace."""

    operation: Literal["list_lists"] = Field(
        "list_lists",
        json_schema_extra={
            "const": "list_lists",
            "ui:hidden": True,
            "x-category": "Schema",
            "x-is-trigger": False,
            "x-display-name": "List All Lists",
        },
        title="List All Lists",
    )


# ============================================================================
# List Entry Operation Configs
# ============================================================================


class AttioListEntriesConfig(BaseModel):
    """Query entries in a list with filters, sorting, and pagination."""

    operation: Literal["list_entries"] = Field(
        "list_entries",
        json_schema_extra={
            "const": "list_entries",
            "ui:hidden": True,
            "x-category": "List Entries",
            "x-is-trigger": False,
            "x-display-name": "List Entries",
        },
        title="List Entries",
    )
    list: str = Field(
        ...,
        title="List",
        description="List slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_list",
            "x-dynamic-options": {
                "field_name": "list",
                "placeholder": "Select a list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list slug",
            }
        },
    )
    filter_json: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description="Attio filter object as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )
    sorts_json: Optional[str] = Field(
        None,
        title="Sorts (JSON)",
        description="Array of sort objects as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of entries to return"
    )
    offset: Optional[str] = Field(
        "0", title="Offset", description="Number of entries to skip for pagination"
    )


class AttioCreateListEntryConfig(BaseModel):
    """Add a record to a list (create an entry)."""

    operation: Literal["create_list_entry"] = Field(
        "create_list_entry",
        json_schema_extra={
            "const": "create_list_entry",
            "ui:hidden": True,
            "x-category": "List Entries",
            "x-is-trigger": False,
            "x-display-name": "Create List Entry",
        },
        title="Create List Entry",
    )
    list: str = Field(
        ...,
        title="List",
        description="List slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_list",
            "x-dynamic-options": {
                "field_name": "list",
                "placeholder": "Select a list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list slug",
            }
        },
    )
    parent_record_id: str = Field(
        ..., title="Record ID", description="The record_id (UUID) to add to the list"
    )
    parent_object: str = Field(
        ...,
        title="Parent Object",
        description="The object slug of the parent record (e.g. companies, people)",
    )
    entry_values_json: Optional[str] = Field(
        None,
        title="Entry Values (JSON)",
        description="Map of list-specific attribute slug -> value as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioUpdateListEntryConfig(BaseModel):
    """Update a list entry's attribute values."""

    operation: Literal["update_list_entry"] = Field(
        "update_list_entry",
        json_schema_extra={
            "const": "update_list_entry",
            "ui:hidden": True,
            "x-category": "List Entries",
            "x-is-trigger": False,
            "x-display-name": "Update List Entry",
        },
        title="Update List Entry",
    )
    list: str = Field(
        ...,
        title="List",
        description="List slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_list",
            "x-dynamic-options": {
                "field_name": "list",
                "placeholder": "Select a list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list slug",
            }
        },
    )
    entry_id: str = Field(..., title="Entry ID", description="The entry_id (UUID) to update")
    entry_values_json: str = Field(
        ...,
        title="Entry Values (JSON)",
        description="Map of attribute slug -> value as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioDeleteListEntryConfig(BaseModel):
    """Remove an entry from a list."""

    operation: Literal["delete_list_entry"] = Field(
        "delete_list_entry",
        json_schema_extra={
            "const": "delete_list_entry",
            "ui:hidden": True,
            "x-category": "List Entries",
            "x-is-trigger": False,
            "x-display-name": "Delete List Entry",
        },
        title="Delete List Entry",
    )
    list: str = Field(
        ...,
        title="List",
        description="List slug or ID",
        json_schema_extra={
            "x-resource-type": "attio_list",
            "x-dynamic-options": {
                "field_name": "list",
                "placeholder": "Select a list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a list slug",
            }
        },
    )
    entry_id: str = Field(..., title="Entry ID", description="The entry_id (UUID) to delete")


# ============================================================================
# Note Operation Configs
# ============================================================================


class AttioListNotesConfig(BaseModel):
    """List notes, optionally filtered by parent record/object."""

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
    parent_object: Optional[str] = Field(
        None, title="Parent Object", description="Filter to notes on this object slug (optional)"
    )
    parent_record_id: Optional[str] = Field(
        None, title="Parent Record ID", description="Filter to notes on this record (optional)"
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of notes to return"
    )


class AttioCreateNoteConfig(BaseModel):
    """Create a note attached to a record."""

    operation: Literal["create_note"] = Field(
        "create_note",
        json_schema_extra={
            "const": "create_note",
            "ui:hidden": True,
            "x-category": "Notes",
            "x-is-trigger": False,
            "x-display-name": "Create Note",
        },
        title="Create Note",
    )
    parent_object: str = Field(
        ..., title="Parent Object", description="Object slug the note is attached to (e.g. companies)"
    )
    parent_record_id: str = Field(
        ..., title="Parent Record ID", description="The record_id (UUID) the note is attached to"
    )
    title: str = Field(..., title="Title", description="Note title")
    content: str = Field(
        ...,
        title="Content",
        description="Note body content (plaintext)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioDeleteNoteConfig(BaseModel):
    """Delete a note by ID."""

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
    note_id: str = Field(..., title="Note ID", description="The note_id (UUID) to delete")


# ============================================================================
# Task Operation Configs
# ============================================================================


class AttioListTasksConfig(BaseModel):
    """List tasks in the workspace."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks",
        json_schema_extra={
            "const": "list_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Tasks",
        },
        title="List Tasks",
    )
    limit: Optional[str] = Field(
        "50", title="Limit", description="Max number of tasks to return"
    )


class AttioCreateTaskConfig(BaseModel):
    """Create a task with content, deadline, assignees, and linked records."""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "const": "create_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Task",
        },
        title="Create Task",
    )
    content: str = Field(
        ...,
        title="Content",
        description="Task description (plaintext)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    deadline_at: Optional[str] = Field(
        None, title="Deadline", description="Task deadline as ISO 8601 datetime"
    )
    is_completed: str = Field(
        "false",
        title="Completed",
        description="Whether the task starts completed",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    assignees_json: Optional[str] = Field(
        None,
        title="Assignees (JSON)",
        description='Array of assignee refs as JSON, e.g. [{"referenced_actor_type": "workspace-member", "referenced_actor_id": "..."}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    linked_records_json: Optional[str] = Field(
        None,
        title="Linked Records (JSON)",
        description='Array of record refs as JSON, e.g. [{"target_object": "companies", "target_record_id": "..."}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioUpdateTaskConfig(BaseModel):
    """Update a task (e.g. mark complete, change deadline)."""

    operation: Literal["update_task"] = Field(
        "update_task",
        json_schema_extra={
            "const": "update_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Update Task",
        },
        title="Update Task",
    )
    task_id: str = Field(..., title="Task ID", description="The task_id (UUID) to update")
    is_completed: Optional[str] = Field(
        None,
        title="Completed",
        description="Mark the task complete or incomplete",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    deadline_at: Optional[str] = Field(
        None, title="Deadline", description="New deadline as ISO 8601 datetime"
    )
    assignees_json: Optional[str] = Field(
        None,
        title="Assignees (JSON)",
        description="Array of assignee refs as JSON",
        json_schema_extra={"ui:widget": "textarea"},
    )


class AttioDeleteTaskConfig(BaseModel):
    """Delete a task by ID."""

    operation: Literal["delete_task"] = Field(
        "delete_task",
        json_schema_extra={
            "const": "delete_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Delete Task",
        },
        title="Delete Task",
    )
    task_id: str = Field(..., title="Task ID", description="The task_id (UUID) to delete")


# ============================================================================
# Comment / Workspace / Self Operation Configs
# ============================================================================


def _comment_content_field() -> Any:
    return Field(..., title="Content", description="Comment body (plaintext)",
                 json_schema_extra={"ui:widget": "textarea", "ui:placeholder": "Write your comment..."})


def _comment_author_field() -> Any:
    return Field(
        None, title="Author (Workspace Member ID)",
        description="Workspace member the comment is authored by. Defaults to the token owner.",
        json_schema_extra={"ui:placeholder": "Defaults to the token owner"},
    )


class AttioCreateCommentConfig(BaseModel):
    """Create a comment on a record (starts a new thread on that record)."""

    operation: Literal["create_comment"] = Field(
        "create_comment", json_schema_extra=_op_meta("create_comment", "Comments", "Comment on Record"),
        title="Comment on Record",
    )
    content: str = _comment_content_field()
    record_object: str = Field(
        ..., title="Record Object", description="Object slug/ID the comment is posted on",
        json_schema_extra={
            "x-resource-type": "attio_object", "x-dynamic-options": {"field_name": "object", "placeholder": "Select an object...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste an object slug"},
        },
    )
    record_id: str = Field(..., title="Record ID", description="record_id (UUID) to comment on", json_schema_extra={"ui:placeholder": "e.g. 6003a6aa-7122-45f1-b840-efe9231dfd06"})
    author_workspace_member_id: Optional[str] = _comment_author_field()


class AttioCreateEntryCommentConfig(BaseModel):
    """Create a comment on a list entry (starts a new thread on that entry)."""

    operation: Literal["create_entry_comment"] = Field(
        "create_entry_comment", json_schema_extra=_op_meta("create_entry_comment", "Comments", "Comment on List Entry"),
        title="Comment on List Entry",
    )
    content: str = _comment_content_field()
    entry_list: str = Field(
        ..., title="List", description="List slug/ID the entry belongs to",
        json_schema_extra={
            "x-resource-type": "attio_list", "x-dynamic-options": {"field_name": "list", "placeholder": "Select a list...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste a list slug"},
        },
    )
    entry_id: str = Field(..., title="Entry ID", description="entry_id (UUID) to comment on", json_schema_extra={"ui:placeholder": "e.g. 861c1071-54ba-4d3d-b642-f72f7bcc8c7e"})
    author_workspace_member_id: Optional[str] = _comment_author_field()


class AttioReplyToThreadConfig(BaseModel):
    """Reply to an existing comment thread."""

    operation: Literal["reply_to_thread"] = Field(
        "reply_to_thread", json_schema_extra=_op_meta("reply_to_thread", "Comments", "Reply to Thread"),
        title="Reply to Thread",
    )
    content: str = _comment_content_field()
    thread_id: str = Field(..., title="Thread ID", description="The thread_id (UUID) to reply to", json_schema_extra={"ui:placeholder": "e.g. 016e88d9-de10-4e1c-9aef-36b07cb4260d"})
    author_workspace_member_id: Optional[str] = _comment_author_field()


class AttioListWorkspaceMembersConfig(BaseModel):
    """List workspace members (for assignment / actor lookup)."""

    operation: Literal["list_workspace_members"] = Field(
        "list_workspace_members",
        json_schema_extra={
            "const": "list_workspace_members",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "List Workspace Members",
        },
        title="List Workspace Members",
    )


class AttioIdentifySelfConfig(BaseModel):
    """Introspect the current token: workspace + granted permissions."""

    operation: Literal["identify_self"] = Field(
        "identify_self",
        json_schema_extra={
            "const": "identify_self",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Identify Self",
        },
        title="Identify Self",
    )


class AttioGetWorkspaceMemberConfig(BaseModel):
    """Fetch a single workspace member by ID."""

    operation: Literal["get_workspace_member"] = Field(
        "get_workspace_member",
        json_schema_extra={
            "const": "get_workspace_member", "ui:hidden": True, "x-category": "Workspace",
            "x-is-trigger": False, "x-display-name": "Get Workspace Member",
        },
        title="Get Workspace Member",
    )
    workspace_member_id: str = Field(..., title="Workspace Member ID", description="The workspace_member_id (UUID)")


# ============================================================================
# Object schema management (create/get/update objects, attributes, options, statuses)
# ============================================================================


def _target_field() -> Any:
    return Field(
        "objects", title="Target",
        description="Whether the identifier refers to an object or a list",
        json_schema_extra={"enum": ["objects", "lists"], "enumNames": ["Object", "List"], "x-enum-searchable": True},
    )


class AttioGetObjectConfig(BaseModel):
    """Fetch a single object definition by slug or ID."""

    operation: Literal["get_object"] = Field("get_object", json_schema_extra=_op_meta("get_object", "Objects", "Get Object"), title="Get Object")
    object: str = Field(..., title="Object", description="Object slug or ID")


class AttioCreateObjectConfig(BaseModel):
    """Create a new custom object."""

    operation: Literal["create_object"] = Field("create_object", json_schema_extra={**_op_meta("create_object", "Objects", "Create Object"), "x-creates-resource": True, "x-resource-type": "attio_object", "x-resource-id-path": "data.api_slug"}, title="Create Object")
    api_slug: str = Field(..., title="API Slug", description="Unique snake_case slug (e.g. projects)")
    singular_noun: str = Field(..., title="Singular Noun", description="e.g. Project")
    plural_noun: str = Field(..., title="Plural Noun", description="e.g. Projects")


class AttioUpdateObjectConfig(BaseModel):
    """Update a custom object's slug or nouns."""

    operation: Literal["update_object"] = Field("update_object", json_schema_extra=_op_meta("update_object", "Objects", "Update Object"), title="Update Object")
    object: str = Field(..., title="Object", description="Object slug or ID")
    api_slug: Optional[str] = Field(None, title="API Slug", json_schema_extra={"ui:placeholder": "e.g. projects"})
    singular_noun: Optional[str] = Field(None, title="Singular Noun", json_schema_extra={"ui:placeholder": "e.g. Project"})
    plural_noun: Optional[str] = Field(None, title="Plural Noun", json_schema_extra={"ui:placeholder": "e.g. Projects"})

    @model_validator(mode="after")
    def _require_one_field(self):
        if not (self.api_slug or self.singular_noun or self.plural_noun):
            raise ValueError("Provide at least one field to update (API Slug, Singular Noun, or Plural Noun).")
        return self


class AttioGetAttributeConfig(BaseModel):
    """Fetch a single attribute on an object or list."""

    operation: Literal["get_attribute"] = Field("get_attribute", json_schema_extra=_op_meta("get_attribute", "Attributes", "Get Attribute"), title="Get Attribute")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID")
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID")


class AttioCreateAttributeConfig(BaseModel):
    """Create an attribute on an object or list."""

    operation: Literal["create_attribute"] = Field("create_attribute", json_schema_extra=_op_meta("create_attribute", "Attributes", "Create Attribute"), title="Create Attribute")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID")
    title: str = Field(..., title="Title", description="Human-readable attribute name")
    api_slug: str = Field(..., title="API Slug", description="Unique snake_case slug")
    type: str = Field(
        "text", title="Type",
        description="Attribute data type",
        json_schema_extra={
            "enum": ["text", "number", "checkbox", "currency", "date", "timestamp", "rating", "status", "select", "record-reference", "actor-reference", "location", "domain", "email-address", "phone-number"],
            "x-enum-searchable": True,
        },
    )
    is_required: str = Field("false", title="Required", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    is_unique: str = Field("false", title="Unique", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    is_multiselect: str = Field("false", title="Multiselect", json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})
    description: Optional[str] = Field(None, title="Description", json_schema_extra={"ui:placeholder": "Optional attribute description"})
    config_json: Optional[str] = Field(None, title="Config (JSON)", description='Type-specific config, e.g. {"currency": {"default_currency_code": "USD", "display_type": "symbol"}}', json_schema_extra={"ui:widget": "textarea"})


class AttioUpdateAttributeConfig(BaseModel):
    """Update an attribute (title, slug, required/unique, archive, config)."""

    operation: Literal["update_attribute"] = Field("update_attribute", json_schema_extra=_op_meta("update_attribute", "Attributes", "Update Attribute"), title="Update Attribute")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID")
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID")
    values_json: str = Field(..., title="Fields (JSON)", description='Fields to update, e.g. {"title": "New name", "is_required": true, "is_archived": false}', json_schema_extra={"ui:widget": "textarea"})


class AttioListSelectOptionsConfig(BaseModel):
    """List the select options of a select attribute."""

    operation: Literal["list_select_options"] = Field("list_select_options", json_schema_extra=_op_meta("list_select_options", "Attributes", "List Select Options"), title="List Select Options")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID", json_schema_extra={"ui:placeholder": "e.g. companies"})
    attribute: str = Field(..., title="Attribute", description="Select attribute slug or ID")


class AttioCreateSelectOptionConfig(BaseModel):
    """Add a select option to a select attribute."""

    operation: Literal["create_select_option"] = Field("create_select_option", json_schema_extra=_op_meta("create_select_option", "Attributes", "Create Select Option"), title="Create Select Option")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID", json_schema_extra={"ui:placeholder": "e.g. companies"})
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID", json_schema_extra={"ui:placeholder": "e.g. status"})
    title: str = Field(..., title="Option Title", json_schema_extra={"ui:placeholder": "e.g. Enterprise"})


class AttioUpdateSelectOptionConfig(BaseModel):
    """Rename or archive a select option."""

    operation: Literal["update_select_option"] = Field("update_select_option", json_schema_extra=_op_meta("update_select_option", "Attributes", "Update Select Option"), title="Update Select Option")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID", json_schema_extra={"ui:placeholder": "e.g. companies"})
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID", json_schema_extra={"ui:placeholder": "e.g. status"})
    option: str = Field(..., title="Option ID", description="Option ID to update", json_schema_extra={"ui:placeholder": "e.g. 016e88d9-de10-4e1c-9aef-36b07cb4260d"})
    title: Optional[str] = Field(None, title="New Title", json_schema_extra={"ui:placeholder": "Leave blank to keep current"})
    is_archived: Optional[str] = Field(None, title="Archived", json_schema_extra={"enum": ["", "true", "false"], "enumNames": ["No change", "Yes", "No"], "x-enum-searchable": True})

    @model_validator(mode="after")
    def _require_one_field(self):
        if not (self.title or self.is_archived):
            raise ValueError("Provide something to update: a New Title and/or Archived.")
        return self


class AttioListStatusesConfig(BaseModel):
    """List the statuses of a status attribute."""

    operation: Literal["list_statuses"] = Field("list_statuses", json_schema_extra=_op_meta("list_statuses", "Attributes", "List Statuses"), title="List Statuses")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID", json_schema_extra={"ui:placeholder": "e.g. companies"})
    attribute: str = Field(..., title="Attribute", description="Status attribute slug or ID")


class AttioCreateStatusConfig(BaseModel):
    """Add a status to a status attribute."""

    operation: Literal["create_status"] = Field("create_status", json_schema_extra=_op_meta("create_status", "Attributes", "Create Status"), title="Create Status")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID", json_schema_extra={"ui:placeholder": "e.g. companies"})
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID", json_schema_extra={"ui:placeholder": "e.g. status"})
    title: str = Field(..., title="Status Title", json_schema_extra={"ui:placeholder": "e.g. In Progress"})
    celebration_enabled: Optional[str] = Field(None, title="Celebration", json_schema_extra={"enum": ["", "true", "false"], "enumNames": ["Default", "Yes", "No"], "x-enum-searchable": True})
    target_time_in_status: Optional[str] = Field(None, title="Target Time In Status", description="ISO-8601 duration, e.g. P0Y0M1DT0H0M0S")


class AttioUpdateStatusConfig(BaseModel):
    """Rename, archive, or retime a status."""

    operation: Literal["update_status"] = Field("update_status", json_schema_extra=_op_meta("update_status", "Attributes", "Update Status"), title="Update Status")
    target: str = _target_field()
    identifier: str = Field(..., title="Identifier", description="Object/list slug or ID", json_schema_extra={"ui:placeholder": "e.g. companies"})
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID", json_schema_extra={"ui:placeholder": "e.g. status"})
    status: str = Field(..., title="Status ID", description="Status ID to update")
    values_json: str = Field(..., title="Fields (JSON)", description='Fields to update, e.g. {"title": "Won", "is_archived": false}', json_schema_extra={"ui:widget": "textarea"})


# ============================================================================
# Additional Record / List Entry ops (overwrite, sub-resources, assert)
# ============================================================================


class AttioOverwriteRecordConfig(BaseModel):
    """Overwrite a record (PUT replaces multiselect attribute values)."""

    operation: Literal["overwrite_record"] = Field("overwrite_record", json_schema_extra=_op_meta("overwrite_record", "Records", "Overwrite Record"), title="Overwrite Record")
    object: str = Field(..., title="Object", description="Object slug or ID")
    record_id: str = Field(..., title="Record ID", description="record_id (UUID) to overwrite")
    values_json: str = Field(..., title="Attribute Values (JSON)", description="Map of attribute slug -> value. PUT overwrites multiselect values.", json_schema_extra={"ui:widget": "textarea"})


class AttioListRecordEntriesConfig(BaseModel):
    """List the list entries a record belongs to."""

    operation: Literal["list_record_entries"] = Field("list_record_entries", json_schema_extra=_op_meta("list_record_entries", "Records", "List Record's List Entries"), title="List Record's List Entries")
    object: str = Field(..., title="Object", description="Object slug or ID")
    record_id: str = Field(..., title="Record ID", description="The record_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 6003a6aa-7122-45f1-b840-efe9231dfd06"})
    limit: Optional[str] = Field("50", title="Limit")
    offset: Optional[str] = Field("0", title="Offset")


class AttioListRecordAttributeValuesConfig(BaseModel):
    """List the historical values of one attribute on a record."""

    operation: Literal["list_record_attribute_values"] = Field("list_record_attribute_values", json_schema_extra=_op_meta("list_record_attribute_values", "Records", "List Record Attribute Values"), title="List Record Attribute Values")
    object: str = Field(..., title="Object", description="Object slug or ID")
    record_id: str = Field(..., title="Record ID", description="The record_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 6003a6aa-7122-45f1-b840-efe9231dfd06"})
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID")
    limit: Optional[str] = Field("50", title="Limit")


class AttioGetListConfig(BaseModel):
    """Fetch a single list by slug or ID."""

    operation: Literal["get_list"] = Field("get_list", json_schema_extra=_op_meta("get_list", "Lists", "Get List"), title="Get List")
    list: str = Field(..., title="List", description="List slug or ID")


class AttioCreateListConfig(BaseModel):
    """Create a new list."""

    operation: Literal["create_list"] = Field("create_list", json_schema_extra={**_op_meta("create_list", "Lists", "Create List"), "x-creates-resource": True, "x-resource-type": "attio_list", "x-resource-id-path": "data.api_slug"}, title="Create List")
    name: str = Field(..., title="Name", json_schema_extra={"ui:placeholder": "e.g. Sales Pipeline"})
    api_slug: str = Field(..., title="API Slug", description="Unique snake_case slug")
    parent_object: str = Field(..., title="Parent Object", description="Object slug or ID the list is based on")
    workspace_access: str = Field(
        "full-access", title="Workspace Access",
        description="Default access level for all workspace members",
        json_schema_extra={"enum": ["full-access", "read-and-write", "read-only"], "x-enum-searchable": True},
    )


class AttioUpdateListConfig(BaseModel):
    """Update a list's name, slug, or access."""

    operation: Literal["update_list"] = Field("update_list", json_schema_extra=_op_meta("update_list", "Lists", "Update List"), title="Update List")
    list: str = Field(..., title="List", description="List slug or ID", json_schema_extra={"ui:placeholder": "e.g. sales_pipeline"})
    name: Optional[str] = Field(None, title="Name", json_schema_extra={"ui:placeholder": "e.g. Sales Pipeline"})
    api_slug: Optional[str] = Field(None, title="API Slug", json_schema_extra={"ui:placeholder": "e.g. projects"})
    workspace_access: Optional[str] = Field(
        None, title="Workspace Access",
        json_schema_extra={"enum": ["", "full-access", "read-and-write", "read-only"], "enumNames": ["No change", "Full access", "Read & write", "Read only"], "x-enum-searchable": True},
    )

    @model_validator(mode="after")
    def _require_one_field(self):
        if not (self.name or self.api_slug or self.workspace_access):
            raise ValueError("Provide at least one field to update (Name, API Slug, or Workspace Access).")
        return self


class AttioGetListEntryConfig(BaseModel):
    """Fetch a single list entry by ID."""

    operation: Literal["get_list_entry"] = Field("get_list_entry", json_schema_extra=_op_meta("get_list_entry", "List Entries", "Get List Entry"), title="Get List Entry")
    list: str = Field(..., title="List", description="List slug or ID")
    entry_id: str = Field(..., title="Entry ID", description="The entry_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 861c1071-54ba-4d3d-b642-f72f7bcc8c7e"})


class AttioAssertListEntryConfig(BaseModel):
    """Upsert a list entry by its parent record (create if absent, else update)."""

    operation: Literal["assert_list_entry"] = Field("assert_list_entry", json_schema_extra=_op_meta("assert_list_entry", "List Entries", "Assert List Entry (by parent)"), title="Assert List Entry")
    list: str = Field(..., title="List", description="List slug or ID")
    parent_record_id: str = Field(..., title="Parent Record ID", description="record_id (UUID) of the parent record")
    parent_object: str = Field(..., title="Parent Object", description="Object slug of the parent record")
    entry_values_json: Optional[str] = Field(None, title="Entry Values (JSON)", description="Map of list attribute slug -> value", json_schema_extra={"ui:widget": "textarea"})


class AttioOverwriteListEntryConfig(BaseModel):
    """Overwrite a list entry (PUT replaces multiselect values)."""

    operation: Literal["overwrite_list_entry"] = Field("overwrite_list_entry", json_schema_extra=_op_meta("overwrite_list_entry", "List Entries", "Overwrite List Entry"), title="Overwrite List Entry")
    list: str = Field(..., title="List", description="List slug or ID")
    entry_id: str = Field(..., title="Entry ID", description="The entry_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 861c1071-54ba-4d3d-b642-f72f7bcc8c7e"})
    entry_values_json: str = Field(..., title="Entry Values (JSON)", description="Map of attribute slug -> value. PUT overwrites multiselect values.", json_schema_extra={"ui:widget": "textarea"})


class AttioListEntryAttributeValuesConfig(BaseModel):
    """List the historical values of one attribute on a list entry."""

    operation: Literal["list_list_entry_attribute_values"] = Field("list_list_entry_attribute_values", json_schema_extra=_op_meta("list_list_entry_attribute_values", "List Entries", "List Entry Attribute Values"), title="List Entry Attribute Values")
    list: str = Field(..., title="List", description="List slug or ID")
    entry_id: str = Field(..., title="Entry ID", description="The entry_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 861c1071-54ba-4d3d-b642-f72f7bcc8c7e"})
    attribute: str = Field(..., title="Attribute", description="Attribute slug or ID")
    limit: Optional[str] = Field("50", title="Limit")


# ============================================================================
# Get-single ops for notes, tasks, comments, threads, files, meetings
# ============================================================================


class AttioGetNoteConfig(BaseModel):
    """Fetch a single note by ID."""

    operation: Literal["get_note"] = Field("get_note", json_schema_extra=_op_meta("get_note", "Notes", "Get Note"), title="Get Note")
    note_id: str = Field(..., title="Note ID", description="The note_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 3cf18abc-4497-4955-89dc-7a4bd0c0eb65"})


class AttioGetTaskConfig(BaseModel):
    """Fetch a single task by ID."""

    operation: Literal["get_task"] = Field("get_task", json_schema_extra=_op_meta("get_task", "Tasks", "Get Task"), title="Get Task")
    task_id: str = Field(..., title="Task ID", description="The task_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 3a07dd01-20b5-4064-b1a0-0f329ba9669c"})


class AttioGetCommentConfig(BaseModel):
    """Fetch a single comment by ID."""

    operation: Literal["get_comment"] = Field("get_comment", json_schema_extra=_op_meta("get_comment", "Comments", "Get Comment"), title="Get Comment")
    comment_id: str = Field(..., title="Comment ID", description="The comment_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 016e88d9-de10-4e1c-9aef-36b07cb4260d"})


class AttioDeleteCommentConfig(BaseModel):
    """Delete a comment by ID."""

    operation: Literal["delete_comment"] = Field("delete_comment", json_schema_extra=_op_meta("delete_comment", "Comments", "Delete Comment"), title="Delete Comment")
    comment_id: str = Field(..., title="Comment ID", description="The comment_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 016e88d9-de10-4e1c-9aef-36b07cb4260d"})


class AttioListThreadsConfig(BaseModel):
    """List comment threads on a record."""

    operation: Literal["list_threads"] = Field("list_threads", json_schema_extra=_op_meta("list_threads", "Comments", "List Threads on Record"), title="List Threads on Record")
    record_object: str = Field(
        ..., title="Record Object", description="Object slug/ID whose threads to list",
        json_schema_extra={
            "x-resource-type": "attio_object", "x-dynamic-options": {"field_name": "object", "placeholder": "Select an object...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste an object slug"},
        },
    )
    record_id: str = Field(..., title="Record ID", description="record_id (UUID) whose threads to list", json_schema_extra={"ui:placeholder": "e.g. 6003a6aa-7122-45f1-b840-efe9231dfd06"})
    limit: Optional[str] = Field("50", title="Limit", json_schema_extra={"ui:placeholder": "e.g. 50"})


class AttioListEntryThreadsConfig(BaseModel):
    """List comment threads on a list entry."""

    operation: Literal["list_entry_threads"] = Field("list_entry_threads", json_schema_extra=_op_meta("list_entry_threads", "Comments", "List Threads on List Entry"), title="List Threads on List Entry")
    entry_list: str = Field(
        ..., title="List", description="List slug/ID the entry belongs to",
        json_schema_extra={
            "x-resource-type": "attio_list", "x-dynamic-options": {"field_name": "list", "placeholder": "Select a list...", "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste a list slug"},
        },
    )
    entry_id: str = Field(..., title="Entry ID", description="entry_id (UUID) whose threads to list", json_schema_extra={"ui:placeholder": "e.g. 861c1071-54ba-4d3d-b642-f72f7bcc8c7e"})
    limit: Optional[str] = Field("50", title="Limit", json_schema_extra={"ui:placeholder": "e.g. 50"})


class AttioGetThreadConfig(BaseModel):
    """Fetch a single comment thread by ID."""

    operation: Literal["get_thread"] = Field("get_thread", json_schema_extra=_op_meta("get_thread", "Comments", "Get Thread"), title="Get Thread")
    thread_id: str = Field(..., title="Thread ID", description="The thread_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 016e88d9-de10-4e1c-9aef-36b07cb4260d"})


class AttioListFilesConfig(BaseModel):
    """List files attached to a record."""

    operation: Literal["list_files"] = Field("list_files", json_schema_extra=_op_meta("list_files", "Files", "List Files"), title="List Files")
    object: str = Field(..., title="Object", description="Object slug or ID")
    record_id: str = Field(..., title="Record ID", description="record_id (UUID) whose files to list")
    limit: Optional[str] = Field("50", title="Limit")


class AttioGetFileConfig(BaseModel):
    """Fetch a single file's metadata by ID."""

    operation: Literal["get_file"] = Field("get_file", json_schema_extra=_op_meta("get_file", "Files", "Get File"), title="Get File")
    file_id: str = Field(..., title="File ID", description="The file_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 6116c4ff-3d9f-4b1a-b47c-67f2a543060f"})


class AttioListMeetingsConfig(BaseModel):
    """List meetings, optionally scoped to a linked record."""

    operation: Literal["list_meetings"] = Field("list_meetings", json_schema_extra=_op_meta("list_meetings", "Meetings", "List Meetings"), title="List Meetings")
    linked_object: Optional[str] = Field(None, title="Linked Object", description="Object slug to scope meetings to (optional)")
    linked_record_id: Optional[str] = Field(None, title="Linked Record ID", description="record_id (UUID) to scope meetings to (optional)")
    limit: Optional[str] = Field("50", title="Limit")


class AttioGetMeetingConfig(BaseModel):
    """Fetch a single meeting by ID."""

    operation: Literal["get_meeting"] = Field("get_meeting", json_schema_extra=_op_meta("get_meeting", "Meetings", "Get Meeting"), title="Get Meeting")
    meeting_id: str = Field(..., title="Meeting ID", description="The meeting_id (UUID)", json_schema_extra={"ui:placeholder": "e.g. 928e88d9-de10-4e1c-9aef-36b07cb4260d"})


# ============================================================================
# Webhook Trigger Config
# ============================================================================


def _attio_trigger_meta(op: str, display: str) -> Dict[str, Any]:
    return {
        "const": op, "ui:hidden": True, "x-category": None,
        "x-is-trigger": True, "x-display-name": display,
    }


def _attio_event_types_field(events: List[str], noun: str) -> Any:
    enum, enum_names = _event_enum_for(events)
    labels = ", ".join(events)
    return Field(
        "*",
        title="Event Type",
        description=(
            f"Which {noun} event fires this workflow. Choose 'All events in this "
            f"category' to fire on every one, or narrow to specific events. "
            f"Supported: {labels}. Accepts a comma-separated list."
        ),
        json_schema_extra={"enum": enum, "enumNames": enum_names, "x-enum-searchable": True},
    )


class _AttioTriggerBase(BaseModel):
    """Shared plumbing for every Attio webhook trigger (hidden fields written back
    by ``load_field_value`` after registration)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Attio posts events here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class AttioOnRecordEventConfig(_AttioTriggerBase):
    """Fire when a record is created, updated, deleted, or merged."""

    operation: Literal["on_record_event"] = Field(
        "on_record_event", json_schema_extra=_attio_trigger_meta("on_record_event", "On Record Event"),
        title="On Record Event",
    )
    event_types: str = _attio_event_types_field(ATTIO_TRIGGER_CATEGORY_EVENTS["on_record_event"], "record")


class AttioOnListEntryEventConfig(_AttioTriggerBase):
    """Fire when a list entry is created, updated, or deleted."""

    operation: Literal["on_list_entry_event"] = Field(
        "on_list_entry_event", json_schema_extra=_attio_trigger_meta("on_list_entry_event", "On List Entry Event"),
        title="On List Entry Event",
    )
    event_types: str = _attio_event_types_field(ATTIO_TRIGGER_CATEGORY_EVENTS["on_list_entry_event"], "list-entry")


class AttioOnNoteEventConfig(_AttioTriggerBase):
    """Fire when a note is created, updated, deleted, or its content changes."""

    operation: Literal["on_note_event"] = Field(
        "on_note_event", json_schema_extra=_attio_trigger_meta("on_note_event", "On Note Event"),
        title="On Note Event",
    )
    event_types: str = _attio_event_types_field(ATTIO_TRIGGER_CATEGORY_EVENTS["on_note_event"], "note")


class AttioOnTaskEventConfig(_AttioTriggerBase):
    """Fire when a task is created, updated, or deleted."""

    operation: Literal["on_task_event"] = Field(
        "on_task_event", json_schema_extra=_attio_trigger_meta("on_task_event", "On Task Event"),
        title="On Task Event",
    )
    event_types: str = _attio_event_types_field(ATTIO_TRIGGER_CATEGORY_EVENTS["on_task_event"], "task")


class AttioOnCommentEventConfig(_AttioTriggerBase):
    """Fire when a comment is created, deleted, resolved, or unresolved."""

    operation: Literal["on_comment_event"] = Field(
        "on_comment_event", json_schema_extra=_attio_trigger_meta("on_comment_event", "On Comment Event"),
        title="On Comment Event",
    )
    event_types: str = _attio_event_types_field(ATTIO_TRIGGER_CATEGORY_EVENTS["on_comment_event"], "comment")


class AttioWebhookTriggerConfig(_AttioTriggerBase):
    """Catch-all: fire on ANY Attio webhook event (including schema/admin events
    like list, attribute, call-recording, and workspace-member changes)."""

    operation: Literal["on_attio_event"] = Field(
        "on_attio_event", json_schema_extra=_attio_trigger_meta("on_attio_event", "On Attio Event (Any)"),
        title="On Attio Event (Any)",
    )
    event_types: str = Field(
        "*",
        title="Event Type",
        description=(
            "Which Attio webhook event fires this workflow. Choose 'All events' to "
            "fire on every event, or pick specific ones. Covers all 27 event types "
            "across records, list entries, notes, tasks, comments, lists, "
            "attributes, call recordings, and workspace members. Accepts a "
            "comma-separated list."
        ),
        json_schema_extra={
            "enum": _ATTIO_EVENT_ENUM,
            "enumNames": _ATTIO_EVENT_ENUM_NAMES,
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Discriminated Union
# ============================================================================


AttioConfig = Annotated[
    Union[
        AttioListRecordsConfig,
        AttioGetRecordConfig,
        AttioCreateRecordConfig,
        AttioUpdateRecordConfig,
        AttioUpsertRecordConfig,
        AttioDeleteRecordConfig,
        AttioSearchRecordsConfig,
        AttioListObjectsConfig,
        AttioListAttributesConfig,
        AttioListListsConfig,
        AttioListEntriesConfig,
        AttioCreateListEntryConfig,
        AttioUpdateListEntryConfig,
        AttioDeleteListEntryConfig,
        AttioListNotesConfig,
        AttioCreateNoteConfig,
        AttioDeleteNoteConfig,
        AttioListTasksConfig,
        AttioCreateTaskConfig,
        AttioUpdateTaskConfig,
        AttioDeleteTaskConfig,
        AttioCreateCommentConfig,
        AttioCreateEntryCommentConfig,
        AttioReplyToThreadConfig,
        AttioGetCommentConfig,
        AttioDeleteCommentConfig,
        AttioListThreadsConfig,
        AttioListEntryThreadsConfig,
        AttioGetThreadConfig,
        AttioListWorkspaceMembersConfig,
        AttioGetWorkspaceMemberConfig,
        AttioIdentifySelfConfig,
        AttioGetObjectConfig,
        AttioCreateObjectConfig,
        AttioUpdateObjectConfig,
        AttioGetAttributeConfig,
        AttioCreateAttributeConfig,
        AttioUpdateAttributeConfig,
        AttioListSelectOptionsConfig,
        AttioCreateSelectOptionConfig,
        AttioUpdateSelectOptionConfig,
        AttioListStatusesConfig,
        AttioCreateStatusConfig,
        AttioUpdateStatusConfig,
        AttioOverwriteRecordConfig,
        AttioListRecordEntriesConfig,
        AttioListRecordAttributeValuesConfig,
        AttioGetListConfig,
        AttioCreateListConfig,
        AttioUpdateListConfig,
        AttioGetListEntryConfig,
        AttioAssertListEntryConfig,
        AttioOverwriteListEntryConfig,
        AttioListEntryAttributeValuesConfig,
        AttioGetNoteConfig,
        AttioGetTaskConfig,
        AttioListFilesConfig,
        AttioGetFileConfig,
        AttioListMeetingsConfig,
        AttioGetMeetingConfig,
        AttioOnRecordEventConfig,
        AttioOnListEntryEventConfig,
        AttioOnNoteEventConfig,
        AttioOnTaskEventConfig,
        AttioOnCommentEventConfig,
        AttioWebhookTriggerConfig,
    ],
    Discriminator("operation"),
]

# All webhook-trigger config classes (isinstance dispatch in execute()).
_ATTIO_TRIGGER_TYPES = (
    AttioOnRecordEventConfig,
    AttioOnListEntryEventConfig,
    AttioOnNoteEventConfig,
    AttioOnTaskEventConfig,
    AttioOnCommentEventConfig,
    AttioWebhookTriggerConfig,
)


class AttioNodeConfig(NodeConfig[AttioConfig, AttioCredential]):
    """Full configuration for the Attio node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _attio_request(
    access_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Attio v2 request and return a structured result."""
    url = f"{ATTIO_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
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
                    message = err.get("message") or err.get("code") or str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[AttioNode] API error ({action_name}): {message}")
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
                    payload = response.json()
                    # Attio wraps results in {data: ...}
                    data = payload.get("data", payload) if isinstance(payload, dict) else payload
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
            logger.error(f"[AttioNode] Request failed ({action_name}): {msg}")
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


class AttioNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Attio CRM automation node."""

    edit_examples = [
        "List all companies in Attio",
        "Create a person record when a form is submitted",
        "Upsert a company by domain to dedupe",
        "Add a note to a deal when it closes",
        "Create a follow-up task assigned to a teammate",
        "Trigger a workflow whenever a new record is created in Attio",
    ]

    scope_registry = ATTIO_SCOPES
    # Lists are built by the user; objects (People/Companies/Deals) ship with
    # every Attio workspace.
    connection_evidence = ConnectionEvidence(
        operation="list_lists",
        noun="lists",
    )
    @classmethod
    def get_config_model(cls):
        return AttioNodeConfig

    # ------------------------------------------------------------------
    # OAuth token freshness (no-op for API keys; Attio OAuth tokens are
    # long-lived, so refresh only fires on the rare expiring token)
    # ------------------------------------------------------------------
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Attio OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-expiring API keys."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.attio_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="attio",
        )

    async def _ensure_fresh_token(self, credentials) -> None:
        """Refresh an expired Attio OAuth token in place. API keys are left untouched."""
        if not isinstance(credentials, AttioOAuthCredential):
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.attio_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="attio",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    # ------------------------------------------------------------------
    # Dynamic options (objects + lists)
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
        if field_name not in ("object", "list"):
            return {"options": []}
        access_token = (credential_data or {}).get("access_token")
        if not access_token:
            return {"options": []}

        endpoint = "/v2/objects" if field_name == "object" else "/v2/lists"
        result = await _attio_request(
            access_token, "GET", endpoint, action_name=f"list_{field_name}s"
        )
        if result.get("status") != "success":
            return {"options": []}
        items = result.get("data") or []
        options = []
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = item.get("api_slug")
            name = item.get("plural_noun") or item.get("singular_noun") or item.get("name") or slug
            value = slug
            if value is None:
                ident = item.get("id") or {}
                value = ident.get("object_id") or ident.get("list_id") if isinstance(ident, dict) else None
            if value is not None:
                options.append({"label": str(name or value), "value": str(value)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        access_token = credential.get("access_token")
        if not access_token:
            raise ValueError("An Attio access token is required to register the trigger")
        events = _selected_attio_events(config or {})
        body = {
            "data": {
                "target_url": webhook_url,
                "subscriptions": [
                    {"event_type": event, "filter": None} for event in events
                ],
            }
        }
        result = await _attio_request(
            access_token, "POST", "/v2/webhooks", json_body=body, action_name="register_webhook"
        )
        if result.get("status") != "success":
            raise ValueError(f"Attio webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        ident = data.get("id") if isinstance(data, dict) else None
        external_id = ident.get("webhook_id") if isinstance(ident, dict) else ident
        secret = data.get("secret") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        access_token = (credential or {}).get("access_token")
        if not external_id or not access_token:
            return
        await _attio_request(
            access_token,
            "DELETE",
            f"/v2/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("attio-signature") or headers.get("x-attio-signature")
        if not sent:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip deliveries whose events aren't in the selected event_types.

        Attio batches events into ``payload["events"][].event_type`` (and may also
        post a single bare event). When the user picked specific events this is a
        runtime backstop on top of per-subscription filtering: fire only when at
        least one delivered event matches a selected type. "All events" / "*"
        always fires.
        """
        selected = _selected_attio_events(config or {})
        if set(selected) == set(ATTIO_TRIGGER_EVENTS):
            return True  # Catch-all with everything selected — nothing to filter.
        delivered = _delivered_event_types(payload)
        if not delivered:
            return True  # Can't classify — don't drop the delivery.
        return any(e in selected for e in delivered)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, AttioNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, _ATTIO_TRIGGER_TYPES):
            return {
                "status": "success",
                "action": op.operation,
                "event_types": _selected_attio_events({"operation": op.operation, "event_types": op.event_types}),
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Attio access token.")
        await self._ensure_fresh_token(credentials)
        access_token = credentials.access_token

        handlers = {
            "list_records": self._list_records,
            "get_record": self._get_record,
            "create_record": self._create_record,
            "update_record": self._update_record,
            "upsert_record": self._upsert_record,
            "delete_record": self._delete_record,
            "search_records": self._search_records,
            "list_objects": self._list_objects,
            "list_attributes": self._list_attributes,
            "list_lists": self._list_lists,
            "list_entries": self._list_entries,
            "create_list_entry": self._create_list_entry,
            "update_list_entry": self._update_list_entry,
            "delete_list_entry": self._delete_list_entry,
            "list_notes": self._list_notes,
            "create_note": self._create_note,
            "delete_note": self._delete_note,
            "list_tasks": self._list_tasks,
            "create_task": self._create_task,
            "update_task": self._update_task,
            "delete_task": self._delete_task,
            "create_comment": self._create_comment,
            "create_entry_comment": self._create_entry_comment,
            "reply_to_thread": self._reply_to_thread,
            "get_comment": self._get_comment,
            "delete_comment": self._delete_comment,
            "list_threads": self._list_threads,
            "list_entry_threads": self._list_entry_threads,
            "get_thread": self._get_thread,
            "list_workspace_members": self._list_workspace_members,
            "get_workspace_member": self._get_workspace_member,
            "identify_self": self._identify_self,
            "get_object": self._get_object,
            "create_object": self._create_object,
            "update_object": self._update_object,
            "get_attribute": self._get_attribute,
            "create_attribute": self._create_attribute,
            "update_attribute": self._update_attribute,
            "list_select_options": self._list_select_options,
            "create_select_option": self._create_select_option,
            "update_select_option": self._update_select_option,
            "list_statuses": self._list_statuses,
            "create_status": self._create_status,
            "update_status": self._update_status,
            "overwrite_record": self._overwrite_record,
            "list_record_entries": self._list_record_entries,
            "list_record_attribute_values": self._list_record_attribute_values,
            "get_list": self._get_list,
            "create_list": self._create_list,
            "update_list": self._update_list,
            "get_list_entry": self._get_list_entry,
            "assert_list_entry": self._assert_list_entry,
            "overwrite_list_entry": self._overwrite_list_entry,
            "list_list_entry_attribute_values": self._list_list_entry_attribute_values,
            "get_note": self._get_note,
            "get_task": self._get_task,
            "list_files": self._list_files,
            "get_file": self._get_file,
            "list_meetings": self._list_meetings,
            "get_meeting": self._get_meeting,
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
    # Record handlers
    # ------------------------------------------------------------------
    async def _list_records(self, c: AttioListRecordsConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        filt = _parse_json(c.filter_json)
        if filt is not None:
            body["filter"] = filt
        sorts = _parse_json(c.sorts_json)
        if sorts is not None:
            body["sorts"] = sorts
        if c.limit:
            body["limit"] = int(c.limit)
        if c.offset:
            body["offset"] = int(c.offset)
        return await _attio_request(
            token, "POST", f"/v2/objects/{c.object}/records/query",
            json_body=body, action_name="list_records",
        )

    async def _get_record(self, c: AttioGetRecordConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(
            token, "GET", f"/v2/objects/{c.object}/records/{c.record_id}",
            action_name="get_record",
        )

    async def _create_record(self, c: AttioCreateRecordConfig, token: str) -> Dict[str, Any]:
        values = _parse_json(c.values_json)
        body = {"data": {"values": values}}
        return await _attio_request(
            token, "POST", f"/v2/objects/{c.object}/records",
            json_body=body, action_name="create_record",
        )

    async def _update_record(self, c: AttioUpdateRecordConfig, token: str) -> Dict[str, Any]:
        values = _parse_json(c.values_json)
        body = {"data": {"values": values}}
        return await _attio_request(
            token, "PATCH", f"/v2/objects/{c.object}/records/{c.record_id}",
            json_body=body, action_name="update_record",
        )

    async def _upsert_record(self, c: AttioUpsertRecordConfig, token: str) -> Dict[str, Any]:
        values = _parse_json(c.values_json)
        body = {"data": {"values": values}}
        return await _attio_request(
            token, "PUT", f"/v2/objects/{c.object}/records",
            params={"matching_attribute": c.matching_attribute},
            json_body=body, action_name="upsert_record",
        )

    async def _delete_record(self, c: AttioDeleteRecordConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(
            token, "DELETE", f"/v2/objects/{c.object}/records/{c.record_id}",
            action_name="delete_record",
        )

    async def _search_records(self, c: AttioSearchRecordsConfig, token: str) -> Dict[str, Any]:
        attribute = (c.attribute or "name").strip() or "name"
        body: Dict[str, Any] = {"filter": {attribute: {"$contains": c.query}}}
        if c.limit:
            body["limit"] = int(c.limit)
        return await _attio_request(
            token, "POST", f"/v2/objects/{c.object}/records/query",
            json_body=body, action_name="search_records",
        )

    # ------------------------------------------------------------------
    # Schema handlers
    # ------------------------------------------------------------------
    async def _list_objects(self, c: AttioListObjectsConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", "/v2/objects", action_name="list_objects")

    async def _list_attributes(self, c: AttioListAttributesConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(
            token, "GET", f"/v2/{c.target}/{c.identifier}/attributes",
            action_name="list_attributes",
        )

    async def _list_lists(self, c: AttioListListsConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", "/v2/lists", action_name="list_lists")

    # ------------------------------------------------------------------
    # List entry handlers
    # ------------------------------------------------------------------
    async def _list_entries(self, c: AttioListEntriesConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        filt = _parse_json(c.filter_json)
        if filt is not None:
            body["filter"] = filt
        sorts = _parse_json(c.sorts_json)
        if sorts is not None:
            body["sorts"] = sorts
        if c.limit:
            body["limit"] = int(c.limit)
        if c.offset:
            body["offset"] = int(c.offset)
        return await _attio_request(
            token, "POST", f"/v2/lists/{c.list}/entries/query",
            json_body=body, action_name="list_entries",
        )

    async def _create_list_entry(self, c: AttioCreateListEntryConfig, token: str) -> Dict[str, Any]:
        entry_values = _parse_json(c.entry_values_json) or {}
        body = {
            "data": {
                "parent_record_id": c.parent_record_id,
                "parent_object": c.parent_object,
                "entry_values": entry_values,
            }
        }
        return await _attio_request(
            token, "POST", f"/v2/lists/{c.list}/entries",
            json_body=body, action_name="create_list_entry",
        )

    async def _update_list_entry(self, c: AttioUpdateListEntryConfig, token: str) -> Dict[str, Any]:
        entry_values = _parse_json(c.entry_values_json)
        body = {"data": {"entry_values": entry_values}}
        return await _attio_request(
            token, "PATCH", f"/v2/lists/{c.list}/entries/{c.entry_id}",
            json_body=body, action_name="update_list_entry",
        )

    async def _delete_list_entry(self, c: AttioDeleteListEntryConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(
            token, "DELETE", f"/v2/lists/{c.list}/entries/{c.entry_id}",
            action_name="delete_list_entry",
        )

    # ------------------------------------------------------------------
    # Note handlers
    # ------------------------------------------------------------------
    async def _list_notes(self, c: AttioListNotesConfig, token: str) -> Dict[str, Any]:
        params = {
            "parent_object": c.parent_object,
            "parent_record_id": c.parent_record_id,
            "limit": c.limit,
        }
        return await _attio_request(
            token, "GET", "/v2/notes", params=params, action_name="list_notes"
        )

    async def _create_note(self, c: AttioCreateNoteConfig, token: str) -> Dict[str, Any]:
        body = {
            "data": {
                "parent_object": c.parent_object,
                "parent_record_id": c.parent_record_id,
                "title": c.title,
                "format": "plaintext",
                "content": c.content,
            }
        }
        return await _attio_request(
            token, "POST", "/v2/notes", json_body=body, action_name="create_note"
        )

    async def _delete_note(self, c: AttioDeleteNoteConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(
            token, "DELETE", f"/v2/notes/{c.note_id}", action_name="delete_note"
        )

    # ------------------------------------------------------------------
    # Task handlers
    # ------------------------------------------------------------------
    async def _list_tasks(self, c: AttioListTasksConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(
            token, "GET", "/v2/tasks", params={"limit": c.limit}, action_name="list_tasks"
        )

    async def _create_task(self, c: AttioCreateTaskConfig, token: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "content": c.content,
            "format": "plaintext",
            "is_completed": c.is_completed == "true",
            "deadline_at": c.deadline_at,
            "assignees": _parse_json(c.assignees_json) or [],
            "linked_records": _parse_json(c.linked_records_json) or [],
        }
        data = {k: v for k, v in data.items() if v is not None}
        return await _attio_request(
            token, "POST", "/v2/tasks", json_body={"data": data}, action_name="create_task"
        )

    async def _update_task(self, c: AttioUpdateTaskConfig, token: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if c.is_completed:
            data["is_completed"] = c.is_completed == "true"
        if c.deadline_at:
            data["deadline_at"] = c.deadline_at
        assignees = _parse_json(c.assignees_json)
        if assignees is not None:
            data["assignees"] = assignees
        return await _attio_request(
            token, "PATCH", f"/v2/tasks/{c.task_id}",
            json_body={"data": data}, action_name="update_task",
        )

    async def _delete_task(self, c: AttioDeleteTaskConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(
            token, "DELETE", f"/v2/tasks/{c.task_id}", action_name="delete_task"
        )

    # ------------------------------------------------------------------
    # Comment / workspace / self handlers
    # ------------------------------------------------------------------
    async def _comment_base_data(self, content: str, author_id: Optional[str], token: str) -> Dict[str, Any]:
        """Build the shared comment body; Attio requires an author, defaulting to
        the token owner via introspection when not provided."""
        if not author_id:
            me = await _attio_request(token, "GET", "/v2/self", action_name="identify_self")
            if me.get("status") == "success":
                author_id = (me.get("data") or {}).get("authorized_by_workspace_member_id")
            if not author_id:
                raise ValueError("Could not resolve a comment author. Provide a Workspace Member ID.")
        return {"format": "plaintext", "content": content, "author": {"type": "workspace-member", "id": author_id}}

    async def _create_comment(self, c: AttioCreateCommentConfig, token: str) -> Dict[str, Any]:
        data = await self._comment_base_data(c.content, c.author_workspace_member_id, token)
        data["record"] = {"object": c.record_object, "record_id": c.record_id}
        return await _attio_request(token, "POST", "/v2/comments", json_body={"data": data}, action_name="create_comment")

    async def _create_entry_comment(self, c: AttioCreateEntryCommentConfig, token: str) -> Dict[str, Any]:
        data = await self._comment_base_data(c.content, c.author_workspace_member_id, token)
        data["entry"] = {"list": c.entry_list, "entry_id": c.entry_id}
        return await _attio_request(token, "POST", "/v2/comments", json_body={"data": data}, action_name="create_entry_comment")

    async def _reply_to_thread(self, c: AttioReplyToThreadConfig, token: str) -> Dict[str, Any]:
        data = await self._comment_base_data(c.content, c.author_workspace_member_id, token)
        data["thread_id"] = c.thread_id
        return await _attio_request(token, "POST", "/v2/comments", json_body={"data": data}, action_name="reply_to_thread")

    async def _list_workspace_members(
        self, c: AttioListWorkspaceMembersConfig, token: str
    ) -> Dict[str, Any]:
        return await _attio_request(
            token, "GET", "/v2/workspace_members", action_name="list_workspace_members"
        )

    async def _identify_self(self, c: AttioIdentifySelfConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", "/v2/self", action_name="identify_self")

    async def _get_comment(self, c: AttioGetCommentConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/comments/{c.comment_id}", action_name="get_comment")

    async def _delete_comment(self, c: AttioDeleteCommentConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "DELETE", f"/v2/comments/{c.comment_id}", action_name="delete_comment")

    async def _list_threads(self, c: AttioListThreadsConfig, token: str) -> Dict[str, Any]:
        params = {"object": c.record_object, "record_id": c.record_id, "limit": c.limit}
        return await _attio_request(token, "GET", "/v2/threads", params=params, action_name="list_threads")

    async def _list_entry_threads(self, c: AttioListEntryThreadsConfig, token: str) -> Dict[str, Any]:
        params = {"list": c.entry_list, "entry_id": c.entry_id, "limit": c.limit}
        return await _attio_request(token, "GET", "/v2/threads", params=params, action_name="list_entry_threads")

    async def _get_thread(self, c: AttioGetThreadConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/threads/{c.thread_id}", action_name="get_thread")

    async def _get_workspace_member(self, c: AttioGetWorkspaceMemberConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/workspace_members/{c.workspace_member_id}", action_name="get_workspace_member")

    # ------------------------------------------------------------------
    # Object / attribute schema management handlers
    # ------------------------------------------------------------------
    async def _get_object(self, c: AttioGetObjectConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/objects/{c.object}", action_name="get_object")

    async def _create_object(self, c: AttioCreateObjectConfig, token: str) -> Dict[str, Any]:
        body = {"data": {"api_slug": c.api_slug, "singular_noun": c.singular_noun, "plural_noun": c.plural_noun}}
        return await _attio_request(token, "POST", "/v2/objects", json_body=body, action_name="create_object")

    async def _update_object(self, c: AttioUpdateObjectConfig, token: str) -> Dict[str, Any]:
        data = {k: v for k, v in {"api_slug": c.api_slug, "singular_noun": c.singular_noun, "plural_noun": c.plural_noun}.items() if v}
        return await _attio_request(token, "PATCH", f"/v2/objects/{c.object}", json_body={"data": data}, action_name="update_object")

    async def _get_attribute(self, c: AttioGetAttributeConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}", action_name="get_attribute")

    async def _create_attribute(self, c: AttioCreateAttributeConfig, token: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "title": c.title,
            "api_slug": c.api_slug,
            "type": c.type,
            "description": c.description,
            "is_required": c.is_required == "true",
            "is_unique": c.is_unique == "true",
            "is_multiselect": c.is_multiselect == "true",
            "config": _parse_json(c.config_json) or {},
        }
        return await _attio_request(token, "POST", f"/v2/{c.target}/{c.identifier}/attributes", json_body={"data": data}, action_name="create_attribute")

    async def _update_attribute(self, c: AttioUpdateAttributeConfig, token: str) -> Dict[str, Any]:
        data = _parse_json(c.values_json)
        return await _attio_request(token, "PATCH", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}", json_body={"data": data}, action_name="update_attribute")

    async def _list_select_options(self, c: AttioListSelectOptionsConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}/options", action_name="list_select_options")

    async def _create_select_option(self, c: AttioCreateSelectOptionConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "POST", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}/options", json_body={"data": {"title": c.title}}, action_name="create_select_option")

    async def _update_select_option(self, c: AttioUpdateSelectOptionConfig, token: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if c.title:
            data["title"] = c.title
        if c.is_archived:
            data["is_archived"] = c.is_archived == "true"
        return await _attio_request(token, "PATCH", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}/options/{c.option}", json_body={"data": data}, action_name="update_select_option")

    async def _list_statuses(self, c: AttioListStatusesConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}/statuses", action_name="list_statuses")

    async def _create_status(self, c: AttioCreateStatusConfig, token: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {"title": c.title}
        if c.celebration_enabled:
            data["celebration_enabled"] = c.celebration_enabled == "true"
        if c.target_time_in_status:
            data["target_time_in_status"] = c.target_time_in_status
        return await _attio_request(token, "POST", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}/statuses", json_body={"data": data}, action_name="create_status")

    async def _update_status(self, c: AttioUpdateStatusConfig, token: str) -> Dict[str, Any]:
        data = _parse_json(c.values_json)
        return await _attio_request(token, "PATCH", f"/v2/{c.target}/{c.identifier}/attributes/{c.attribute}/statuses/{c.status}", json_body={"data": data}, action_name="update_status")

    # ------------------------------------------------------------------
    # Record / list-entry extra handlers
    # ------------------------------------------------------------------
    async def _overwrite_record(self, c: AttioOverwriteRecordConfig, token: str) -> Dict[str, Any]:
        body = {"data": {"values": _parse_json(c.values_json)}}
        return await _attio_request(token, "PUT", f"/v2/objects/{c.object}/records/{c.record_id}", json_body=body, action_name="overwrite_record")

    async def _list_record_entries(self, c: AttioListRecordEntriesConfig, token: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "offset": c.offset}
        return await _attio_request(token, "GET", f"/v2/objects/{c.object}/records/{c.record_id}/entries", params=params, action_name="list_record_entries")

    async def _list_record_attribute_values(self, c: AttioListRecordAttributeValuesConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/objects/{c.object}/records/{c.record_id}/attributes/{c.attribute}/values", params={"limit": c.limit}, action_name="list_record_attribute_values")

    async def _get_list(self, c: AttioGetListConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/lists/{c.list}", action_name="get_list")

    async def _create_list(self, c: AttioCreateListConfig, token: str) -> Dict[str, Any]:
        data = {
            "name": c.name,
            "api_slug": c.api_slug,
            "parent_object": c.parent_object,
            "workspace_access": c.workspace_access,
            "workspace_member_access": [],
        }
        return await _attio_request(token, "POST", "/v2/lists", json_body={"data": data}, action_name="create_list")

    async def _update_list(self, c: AttioUpdateListConfig, token: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if c.name:
            data["name"] = c.name
        if c.api_slug:
            data["api_slug"] = c.api_slug
        if c.workspace_access:
            data["workspace_access"] = c.workspace_access
        return await _attio_request(token, "PATCH", f"/v2/lists/{c.list}", json_body={"data": data}, action_name="update_list")

    async def _get_list_entry(self, c: AttioGetListEntryConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/lists/{c.list}/entries/{c.entry_id}", action_name="get_list_entry")

    async def _assert_list_entry(self, c: AttioAssertListEntryConfig, token: str) -> Dict[str, Any]:
        data = {
            "parent_record_id": c.parent_record_id,
            "parent_object": c.parent_object,
            "entry_values": _parse_json(c.entry_values_json) or {},
        }
        return await _attio_request(token, "PUT", f"/v2/lists/{c.list}/entries", json_body={"data": data}, action_name="assert_list_entry")

    async def _overwrite_list_entry(self, c: AttioOverwriteListEntryConfig, token: str) -> Dict[str, Any]:
        body = {"data": {"entry_values": _parse_json(c.entry_values_json)}}
        return await _attio_request(token, "PUT", f"/v2/lists/{c.list}/entries/{c.entry_id}", json_body=body, action_name="overwrite_list_entry")

    async def _list_list_entry_attribute_values(self, c: AttioListEntryAttributeValuesConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/lists/{c.list}/entries/{c.entry_id}/attributes/{c.attribute}/values", params={"limit": c.limit}, action_name="list_list_entry_attribute_values")

    # ------------------------------------------------------------------
    # Get-single + files/meetings handlers
    # ------------------------------------------------------------------
    async def _get_note(self, c: AttioGetNoteConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/notes/{c.note_id}", action_name="get_note")

    async def _get_task(self, c: AttioGetTaskConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/tasks/{c.task_id}", action_name="get_task")

    async def _list_files(self, c: AttioListFilesConfig, token: str) -> Dict[str, Any]:
        params = {"object": c.object, "record_id": c.record_id, "limit": c.limit}
        return await _attio_request(token, "GET", "/v2/files", params=params, action_name="list_files")

    async def _get_file(self, c: AttioGetFileConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/files/{c.file_id}", action_name="get_file")

    async def _list_meetings(self, c: AttioListMeetingsConfig, token: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "linked_object": c.linked_object, "linked_record_id": c.linked_record_id}
        return await _attio_request(token, "GET", "/v2/meetings", params=params, action_name="list_meetings")

    async def _get_meeting(self, c: AttioGetMeetingConfig, token: str) -> Dict[str, Any]:
        return await _attio_request(token, "GET", f"/v2/meetings/{c.meeting_id}", action_name="get_meeting")
