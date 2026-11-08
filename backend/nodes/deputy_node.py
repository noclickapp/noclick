"""Deputy v1 workforce operations using a tenant's permanent token.

Each operation issues one documented request. List resources are single server
responses (Deputy caps each at 500 records), bounded by size; they do not
promise a complete export or pagination.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client


class DeputyPermanentTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Deputy Permanent Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.deputy.com/docs/the-hello-world-of-deputy",
            "x-credential-instructions": "Paste a Deputy permanent token and your Deputy workplace URL, such as https://your-workplace.au.deputy.com. In Deputy, open /exec/devapp/oauth_clients, add an OAuth client, save it, and select Get an Access Token. Requests use Bearer authentication; the token's existing user permissions control access. Connecting reads your workplace locations.",
        },
    )
    credential_type: Literal["deputy_permanent_token"] = Field("deputy_permanent_token", json_schema_extra={"ui:hidden": True})
    workplace_url: str = Field(..., title="Workplace URL", description="HTTPS origin of your Deputy workplace, including its region; no API path.")
    permanent_token: str = Field(..., title="Permanent token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("workplace_url", mode="before")
    @classmethod
    def workplace(cls, value):
        if not isinstance(value, str):
            raise ValueError("Copy your Deputy workplace HTTPS URL")
        value = value.strip()
        # The region and tenant are mandatory; a suffix match alone also permits
        # unrelated Deputy services. Never accept userinfo, ports or API paths.
        if not re.fullmatch(r"https://[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.(?:au|eu|na|deputy)\.deputy\.com/?", value):
            raise ValueError("Use https://your-workplace.au.deputy.com (or your eu, na or deputy region)")
        return "https://" + urlsplit(value).hostname.lower()

    @field_validator("permanent_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Permanent token")
        if not value.isascii() or any(c.isspace() for c in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste only the Deputy permanent token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


PositiveId = Annotated[int, Field(ge=1, le=2147483647)]
Name = Annotated[str, Field(min_length=1, max_length=64)]
Date = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
LeaveDate = Annotated[str, Field(pattern=r"^\d{4}/\d{2}/\d{2}$")]


class ListEmployees(_Input):
    operation: Literal["list_employees"] = Field("list_employees", title="List Employees", json_schema_extra={"ui:hidden": True})


class GetEmployee(_Input):
    operation: Literal["get_employee"] = Field("get_employee", title="Get Employee", json_schema_extra={"ui:hidden": True})
    employee_id: PositiveId


class CreateEmployee(_Input):
    operation: Literal["create_employee"] = Field("create_employee", title="Create Employee", json_schema_extra={"ui:hidden": True})
    first_name: Name
    last_name: Name
    company_id: PositiveId = Field(..., description="Location to add this employee to.")
    mobile_phone: str | None = Field(None, min_length=1, max_length=64)
    payroll_id: str | None = Field(None, min_length=1, max_length=64)


class UpdateEmployeePhone(_Input):
    operation: Literal["update_employee_phone"] = Field("update_employee_phone", title="Update Employee Phone", json_schema_extra={"ui:hidden": True})
    employee_id: PositiveId
    phone: str = Field(..., min_length=1, max_length=64)


class ListLocations(_Input):
    operation: Literal["list_locations"] = Field("list_locations", title="List Locations", json_schema_extra={"ui:hidden": True})


class GetLocation(_Input):
    operation: Literal["get_location"] = Field("get_location", title="Get Location", json_schema_extra={"ui:hidden": True})
    company_id: PositiveId


class ListAreas(_Input):
    operation: Literal["list_areas"] = Field("list_areas", title="List Areas", json_schema_extra={"ui:hidden": True})


class GetArea(_Input):
    operation: Literal["get_area"] = Field("get_area", title="Get Area", json_schema_extra={"ui:hidden": True})
    area_id: PositiveId


class CreateArea(_Input):
    operation: Literal["create_area"] = Field("create_area", title="Create Area", json_schema_extra={"ui:hidden": True})
    company_id: PositiveId
    name: str = Field(..., min_length=1, max_length=200)
    export_name: str | None = Field(None, min_length=1, max_length=64)


class ListRosters(_Input):
    operation: Literal["list_rosters"] = Field("list_rosters", title="List Rosters (Shifts)", json_schema_extra={"ui:hidden": True})


class GetRoster(_Input):
    operation: Literal["get_roster"] = Field("get_roster", title="Get Roster (Shift)", json_schema_extra={"ui:hidden": True})
    roster_id: PositiveId


class CopyRosters(_Input):
    operation: Literal["copy_rosters"] = Field("copy_rosters", title="Copy Rosters", json_schema_extra={"ui:hidden": True})
    from_date: Date = Field(..., description="Source date in YYYY-MM-DD.")
    to_date: Date = Field(..., description="Destination date in YYYY-MM-DD.")
    area_ids: list[PositiveId] = Field(..., min_length=1, max_length=100)

    @field_validator("from_date", "to_date")
    @classmethod
    def date(cls, value):
        datetime.strptime(value, "%Y-%m-%d")
        return value


class PublishRosters(_Input):
    operation: Literal["publish_rosters"] = Field("publish_rosters", title="Publish Rosters", description="Publish the specified roster IDs; Deputy may notify employees according to the selected mode.", json_schema_extra={"ui:hidden": True})
    roster_ids: list[PositiveId] = Field(..., min_length=1, max_length=100)
    mode: int = Field(..., ge=0, le=2147483647, description="Deputy intMode publishing/notification mode. Choose the value for your workplace; all-locations publishing is disabled.")


class ListTimesheets(_Input):
    operation: Literal["list_timesheets"] = Field("list_timesheets", title="List Timesheets", json_schema_extra={"ui:hidden": True})


class GetTimesheet(_Input):
    operation: Literal["get_timesheet"] = Field("get_timesheet", title="Get Timesheet", json_schema_extra={"ui:hidden": True})
    timesheet_id: PositiveId


class StartTimesheet(_Input):
    operation: Literal["start_timesheet"] = Field("start_timesheet", title="Clock In Employee", json_schema_extra={"ui:hidden": True})
    employee_id: PositiveId
    area_id: PositiveId


class StopTimesheet(_Input):
    operation: Literal["stop_timesheet"] = Field("stop_timesheet", title="Clock Out Employee", json_schema_extra={"ui:hidden": True})
    timesheet_id: PositiveId
    mealbreak_minutes: int = Field(..., ge=0, le=1440)


class PauseTimesheet(_Input):
    operation: Literal["pause_timesheet"] = Field("pause_timesheet", title="Toggle Timesheet Break", description="Deputy toggles the break state. Inspect the result before retrying.", json_schema_extra={"ui:hidden": True})
    timesheet_id: PositiveId
    mealbreak_minutes: int = Field(..., ge=0, le=1440)


class ListLeave(_Input):
    operation: Literal["list_leave"] = Field("list_leave", title="List Leave", json_schema_extra={"ui:hidden": True})


class GetLeave(_Input):
    operation: Literal["get_leave"] = Field("get_leave", title="Get Leave", json_schema_extra={"ui:hidden": True})
    leave_id: PositiveId


class CreateLeave(_Input):
    operation: Literal["create_leave"] = Field("create_leave", title="Create Leave", json_schema_extra={"ui:hidden": True})
    employee_id: PositiveId
    date_start: LeaveDate
    date_end: LeaveDate
    status: Literal[0, 1, 2, 3] = Field(..., description="0 awaiting approval, 1 approved, 2 declined, 3 cancelled.")
    approval_comment: str = Field(..., max_length=2000)
    overlapping_rosters_action: int = Field(..., ge=0, le=2147483647, description="Deputy ActionOverlappingRosters value. Explicitly choose how existing shifts are handled.")

    @field_validator("date_start", "date_end")
    @classmethod
    def date(cls, value):
        datetime.strptime(value, "%Y/%m/%d")
        return value

    @model_validator(mode="after")
    def dates(self):
        if self.date_end < self.date_start:
            raise ValueError("Leave end must be on or after its start")
        return self


class ListTasks(_Input):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})


class GetTask(_Input):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})
    task_id: PositiveId


class GetEmployeeUnavailability(_Input):
    operation: Literal["get_employee_unavailability"] = Field("get_employee_unavailability", title="Get Employee Unavailability", json_schema_extra={"ui:hidden": True})
    employee_id: PositiveId


DeputyOperation = Annotated[Union[
    ListEmployees, GetEmployee, CreateEmployee, UpdateEmployeePhone,
    ListLocations, GetLocation, ListAreas, GetArea, CreateArea,
    ListRosters, GetRoster, CopyRosters, PublishRosters,
    ListTimesheets, GetTimesheet, StartTimesheet, StopTimesheet, PauseTimesheet,
    ListLeave, GetLeave, CreateLeave, ListTasks, GetTask, GetEmployeeUnavailability,
], Field(discriminator="operation")]


class DeputyNodeConfig(NodeConfig[DeputyOperation, DeputyPermanentTokenCredential]):
    pass


# Fixed read routes and selectors: user data cannot choose a host, method or path.
READS = {
    "list_employees": ("Employee", None), "get_employee": ("Employee", "employee_id"),
    "list_locations": ("Company", None), "get_location": ("Company", "company_id"),
    "list_areas": ("OperationalUnit", None), "get_area": ("OperationalUnit", "area_id"),
    "list_rosters": ("Roster", None), "get_roster": ("Roster", "roster_id"),
    "list_timesheets": ("Timesheet", None), "get_timesheet": ("Timesheet", "timesheet_id"),
    "list_leave": ("Leave", None), "get_leave": ("Leave", "leave_id"),
    "list_tasks": ("Task", None), "get_task": ("Task", "task_id"),
}


def _request_for(op):
    action = op.operation
    if action in READS:
        resource, field = READS[action]
        return "GET", "/resource/" + resource + ("/" + str(getattr(op, field)) if field else ""), None
    if action == "get_employee_unavailability":
        return "GET", f"/supervise/unavail/{op.employee_id}", None
    if action == "create_employee":
        return "POST", "/supervise/employee", {
            "strFirstName": op.first_name, "strLastName": op.last_name, "intCompanyId": op.company_id,
            **({"strMobilePhone": op.mobile_phone} if op.mobile_phone is not None else {}),
            **({"strPayrollId": op.payroll_id} if op.payroll_id is not None else {}),
        }
    if action == "update_employee_phone":
        return "POST", f"/supervise/employee/{op.employee_id}", {"Phone": op.phone}
    if action == "create_area":
        return "PUT", "/supervise/department", {"intCompanyId": op.company_id, "strOpunitName": op.name,
            **({"strExportName": op.export_name} if op.export_name is not None else {})}
    if action == "copy_rosters":
        return "POST", "/supervise/roster/copy", {"strFromDate": op.from_date, "strToDate": op.to_date,
            "intOperationalUnitArray": op.area_ids, "blnRequireErrorDetails": 1}
    if action == "publish_rosters":
        return "POST", "/supervise/roster/publish", {"intMode": op.mode, "blnAllLocationsMode": 0, "intRosterArray": op.roster_ids}
    if action == "start_timesheet":
        return "POST", "/supervise/timesheet/start", {"intOpunitId": op.area_id, "intEmployeeId": op.employee_id}
    if action in {"stop_timesheet", "pause_timesheet"}:
        return "POST", "/supervise/timesheet/" + ("end" if action == "stop_timesheet" else "pause"), {
            "intTimesheetId": op.timesheet_id, "intMealbreakMinute": op.mealbreak_minutes}
    if action == "create_leave":
        return "POST", "/supervise/leave", {"Status": op.status, "Employee": op.employee_id,
            "DateStart": op.date_start, "DateEnd": op.date_end, "ApprovalComment": op.approval_comment,
            "ActionOverlappingRosters": op.overlapping_rosters_action}
    raise ValueError("Unsupported Deputy operation")


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class DeputyNode(WorkflowNode):
    integration_type = "automation-deputy"
    connection_evidence = ConnectionEvidence(noun="locations", operation="list_locations", label_keys=("CompanyName", "TradingName", "Id"))

    @classmethod
    def get_config_model(cls):
        return DeputyNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Deputy permanent token")
        credential = self.config.credentials
        op = self.config.config
        method, route, body = _request_for(op)
        write = method != "GET"
        headers = {"Authorization": "Bearer " + credential.permanent_token, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, credential.workplace_url + "/api/v1" + route, headers=headers,
                                         **({"json": body} if body is not None else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 4 * 1024 * 1024:
                            raise ValueError("Deputy response exceeds 4 MiB; use a smaller resource selection")
                    if response.status_code != 200:
                        message = "Deputy request was not accepted"
                        try:
                            error = json.loads(raw)
                            if isinstance(error, dict):
                                detail = error.get("message") or error.get("error")
                                if isinstance(detail, str):
                                    message += ": " + detail[:1000]
                        except (ValueError, UnicodeError):
                            pass
                        ambiguous = write and (response.status_code < 400 or response.status_code >= 500)
                        return _redact({"status": "unknown" if ambiguous else "error", "success": False,
                            "error": message, "http_status": response.status_code,
                            **({"write_outcome": "unverified"} if ambiguous else {})}, credential.permanent_token)
                    media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if media != "application/json" and not (media.startswith("application/") and media.endswith("+json")):
                        raise ValueError("Deputy returned a non-JSON response")
                    payload = json.loads(raw)
            if payload is False or payload is None or (isinstance(payload, dict) and (payload.get("error") or payload.get("errors") or payload.get("success") is False)):
                return _redact({"status": "error", "success": False, "error": payload}, credential.permanent_token)
            if op.operation in READS:
                _, selector = READS[op.operation]
                if selector is None and not isinstance(payload, list):
                    raise ValueError("Deputy returned an unexpected resource list")
                if selector is not None and not isinstance(payload, dict):
                    raise ValueError("Deputy returned an unexpected resource")
            return _redact({"status": "success", "success": True, "data": payload, "http_status": 200,
                **({"write_acknowledged": True, "readback_verified": False} if write else {})}, credential.permanent_token)
        except (ValueError, UnicodeError, httpx.HTTPError, OSError, SSRFError):
            return {"status": "unknown" if write else "error", "success": False,
                "error": "Deputy response could not be verified; inspect the workplace before retrying a write" if write else "Deputy read could not be verified",
                **({"write_outcome": "unverified"} if write else {})}
