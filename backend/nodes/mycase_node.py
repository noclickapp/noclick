"""MyCase Open API v1: one published endpoint per operation.

Contract: https://mycaseapi.stoplight.io/docs/mycase-api-documentation
OAuth: https://mycaseapi.stoplight.io/docs/mycase-api-documentation/k5xpc4jyhkom7-getting-started
Pagination: https://stoplight.io/api/v1/projects/mycaseapi/mycase-api-documentation/nodes/docs/Pagination.md
"""
from datetime import date, datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from nodes.scopes.mycase import MYCASE_SCOPES
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://external-integrations.mycase.com"
Identifier = Annotated[int, Field(ge=1, le=9223372036854775807)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


class MyCaseOAuthCredential(BaseModel):
    model_config = ConfigDict(title="MyCase Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "mycase",
            "x-oauth-scopes": MYCASE_SCOPES.declared_scopes(),
            "x-credential-url": "https://supportcenter.mycase.com/en/articles/9370198-open-api",
            "x-credential-instructions": "Connect an Advanced-tier MyCase account. MyCase support must provision your application's client credentials, registered callback URL and read/write resource permissions. The authorizing user needs permission to manage the firm's preferences, billing and payment options. The connection check reads your current staff account and does not prove write access.",
        })
    credential_type: Literal["mycase_oauth"] = Field("mycase_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh token", min_length=1, max_length=8192, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token expiry")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k != "credentialIds" and not k.endswith("__label")}
        return value


class _Page(_Input):
    page_size: int = Field(25, ge=1, le=1000, description="Return one page of up to 1000 records.")
    page_token: Optional[str] = Field(None, min_length=1, max_length=4096, description="next_page_token from the previous response. Keep the same operation and filters; tokens expire after three days.")
    updated_after: Optional[datetime] = Field(None, description="Inclusive last-update filter in ISO 8601 format.")


class _PeoplePage(_Page):
    email: Optional[Text] = None
    first_name: Optional[Text] = None
    last_name: Optional[Text] = None


class _Person(_Input):
    first_name: Text
    last_name: Text
    email: Optional[Text] = None
    birthdate: Optional[date] = None
    cell_phone_number: Optional[Text] = None
    work_phone_number: Optional[Text] = None
    home_phone_number: Optional[Text] = None


class _Client(_Person):
    middle_name: Optional[Text] = None
    notes: Optional[Text] = None
    case_ids: Optional[list[Identifier]] = Field(None, max_length=100, description="Cases to associate with this client.")


class _Lead(_Person):
    lead_details: Optional[Text] = None
    referral_source_id: Optional[Identifier] = None


class _Case(_Input):
    name: Text = Field(..., description="Case name; must be unique in MyCase. Required for creation and replacement updates.")
    case_number: Optional[Text] = None
    opened_date: Optional[date] = None
    sol_date: Optional[date] = None
    case_stage: Optional[Text] = Field(None, description="Existing case stage name; unmatched names become blank in MyCase.")
    practice_area: Optional[Text] = Field(None, description="Existing practice area name; unmatched names become blank in MyCase.")
    description: Optional[Text] = None
    status: Optional[Literal["open", "closed"]] = None
    client_ids: Optional[list[Identifier]] = Field(None, max_length=100)
    company_ids: Optional[list[Identifier]] = Field(None, max_length=100)


class _Task(_Input):
    name: Text
    priority: Literal["Low", "Medium", "High"]
    due_date: date
    staff_ids: list[Identifier] = Field(..., min_length=1, max_length=100, description="Staff assigned to the task.")
    description: Optional[Text] = None
    completed: Optional[StrictBool] = None
    case_id: Optional[Identifier] = None


class MyCaseGetCurrentUser(_Input):
    """Get current user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class MyCaseListClients(_PeoplePage):
    """List clients."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})


class MyCaseGetClient(_Input):
    """Get client."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})
    client_id: Identifier


class MyCaseCreateClient(_Client):
    """Create client."""
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})


class MyCaseUpdateClient(_Client):
    """Update client."""
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})
    client_id: Identifier


class MyCaseListLeads(_PeoplePage):
    """List leads."""
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})


class MyCaseGetLead(_Input):
    """Get lead."""
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True})
    lead_id: Identifier


class MyCaseCreateLead(_Lead):
    """Create lead."""
    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True})


class MyCaseUpdateLead(_Lead):
    """Update lead."""
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True})
    lead_id: Identifier


class MyCaseListCases(_Page):
    """List cases."""
    operation: Literal["list_cases"] = Field("list_cases", json_schema_extra={"ui:hidden": True})
    status: Optional[Literal["open", "closed"]] = None


class MyCaseGetCase(_Input):
    """Get case."""
    operation: Literal["get_case"] = Field("get_case", json_schema_extra={"ui:hidden": True})
    case_id: Identifier


class MyCaseCreateCase(_Case):
    """Create case."""
    operation: Literal["create_case"] = Field("create_case", json_schema_extra={"ui:hidden": True})


class MyCaseUpdateCase(_Case):
    """Update case."""
    operation: Literal["update_case"] = Field("update_case", json_schema_extra={"ui:hidden": True})
    case_id: Identifier


class MyCaseListTasks(_Page):
    """List tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})


