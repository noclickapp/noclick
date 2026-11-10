"""FlowSavvy v1 task, event and schedule automation with a personal API key.

Routes and field names follow FlowSavvy's published OpenAPI document. Polling
uses the documented item modification timestamps because the API has no webhooks.
"""
from __future__ import annotations

from datetime import date

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://my.flowsavvy.app"
DOCS = BASE_URL + "/api/docs/public/openapi.json"


class FlowSavvyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="FlowSavvy API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://my.flowsavvy.app",
        "x-credential-instructions": "Requires FlowSavvy Pro. In FlowSavvy, open Settings → Integrations → API and copy your API key. Paste only the key here.",
    })
    credential_type: Literal["flowsavvy_api_key"] = Field("flowsavvy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListItems(Input):
    operation: Literal["list_items"] = Field("list_items", title="List Items")
    modifiedAfter: Optional[str] = Field(None, title="Modified after", description="UTC timestamp, YYYY-MM-DDThh:mm:ssZ. Strictly after this instant.", json_schema_extra={"format": "date-time"})
    itemType: Optional[Literal["task", "event"]] = Field(None, title="Item type")
    completed: Optional[bool] = Field(None, description="Omit to use the provider's default (incomplete items).")
    listId: Optional[str] = Field(None, title="List ID", description="Requires item type task. Use inbox for unscheduled inbox tasks.")
    calendarId: Optional[str] = Field(None, title="Calendar ID", description="Requires item type event.")
    query: Optional[str] = Field(None, title="Search", description="Search title, notes or location.")
    pageToken: Optional[str] = Field(None, title="Page token")
    limit: int = Field(50, ge=1, le=200)

    @model_validator(mode="after")
    def filters(self):
        if self.listId is not None and self.itemType != "task":
            raise ValueError("Set item type to task when filtering by list")
        if self.calendarId is not None and self.itemType != "event":
            raise ValueError("Set item type to event when filtering by calendar")
        return self


class ItemRef(Input):
    id: str = Field(..., min_length=1, title="Item ID")


class OccurrenceRef(ItemRef):
    occurrenceDate: Optional[str] = Field(None, title="Occurrence date", description="YYYY-MM-DD; omit for the whole non-repeating item.", json_schema_extra={"format": "date"})

    @field_validator("occurrenceDate")
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class GetItem(OccurrenceRef):
    operation: Literal["get_item"] = Field("get_item", title="Get Item")


class EditOccurrence(OccurrenceRef):
    scope: Optional[Literal["thisOccurrence", "thisAndFutureOccurrences"]] = Field(None, description="Required for repeating items; also provide the occurrence date.")


class DeleteItem(EditOccurrence):
    operation: Literal["delete_item"] = Field("delete_item", title="Delete Item")


class ItemFields(Input):
    title: str = Field(..., title="Title", min_length=1)
    notes: Optional[str] = Field(None, max_length=8192, description="Rich-text HTML notes.")
    timeZone: Optional[str] = Field(None, title="Time zone", description="IANA time zone or Floating; omit to use account settings.")
    recurrenceRule: Optional[str] = Field(None, title="Recurrence rule", description="RRULE without the RRULE: prefix.")
    customColor: Optional[str] = Field(None, title="Custom color", description="Hex color, e.g. #FF0000.")
    bufferBeforeMinutes: Optional[int] = Field(None, title="Buffer before (minutes)", ge=0)
    bufferAfterMinutes: Optional[int] = Field(None, title="Buffer after (minutes)", ge=0)


class TaskFields(ItemFields):
    listId: Optional[str] = Field(None, title="List ID", description="Use inbox for unscheduled tasks; omit for the default list.")
    isAutoScheduled: Optional[bool] = Field(None, title="Auto-schedule", description="Without a start time, defaults to automatic scheduling.")
    durationMinutes: Optional[int] = Field(None, title="Duration (minutes)", gt=0, lt=1440)
    dueDateTime: Optional[str] = Field(None, title="Due date/time", description="Local YYYY-MM-DDThh:mm:ss, without an offset.")
    canBeStartedAt: Optional[str] = Field(None, title="Can start at", description="Local YYYY-MM-DDThh:mm:ss, without an offset.")
    startDateTime: Optional[str] = Field(None, title="Start date/time", description="For fixed-time tasks; local YYYY-MM-DDThh:mm:ss.")
    endDateTime: Optional[str] = Field(None, title="End date/time", description="For fixed-time tasks; local YYYY-MM-DDThh:mm:ss.")
    minLengthMinutes: Optional[int] = Field(None, title="Minimum chunk (minutes)", gt=0)
    priority: Optional[Literal["low", "normal", "high", "asap"]] = None
    schedulingHoursId: Optional[str] = Field(None, title="Scheduling hours ID")
    isAutoIgnored: Optional[bool] = Field(None, title="Ignore if overdue")
    blockedByIds: Optional[list[str]] = Field(None, title="Blocked by item IDs")
    blocksIds: Optional[list[str]] = Field(None, title="Blocks item IDs")


class CreateTask(TaskFields):
    operation: Literal["create_task"] = Field("create_task", title="Create Task")


class UpdateTask(TaskFields, EditOccurrence):
    """Replace the task using PUT. Omitted fields are cleared; map every value you want to keep."""
    operation: Literal["update_task"] = Field("update_task", title="Update Task")
    progressMinutes: Optional[int] = Field(None, title="Completed progress (minutes)", ge=0)


class EventFields(ItemFields):
    startDateTime: str = Field(..., title="Start date/time", description="Local YYYY-MM-DDThh:mm:ss, without an offset.")
    endDateTime: str = Field(..., title="End date/time", description="Exclusive end, local YYYY-MM-DDThh:mm:ss. For all-day events use midnight after the last day.")
    allDay: Optional[bool] = Field(None, title="All day")
    busy: Optional[bool] = None
    calendarId: Optional[str] = Field(None, title="Calendar ID", description="Omit for the default calendar.")
    location: Optional[str] = None


class CreateEvent(EventFields):
    operation: Literal["create_event"] = Field("create_event", title="Create Event")


class UpdateEvent(EventFields, EditOccurrence):
    """Replace the event using PUT. Omitted fields are cleared; map every value you want to keep."""
    operation: Literal["update_event"] = Field("update_event", title="Update Event")


class CompleteTask(OccurrenceRef):
    operation: Literal["complete_task"] = Field("complete_task", title="Complete Task")


class UncompleteTask(ItemRef):
    operation: Literal["uncomplete_task"] = Field("uncomplete_task", title="Uncomplete Task")


class GetSchedule(Input):
    operation: Literal["get_schedule"] = Field("get_schedule", title="Get Schedule")
    startDate: Optional[str] = Field(None, title="Start date", description="Inclusive YYYY-MM-DD in the account time zone.", json_schema_extra={"format": "date"})
    endDate: Optional[str] = Field(None, title="End date", description="Inclusive YYYY-MM-DD in the account time zone.", json_schema_extra={"format": "date"})

    @field_validator("startDate", "endDate")
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class Recalculate(Input):
    operation: Literal["recalculate"] = Field("recalculate", title="Recalculate Schedule")
    reschedulePastTasks: bool = Field(False, title="Reschedule past tasks", description="Also move past and in-progress blocks. Otherwise those blocks stay put.")


class ListCalendars(Input):
    operation: Literal["list_calendars"] = Field("list_calendars", title="List Calendars")


class ListLists(Input):
    operation: Literal["list_lists"] = Field("list_lists", title="List Task Lists")


class ListSchedulingHours(Input):
    operation: Literal["list_scheduling_hours"] = Field("list_scheduling_hours", title="List Scheduling Hours")


class PollItems(PollTriggerConfigBase):
    modifiedAfter: Optional[str] = Field(None, title="Modified after", description="Optional fixed UTC lower bound (YYYY-MM-DDThh:mm:ssZ). Existing items are baselined when armed; each later item revision fires once.", json_schema_extra={"format": "date-time"})


class OnTaskUpdated(PollItems):
    operation: Literal["on_task_updated"] = Field("on_task_updated", title="On New or Updated Task", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "ui:hidden": True,
    })
    listId: Optional[str] = Field(None, title="List ID", description="Omit to monitor all lists; inbox is supported.")


