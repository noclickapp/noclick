"""7shifts scheduling and workforce operations, pinned to API version 2024-04-01."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.7shifts.com/v2"
API_VERSION = "2024-04-01"
ID = Annotated[int, Field(ge=1)]
OptionalID = Annotated[int, Field(ge=0)]
Text = Annotated[str, Field(max_length=10000)]
DateText = Annotated[str, Field(json_schema_extra={"format": "date"})]
DateTimeText = Annotated[str, Field(json_schema_extra={"format": "date-time"})]


class SevenShiftsAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="7shifts Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.7shifts.com/reference/authentication",
            "x-credential-instructions": "In 7shifts, open Company Settings → Developer Tools → Access Tokens and create an access token. Paste it without the Bearer prefix. Access tokens grant admin access to one company and cannot be scoped. Leave Company GUID empty for an access token. A partner-issued bearer token may instead be pasted with its Company GUID; those tokens expire after one hour and must be replaced manually.",
        })
    credential_type: Literal["7shifts_access_token"] = Field("7shifts_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})
    company_guid: str | None = Field(None, title="Company GUID (partner tokens only)",
        description="Leave empty for a personal access token. Partner bearer tokens require the company GUID from Connected Apps.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the access token as text")
        value = clean_secret(value, field_name="Access token", key=True)
        if not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value

    @field_validator("company_guid", mode="before")
    @classmethod
    def guid(cls, value):
        if value is None or value == "":
            return None
        try:
            return str(UUID(value.strip()))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Use the company's UUID from 7shifts Connected Apps") from None


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def dates(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"start", "end", "clocked_in", "clocked_out", "start_gte", "start_lte", "end_gte", "end_lte", "clocked_in_gte", "clocked_in_lte", "clocked_out_gte", "clocked_out_lte"}:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("Use an ISO8601 date and time with a timezone") from None
        if info.field_name in {"modified_since", "hire_date", "from_date", "to_date", "to_date_gte"}:
            try:
                date.fromisoformat(value)
            except (ValueError, TypeError):
                raise ValueError("Use a date in YYYY-MM-DD format") from None
        return value

    @model_validator(mode="after")
    def ranges(self):
        for start, end in (("start", "end"), ("clocked_in", "clocked_out"), ("from_date", "to_date")):
            a, b = getattr(self, start, None), getattr(self, end, None)
            if a is not None and b is not None:
                left, right = (date.fromisoformat(a), date.fromisoformat(b)) if start == "from_date" else (datetime.fromisoformat(a.replace("Z", "+00:00")), datetime.fromisoformat(b.replace("Z", "+00:00")))
                if right < left or (start != "from_date" and right == left):
                    raise ValueError(f"{end} must be after {start}")
        return self


class _Company(_Input):
    company_id: ID = Field(..., title="Company ID", description="Find the company ID with List companies or Developer Tools → Resource IDs.")


class _Page(_Company):
    cursor: str | None = Field(None, max_length=4096, description="Use meta.cursor.next from the previous page. One page is returned per execution.")
    limit: int = Field(100, ge=1, le=100)


class ListCompanies(_Input):
    operation: Literal["list_companies"] = "list_companies"
    modified_since: DateText | None = None


class GetCompany(_Company):
    operation: Literal["get_company"] = "get_company"


class ListLocations(_Page):
    operation: Literal["list_locations"] = "list_locations"
    modified_since: DateText | None = None
    deleted: bool | None = None


class GetLocation(_Company):
    operation: Literal["get_location"] = "get_location"
    location_id: ID


class ListDepartments(_Page):
    operation: Literal["list_departments"] = "list_departments"
    location_id: ID | None = None
    modified_since: DateText | None = None


class ListRoles(_Page):
    operation: Literal["list_roles"] = "list_roles"
    location_id: ID | None = None
    department_id: OptionalID | None = None
    modified_since: DateText | None = None


class ListUsers(_Page):
    operation: Literal["list_users"] = "list_users"
    location_id: ID | None = None
    department_id: ID | None = None
    role_id: ID | None = None
    status: Literal["active", "inactive"] | None = None
    name: str | None = Field(None, max_length=200)
    modified_since: DateText | None = None

    @model_validator(mode="after")
    def exclusive_filters(self):
        if sum(value is not None for value in (self.location_id, self.department_id, self.role_id)) > 1:
            raise ValueError("Filter users by only one of location, department or role")
        return self


class GetUser(_Company):
    operation: Literal["get_user"] = "get_user"
    user_id: ID


class CreateUser(_Company):
    operation: Literal["create_user"] = "create_user"
    first_name: str = Field(..., min_length=1, max_length=200)
    last_name: str = Field(..., min_length=1, max_length=200)
    location_ids: list[ID] = Field(..., min_length=1, max_length=100)
    department_ids: list[ID] = Field(..., max_length=100, description="Use an empty list if the location has no departments.")
    role_ids: list[ID] | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=320)
    type: Literal["employee", "asst_manager", "manager", "employer"] = "employee"
    invite_user: bool = Field(False, description="Send a 7shifts invitation email only when explicitly enabled.")
    employee_id: str | None = Field(None, max_length=200)
    hire_date: DateText | None = None
    mobile_number: str | None = Field(None, max_length=50)
    notes: Text | None = None


class UpdateUser(_Company):
    operation: Literal["update_user"] = "update_user"
    user_id: ID
    first_name: str | None = Field(None, min_length=1, max_length=200)
    last_name: str | None = Field(None, min_length=1, max_length=200)
    email: str | None = Field(None, max_length=320)
    mobile_number: str | None = Field(None, max_length=50)
    employee_id: str | None = Field(None, max_length=200)
    hire_date: DateText | None = None
    active: bool | None = None
    notes: Text | None = None


class ListShifts(_Page):
    operation: Literal["list_shifts"] = "list_shifts"
    location_id: ID | None = None
    department_id: OptionalID | None = None
    role_id: OptionalID | None = None
    user_id: ID | None = None
    start_gte: DateTimeText | None = None
    start_lte: DateTimeText | None = None
    end_gte: DateTimeText | None = None
    end_lte: DateTimeText | None = None
    draft: bool | None = None
    include_draft: bool | None = None
    deleted: bool | None = None
    open: bool | None = None


class GetShift(_Company):
    operation: Literal["get_shift"] = "get_shift"
    shift_id: ID
    include_deleted: bool | None = None


class _ShiftBody(_Company):
    location_id: ID
    start: DateTimeText = Field(..., description="ISO8601 date and time with timezone; sent in UTC.")
    end: DateTimeText = Field(..., description="ISO8601 date and time with timezone; sent in UTC.")
    user_id: ID | None = None
    department_id: OptionalID | None = Field(None, description="Required when the location uses departments.")
    role_id: OptionalID | None = Field(None, description="Required when the location uses roles.")
    notes: Text | None = None
    draft: bool | None = None
    open: bool | None = None


class CreateShift(_ShiftBody):
    operation: Literal["create_shift"] = "create_shift"


class UpdateShift(_ShiftBody):
    operation: Literal["update_shift"] = "update_shift"
    shift_id: ID


class DeleteShift(_Company):
    """Delete a shift by its ID."""
    operation: Literal["delete_shift"] = "delete_shift"
    shift_id: ID


class ListTimePunches(_Page):
    operation: Literal["list_time_punches"] = "list_time_punches"
    location_id: ID | None = None
    department_id: OptionalID | None = None
    role_id: OptionalID | None = None
    user_id: ID | None = None
    approved: bool | None = None
    modified_since: DateText | None = None
    clocked_in_gte: DateTimeText | None = None
    clocked_in_lte: DateTimeText | None = None
    clocked_out_gte: DateTimeText | None = None
    clocked_out_lte: DateTimeText | None = None
    deleted: bool | None = None


class GetTimePunch(_Company):
    operation: Literal["get_time_punch"] = "get_time_punch"
    time_punch_id: ID


class CreateTimePunch(_Company):
    operation: Literal["create_time_punch"] = "create_time_punch"
    location_id: ID
    user_id: ID
    clocked_in: DateTimeText
    clocked_out: DateTimeText | None = None
    department_id: OptionalID | None = Field(None, description="Required when the location uses departments.")
    role_id: OptionalID | None = None
    notes: Text | None = None
    tips: int | None = Field(None, ge=0, description="Declared tips in cents.")


class UpdateTimePunch(_Company):
    operation: Literal["update_time_punch"] = "update_time_punch"
    time_punch_id: ID
    clocked_in: DateTimeText | None = None
    clocked_out: DateTimeText | None = None
    department_id: OptionalID | None = None
    role_id: OptionalID | None = None
    notes: Text | None = None
    tips: int | None = Field(None, ge=0, description="Declared tips in cents.")


class ListTimeOff(_Page):
    operation: Literal["list_time_off"] = "list_time_off"
    location_id: ID | None = None
    user_id: ID | None = None
    status: int | None = None
    category: str | None = Field(None, max_length=100)
    to_date_gte: DateText | None = None


class GetTimeOff(_Input):
    operation: Literal["get_time_off"] = "get_time_off"
    time_off_id: ID


class CreateTimeOff(_Company):
    operation: Literal["create_time_off"] = "create_time_off"
    user_id: ID
    from_date: DateText
    to_date: DateText
    partial: bool
    status: int
    category: str = Field(..., min_length=1, max_length=100)
    partial_from: str | None = Field(None, pattern=r"^\d{2}:\d{2}(?::\d{2})?$")
    partial_to: str | None = Field(None, pattern=r"^\d{2}:\d{2}(?::\d{2})?$")
    comments: Text | None = None

    @model_validator(mode="after")
    def partial_times(self):
        if self.partial and (not self.partial_from or not self.partial_to):
            raise ValueError("Partial time off needs partial_from and partial_to")
        return self


class UpdateTimeOff(_Input):
    operation: Literal["update_time_off"] = "update_time_off"
    time_off_id: ID
    user_id: ID | None = None
    from_date: DateText | None = None
    to_date: DateText | None = None
    partial: bool | None = None
    status: int | None = None
    category: str | None = Field(None, max_length=100)
    partial_from: str | None = Field(None, pattern=r"^\d{2}:\d{2}(?::\d{2})?$")
    partial_to: str | None = Field(None, pattern=r"^\d{2}:\d{2}(?::\d{2})?$")
    comments: Text | None = None
    status_action_message: Text | None = None


SevenShiftsConfig = Annotated[Union[ListCompanies, GetCompany, ListLocations, GetLocation, ListDepartments, ListRoles,
    ListUsers, GetUser, CreateUser, UpdateUser, ListShifts, GetShift, CreateShift, UpdateShift, DeleteShift,
    ListTimePunches, GetTimePunch, CreateTimePunch, UpdateTimePunch, ListTimeOff, GetTimeOff, CreateTimeOff, UpdateTimeOff], Field(discriminator="operation")]


class SevenShiftsFullConfig(NodeConfig[SevenShiftsConfig, SevenShiftsAccessTokenCredential]):
    pass


ROUTES = {
    "list_companies": ("GET", "/companies"),
    "get_company": ("GET", "/companies/{company_id}"),
    "list_locations": ("GET", "/company/{company_id}/locations"),
    "get_location": ("GET", "/company/{company_id}/locations/{location_id}"),
    "list_departments": ("GET", "/company/{company_id}/departments"),
    "list_roles": ("GET", "/company/{company_id}/roles"),
    "list_users": ("GET", "/company/{company_id}/users"),
    "get_user": ("GET", "/company/{company_id}/users/{user_id}"),
    "create_user": ("POST", "/company/{company_id}/users"),
    "update_user": ("PUT", "/company/{company_id}/users/{user_id}"),
    "list_shifts": ("GET", "/company/{company_id}/shifts"),
    "get_shift": ("GET", "/company/{company_id}/shifts/{shift_id}"),
    "create_shift": ("POST", "/company/{company_id}/shifts"),
    "update_shift": ("PUT", "/company/{company_id}/shifts/{shift_id}"),
    "delete_shift": ("DELETE", "/company/{company_id}/shifts/{shift_id}"),
    "list_time_punches": ("GET", "/company/{company_id}/time_punches"),
    "get_time_punch": ("GET", "/company/{company_id}/time_punches/{time_punch_id}"),
    "create_time_punch": ("POST", "/company/{company_id}/time_punches"),
    "update_time_punch": ("PUT", "/company/{company_id}/time_punches/{time_punch_id}"),
    "list_time_off": ("GET", "/time_off"),
    "get_time_off": ("GET", "/time_off/{time_off_id}"),
    "create_time_off": ("POST", "/time_off"),
    "update_time_off": ("PATCH", "/time_off/{time_off_id}"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()
                if key.lower() not in {"api_key", "access_token", "refresh_token", "password", "authorization"}}
    return value


class SevenShiftsNode(WorkflowNode):
    integration_type = "automation-7shifts"
    connection_evidence = ConnectionEvidence(noun="7shifts companies", operation="list_companies")

    @classmethod
    def get_config_model(cls):
        return SevenShiftsFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, SevenShiftsFullConfig) or not self.config.credentials:
            raise ValueError("Attach a 7shifts access token")
        config, credential = self.config.config, self.config.credentials
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = template.format(**{key: values.pop(key) for key in re.findall(r"\{(\w+)\}", template)})
        if config.operation.startswith("update_") and not values:
            raise ValueError("Provide at least one field to update")
        # 7shifts date-time inputs are UTC even when the user provides an offset.
        for key in ("start", "end", "clocked_in", "clocked_out", "start_gte", "start_lte", "end_gte", "end_lte", "clocked_in_gte", "clocked_in_lte", "clocked_out_gte", "clocked_out_lte"):
            if key in values:
                values[key] = datetime.fromisoformat(values[key].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        headers = {"Authorization": "Bearer " + credential.access_token, "Accept": "application/problem+json" if method == "DELETE" else "application/json", "x-api-version": API_VERSION}
        if credential.company_guid:
            headers["x-company-guid"] = credential.company_guid
        kwargs = {}
        if method == "GET":
            params = {(re.sub(r"_(gte|lte)$", r"[\1]", key) if key.startswith(("start_", "end_", "clocked_in_", "clocked_out_")) else key): str(value).lower() if isinstance(value, bool) else value for key, value in values.items()}
            if params:
                kwargs["params"] = params
        elif method in {"POST", "PUT", "PATCH"}:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        if len(response.content) > 10_000_000:
            raise ValueError("7shifts response exceeds the size limit")
        if response.status_code == 204 and method == "DELETE" and not response.content:
            return {"status": "success", "operation": config.operation, "http_status": 204, "deleted": True}
        media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media not in {"application/json", "application/problem+json"}:
            raise ValueError("Expected JSON from 7shifts")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("7shifts returned invalid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("7shifts returned an unexpected response envelope")
        if response.status_code >= 300 or body.get("error") or body.get("errors") or body.get("status") in {"error", "failed"}:
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(body.get("message") or body.get("detail") or body.get("error") or body, credential.access_token)}
        if response.status_code not in {200, 201}:
            raise ValueError("7shifts did not confirm the operation")
        bare = config.operation in {"get_company", "get_time_off", "create_time_off", "update_time_off"}
        data = body if bare else body.get("data")
        if not isinstance(data, list if config.operation.startswith("list_") else dict):
            raise ValueError("7shifts returned an unexpected data shape")
        result = {"status": "success", "operation": config.operation, "http_status": response.status_code, "data": data}
        if not bare and "meta" in body:
            result["meta"] = body["meta"]
        if config.operation.startswith("list_"):
            cursor = body.get("meta", {}).get("cursor", {}).get("next")
            result.update(next_cursor=cursor, has_more=bool(cursor))
        return _redact(result, credential.access_token)
