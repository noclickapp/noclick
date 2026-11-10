"""Gusto company, employee, payroll and time-off operations using a pasted Bearer token.

Each operation maps to one official API endpoint, pinned to version 2026-06-15.
Company access tokens expire after two hours; replace expired tokens in the credential.
Webhooks require a separate system-token subscription flow and are not exposed here.
Docs: https://docs.gusto.com/app-integrations/llms.txt
"""
from __future__ import annotations

import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

API_VERSION = "2026-06-15"
API_ORIGINS = {"production": "https://api.gusto.com", "demo": "https://api.gusto-demo.com"}


class GustoAccessTokenCredential(BaseModel):
    credential_type: Literal["gusto_access_token"] = Field("gusto_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1,
        description="Company-level Bearer access token issued by your approved Gusto integration. Expires after two hours.",
        json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "demo"] = Field("production", title="Environment",
        description="Use demo for tokens from api.gusto-demo.com; production for api.gusto.com.")
    model_config = ConfigDict(title="Gusto Access Token", json_schema_extra={
        "x-credential-url": "https://docs.gusto.com/app-integrations/docs/oauth2",
        "x-credential-instructions": "Paste an existing company-level access token from your approved Gusto integration and select its environment. Tokens expire after two hours; replace an expired token here. Your integration must grant the scopes listed in each operation's description.",
    })


class GustoFixedCompensation(BaseModel):
    name: str = Field(..., description="Gusto earning type name, such as Bonus.")
    amount: str = Field(..., description="Decimal dollar amount.")
    job_uuid: Optional[str] = None
    model_config = ConfigDict(extra="forbid")


class GustoHourlyCompensation(BaseModel):
    name: str = Field(..., description="Gusto earning type, such as Regular Hours.")
    hours: str = Field(..., description="Decimal hours worked.")
    job_uuid: Optional[str] = None
    model_config = ConfigDict(extra="forbid")


class GustoPaidTimeOff(BaseModel):
    name: Optional[str] = None
    policy_uuid: Optional[str] = None
    hours: str
    model_config = ConfigDict(extra="forbid")


class GustoPayrollEmployee(BaseModel):
    employee_uuid: str
    version: str = Field(..., description="Current employee compensation version from Prepare Payroll.")
    excluded: Optional[bool] = None
    payment_method: Optional[Literal["Direct Deposit", "Check"]] = None
    memo: Optional[str] = None
    fixed_compensations: Optional[List[GustoFixedCompensation]] = None
    hourly_compensations: Optional[List[GustoHourlyCompensation]] = None
    paid_time_off: Optional[List[GustoPaidTimeOff]] = None
    model_config = ConfigDict(extra="forbid")


class GustoPolicyEmployee(BaseModel):
    uuid: str
    balance: Optional[str] = Field(None, description="Starting hours balance for a non-unlimited policy.")
    model_config = ConfigDict(extra="forbid")


class GustoOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GustoCompanyOperation(GustoOperation):
    company_id: str = Field(..., title="Company UUID", min_length=1, description="Company UUID from Get Token Info or Get Company.")


class GustoEmployeeOperation(GustoOperation):
    employee_id: str = Field(..., title="Employee UUID", min_length=1, description="Employee UUID from List Employees.")


class GustoPayrollOperation(GustoCompanyOperation):
    payroll_id: str = Field(..., title="Payroll UUID", min_length=1, description="Payroll UUID from List Payrolls.")


class GustoPolicyOperation(GustoOperation):
    time_off_policy_uuid: str = Field(..., title="Time off policy UUID", min_length=1)


class GustoPagination(BaseModel):
    page: int = Field(1, ge=1, description="Page number. Run the operation again with the next page to retrieve more records.")
    per: int = Field(100, ge=1, le=100, title="Records per page")


class GustoPayrollListBase(GustoCompanyOperation, GustoPagination):
    processed: Optional[bool] = Field(None, description="Filter processed or unprocessed payrolls.")
    start_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    sort_order: Optional[Literal["asc", "desc"]] = None


