"""Amazing Marvin's published API, using the person's limited-access API token.

One request per operation; no automatic retries or nested reads. Schedule calls
at least one minute apart to respect the documented 1,440 queries/day budget.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://serv.amazingmarvin.com/api"
DOCS = "https://github.com/amazingmarvin/MarvinAPI/wiki/Marvin-API"


class AmazingMarvinAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Amazing Marvin API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.amazingmarvin.com/pre?api",
            "x-credential-instructions": "Open Amazing Marvin's API strategy settings and paste API_TOKEN (the limited-access token). NoClick sends it as X-API-Token to serv.amazingmarvin.com. Full-access tokens are not needed. Schedule requests at least one minute apart; Marvin limits queries to 1,440 per day and bursts to one every three seconds.",
        })
    credential_type: Literal["amazing_marvin_api_token"] = Field("amazing_marvin_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def dates(cls, value, info):
        if value is not None and info.field_name in {"day", "due_date", "planned_week", "by", "date"}:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("Use YYYY-MM-DD")
        return value


class _CreateItem(_Input):
    title: str = Field(..., min_length=1, max_length=10000)
    note: str | None = Field(None, max_length=100000)
    parent_id: str | None = Field(None, min_length=1, description="Parent category or project ID; use list_categories or list_children to find IDs.")
    label_ids: list[str] | None = Field(None, description="Label IDs from list_labels.")
    day: str | None = Field(None, description="Schedule date, YYYY-MM-DD.")
    due_date: str | None = Field(None, description="Due date, YYYY-MM-DD.")
    planned_week: str | None = Field(None, description="Monday of the planned week, YYYY-MM-DD.")
    planned_month: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Planned month, YYYY-MM.")
    time_estimate: float | None = Field(None, ge=0, allow_inf_nan=False, description="Estimated duration in milliseconds.")
    time_zone_offset: float | None = Field(None, ge=-1440, le=1440, allow_inf_nan=False, description="Local time minus UTC, in minutes (Pacific standard time is -480).")
    backburner: bool | None = None


class CreateTask(_CreateItem):
    """Create a task, optionally resolving title shortcuts like +today and @label."""
    operation: Literal["create_task"] = "create_task"
    auto_complete: bool = Field(True, description="Allow Marvin to expand title shortcuts; false sends X-Auto-Complete: false.")
    is_starred: Literal[0, 1, 2, 3] | None = Field(None, description="Priority: 3 red, 2 orange, 1 yellow, 0 none.")
    daily_section: Literal["Morning", "Afternoon", "Evening"] | None = None
    bonus_section: Literal["Essential", "Bonus"] | None = None


class MarkTaskDone(_Input):
    """Mark a task done. Some client-side completion effects are not implemented by the API."""
    operation: Literal["mark_task_done"] = "mark_task_done"
    item_id: str = Field(..., min_length=1)
    time_zone_offset: float = Field(..., ge=-1440, le=1440, allow_inf_nan=False, description="Local time minus UTC, in minutes.")


class CreateProject(_CreateItem):
    """Create a project in the master list."""
    operation: Literal["create_project"] = "create_project"
    priority: Literal["low", "mid", "high"] | None = None


class CreateEvent(_Input):
    """Create an event. Calendar sync happens in the Marvin client."""
    operation: Literal["create_event"] = "create_event"
    title: str = Field(..., min_length=1, max_length=10000)
    start: str = Field(..., description="ISO 8601 start timestamp with a timezone, e.g. 2021-08-21T14:30:00.000Z.")
    length: float = Field(..., gt=0, allow_inf_nan=False, description="Event duration in milliseconds.")
    note: str | None = None

    @field_validator("start")
    @classmethod
    def timestamp(cls, value):
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Include a timezone in the event start")
        return value


class GetTrackedTask(_Input):
    """Read the task currently being tracked."""
    operation: Literal["get_tracked_task"] = "get_tracked_task"


class ListChildren(_Input):
    """Read direct open child tasks/projects; descendants require separate calls."""
    operation: Literal["list_children"] = "list_children"
    parent_id: str = Field(..., min_length=1, description="Parent ID, or unassigned for inbox items.")


class ListTodayItems(_Input):
    """Read tasks/projects scheduled for a date, including enabled rollover rules."""
    operation: Literal["list_today_items"] = "list_today_items"
    date: str | None = Field(None, description="YYYY-MM-DD; defaults to the server's current date (UTC).")


class ListDueItems(_Input):
    """Read open tasks/projects due on or before a date."""
    operation: Literal["list_due_items"] = "list_due_items"
    by: str | None = Field(None, description="YYYY-MM-DD; defaults to the server's current date.")


class ListTodayTimeBlocks(_Input):
    """Read time blocks for a date."""
    operation: Literal["list_today_time_blocks"] = "list_today_time_blocks"
    date: str | None = Field(None, description="YYYY-MM-DD; defaults to today.")


class ListCategories(_Input):
    """Read the account's categories."""
    operation: Literal["list_categories"] = "list_categories"


class ListLabels(_Input):
    """Read the account's labels in their sort order."""
    operation: Literal["list_labels"] = "list_labels"


class TrackTime(_Input):
    """Start or stop a task's timer. The API does not update cached task duration/times; reconcile those separately in Marvin."""
    operation: Literal["track_time"] = "track_time"
    task_id: str = Field(..., min_length=1)
    action: Literal["START", "STOP"] = Field(..., description="Start or stop tracking the task.")


class GetTimeTracks(_Input):
    """Read authoritative time-track data for up to 100 tasks."""
    operation: Literal["get_time_tracks"] = "get_time_tracks"
    task_ids: list[str] = Field(..., min_length=1, max_length=100)


