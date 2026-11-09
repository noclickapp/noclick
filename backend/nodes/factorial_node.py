"""Factorial 2026-10-01 HR operations and API-registered webhook subscriptions.

Contract: https://api.factorialhr.com/oas/?version=2026-10-01
API keys are for a person's own company's internal workflows (not marketplace apps).
Delivery verification is an echoed secret challenge, not a body signature:
https://apidoc.factorialhr.com/docs/manage-webhooks
"""
from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.factorialhr.com/api/2026-10-01/resources"
VERSION = "2026-10-01"


class FactorialAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Factorial API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://apidoc.factorialhr.com/docs/api-keys",
        "x-credential-instructions": "For internal workflows in your own company, paste an API key from Factorial: Configuration → API → Create API Key. A company administrator must create it. Keys grant full company access and do not expire. Factorial requires OAuth for marketplace integrations.",
    })
    credential_type: Literal["factorial_api_key"] = Field("factorial_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without spaces or an authentication prefix")
        return value


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: dict[str, tuple[Any, Any]]
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


def text(title, *, required=False, description=""):
    return (str if required else Optional[str], Field(... if required else None, title=title,
        min_length=1, description=description))


def boolean(title, *, required=False, description=""):
    return (bool if required else Optional[bool], Field(False if required else None, title=title, description=description))


def integer(title, *, required=False, description=""):
    return (int if required else Optional[int], Field(... if required else None, title=title, description=description))


def choice(values, title, *, required=False, description=""):
    return (Literal[tuple(values)] if required else Optional[Literal[tuple(values)]],
        Field(... if required else None, title=title, description=description))


