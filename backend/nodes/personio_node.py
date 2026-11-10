"""Personio employees, day-based time off and v2 attendance periods.

Official contracts: https://github.com/personio/api-docs and
https://developer.personio.de/openapi/attendance-period-service-v2.yaml
Auth: manually supplied bearer token, valid for 24 hours. Permissions are set
on the API credential in Personio. No interactive OAuth or webhook subscription.
List operations return one page and preserve pagination metadata for syncing.
"""
import time
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Discriminator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

BASE_URL = "https://api.personio.de"


class PersonioAccessTokenCredential(BaseModel):
    credential_type: Literal["personio_access_token"] = Field(
        "personio_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        min_length=1,
        description="Personio bearer token (without the Bearer prefix). Tokens expire after 24 hours.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developer.personio.de/reference/authentication",
            "x-credential-instructions": "Generate a bearer token using your Personio API client ID and secret, then paste the token here. Tokens expire after 24 hours; replace the saved token when it expires. Enable read/write permissions for Employees, Absences and Attendances in your Personio API credentials.",
        }
    )


def operation_field(name: str, title: str, category: str):
    return Field(
        name,
        title=title,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-display-name": title,
            "x-category": category,
            "x-is-trigger": False,
        },
    )


def employee_id_field():
    return Field(
        ...,
        title="Employee ID",
        gt=0,
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "employee_id",
                "allow_custom": True,
                "searchable": True,
            }
        },
    )


class PersonioPageConfig(BaseModel):
    limit: int = Field(100, ge=1, title="Page Size")
    offset: int = Field(
        0,
        ge=0,
        title="Offset",
        description="Zero-based offset. Use returned metadata to request the next page.",
    )


class PersonioListEmployeesConfig(BaseModel):
    """List Personio persons (v2), including employee profile fields."""

    operation: Literal["list_employees"] = operation_field(
        "list_employees", "List Employees (Persons)", "Employees"
    )
    limit: int = Field(50, ge=1, le=50, title="Page Size")
    cursor: str | None = Field(
        None,
        title="Cursor",
        description="Cursor from the previous response _meta links",
    )
    email: str | None = Field(None, title="Email")
    updated_since: str | None = Field(
        None, title="Updated Since", description="UTC date/time, YYYY-MM-DDTHH:MM:SSZ"
    )


class PersonioGetEmployeeConfig(BaseModel):
    operation: Literal["get_employee"] = operation_field(
        "get_employee", "Get Employee", "Employees"
    )
    employee_id: int = employee_id_field()


class PersonioEmployeeFields(BaseModel):
    first_name: str | None = Field(None, title="First Name")
    last_name: str | None = Field(None, title="Last Name")
    preferred_name: str | None = Field(None, title="Preferred Name")
    gender: Literal["male", "female", "diverse"] | None = None
    position: str | None = None
    subcompany: str | None = None
    department: str | None = None
    office: str | None = None
    hire_date: date | None = Field(None, title="Hire Date")
    weekly_working_hours: float | None = Field(None, title="Weekly Working Hours", ge=0)
    status: Literal["onboarding", "active", "leave", "inactive"] | None = None
    supervisor_id: int | None = Field(
        None,
        title="Supervisor ID",
        description="On update, explicitly supplying null removes the supervisor.",
    )
    custom_attributes: dict[str, str] | None = Field(
        None,
        title="Custom Attributes",
        description="Map dynamic attribute IDs to values",
    )


class PersonioCreateEmployeeConfig(PersonioEmployeeFields):
    operation: Literal["create_employee"] = operation_field(
        "create_employee", "Create Employee", "Employees"
    )
    email: str = Field(..., title="Email", min_length=1)
    first_name: str = Field(..., title="First Name", min_length=1)
    last_name: str = Field(..., title="Last Name", min_length=1)


class PersonioUpdateEmployeeConfig(PersonioEmployeeFields):
    operation: Literal["update_employee"] = operation_field(
        "update_employee", "Update Employee", "Employees"
    )
    employee_id: int = employee_id_field()

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_fields_set - {"operation", "employee_id"}:
            raise ValueError("Supply at least one employee field to update")
        return self


class PersonioGetAbsenceBalanceConfig(BaseModel):
    operation: Literal["get_absence_balance"] = operation_field(
        "get_absence_balance", "Get Absence Balance", "Time Off"
    )
    employee_id: int = employee_id_field()


class PersonioListEmployeeAttributesConfig(BaseModel):
    operation: Literal["list_employee_attributes"] = operation_field(
        "list_employee_attributes", "List Employee Attributes", "Employees"
    )