class MyCaseCreateTask(_Task):
    """Create task."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})


class MyCaseUpdateTask(_Task):
    """Update task."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})
    task_id: Identifier


class MyCaseListCaseNotes(_Input):
    """List case notes."""
    operation: Literal["list_case_notes"] = Field("list_case_notes", json_schema_extra={"ui:hidden": True})
    case_id: Identifier


class MyCaseCreateCaseNote(_Input):
    """Create case note."""
    operation: Literal["create_case_note"] = Field("create_case_note", json_schema_extra={"ui:hidden": True})
    case_id: Identifier
    subject: Text
    note: Text
    date: datetime


class MyCaseGetNote(_Input):
    """Get note."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})
    note_id: Identifier


class MyCaseListTimeEntries(_Page):
    """List time entries."""
    operation: Literal["list_time_entries"] = Field("list_time_entries", json_schema_extra={"ui:hidden": True})


class MyCaseCreateTimeEntry(_Input):
    """Create time entry."""
    operation: Literal["create_time_entry"] = Field("create_time_entry", json_schema_extra={"ui:hidden": True})
    activity_name: Text
    entry_date: date
    rate: float = Field(..., ge=0, allow_inf_nan=False)
    hours: float = Field(..., gt=0, le=100000, allow_inf_nan=False)
    case_id: Identifier
    staff_id: Identifier
    description: Optional[Text] = None
    billable: Optional[StrictBool] = None
    flat_fee: Optional[StrictBool] = None


class MyCaseGetTimeEntry(_Input):
    """Get time entry."""
    operation: Literal["get_time_entry"] = Field("get_time_entry", json_schema_extra={"ui:hidden": True})
    time_entry_id: Identifier


class MyCaseListEvents(_Page):
    """List events."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})


class MyCaseCreateEvent(_Input):
    """Create event."""
    operation: Literal["create_event"] = Field("create_event", json_schema_extra={"ui:hidden": True})
    name: Text
    start: datetime
    end: datetime
    staff_ids: list[Identifier] = Field(..., min_length=1, max_length=100)
    description: Optional[Text] = None
    all_day: Optional[StrictBool] = None
    private: Optional[StrictBool] = None
    case_id: Optional[Identifier] = None
    location_id: Optional[Identifier] = None

    @model_validator(mode="after")
    def ordered_dates(self):
        try:
            ordered = self.end >= self.start
        except TypeError:
            raise ValueError("Start and end must use the same timezone convention") from None
        if not ordered:
            raise ValueError("End must be on or after start")
        return self