# Scalar fields are typed; assignee_ids_json is a JSON array of Factorial access IDs.
# Lists return one page and the provider's meta cursors without implying completeness.
OPERATIONS = {
    'get_credentials': Operation('Get Connected Company', 'Account', 'GET', '/api_public/credentials', {

    }, query=(), body=()),
    'list_employees': Operation('List Employees', 'Employees', 'GET', '/employees/employees', {
        'full_text_name': text('Full Text Name', required=False, description='filter by employee name.'),
        'updated_at_gteq': text('Updated At Gteq', required=False, description='Filter employees by their latest update timestamp (`updated_at`), on or after this date. Only the date is considered; any time component is ignored (matching starts at 00:00:00 of the given date). Note: `updated_at` only stores the most recent update, so an employee updated multiple times is matched solely by its latest update, not by earlier ones.'),
        'only_active': boolean('Only Active', required=True, description='Set to true to keep only the employees not terminated as of today: those with no termination date, or one still in the future. Passing false has no effect, and it is ignored altogether when `include_active_and_terminated` is set.'),
        'only_managers': boolean('Only Managers', required=True, description='Set to true to return only the employees who have at least one direct report. Passing false has no effect.'),
    }, query=('full_text_name', 'updated_at_gteq', 'only_active', 'only_managers'), body=()),
    'get_employee': Operation('Get Employee', 'Employees', 'GET', '/employees/employees/{id}', {
        'id': text('Employee ID', required=True, description='Return only the employees with these ids. Ids outside what the reader may see are dropped, rather than failing the whole read.'),
    }, query=(), body=()),
    'create_employee': Operation('Create Employee With Contract', 'Employees', 'POST', '/employees/employees/create_with_contract', {
        'company_id': text('Company Id', required=True, description='company id of the employee, you can get it in companies/legal_entities endpoint.'),
        'first_name': text('First Name', required=True, description='name of the employee.'),
        'last_name': text('Last Name', required=True, description='last name of the employee.'),
        'email': text('Email', required=True, description='login email of the new employee. Not the personal email.'),
        'contract_effective_on': text('Contract Effective On', required=False, description='the day the specific contract starts, in case of hiring the same than contract_starts_on.'),
        'contract_starts_on': text('Contract Starts On', required=False, description='the day the employee is hired.'),
        'ends_on': text('Ends On', required=False, description='the day the contract ends.'),
        'manager_id': text('Manager Id', required=False, description='id of manager, you can get the manager_id from employees endpoint.'),
        'team_id': text('Team Id', required=False, description='team id of the employee.'),
        'location_id': text('Location Id', required=False, description='location id of the employee, references to locations/locations.'),
        'legal_entity_id': text('Legal Entity Id', required=False, description='legal entity of the employee, references to companies/legal_entities.'),
        'company_identifier': text('Company Identifier', required=False, description='identity number or string used inside a company to internally identify the employee.'),
    }, query=(), body=('company_id', 'first_name', 'last_name', 'email', 'contract_effective_on', 'contract_starts_on', 'ends_on', 'manager_id', 'team_id', 'location_id', 'legal_entity_id', 'company_identifier')),
    'update_employee': Operation('Update Employee', 'Employees', 'PUT', '/employees/employees/{id}', {
        'id': text('Employee ID', required=True, description='id of the employee.'),
        'first_name': text('First Name', required=False, description='name of the employee.'),
        'last_name': text('Last Name', required=False, description='last name of the employee.'),
        'preferred_name': text('Preferred Name', required=False, description='nickname of the employee or a name that defines the employee better.'),
        'manager_id': text('Manager Id', required=False, description='id of manager, you can get the manager_id from employees endpoint.'),
        'timeoff_manager_id': text('Timeoff Manager Id', required=False, description='id of manager, you can get the manager_id from employees endpoint.'),
        'location_id': text('Location Id', required=False, description='location id of the employee, references to locations/locations.'),
        'legal_entity_id': text('Legal Entity Id', required=False, description='legal entity of the employee, references to companies/legal_entities.'),
        'phone_number': text('Phone Number', required=False, description='phone number of the employee.'),
        'personal_email': text('Personal Email', required=False, description='personal email of the employee.'),
        'communications_email': text('Communications Email', required=False, description='Email address for company communications and notifications. Separate from login email.'),
        'company_identifier': text('Company Identifier', required=False, description='identity number or string used inside a company to internally identify the employee.'),
    }, query=(), body=('id', 'first_name', 'last_name', 'preferred_name', 'manager_id', 'timeoff_manager_id', 'location_id', 'legal_entity_id', 'phone_number', 'personal_email', 'communications_email', 'company_identifier')),
    'terminate_employee': Operation('Terminate Employee', 'Employees', 'POST', '/employees/employees/terminate', {
        'id': text('Employee ID', required=True, description='id of the employee.'),
        'terminated_on': text('Terminated On', required=True, description='when the employee will be terminated.'),
        'termination_reason': text('Termination Reason', required=False, description='A reason for the termination.'),
        'termination_assigned_manager_id': text('Termination Assigned Manager Id', required=False, description='id of manager that terminates the employee, you can get the manager_id from employees endpoint.'),
        'open_backfill': boolean('Open Backfill', required=False, description='When true, automatically opens a backfill position (vacancy or requisition) for the terminated employee. Requires ATS to be enabled with an automatic backfill setting configured. When false or omitted, no backfill is created.'),
    }, query=(), body=('id', 'terminated_on', 'termination_reason', 'termination_assigned_manager_id', 'open_backfill')),
    'list_leaves': Operation('List Leave Requests', 'Time Off', 'GET', '/timeoff/leaves', {
        'to': text('To', required=False, description='Return only the leaves that had already started by this date (start date on or before it). Usable on its own; pair it with `from` for a window.'),
        'from_date': text('From', required=False, description='Return only the leaves that had not finished before this date, meaning they end on or after it or have no end date at all. Usable on its own; pair it with `to` for a window.'),
        'only_active': boolean('Only Active', required=False, description='Retrieve only active leaves'),
        'include_deleted_leaves': boolean('Include Deleted Leaves', required=True, description='Whether to include deleted leaves (not included by default if not specified)'),
        'approved': boolean('Approved', required=False, description='Set to true for leaves that were approved, false for leaves that were rejected. Leave it unset for every leave whatever its decision. Combining `approved: true` with `include_pending: true` returns approved and still-pending leaves together.'),
        'include_pending': boolean('Include Pending', required=False, description='Set to true to include leaves still awaiting a decision. On its own it returns ONLY the pending ones; alongside `approved: true` it returns approved and pending together.'),
    }, query=('to', 'from', 'only_active', 'include_deleted_leaves', 'approved', 'include_pending'), body=()),
    'get_leave': Operation('Get Leave Request', 'Time Off', 'GET', '/timeoff/leaves/{id}', {
        'id': text('Leave ID', required=True, description='Return only the leaves with these ids.'),
    }, query=(), body=()),
    'create_leave': Operation('Create Leave Request', 'Time Off', 'POST', '/timeoff/leaves', {
        'employee_id': text('Employee Id', required=True, description='The employee id of the leave'),
        'leave_type_id': text('Leave Type Id', required=False, description='The leave type id'),
        'description': text('Description', required=False, description='The description of the leave'),
        'start_on': text('Start On', required=True, description='The valid start date of the leave following the format YYYY-MM-DD'),
        'finish_on': text('Finish On', required=False, description='The valid end date of the leave following the format YYYY-MM-DD'),
        'start_time': text('Start Time', required=False, description='The start time of a leave'),
        'hours_amount_in_cents': integer('Hours Amount In Cents', required=False, description='The hours amount in cents of a leave'),
    }, query=(), body=('employee_id', 'leave_type_id', 'description', 'start_on', 'finish_on', 'start_time', 'hours_amount_in_cents')),
    'update_leave': Operation('Update Leave Request', 'Time Off', 'PUT', '/timeoff/leaves/{id}', {
        'id': text('Leave ID', required=True, description='The leave id'),
        'leave_type_id': text('Leave Type Id', required=False, description='The leave type id'),
        'description': text('Description', required=False, description='The description of the leave'),
        'start_on': text('Start On', required=False, description='The valid start date of the leave following the format YYYY-MM-DD'),
        'finish_on': text('Finish On', required=False, description='The valid end date of the leave following the format YYYY-MM-DD'),
        'start_time': text('Start Time', required=False, description='The start time of a leave'),
        'hours_amount_in_cents': integer('Hours Amount In Cents', required=False, description='The hours amount in cents of a leave'),
    }, query=(), body=('id', 'leave_type_id', 'description', 'start_on', 'finish_on', 'start_time', 'hours_amount_in_cents')),
    'delete_leave': Operation('Delete Leave Request', 'Time Off', 'DELETE', '/timeoff/leaves/{id}', {
        'id': text('Leave ID', required=True, description=''),
    }, query=(), body=()),
    'approve_leave': Operation('Approve Leave Request', 'Time Off', 'POST', '/timeoff/leaves/approve', {
        'id': text('Leave ID', required=True, description='Identifier of the Leave'),
    }, query=(), body=('id',)),
    'reject_leave': Operation('Reject Leave Request', 'Time Off', 'POST', '/timeoff/leaves/reject', {
        'id': text('Leave ID', required=True, description='Identifier of the Leave'),
        'reason': text('Reason', required=False, description='Reason for rejecting the leave'),
    }, query=(), body=('id', 'reason')),
    'list_leave_types': Operation('List Leave Types', 'Time Off', 'GET', '/timeoff/leave_types', {
        'active': boolean('Active', required=False, description='Set to true for the leave types currently in use, false for the retired ones. Leave it unset to get both.'),
        'payable': boolean('Payable', required=False, description='Set to true for the leave types that are paid, false for the unpaid ones. Leave it unset to get both.'),
        'employee_id': text('Employee Id', required=False, description='Return only the leave types the time-off policy in force for this employee grants. It REQUIRES `reference_date`, which says on which date to resolve that policy: without it the read raises.'),
    }, query=('active', 'payable', 'employee_id'), body=()),
    'list_teams': Operation('List Teams', 'Organisation', 'GET', '/teams/teams', {

    }, query=(), body=()),
    'create_team': Operation('Create Team', 'Organisation', 'POST', '/teams/teams', {
        'name': text('Name', required=True, description='Name of the team.'),
        'description': text('Description', required=False, description='Description of the team'),
        'parent_team_id': text('Parent Team Id', required=False, description='ID of the parent team to nest the new team under (omit or null for a root team). Requires the nested teams feature and permission to manage the parent team; the hierarchy is capped at 4 levels.'),
    }, query=(), body=('name', 'description', 'parent_team_id')),
    'list_tasks': Operation('List Tasks', 'Tasks', 'GET', '/tasks/tasks', {
        'company_id': text('Company Id', required=False, description='retrieve the tasks that have a company_id associated'),
        'assignee_id': text('Assignee Id', required=False, description='retrieve the tasks that have an assignee_id associated, assignee_id references to access_id.'),
        'due_on': text('Due On', required=False, description='filter by tasks that have a due date.'),
        'already_due': boolean('Already Due', required=False, description='filter by tasks that have expired or are still due.'),
        'task_status': choice(['todo', 'in_progress', 'done', 'discarded'], 'Task Status', required=False, description='filter by tasks that with an especific status (todo | in_progress | done | discarded).'),
    }, query=('company_id', 'assignee_id', 'due_on', 'already_due', 'task_status'), body=()),
    'get_task': Operation('Get Task', 'Tasks', 'GET', '/tasks/tasks/{id}', {
        'id': text('Task ID', required=True, description='retrieve only the tasks that match the IDs passed in the request.'),
    }, query=(), body=()),
    'create_task': Operation('Create Task', 'Tasks', 'POST', '/tasks/tasks', {
        'name': text('Name', required=True, description='name of the task.'),
        'status': choice(['todo', 'in_progress', 'done', 'discarded'], 'Status', required=True, description='status of the task (todo | in_progress | done | discarded).'),
        'content': text('Content', required=False, description='description of the task'),
        'due_on': text('Due On', required=False, description='expiration date of the task.'),
        'assignee_ids_json': text('Assignee Ids JSON', required=False, description='Employees assigned to the task, assignee_id references to access_id. Enter a JSON array of access IDs, for example ["1", "2"].'),
        'author_employee_id': text('Author Employee Id', required=False, description='employee that will be set as the author of the task. Only taken into account when authenticating with an API key, requests performed on behalf of a user always use that user as the author. When omitted, the task is authored by the first active employee of the company.'),
    }, query=(), body=('name', 'status', 'content', 'due_on', 'assignee_ids', 'author_employee_id')),
    'update_task': Operation('Update Task', 'Tasks', 'PUT', '/tasks/tasks/{id}', {
        'id': text('Task ID', required=True, description='id of a task.'),
        'name': text('Name', required=False, description='name of  task.'),
        'status': choice(['todo', 'in_progress', 'done', 'discarded'], 'Status', required=False, description='status of the task (todo | in_progress | done | discarded).'),
        'content': text('Content', required=False, description='description of the task.'),
        'due_on': text('Due On', required=False, description='expiration date of the task.'),
        'assignee_ids_json': text('Assignee Ids JSON', required=False, description='employees assigned to the task, assignee_id references to access_id. Enter a JSON array of access IDs, for example ["1", "2"].'),
    }, query=(), body=('id', 'name', 'status', 'content', 'due_on', 'assignee_ids')),
    'list_candidates': Operation('List Candidates', 'Recruitment', 'GET', '/ats/candidates', {
        'active': boolean('Active', required=False, description='is the candidate active?'),
        'talent_pool': boolean('Talent Pool', required=False, description='is the candidate part of talent pool?'),
        'archived': boolean('Archived', required=False, description='is the candidate archived?'),
    }, query=('active', 'talent_pool', 'archived'), body=()),
    'get_candidate': Operation('Get Candidate', 'Recruitment', 'GET', '/ats/candidates/{id}', {
        'id': text('Candidate ID', required=True, description='list of candidate identifiers.'),
    }, query=(), body=()),
    'create_candidate': Operation('Create Candidate', 'Recruitment', 'POST', '/ats/candidates', {
        'company_id': text('Company Id', required=True, description='company identifier, refers to /core/me endpoint.'),
        'first_name': text('First Name', required=True, description='first name of the candidate.'),
        'last_name': text('Last Name', required=True, description='last name of the candidate.'),
        'email': text('Email', required=False, description='email of the candidate.'),
        'talent_pool': boolean('Talent Pool', required=False, description='is the candidate part of talent pool?'),
        'consent_given_at': text('Consent Given At', required=False, description='date when the consent was given.'),
        'source': text('Source', required=False, description='source of the candidate.'),
        'medium': text('Medium', required=False, description='specifies additional details related to the source of the candidate, such as the referrer name for example if the source is referred.'),
        'phone_number': text('Phone Number', required=False, description='phone number of the candidate.'),
        'personal_url': text('Personal Url', required=False, description='personal web resource from the candidate.'),
    }, query=(), body=('company_id', 'first_name', 'last_name', 'email', 'talent_pool', 'consent_given_at', 'source', 'medium', 'phone_number', 'personal_url')),
}