class GetKudos(_Input):
    """Read Kudos level and remaining points."""
    operation: Literal["get_kudos"] = "get_kudos"


class GetProfile(_Input):
    """Read account information."""
    operation: Literal["get_profile"] = "get_profile"


class ListGoals(_Input):
    """Read all goals."""
    operation: Literal["list_goals"] = "list_goals"


class RecordHabit(_Input):
    """Record a habit value and update its synced document (experimental)."""
    operation: Literal["record_habit"] = "record_habit"
    habit_id: str = Field(..., min_length=1)
    value: float = Field(..., allow_inf_nan=False)
    time: float | None = Field(None, ge=0, allow_inf_nan=False, description="Recording time as Unix milliseconds; defaults to now on the server.")
    update_db: bool = Field(True, description="Update the synced Habit document as well as the source-of-truth history.")


class GetHabit(_Input):
    """Read a habit including its history (experimental)."""
    operation: Literal["get_habit"] = "get_habit"
    id: str = Field(..., min_length=1, title="Habit ID")


class ListHabits(_Input):
    """Read habits with history; raw full-access mode is not requested (experimental)."""
    operation: Literal["list_habits"] = "list_habits"


Operation = Annotated[Union[CreateTask, MarkTaskDone, CreateProject, CreateEvent,
    GetTrackedTask, ListChildren, ListTodayItems, ListDueItems, ListTodayTimeBlocks,
    ListCategories, ListLabels, TrackTime, GetTimeTracks, GetKudos, GetProfile,
    ListGoals, RecordHabit, GetHabit, ListHabits], Field(discriminator="operation")]


class AmazingMarvinConfig(NodeConfig[Operation, AmazingMarvinAPITokenCredential]):
    pass


# Each operation maps to one published endpoint. POST /tracks is a read.
ROUTES = {
    "create_task": ("POST", "/addTask"),
    "mark_task_done": ("POST", "/markDone"),
    "create_project": ("POST", "/addProject"),
    "create_event": ("POST", "/addEvent"),
    "get_tracked_task": ("GET", "/trackedItem"),
    "list_children": ("GET", "/children"),
    "list_today_items": ("GET", "/todayItems"),
    "list_due_items": ("GET", "/dueItems"),
    "list_today_time_blocks": ("GET", "/todayTimeBlocks"),
    "list_categories": ("GET", "/categories"),
    "list_labels": ("GET", "/labels"),
    "track_time": ("POST", "/track"),
    "get_time_tracks": ("POST", "/tracks"),
    "get_kudos": ("GET", "/kudos"),
    "get_profile": ("GET", "/me"),
    "list_goals": ("GET", "/goals"),
    "record_habit": ("POST", "/updateHabit"),
    "get_habit": ("GET", "/habit"),
    "list_habits": ("GET", "/habits"),
}
WIRE_NAMES = {"parent_id": "parentId", "label_ids": "labelIds", "due_date": "dueDate",
    "planned_week": "plannedWeek", "planned_month": "plannedMonth", "time_estimate": "timeEstimate",
    "time_zone_offset": "timeZoneOffset", "is_starred": "isStarred", "daily_section": "dailySection",
    "bonus_section": "bonusSection", "item_id": "itemId", "task_id": "taskId", "task_ids": "taskIds",
    "habit_id": "habitId", "update_db": "updateDB"}
ACKNOWLEDGEMENTS = {"create_task", "mark_task_done", "create_project", "create_event"}
ARRAYS = {key for key in ROUTES if key.startswith("list_")} | {"get_time_tracks"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {str(key).replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()
            if str(key).lower() not in {"api_token", "full_access_token", "x-api-token", "x-full-access-token", "password", "access_token", "refresh_token"}}
    return value


class AmazingMarvinNode(WorkflowNode):
    integration_type = "automation-amazing-marvin"
    connection_evidence = ConnectionEvidence(noun="categories", operation="list_categories", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return AmazingMarvinConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Amazing Marvin API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[config.operation]
        fields = config.model_dump(exclude_none=True, exclude={"operation", "auto_complete"})
        payload = {WIRE_NAMES.get(key, key): value for key, value in fields.items()}
        headers = {"X-API-Token": token, "Accept": "application/json"}
        if isinstance(config, CreateTask):
            headers["X-Auto-Complete"] = str(config.auto_complete).lower()
        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=30.0) as client:
            response = await client.request(method, BASE + path, headers=headers,
                **({"params": payload} if method == "GET" else {"json": payload}))
        if response.status_code != 200:
            # No retry: writes may have taken effect before an upstream error.
            message = _redact(response.text[:2000], token)
            return {"status": "error", "http_status": response.status_code, "error": message or "Amazing Marvin did not acknowledge the request"}
        if config.operation in ACKNOWLEDGEMENTS:
            # The published contract promises no response body or resource ID.
            return {"status": "success", "http_status": 200, "acknowledged": True}
        data = response.json()
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            return {"status": "error", "error": _redact(str(data.get("error") or data["errors"]), token)}
        if config.operation in ARRAYS:
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ValueError("Amazing Marvin returned an unexpected list response")
        elif config.operation == "get_tracked_task" and data is None:
            pass  # No timer is running.
        elif config.operation == "record_habit" and isinstance(data, (int, float)):
            pass  # The wiki documents the new habit value.
        elif not isinstance(data, dict):
            raise ValueError("Amazing Marvin returned an unexpected object response")
        return {"status": "success", "data": _redact(data, token)}
