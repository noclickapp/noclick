"""Timeero public API actions and signed webhook triggers.

Requests follow the pinned TIMEERO PUBLIC API 1.0.0 contract. Webhook delivery
and authentication follow https://developers.timeero.com/docs/overview.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime
from typing import Annotated, Literal, Union, get_args

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.timeero.app"
CREDENTIAL_TYPE = "timeero_api_key"


class TimeeroAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Timeero API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.timeero.com/public-api-integration",
        "x-credential-instructions": "In Timeero, open Integrations > Public API > Configuration and copy your API key. Paste only the key. Timeero API keys have administrative access; NoClick sends yours directly in the Authorization header.",
    })
    credential_type: Literal["timeero_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without an Authorization or Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("user_id", "job_id", "task_id", "timesheet_id", "schedule_id", "group_id", mode="before", check_fields=False)
    @classmethod
    def normalize_resource_ids(cls, value, info):
        # Native workflow resource resolution can serialize numeric IDs as text.
        # Normalize only fields declared as integers; clock-in job/task IDs are
        # strings in the provider contract and retain their declared type.
        annotation = cls.model_fields[info.field_name].annotation
        if info.field_name.endswith("_id") and (annotation is int or int in get_args(annotation)):
            if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value):
                return int(value)
        return value

    @model_validator(mode="after")
    def validate_times_and_job_requirements(self):
        values = self.model_dump()
        start, end = values.get("start"), values.get("end")
        if start and end and end <= start:
            raise ValueError("End must be after start")
        if values.get("require_geofence") and not (values.get("latitude") is not None and values.get("longitude") is not None):
            if not all(values.get(k) for k in ("street", "city", "state", "zip_code", "country")):
                raise ValueError("A geofence requires coordinates or a complete street address")
        if values.get("contact_required") and not all(values.get(k) for k in ("contact_name", "contact_phone", "contact_mobile", "contact_email")):
            raise ValueError("Supply all four contact fields when a contact is required")
        return self


class TimeeroListUsersConfig(_Input):
    """List Users using one documented API operation."""
    operation: Literal['list_users'] = Field('list_users', title='List Users', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Users', "x-category": 'Users', "x-is-trigger": False})
    page: int | None = Field(None, title='Page', description='Specifies which page of the paginated results to return, starting from page 1.', ge=1, strict=True)
    per_page: int | None = Field(None, title='Per Page', description='The number of items to include in each page of the response.', ge=1, le=100, strict=True)
    sort: Literal['first_name', 'last_name', 'role_id'] | None = Field(None, title='Sort', description='The field used to sort the results. Allowed values are first_name, last_name, and role_id.')
    search: str | None = Field(None, title='Search', description='A keyword used to search users by first name, last name, group name, phone number, or email address.', min_length=1, max_length=4096)
    role: str | None = Field(None, title='Role', description='Filters users based on their role (1 for Admin, 2 for Manager, 3 for Employee).', min_length=1, max_length=4096)
    group_id: str | None = Field(None, title='Group Id', description='Filters users by their group ID.', min_length=1, max_length=4096)
    active: bool | None = Field(None, title='Active', description='Filters users based on their active status (true or false).', strict=True)

class TimeeroGetUserConfig(_Input):
    """Get User using one documented API operation."""
    operation: Literal['get_user'] = Field('get_user', title='Get User', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get User', "x-category": 'Users', "x-is-trigger": False})
    user_id: int = Field(..., title='User Id', ge=1, strict=True)

class TimeeroListGroupsConfig(_Input):
    """List Groups using one documented API operation."""
    operation: Literal['list_groups'] = Field('list_groups', title='List Groups', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Groups', "x-category": 'Groups', "x-is-trigger": False})
    page: int | None = Field(None, title='Page', description='Specifies which page of the paginated results to return, starting from page 1.', ge=1, strict=True)
    per_page: int | None = Field(None, title='Per Page', description='The number of items to include in each page of the response.', ge=1, le=100, strict=True)
    sort: Literal["id", "name"] | None = Field(None, title='Sort', description='The field used to sort the results. Allowed values are id, name.')
    name: str | None = Field(None, title='Name', description='This field used to filter groups by group name', min_length=1, max_length=4096)

class TimeeroListJobsConfig(_Input):
    """List Jobs using one documented API operation."""
    operation: Literal['list_jobs'] = Field('list_jobs', title='List Jobs', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Jobs', "x-category": 'Jobs', "x-is-trigger": False})
    page: int | None = Field(None, title='Page', description='Specifies which page of the paginated results to return, starting from page 1.', ge=1, strict=True)
    page_size: int | None = Field(None, title='Page Size', description='The number of items to include in each page of the response.', ge=1, le=100, strict=True)
    sort: Literal["id", "name"] | None = Field(None, title='Sort', description='The field used to sort the results. Allowed values are id, name.')
    job_status: bool | None = Field(None, title='Job Status', description='The field used to filter jobs by job status. true for Active and false for Inactive jobs.', strict=True)
    name: str | None = Field(None, title='Name', description='The name field used to filter jobs by job name', min_length=1, max_length=4096)

class TimeeroGetJobConfig(_Input):
    """Get Job using one documented API operation."""
    operation: Literal['get_job'] = Field('get_job', title='Get Job', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Job', "x-category": 'Jobs', "x-is-trigger": False})
    job_id: int = Field(..., title='Job Id', ge=1, strict=True)

class TimeeroCreateJobConfig(_Input):
    """Create Job using one documented API operation."""
    operation: Literal['create_job'] = Field('create_job', title='Create Job', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Job', "x-category": 'Jobs', "x-is-trigger": False})
    name: str = Field(..., title='Name', description='The name of the job.', min_length=1, max_length=4096)
    description: str | None = Field(None, title='Description', description='A brief description of the job.', min_length=1, max_length=4096)
    track_mileage: bool | None = Field(None, title='Track Mileage', description='Indicates whether mileage tracking is enabled for the job', strict=True)
    require_geofence: bool | None = Field(None, title='Require Geofence', description='Indicates whether users must be within the geofence to perform job-related actions. All the fields are optional except street, city, state, zip_code and country are required when require_geofence is true or 1 and latitude and longitude are not provided.', strict=True)
    street: str | None = Field(None, title='Street', description='The street address of the job location.', min_length=1, max_length=4096)
    landmark: str | None = Field(None, title='Landmark', description='A nearby landmark to help identify the job location.', min_length=1, max_length=4096)
    state: str | None = Field(None, title='State', description='The state or region where the job is located.', min_length=1, max_length=4096)
    city: str | None = Field(None, title='City', description='The city where the job is located.', min_length=1, max_length=4096)
    zip_code: str | None = Field(None, title='Zip Code', description='The ZIP or postal code of the job location.', min_length=1, max_length=4096)
    country: str | None = Field(None, title='Country', description='The country where the job is located.', min_length=1, max_length=4096)
    latitude: float | None = Field(None, title='Latitude', description='The latitude coordinate of the job location.', ge=-90, le=90, strict=True)
    longitude: float | None = Field(None, title='Longitude', description='The longitude coordinate of the job location.', ge=-180, le=180, strict=True)
    radius: int | None = Field(None, title='Radius', description='The geofence radius around the job location, in meters.', ge=1, strict=True)
    contact_required: bool | None = Field(None, title='Contact Required', description='Indicates whether a contact person is required for the job (true = required, false = not required). contact_name, contact_phone, contact_mobile, and contact_email are required when contact_required is true.', strict=True)
    contact_name: str | None = Field(None, title='Contact Name', description='The name of the job contact person.', min_length=1, max_length=4096)
    contact_phone: str | None = Field(None, title='Contact Phone', description='The phone number of the job contact person.', min_length=1, max_length=4096)
    contact_mobile: str | None = Field(None, title='Contact Mobile', description='The mobile number of the job contact person.', min_length=1, max_length=4096)
    contact_email: str | None = Field(None, title='Contact Email', description='The email address of the job contact person.', min_length=1, max_length=4096)
    geofence_members: list[int] | None = Field(None, title='Geofence Members', description='A list of user IDs allowed to access or operate within the job’s geofence.')
    users: list[int] | None = Field(None, title='Users', description='A list of user IDs assigned to the job.')

class TimeeroUpdateJobConfig(_Input):
    """Update Job using one documented API operation."""
    operation: Literal['update_job'] = Field('update_job', title='Update Job', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Job', "x-category": 'Jobs', "x-is-trigger": False})
    job_id: int = Field(..., title='Job Id', ge=1, strict=True)
    name: str = Field(..., title='Name', description='The name of the job.', min_length=1, max_length=4096)
    description: str | None = Field(None, title='Description', description='A brief description of the job.', min_length=1, max_length=4096)
    track_mileage: bool | None = Field(None, title='Track Mileage', description='Indicates whether mileage tracking is enabled for the job.', strict=True)
    require_geofence: bool | None = Field(None, title='Require Geofence', description='Indicates whether users must be within the geofence to perform job-related actions. All the fields are optional except street, city, state, zip_code and country are required when require_geofence is true or 1 and latitude and longitude are not provided.', strict=True)
    street: str | None = Field(None, title='Street', description='The street address of the job location.', min_length=1, max_length=4096)
    landmark: str | None = Field(None, title='Landmark', description='A nearby landmark to help identify the job location.', min_length=1, max_length=4096)
    state: str | None = Field(None, title='State', description='The state or region where the job is located.', min_length=1, max_length=4096)
    city: str | None = Field(None, title='City', description='The city where the job is located.', min_length=1, max_length=4096)
    zip_code: str | None = Field(None, title='Zip Code', description='The ZIP or postal code of the job location.', min_length=1, max_length=4096)
    country: str | None = Field(None, title='Country', description='The country where the job is located.', min_length=1, max_length=4096)
    latitude: str | None = Field(None, title='Latitude', description='The latitude coordinate of the job location.', min_length=1, max_length=4096)
    longitude: str | None = Field(None, title='Longitude', description='The longitude coordinate of the job location.', min_length=1, max_length=4096)
    radius: int | None = Field(None, title='Radius', description='The geofence radius around the job location, in meters.', ge=1, strict=True)
    contact_required: bool | None = Field(None, title='Contact Required', description='Indicates whether a contact person is required for the job (true = required, false = not required). contact_name, contact_phone, contact_mobile, and contact_email are required when contact_required is true.', strict=True)
    contact_name: str | None = Field(None, title='Contact Name', description='The name of the job contact person.', min_length=1, max_length=4096)
    contact_phone: str | None = Field(None, title='Contact Phone', description='The phone number of the job contact person.', min_length=1, max_length=4096)
    contact_mobile: str | None = Field(None, title='Contact Mobile', description='The mobile number of the job contact person.', min_length=1, max_length=4096)
    contact_email: str | None = Field(None, title='Contact Email', description='The email address of the job contact person.', min_length=1, max_length=4096)
    geofence_members: list[int] | None = Field(None, title='Geofence Members', description='A list of user IDs allowed to access or operate within the job’s geofence.')
    users: list[int] | None = Field(None, title='Users', description='A list of user IDs assigned to the job.')

class TimeeroListTasksConfig(_Input):
    """List Tasks using one documented API operation."""
    operation: Literal['list_tasks'] = Field('list_tasks', title='List Tasks', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Tasks', "x-category": 'Tasks', "x-is-trigger": False})
    page: int | None = Field(None, title='Page', description='Specifies which page of the paginated results to return, starting from page 1.', ge=1, strict=True)
    page_size: int | None = Field(None, title='Page Size', description='The number of items to include in each page of the response. Maximum items per page is 100.', ge=1, le=100, strict=True)
    jobId: int | None = Field(None, title='Job ID', description='Filter tasks by unique job ID.', ge=1, strict=True)
    task_status: bool | None = Field(None, title='Task Status', description='The field used to filter tasks by task status. true for Active and false for Inactive tasks.', strict=True)
    name: str | None = Field(None, title='Name', description='The name field used to filter tasks by task name', min_length=1, max_length=4096)

class TimeeroGetTaskConfig(_Input):
    """Get Task using one documented API operation."""
    operation: Literal['get_task'] = Field('get_task', title='Get Task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Task', "x-category": 'Tasks', "x-is-trigger": False})
    task_id: int = Field(..., title='Task Id', ge=1, strict=True)

class TimeeroCreateTaskConfig(_Input):
    """Create Task using one documented API operation."""
    operation: Literal['create_task'] = Field('create_task', title='Create Task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Task', "x-category": 'Tasks', "x-is-trigger": False})
    name: str = Field(..., title='Name', description='The name of the task.', min_length=1, max_length=4096)
    description: str | None = Field(None, title='Description', description='A brief description of the task.', min_length=1, max_length=4096)
    user_id: int = Field(..., title='User Id', description='The ID of the user with role Admin.', ge=1, strict=True)
    billable: bool | None = Field(None, title='Billable', description='Indicates whether the task is billable.', strict=True)
    billable_rate: float | None = Field(None, title='Billable Rate', description='The billing rate for the task. Set to 0 if the task is not billable.', strict=True)
    jobs: list[int] | None = Field(None, title='Jobs', description='A list of job IDs associated with the task.')

class TimeeroUpdateTaskConfig(_Input):
    """Update Task using one documented API operation."""
    operation: Literal['update_task'] = Field('update_task', title='Update Task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Task', "x-category": 'Tasks', "x-is-trigger": False})
    task_id: int = Field(..., title='Task Id', ge=1, strict=True)
    name: str = Field(..., title='Name', description='The name of the task.', min_length=1, max_length=4096)
    description: str | None = Field(None, title='Description', description='A brief description of the task.', min_length=1, max_length=4096)
    user_id: int = Field(..., title='User Id', description='The ID of the user with role Admin.', ge=1, strict=True)
    billable: bool | None = Field(None, title='Billable', description='Indicates whether the task is billable.', strict=True)
    billable_rate: float | None = Field(None, title='Billable Rate', description='The billing rate for the task. Set to 0 if the task is not billable.', strict=True)
    jobs: list[int] | None = Field(None, title='Jobs', description='A list of job IDs associated with the task')

class TimeeroListTimesheetsConfig(_Input):
    """List Timesheets using one documented API operation."""
    operation: Literal['list_timesheets'] = Field('list_timesheets', title='List Timesheets', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Timesheets', "x-category": 'Timesheets', "x-is-trigger": False})
    page: int | None = Field(None, title='Page', description='Specifies which page of the paginated results to return, starting from page 1.', ge=1, strict=True)
    page_size: int | None = Field(None, title='Page Size', description='The number of items to include in each page of the response. Maximum items per page is 100.', ge=1, le=100, strict=True)
    user_id: int | None = Field(None, title='User Id', description='The ID of the user associated with the timesheet entry.', ge=1, strict=True)
    group_id: int | None = Field(None, title='Group Id', description="The ID of the group associated with users. It fetches all the user's timesheet associated with the given group id.", ge=1, strict=True)
    date_range: str | None = Field(None, title='Date Range', description='Filter timesheets with in date range. value format for this field e.g `2025-07-18,2025-07-31`', min_length=1, max_length=4096)

class TimeeroGetTimesheetConfig(_Input):
    """Get Timesheet using one documented API operation."""
    operation: Literal['get_timesheet'] = Field('get_timesheet', title='Get Timesheet', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Timesheet', "x-category": 'Timesheets', "x-is-trigger": False})
    timesheet_id: int = Field(..., title='Timesheet Id', ge=1, strict=True)

class TimeeroCreateTimesheetConfig(_Input):
    """Create Timesheet using one documented API operation."""
    operation: Literal['create_timesheet'] = Field('create_timesheet', title='Create Timesheet', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create Timesheet', "x-category": 'Timesheets', "x-is-trigger": False})
    user_id: int = Field(..., title='User Id', description='The ID of the timesheet owner', ge=1, strict=True)
    start: datetime = Field(..., title='Start', description='The date and time when the user clocked in, in ISO 8601 format, e.g: YYYY-MM-DDTHH:MM:SS±HH:MM.', json_schema_extra={"format": "date-time"})
    end: datetime | None = Field(None, title='End', description='The date and time when the user clocked out, in ISO 8601 format: YYYY-MM-DDTHH:MM:SS±HH:MM. Set to null if the user is still clocked in.', json_schema_extra={"format": "date-time"})
    job_id: int | None = Field(None, title='Job Id', description='The ID of the job associated with the timesheet entry.', ge=1, strict=True)
    task_id: int | None = Field(None, title='Task Id', description='The ID of the task associated with the timesheet entry.', ge=1, strict=True)
    mileage: float | None = Field(None, title='Mileage', description='The distance(in miles) traveled during the timesheet period.', strict=True)
    clock_in_timezone: str | None = Field(None, title='Clock In Timezone', description="The timezone in which the clock-in time was recorded. The company's timezone will be used if none is provided. And it must match the offset when ISO 8601 offset is set.", min_length=1, max_length=4096)
    clock_out_timezone: str | None = Field(None, title='Clock Out Timezone', description="The timezone in which the clock-out time was recorded. Set to null if the user has not clocked out yet. The company's timezone will be used if none is provided. And it must match the ISO 8601 offset when set.", min_length=1, max_length=4096)
    notes: str | None = Field(None, title='Notes', description='Additional notes or comments for the timesheet entry.', min_length=1, max_length=4096)

class TimeeroUpdateTimesheetConfig(_Input):
    """Update Timesheet using one documented API operation."""
    operation: Literal['update_timesheet'] = Field('update_timesheet', title='Update Timesheet', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update Timesheet', "x-category": 'Timesheets', "x-is-trigger": False})
    timesheet_id: int = Field(..., title='Timesheet Id', ge=1, strict=True)
    user_id: int = Field(..., title='User Id', description='The ID of the timesheet owner.', ge=1, strict=True)
    start: datetime = Field(..., title='Start', description='The date and time when the user clocked in, in ISO 8601 format, e.g: YYYY-MM-DDTHH:MM:SS±HH:MM.', json_schema_extra={"format": "date-time"})
    end: datetime | None = Field(None, title='End', description='The date and time when the user clocked out, in ISO 8601 format: YYYY-MM-DDTHH:MM:SS±HH:MM. Set to null if the user is still clocked in.', json_schema_extra={"format": "date-time"})
    job_id: int | None = Field(None, title='Job Id', description='The ID of the job associated with the timesheet entry.', ge=1, strict=True)
    task_id: int | None = Field(None, title='Task Id', description='The ID of the task associated with the timesheet entry.', ge=1, strict=True)
    mileage: float | None = Field(None, title='Mileage', description='The distance(in miles) traveled during the timesheet period.', strict=True)
    clock_in_timezone: str | None = Field(None, title='Clock In Timezone', description="The timezone in which the clock-in time was recorded. The company's timezone will be used if none is provided. And it must match the offset when ISO 8601 offset is set.", min_length=1, max_length=4096)
    clock_out_timezone: str | None = Field(None, title='Clock Out Timezone', description="The timezone in which the clock-out time was recorded. Set to null if the user has not clocked out yet. The company's timezone will be used if none is provided. And it must match the ISO 8601 offset when set.", min_length=1, max_length=4096)
    notes: str | None = Field(None, title='Notes', description='Additional notes or comments for the timesheet entry.', min_length=1, max_length=4096)

class TimeeroApproveTimesheetsConfig(_Input):
    """Approve Timesheets using one documented API operation."""
    operation: Literal['approve_timesheets'] = Field('approve_timesheets', title='Approve Timesheets', json_schema_extra={"ui:hidden": True, "x-display-name": 'Approve Timesheets', "x-category": 'Timesheets', "x-is-trigger": False})
    ids: list[int] = Field(..., title='Ids', description='An array of timesheet IDs that should be approved in a single request.', min_length=1, max_length=100)
    mute_notification: bool | None = Field(None, title='Mute Notification', description='Indicates whether approval notifications should be muted for this action. When set to true, approval notifications will not be sent to users. If false or omitted, users will receive a notification after their timesheets are approved.', strict=True)

class TimeeroClockInConfig(_Input):
    """Clock In using one documented API operation."""
    operation: Literal['clock_in'] = Field('clock_in', title='Clock In', json_schema_extra={"ui:hidden": True, "x-display-name": 'Clock In', "x-category": 'Timesheets', "x-is-trigger": False})
    user_id: int = Field(..., title='User Id', description='The unique ID of the user who is clocking in.', ge=1, strict=True)
    job_id: str | None = Field(None, title='Job Id', description='The ID of the job or project the user is clocking in for. this is required based on company settings.', min_length=1, max_length=4096)
    task_id: str | None = Field(None, title='Task Id', description='The specific task ID under the job. If not applicable, this value can be set to null. this is required based on company settings.', min_length=1, max_length=4096)
    clock_in_time: datetime | None = Field(None, title='Clock In Time', description='The exact date and time when the user clocked in. This should be provided in ISO 8601 format, e.g YYYY-MM-DDTHH:MM:SS±HH:MM.', json_schema_extra={"format": "date-time"})
    timezone: str | None = Field(None, title='Timezone', description='The user’s local timezone at the time of clock-in, formatted as an IANA timezone identifier.', min_length=1, max_length=4096)
    latitude: float | None = Field(None, title='Latitude', description='The latitude coordinate where the user clocked in. Used for location tracking and geofencing validation.', ge=-90, le=90, strict=True)
    longitude: float | None = Field(None, title='Longitude', description='The longitude coordinate where the user clocked in. Used for location tracking and geofencing validation.', ge=-180, le=180, strict=True)

class TimeeroClockOutConfig(_Input):
    """Clock Out using one documented API operation."""
    operation: Literal['clock_out'] = Field('clock_out', title='Clock Out', json_schema_extra={"ui:hidden": True, "x-display-name": 'Clock Out', "x-category": 'Timesheets', "x-is-trigger": False})
    user_id: int = Field(..., title='User Id', description='The unique ID of the user who is clocking out.', ge=1, strict=True)
    clock_out_time: str = Field(..., title='Clock Out Time', description='The exact date and time when the user clocked out. Must be later than the corresponding clock-in time and formatted in ISO 8601.  e.g YYYY-MM-DDTHH:MM:SS±HH:MM.', min_length=1, max_length=4096)
    timezone: str | None = Field(None, title='Timezone', description='The user’s local timezone at the moment of clock-out, provided as an IANA timezone identifier.', min_length=1, max_length=4096)
    latitude: str | None = Field(None, title='Latitude', description='The latitude coordinate where the user clocked out. Used for location verification and geofence enforcement.', min_length=1, max_length=4096)
    longitude: str | None = Field(None, title='Longitude', description='The longitude coordinate where the user clocked out. Used for location verification and geofence enforcement.', min_length=1, max_length=4096)

class TimeeroListSchedulesConfig(_Input):
    """List Schedules using one documented API operation."""
    operation: Literal['list_schedules'] = Field('list_schedules', title='List Schedules', json_schema_extra={"ui:hidden": True, "x-display-name": 'List Schedules', "x-category": 'Schedules', "x-is-trigger": False})
    date_range: str = Field(..., title='Date Range', description='Filter schedules with in date range. value format for this field e.g `2025-07-18,2025-07-31`', min_length=1, max_length=4096)
    job_id: int | None = Field(None, title='Job Id', description='The ID of the job associated with the schedules.', ge=1, strict=True)
    status: Literal['draft', 'published'] | None = Field(None, title='Status', description='The status of schedules. values are `draft` or `published`')
    employee_id: int | None = Field(None, title='Employee Id', description='The ID of the user for whom the schedule is being created.', ge=1, strict=True)

class TimeeroGetScheduleConfig(_Input):
    """Get Schedule using one documented API operation."""
    operation: Literal['get_schedule'] = Field('get_schedule', title='Get Schedule', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Schedule', "x-category": 'Schedules', "x-is-trigger": False})
    schedule_id: int = Field(..., title='Schedule Id', ge=1, strict=True)


ROUTES = {'list_users': ('GET',
                '/api/public/users',
                ('page', 'per_page', 'sort', 'search', 'role', 'group_id', 'active')),
 'get_user': ('GET', '/api/public/users/{id}', ()),
 'list_groups': ('GET', '/api/public/groups', ('page', 'per_page', 'sort', 'name')),
 'list_jobs': ('GET', '/api/public/jobs', ('page', 'page_size', 'sort', 'job_status', 'name')),
 'get_job': ('GET', '/api/public/jobs/{id}', ()),
 'create_job': ('POST', '/api/public/jobs', ()),
 'update_job': ('PUT', '/api/public/jobs/{id}', ()),
 'list_tasks': ('GET', '/api/public/tasks', ('page', 'page_size', 'jobId', 'task_status', 'name')),
 'get_task': ('GET', '/api/public/tasks/{id}', ()),
 'create_task': ('POST', '/api/public/tasks', ()),
 'update_task': ('PUT', '/api/public/tasks/{id}', ()),
 'list_timesheets': ('GET',
                     '/api/public/timesheets',
                     ('page', 'page_size', 'user_id', 'group_id', 'date_range')),
 'get_timesheet': ('GET', '/api/public/timesheets/{id}', ()),
 'create_timesheet': ('POST', '/api/public/timesheets', ()),
 'update_timesheet': ('PUT', '/api/public/timesheets/{id}', ()),
 'approve_timesheets': ('POST', '/api/public/timesheets/approve', ()),
 'clock_in': ('POST', '/api/public/timesheets/clock-in', ()),
 'clock_out': ('POST', '/api/public/timesheets/clock-out', ()),
 'list_schedules': ('GET', '/api/public/schedules', ('date_range', 'job_id', 'status', 'employee_id')),
 'get_schedule': ('GET', '/api/public/schedules/{id}', ())}

TRIGGERS = {'on_clock_in': ('Clock In', 'clockin', 'clockin_created', 'timesheets'), 'on_clock_out': ('Clock Out', 'clockout', 'clockout_updated', 'timesheets'), 'on_new_job': ('New Job', 'jobs', 'jobs_created', 'jobs'), 'on_new_task': ('New Task', 'tasks', 'tasks_created', 'tasks'), 'on_new_schedule': ('New Schedule', 'schedules', 'schedules_created', 'schedules')}


class TimeeroOnClockInConfig(WebhookTriggerConfigBase):
    """Receive a documented clock in notification."""
    operation: Literal['on_clock_in'] = Field('on_clock_in', title='Clock In', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'Clock In'})
    replace_existing_subscription: bool = Field(False, title="Replace Company Webhook", description="Enable to use this workflow as Timeero’s single company webhook receiver, replacing any existing configuration.")
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Timeero has one company webhook configuration. Activating this trigger replaces it; use one Timeero trigger per company. Only matching events start this workflow.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class TimeeroOnClockOutConfig(WebhookTriggerConfigBase):
    """Receive a documented clock out notification."""
    operation: Literal['on_clock_out'] = Field('on_clock_out', title='Clock Out', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'Clock Out'})
    replace_existing_subscription: bool = Field(False, title="Replace Company Webhook", description="Enable to use this workflow as Timeero’s single company webhook receiver, replacing any existing configuration.")
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Timeero has one company webhook configuration. Activating this trigger replaces it; use one Timeero trigger per company. Only matching events start this workflow.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class TimeeroOnNewJobConfig(WebhookTriggerConfigBase):
    """Receive a documented new job notification."""
    operation: Literal['on_new_job'] = Field('on_new_job', title='New Job', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'New Job'})
    replace_existing_subscription: bool = Field(False, title="Replace Company Webhook", description="Enable to use this workflow as Timeero’s single company webhook receiver, replacing any existing configuration.")
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Timeero has one company webhook configuration. Activating this trigger replaces it; use one Timeero trigger per company. Only matching events start this workflow.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class TimeeroOnNewTaskConfig(WebhookTriggerConfigBase):
    """Receive a documented new task notification."""
    operation: Literal['on_new_task'] = Field('on_new_task', title='New Task', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'New Task'})
    replace_existing_subscription: bool = Field(False, title="Replace Company Webhook", description="Enable to use this workflow as Timeero’s single company webhook receiver, replacing any existing configuration.")
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Timeero has one company webhook configuration. Activating this trigger replaces it; use one Timeero trigger per company. Only matching events start this workflow.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class TimeeroOnNewScheduleConfig(WebhookTriggerConfigBase):
    """Receive a documented new schedule notification."""
    operation: Literal['on_new_schedule'] = Field('on_new_schedule', title='New Schedule', json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": 'New Schedule'})
    replace_existing_subscription: bool = Field(False, title="Replace Company Webhook", description="Enable to use this workflow as Timeero’s single company webhook receiver, replacing any existing configuration.")
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Timeero has one company webhook configuration. Activating this trigger replaces it; use one Timeero trigger per company. Only matching events start this workflow.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


TimeeroConfig = Annotated[Union[TimeeroListUsersConfig, TimeeroGetUserConfig, TimeeroListGroupsConfig, TimeeroListJobsConfig, TimeeroGetJobConfig, TimeeroCreateJobConfig, TimeeroUpdateJobConfig, TimeeroListTasksConfig, TimeeroGetTaskConfig, TimeeroCreateTaskConfig, TimeeroUpdateTaskConfig, TimeeroListTimesheetsConfig, TimeeroGetTimesheetConfig, TimeeroCreateTimesheetConfig, TimeeroUpdateTimesheetConfig, TimeeroApproveTimesheetsConfig, TimeeroClockInConfig, TimeeroClockOutConfig, TimeeroListSchedulesConfig, TimeeroGetScheduleConfig, TimeeroOnClockInConfig, TimeeroOnClockOutConfig, TimeeroOnNewJobConfig, TimeeroOnNewTaskConfig, TimeeroOnNewScheduleConfig], Field(discriminator="operation")]


class TimeeroNodeConfig(NodeConfig[TimeeroConfig, TimeeroAPIKeyCredential]):
    pass


class TimeeroNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-timeero"
    connection_evidence = ConnectionEvidence(operation="list_users", noun="employees")

    @classmethod
    def get_config_model(cls):
        return TimeeroNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        key = TimeeroAPIKeyCredential.model_validate(credential).api_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": key, "Accept": "application/json"})
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"Timeero returned HTTP {response.status_code} without JSON") from None
        if response.is_error or response.is_redirect or not isinstance(data, dict):
            detail = data.get("message") if isinstance(data, dict) else None
            raise ValueError(f"Timeero HTTP {response.status_code}: {detail or 'Unexpected API response'}")
        if ("status" in data and data["status"] is False) or ("error_code" in data and data["error_code"]):
            raise ValueError(str(data.get("message") or "Timeero rejected the request"))
        return data

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        if (config or {}).get("operation") not in TRIGGERS:
            raise ValueError("Choose a Timeero trigger before activation")
        if (config or {}).get("replace_existing_subscription") is not True:
            raise ValueError("Enable Replace Company Webhook to use this workflow as Timeero’s single receiver")
        secret = secrets.token_hex(32)
        # The provider’s published request example sends an array (the schema
        # incorrectly declares string). The wildcard also includes clock events.
        result = await cls._request(credential, "POST", "/webhooks/subscription/subscribe",
            body={"url": webhook_url, "signature_secret_key": secret, "active": True, "events": ["*"]})
        subscription = result.get("payload")
        if not isinstance(subscription, dict) or not subscription.get("id"):
            raise ValueError("Timeero did not return a webhook subscription ID")
        return {"external_webhook_id": str(subscription["id"]), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not (config or {}).get("external_webhook_id"):
            return
        # A company has one subscription: never remove a receiver that was
        # subsequently replaced in Timeero or by another workflow.
        data = await cls._request(credential, "GET", "/api/public/webhooks/subscription/list")
        payload = data.get("payload")
        current = payload.get("subscription") if isinstance(payload, dict) else None
        if current is None:
            return
        if not isinstance(current, dict):
            raise ValueError("Timeero returned an invalid webhook subscription")
        if (str(current.get("id")) == str(config["external_webhook_id"])
                and current.get("url") == config.get("webhook_url")
                and current.get("signature_secret_key") == config.get("signing_secret")):
            await cls._request(credential, "DELETE", "/webhooks/subscription/unsubscribe")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"replace_existing_subscription": (config or {}).get("replace_existing_subscription", False)}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        if not isinstance(secret, str) or not secret:
            return False
        normalized = {k.lower(): v for k, v in (headers or {}).items()}
        # The guide's header section uses x-webhook-*. Its PHP example also
        # documents x-timestamp / x-signature; require a complete matching pair.
        for timestamp_key, signature_key in (("x-webhook-timestamp", "x-webhook-signature"), ("x-timestamp", "x-signature")):
            timestamp, signature = normalized.get(timestamp_key, ""), normalized.get(signature_key, "")
            if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,20}", timestamp):
                continue
            if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature):
                continue
            expected = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, signature):
                return True
        return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        expected = TRIGGERS.get((config or {}).get("operation"))
        if not expected or not isinstance(payload, dict):
            return False
        envelope = payload.get("payload")
        if not isinstance(envelope, dict):
            return False
        data = envelope.get("data")
        return (envelope.get("event") == expected[1] and isinstance(data, dict)
                and data.get("operation") == expected[2]
                and type(data.get("id")) is int and data["id"] > 0)

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        # Hydrate the documented notification's ID so an agent hears the
        # employee, job or schedule details instead of an opaque ID alone.
        return None

    async def execute(self, inputs):
        if not isinstance(self.config, TimeeroNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Timeero API key")
        config = self.config.config
        operation = config.operation
        credential = self.config.credentials.model_dump()
        if operation in TRIGGERS:
            event = self.node_data.get("config", {}).get("_triggerPayload") or inputs
            if not self.filter_trigger_payload(event, {"operation": operation}):
                return {"status": "skipped", "operation": operation}
            resource_type = TRIGGERS[operation][3]
            identifier = event["payload"]["data"]["id"]
            response = await self._request(credential, "GET", f"/api/public/{resource_type}/{identifier}")
            resource = response.get("items")
            if not isinstance(resource, dict):
                raise ValueError("Timeero did not return the event's resource")
            return {"status": "success", "operation": operation, "event": event["payload"], "resource": resource}
        method, path, query = ROUTES[operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            id_field = path.split("/")[3][:-1] + "_id"
            path = path.replace("{id}", str(values.pop(id_field)))
        params = {name: values.pop(name) for name in query if name in values}
        data = await self._request(credential, method, path, params=params or None,
                                   body=values if method in {"POST", "PUT"} else None)
        if "items" not in data:
            raise ValueError("Timeero returned an unexpected resource response")
        return {"status": "success", "operation": operation, "data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in TRIGGERS or output.get("status") != "success":
            return None
        operation = output["operation"]
        label, _, _, kind = TRIGGERS[operation]
        event, record = output["event"], output["resource"]
        identifier = event["data"]["id"]
        lines = [f"Timeero: {label} (notification for {kind} ID {identifier})."]
        if kind == "timesheets":
            name = " ".join(str(record.get(k) or "") for k in ("first_name", "last_name")).strip()
            lines += [f"Employee: {name or 'Unknown'} (user_id={record.get('user_id')}).",
                      f"Job: {record.get('job_name')} (job_id={record.get('job_id')}).",
                      f"Clock in: {record.get('clock_in_time')}; clock out: {record.get('clock_out_time')}.",
                      f"Notes: {record.get('notes') or ''}", f"To act: get_timesheet or update_timesheet with timesheet_id={identifier}."]
        elif kind == "schedules":
            lines += [f"Schedule: {record.get('title')}; assigned by {record.get('assign_by')}.",
                      f"Employees: {record.get('user_ids')}; job: {record.get('job_name')} (job_id={record.get('job_id')}).",
                      f"When: {record.get('start_date')} to {record.get('end_date')}.",
                      f"Description: {record.get('description') or ''}", f"To act: get_schedule with schedule_id={identifier}."]
        else:
            singular = kind[:-1]
            lines += [f"{singular.title()}: {record.get('name')}.", f"Description: {record.get('description') or ''}",
                      f"To act: get_{singular} or update_{singular} with {singular}_id={identifier}."]
        lines += [f"Event timestamp: {event['data'].get('last_updated_at')}. Latest resource details are shown above."]
        return {"text": "\n".join(lines), "conversation_key": f"timeero:{kind}:{identifier}", "title": f"Timeero {label}"}