class MyCaseListInvoices(_Page):
    """List invoices."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})


class _MyCasePoll(PollTriggerConfigBase):
    model_config = ConfigDict(hide_input_in_errors=True)
    updated_after: Optional[datetime] = Field(None, title="Updated after", description="Optionally watch records created or updated on or after this time. Existing records are baselined when the trigger is armed.")


class MyCaseClientChanged(_MyCasePoll):
    """Poll the documented client list for new record versions."""
    operation: Literal["on_new_or_updated_client"] = Field("on_new_or_updated_client", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "New or Updated Client",
    })


class MyCaseLeadChanged(_MyCasePoll):
    """Poll the documented lead list for new record versions."""
    operation: Literal["on_new_or_updated_lead"] = Field("on_new_or_updated_lead", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "New or Updated Lead",
    })


class MyCaseCaseChanged(_MyCasePoll):
    """Poll the documented case list for new record versions."""
    operation: Literal["on_new_or_updated_case"] = Field("on_new_or_updated_case", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "New or Updated Case",
    })


class MyCaseTaskChanged(_MyCasePoll):
    """Poll the documented task list for new record versions."""
    operation: Literal["on_new_or_updated_task"] = Field("on_new_or_updated_task", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "New or Updated Task",
    })


MyCaseConfig = Annotated[Union[MyCaseClientChanged, MyCaseLeadChanged, MyCaseCaseChanged, MyCaseTaskChanged, MyCaseGetCurrentUser, MyCaseListClients, MyCaseGetClient, MyCaseCreateClient, MyCaseUpdateClient, MyCaseListLeads, MyCaseGetLead, MyCaseCreateLead, MyCaseUpdateLead, MyCaseListCases, MyCaseGetCase, MyCaseCreateCase, MyCaseUpdateCase, MyCaseListTasks, MyCaseCreateTask, MyCaseUpdateTask, MyCaseListCaseNotes, MyCaseCreateCaseNote, MyCaseGetNote, MyCaseListTimeEntries, MyCaseCreateTimeEntry, MyCaseGetTimeEntry, MyCaseListEvents, MyCaseCreateEvent, MyCaseListInvoices], Field(discriminator="operation")]


class MyCaseFullConfig(NodeConfig[MyCaseConfig, MyCaseOAuthCredential]):
    pass


OPERATIONS = {
    'get_current_user': ('GET', '/v1/me'),
    'list_clients': ('GET', '/v1/clients'),
    'get_client': ('GET', '/v1/clients/{client_id}'),
    'create_client': ('POST', '/v1/clients'),
    'update_client': ('PUT', '/v1/clients/{client_id}'),
    'list_leads': ('GET', '/v1/leads'),
    'get_lead': ('GET', '/v1/leads/{lead_id}'),
    'create_lead': ('POST', '/v1/leads'),
    'update_lead': ('PUT', '/v1/leads/{lead_id}'),
    'list_cases': ('GET', '/v1/cases'),
    'get_case': ('GET', '/v1/cases/{case_id}'),
    'create_case': ('POST', '/v1/cases'),
    'update_case': ('PUT', '/v1/cases/{case_id}'),
    'list_tasks': ('GET', '/v1/tasks'),
    'create_task': ('POST', '/v1/tasks'),
    'update_task': ('PUT', '/v1/tasks/{task_id}'),
    'list_case_notes': ('GET', '/v1/cases/{case_id}/notes'),
    'create_case_note': ('POST', '/v1/cases/{case_id}/notes'),
    'get_note': ('GET', '/v1/notes/{note_id}'),
    'list_time_entries': ('GET', '/v1/time_entries'),
    'create_time_entry': ('POST', '/v1/time_entries'),
    'get_time_entry': ('GET', '/v1/time_entries/{time_entry_id}'),
    'list_events': ('GET', '/v1/events'),
    'create_event': ('POST', '/v1/events'),
    'list_invoices': ('GET', '/v1/invoices'),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(str(key), secrets): _redact(item, secrets) for key, item in value.items()}
    return value


POLL_RESOURCES = {
    "on_new_or_updated_client": "clients",
    "on_new_or_updated_lead": "leads",
    "on_new_or_updated_case": "cases",
    "on_new_or_updated_task": "tasks",
}


class MyCaseNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-mycase"
    scope_registry = MYCASE_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_current_user", noun="account")

    @classmethod
    def get_config_model(cls):
        return MyCaseFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.mycase_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="mycase")

    @classmethod
    def resolve_agent_event(cls, output):
        resource = POLL_RESOURCES.get(output.get("operation"))
        if not resource:
            return super().resolve_agent_event(output)
        records = output.get("data") or []
        if not records:
            return None
        lines = [f"MyCase: {len(records)} new or updated {resource}."]
        for record in records[:50]:
            if resource in {"clients", "leads"}:
                name = " ".join(str(record.get(key) or "") for key in ("first_name", "last_name")).strip()
                detail = record.get("email") or ""
            else:
                name = record.get("name") or ""
                detail = record.get("description") or ""
            lines.append(f"{name} (ID {record['id']}, updated {record['updated_at']}): {detail}"[:2000])
        if len(records) > 50:
            lines.append("More changed records are available in the trigger output.")
        return {"text": "\n".join(lines)[:20000], "conversation_key": None}

    async def _poll_records(self, token, op):
        # The provider's FilterUpdatedAfter and response schemas document these fields.
        # Read all pages before recording seen versions: failed or oversized polls must retry intact.
        path = "/v1/" + POLL_RESOURCES[op.operation]
        params = {"page_size": 1000}
        if op.updated_after is not None:
            params["filter[updated_after]"] = op.updated_after.isoformat()
        records, tokens = [], set()
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            for _ in range(10):
                response = await client.get(BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
                response.raise_for_status()
                if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Expected bounded JSON from MyCase")
                page = response.json()
                if not isinstance(page, list) or any(
                    not isinstance(row, dict) or row.get("id") is None or not row.get("updated_at")
                    for row in page
                ):
                    raise ValueError("Expected MyCase records with IDs and update times")
                records.extend(page)
                if len(records) > 10000:
                    raise ValueError("MyCase poll exceeds 10,000 records; set Updated after to narrow the scope")
                cursor = self._next_page(response, path, params.get("page_token"))
                if cursor is None:
                    break
                if cursor in tokens:
                    raise ValueError("MyCase returned a repeated pagination token")
                tokens.add(cursor)
                params["page_token"] = cursor
            else:
                raise ValueError("MyCase poll exceeds ten pages; set Updated after to narrow the scope")
        fresh = await self._filter_unseen(records, lambda row: f"{row['id']}:{row['updated_at']}")
        return {"status": "success", "operation": op.operation, "data": fresh, "changed_count": len(fresh)}

    @staticmethod
    def _request_parts(op):
        method, path = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        params, body = {}, None
        if isinstance(op, _Page):
            for key, value in values.items():
                params[key if key in {"page_size", "page_token"} else "filter[" + key + "]"] = value
        elif method in {"POST", "PUT"}:
            body = {}
            for key, value in values.items():
                if key in {"case_id", "staff_id", "location_id", "referral_source_id"}:
                    body[{"case_id": "case", "staff_id": "staff", "location_id": "location", "referral_source_id": "referral_source_reference"}[key]] = {"id": value}
                elif key in {"client_ids", "company_ids", "case_ids", "staff_ids"}:
                    body[{"client_ids": "clients", "company_ids": "companies", "case_ids": "cases", "staff_ids": "staff"}[key]] = [{"id": identifier} for identifier in value]
                else:
                    body[key] = value
        return method, path, params, body

    @staticmethod
    def _next_page(response, path, previous):
        link = response.links.get("next", {}).get("url")
        if link is None:
            return None
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.netloc != "external-integrations.mycase.com" or parsed.path != path or parsed.fragment:
            raise ValueError("MyCase returned an unexpected pagination destination")
        tokens = parse_qs(parsed.query).get("page_token", [])
        if len(tokens) != 1 or not tokens[0] or len(tokens[0]) > 4096 or tokens[0] == previous:
            raise ValueError("MyCase did not provide an advancing page token")
        # Never follow a provider URL. Only the cursor returns to the fixed API origin.
        return tokens[0]

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a MyCase account")
        op, credential = self.config.config, self.config.credentials
        polling = isinstance(op, _MyCasePoll)
        method, path, params, body = ("GET", "", {}, None) if polling else self._request_parts(op)
        writing = method != "GET"
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.mycase_oauth import refresh_access_token
        raw = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=raw, refresh=refresh_access_token, provider="mycase", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in raw:
                setattr(credential, key, raw[key])
        secrets = (token, credential.access_token, credential.refresh_token)
        try:
            if polling:
                return _redact(await self._poll_records(token, op), secrets)
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                message = "MyCase rejected the request"
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        message = error.get("message") or error.get("error") or error.get("errors") or message
                except ValueError:
                    pass
                return _redact({"status": "error", "http_status": response.status_code, "error": message,
                    "write_outcome": "unverified" if writing and response.status_code >= 500 else None}, secrets)
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code}
            if response.status_code == 204:
                if not writing:
                    raise ValueError("Expected a MyCase JSON response")
                output["write_acknowledged"] = True
                return output
            if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
                raise ValueError("Expected bounded JSON from MyCase")
            payload = response.json()
            listing = op.operation.startswith("list_")
            if listing:
                if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                    raise ValueError("Expected a MyCase record list")
                cursor = self._next_page(response, path, getattr(op, "page_token", None))
                output.update(data=payload, next_page_token=cursor, has_more=cursor is not None)
            else:
                if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                    raise ValueError("Unexpected MyCase record response")
                if op.operation == "get_current_user" and (type(payload.get("id")) is not int or payload["id"] <= 0):
                    raise ValueError("MyCase did not identify the current account")
                output["data"] = payload
            if writing:
                output["write_acknowledged"] = True
            return _redact(output, secrets)
        except (httpx.HTTPError, ValueError, SSRFError):
            return {"status": "error", "operation": op.operation,
                "error": "MyCase request could not be verified; inspect the record before retrying" if writing else "MyCase read could not be verified",
                "write_outcome": "unverified" if writing else None}
