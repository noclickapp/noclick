"""Remote customer API operations, pinned to the published Remote OpenAPI 0.1.0.

Each action sends one documented request. API tokens come from the customer's
Integration Settings. Remote enforces the token's selected permissions.
"""
from __future__ import annotations
import hashlib
import hmac
import re
from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


class RemoteAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Remote API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.remote.com/docs/authorization-for-customers",
        "x-credential-instructions": "In Remote, open Company → Company Settings → Integrations & APIs → Integrations → Remote API. Paste your customer API token. Enable the read/write permissions your actions need and webhook:write for triggers. ra_test_ tokens use Remote's sandbox; other tokens use production."})
    credential_type: Literal["remote_api_token"] = Field("remote_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() for c in value) or len(value) > 4096:
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeoffDay(Input):
    day: date = Field(..., title="Day")
    hours: int = Field(..., ge=0, le=24, title="Hours")


def text(title, required=False, **kwargs):
    return (str if required else str | None, Field(... if required else None, title=title, **kwargs))


def identifier(title):
    return text(title, True, min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


PAGE = {"page": (int, Field(1, ge=1, title="Page")), "page_size": (int, Field(20, ge=1, le=100, title="Page Size"))}

RemoteListCompaniesConfig = create_model('RemoteListCompaniesConfig', __base__=Input, __module__=__name__,
    operation=(Literal['list_companies'], Field('list_companies', title='List Companies', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Companies'})),
    external_id=(str | None, Field(None, title='External Id', min_length=1, max_length=4096)),
)

RemoteGetCompanyConfig = create_model('RemoteGetCompanyConfig', __base__=Input, __module__=__name__,
    operation=(Literal['get_company'], Field('get_company', title='Get Company', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Companies'})),
    company_id=identifier('Company Id'),
)

RemoteListEmploymentsConfig = create_model('RemoteListEmploymentsConfig', __base__=Input, __module__=__name__,
    operation=(Literal['list_employments'], Field('list_employments', title='List Employments', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Employments'})),
    company_id=(str | None, Field(None, title='Company Id', min_length=1, max_length=4096)),
    email=(str | None, Field(None, title='Email', min_length=1, max_length=4096)),
    name=(str | None, Field(None, title='Name', min_length=1, max_length=4096)),
    status=(str | None, Field(None, title='Status', min_length=1, max_length=4096)),
    employment_type=(str | None, Field(None, title='Employment Type', min_length=1, max_length=4096)),
    employment_model=(Literal['global_payroll', 'peo', 'eor'] | None, Field(None, title='Employment Model')),
    short_id=(str | None, Field(None, title='Short Id', min_length=1, max_length=4096)),
    partner_external_id=(str | None, Field(None, title='Partner External Id', min_length=1, max_length=64)),
    page=PAGE["page"],
    page_size=PAGE["page_size"],
)

RemoteGetEmploymentConfig = create_model('RemoteGetEmploymentConfig', __base__=Input, __module__=__name__,
    operation=(Literal['get_employment'], Field('get_employment', title='Get Employment', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Employments'})),
    employment_id=identifier('Employment Id'),
    exclude_files=(bool | None, Field(None, title='Exclude Files')),
    group_tax_servicing_countries=(bool | None, Field(None, title='Group Tax Servicing Countries')),
)

RemoteInviteEmploymentConfig = create_model('RemoteInviteEmploymentConfig', __base__=Input, __module__=__name__,
    operation=(Literal['invite_employment'], Field('invite_employment', title='Invite Employee (Sends Email)', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Employments'})),
    employment_id=identifier('Employment Id'),
)

RemoteListTimeoffConfig = create_model('RemoteListTimeoffConfig', __base__=Input, __module__=__name__,
    operation=(Literal['list_timeoff'], Field('list_timeoff', title='List Time Off', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Time Off'})),
    employment_id=(str | None, Field(None, title='Employment Id', min_length=1, max_length=4096)),
    timeoff_type=(Literal['time_off', 'sick_leave', 'public_holiday', 'unpaid_leave', 'extended_leave', 'in_lieu_time', 'maternity_leave', 'paternity_leave', 'parental_leave', 'bereavement', 'military_leave', 'other', 'paid_time_off', 'custom_company_leave', 'rtt', 'casual_leave', 'rol', 'ex_festivita', 'civic_duty', 'adoption', 'caregiver', 'transfer', 'exam', 'monkhood', 'marriage', 'sterilization', 'celebration', 'blood_donation', 'health_day', 'special', 'career', 'study', 'voluntary', 'adv', 'public_duties', 'force_majeure', 'medical_visits', 'marriage_child', 'breastfeeding', 'maternity_paid', 'maternity_unpaid', 'paternity_paid', 'paternity_unpaid', 'pregnancy_leave', 'business_trip_eu', 'business_trip_non_eu', 'training', 'sustainable_employability'] | None, Field(None, title='Timeoff Type')),
    status=(Literal['approved', 'cancelled', 'declined', 'requested', 'taken', 'cancel_requested'] | None, Field(None, title='Status')),
    start_date=(date | None, Field(None, title='Start Date')),
    end_date=(date | None, Field(None, title='End Date')),
    order=(Literal['asc', 'desc'] | None, Field(None, title='Order')),
    sort_by=(Literal['timeoff_type', 'status'] | None, Field(None, title='Sort By')),
    page=PAGE["page"],
    page_size=PAGE["page_size"],
)

RemoteGetTimeoffConfig = create_model('RemoteGetTimeoffConfig', __base__=Input, __module__=__name__,
    operation=(Literal['get_timeoff'], Field('get_timeoff', title='Get Time Off', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Time Off'})),
    id=identifier('Id'),
)

RemoteCreateTimeoffConfig = create_model('RemoteCreateTimeoffConfig', __base__=Input, __module__=__name__,
    operation=(Literal['create_timeoff'], Field('create_timeoff', title='Create Approved Time Off', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Time Off'})),
    employment_id=(str, Field(..., title='Employment Id', min_length=1, max_length=4096)),
    start_date=(str, Field(..., title='Start Date', min_length=1, max_length=4096)),
    end_date=(str, Field(..., title='End Date', min_length=1, max_length=4096)),
    timezone=(str, Field(..., title='Timezone', min_length=1, max_length=4096)),
    timeoff_days=(Json[list[TimeoffDay]], Field(..., title='Time Off Days (JSON)', description='JSON array of day and hours, for example [{"day":"2021-12-20","hours":8}].', json_schema_extra={'ui:widget': 'textarea'})),
    timeoff_type=(Literal['time_off', 'sick_leave', 'public_holiday', 'unpaid_leave', 'extended_leave', 'in_lieu_time', 'maternity_leave', 'paternity_leave', 'parental_leave', 'bereavement', 'military_leave', 'other', 'paid_time_off', 'custom_company_leave', 'rtt', 'casual_leave', 'rol', 'ex_festivita'] | None, Field(None, title='Timeoff Type')),
    leave_policy_variant_id=(str | None, Field(None, title='Leave Policy Variant Id', min_length=1, max_length=4096)),
    notes=(str | None, Field(None, title='Notes', min_length=1, max_length=4096)),
    status=(Literal['approved'], Field('approved', title='Status')),
    approver_id=(str | None, Field(..., title='Approver Id', min_length=1, max_length=4096)),
    approved_at=(datetime, Field(..., title='Approved At')),
)

RemoteApproveTimeoffConfig = create_model('RemoteApproveTimeoffConfig', __base__=Input, __module__=__name__,
    operation=(Literal['approve_timeoff'], Field('approve_timeoff', title='Approve Time Off', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Time Off'})),
    timeoff_id=identifier('Timeoff Id'),
    approver_id=(str | None, Field(..., title='Approver Id', min_length=1, max_length=4096)),
)

RemoteDeclineTimeoffConfig = create_model('RemoteDeclineTimeoffConfig', __base__=Input, __module__=__name__,
    operation=(Literal['decline_timeoff'], Field('decline_timeoff', title='Decline Time Off', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Time Off'})),
    timeoff_id=identifier('Timeoff Id'),
    decline_reason=(str | None, Field(..., title='Decline Reason', min_length=1, max_length=4096)),
)

RemoteListExpensesConfig = create_model('RemoteListExpensesConfig', __base__=Input, __module__=__name__,
    operation=(Literal['list_expenses'], Field('list_expenses', title='List Expenses', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Expenses'})),
    page=PAGE["page"],
    page_size=PAGE["page_size"],
)

RemoteGetExpenseConfig = create_model('RemoteGetExpenseConfig', __base__=Input, __module__=__name__,
    operation=(Literal['get_expense'], Field('get_expense', title='Get Expense', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Expenses'})),
    id=identifier('Id'),
)

RemoteCreateExpenseConfig = create_model('RemoteCreateExpenseConfig', __base__=Input, __module__=__name__,
    operation=(Literal['create_expense'], Field('create_expense', title='Create Expense', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Expenses'})),
    expense_date=(str, Field(..., title='Expense Date', min_length=1, max_length=4096)),
    title=(str, Field(..., title='Title', min_length=1, max_length=4096)),
    amount=(int, Field(..., title='Amount', description='Amount in minor currency units: 50025 means 500.25 in a two-decimal currency.')),
    currency=(str, Field(..., title='Currency', min_length=1, max_length=4096)),
    employment_id=(str, Field(..., title='Employment Id', min_length=1, max_length=4096)),
    expense_category_slug=(str | None, Field(None, title='Expense Category Slug', min_length=1, max_length=4096)),
    tax_amount=(int | None, Field(None, title='Tax Amount')),
    timezone=(str | None, Field(None, title='Timezone', min_length=1, max_length=4096)),
)

RemoteListIncentivesConfig = create_model('RemoteListIncentivesConfig', __base__=Input, __module__=__name__,
    operation=(Literal['list_incentives'], Field('list_incentives', title='List Incentives', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Incentives'})),
    employment_id=(str | None, Field(None, title='Employment Id', min_length=1, max_length=4096)),
    status=(str | None, Field(None, title='Status', min_length=1, max_length=4096)),
    recurring_incentive_id=(str | None, Field(None, title='Recurring Incentive Id', min_length=1, max_length=4096)),
    type=(str | None, Field(None, title='Type', min_length=1, max_length=4096)),
    page=PAGE["page"],
    page_size=PAGE["page_size"],
)

RemoteGetIncentiveConfig = create_model('RemoteGetIncentiveConfig', __base__=Input, __module__=__name__,
    operation=(Literal['get_incentive'], Field('get_incentive', title='Get Incentive', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Incentives'})),
    id=identifier('Id'),
)

RemoteCreateIncentiveConfig = create_model('RemoteCreateIncentiveConfig', __base__=Input, __module__=__name__,
    operation=(Literal['create_incentive'], Field('create_incentive', title='Create Incentive', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Incentives'})),
    employment_id=(str, Field(..., title='Employment Id', min_length=1, max_length=4096)),
    type=(Literal['acting_up_allowance', 'allowance', 'car_allowance', 'health_and_wellness_allowance', 'internet_allowance', 'meal_allowance', 'on_call_allowance', 'parenthood_allowance', 'phone_allowance', 'relocation_allowance', 'travel_allowance', 'work_from_home_allowance', 'bonus', 'holiday_bonus', 'referral_bonus', 'retention_bonus', 'commission', 'other', 'overtime', 'stipend', 'signing_bonus'], Field(..., title='Type')),
    amount=(int, Field(..., title='Amount', description='Amount in minor currency units: 50025 means 500.25 in a two-decimal currency.')),
    amount_tax_type=(Literal['gross', 'net'], Field(..., title='Amount Tax Type')),
    effective_date=(date, Field(..., title='Effective Date')),
    note=(str | None, Field(None, title='Note', min_length=1, max_length=4096)),
    period_start=(date | None, Field(None, title='Period Start')),
    period_end=(date | None, Field(None, title='Period End')),
)

RemoteDeleteIncentiveConfig = create_model('RemoteDeleteIncentiveConfig', __base__=Input, __module__=__name__,
    operation=(Literal['delete_incentive'], Field('delete_incentive', title='Delete Incentive', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Incentives'})),
    id=identifier('Id'),
)

RemoteListTimesheetsConfig = create_model('RemoteListTimesheetsConfig', __base__=Input, __module__=__name__,
    operation=(Literal['list_timesheets'], Field('list_timesheets', title='List Timesheets', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Timesheets'})),
    status=(Literal['open', 'submitted', 'approved', 'in_calibration', 'processed'] | None, Field(None, title='Status')),
    order=(Literal['asc', 'desc'] | None, Field(None, title='Order')),
    sort_by=(Literal['submitted_at'] | None, Field(None, title='Sort By')),
    page=PAGE["page"],
    page_size=PAGE["page_size"],
)

RemoteGetTimesheetConfig = create_model('RemoteGetTimesheetConfig', __base__=Input, __module__=__name__,
    operation=(Literal['get_timesheet'], Field('get_timesheet', title='Get Timesheet', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Timesheets'})),
    id=identifier('Id'),
)

RemoteApproveTimesheetConfig = create_model('RemoteApproveTimesheetConfig', __base__=Input, __module__=__name__,
    operation=(Literal['approve_timesheet'], Field('approve_timesheet', title='Approve Timesheet', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Timesheets'})),
    timesheet_id=identifier('Timesheet Id'),
)

RemoteSendBackTimesheetConfig = create_model('RemoteSendBackTimesheetConfig', __base__=Input, __module__=__name__,
    operation=(Literal['send_back_timesheet'], Field('send_back_timesheet', title='Send Back Timesheet (Notifies Employee)', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-category": 'Timesheets'})),
    timesheet_id=identifier('Timesheet Id'),
    sent_back_reason=(str, Field(..., title='Sent Back Reason', min_length=1, max_length=4096)),
)

OPERATIONS = {
    'list_companies': ('GET', '/v1/companies', ('external_id',), ()),
    'get_company': ('GET', '/v1/companies/{company_id}', (), ()),
    'list_employments': ('GET', '/v1/employments', ('company_id', 'email', 'name', 'status', 'employment_type', 'employment_model', 'short_id', 'partner_external_id', 'page', 'page_size'), ()),
    'get_employment': ('GET', '/v1/employments/{employment_id}', ('exclude_files', 'group_tax_servicing_countries'), ()),
    'invite_employment': ('POST', '/v1/employments/{employment_id}/invite', (), ()),
    'list_timeoff': ('GET', '/v1/timeoff', ('employment_id', 'timeoff_type', 'status', 'start_date', 'end_date', 'order', 'sort_by', 'page', 'page_size'), ()),
    'get_timeoff': ('GET', '/v1/timeoff/{id}', (), ()),
    'create_timeoff': ('POST', '/v1/timeoff', (), ('employment_id', 'start_date', 'end_date', 'timezone', 'timeoff_days', 'timeoff_type', 'leave_policy_variant_id', 'notes', 'status', 'approver_id', 'approved_at')),
    'approve_timeoff': ('POST', '/v1/timeoff/{timeoff_id}/approve', (), ('approver_id',)),
    'decline_timeoff': ('POST', '/v1/timeoff/{timeoff_id}/decline', (), ('decline_reason',)),
    'list_expenses': ('GET', '/v1/expenses', ('page', 'page_size'), ()),
    'get_expense': ('GET', '/v1/expenses/{id}', (), ()),
    'create_expense': ('POST', '/v1/expenses', (), ('expense_date', 'title', 'amount', 'currency', 'employment_id', 'expense_category_slug', 'tax_amount', 'timezone')),
    'list_incentives': ('GET', '/v1/incentives', ('employment_id', 'status', 'recurring_incentive_id', 'type', 'page', 'page_size'), ()),
    'get_incentive': ('GET', '/v1/incentives/{id}', (), ()),
    'create_incentive': ('POST', '/v1/incentives', (), ('employment_id', 'type', 'amount', 'amount_tax_type', 'effective_date', 'note', 'period_start', 'period_end')),
    'delete_incentive': ('DELETE', '/v1/incentives/{id}', (), ()),
    'list_timesheets': ('GET', '/v1/timesheets', ('status', 'order', 'sort_by', 'page', 'page_size'), ()),
    'get_timesheet': ('GET', '/v1/timesheets/{id}', (), ()),
    'approve_timesheet': ('POST', '/v1/timesheets/{timesheet_id}/approve', (), ()),
    'send_back_timesheet': ('POST', '/v1/timesheets/{timesheet_id}/send-back', (), ('sent_back_reason',)),
}

WEBHOOK_EVENTS = ('employment.onboarding.completed', 'employment.updated', 'employment.status.updated', 'timeoff.requested', 'timeoff.approved', 'expense.submitted', 'incentive.created', 'timesheet.submitted')

class RemoteOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Remote Event", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    event_type: Literal[*WEBHOOK_EVENTS] = Field("employment.onboarding.completed", title="Event")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


RemoteOperation = Annotated[Union[RemoteListCompaniesConfig, RemoteGetCompanyConfig, RemoteListEmploymentsConfig, RemoteGetEmploymentConfig, RemoteInviteEmploymentConfig, RemoteListTimeoffConfig, RemoteGetTimeoffConfig, RemoteCreateTimeoffConfig, RemoteApproveTimeoffConfig, RemoteDeclineTimeoffConfig, RemoteListExpensesConfig, RemoteGetExpenseConfig, RemoteCreateExpenseConfig, RemoteListIncentivesConfig, RemoteGetIncentiveConfig, RemoteCreateIncentiveConfig, RemoteDeleteIncentiveConfig, RemoteListTimesheetsConfig, RemoteGetTimesheetConfig, RemoteApproveTimesheetConfig, RemoteSendBackTimesheetConfig, RemoteOnEventConfig], Field(discriminator="operation")]

class RemoteNodeConfig(NodeConfig[RemoteOperation, RemoteAPITokenCredential]):
    pass


class RemoteNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-remote"
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies")

    @classmethod
    def get_config_model(cls):
        return RemoteNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        token = credential["api_token"]
        base = "https://gateway.remote-sandbox.com" if token.startswith("ra_test_") else "https://gateway.remote.com"
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, base + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            # Provider errors are needed by the manual-connect seam, but never echo the credential.
            detail = response.text[:2000].replace(token, "[redacted]")
            raise ValueError(f"Remote API {response.status_code}: {detail}")
        if not response.content:
            return {"ok": True}
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Remote returned an unexpected response")
        return result

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, RemoteOnEventConfig):
            payload = self.node_data.get("config", {}).get("_triggerPayload") or inputs
            if not payload:
                return {"status": "success", "operation": "on_event", "no_event": True}
            return self.resolve_trigger_payload(payload, op.model_dump())
        if self.config.credentials is None:
            raise ValueError("Connect a Remote API token")
        method, path, query_keys, body_keys = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        params = {k: values[k] for k in query_keys if k in values}
        body = {k: values[k] for k in body_keys if k in values}
        # Remote requires these nullable keys to be present even when explicitly null.
        if op.operation in {"create_timeoff", "approve_timeoff"}:
            body["approver_id"] = op.approver_id
        if op.operation == "decline_timeoff":
            body["decline_reason"] = op.decline_reason
        result = await self._request(self.config.credentials.model_dump(), method, path,
                                     params=params or None, body=body if body_keys else None)
        return {"status": "success", "operation": op.operation, "data": result}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = (config or {}).get("event_type", "employment.onboarding.completed")
        if event not in WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Remote event")
        response = await cls._request(credential, "POST", "/v1/webhook-callbacks",
            body={"url": webhook_url, "subscribed_events": [event]})
        callback = response["data"]["webhook_callback"]
        if not callback.get("id") or not callback.get("signing_key"):
            raise ValueError("Remote did not return the webhook ID and signing key")
        return {"external_webhook_id": callback["id"], "signing_secret": callback["signing_key"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if credential and (config or {}).get("external_webhook_id"):
            await cls._request(credential, "DELETE", "/v1/webhook-callbacks/" + quote(str(config["external_webhook_id"]), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "employment.onboarding.completed")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://developer.remote.com/docs/verifying-webhooks: HMAC-SHA256(raw body + ':' + timestamp), hex.
        secret = (config or {}).get("signing_secret")
        normalized = {k.lower(): v for k, v in headers.items()}
        timestamp = normalized.get("x-remote-timestamp", "")
        signature = normalized.get("x-remote-signature", "")
        if not secret or not re.fullmatch(r"[0-9]+", timestamp) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            return False
        expected = hmac.new(str(secret).encode(), body + b":" + timestamp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.lower())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return isinstance(payload, dict) and payload.get("event_type") == (config or {}).get("event_type", "employment.onboarding.completed")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        return {"status": "success", "operation": "on_event", "data": {k: v for k, v in payload.items() if not k.startswith("_")}}

    @classmethod
    def resolve_agent_event(cls, output):
        payload = output.get("data", output)
        event = payload.get("event_type")
        if event not in WEBHOOK_EVENTS:
            return None
        # Only event-specific documented fields are read; Remote sends IDs rather than employee names.
        employment = payload.get("employment_id")
        company = payload.get("company_id")
        resource = {"timeoff": ("timeoff_id", "get_timeoff"), "expense": ("expense_id", "get_expense"),
                    "incentive": ("incentive_id", "get_incentive"), "timesheet": ("timesheet_id", "get_timesheet")}.get(event.split(".")[0])
        text = f"Remote: {event.replace('.', ' ')} for employment {employment} at company {company}."
        if resource:
            field, action = resource
            rid = payload.get(field)
            text += f"\n{field}: {rid}. Read the record with {action} id={rid}."
        else:
            text += f"\nRead the employee's current details with get_employment employment_id={employment}."
        return {"text": text, "title": "Remote: " + event, "conversation_key": str(employment)}
