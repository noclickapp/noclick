"""Exercise.com Modern API (2026-05-20): one published endpoint per operation.

Personal API tokens are issued in Exercise.com and pasted by the account owner.
Collections return one cursor page; no automatic replay of writes or redirects.
Contract: https://train.demoexercise.com/api-docs/modern/swagger.yaml
"""
from __future__ import annotations

import json
from datetime import date as Date
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ExercisecomTokenCredential(BaseModel):
    model_config = ConfigDict(title="Exercise.com Personal API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://train.demoexercise.com/api-docs/modern/swagger.yaml",
            "x-credential-instructions": "Create a Personal API Token in Exercise.com and paste it here. It acts as the platform owner, so use only an account authorized for these operations. Choose your API host; the published contract also exposes the demo and staging hosts. Connection checks list staff tasks and require task access. NoClick does not request your password or create a session.",
        })
    credential_type: Literal["exercisecom_token"] = Field("exercisecom_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="Personal API token", json_schema_extra={"ui:widget": "password"})
    api_host: Literal["api.exercise.com", "train.demoexercise.com", "api.staging.exercise.com"] = Field("api.exercise.com", title="API host")

    @field_validator("api_token", mode="before")
    @classmethod
    def valid_token(cls, value):
        value = clean_secret(value, field_name="Personal API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the token alone, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

    @model_validator(mode="after")
    def compatible_filters(self):
        if getattr(self, "after", None) and getattr(self, "before", None):
            raise ValueError("Use only one cursor direction")
        if getattr(self, "all_members", False) and getattr(self, "user_id", None) is not None:
            raise ValueError("Choose either a user or all members")
        start = getattr(self, "start_date", None) or getattr(self, "from_time", None)
        end = getattr(self, "end_date", None) or getattr(self, "to_time", None)
        if start is not None and end is not None and end < start:
            raise ValueError("End must not precede start")
        if self.operation == "list_calendar" and (end - start).days > 100:
            raise ValueError("Calendar ranges may span at most 100 days")
        return self

    @model_validator(mode="before")
    @classmethod
    def no_invalid_null_writes(cls, value):
        if isinstance(value, dict):
            operation = value.get("operation", cls.model_fields.get("operation").default if "operation" in cls.model_fields else None)
            nonnull = {"create_task": ("status", "due_at", "assigned_to_id", "title"),
                       "update_task": ("status", "due_at", "assigned_to_id", "title"),
                       "update_user": ("privacy_level", "profile_fields")}.get(operation, ())
            if any(key in value and value[key] is None for key in nonnull):
                raise ValueError("This Exercise.com field does not accept null")
        return value


class ExercisecomListCalendarConfig(_Input):
    'List calendar items'
    operation: Literal['list_calendar'] = Field('list_calendar', json_schema_extra={"ui:hidden": True})
    start_date: Date = Field(..., description='Inclusive first calendar date (YYYY-MM-DD).')
    end_date: Date = Field(..., description='Inclusive last calendar date, at most 100 days after start_date.')
    types: Optional[Literal['workout', 'logged_workout']] = Field(None, description='Filter to one item type. Omit for all supported types.')


class ExercisecomScheduleWorkoutConfig(_Input):
    'Add a workout to the member calendar'
    operation: Literal['schedule_workout'] = Field('schedule_workout', json_schema_extra={"ui:hidden": True})
    workout_id: int = Field(..., ge=1, description='Source PlanWorkout id.')
    date: Date = Field(..., description='Target calendar date (YYYY-MM-DD); may be in the past.')


class ExercisecomMoveWorkoutConfig(_Input):
    'Move a scheduled workout'
    operation: Literal['move_workout'] = Field('move_workout', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='Scheduled PlanWorkout id, not a logged Workout id.')
    date: Date = Field(..., description='Target calendar date (YYYY-MM-DD); may be in the past.')


class ExercisecomRemoveWorkoutConfig(_Input):
    'Remove a scheduled workout'
    operation: Literal['remove_workout'] = Field('remove_workout', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='Scheduled PlanWorkout id, not a logged Workout id.')


class ExercisecomListPackagesConfig(_Input):
    'List packages'
    operation: Literal['list_packages'] = Field('list_packages', json_schema_extra={"ui:hidden": True})
    public: Optional[bool] = Field(None, description='Filter by public catalog visibility. Defaults to true for members.')
    available: Optional[bool] = Field(None, description='Staff only. When true, limit to packages whose enrollment window includes today (platform time zone). Ignored for members, who always receive the currently enrollable catalog.')
    location_id: Optional[int] = Field(None, ge=1, description="Include packages assigned to this location or with no location (platform-wide). Must belong to the current platform; unknown ids are ignored. Pricing uses this location, or the caller's location when omitted.")
    sort: Optional[str] = Field(None, max_length=4096, description='Sortable fields: created_at, name, updated_at, id. Use comma-separated field:asc or field:desc pairs.')
    limit: Optional[int] = Field(25, ge=1, le=100, description='Page size, from 1 through 100. Defaults to 25.')
    after: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the next page. Mutually exclusive with before.')
    before: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the previous page. Mutually exclusive with after.')


class ExercisecomListUserPackagesConfig(_Input):
    'List user packages'
    operation: Literal['list_user_packages'] = Field('list_user_packages', json_schema_extra={"ui:hidden": True})
    user_id: Optional[int] = Field(None, ge=1, description='Authorized member whose user packages should be returned. Defaults to the bearer. Members who are not on the current platform return 404.')
    status: Optional[str] = Field(None, max_length=4096, description='Lifecycle status filter: not_started, current, hold, drop_pending, dropped, completed.')
    payment_type: Optional[str] = Field(None, max_length=4096, description='Payment type filter: subscription, single_purchase, free. Comma-separated values are allowed.')
    package_id: Optional[int] = Field(None, ge=1)
    subscription_id: Optional[int] = Field(None, ge=1)
    sort: Optional[str] = Field(None, max_length=4096, description='Sortable fields: created_at, activation_date, expires_on, id. Use comma-separated field:asc or field:desc pairs.')
    limit: Optional[int] = Field(25, ge=1, le=100, description='Page size, from 1 through 100. Default 25.')
    after: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the next page.')
    before: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the previous page.')


class ExercisecomListInvoicesConfig(_Input):
    'List invoices'
    operation: Literal['list_invoices'] = Field('list_invoices', json_schema_extra={"ui:hidden": True})
    user_id: Optional[int] = Field(None, ge=1, description='Authorized member whose invoices should be returned. Defaults to the authenticated user.')
    status: Optional[str] = Field(None, max_length=4096, description='Comma-separated invoice statuses: draft, open, paid, uncollectible, void.')
    overdue: Optional[bool] = Field(None, description='True returns only overdue invoices; false returns only invoices that are not overdue.')
    sort: Optional[str] = Field(None, max_length=4096, description='Sortable fields: created_at. Use comma-separated field:asc or field:desc pairs. Defaults to created_at:desc.')
    limit: Optional[int] = Field(25, ge=1, le=100, description='Page size, from 1 through 100.')
    after: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the next page.')
    before: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the previous page.')


class ExercisecomListVisitsConfig(_Input):
    'List visits'
    operation: Literal['list_visits'] = Field('list_visits', json_schema_extra={"ui:hidden": True})
    user_id: Optional[int] = Field(None, ge=1, description='Authorized member whose visits should be returned. Defaults to the authenticated user. Cannot be combined with all_members.')
    all_members: Optional[bool] = Field(None, description='When true, list visits across members visible to the authenticated user instead of a single member. Cannot be combined with user_id.')
    state: Optional[str] = Field(None, max_length=4096, description='Comma-separated states: reserved, registered, checked_in, completed, canceled, late_canceled, no_show.')
    attendance_type: Optional[str] = Field(None, max_length=4096, description='Comma-separated attendance types: visit, class, session.')
    appointment_id: Optional[str] = Field(None, max_length=4096, description='Comma-separated appointment ids. Returns visits for those appointments within the caller access scope.')
    from_time: Optional[AwareDatetime] = Field(None, alias='from', description='Inclusive ISO-8601 lower bound for the attendance time.')
    to_time: Optional[AwareDatetime] = Field(None, alias='to', description='Inclusive ISO-8601 upper bound for the attendance time.')
    limit: Optional[int] = Field(25, ge=1, le=100, description='Page size, from 1 through 100.')
    after: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the next page.')
    before: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the previous page.')


class ExercisecomGetVisitSummaryConfig(_Input):
    'Show visit summary'
    operation: Literal['get_visit_summary'] = Field('get_visit_summary', json_schema_extra={"ui:hidden": True})
    user_id: Optional[int] = Field(None, ge=1, description='User to summarize. Defaults to the authenticated user.')
    start_date: AwareDatetime = Field(..., description='Inclusive window start as an ISO-8601 instant.')
    end_date: AwareDatetime = Field(..., description='Inclusive window end as an ISO-8601 instant.')
    statuses: Optional[str] = Field(None, max_length=4096, description='Comma-separated visit statuses. Default: completed. Allowed: reserved, registered, completed, noshowed, late_cancelled, cancelled, cancel_or_late_cancel.')
    types: Optional[str] = Field(None, max_length=4096, description='Comma-separated categories. Default: visit,class,session.')


class ExercisecomGetVisitTotalsConfig(_Input):
    'Show visit totals'
    operation: Literal['get_visit_totals'] = Field('get_visit_totals', json_schema_extra={"ui:hidden": True})
    user_id: Optional[int] = Field(None, ge=1, description='User to total. Defaults to the authenticated user.')


class ExercisecomGetConversationSummaryConfig(_Input):
    'Get unread conversation count and messaging availability'
    operation: Literal['get_conversation_summary'] = Field('get_conversation_summary', json_schema_extra={"ui:hidden": True})


class ExercisecomGetUserConfig(_Input):
    'Show user profile'
    operation: Literal['get_user'] = Field('get_user', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='User ID')


class ExercisecomUpdateUserConfig(_Input):
    'Update user profile'
    operation: Literal['update_user'] = Field('update_user', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='User ID')
    first_name: Optional[str] = Field(None, max_length=4096)
    last_name: Optional[str] = Field(None, max_length=4096)
    nickname: Optional[str] = Field(None, max_length=4096)
    gender: Optional[Literal['male', 'female', 'other', 'prefer_not_to_say']] = Field(None)
    birthdate: Optional[Date] = Field(None)
    phone_number: Optional[str] = Field(None, max_length=4096)
    street_address: Optional[str] = Field(None, max_length=4096)
    city: Optional[str] = Field(None, max_length=4096)
    state: Optional[str] = Field(None, max_length=4096)
    zip_code: Optional[str] = Field(None, max_length=4096)
    country_address: Optional[str] = Field(None, max_length=4096)
    about_me: Optional[str] = Field(None, max_length=4096)
    height: Optional[float] = Field(None, allow_inf_nan=False)
    height_metric: Optional[Literal['cm', 'in']] = Field(None)
    weight: Optional[float] = Field(None, allow_inf_nan=False)
    weight_metric: Optional[Literal['kg', 'lb']] = Field(None)
    uses_metric: Optional[bool] = Field(None)
    time_zone: Optional[str] = Field(None, max_length=4096)
    privacy_level: Optional[Literal[0, 1]] = Field(None)
    profile_fields: Optional[list[dict]] = Field(None)

    @model_validator(mode="after")
    def nonempty_update(self):
        if not (self.model_fields_set - {"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class ExercisecomListTasksConfig(_Input):
    'List staff tasks'
    operation: Literal['list_tasks'] = Field('list_tasks', json_schema_extra={"ui:hidden": True})
    assigned_to_id: Optional[int] = Field(None, ge=1)
    assigned_to_ids: Optional[str] = Field(None, max_length=4096, description='Comma-separated assignee user ids')
    status: Optional[str] = Field(None, max_length=4096, description='open, complete, or overdue')
    start_date: Optional[AwareDatetime] = Field(None)
    end_date: Optional[AwareDatetime] = Field(None)
    regarding_type: Optional[str] = Field(None, max_length=4096)
    regarding_id: Optional[int] = Field(None, ge=1)
    sort: Optional[str] = Field(None, max_length=4096, description='Sortable fields: title, status, created_at, updated_at, due_at, completed_at, id. Use comma-separated field:asc or field:desc pairs.')
    limit: Optional[int] = Field(25, ge=1, le=100, description='Page size, from 1 through 100.')
    after: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the next page.')
    before: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the previous page.')


class ExercisecomCreateTaskConfig(_Input):
    'Create staff task'
    operation: Literal['create_task'] = Field('create_task', json_schema_extra={"ui:hidden": True})
    title: str = Field(..., max_length=4096)
    description: Optional[str] = Field(None, max_length=4096)
    status: Optional[Literal['open', 'in_progress', 'complete', 'blocked']] = Field(None)
    category: Optional[str] = Field(None, max_length=4096)
    due_at: AwareDatetime = Field(..., description='ISO-8601 due time')
    assigned_to_id: int = Field(..., ge=1)
    regarding_type: Optional[Literal['ClientAssociation', 'User']] = Field(None)
    regarding_id: Optional[int] = Field(None, ge=1)
    regarding_member_id: Optional[int] = Field(None, ge=1, description='ClientAssociation id')
    regarding_staff_id: Optional[int] = Field(None, ge=1, description='Staff User id')


class ExercisecomGetTaskConfig(_Input):
    'Show staff task'
    operation: Literal['get_task'] = Field('get_task', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='Staff task id')


class ExercisecomUpdateTaskConfig(_Input):
    'Update staff task (partial)'
    operation: Literal['update_task'] = Field('update_task', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='Staff task id')
    title: Optional[str] = Field(None, max_length=4096)
    description: Optional[str] = Field(None, max_length=4096)
    status: Optional[Literal['open', 'in_progress', 'complete', 'blocked']] = Field(None)
    category: Optional[str] = Field(None, max_length=4096)
    due_at: Optional[AwareDatetime] = Field(None, description='ISO-8601 due time')
    assigned_to_id: Optional[int] = Field(None, ge=1)
    regarding_type: Optional[Literal['ClientAssociation', 'User']] = Field(None)
    regarding_id: Optional[int] = Field(None, ge=1)
    regarding_member_id: Optional[int] = Field(None, ge=1, description='ClientAssociation id')
    regarding_staff_id: Optional[int] = Field(None, ge=1, description='Staff User id')

    @model_validator(mode="after")
    def nonempty_update(self):
        if not (self.model_fields_set - {"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class ExercisecomDeleteTaskConfig(_Input):
    'Delete staff task'
    operation: Literal['delete_task'] = Field('delete_task', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='Staff task id')


class ExercisecomListAssigneesConfig(_Input):
    'List staff who can be assigned a task'
    operation: Literal['list_assignees'] = Field('list_assignees', json_schema_extra={"ui:hidden": True})
    limit: Optional[int] = Field(25, ge=1, le=100, description='Page size, from 1 through 100.')
    after: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the next page.')
    before: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the previous page.')


class ExercisecomListTaskAuditLogsConfig(_Input):
    'List staff task audit logs'
    operation: Literal['list_task_audit_logs'] = Field('list_task_audit_logs', json_schema_extra={"ui:hidden": True})
    task_id: Optional[int] = Field(None, ge=1)
    search: Optional[str] = Field(None, max_length=4096, description='Filter by task title (partial match)')
    event_type: Optional[str] = Field(None, max_length=4096)
    actor_id: Optional[int] = Field(None, ge=1)
    sort: Optional[str] = Field(None, max_length=4096, description='Sortable fields: occurred_at, task_title, event_type, id. Use comma-separated field:asc or field:desc pairs.')
    actor_ids: Optional[str] = Field(None, max_length=4096, description='Comma-separated actor ids; use system for automation')
    start_date: Optional[AwareDatetime] = Field(None)
    end_date: Optional[AwareDatetime] = Field(None)
    limit: Optional[int] = Field(25, ge=1, le=100, description='Page size, from 1 through 100.')
    after: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the next page.')
    before: Optional[str] = Field(None, max_length=4096, description='Opaque cursor for the previous page.')


ExercisecomOperation = Annotated[Union[
    ExercisecomListCalendarConfig,
    ExercisecomScheduleWorkoutConfig,
    ExercisecomMoveWorkoutConfig,
    ExercisecomRemoveWorkoutConfig,
    ExercisecomListPackagesConfig,
    ExercisecomListUserPackagesConfig,
    ExercisecomListInvoicesConfig,
    ExercisecomListVisitsConfig,
    ExercisecomGetVisitSummaryConfig,
    ExercisecomGetVisitTotalsConfig,
    ExercisecomGetConversationSummaryConfig,
    ExercisecomGetUserConfig,
    ExercisecomUpdateUserConfig,
    ExercisecomListTasksConfig,
    ExercisecomCreateTaskConfig,
    ExercisecomGetTaskConfig,
    ExercisecomUpdateTaskConfig,
    ExercisecomDeleteTaskConfig,
    ExercisecomListAssigneesConfig,
    ExercisecomListTaskAuditLogsConfig
], Field(discriminator="operation")]


class ExercisecomConfig(NodeConfig[ExercisecomOperation, ExercisecomTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'list_calendar': ('GET', '/calendar', ['start_date', 'end_date', 'types'], [], None),
 'schedule_workout': ('POST', '/calendar/workouts', [], ['workout_id', 'date'], None),
 'move_workout': ('PATCH', '/calendar/workouts/{id}', [], ['date'], None),
 'remove_workout': ('DELETE', '/calendar/workouts/{id}', [], [], None),
 'list_packages': ('GET',
                   '/packages',
                   ['public', 'available', 'location_id', 'sort', 'limit', 'after', 'before'],
                   [],
                   None),
 'list_user_packages': ('GET',
                        '/user_packages',
                        ['user_id',
                         'status',
                         'payment_type',
                         'package_id',
                         'subscription_id',
                         'sort',
                         'limit',
                         'after',
                         'before'],
                        [],
                        None),
 'list_invoices': ('GET',
                   '/invoices',
                   ['user_id', 'status', 'overdue', 'sort', 'limit', 'after', 'before'],
                   [],
                   None),
 'list_visits': ('GET',
                 '/visits',
                 ['user_id',
                  'all_members',
                  'state',
                  'attendance_type',
                  'appointment_id',
                  'from',
                  'to',
                  'limit',
                  'after',
                  'before'],
                 [],
                 None),
 'get_visit_summary': ('GET',
                       '/visit_summary',
                       ['user_id', 'start_date', 'end_date', 'statuses', 'types'],
                       [],
                       None),
 'get_visit_totals': ('GET', '/visit_totals', ['user_id'], [], None),
 'get_conversation_summary': ('GET', '/conversations/summary', [], [], None),
 'get_user': ('GET', '/users/{id}', [], [], None),
 'update_user': ('PATCH',
                 '/users/{id}',
                 [],
                 ['first_name',
                  'last_name',
                  'nickname',
                  'gender',
                  'birthdate',
                  'phone_number',
                  'street_address',
                  'city',
                  'state',
                  'zip_code',
                  'country_address',
                  'about_me',
                  'height',
                  'height_metric',
                  'weight',
                  'weight_metric',
                  'uses_metric',
                  'time_zone',
                  'privacy_level',
                  'profile_fields'],
                 None),
 'list_tasks': ('GET',
                '/staff/tasks',
                ['assigned_to_id',
                 'assigned_to_ids',
                 'status',
                 'start_date',
                 'end_date',
                 'regarding_type',
                 'regarding_id',
                 'sort',
                 'limit',
                 'after',
                 'before'],
                [],
                None),
 'create_task': ('POST',
                 '/staff/tasks',
                 [],
                 ['title',
                  'description',
                  'status',
                  'category',
                  'due_at',
                  'assigned_to_id',
                  'regarding_type',
                  'regarding_id',
                  'regarding_member_id',
                  'regarding_staff_id'],
                 'task'),
 'get_task': ('GET', '/staff/tasks/{id}', [], [], None),
 'update_task': ('PATCH',
                 '/staff/tasks/{id}',
                 [],
                 ['title',
                  'description',
                  'status',
                  'category',
                  'due_at',
                  'assigned_to_id',
                  'regarding_type',
                  'regarding_id',
                  'regarding_member_id',
                  'regarding_staff_id'],
                 'task'),
 'delete_task': ('DELETE', '/staff/tasks/{id}', [], [], None),
 'list_assignees': ('GET', '/staff/assignees', ['limit', 'after', 'before'], [], None),
 'list_task_audit_logs': ('GET',
                          '/staff/task_audit_logs',
                          ['task_id',
                           'search',
                           'event_type',
                           'actor_id',
                           'sort',
                           'actor_ids',
                           'start_date',
                           'end_date',
                           'limit',
                           'after',
                           'before'],
                          [],
                          None)}
COLLECTIONS = {'list_calendar': 'calendar_item',
 'list_packages': 'package',
 'list_user_packages': 'user_package',
 'list_invoices': 'invoice',
 'list_visits': 'visit',
 'list_tasks': 'task',
 'list_assignees': 'assignee',
 'list_task_audit_logs': 'task_audit_log'}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class ExercisecomNode(WorkflowNode):
    integration_type = "automation-exercisecom"
    connection_evidence = ConnectionEvidence(noun="staff tasks", operation="list_tasks", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return ExercisecomConfig

    async def execute(self, inputs):
        if not isinstance(self.config, ExercisecomConfig) or not self.config.credentials:
            raise ValueError("Connect an Exercise.com Personal API Token")
        op, credential = self.config.config, self.config.credentials
        method, route, query_fields, body_fields, wrapper = ROUTES[op.operation]
        values = op.model_dump(mode="json", by_alias=True, exclude_none=True)
        if "{id}" in route:
            route = route.replace("{id}", str(values["id"]))
        params = {key: values[key] for key in query_fields if key in values}
        # Form-style exploded arrays are repeated query parameters, as OpenAPI specifies.
        params = [(key, str(item).lower() if isinstance(item, bool) else item)
                  for key, value in params.items()
                  for item in (value if isinstance(value, list) else [value])]
        # Explicit null on an update clears nullable provider fields; untouched fields stay absent.
        supplied = op.model_dump(mode="json", by_alias=True, exclude_unset=True)
        body = {key: supplied.get(key, values.get(key)) for key in body_fields
                if key in supplied or key in values}
        if wrapper:
            body = {wrapper: body}
        output = {"operation": op.operation}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://" + credential.api_host + route,
                    headers={"Authorization": "Bearer " + credential.api_token,
                             "Accept": "application/json", "X-Api-Version": "2026-05-20"},
                    params=params, **({"json": body} if body_fields else {}))
            output["http_status"] = response.status_code
            payload = None
            if response.content:
                if "json" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Exercise.com returned a non-JSON response")
                payload = json.loads(response.text, parse_constant=_invalid_constant)
            if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and payload.get("success") is False):
                error = payload.get("error") if isinstance(payload, dict) else None
                return {**output, "status": "error", "error": _redact(str(error or "Exercise.com rejected the request"), credential.api_token),
                        **({"details": _redact(payload["details"], credential.api_token)} if isinstance(payload, dict) and "details" in payload else {})}
            if op.operation == "remove_workout":
                if response.status_code != 204:
                    raise ValueError("Exercise.com did not acknowledge workout removal")
                return {**output, "status": "success", "removal_acknowledged": True, "id": op.id}
            if not isinstance(payload, dict):
                raise ValueError("Exercise.com returned an invalid JSON object")
            if op.operation in COLLECTIONS:
                key = COLLECTIONS[op.operation]
                if not isinstance(payload.get(key), list) or any(not isinstance(row, dict) for row in payload[key]):
                    raise ValueError("Exercise.com returned an invalid collection")
                result = {**output, "status": "success", "data": payload[key], "meta": payload.get("meta", {})}
                pagination = result["meta"].get("pagination", {}) if isinstance(result["meta"], dict) else {}
                result["pagination"] = pagination
                # Cursors are returned unchanged and must be used with the same endpoint and filters.
                result["next_after"] = pagination.get("cursors", {}).get("after") if isinstance(pagination.get("cursors"), dict) else None
                result["previous_before"] = pagination.get("cursors", {}).get("before") if isinstance(pagination.get("cursors"), dict) else None
            else:
                result = {**output, "status": "success", "data": payload}
            return _redact(result, credential.api_token)
        except (httpx.HTTPError, ValueError):
            # Never replay a mutation after a timeout or an unreadable acknowledgement.
            return {**output, "status": "error", "error": "Exercise.com request failed or returned an unreadable response",
                    "outcome_unknown": method != "GET"}


def _invalid_constant(value):
    raise ValueError("Nonfinite JSON number")
