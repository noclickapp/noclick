"""Inmobalia CRM v1: personal-token actions and scheduled CRM change triggers.

Contract: https://api-crm.inmobalia.com/docs/api-docs (v1).
Each action makes one documented API operation; polling exhausts its scoped list
before changing deduplication state. Writes are never automatically retried.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api-crm.inmobalia.com"
DOCS_URL = "https://api-crm.inmobalia.com/docs/api-docs"


class InmobaliaCRMPersonalToken(BaseModel):
    model_config = ConfigDict(title="Inmobalia CRM Personal Access Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste your Inmobalia CRM Personal Access Token (PAT). It uses your CRM user's permissions. NoClick sends it as a bearer token only to api-crm.inmobalia.com. Include permission to read your current user for the connection check, plus the resources you automate.",
        })
    credential_type: Literal["inmobalia_crm_pat"] = Field("inmobalia_crm_pat", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, title="Personal access token",
                           json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the personal access token, without Bearer or whitespace")
        return value


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    contract_id: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


PAGE = ("page", "size", "sort")
DATES = ("fromDateCreated", "toDateCreated", "fromDateModified", "toDateModified")
CONTACT_FIELDS = ("name", "surname", "company", "email", "mobile", "telephone", "notes", "archived", "typeBuyer", "typeOwner")
ACTIVITY_FIELDS = ("type", "subject", "details", "responsible", "contactMain", "dateCompleted")

OPERATIONS = {
    "get_current_user": Operation("Get Current User", "Account", "GET", "/v1/users/me", "getCurrentUser"),
    "list_users": Operation("List Users", "Account", "GET", "/v1/users", "listUsers", query=("enabled",)),
    "list_activity_types": Operation("List Activity Types", "Activities", "GET", "/v1/activities/types", "getActivityTypes"),
    "list_contacts": Operation("List Contacts", "Contacts", "GET", "/v1/contacts", "listContacts", query=("email", "phone", "emailAndPhoneAsOr", "archived", *DATES, *PAGE)),
    "get_contact": Operation("Get Contact", "Contacts", "GET", "/v1/contacts/{contactId}", "getContactById", required=("contactId",)),
    "create_contact": Operation("Create Contact", "Contacts", "POST", "/v1/contacts", "createContact", body=CONTACT_FIELDS),
    "patch_contact": Operation("Edit Contact Fields", "Contacts", "PATCH", "/v1/contacts/{contactId}", "patchContact", required=("contactId",), body=CONTACT_FIELDS),
    "list_web_leads": Operation("List Web Leads", "Web Leads", "GET", "/v1/web-leads", "listWebLeads", query=("status", "fromDate", "toDate", *PAGE)),
    "get_web_lead": Operation("Get Web Lead", "Web Leads", "GET", "/v1/web-leads/{webLeadId}", "getWebLeadById", required=("webLeadId",)),
    "create_web_lead": Operation("Create Web Lead", "Web Leads", "POST", "/v1/web-leads", "createWebLead", required=("source",), body=("source", "name", "email", "phone", "comments", "properties", "contact")),
    "process_web_lead": Operation("Process Web Lead", "Web Leads", "PUT", "/v1/web-leads/{webLeadId}/processed", "processWebLead", required=("webLeadId", "contact"), body=("contact",)),
    "list_properties": Operation("List Properties", "Properties", "GET", "/v1/properties", "listProperties", query=(*DATES, "countryIso", "statusPublish", *PAGE)),
    "get_property": Operation("Get Property", "Properties", "GET", "/v1/properties/{propertyId}", "getPropertyById", required=("propertyId",)),
    "list_enquiries": Operation("List Enquiries", "Enquiries", "GET", "/v1/enquiries", "listEnquiries", query=(*DATES, "status", "transactionType", *PAGE)),
    "get_enquiry": Operation("Get Enquiry", "Enquiries", "GET", "/v1/enquiries/{enquiryId}", "getEnquiryById", required=("enquiryId",)),
    "list_activity_tasks": Operation("List Activity Tasks", "Activities", "GET", "/v1/activities/task", "listActivityTasks", query=(*DATES, "type", *PAGE)),
    "get_activity_task": Operation("Get Activity Task", "Activities", "GET", "/v1/activities/task/{activityTaskId}", "getActivityTaskById", required=("activityTaskId",)),
    "create_activity_task": Operation("Create Activity Task", "Activities", "POST", "/v1/activities/task", "createActivityTask", required=("type", "subject", "dateCompleted", "status"), body=(*ACTIVITY_FIELDS, "status")),
    "list_activity_logs": Operation("List Activity Logs", "Activities", "GET", "/v1/activities/log", "listActivityLogs", query=(*DATES, "type", *PAGE)),
    "create_activity_log": Operation("Create Activity Log", "Activities", "POST", "/v1/activities/log", "createActivityLog", required=("type", "subject"), body=ACTIVITY_FIELDS),
}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def constraints(self):
        values = self.model_dump(exclude_none=True)
        op = values["operation"]
        if op == "create_contact" and not any(values.get(k, "").strip() for k in ("name", "surname", "company")):
            raise ValueError("Provide a contact name, surname or company")
        if op == "patch_contact" and not any(k in values for k in CONTACT_FIELDS):
            raise ValueError("Provide at least one contact field to edit")
        for prefix in ("DateCreated", "DateModified", "Date"):
            low, high = getattr(self, "from" + prefix, None), getattr(self, "to" + prefix, None)
            if low is not None and high is not None and low > high:
                raise ValueError("The end of a date range must be at or after its start")
        if op == "create_activity_log" and self.dateCompleted is not None and self.dateCompleted > datetime.now(timezone.utc):
            raise ValueError("An activity log completion date cannot be in the future")
        if op == "create_web_lead" and any(not ref or any(c.isspace() for c in ref) for ref in (self.properties or [])):
            raise ValueError("Property references cannot contain whitespace")
        return self


def _field(name, spec):
    required = name in spec.required
    typ: Any = str
    kwargs: dict[str, Any] = {}
    default: Any = ... if required else None
    if name in {"contactId", "webLeadId", "propertyId", "enquiryId", "activityTaskId", "contact", "contactMain"}:
        typ, kwargs = int, {"ge": 1, "le": 2147483647}
    elif name == "page":
        typ, default, kwargs = int, 0, {"ge": 0, "le": 1000000}
    elif name == "size":
        typ, default, kwargs = int, 20, {"ge": 1, "le": 500}
    elif name in {"archived", "typeBuyer", "typeOwner", "emailAndPhoneAsOr", "enabled"}:
        typ = bool
    elif name.startswith(("fromDate", "toDate")) or name == "dateCompleted":
        typ = AwareDatetime
    elif name in {"sort", "properties", "statusPublish"} or (name == "type" and spec.method == "GET"):
        typ, kwargs = list[str], {"max_length": 100}
    elif name == "status":
        if spec.contract_id == "listEnquiries":
            typ = list[Literal["ACTIVE", "LOST", "WON"]]
        else:
            typ = Literal["PENDING", "COMPLETED"] if spec.contract_id == "createActivityTask" else Literal["PENDING", "PROCESSED"]
    elif name == "transactionType":
        typ = Literal["SALE", "RENT_SHORTTERM", "RENT_LONGTERM"]
    else:
        kwargs = {"min_length": 1, "max_length": {"notes": 25000, "details": 25000, "comments": 25000, "type": 45, "mobile": 50, "telephone": 50}.get(name, 255)}
        if name == "type":
            kwargs.update(min_length=2, pattern='^[^"\'<>&\\s][^"\'<>&\\r\\n]*[^"\'<>&\\s]$')
        if name == "email":
            kwargs["pattern"] = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
        elif name == "source":
            kwargs.update(max_length=4096, pattern=r"^https?://[^\s]+$")
        elif name in {"mobile", "telephone"}:
            kwargs["pattern"] = r"^\+[1-9][0-9]{1,14}$"
        elif name == "countryIso":
            kwargs["pattern"] = r"^[A-Z]{2}$"
    description = None
    if name == "dateCompleted":
        description = "UTC due/completion time. For an activity log this cannot be in the future."
    if name == "type":
        description = "An agency activity type from List Activity Types."
    if name == "sort":
        description = "Sort criteria such as dateCreated,asc. Multiple criteria are sent as repeated sort parameters."
    if name == "properties":
        description = "Property references of interest, such as P12345."
    if name == "comments":
        description = "The lead's message."
    return (typ if required or default is not None else Optional[typ],
            Field(default, title=name.replace("Id", " ID"), description=description, **kwargs))


def _make_config(name, spec):
    fields = {key: _field(key, spec) for key in sorted(set(spec.required + spec.query + spec.body))}
    return create_model("InmobaliaCRM" + "".join(p.title() for p in name.split("_")) + "Config",
        __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, json_schema_extra={
            "ui:hidden": True, "x-display-name": spec.label, "x-category": spec.category,
            "x-is-trigger": False, "x-contract-operation": spec.contract_id})), **fields)


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class OnNewWebLead(PollTriggerConfigBase):
    operation: Literal["on_new_web_lead"] = Field("on_new_web_lead", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New Web Lead", "x-category": "Triggers", "x-is-trigger": True})
    fromDate: Optional[AwareDatetime] = Field(None, title="Received since (UTC)", description="Optional inclusive lower bound for the watched history. Existing leads are baselined when armed.")


class OnNewOrUpdatedContact(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_contact"] = Field("on_new_or_updated_contact", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New or Updated Contact", "x-category": "Triggers", "x-is-trigger": True})
    fromDateModified: Optional[AwareDatetime] = Field(None, title="Modified since (UTC)", description="Optional inclusive lower bound; existing versions are baselined when armed.")


class OnNewOrUpdatedProperty(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_property"] = Field("on_new_or_updated_property", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New or Updated Property", "x-category": "Triggers", "x-is-trigger": True})
    fromDateModified: Optional[AwareDatetime] = Field(None, title="Modified since (UTC)", description="Optional inclusive lower bound; existing versions are baselined when armed.")


TRIGGERS = {
    "on_new_web_lead": ("/v1/web-leads", "date", "fromDate", "web lead"),
    "on_new_or_updated_contact": ("/v1/contacts", "dateModified", "fromDateModified", "contact"),
    "on_new_or_updated_property": ("/v1/properties", "dateModified", "fromDateModified", "property"),
}
InmobaliaCRMOperation = Annotated[Union[tuple(CONFIG_MODELS.values()) +
    (OnNewWebLead, OnNewOrUpdatedContact, OnNewOrUpdatedProperty)], Field(discriminator="operation")]


class InmobaliaCRMNodeConfig(NodeConfig[InmobaliaCRMOperation, InmobaliaCRMPersonalToken]):
    pass


class InmobaliaCRMNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-inmobalia-crm"
    connection_evidence = ConnectionEvidence(noun="current user", identity_operation="get_current_user", identity_keys=("name", "surname", "email"))
    edit_examples = ["Create a contact from a web form", "Watch for new web leads", "Create a follow-up activity task", "Find properties modified this week"]

    @classmethod
    def get_config_model(cls):
        return InmobaliaCRMNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        token = self.config.credentials.api_token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json-patch+json" if method == "PATCH" else "application/json"
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            try:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, json=body)
            except httpx.RequestError:
                raise ValueError("Inmobalia CRM could not be reached; a write may have completed. Inspect the CRM before retrying a write.") from None
        if response.status_code >= 300:
            detail = response.text.replace(token, "[redacted]")[:2000]
            retry = response.headers.get("Retry-After")
            raise ValueError(f"Inmobalia CRM HTTP {response.status_code}: {detail}" + (f"; Retry-After: {retry}" if retry else ""))
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Inmobalia CRM returned a non-JSON response") from None
        return data

    @staticmethod
    def _page(data, page, size):
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise ValueError("Inmobalia CRM returned no collection content")
        rows = data["content"]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("Inmobalia CRM returned an invalid collection item")
        total = data.get("totalPages")
        if total is not None:
            if type(total) is not int or total < 0:
                raise ValueError("Inmobalia CRM returned invalid totalPages")
            next_page = page + 1 if page + 1 < total else None
        else:
            # Without a total, a short page is terminal; a full page needs one more read.
            next_page = page + 1 if len(rows) >= size else None
        return rows, next_page

    async def _poll(self, config):
        path, date_field, lower_bound, noun = TRIGGERS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        params = {"size": 500, "sort": [date_field + ",asc", "id,asc"]}
        if lower_bound in values:
            params[lower_bound] = values[lower_bound]
        items, identities = [], set()
        page = 0
        for _ in range(20):
            data = await self._request("GET", path, params={**params, "page": page})
            rows, following = self._page(data, page, 500)
            for row in rows:
                identifier = row.get("id")
                stamp = row.get(date_field)
                if type(identifier) is not int or not isinstance(stamp, str) or not stamp:
                    raise ValueError("Inmobalia CRM poll item has no documented ID or timestamp")
                key = str(identifier) if config.operation == "on_new_web_lead" else f"{identifier}:{stamp}"
                if key not in identities:
                    identities.add(key)
                    items.append(row)
            if following is None:
                break
            if not rows:
                raise ValueError("Inmobalia CRM returned an empty nonterminal poll page")
            page = following
        else:
            raise ValueError("More than 10000 CRM records in this poll scope; set a later date lower bound")
        fresh = await self._filter_unseen(items, lambda row: str(row["id"]) if config.operation == "on_new_web_lead" else f"{row['id']}:{row[date_field]}")
        return {"operation": config.operation, "event_type": noun, "items": fresh, "count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Inmobalia CRM personal access token")
        config = self.config.config
        if config.operation in TRIGGERS:
            return await self._poll(config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = spec.path
        for name in spec.required:
            path = path.replace("{" + name + "}", str(values[name]))
        params = {key: values[key] for key in spec.query if key in values}
        body = {key: values[key] for key in spec.body if key in values} if spec.body else None
        if spec.method == "PATCH":
            body = [{"op": "add", "path": "/" + key, "value": value} for key, value in body.items()]
        data = await self._request(spec.method, path, params=params or None, body=body)
        output = {"data": data, "operation": config.operation}
        if "page" in spec.query:
            _, following = self._page(data, values["page"], values["size"])
            output["next_page"] = following
        return output

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in TRIGGERS:
            return super().resolve_agent_event(output)
        items = output.get("items")
        if not items:
            return None
        operation = output["operation"]
        noun = TRIGGERS[operation][3]
        lines = []
        for row in items[:10]:
            if operation == "on_new_web_lead":
                lines.append(f"- Web lead {row['id']} from {row.get('name') or row.get('email') or 'website visitor'} at {row.get('source')}: {row.get('comments') or '(no message)'}; contact {row.get('contact')}; properties {row.get('properties')}")
            elif operation == "on_new_or_updated_contact":
                name = " ".join(str(row.get(k) or '') for k in ('name', 'surname')).strip()
                lines.append(f"- Contact {row['id']}: {name or row.get('company') or row.get('email') or 'unnamed contact'}; email {row.get('email')}; changed by {row.get('modifiedBy')} at {row.get('dateModified')}")
            else:
                lines.append(f"- Property {row['id']} ({row.get('reference')}), {row.get('country')}, city {row.get('city')}; publication {row.get('statusPublish')}; changed by {row.get('modifiedBy')} at {row.get('dateModified')}")
        if len(items) > 10:
            lines.append(f"- and {len(items) - 10} more (all IDs and records are in items)")
        return {"text": f"Inmobalia CRM: {len(items)} new or updated {noun}(s):\n" + "\n".join(lines), "conversation_key": None}