class OnEventUpdated(PollItems):
    operation: Literal["on_event_updated"] = Field("on_event_updated", title="On New or Updated Event", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "ui:hidden": True,
    })
    calendarId: Optional[str] = Field(None, title="Calendar ID", description="Omit to monitor all calendars.")


FlowSavvyConfig = Annotated[Union[
    ListItems, GetItem, DeleteItem, CreateTask, UpdateTask, CreateEvent, UpdateEvent,
    CompleteTask, UncompleteTask, GetSchedule, Recalculate, ListCalendars,
    ListLists, ListSchedulingHours, OnTaskUpdated, OnEventUpdated,
], Field(discriminator="operation")]


class FlowSavvyNodeConfig(NodeConfig[FlowSavvyConfig, FlowSavvyAPIKeyCredential]):
    pass


# Each action maps to exactly one published HTTP operation.
ROUTES = {
    "list_items": ("GET", "/api/items"),
    "get_item": ("GET", "/api/items/{id}"),
    "delete_item": ("DELETE", "/api/items/{id}"),
    "create_task": ("POST", "/api/tasks"),
    "update_task": ("PUT", "/api/tasks/{id}"),
    "create_event": ("POST", "/api/events"),
    "update_event": ("PUT", "/api/events/{id}"),
    "complete_task": ("POST", "/api/tasks/{id}/complete"),
    "uncomplete_task": ("POST", "/api/tasks/{id}/uncomplete"),
    "get_schedule": ("GET", "/api/schedule"),
    "recalculate": ("POST", "/api/recalculate"),
    "list_calendars": ("GET", "/api/calendars"),
    "list_lists": ("GET", "/api/lists"),
    "list_scheduling_hours": ("GET", "/api/scheduling-hours"),
}


class FlowSavvyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-flowsavvy"
    connection_evidence = ConnectionEvidence(noun="task lists", operation="list_lists")
    edit_examples = ["Create a FlowSavvy task due tomorrow", "Complete this task", "Show my schedule", "Watch for updated tasks"]

    @classmethod
    def get_config_model(cls):
        return FlowSavvyNodeConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None):
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        # Never follow redirects with a credential or retry ambiguous writes.
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            try:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
            except httpx.RequestError:
                raise ValueError("FlowSavvy request could not be completed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            message = response.text[:1000].replace(key, "[redacted]")
            raise ValueError(f"FlowSavvy HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("FlowSavvy returned an invalid JSON response") from None
        if not isinstance(data, dict):
            raise ValueError("FlowSavvy returned an unexpected response shape")
        return data

    async def _poll_items(self, key, op):
        rows = []
        item_type = "task" if isinstance(op, OnTaskUpdated) else "event"
        for completed in (False, True) if item_type == "task" else (False,):
            params = {"itemType": item_type, "completed": str(completed).lower(), "limit": 200}
            for name in ("modifiedAfter", "listId", "calendarId"):
                value = getattr(op, name, None)
                if value is not None:
                    params[name] = value
            tokens = set()
            for _ in range(25):
                data = await self._request(key, "GET", "/api/items", params=params)
                items = data.get("items") or []
                if not isinstance(items, list):
                    raise ValueError("FlowSavvy item list is invalid")
                for item in items:
                    if not isinstance(item, dict) or not item.get("id") or not item.get("lastModified"):
                        raise ValueError("FlowSavvy poll item needs an ID and modification timestamp")
                rows.extend(items)
                token = data.get("nextPageToken")
                if not token:
                    break
                if token in tokens:
                    raise ValueError("FlowSavvy pagination did not advance")
                tokens.add(token)
                params["pageToken"] = token
            else:
                raise ValueError("FlowSavvy poll exceeded 5000 items per status; narrow the list, calendar or modification lower bound")
        # A task moving between completion states during pagination may occur twice.
        rows = list({(row["id"], row.get("occurrenceDate"), row["lastModified"]): row for row in rows}.values())
        fresh = await self._filter_unseen(rows, lambda row: str((row["id"], row.get("occurrenceDate"), row["lastModified"])))
        return {"items": fresh, "new_item_count": len(fresh), "operation": op.operation}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a FlowSavvy API key")
        key = self.config.credentials.api_key
        op = self.config.config
        if isinstance(op, PollItems):
            return await self._poll_items(key, op)
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        identifier = values.pop("id", None)
        if identifier is not None:
            path = path.replace("{id}", quote(identifier, safe=""))
        body = None
        if isinstance(op, (CreateTask, UpdateTask, CreateEvent, UpdateEvent)):
            params = {name: values.pop(name) for name in ("occurrenceDate", "scope") if name in values}
            body = values
        else:
            params = values
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        data = await self._request(key, method, path, params=params, body=body)
        # Keep provider envelopes and pagination tokens intact for subsequent steps.
        return {"success": True, "operation": op.operation, **data}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in {"on_task_updated", "on_event_updated"}:
            return super().resolve_agent_event(output)
        items = output.get("items") or []
        if not items:
            return None
        lines = []
        location_key = "listId" if output["operation"] == "on_task_updated" else "calendarId"
        for item in items[:20]:
            lines.append(f"- {item.get('title') or 'Untitled item'} (ID {item.get('id')}, list/calendar {item.get(location_key) or 'default'}, updated {item.get('lastModified')}): {item.get('notes') or ''} {item.get('url') or ''}")
        if len(items) > 20:
            lines.append(f"… and {len(items) - 20} more items (see trigger output).")
        return {"text": f"FlowSavvy: {len(items)} new or updated items in the connected account:\n" + "\n".join(lines), "conversation_key": None}