# https://docs.gusto.com/app-integrations/reference/get-v1-token-info.md
class GustoGetTokenInfoConfig(GustoOperation):
    """Get info about the current access token. Required token scopes: public (any valid token)."""
    operation: Literal["get_token_info"] = Field("get_token_info", title="Get Token Info", json_schema_extra={"const": "get_token_info", "ui:hidden": True, "x-category": "Account", "x-display-name": "Get Token Info", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/get-v1-companies.md
class GustoGetCompanyConfig(GustoCompanyOperation):
    """Get a company. Required token scopes: companies:read."""
    operation: Literal["get_company"] = Field("get_company", title="Get Company", json_schema_extra={"const": "get_company", "ui:hidden": True, "x-category": "Companies", "x-display-name": "Get Company", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/put-v1-companies.md
class GustoUpdateCompanyConfig(GustoCompanyOperation):
    """Update a company. Required token scopes: companies:write."""
    operation: Literal["update_company"] = Field("update_company", title="Update Company", json_schema_extra={"const": "update_company", "ui:hidden": True, "x-category": "Companies", "x-display-name": "Update Company", "x-is-trigger": False})
    contractor_only: Literal[False] = Field(..., description="Set false to enable W-2 employees. Gusto permits only true to false; additional onboarding is required.")


# https://docs.gusto.com/app-integrations/reference/get-v1-companies-company_id-locations.md
class GustoListLocationsConfig(GustoCompanyOperation, GustoPagination):
    """Get all company locations. Required token scopes: companies:read."""
    operation: Literal["list_locations"] = Field("list_locations", title="List Locations", json_schema_extra={"const": "list_locations", "ui:hidden": True, "x-category": "Companies", "x-display-name": "List Locations", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/get-v1-companies-company_id-employees.md
class GustoListEmployeesConfig(GustoCompanyOperation, GustoPagination):
    """Get employees of a company. Required token scopes: employees:read."""
    operation: Literal["list_employees"] = Field("list_employees", title="List Employees", json_schema_extra={"const": "list_employees", "ui:hidden": True, "x-category": "Employees", "x-display-name": "List Employees", "x-is-trigger": False})
    search_term: Optional[str] = Field(None, description="Search employees by name or email.")
    onboarded: Optional[bool] = None
    terminated: Optional[bool] = None


# https://docs.gusto.com/app-integrations/reference/get-v1-employees.md
class GustoGetEmployeeConfig(GustoEmployeeOperation):
    """Get an employee. Required token scopes: employees:read."""
    operation: Literal["get_employee"] = Field("get_employee", title="Get Employee", json_schema_extra={"const": "get_employee", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Get Employee", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/post-v1-employees.md
class GustoCreateEmployeeConfig(GustoCompanyOperation):
    """Create an employee. Required token scopes: employees:manage."""
    operation: Literal["create_employee"] = Field("create_employee", title="Create Employee", json_schema_extra={"const": "create_employee", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Create Employee", "x-is-trigger": False})
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    middle_initial: Optional[str] = None
    email: Optional[str] = Field(None, description="Personal email. Required by Gusto when self_onboarding is true.")
    work_email: Optional[str] = None
    date_of_birth: Optional[str] = Field(None, description="YYYY-MM-DD")
    self_onboarding: bool = Field(False, description="Whether the employee will complete their own onboarding.")


# https://docs.gusto.com/app-integrations/reference/put-v1-employees.md
class GustoUpdateEmployeeConfig(GustoEmployeeOperation):
    """Update an employee.. Required token scopes: employees:write."""
    operation: Literal["update_employee"] = Field("update_employee", title="Update Employee", json_schema_extra={"const": "update_employee", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Update Employee", "x-is-trigger": False})
    version: str = Field(..., min_length=1, description="Current version from Get Employee; required for optimistic concurrency.")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_initial: Optional[str] = None
    preferred_first_name: Optional[str] = None
    email: Optional[str] = None
    work_email: Optional[str] = None
    date_of_birth: Optional[str] = Field(None, description="YYYY-MM-DD")
    two_percent_shareholder: Optional[bool] = None


# https://docs.gusto.com/app-integrations/reference/delete-v1-employee.md
class GustoDeleteEmployeeConfig(GustoEmployeeOperation):
    """Delete an onboarding employee. Required token scopes: employees:manage."""
    operation: Literal["delete_employee"] = Field("delete_employee", title="Delete Employee", json_schema_extra={"const": "delete_employee", "ui:hidden": True, "x-category": "Employees", "x-display-name": "Delete Employee", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/get-v1-companies-company_id-payrolls.md
class GustoListPayrollsConfig(GustoPayrollListBase):
    """Get all payrolls for a company. Required token scopes: payrolls:read."""
    operation: Literal["list_payrolls"] = Field("list_payrolls", title="List Payrolls", json_schema_extra={"const": "list_payrolls", "ui:hidden": True, "x-category": "Payrolls", "x-display-name": "List Payrolls", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/get-v1-companies-company_id-payrolls-payroll_id.md
class GustoGetPayrollConfig(GustoPayrollOperation, GustoPagination):
    """Get a single payroll. Required token scopes: payrolls:read."""
    operation: Literal["get_payroll"] = Field("get_payroll", title="Get Payroll", json_schema_extra={"const": "get_payroll", "ui:hidden": True, "x-category": "Payrolls", "x-display-name": "Get Payroll", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/put-v1-companies-company_id-payrolls.md
class GustoUpdatePayrollConfig(GustoPayrollOperation):
    """Update a payroll by ID. Required token scopes: payrolls:write."""
    operation: Literal["update_payroll"] = Field("update_payroll", title="Update Payroll", json_schema_extra={"const": "update_payroll", "ui:hidden": True, "x-category": "Payrolls", "x-display-name": "Update Payroll", "x-is-trigger": False})
    employee_compensations: Json[List[GustoPayrollEmployee]] = Field(..., description="JSON array of employee compensations, with current versions from Prepare Payroll. Supports fixed earnings, hourly earnings and paid time off.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    withholding_pay_period: Optional[Literal["Every week", "Every other week", "Twice per month", "Monthly", "Quarterly", "Semiannually", "Annually"]] = None
    skip_regular_deductions: Optional[bool] = None
    fixed_withholding_rate: Optional[bool] = None


# https://docs.gusto.com/app-integrations/reference/put-v1-companies-company_id-payrolls-payroll_id-prepare.md
class GustoPreparePayrollConfig(GustoPayrollOperation, GustoPagination):
    """Prepare a payroll for update. Required token scopes: payrolls:write, employees:read."""
    operation: Literal["prepare_payroll"] = Field("prepare_payroll", title="Prepare Payroll", json_schema_extra={"const": "prepare_payroll", "ui:hidden": True, "x-category": "Payrolls", "x-display-name": "Prepare Payroll", "x-is-trigger": False})
    employee_uuids: Optional[Json[List[str]]] = Field(None, description="Optional JSON array of employee UUIDs. Omit to prepare all existing payroll employees.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


# https://docs.gusto.com/app-integrations/reference/get-v1-companies-company_uuid-time_off_policies.md
class GustoListTimeOffPoliciesConfig(GustoCompanyOperation):
    """Get all time off policies for a company. Required token scopes: time_off_policies:read."""
    operation: Literal["list_time_off_policies"] = Field("list_time_off_policies", title="List Time Off Policies", json_schema_extra={"const": "list_time_off_policies", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "List Time Off Policies", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/get-v1-time_off_policies-time_off_policy_uuid.md
class GustoGetTimeOffPolicyConfig(GustoPolicyOperation):
    """Get a time off policy. Required token scopes: time_off_policies:read."""
    operation: Literal["get_time_off_policy"] = Field("get_time_off_policy", title="Get Time Off Policy", json_schema_extra={"const": "get_time_off_policy", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Get Time Off Policy", "x-is-trigger": False})


# https://docs.gusto.com/app-integrations/reference/put-v1-time_off_policies-time_off_policy_uuid-add_employees.md
class GustoAddEmployeesToTimeOffPolicyConfig(GustoPolicyOperation):
    """Add employees to a time off policy. Required token scopes: time_off_policies:write."""
    operation: Literal["add_employees_to_time_off_policy"] = Field("add_employees_to_time_off_policy", title="Add Employees To Time Off Policy", json_schema_extra={"const": "add_employees_to_time_off_policy", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Add Employees To Time Off Policy", "x-is-trigger": False})
    employees: Json[List[GustoPolicyEmployee]] = Field(..., description='JSON array of {"uuid": "employee UUID", "balance": "starting hours"}. Employees must have a job.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


# https://docs.gusto.com/app-integrations/reference/get-v1-companies-company_id-time_off_requests.md
class GustoListTimeOffRequestsConfig(GustoCompanyOperation):
    """Get time off requests for a company. Required token scopes: time_off_requests:read."""
    operation: Literal["list_time_off_requests"] = Field("list_time_off_requests", title="List Time Off Requests", json_schema_extra={"const": "list_time_off_requests", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "List Time Off Requests", "x-is-trigger": False})
    start_date: Optional[str] = Field(None, description="Include requests on or after this date (YYYY-MM-DD).")
    end_date: Optional[str] = Field(None, description="Include requests on or before this date (YYYY-MM-DD).")


# https://docs.gusto.com/app-integrations/reference/get-version-employees-time_off_activities.md
class GustoGetTimeOffActivitiesConfig(GustoEmployeeOperation):
    """Get employee time off activities. Required token scopes: employee_time_off_activities:read."""
    operation: Literal["get_time_off_activities"] = Field("get_time_off_activities", title="Get Time Off Activities", json_schema_extra={"const": "get_time_off_activities", "ui:hidden": True, "x-category": "Time Off", "x-display-name": "Get Time Off Activities", "x-is-trigger": False})
    time_off_type: str = Field(..., description="Gusto time off type, for example vacation or sick.")


GustoConfig = Annotated[Union[
    GustoGetTokenInfoConfig,
    GustoGetCompanyConfig,
    GustoUpdateCompanyConfig,
    GustoListLocationsConfig,
    GustoListEmployeesConfig,
    GustoGetEmployeeConfig,
    GustoCreateEmployeeConfig,
    GustoUpdateEmployeeConfig,
    GustoDeleteEmployeeConfig,
    GustoListPayrollsConfig,
    GustoGetPayrollConfig,
    GustoUpdatePayrollConfig,
    GustoPreparePayrollConfig,
    GustoListTimeOffPoliciesConfig,
    GustoGetTimeOffPolicyConfig,
    GustoAddEmployeesToTimeOffPolicyConfig,
    GustoListTimeOffRequestsConfig,
    GustoGetTimeOffActivitiesConfig,
], Field(discriminator="operation")]


class GustoNodeConfig(NodeConfig[GustoConfig, GustoAccessTokenCredential]):
    model_config = ConfigDict(title="Gusto Node Configuration")

# Scope requirements come from the official endpoint descriptions linked above.
# Tokens are pasted, so NoClick does not initiate an OAuth authorization flow.
GUSTO_SCOPES = ScopeRegistry("gusto", {
    "get_token_info": ScopeRequirement(scopes=()),
    "get_company": ScopeRequirement(scopes=('companies:read',)),
    "update_company": ScopeRequirement(scopes=('companies:write',)),
    "list_locations": ScopeRequirement(scopes=('companies:read',)),
    "list_employees": ScopeRequirement(scopes=('employees:read',)),
    "get_employee": ScopeRequirement(scopes=('employees:read',)),
    "create_employee": ScopeRequirement(scopes=('employees:manage',)),
    "update_employee": ScopeRequirement(scopes=('employees:write',)),
    "delete_employee": ScopeRequirement(scopes=('employees:manage',)),
    "list_payrolls": ScopeRequirement(scopes=('payrolls:read',)),
    "get_payroll": ScopeRequirement(scopes=('payrolls:read',)),
    "update_payroll": ScopeRequirement(scopes=('payrolls:write',)),
    "prepare_payroll": ScopeRequirement(scopes=('payrolls:write', 'employees:read')),
    "list_time_off_policies": ScopeRequirement(scopes=('time_off_policies:read',)),
    "get_time_off_policy": ScopeRequirement(scopes=('time_off_policies:read',)),
    "add_employees_to_time_off_policy": ScopeRequirement(scopes=('time_off_policies:write',)),
    "list_time_off_requests": ScopeRequirement(scopes=('time_off_requests:read',)),
    "get_time_off_activities": ScopeRequirement(scopes=('employee_time_off_activities:read',)),
})

# Each operation is exactly one documented request. Path aliases only adapt UI
# field names to Gusto's inconsistent company_id/company_uuid naming.
ROUTES = {
    "get_token_info": [
        "GET",
        "/v1/token_info"
    ],
    "get_company": [
        "GET",
        "/v1/companies/{company_id}"
    ],
    "update_company": [
        "PUT",
        "/v1/companies/{company_id}"
    ],
    "list_locations": [
        "GET",
        "/v1/companies/{company_id}/locations"
    ],
    "list_employees": [
        "GET",
        "/v1/companies/{company_id}/employees"
    ],
    "get_employee": [
        "GET",
        "/v1/employees/{employee_id}"
    ],
    "create_employee": [
        "POST",
        "/v1/companies/{company_id}/employees"
    ],
    "update_employee": [
        "PUT",
        "/v1/employees/{employee_id}"
    ],
    "delete_employee": [
        "DELETE",
        "/v1/employees/{employee_id}"
    ],
    "list_payrolls": [
        "GET",
        "/v1/companies/{company_id}/payrolls"
    ],
    "get_payroll": [
        "GET",
        "/v1/companies/{company_id}/payrolls/{payroll_id}"
    ],
    "update_payroll": [
        "PUT",
        "/v1/companies/{company_id}/payrolls/{payroll_id}"
    ],
    "prepare_payroll": [
        "PUT",
        "/v1/companies/{company_id}/payrolls/{payroll_id}/prepare"
    ],
    "list_time_off_policies": [
        "GET",
        "/v1/companies/{company_uuid}/time_off_policies"
    ],
    "get_time_off_policy": [
        "GET",
        "/v1/time_off_policies/{time_off_policy_uuid}"
    ],
    "add_employees_to_time_off_policy": [
        "PUT",
        "/v1/time_off_policies/{time_off_policy_uuid}/add_employees"
    ],
    "list_time_off_requests": [
        "GET",
        "/v1/companies/{company_id}/time_off_requests"
    ],
    "get_time_off_activities": [
        "GET",
        "/v1/employees/{employee_uuid}/time_off_activities"
    ]
}
PATH_ALIASES = {"company_uuid": "company_id", "employee_uuid": "employee_id"}
QUERY_FIELDS = {
    "get_token_info": [],
    "get_company": [],
    "update_company": [],
    "list_locations": [
        "page",
        "per"
    ],
    "list_employees": [
        "location_uuid",
        "payroll_uuid",
        "search_term",
        "sort_by",
        "include",
        "onboarded",
        "onboarded_active",
        "terminated",
        "terminated_today",
        "uuids",
        "page",
        "per"
    ],
    "get_employee": [
        "include"
    ],
    "create_employee": [],
    "update_employee": [],
    "delete_employee": [],
    "list_payrolls": [
        "processing_statuses",
        "payroll_types",
        "processed",
        "include_off_cycle",
        "include",
        "start_date",
        "end_date",
        "date_filter_by",
        "page",
        "per",
        "sort_order"
    ],
    "get_payroll": [
        "include",
        "page",
        "per",
        "sort_by"
    ],
    "update_payroll": [],
    "prepare_payroll": [
        "page",
        "per",
        "sort_by"
    ],
    "list_time_off_policies": [],
    "get_time_off_policy": [],
    "add_employees_to_time_off_policy": [],
    "list_time_off_requests": [
        "start_date",
        "end_date"
    ],
    "get_time_off_activities": [
        "time_off_type"
    ]
}


class GustoNode(WorkflowNode):
    integration_type = "automation-gusto"
    credential_provider_labels = {"gusto": "Gusto Account"}
    scope_registry = GUSTO_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="authorized account", identity_operation="get_token_info", identity_keys=("uuid",),
    )

    @classmethod
    def get_config_model(cls):
        return GustoNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, GustoNodeConfig):
            raise ValueError("Valid Gusto configuration is required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Gusto access token is required")
        config = self.config.config
        action = config.operation
        self.scope_registry.require(action)
        method, path = ROUTES[action]
        values = config.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        for placeholder in ("company_id", "company_uuid", "employee_id", "employee_uuid", "payroll_id", "time_off_policy_uuid"):
            if "{" + placeholder + "}" in path:
                value = values.pop(PATH_ALIASES.get(placeholder, placeholder))
                path = path.replace("{" + placeholder + "}", quote(value, safe=""))
        params = {key: values.pop(key) for key in QUERY_FIELDS[action] if key in values}
        # httpx uses lowercase booleans in query strings. False is intentional
        # and must survive both query and request-body serialization.
        request_args: Dict[str, Any] = {"params": params}
        if method in ("POST", "PUT", "PATCH"):
            request_args["json"] = values
        headers = {
            "Authorization": f"Bearer {credential.access_token}",
            "X-Gusto-API-Version": API_VERSION,
            "Accept": "application/json",
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, API_ORIGINS[credential.environment] + path, headers=headers, **request_args)
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            if not response.is_success:
                return {"status": "error", "action": action, "status_code": response.status_code,
                    "error": response.text, "timing_ms": {"api_request": elapsed, "total": elapsed}}
            data = {} if response.status_code == 204 else response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Gusto returned an invalid JSON response; expected an object or array")
            result: Dict[str, Any] = {"status": "success", "action": action, "data": data,
                "status_code": response.status_code, "timing_ms": {"api_request": elapsed, "total": elapsed}}
            # A successful token-info response must identify an account before
            # the shared evidence collector can call the credential working.
            if action == "get_token_info":
                resource = data.get("resource") if isinstance(data, dict) else None
                if not isinstance(resource, dict) or not resource.get("uuid") or not resource.get("type"):
                    raise ValueError("Gusto token info omitted the authorized resource")
            pagination = {key: response.headers[key] for key in ("x-page", "x-per-page", "x-total-pages", "x-total-count") if key in response.headers}
            if pagination:
                result["pagination"] = pagination
            return result
        except httpx.RequestError as exc:
            # RequestError may contain the request; never return its headers.
            return {"status": "error", "action": action, "error": f"Gusto request failed ({type(exc).__name__})"}