class PersonioListTimeOffTypesConfig(PersonioPageConfig):
    operation: Literal["list_time_off_types"] = operation_field(
        "list_time_off_types", "List Time-Off Types", "Time Off"
    )


class PersonioListTimeOffsConfig(BaseModel):
    """List v2 absence periods, including day and hour absences."""

    operation: Literal["list_time_offs"] = operation_field(
        "list_time_offs", "List Time-Offs", "Time Off"
    )
    limit: int = Field(100, ge=1, le=100, title="Page Size")
    cursor: str | None = Field(None, title="Cursor")
    start_from: str | None = Field(
        None, title="Start From", description="UTC date/time, YYYY-MM-DDTHH:MM:SSZ"
    )
    end_to: str | None = Field(
        None, title="End To", description="UTC date/time, YYYY-MM-DDTHH:MM:SSZ"
    )
    updated_from: str | None = Field(
        None, title="Updated From", description="UTC date/time, YYYY-MM-DDTHH:MM:SSZ"
    )
    person_ids: list[str] | None = Field(None, title="Person IDs")


class PersonioGetTimeOffConfig(BaseModel):
    operation: Literal["get_time_off"] = operation_field(
        "get_time_off", "Get Time-Off", "Time Off"
    )
    time_off_id: str = Field(
        ...,
        min_length=1,
        title="Absence Period ID",
        description="v2 absence period UUID returned by List Time-Offs",
    )


class PersonioDeleteTimeOffConfig(BaseModel):
    operation: Literal["delete_time_off"] = operation_field(
        "delete_time_off", "Delete Time-Off", "Time Off"
    )
    time_off_id: int = Field(
        ...,
        gt=0,
        title="Time-Off ID",
        description="Numeric v1 day-based time-off ID, as returned by Create Time-Off; v2 list UUIDs cannot be used here.",
    )


class PersonioCreateTimeOffConfig(BaseModel):
    operation: Literal["create_time_off"] = operation_field(
        "create_time_off", "Create Time-Off", "Time Off"
    )
    employee_id: int = employee_id_field()
    time_off_type_id: int = Field(
        ..., gt=0, title="Time-Off Type ID", description="A day-based time-off type"
    )
    start_date: date = Field(..., title="Start Date")
    end_date: date = Field(..., title="End Date")
    half_day_start: bool = Field(False, title="Half Day at Start")
    half_day_end: bool = Field(False, title="Half Day at End")
    comment: str | None = None
    skip_approval: bool = Field(
        False,
        title="Skip Approval",
        description="False keeps the configured Personio approval flow.",
    )


class PersonioListAttendancePeriodsConfig(BaseModel):
    operation: Literal["list_attendance_periods"] = operation_field(
        "list_attendance_periods", "List Attendance Periods", "Attendance"
    )
    limit: int = Field(100, ge=1, le=100, title="Page Size")
    cursor: str | None = Field(
        None,
        title="Cursor",
        description="Cursor from the previous response _meta.links.next URL",
    )
    person_ids: list[str] | None = Field(None, title="Person IDs")
    start_from: str | None = Field(
        None,
        title="Start From",
        description="Local date/time without timezone, YYYY-MM-DDTHH:MM:SS",
    )
    start_to: str | None = Field(
        None,
        title="Start To",
        description="Local date/time without timezone, YYYY-MM-DDTHH:MM:SS",
    )
    updated_from: str | None = Field(
        None, title="Updated From", description="UTC date/time, YYYY-MM-DDTHH:MM:SSZ"
    )
    status: Literal["PENDING", "CONFIRMED", "REJECTED"] | None = None


class PersonioGetAttendancePeriodConfig(BaseModel):
    operation: Literal["get_attendance_period"] = operation_field(
        "get_attendance_period", "Get Attendance Period", "Attendance"
    )
    attendance_id: str = Field(..., title="Attendance Period ID", min_length=1)


class PersonioDeleteAttendancePeriodConfig(BaseModel):
    operation: Literal["delete_attendance_period"] = operation_field(
        "delete_attendance_period", "Delete Attendance Period", "Attendance"
    )
    attendance_id: str = Field(..., title="Attendance Period ID", min_length=1)


class PersonioAttendanceFields(BaseModel):
    start: str | None = Field(
        None,
        title="Start",
        description="Local date/time without timezone, YYYY-MM-DDTHH:MM:SS",
    )
    end: str | None = Field(
        None,
        title="End",
        description="Local date/time without timezone; omit for an open period. Explicit null reopens a period on update.",
    )
    comment: str | None = None
    project_id: str | None = Field(
        None,
        title="Project ID",
        description="Active project ID; explicit null removes the project on update.",
    )
    skip_approval: bool = Field(False, title="Skip Approval")


