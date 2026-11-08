"""Hello Tracks v1 REST integration; API-Key authentication and fixed resource operations.

Contract: https://api-docs.hellotracks.com/v1/openapi.json, version 1.
No sign-in, email-code or key-management endpoints are invoked.
"""
from __future__ import annotations

from datetime import date as calendar_date
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.hellotracks.com/v1"

class HelloTracksAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hello Tracks API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api-docs.hellotracks.com/v1/",
            "x-credential-instructions": "Paste an API key from More → API & Integrations in the Hello Tracks dashboard. The key is sent in the API-Key header. Your account role and company settings control which operations are allowed.",
        })
    credential_type: Literal["hello_tracks_api_key"] = Field("hello_tracks_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)

    @model_validator(mode="after")
    def check_semantics(self):
        values = self.model_dump(by_alias=True, exclude_none=True)
        for name in ("date", "from", "until", "clockOutDate"):
            value = values.get(name)
            if value and (name in {"date", "clockOutDate"} or self.__class__.__name__ == "HelloTracksListTimesheetsConfig"):
                calendar_date.fromisoformat(value)
        for name in ("id",):
            value = values.get(name)
            if value is not None and (not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", value) or value in {".", ".."}):
                raise ValueError("Use a single Hello Tracks resource ID")
        for a, b in (("assigneeId", "assigneeUsername"), ("clockIn", "clockInAt"), ("clockOut", "clockOutAt")):
            if a in values and b in values:
                raise ValueError(f"Use {a} or {b}, not both")
        op = values.get("operation")
        if op == "create_timesheet_entry":
            if not any(k in values for k in ("clockIn", "clockInAt")):
                raise ValueError("Supply clockIn or clockInAt")
            if any(k in values for k in ("clockIn", "clockOut")) and "date" not in values:
                raise ValueError("Supply the date for clock times")
        if op == "update_timesheet_entry" and not any(k in values for k in ("clockIn", "clockInAt", "clockOut", "clockOutAt")):
            raise ValueError("Supply at least one clock time")
        if op == "list_timesheets":
            if ("from" in values) != ("until" in values) or ("date" in values and "from" in values):
                raise ValueError("Use date or both from and until")
            if "from" in values and values["from"] > values["until"]:
                raise ValueError("From must precede until")
        for name in ("clockIn", "clockOut", "start", "end"):
            value = values.get(name)
            if isinstance(value, str) and not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00", value):
                raise ValueError("Use a time from 00:00 through 24:00")
        if all(k in values for k in ("clockInAt", "clockOutAt")) and values["clockOutAt"] <= values["clockInAt"]:
            raise ValueError("Clock-out must follow clock-in")
        return self


class HelloTracksGetWhoAmIConfig(_Input):
    "Returns the account the API key acts as, its company and the key's id. Any valid key may call it. A wrong, expired, revoked or missing key answers 401."
    operation: Literal['get_who_am_i'] = Field('get_who_am_i', json_schema_extra={"ui:hidden": True})
    pass


class HelloTracksGetCompanyConfig(_Input):
    "Returns the key's company: contact details, address, location, settings and teams. Any member of the company may call it."
    operation: Literal['get_company'] = Field('get_company', json_schema_extra={"ui:hidden": True})
    pass


class HelloTracksListMembersConfig(_Input):
    "Lists the company's active members the key may see: admins and company keys see everyone; operators and workers see what the company's visibility settings allow (for example only their own team). The caller is always included. Removed members appear only when asked for by id. No paging: query and max filter the full list."
    operation: Literal['list_members'] = Field('list_members', json_schema_extra={"ui:hidden": True})
    uids: Optional[list[str]] = Field(None, alias='uids', description='Only these member ids; comma-separated or repeated. Removed members of the company are included.')
    uid: Optional[str] = Field(None, alias='uid', description='One member id (replaces uids).')
    query: Optional[str] = Field(None, alias='query', description='Case-insensitive text found in id, username, name or email.')
    max: Optional[int] = Field(None, alias='max', description='At most this many members; no limit by default.', ge=1)


class HelloTracksGetMemberConfig(_Input):
    'Returns one member in a list of one. An unknown id, or a member the key may not see, answers 404 (`not_found`, "Member not found"). Removed members of the company are returned, with activeStatus.'
    operation: Literal['get_member'] = Field('get_member', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Member id (6 characters).')


class HelloTracksListJobsConfig(_Input):
    "Lists the company's jobs.\n\nTwo modes:\n- **Day list** (none of limit, skip, createdSince, updatedSince, progress): the jobs of one day, `date` or today in the caller's time zone, ordered by route position, at most 5,000. Archived jobs only with includeArchived=true.\n- **Paged list** (any of limit, skip, createdSince, updatedSince, progress): all dates unless `date` is given, newest first (by last save, or by creation with createdSince), `limit` default 100, with totalCount and hasMore. Archived jobs are left out unless includeArchived=true.\n\nDeleted jobs never come back. Looking up by `id` or `externalId` returns the job whatever its archive status and ignores date and assignee; no match gives an empty list.\n\nWorkers without the company setting workersViewJobCalendar may only list today (give or take four hours); other dates give 403."
    operation: Literal['list_jobs'] = Field('list_jobs', json_schema_extra={"ui:hidden": True})
    id: Optional[str] = Field(None, alias='id', description='Only this job.')
    external_id: Optional[str] = Field(None, alias='externalId', description='Only the job with this externalId. No match returns an empty list with totalCount 0.')
    date: Optional[str] = Field(None, alias='date', description='Day of the jobs, YYYY-MM-DD. An empty value lists jobs without a date. Default: today in the day list, all dates in the paged list.')
    all_dates: Optional[bool] = Field(None, alias='allDates', description='Search across all dates (used with text).')
    assignee_id: Optional[str] = Field(None, alias='assigneeId', description='Only jobs of this member. An empty value lists unassigned jobs. Not together with assigneeUsername.')
    assignee_username: Optional[str] = Field(None, alias='assigneeUsername', description='Only jobs of the member with this username. An empty value lists unassigned jobs. Not together with assigneeId.')
    progress: Optional[Literal['unassigned', 'scheduled', 'accepted', 'in_progress', 'success', 'failed']] = Field(None, alias='progress', description='Only jobs in this progress state. Switches to the paged list.')
    text: Optional[str] = Field(None, alias='text', description='Case-insensitive search in title, address and notes; also matches a job id, an order number or a job group name.')
    created_since: Optional[int] = Field(None, alias='createdSince', description='ms timestamp: only jobs created at or after it, newest created first. Switches to the paged list.')
    updated_since: Optional[int] = Field(None, alias='updatedSince', description='ms timestamp: only jobs saved at or after it. Switches to the paged list.')
    include_archived: Optional[bool] = Field(None, alias='includeArchived', description='Include archived jobs.')
    limit: Optional[int] = Field(None, alias='limit', description='Page size of the paged list. Switches to the paged list.', ge=0)
    skip: Optional[int] = Field(None, alias='skip', description='Jobs to skip in the paged list. Switches to the paged list.', ge=0)


class HelloTracksCreateJobsConfigLocation(_Input):
    lat: Optional[Union[float, str]] = Field(None, alias='lat', description='Number or numeric string.')
    lng: Optional[Union[float, str]] = Field(None, alias='lng', description='Number or numeric string.')


class HelloTracksCreateJobsConfigTimeWindow(_Input):
    start: Optional[str] = Field(None, alias='start', description='HH:mm (00:00 to 24:00).')
    end: Optional[str] = Field(None, alias='end', description='HH:mm (00:00 to 24:00).')


class HelloTracksCreateJobsConfigContact(_Input):
    name: Optional[str] = Field(None, alias='name', description='name')
    phone: Optional[str] = Field(None, alias='phone', description='phone')
    email: Optional[str] = Field(None, alias='email', description='email')


class HelloTracksCreateJobsConfig(_Input):
    'Creates one job (the job object as the body) or several (`{"jobs": [...]}`).\n\nA job whose externalId matches an existing job of the company is updated with the fields sent instead of creating a duplicate (upsert), and is set back to normal if it was archived. A job that was deleted in Hellotracks stays deleted: it is not changed, and the answer lists it with `status: "deleted"`. The answer lists one job per job sent, in the same order.\n\nJobs without a location get the location of their place, else their address is geocoded in the background, so the response can still show location 0/0. Jobs that are assigned and dated drop the worker\'s saved route for that day, workers get the updated jobs, and the company\'s job webhooks fire. Unknown fields are refused with 400.'
    operation: Literal['create_jobs'] = Field('create_jobs', json_schema_extra={"ui:hidden": True})
    title: Optional[str] = Field(None, alias='title', description='title')
    external_id: Optional[str] = Field(None, alias='externalId', description='Your own id. On POST /jobs an existing job of the company with the same externalId is updated instead of creating a new one.')
    address: Optional[str] = Field(None, alias='address', description='Geocoded in the background when no location is given.')
    location: Optional[HelloTracksCreateJobsConfigLocation] = Field(None, alias='location', description='location')
    place_id: Optional[str] = Field(None, alias='placeId', description="Link the job to a place. A job without location takes the place's location, a job without title the place's name.")
    assignee_id: Optional[str] = Field(None, alias='assigneeId', description='Member id to assign. An empty string unassigns. Do not send together with assigneeUsername.')
    assignee_username: Optional[str] = Field(None, alias='assigneeUsername', description='Member username to assign. An unknown username is ignored. Do not send together with assigneeId.')
    date: Optional[str] = Field(None, alias='date', description='YYYY-MM-DD. An empty string removes the date; null leaves it as it is.')
    time_window: Optional[HelloTracksCreateJobsConfigTimeWindow] = Field(None, alias='timeWindow', description='timeWindow')
    on_site_duration_seconds: Optional[int] = Field(None, alias='onSiteDurationSeconds', description='Non-negative integer (or digits as a string).', ge=0)
    priority: Optional[int] = Field(None, alias='priority', description='0 to 10 (or digits as a string).', ge=0, le=10)
    notes: Optional[str] = Field(None, alias='notes', description='notes')
    contact: Optional[HelloTracksCreateJobsConfigContact] = Field(None, alias='contact', description='contact')
    custom_fields: Optional[dict[str, str]] = Field(None, alias='customFields', description="Replaces the job's whole set of custom fields: names left out are removed. Values are stored as text.")


class HelloTracksGetJobConfig(_Input):
    'Returns the job in `items` (one element), archived ones included. A deleted or unknown job answers 404 (`not_found`, "Job not found").'
    operation: Literal['get_job'] = Field('get_job', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Job id (24 hex characters).')


class HelloTracksUpdateJobConfigLocation(_Input):
    lat: Optional[Union[float, str]] = Field(None, alias='lat', description='Number or numeric string.')
    lng: Optional[Union[float, str]] = Field(None, alias='lng', description='Number or numeric string.')


class HelloTracksUpdateJobConfigTimeWindow(_Input):
    start: Optional[str] = Field(None, alias='start', description='HH:mm (00:00 to 24:00).')
    end: Optional[str] = Field(None, alias='end', description='HH:mm (00:00 to 24:00).')


class HelloTracksUpdateJobConfigContact(_Input):
    name: Optional[str] = Field(None, alias='name', description='name')
    phone: Optional[str] = Field(None, alias='phone', description='phone')
    email: Optional[str] = Field(None, alias='email', description='email')


class HelloTracksUpdateJobConfig(_Input):
    "Updates the job; only the fields sent change. Always notifies the assigned worker and sends route changes; a changed address (without a location) is re-geocoded in the background. An unknown id gives an empty `items` list. Workers may only change today's jobs unless the company allows workersEditJob."
    operation: Literal['update_job'] = Field('update_job', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Job id (24 hex characters).')
    title: Optional[str] = Field(None, alias='title', description='title')
    external_id: Optional[str] = Field(None, alias='externalId', description='Your own id. On POST /jobs an existing job of the company with the same externalId is updated instead of creating a new one.')
    address: Optional[str] = Field(None, alias='address', description='Geocoded in the background when no location is given.')
    location: Optional[HelloTracksUpdateJobConfigLocation] = Field(None, alias='location', description='location')
    place_id: Optional[str] = Field(None, alias='placeId', description="Link the job to a place. A job without location takes the place's location, a job without title the place's name.")
    assignee_id: Optional[str] = Field(None, alias='assigneeId', description='Member id to assign. An empty string unassigns. Do not send together with assigneeUsername.')
    assignee_username: Optional[str] = Field(None, alias='assigneeUsername', description='Member username to assign. An unknown username is ignored. Do not send together with assigneeId.')
    date: Optional[str] = Field(None, alias='date', description='YYYY-MM-DD. An empty string removes the date; null leaves it as it is.')
    time_window: Optional[HelloTracksUpdateJobConfigTimeWindow] = Field(None, alias='timeWindow', description='timeWindow')
    on_site_duration_seconds: Optional[int] = Field(None, alias='onSiteDurationSeconds', description='Non-negative integer (or digits as a string).', ge=0)
    priority: Optional[int] = Field(None, alias='priority', description='0 to 10 (or digits as a string).', ge=0, le=10)
    notes: Optional[str] = Field(None, alias='notes', description='notes')
    contact: Optional[HelloTracksUpdateJobConfigContact] = Field(None, alias='contact', description='contact')
    custom_fields: Optional[dict[str, str]] = Field(None, alias='customFields', description="Replaces the job's whole set of custom fields: names left out are removed. Values are stored as text.")


class HelloTracksDeleteJobConfig(_Input):
    'Deletes the job; it no longer appears in any list. Workers are refused; dispatchers only when the company allows dispatchers to delete jobs. Returns the deleted job in `items`; an unknown id gives an empty list.'
    operation: Literal['delete_job'] = Field('delete_job', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Job id (24 hex characters).')


class HelloTracksArchiveJobConfig(_Input):
    'Archives the job: it leaves the lists unless includeArchived=true and can be restored. Returns the job in `items`. An unknown or deleted id gives an empty list: a deleted job stays deleted, and restore is the way back.'
    operation: Literal['archive_job'] = Field('archive_job', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Job id (24 hex characters).')


class HelloTracksRestoreJobConfig(_Input):
    'Sets an archived job back to normal. Returns the job in `items`; an unknown id gives an empty list.'
    operation: Literal['restore_job'] = Field('restore_job', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Job id (24 hex characters).')


class HelloTracksOptimizeRouteConfigConstraints(_Input):
    working_hours: Optional[bool] = Field(None, alias='working_hours', description='working_hours')
    time_window: Optional[bool] = Field(None, alias='time_window', description='time_window')
    skills: Optional[bool] = Field(None, alias='skills', description='skills')
    capacity: Optional[bool] = Field(None, alias='capacity', description='capacity')
    max_jobs: Optional[int] = Field(None, alias='max_jobs', description='max_jobs')


class HelloTracksOptimizeRouteConfig(_Input):
    "Optimizes the order of one member's jobs on one day and saves the route. Allowed for admins, dispatchers and the company; workers only when the company allows workersOptimizeRoute (403 otherwise, also for a member the caller cannot see). With solve=false a worker's route that was optimized in the last 3 hours is returned unchanged."
    operation: Literal['optimize_route'] = Field('optimize_route', json_schema_extra={"ui:hidden": True})
    account_id: str = Field(..., alias='accountId', description='Member id or username whose route to optimize. Required unless account is sent.')
    account: Optional[str] = Field(None, alias='account', description='Same as accountId (member id or username). Wins when both are sent.')
    date: str = Field(..., alias='date', description='Route day, YYYY-MM-DD. Required.')
    solve: Optional[bool] = Field(None, alias='solve', description='true runs the full solver (time windows, working hours, skills, capacity; jobs that do not fit come back in unassigned). false only reorders the stops.')
    index: Optional[int] = Field(None, alias='index', description='With count: optimize only the stops from this position on.')
    count: Optional[int] = Field(None, alias='count', description='With index: number of stops to optimize.')
    constraints: Optional[HelloTracksOptimizeRouteConfigConstraints] = Field(None, alias='constraints', description='Solver constraints (with solve=true). Keys are snake_case. Each defaults to on.')


class HelloTracksListPlacesConfig(_Input):
    'Lists the places the caller can see. Workers without the company setting workersViewPlaces only see places of their own teams.'
    operation: Literal['list_places'] = Field('list_places', json_schema_extra={"ui:hidden": True})
    uids: Optional[list[str]] = Field(None, alias='uids', description='Only these place ids (repeat the parameter or separate with commas). Ids the caller cannot see are left out.')
    query: Optional[str] = Field(None, alias='query', description='Case-insensitive part of the place name.')
    max: Optional[int] = Field(None, alias='max', description='Maximum number of places.')


class HelloTracksCreatePlaceConfigLocation(_Input):
    lat: float = Field(..., alias='lat', description='lat')
    lng: float = Field(..., alias='lng', description='lng')


class HelloTracksCreatePlaceConfig(_Input):
    "Creates a place for the company. Workers only when the company allows workersCreatePlaces. Without teams the place goes to the creator's teams; without a location the address is geocoded in the background. Visits of the last 30 days that match the new place are labeled with it."
    operation: Literal['create_place'] = Field('create_place', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., alias='name', description='name')
    address: Optional[str] = Field(None, alias='address', description='Geocoded in the background on create when no location is given.')
    email: Optional[str] = Field(None, alias='email', description='email')
    phone: Optional[str] = Field(None, alias='phone', description='phone')
    city: Optional[str] = Field(None, alias='city', description='city')
    postal_code: Optional[str] = Field(None, alias='postalCode', description='postalCode')
    state: Optional[str] = Field(None, alias='state', description='state')
    country_code: Optional[str] = Field(None, alias='countryCode', description='countryCode')
    color: Optional[str] = Field(None, alias='color', description='color')
    teams: Optional[list[int]] = Field(None, alias='teams', description="Team numbers. On create, without teams the place goes to the creator's teams.")
    radius: Optional[int] = Field(None, alias='radius', description='Check-in radius in meters.')
    location: Optional[HelloTracksCreatePlaceConfigLocation] = Field(None, alias='location', description='location')
    extended_data: Optional[dict[str, Union[str, float, bool, None]]] = Field(None, alias='extendedData', description="Custom fields. Merged into the place's current fields: names sent get the value (stored as text), names sent as null are removed, names not sent stay.")


class HelloTracksGetPlaceConfig(_Input):
    'Returns the place in `items` (one element). An unknown place, or one the caller cannot see, answers 404 (`not_found`, "Place not found").'
    operation: Literal['get_place'] = Field('get_place', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Place id.')


class HelloTracksUpdatePlaceConfigLocation(_Input):
    lat: float = Field(..., alias='lat', description='lat')
    lng: float = Field(..., alias='lng', description='lng')


class HelloTracksUpdatePlaceConfig(_Input):
    'Changes the fields sent. extendedData is merged: names sent are set, names sent as null are removed, the others stay. Admins, dispatchers and the company may edit; workers only places they can see when the company allows workersCreatePlaces (403 otherwise).'
    operation: Literal['update_place'] = Field('update_place', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Place id.')
    name: Optional[str] = Field(None, alias='name', description='name')
    address: Optional[str] = Field(None, alias='address', description='Geocoded in the background on create when no location is given.')
    email: Optional[str] = Field(None, alias='email', description='email')
    phone: Optional[str] = Field(None, alias='phone', description='phone')
    city: Optional[str] = Field(None, alias='city', description='city')
    postal_code: Optional[str] = Field(None, alias='postalCode', description='postalCode')
    state: Optional[str] = Field(None, alias='state', description='state')
    country_code: Optional[str] = Field(None, alias='countryCode', description='countryCode')
    color: Optional[str] = Field(None, alias='color', description='color')
    teams: Optional[list[int]] = Field(None, alias='teams', description="Team numbers. On create, without teams the place goes to the creator's teams.")
    radius: Optional[int] = Field(None, alias='radius', description='Check-in radius in meters.')
    location: Optional[HelloTracksUpdatePlaceConfigLocation] = Field(None, alias='location', description='location')
    extended_data: Optional[dict[str, Union[str, float, bool, None]]] = Field(None, alias='extendedData', description="Custom fields. Merged into the place's current fields: names sent get the value (stored as text), names sent as null are removed, names not sent stay.")


class HelloTracksDeletePlaceConfig(_Input):
    "Deletes one place of the caller's company. Workers are refused. An unknown id, or one that is not a place of the company, gives 403 with the message 'place not found'."
    operation: Literal['delete_place'] = Field('delete_place', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Place id.')


class HelloTracksListZonesConfig(_Input):
    "Lists the company's zones (geofences). Workers are refused with 403 (code permission_denied)."
    operation: Literal['list_zones'] = Field('list_zones', json_schema_extra={"ui:hidden": True})
    pass


class HelloTracksListTimesheetsConfig(_Input):
    "Lists clock-in/clock-out entries of the company's members for one day (default today) or a from/until range, with totals. Days are in the caller's time zone; an entry belongs to the day it starts. There is no paging and no limit on the range. Admins, operators and the company key may call it; workers get 403."
    operation: Literal['list_timesheets'] = Field('list_timesheets', json_schema_extra={"ui:hidden": True})
    date: Optional[str] = Field(None, alias='date', description='One day, YYYY-MM-DD. Use either date or from+until; neither = today.')
    from_: Optional[str] = Field(None, alias='from', description='First day, YYYY-MM-DD; needs until.')
    until: Optional[str] = Field(None, alias='until', description='Last day, YYYY-MM-DD, inclusive.')
    member_id: Optional[str] = Field(None, alias='memberId', description='Only this member.')


class HelloTracksCreateTimesheetEntryConfig(_Input):
    'Adds a clock-in, and optionally a clock-out, for a member, as the dashboard does. clockIn or clockInAt is required; the clock-out must be after the clock-in. Admins, operators and the company key may call it; workers get 403.'
    operation: Literal['create_timesheet_entry'] = Field('create_timesheet_entry', json_schema_extra={"ui:hidden": True})
    member_id: str = Field(..., alias='memberId', description='Create only, required: a member of the company.')
    date: Optional[str] = Field(None, alias='date', description="YYYY-MM-DD; required on create when clockIn or clockOut is used. On update it defaults to the entry's day.")
    clock_out_date: Optional[str] = Field(None, alias='clockOutDate', description='YYYY-MM-DD of the clock-out; defaults to date.')
    clock_in: Optional[str] = Field(None, alias='clockIn', description='HH:mm (00:00 to 24:00).', pattern='^\\d{2}:\\d{2}$')
    clock_out: Optional[str] = Field(None, alias='clockOut', description='HH:mm (00:00 to 24:00).', pattern='^\\d{2}:\\d{2}$')
    clock_in_at: Optional[int] = Field(None, alias='clockInAt', description='Milliseconds since the epoch (a numeric string works too).')
    clock_out_at: Optional[int] = Field(None, alias='clockOutAt', description='Milliseconds since the epoch.')


class HelloTracksUpdateTimesheetEntryConfig(_Input):
    "Moves the clock-in and/or clock-out of an entry, or adds the missing clock-out. At least one time field is required. The answer's entry may have a new id. An unknown or foreign entry is answered with 400 invalid_request. Admins, operators and the company key may call it; workers get 403."
    operation: Literal['update_timesheet_entry'] = Field('update_timesheet_entry', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Entry id clockInId_clockOutId, as listed ("-" for a missing side).')
    member_id: Optional[str] = Field(None, alias='memberId', description='Create only, required: a member of the company.')
    date: Optional[str] = Field(None, alias='date', description="YYYY-MM-DD; required on create when clockIn or clockOut is used. On update it defaults to the entry's day.")
    clock_out_date: Optional[str] = Field(None, alias='clockOutDate', description='YYYY-MM-DD of the clock-out; defaults to date.')
    clock_in: Optional[str] = Field(None, alias='clockIn', description='HH:mm (00:00 to 24:00).', pattern='^\\d{2}:\\d{2}$')
    clock_out: Optional[str] = Field(None, alias='clockOut', description='HH:mm (00:00 to 24:00).', pattern='^\\d{2}:\\d{2}$')
    clock_in_at: Optional[int] = Field(None, alias='clockInAt', description='Milliseconds since the epoch (a numeric string works too).')
    clock_out_at: Optional[int] = Field(None, alias='clockOutAt', description='Milliseconds since the epoch.')


class HelloTracksDeleteTimesheetEntryConfig(_Input):
    "Deletes the entry's clock-in and clock-out records for good. An unknown or foreign entry is answered with 400 invalid_request. Admins, operators and the company key may call it; workers get 403."
    operation: Literal['delete_timesheet_entry'] = Field('delete_timesheet_entry', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Entry id clockInId_clockOutId, as listed ("-" for a missing side).')


class HelloTracksListFormTemplatesConfig(_Input):
    "Lists the company's form templates (active and archived). Workers may call it and see only templates linked to places of their teams."
    operation: Literal['list_form_templates'] = Field('list_form_templates', json_schema_extra={"ui:hidden": True})
    pass


class HelloTracksListFormSubmissionsConfig(_Input):
    'Lists submitted forms, newest first. limit is applied before the templateId, jobId and placeId filters, so fewer items than limit may come back even when more match. Admins, operators and the company key only; workers get 403 permission_denied.'
    operation: Literal['list_form_submissions'] = Field('list_form_submissions', json_schema_extra={"ui:hidden": True})
    from_: Optional[str] = Field(None, alias='from', description="From: ms timestamp, or YYYY-MM-DD (start of that day, caller's time zone).")
    until: Optional[str] = Field(None, alias='until', description='Until: ms timestamp, or YYYY-MM-DD (end of that day).')
    limit: Optional[int] = Field(None, alias='limit', description='Maximum number read.', ge=1, le=1000)
    submission_ids: Optional[str] = Field(None, alias='submissionIds', description='Comma-separated numeric submission ids.')
    template_id: Optional[str] = Field(None, alias='templateId', description='Only this template.')
    member_id: Optional[str] = Field(None, alias='memberId', description='Only submissions by this member.')
    job_id: Optional[str] = Field(None, alias='jobId', description='Only submissions for this job.')
    place_id: Optional[str] = Field(None, alias='placeId', description='Only submissions at this place.')


class HelloTracksGetFormSubmissionConfig(_Input):
    'Returns one submitted form with its answers. An unknown or foreign id is answered with 400 invalid_request. Admins, operators and the company key only; workers get 403 permission_denied.'
    operation: Literal['get_form_submission'] = Field('get_form_submission', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., alias='id', description='Numeric submission id.')

HelloTracksOperation = Annotated[Union[
    HelloTracksGetWhoAmIConfig,
    HelloTracksGetCompanyConfig,
    HelloTracksListMembersConfig,
    HelloTracksGetMemberConfig,
    HelloTracksListJobsConfig,
    HelloTracksCreateJobsConfig,
    HelloTracksGetJobConfig,
    HelloTracksUpdateJobConfig,
    HelloTracksDeleteJobConfig,
    HelloTracksArchiveJobConfig,
    HelloTracksRestoreJobConfig,
    HelloTracksOptimizeRouteConfig,
    HelloTracksListPlacesConfig,
    HelloTracksCreatePlaceConfig,
    HelloTracksGetPlaceConfig,
    HelloTracksUpdatePlaceConfig,
    HelloTracksDeletePlaceConfig,
    HelloTracksListZonesConfig,
    HelloTracksListTimesheetsConfig,
    HelloTracksCreateTimesheetEntryConfig,
    HelloTracksUpdateTimesheetEntryConfig,
    HelloTracksDeleteTimesheetEntryConfig,
    HelloTracksListFormTemplatesConfig,
    HelloTracksListFormSubmissionsConfig,
    HelloTracksGetFormSubmissionConfig
], Field(discriminator="operation")]

class HelloTracksFullConfig(NodeConfig[HelloTracksOperation, HelloTracksAPIKeyCredential]):
    pass

ROUTES = {'get_who_am_i': ('GET', '/auth/whoami'), 'get_company': ('GET', '/company'), 'list_members': ('GET', '/members'), 'get_member': ('GET', '/members/{id}'), 'list_jobs': ('GET', '/jobs'), 'create_jobs': ('POST', '/jobs'), 'get_job': ('GET', '/jobs/{id}'), 'update_job': ('PATCH', '/jobs/{id}'), 'delete_job': ('DELETE', '/jobs/{id}'), 'archive_job': ('POST', '/jobs/{id}/archive'), 'restore_job': ('POST', '/jobs/{id}/restore'), 'optimize_route': ('POST', '/routing/optimize'), 'list_places': ('GET', '/places'), 'create_place': ('POST', '/places'), 'get_place': ('GET', '/places/{id}'), 'update_place': ('PATCH', '/places/{id}'), 'delete_place': ('DELETE', '/places/{id}'), 'list_zones': ('GET', '/zones'), 'list_timesheets': ('GET', '/timesheets'), 'create_timesheet_entry': ('POST', '/timesheets/entries'), 'update_timesheet_entry': ('PATCH', '/timesheets/entries/{id}'), 'delete_timesheet_entry': ('DELETE', '/timesheets/entries/{id}'), 'list_form_templates': ('GET', '/forms/templates'), 'list_form_submissions': ('GET', '/forms/submissions'), 'get_form_submission': ('GET', '/forms/submissions/{id}')}
QUERY_FIELDS = {'get_who_am_i': [], 'get_company': [], 'list_members': ['uids', 'uid', 'query', 'max'], 'get_member': [], 'list_jobs': ['id', 'externalId', 'date', 'allDates', 'assigneeId', 'assigneeUsername', 'progress', 'text', 'createdSince', 'updatedSince', 'includeArchived', 'limit', 'skip'], 'create_jobs': [], 'get_job': [], 'update_job': [], 'delete_job': [], 'archive_job': [], 'restore_job': [], 'optimize_route': [], 'list_places': ['uids', 'query', 'max'], 'create_place': [], 'get_place': [], 'update_place': [], 'delete_place': [], 'list_zones': [], 'list_timesheets': ['date', 'from', 'until', 'memberId'], 'create_timesheet_entry': [], 'update_timesheet_entry': [], 'delete_timesheet_entry': [], 'list_form_templates': [], 'list_form_submissions': ['from', 'until', 'limit', 'submissionIds', 'templateId', 'memberId', 'jobId', 'placeId'], 'get_form_submission': []}


class HelloTracksNode(WorkflowNode):
    integration_type = "automation-hello-tracks"
    connection_evidence = ConnectionEvidence(noun="Hello Tracks account", identity_operation="get_who_am_i")

    @classmethod
    def get_config_model(cls):
        return HelloTracksFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Hello Tracks API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(by_alias=True, exclude_none=True)
        values.pop("operation")
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        params = {key: values.pop(key) for key in QUERY_FIELDS[config.operation] if key in values}
        params = {k: "true" if v is True else "false" if v is False else v for k, v in params.items()}
        kwargs = {"params": params, "headers": {"API-Key": self.config.credentials.api_key, "Accept": "application/json"}}
        if method in {"POST", "PATCH"} and config.operation not in {"archive_job", "restore_job"}:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, **kwargs)
        try:
            body = response.json()
        except ValueError:
            response.raise_for_status()
            raise ValueError("Hello Tracks returned a non-JSON response") from None
        if isinstance(body, dict) and body.get("error"):
            error = body["error"]
            message = error.get("message", "Hello Tracks rejected the request") if isinstance(error, dict) else str(error)
            return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(self.config.credentials.api_key, "[redacted]")}
        response.raise_for_status()
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise ValueError("Hello Tracks returned an invalid data envelope")
        return {**body["data"], "status": "success"}
