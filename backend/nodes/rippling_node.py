"""Rippling REST API: employees (workers), departments, leave and supergroups.

Contract: https://developer.rippling.com/docs/rest-beta.yaml (2024-08-01).
Each operation performs exactly one documented request. Pagination is explicit;
next_link stays in data and is never followed with credentials to another host.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
from time import perf_counter

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://rest.ripplingapis.com"
API_VERSION = "2024-08-01"


class RipplingAPITokenCredential(BaseModel):
    credential_type: Literal["rippling_api_token"] = Field("rippling_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", description="Paste the token generated in Rippling's Developer app.", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Rippling API Token", json_schema_extra={
        "x-credential-url": "https://app.rippling.com/api-tokens/tokens",
        "x-credential-instructions": "In Rippling, open Tools → Developer → API Tokens and create a token. Select companies.read for connection verification, workers.read, departments.read and departments.read-write, leave-requests.read and leave-requests.read-write, leave-types.read, leave-balances.read, supergroups.read and supergroups.read-write for the operations you use. Your permission profile and Rippling API plan also limit access. Copy the token once and paste it here.",
    })


class RipplingListCompaniesConfig(BaseModel):
    """List companies."""
    operation: Literal['list_companies'] = Field('list_companies', title='List Companies', json_schema_extra={"ui:hidden": True, "x-category": 'Companies', "x-display-name": 'List Companies', "x-is-trigger": False})
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingListWorkersConfig(BaseModel):
    """List workers."""
    operation: Literal['list_workers'] = Field('list_workers', title='List Workers', json_schema_extra={"ui:hidden": True, "x-category": 'Employees', "x-display-name": 'List Workers', "x-is-trigger": False})
    filter: str | None = Field(None, description='Rippling filter expression, such as status eq "ACTIVE".')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingGetWorkerConfig(BaseModel):
    """Retrieve a specific worker."""
    operation: Literal['get_worker'] = Field('get_worker', title='Get Worker', json_schema_extra={"ui:hidden": True, "x-category": 'Employees', "x-display-name": 'Get Worker', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to return')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')

class RipplingListDepartmentsConfig(BaseModel):
    """List departments."""
    operation: Literal['list_departments'] = Field('list_departments', title='List Departments', json_schema_extra={"ui:hidden": True, "x-category": 'Departments', "x-display-name": 'List Departments', "x-is-trigger": False})
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingGetDepartmentConfig(BaseModel):
    """Retrieve a specific department."""
    operation: Literal['get_department'] = Field('get_department', title='Get Department', json_schema_extra={"ui:hidden": True, "x-category": 'Departments', "x-display-name": 'Get Department', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to return')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')

class RipplingCreateDepartmentConfig(BaseModel):
    """Create a new department."""
    operation: Literal['create_department'] = Field('create_department', title='Create Department', json_schema_extra={"ui:hidden": True, "x-category": 'Departments', "x-display-name": 'Create Department', "x-is-trigger": False})
    name: str = Field(..., description='The name of the department.')
    parent_id: str | None = Field(None, description='The parent department.')
    reference_code: str | None = Field(None, description='Reference code of the department.')

class RipplingUpdateDepartmentConfig(BaseModel):
    """Update a department."""
    operation: Literal['update_department'] = Field('update_department', title='Update Department', json_schema_extra={"ui:hidden": True, "x-category": 'Departments', "x-display-name": 'Update Department', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to patch')
    name: str | None = Field(None, description='The name of the department.')
    parent_id: str | None = Field(None, description='The parent department.')
    reference_code: str | None = Field(None, description='Reference code of the department.')

class RipplingListLeaveRequestsConfig(BaseModel):
    """List leave requests."""
    operation: Literal['list_leave_requests'] = Field('list_leave_requests', title='List Leave Requests', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'List Leave Requests', "x-is-trigger": False})
    filter: str | None = Field(None, description='Rippling filter expression, such as status eq "ACTIVE".')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingGetLeaveRequestConfig(BaseModel):
    """Retrieve a specific leave request."""
    operation: Literal['get_leave_request'] = Field('get_leave_request', title='Get Leave Request', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'Get Leave Request', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to return')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')

class RipplingCreateLeaveRequestConfig(BaseModel):
    """Create a new leave request."""
    operation: Literal['create_leave_request'] = Field('create_leave_request', title='Create Leave Request', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'Create Leave Request', "x-is-trigger": False})
    worker_id: str = Field(..., description='The ID of the worker associated with the leave request.')
    requester_id: str | None = Field(None, description='The ID of the worker who requested the leave request.')
    status: Literal["PENDING", "APPROVED"] = Field(..., description='The status of the leave request.')
    start_date: str = Field(..., description='The start date of the leave request.')
    start_time: str | None = Field(None, description='The start time of the leave request.')
    end_date: str = Field(..., description='The end date of the leave request.')
    end_time: str | None = Field(None, description='The end time of the leave request.')
    start_date_custom_hours: float | None = Field(None, description='The number of hours to take off on the start date.')
    end_date_custom_hours: float | None = Field(None, description='The number of hours to take off on the end date.')
    comments: str | None = Field(None, description='The comments associated with the leave request.')
    leave_policy_id: str | None = Field(None, description='The ID of the leave policy associated with the leave request, either leave_policy_id or leave_type_id must be provided.')
    leave_type_id: str | None = Field(None, description='The ID of the leave type associated with the leave request, either leave_policy_id or leave_type_id must be provided.')
    leave_event_id: str | None = Field(None, description='The ID of the leave event associated with the leave request, if any.')
    reason_for_leave: str | None = Field(None, description='The reason for the leave request.')
    reviewer_id: str | None = Field(None, description='The ID of the worker who reviewed the leave request.')
    reviewed_at: str | None = Field(None, description='The timestamp of when the leave request was reviewed.')

    @model_validator(mode="after")
    def require_leave_type_or_policy(self):
        if not self.leave_type_id and not self.leave_policy_id:
            raise ValueError("Supply a leave_type_id or leave_policy_id from Rippling.")
        return self

class RipplingUpdateLeaveRequestConfig(BaseModel):
    """Update a leave request."""
    operation: Literal['update_leave_request'] = Field('update_leave_request', title='Update Leave Request', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'Update Leave Request', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to patch')
    worker_id: str | None = Field(None, description='The ID of the worker associated with the leave request.')
    requester_id: str | None = Field(None, description='The ID of the worker who requested the leave request.')
    status: Literal["PENDING", "APPROVED", "REJECTED", "CANCELED"] | None = Field(None, description='The status of the leave request.')
    start_date: str | None = Field(None, description='The start date of the leave request.')
    start_time: str | None = Field(None, description='The start time of the leave request.')
    end_date: str | None = Field(None, description='The end date of the leave request.')
    end_time: str | None = Field(None, description='The end time of the leave request.')
    start_date_custom_hours: float | None = Field(None, description='The number of hours to take off on the start date.')
    end_date_custom_hours: float | None = Field(None, description='The number of hours to take off on the end date.')
    comments: str | None = Field(None, description='The comments associated with the leave request.')
    leave_policy_id: str | None = Field(None, description='The ID of the leave policy associated with the leave request, either leave_policy_id or leave_type_id must be provided.')
    leave_type_id: str | None = Field(None, description='The ID of the leave type associated with the leave request, either leave_policy_id or leave_type_id must be provided.')
    leave_event_id: str | None = Field(None, description='The ID of the leave event associated with the leave request, if any.')
    reason_for_leave: str | None = Field(None, description='The reason for the leave request.')
    reviewer_id: str | None = Field(None, description='The ID of the worker who reviewed the leave request.')
    reviewed_at: str | None = Field(None, description='The timestamp of when the leave request was reviewed.')

class RipplingListLeaveTypesConfig(BaseModel):
    """List leave types."""
    operation: Literal['list_leave_types'] = Field('list_leave_types', title='List Leave Types', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'List Leave Types', "x-is-trigger": False})
    filter: str | None = Field(None, description='Rippling filter expression, such as status eq "ACTIVE".')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingGetLeaveTypeConfig(BaseModel):
    """Retrieve a specific leave type."""
    operation: Literal['get_leave_type'] = Field('get_leave_type', title='Get Leave Type', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'Get Leave Type', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to return')

class RipplingListLeaveBalancesConfig(BaseModel):
    """List leave balances."""
    operation: Literal['list_leave_balances'] = Field('list_leave_balances', title='List Leave Balances', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'List Leave Balances', "x-is-trigger": False})
    filter: str | None = Field(None, description='Rippling filter expression, such as status eq "ACTIVE".')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingGetLeaveBalanceConfig(BaseModel):
    """Retrieve a specific leave balance."""
    operation: Literal['get_leave_balance'] = Field('get_leave_balance', title='Get Leave Balance', json_schema_extra={"ui:hidden": True, "x-category": 'Leave', "x-display-name": 'Get Leave Balance', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to return')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')

class RipplingListSupergroupsConfig(BaseModel):
    """List supergroups."""
    operation: Literal['list_supergroups'] = Field('list_supergroups', title='List Supergroups', json_schema_extra={"ui:hidden": True, "x-category": 'Groups', "x-display-name": 'List Supergroups', "x-is-trigger": False})
    filter: str | None = Field(None, description='Rippling filter expression, such as status eq "ACTIVE".')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingGetSupergroupConfig(BaseModel):
    """Retrieve a specific supergroup."""
    operation: Literal['get_supergroup'] = Field('get_supergroup', title='Get Supergroup', json_schema_extra={"ui:hidden": True, "x-category": 'Groups', "x-display-name": 'Get Supergroup', "x-is-trigger": False})
    id: str = Field(..., description='ID of the resource to return')

class RipplingListSupergroupMembersConfig(BaseModel):
    """List supergroup members."""
    operation: Literal['list_supergroup_members'] = Field('list_supergroup_members', title='List Supergroup Members', json_schema_extra={"ui:hidden": True, "x-category": 'Groups', "x-display-name": 'List Supergroup Members', "x-is-trigger": False})
    group_id: str = Field(..., description='The unique identifier of the group.')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingListInclusionMembersConfig(BaseModel):
    """List supergroup inclusion members."""
    operation: Literal['list_inclusion_members'] = Field('list_inclusion_members', title='List Inclusion Members', json_schema_extra={"ui:hidden": True, "x-category": 'Groups', "x-display-name": 'List Inclusion Members', "x-is-trigger": False})
    group_id: str = Field(..., description='The unique identifier of the group.')
    expand: str | None = Field(None, description='Comma-separated related fields to expand; workers may use user (requires users.read).')
    order_by: str | None = Field(None, description='Rippling ordering expression.')
    limit: int = Field(50, description='The maximum number of results to return. Defaults to 50. Maximum is 100.', ge=1, le=100)
    cursor: str | None = Field(None, description='Cursor from the previous response next_link.')

class RipplingUpdateInclusionMembersConfig(BaseModel):
    """Update supergroup inclusion members."""
    operation: Literal['update_inclusion_members'] = Field('update_inclusion_members', title='Update Inclusion Members', json_schema_extra={"ui:hidden": True, "x-category": 'Groups', "x-display-name": 'Update Inclusion Members', "x-is-trigger": False})
    group_id: str = Field(..., description='The unique identifier of the group.')
    member_action: Literal["add", "remove"] = Field("add", description="Add or remove workers from the explicit inclusion list.")
    member_ids: str = Field(..., description="JSON array of worker IDs from List Workers.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @model_validator(mode="after")
    def valid_member_ids(self):
        _member_ids(self.member_ids)
        return self


def _member_ids(value: str) -> list[str]:
    import json
    try:
        ids = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Member IDs must be a JSON array of worker IDs.") from exc
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i.strip() for i in ids):
        raise ValueError("Member IDs must be a nonempty JSON array of worker IDs.")
    return ids

RipplingConfig = Annotated[Union[
    RipplingListCompaniesConfig,
    RipplingListWorkersConfig,
    RipplingGetWorkerConfig,
    RipplingListDepartmentsConfig,
    RipplingGetDepartmentConfig,
    RipplingCreateDepartmentConfig,
    RipplingUpdateDepartmentConfig,
    RipplingListLeaveRequestsConfig,
    RipplingGetLeaveRequestConfig,
    RipplingCreateLeaveRequestConfig,
    RipplingUpdateLeaveRequestConfig,
    RipplingListLeaveTypesConfig,
    RipplingGetLeaveTypeConfig,
    RipplingListLeaveBalancesConfig,
    RipplingGetLeaveBalanceConfig,
    RipplingListSupergroupsConfig,
    RipplingGetSupergroupConfig,
    RipplingListSupergroupMembersConfig,
    RipplingListInclusionMembersConfig,
    RipplingUpdateInclusionMembersConfig,
], Discriminator("operation")]


class RipplingNodeConfig(NodeConfig[RipplingConfig, RipplingAPITokenCredential]):
    pass


OPERATIONS = {
    'list_companies': ('GET', '/companies/'),
    'list_workers': ('GET', '/workers/'),
    'get_worker': ('GET', '/workers/{id}/'),
    'list_departments': ('GET', '/departments/'),
    'get_department': ('GET', '/departments/{id}/'),
    'create_department': ('POST', '/departments/'),
    'update_department': ('PATCH', '/departments/{id}/'),
    'list_leave_requests': ('GET', '/leave-requests/'),
    'get_leave_request': ('GET', '/leave-requests/{id}/'),
    'create_leave_request': ('POST', '/leave-requests/'),
    'update_leave_request': ('PATCH', '/leave-requests/{id}/'),
    'list_leave_types': ('GET', '/leave-types/'),
    'get_leave_type': ('GET', '/leave-types/{id}/'),
    'list_leave_balances': ('GET', '/leave-balances/'),
    'get_leave_balance': ('GET', '/leave-balances/{id}/'),
    'list_supergroups': ('GET', '/supergroups/'),
    'get_supergroup': ('GET', '/supergroups/{id}/'),
    'list_supergroup_members': ('GET', '/supergroups/{group_id}/members/'),
    'list_inclusion_members': ('GET', '/supergroups/{group_id}/inclusion-members/'),
    'update_inclusion_members': ('PATCH', '/supergroups/{group_id}/inclusion-members/'),
}


class RipplingNode(WorkflowNode):
    integration_type = "automation-rippling"
    credential_provider_labels = {"rippling": "Rippling Account"}
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies")
    edit_examples = ["List employees with their user profiles", "Create a department", "Request vacation leave", "Add workers to a supergroup"]

    @classmethod
    def get_config_model(cls):
        return RipplingNodeConfig

    async def execute(self, inputs):
        started = perf_counter()
        if not isinstance(self.config, RipplingNodeConfig) or not self.config.credentials:
            raise ValueError("Add a Rippling API token to run this operation.")
        config = self.config.config
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("id", "group_id"):
            if key in values:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = None
        body = None
        if method == "GET":
            params = {k: v for k, v in values.items() if v != ""}
        elif config.operation == "update_inclusion_members":
            body = {"Operations": [{"op": config.member_action, "value": [{"id": i} for i in _member_ids(config.member_ids)]}]}
        else:
            body = values
        headers = {"Authorization": f"Bearer {self.config.credentials.api_token}", "Accept": "application/json", "Rippling-Api-Version": API_VERSION}
        try:
            # No automatic write retries: create leave is not idempotent.
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, API_BASE + path, headers=headers, params=params, json=body)
            elapsed = round((perf_counter() - started) * 1000, 2)
            if response.is_error:
                error = response.text.replace(self.config.credentials.api_token, "[redacted]")
                return {"status": "error", "action": config.operation, "status_code": response.status_code, "error": error, "timing_ms": {"total": elapsed}}
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Rippling returned an unexpected response; expected an object.")
            if config.operation.startswith("list_") and (not isinstance(data.get("results"), list) or any(not isinstance(row, dict) for row in data["results"])):
                raise ValueError("Rippling returned an unexpected list response; expected results containing objects.")
            if data.get("ok") is False or data.get("error"):
                return {"status": "error", "action": config.operation, "error": str(data).replace(self.config.credentials.api_token, "[redacted]"), "status_code": response.status_code}
            return {"status": "success", "action": config.operation, "data": data, "status_code": response.status_code, "timing_ms": {"api_request": elapsed, "total": elapsed}}
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "error", "action": config.operation, "error": str(exc).replace(self.config.credentials.api_token, "[redacted]"), "timing_ms": {"total": round((perf_counter() - started) * 1000, 2)}}