class PersonioCreateAttendancePeriodConfig(PersonioAttendanceFields):
    operation: Literal["create_attendance_period"] = operation_field(
        "create_attendance_period", "Create Attendance Period", "Attendance"
    )
    person_id: str = Field(..., title="Person ID", min_length=1)
    period_type: Literal["WORK", "BREAK"] = Field("WORK", title="Period Type")
    start: str = Field(
        ...,
        title="Start",
        description="Local date/time without timezone, YYYY-MM-DDTHH:MM:SS",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$",
    )


class PersonioUpdateAttendancePeriodConfig(PersonioAttendanceFields):
    operation: Literal["update_attendance_period"] = operation_field(
        "update_attendance_period", "Update Attendance Period", "Attendance"
    )
    attendance_id: str = Field(..., title="Attendance Period ID", min_length=1)

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_fields_set & {"start", "end", "comment", "project_id"}:
            raise ValueError("Supply a start, end, comment or project to update")
        return self


PersonioConfig = Annotated[
    Union[
        PersonioListEmployeesConfig,
        PersonioGetEmployeeConfig,
        PersonioCreateEmployeeConfig,
        PersonioUpdateEmployeeConfig,
        PersonioGetAbsenceBalanceConfig,
        PersonioListEmployeeAttributesConfig,
        PersonioListTimeOffTypesConfig,
        PersonioListTimeOffsConfig,
        PersonioGetTimeOffConfig,
        PersonioCreateTimeOffConfig,
        PersonioDeleteTimeOffConfig,
        PersonioListAttendancePeriodsConfig,
        PersonioGetAttendancePeriodConfig,
        PersonioCreateAttendancePeriodConfig,
        PersonioUpdateAttendancePeriodConfig,
        PersonioDeleteAttendancePeriodConfig,
    ],
    Discriminator("operation"),
]


class PersonioNodeConfig(NodeConfig[PersonioConfig, PersonioAccessTokenCredential]):
    pass


# Each action is exactly one documented API operation; no hidden mutations.
ROUTES = {
    "list_employees": ("GET", "/v2/persons"),
    "get_employee": ("GET", "/v1/company/employees/{employee_id}"),
    "create_employee": ("POST", "/v1/company/employees"),
    "update_employee": ("PATCH", "/v1/company/employees/{employee_id}"),
    "get_absence_balance": (
        "GET",
        "/v1/company/employees/{employee_id}/absences/balance",
    ),
    "list_employee_attributes": ("GET", "/v1/company/employees/attributes"),
    "list_time_off_types": ("GET", "/v1/company/time-off-types"),
    "list_time_offs": ("GET", "/v2/absence-periods"),
    "get_time_off": ("GET", "/v2/absence-periods/{time_off_id}"),
    "create_time_off": ("POST", "/v1/company/time-offs"),
    "delete_time_off": ("DELETE", "/v1/company/time-offs/{time_off_id}"),
    "list_attendance_periods": ("GET", "/v2/attendance-periods"),
    "get_attendance_period": ("GET", "/v2/attendance-periods/{attendance_id}"),
    "create_attendance_period": ("POST", "/v2/attendance-periods"),
    "update_attendance_period": ("PATCH", "/v2/attendance-periods/{attendance_id}"),
    "delete_attendance_period": ("DELETE", "/v2/attendance-periods/{attendance_id}"),
}


class PersonioAPIError(ValueError):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


async def _request(token, method, path, **kwargs):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method,
            BASE_URL + path,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            **kwargs,
        )
    if response.status_code == 204:
        return {}, response.status_code
    try:
        body = response.json()
    except ValueError:
        raise PersonioAPIError(
            f"Personio returned HTTP {response.status_code}: {response.text}",
            response.status_code,
        ) from None
    if response.is_error or (isinstance(body, dict) and body.get("success") is False):
        # Keep the provider error verbatim for the manual credential connect seam.
        raise PersonioAPIError(response.text, response.status_code)
    if not isinstance(body, dict):
        raise ValueError("Personio returned an unexpected response shape")
    return body, response.status_code