class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def make_config(name, spec):
    fields = dict(spec.fields)
    if spec.method == "GET" and "{id}" not in spec.path:
        fields.update({
            "limit": (int, Field(100, ge=1, le=100, title="Page Size")),
            "after_id": (Optional[str], Field(None, title="After Cursor", description="Use meta.end_cursor from the previous page.")),
        })
    return create_model("Factorial" + "".join(w.title() for w in name.split("_")) + "Config",
        __base__=OperationConfig, __module__=__name__,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-display-name": spec.label,
            "x-category": spec.category, "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})

EVENTS = (
    "employees/employee/create_with_contract", "employees/employee/update",
    "employees/employee/terminate", "employees/employee/unterminate",
    "timeoff/leave/create", "timeoff/leave/update", "timeoff/leave/approve", "timeoff/leave/reject",
    "attendance/shift/clock_in", "attendance/shift/clock_out", "ats/candidate/create",
)


class FactorialOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Factorial Event", json_schema_extra={
        "const": "on_event", "ui:hidden": True, "x-display-name": "On Factorial Event",
        "x-category": "Triggers", "x-is-trigger": True})
    subscription_type: Literal[*EVENTS] = Field("employees/employee/update", title="Event")
    company_id: str = Field(..., title="Company ID", min_length=1,
        description="The company_id returned by Get Connected Company.")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with Factorial automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


FactorialConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (FactorialOnEventConfig,)], Discriminator("operation")]


class FactorialNodeConfig(NodeConfig[FactorialConfig, FactorialAPIKeyCredential]):
    pass


class FactorialNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-factorial"
    connection_evidence = ConnectionEvidence(operation="get_credentials", noun="companies", identity_operation="get_credentials")

    @classmethod
    def get_config_model(cls):
        return FactorialNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = FactorialAPIKeyCredential.model_validate(credential)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"x-api-key": credential.api_key, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            detail = response.text[:2000].replace(credential.api_key, "[redacted]")
            if body and body.get("challenge"):
                detail = detail.replace(body["challenge"], "[redacted]")
            raise ValueError(f"Factorial API error {response.status_code}: {detail}")
        if not response.content:
            raise ValueError("Factorial returned an empty response; check that the key belongs to production")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Factorial returned an unexpected response shape")
        return result

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, FactorialOnEventConfig):
            payload = (self.node_data or {}).get("config", {}).get("_triggerPayload")
            return self.resolve_trigger_payload(payload, op.model_dump()) if payload else {"status": "no_event"}
        if self.config.credentials is None:
            raise ValueError("Connect Factorial before running this operation")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        params = {key: values["from_date" if key == "from" else key] for key in spec.query
                  if ("from_date" if key == "from" else key) in values}
        if spec.method == "GET" and "{id}" not in spec.path:
            params.update({key: values[key] for key in ("limit", "after_id") if key in values})
        body = {key: values[key] for key in spec.body if key in values}
        if "assignee_ids_json" in values:
            ids = json.loads(values["assignee_ids_json"])
            if not isinstance(ids, list) or not all(isinstance(v, str) and v.strip() for v in ids):
                raise ValueError("Assignee IDs JSON must be an array of nonempty access ID strings")
            body["assignee_ids"] = ids
        path = spec.path.replace("{id}", quote(values.get("id", ""), safe=""))
        data = await self._request(self.config.credentials.model_dump(), spec.method, path,
            params=params or None, body=body if spec.body else None)
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = FactorialOnEventConfig.model_validate(config)
        challenge = secrets.token_urlsafe(32)
        result = await cls._request(credential, "POST", "/api_public/webhook_subscriptions", body={
            "subscription_type": op.subscription_type, "company_id": op.company_id, "target_url": webhook_url,
            "name": f"NoClick {node_id}", "challenge": challenge, "enabled": True, "api_version": VERSION})
        if not result.get("id"):
            raise ValueError("Factorial did not return the subscription ID")
        return {"external_webhook_id": str(result["id"]), "signing_secret": challenge}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        subscription_id = (config or {}).get("external_webhook_id")
        if subscription_id is not None:
            await cls._request(credential, "DELETE", "/api_public/webhook_subscriptions/" + quote(str(subscription_id), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: (config or {}).get(key) for key in ("subscription_type", "company_id")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Factorial echoes the subscription challenge; it does not sign the body.
        secret = (config or {}).get("signing_secret")
        supplied = next((v for k, v in headers.items() if k.lower() == "x-factorial-wh-challenge"), None)
        return bool(isinstance(secret, str) and secret and isinstance(supplied, str)
                    and hmac.compare_digest(secret.encode(), supplied.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if not isinstance(payload, dict):
            return False
        event = (config or {}).get("subscription_type", "")
        required = {"employees": ("id", "company_id", "full_name", "access_id"),
                    "timeoff": ("id", "company_id", "employee_id", "start_on"),
                    "attendance": ("id", "employee_id"),
                    "ats": ("id", "first_name", "last_name")}.get(event.split("/")[0])
        return bool(required and all(key in payload for key in required))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        return {"status": "success", "operation": "on_event", "subscription_type": config["subscription_type"], "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") != "on_event":
            return super().resolve_agent_event(output)
        row, event = output["data"], output["subscription_type"]
        domain, kind, action = event.split("/")
        # Only access optional fields present in the delivered resource. These
        # are fields of the pinned webhook schemas, never an assumed envelope.
        facts = {key: row[key] for key in (
            "id", "company_id", "employee_id", "access_id", "full_name", "first_name", "last_name",
            "email", "employee_full_name", "start_on", "finish_on", "description", "reason", "approved",
            "terminated_on", "termination_reason", "clock_in", "clock_out", "date", "reference_date",
            "location_type", "workplace_id", "observations", "updated_at") if key in row}
        who = facts.get("full_name") or facts.get("employee_full_name") or " ".join(
            str(facts[key]) for key in ("first_name", "last_name") if facts.get(key)) or (
            "Employee " + str(facts["employee_id"]) if facts.get("employee_id") else kind.title())
        lines = [f"Factorial: {who} — {kind} {action.replace('_', ' ')}."]
        lines.extend(f"{key.replace('_', ' ')}: {value}" for key, value in facts.items() if value is not None)
        lines.append("Workspace: https://app.factorialhr.com")
        lines.append(f"Factorial resource ID: {row['id']}.")
        action_hint = {
            "employee": f"get_employee or update_employee id={row['id']}",
            "leave": f"get_leave, approve_leave or reject_leave id={row['id']}",
            "candidate": f"get_candidate id={row['id']}",
            "shift": f"get_employee id={facts.get('employee_id', '')}; the shift ID is a separate resource",
        }[kind]
        lines.append("To act: " + action_hint)
        return {"text": "\n".join(lines), "title": f"{who}: {kind} {action}",
                "conversation_key": f"factorial:{domain}:{kind}:{row['id']}"}
