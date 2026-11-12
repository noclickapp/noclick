"""Custify customer-success operations from the published OpenAPI 1.6.0 contract.

Poll triggers use the documented task/ticket list shapes and time ordering.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class CustifyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Custify API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.custify.com/settings/developer/api-key",
        "x-credential-instructions": "Copy your API key and API URL from Custify Settings → Developers → API Key. The key grants read and write access. Paste only the key, without Bearer.",
    })
    credential_type: Literal["custify_api_key"] = Field("custify_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False,
                         json_schema_extra={"ui:widget": "password"})
    api_url: str = Field("https://api.custify.com", title="API URL",
                         description="The HTTPS API origin shown beside your key in Custify.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a header or whitespace")
        return value

    @field_validator("api_url", mode="before")
    @classmethod
    def origin(cls, value):
        return normalize_provider_https_origin(value, "custify.com", field_name="API URL", allow_nested_labels=True)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1)
    itemsPerPage: int = Field(20, ge=1, le=50, title="Items per page",
                              description="Read one page; increment page to continue.")


class _CustomerList(_Page):
    sorting: dict[str, Any] | None = Field(None, description='For example {"field":"updated_at","direction":"desc"}.')
    filters: list[dict[str, Any]] | None = Field(None, description="Custify fieldName/fieldType/filterType/filterValue filters.")
    properties: list[str] | None = None
    includeSegments: bool | None = None


class _ID(_Input):
    id: str = Field(..., min_length=1, max_length=256, title="Custify ID")


class _Person(_Input):
    user_id: str = Field(..., min_length=1, title="External person ID",
                         description="Stable ID in your system. Custify creates or updates the matching person.")
    email: str | None = None
    name: str | None = None
    phone: str | None = None
    signed_up_at: AwareDatetime | None = None
    session_count: int | None = Field(None, ge=0)
    companies: list[dict[str, Any]] | None = None
    custom_attributes: dict[str, Any] | None = None
    unsubscribed_from_emails: bool | None = None
    unsubscribed_from_calls: bool | None = None


class _Company(_Input):
    company_id: str = Field(..., min_length=1, title="External company ID")
    name: str | None = None
    signed_up_at: AwareDatetime | None = None
    size: int | None = Field(None, ge=0)
    website: str | None = None
    industry: str | None = None
    plan: str | None = None
    monthly_revenue: int | None = None
    churned: bool | None = None
    owners_csm: str | None = None
    owners_account: str | None = None
    parent_companies: list[dict[str, Any]] | None = None
    custom_attributes: dict[str, Any] | None = None


class _TaskList(_Page):
    sorting: dict[str, Any] | None = None
    filters: list[dict[str, Any]] | None = None
    substatus: str | None = None


class _TaskFields(_Input):
    description: str | None = None
    company_id: str | None = Field(None, title="External company ID")
    company: str | None = Field(None, title="Custify company ID")
    people: str | None = None
    user_id: str | None = None
    assignedTo: str | None = Field(None, title="Assignee ID or email")
    dueDate: AwareDatetime | None = None
    substatus: str | None = None
    externalId: str | None = None
    showInPortal: bool | None = None
    tags: list[str] | None = None


class _CreateTask(_TaskFields):
    name: str = Field(..., min_length=1)
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["open", "done", "not relevant"] = "open"

    @model_validator(mode="after")
    def account(self):
        if not (self.company or self.company_id):
            raise ValueError("Provide a Custify company ID or an external company ID")
        return self


class _UpdateTask(_TaskFields, _ID):
    name: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    status: Literal["open", "done", "not relevant"] | None = None
    substatusNote: str | None = Field(None, max_length=200)


class _TicketList(_Page):
    sort: str = "openedAt"
    order: Literal["asc", "desc"] = "desc"
    filters: list[dict[str, Any]] | None = None
    searchTerm: str | None = None
    externalId: str | None = None


class _CreateTicket(_Input):
    externalId: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1, title="External company ID")
    description: str | None = None
    ticketStatus: str = "open"
    priority: str | None = None
    openedAt: AwareDatetime | None = None
    lastModifiedAt: AwareDatetime | None = None
    assignedToName: str | None = None
    people: str | None = None


class _Event(_Input):
    name: str = Field(..., min_length=1)
    created_at: AwareDatetime = Field(..., description="ISO 8601 time when the event occurred.")
    user_id: str | None = None
    email: str | None = None
    company_id: str | None = None
    deduplication_id: str | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def subject(self):
        if not (self.user_id or self.email or self.company_id):
            raise ValueError("Provide a person ID, email, or company ID")
        return self


class _TagPeople(_Input):
    ids: list[str] = Field(..., min_length=1, title="Custify person IDs")
    tag: str = Field(..., min_length=1, title="Custify tag ID")
    type: Literal["add", "remove"] = "add"


class _SurveyResponses(_Page, _ID):
    pass


class _SortedPage(_Page):
    sorting: dict[str, Any] | None = None


class _TypedPage(_SortedPage):
    type: Literal["company", "people"] = "company"


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    model: type[BaseModel]
    category: str


OPERATIONS = {
    "list_people": Operation("GET", "/people/all", _CustomerList, "People"),
    "get_person": Operation("GET", "/people/{id}", _ID, "People"),
    "upsert_person": Operation("POST", "/people", _Person, "People"),
    "list_companies": Operation("GET", "/company/all", _CustomerList, "Companies"),
    "get_company": Operation("GET", "/company/{id}", _ID, "Companies"),
    "upsert_company": Operation("POST", "/company", _Company, "Companies"),
    "list_company_people": Operation("GET", "/company/people/{id}", _ID, "Companies"),
    "list_tasks": Operation("GET", "/task", _TaskList, "Tasks"),
    "get_task": Operation("GET", "/task/{id}", _ID, "Tasks"),
    "create_task": Operation("POST", "/task", _CreateTask, "Tasks"),
    "update_task": Operation("PUT", "/task/{id}", _UpdateTask, "Tasks"),
    "list_task_filter_values": Operation("GET", "/task/filtersAvailableValues", _Input, "Tasks"),
    "list_tickets": Operation("GET", "/ticket", _TicketList, "Tickets"),
    "create_ticket": Operation("POST", "/ticket", _CreateTicket, "Tickets"),
    "insert_event": Operation("POST", "/event", _Event, "Events"),
    "tag_people": Operation("POST", "/people/tag", _TagPeople, "People"),
    "list_surveys": Operation("GET", "/survey", _Page, "Surveys"),
    "get_survey_responses": Operation("GET", "/survey/{id}/responses", _SurveyResponses, "Surveys"),
    "list_health_scores": Operation("GET", "/health_score", _SortedPage, "Health"),
    "list_calculated_metrics": Operation("GET", "/calculated_metric", _TypedPage, "Health"),
    "list_segments": Operation("GET", "/segment", _TypedPage, "Segments"),
}


def _operation_model(name, spec):
    label = name.replace("_", " ").title()
    return create_model("Custify" + label.replace(" ", "") + "Config", __base__=spec.model,
                        __module__=__name__, operation=(Literal[name], Field(name, title=label,
                        json_schema_extra={"ui:hidden": True, "x-display-name": label,
                                           "x-category": spec.category, "x-is-trigger": False})))


CONFIG_MODELS = {name: _operation_model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class CustifyOnTaskUpdatedConfig(PollTriggerConfigBase):
    operation: Literal["on_task_updated"] = Field("on_task_updated", title="On New or Updated Task", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New or Updated Task", "x-category": "Triggers", "x-is-trigger": True,
    })


class CustifyOnNewTicketConfig(PollTriggerConfigBase):
    operation: Literal["on_new_ticket"] = Field("on_new_ticket", title="On New Ticket", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New Ticket", "x-category": "Triggers", "x-is-trigger": True,
    })


CustifyOperation = Annotated[Union[tuple(CONFIG_MODELS.values()) + (CustifyOnTaskUpdatedConfig, CustifyOnNewTicketConfig)], Field(discriminator="operation")]


class CustifyNodeConfig(NodeConfig[CustifyOperation, CustifyAPIKeyCredential]):
    pass


class CustifyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-custify"
    connection_evidence = ConnectionEvidence(operation="list_tasks", noun="tasks", label_keys=("name", "id"))
    edit_examples = ["Create a follow-up task for this customer", "Update a company's plan and revenue", "Track a customer login event"]

    @classmethod
    def get_config_model(cls):
        return CustifyNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.api_url + path, params=params, json=body,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            detail = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"Custify API error {response.status_code}: {detail}")
        return response.json() if response.content else {}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Custify API key")
        op = self.config.config
        credential = self.config.credentials
        if isinstance(op, (CustifyOnTaskUpdatedConfig, CustifyOnNewTicketConfig)):
            return await self._poll(credential, op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec.path
        if "{id}" in path:
            identifier = values.pop("id")
            path = path.replace("{id}", quote(identifier, safe=""))
            if op.operation == "update_task":
                values["_id"] = identifier
        params, body = None, None
        if spec.method == "GET":
            params = {key: json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list))
                      else str(value).lower() if isinstance(value, bool) else value for key, value in values.items()}
        else:
            body = values
        data = await self._request(credential, spec.method, path, params=params, body=body)
        # Keep the API envelope for ordinary operations; evidence expects account-owned rows.
        if op.operation == "list_tasks":
            if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
                raise ValueError("Custify returned an invalid task list")
            return {"status": "success", "data": data["tasks"], "total": data.get("total"), "page": op.page}
        return {"status": "success", "data": data}

    async def _poll(self, credential, operation):
        task = operation == "on_task_updated"
        path, key = ("/task", "tasks") if task else ("/ticket", "tickets")
        rows = []
        # Read every page or fail without advancing dedup state; never silently truncate a scope.
        for page in range(1, 101):
            # Every page is read, so the task poll needs no sort order.
            params = {"itemsPerPage": 50, "page": page, **({} if task else {"sort": "openedAt", "order": "desc"})}
            data = await self._request(credential, "GET", path, params=params)
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise ValueError("Custify returned an invalid poll list")
            batch = data[key]
            for row in batch:
                if not isinstance(row, dict) or not row.get("id") or (task and not row.get("updated_at")):
                    raise ValueError("Custify poll item is missing its ID or update time")
            rows.extend(batch)
            total = data.get("total")
            if type(total) is not int or total < 0:
                raise ValueError("Custify poll list is missing its total")
            if len(rows) >= total:
                break
            if not batch:
                raise ValueError("Custify returned an incomplete poll list")
        else:
            raise ValueError("Custify poll scope exceeds 5,000 items")
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]) + ":" + str(row["updated_at"]) if task else str(row["id"]))
        return {"status": "success", "operation": operation, "items": fresh, "new_item_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_item_count")) if config.get("operation") in {"on_task_updated", "on_new_ticket"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") not in {"on_task_updated", "on_new_ticket"}:
            return super().resolve_agent_event(output)
        rows = output.get("items")
        if not isinstance(rows, list) or not rows:
            return None
        task = output["operation"] == "on_task_updated"
        lines = []
        for row in rows[:10]:
            if task:
                lines.append(f"Task {row.get('name')} (id {row.get('id')}) for company {row.get('company')}; "
                             f"assignee {row.get('assignedToName')}; status {row.get('status')}; {row.get('description')}")
            else:
                lines.append(f"Ticket {row.get('title')} (id {row.get('id')}, external {row.get('externalId')}) "
                             f"for companies {row.get('company')}, people {row.get('peopleNames')}; "
                             f"status {row.get('ticketStatus')}; {row.get('description')}")
        return {"text": f"Custify: {len(rows)} {'new or updated tasks' if task else 'new tickets'}\n" + "\n".join(lines),
                "conversation_key": None}