class PersonioNode(WorkflowNode):
    integration_type = "automation-personio"
    credential_provider_labels = {"personio": "Personio Account"}
    auto_select_credential = False
    connection_evidence = ConnectionEvidence(
        operation="list_employees",
        noun="employees",
        label_keys=("first_name", "email", "id"),
    )
    edit_examples = [
        "Sync employee records updated since yesterday",
        "Get an employee’s available time-off balance",
        "Create a time-off request using the approval flow",
        "Record a work attendance period",
    ]

    @classmethod
    def get_config_model(cls):
        return PersonioNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name, credential_data, context=None, page_token=None, search=None
    ):
        if field_name != "employee_id" or not credential_data:
            return {"options": []}
        params = {"limit": 50}
        if page_token:
            params["cursor"] = page_token
        body, _ = await _request(
            credential_data["access_token"], "GET", "/v2/persons", params=params
        )
        rows = body.get("_data")
        if not isinstance(rows, list):
            raise ValueError("Personio returned an invalid person list")
        options = []
        for row in rows:
            employee_id = row.get("id")
            label = (
                " ".join(
                    str(row.get(k) or "") for k in ("first_name", "last_name")
                ).strip()
                or row.get("email")
                or str(employee_id)
            )
            if employee_id is not None and (
                not search or search.casefold() in label.casefold()
            ):
                options.append({"value": str(employee_id), "label": label})
        # Read the cursor only; never follow a provider-supplied URL with credentials.
        from urllib.parse import parse_qs, urlsplit

        next_link = body.get("_meta", {}).get("links", {}).get("next", {})
        next_cursor = parse_qs(urlsplit(next_link.get("href", "")).query).get(
            "cursor", [None]
        )[0]
        return {"options": options, "next_page_token": next_cursor}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        if (
            not isinstance(self.config, PersonioNodeConfig)
            or not self.config.credentials
        ):
            raise ValueError("Personio credentials and configuration are required")
        config = self.config.config
        action = config.operation
        method, path = ROUTES[action]
        values = config.model_dump(
            mode="json", exclude={"operation"}, exclude_none=True
        )
        for key in ("employee_id", "time_off_id", "attendance_id"):
            if "{" + key + "}" in path:
                path = path.replace(
                    "{" + key + "}", quote(str(values.pop(key)), safe="")
                )
        kwargs = {}
        if action in ("create_employee", "update_employee"):
            employee = config.model_dump(
                mode="json", exclude={"operation", "employee_id"}, exclude_unset=True
            )
            # Defaulted nullable fields must not erase existing values.
            kwargs["json"] = {"employee": employee}
        elif action == "create_time_off":
            kwargs["data"] = {
                k: str(v).lower() if isinstance(v, bool) else str(v)
                for k, v in values.items()
            }
        elif action in ("create_attendance_period", "update_attendance_period"):
            kwargs["params"] = {"skip_approval": str(config.skip_approval).lower()}
            body = {}
            # PATCH nulls have meaning and must survive exclude_none.
            supplied = config.model_dump(mode="json", exclude_unset=True)
            for key in ("start", "end", "comment", "project_id"):
                if key in supplied:
                    value = supplied[key]
                    target = "project" if key == "project_id" else key
                    body[target] = (
                        (
                            {"id": value}
                            if key == "project_id"
                            else {"date_time": value}
                            if key in ("start", "end")
                            else value
                        )
                        if value is not None
                        else None
                    )
            if action == "create_attendance_period":
                body.update(person={"id": config.person_id}, type=config.period_type)
            kwargs["json"] = body
        elif method == "GET":
            aliases = {
                "person_ids": "person.id",
                "start_from": "start.date_time.gte",
                "start_to": "start.date_time.lte",
            }
            if action == "list_employees":
                aliases["updated_since"] = "updated_at.gte"
            if action == "list_time_offs":
                aliases.update(
                    start_from="starts_from.date_time.gte",
                    end_to="ends_at.date_time.lte",
                    updated_from="updated_at.gte",
                )
            if action == "list_attendance_periods":
                aliases["updated_from"] = "updated_at.gte"
            kwargs["params"] = {
                aliases.get(k, k): ",".join(v) if k == "person_ids" else v
                for k, v in values.items()
            }
        try:
            body, status_code = await _request(
                self.config.credentials.access_token, method, path, **kwargs
            )
        except (ValueError, httpx.HTTPError) as exc:
            return {
                "status": "error",
                "action": action,
                "error": str(exc),
                "status_code": getattr(exc, "status_code", None),
                "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)},
            }
        data = body.get("data", body.get("_data", body))
        return {
            "status": "success",
            "action": action,
            "data": data,
            "metadata": body.get("metadata", body.get("_meta", {})),
            "raw_response": body,
            "status_code": status_code,
            "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)},
        }
