"""TalentHR v1 operations, checked against the publisher's Postman examples.

One provider request per operation; list operations return one page. Provider
JSON is preserved without inferring schemas from saved response examples.
"""
from __future__ import annotations

import base64
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://pubapi.talenthr.io/v1"
DOCS = "https://www.postman.com/collections/32971705-282b1908-49ef-4074-8ea7-67fdb51c9b4a"


class TalenthrApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="TalentHR API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://help.talenthr.io/hc/en-us/articles/17627841146909-Can-I-integrate-my-site-with-TalentHR-Do-you-offer-an-API",
            "x-credential-instructions": "In TalentHR, open Settings → Domain settings → API and copy an API key. Paste the key alone. NoClick sends it as the Basic username with an empty password. A read-only key supports reads; writes require a full key and the appropriate permissions."})
    credential_type: Literal["talenthr_api_key"] = Field("talenthr_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if ":" in value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key alone, without a header or colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Identifier = Annotated[int, Field(gt=0)]
Name = Annotated[str, Field(min_length=1, max_length=255)]
PersonName = Annotated[str, Field(min_length=1, max_length=191)]
Email = Annotated[str, Field(max_length=191, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]


class _Employee(_Input):
    employee_id: Identifier = Field(..., description="TalentHR employee ID.")


class _Department(_Input):
    department_id: Identifier


class _Location(_Input):
    location_id: Identifier


class _Page(_Input):
    limit: int = Field(10, ge=1, le=100, description="Rows per page; this operation returns one page.")
    offset: int = Field(0, ge=0, description="Start at 0; add limit to request the next page.")


class EmploymentStatus(_Input):
    employment_status_id: Identifier


class _Person(_Input):
    first_name: PersonName
    last_name: PersonName
    email: Email


class _Hire(_Input):
    hire_date: date
    reports_to_employee_id: Identifier | None = Field(..., description="Manager ID; null makes a new hire the company head.")
    employment_status: EmploymentStatus


class _Request(_Employee):
    request_id: Identifier


class TalenthrListEmployeesConfig(_Page):
    """Get directory's info."""
    operation: Literal["list_employees"] = Field("list_employees", json_schema_extra={"ui:hidden": True})
    filter: str | None = Field(None, description="Directory filter expression, for example location=36;emp_state=1,2,3,5;")
    custom_fields: str | None = Field(None, description="Comma-separated enabled custom field slugs.")


class TalenthrGetEmployeeConfig(_Employee):
    """Get an employee."""
    operation: Literal["get_employee"] = Field("get_employee", json_schema_extra={"ui:hidden": True})


class TalenthrHireEmployeeConfig(_Person, _Hire):
    """Hire an employee. TalentHR sends invitation emails and starts onboarding tasks, which can notify task owners."""
    operation: Literal["hire_employee"] = Field("hire_employee", json_schema_extra={"ui:hidden": True})


class TalenthrUpdateEmployeeConfig(_Employee, _Person):
    """Update an employee."""
    operation: Literal["update_employee"] = Field("update_employee", json_schema_extra={"ui:hidden": True})
    work_phone: str | None = Field(None, max_length=191)
    mobile_phone: str | None = Field(None, max_length=191)
    employee_number: str | None = Field(None, max_length=191)
    prevent_email: StrictBool = Field(True, description="Suppress the profile update email where supported.")


class TalenthrTerminateEmployeeConfig(_Employee):
    """Terminate an employee."""
    operation: Literal["terminate_employee"] = Field("terminate_employee", json_schema_extra={"ui:hidden": True})
    effective_date: date = Field(..., description="Termination date. Starts offboarding, emails task owners, reassigns reports and tasks, and removes future records and unanswered/rejected leave requests. Same-day termination revokes access immediately.")
    termination_reason: str | None = Field(None, max_length=4000)
    termination_type: Literal["termination", "resignation"] | None = None
    regrettable_status: Literal["regrettable"] | None = None


class TalenthrListDepartmentsConfig(_Input):
    """Get all the departments."""
    operation: Literal["list_departments"] = Field("list_departments", json_schema_extra={"ui:hidden": True})


class TalenthrGetDepartmentConfig(_Department):
    """Get  a department."""
    operation: Literal["get_department"] = Field("get_department", json_schema_extra={"ui:hidden": True})


class TalenthrCreateDepartmentConfig(_Input):
    """Create a department."""
    operation: Literal["create_department"] = Field("create_department", json_schema_extra={"ui:hidden": True})
    name: Name


class TalenthrUpdateDepartmentConfig(_Department):
    """Update a department."""
    operation: Literal["update_department"] = Field("update_department", json_schema_extra={"ui:hidden": True})
    name: Name


class TalenthrDeleteDepartmentConfig(_Department):
    """Delete a department."""
    operation: Literal["delete_department"] = Field("delete_department", json_schema_extra={"ui:hidden": True})


class TalenthrListLocationsConfig(_Input):
    """Get all the locations."""
    operation: Literal["list_locations"] = Field("list_locations", json_schema_extra={"ui:hidden": True})


class TalenthrGetLocationConfig(_Location):
    """Get  a location."""
    operation: Literal["get_location"] = Field("get_location", json_schema_extra={"ui:hidden": True})


class TalenthrDeleteLocationConfig(_Location):
    """Delete a location."""
    operation: Literal["delete_location"] = Field("delete_location", json_schema_extra={"ui:hidden": True})


class TalenthrListTimeOffTypesConfig(_Input):
    """Get time off types."""
    operation: Literal["list_time_off_types"] = Field("list_time_off_types", json_schema_extra={"ui:hidden": True})


class TalenthrListTimeOffRequestsConfig(_Employee, _Page):
    """Get employee's time off requests."""
    operation: Literal["list_time_off_requests"] = Field("list_time_off_requests", json_schema_extra={"ui:hidden": True})
    sort: str | None = None


class TalenthrReplyTimeOffRequestConfig(_Request):
    """Approve or reject time off request."""
    operation: Literal["reply_time_off_request"] = Field("reply_time_off_request", json_schema_extra={"ui:hidden": True})
    accept: StrictBool = Field(..., description="True approves; false rejects. TalentHR emails the decision to the employee.")


class TalenthrCancelTimeOffRequestConfig(_Request):
    """Cancel time off request."""
    operation: Literal["cancel_time_off_request"] = Field("cancel_time_off_request", json_schema_extra={"ui:hidden": True})


class TalenthrListEmployeeJobRecordsConfig(_Employee):
    """Get employee's job-records."""
    operation: Literal["list_employee_job_records"] = Field("list_employee_job_records", json_schema_extra={"ui:hidden": True})


class TalenthrGetEmployeeJobConfig(_Employee):
    """Get employee job info."""
    operation: Literal["get_employee_job"] = Field("get_employee_job", json_schema_extra={"ui:hidden": True})


class TalenthrListTimeOffBudgetsConfig(_Employee):
    """Get employee's time off budgets."""
    operation: Literal["list_time_off_budgets"] = Field("list_time_off_budgets", json_schema_extra={"ui:hidden": True})


TalenthrConfig = Annotated[Union[
    TalenthrListEmployeesConfig,
    TalenthrGetEmployeeConfig,
    TalenthrHireEmployeeConfig,
    TalenthrUpdateEmployeeConfig,
    TalenthrTerminateEmployeeConfig,
    TalenthrListDepartmentsConfig,
    TalenthrGetDepartmentConfig,
    TalenthrCreateDepartmentConfig,
    TalenthrUpdateDepartmentConfig,
    TalenthrDeleteDepartmentConfig,
    TalenthrListLocationsConfig,
    TalenthrGetLocationConfig,
    TalenthrDeleteLocationConfig,
    TalenthrListTimeOffTypesConfig,
    TalenthrListTimeOffRequestsConfig,
    TalenthrReplyTimeOffRequestConfig,
    TalenthrCancelTimeOffRequestConfig,
    TalenthrListEmployeeJobRecordsConfig,
    TalenthrGetEmployeeJobConfig,
    TalenthrListTimeOffBudgetsConfig
], Field(discriminator="operation")]


class TalenthrFullConfig(NodeConfig[TalenthrConfig, TalenthrApiKeyCredential]):
    pass


OPERATIONS = {
    "list_employees": ("GET", "/directory"),
    "get_employee": ("GET", "/employees/{employee_id}"),
    "hire_employee": ("POST", "/employees/hire"),
    "update_employee": ("PUT", "/employees/{employee_id}"),
    "terminate_employee": ("POST", "/employees/{employee_id}/terminate"),
    "list_departments": ("GET", "/departments"),
    "get_department": ("GET", "/departments/{department_id}"),
    "create_department": ("POST", "/departments"),
    "update_department": ("PUT", "/departments/{department_id}"),
    "delete_department": ("DELETE", "/departments/{department_id}"),
    "list_locations": ("GET", "/locations"),
    "get_location": ("GET", "/locations/{location_id}"),
    "delete_location": ("DELETE", "/locations/{location_id}"),
    "list_time_off_types": ("GET", "/time-off-types"),
    "list_time_off_requests": ("GET", "/employees/{employee_id}/time-off-requests"),
    "reply_time_off_request": ("POST", "/employees/{employee_id}/time-off-requests/{request_id}/reply"),
    "cancel_time_off_request": ("DELETE", "/employees/{employee_id}/time-off-requests/{request_id}"),
    "list_employee_job_records": ("GET", "/employees/{employee_id}/job-records"),
    "get_employee_job": ("GET", "/employees/{employee_id}/job"),
    "list_time_off_budgets": ("GET", "/employees/{employee_id}/time-off-budgets"),
}


class TalenthrNode(WorkflowNode):
    integration_type = "automation-talenthr"
    connection_evidence = ConnectionEvidence(noun="departments", operation="list_departments")

    @classmethod
    def get_config_model(cls):
        return TalenthrFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a TalentHR API key")
        config = self.config.config
        method, template = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        path_values = {name: values.pop(name) for name in ("employee_id", "department_id", "location_id", "request_id") if "{" + name + "}" in template}
        path = template.format(**path_values)
        # Hire requires the manager key even when its value is explicitly null.
        if config.operation == "hire_employee":
            values["reports_to_employee_id"] = config.reports_to_employee_id
        token = self.config.credentials.api_key
        headers = {"Accept": "application/json", "Authorization": "Basic " + base64.b64encode((token + ":").encode()).decode("ascii")}
        kwargs = {}
        if method == "GET":
            kwargs["params"] = values
        elif values:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        response.raise_for_status()
        if "application/json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("TalentHR returned a web page instead of an API response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TalentHR returned an unexpected JSON response")
        if payload.get("success") is False or payload.get("error"):
            raise ValueError(str(payload.get("error") or "TalentHR did not confirm the operation"))
        # Preserve the saved examples verbatim, including the collection's unusual
        # quoted keys on list_time_off_requests; do not invent a response schema.
        return {"status": "success", "operation": config.operation, "data": payload}
